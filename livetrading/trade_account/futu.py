from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pandas as pd

from ..config import TradeAccountConfig
from ..futu.runtime import _load_futu_api
from ..models import AccountSnapshot, FillEvent, OrderIntent, OrderSubmission, OrderUpdate, PositionSnapshot
from .base import TradeAccountClient, TradeAccountEventSink


class FutuTradeAccountClient(TradeAccountClient):
    """Futu 交易账户客户端，负责把统一账户接口映射到 Futu SDK。

    它的职责有三块：建立/关闭交易上下文、轮询账户与持仓快照、把订单与成交推送转换成统一模型。
    """

    def __init__(self, config: TradeAccountConfig, event_sink: TradeAccountEventSink, logger: logging.Logger) -> None:
        self._config = config
        self._event_sink = event_sink
        self._logger = logger
        self._trade_ctx = None
        self._futu = None
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def connect(self) -> None:
        """建立 Futu 交易连接，并启动后台轮询线程。

        连接建立后会立刻主动拉一次账户和持仓快照，
        这样引擎在启动后不需要等第一轮轮询周期结束才能拿到基线状态。
        """
        self.close()
        with self._lock:
            self._poll_stop = threading.Event()
            self._futu = _load_futu_api()
            self._trade_ctx = self._futu["OpenSecTradeContext"](
                filter_trdmarket=self._futu["TrdMarket"].US,
                host=self._config.broker.host,
                port=self._config.broker.port,
            )
            self._trade_ctx.set_handler(self._build_trade_order_handler())
            self._trade_ctx.set_handler(self._build_trade_deal_handler())
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name=f"futu-account-poller-{self._config.account_id}",
                daemon=True,
            )
            trade_ctx = self._trade_ctx
            poll_thread = self._poll_thread
        trade_ctx.start()
        poll_thread.start()
        self._poll_account()
        self._poll_positions()

    def close(self) -> None:
        """关闭当前交易上下文和轮询线程。

        这里会先把内部引用摘掉，再在锁外等待线程退出并关闭 trade context，
        避免 join/close 过程和其他持锁逻辑互相阻塞。
        """
        with self._lock:
            poll_stop = self._poll_stop
            poll_thread = self._poll_thread
            self._poll_thread = None
            trade_ctx = self._trade_ctx
            self._trade_ctx = None
            self._futu = None
        poll_stop.set()
        if poll_thread is not None and poll_thread.is_alive():
            poll_thread.join(timeout=3.0)
        if trade_ctx is not None:
            try:
                trade_ctx.close()
            except Exception as exc:
                self._event_sink.on_broker_message(
                    logging.WARNING,
                    f"account={self._config.account_id} trade context close failed: {exc}",
                )

    def submit_order(self, intent: OrderIntent) -> OrderSubmission:
        """把统一的 OrderIntent 翻译成一次 Futu `place_order` 调用。

        返回值会尽量保留 broker ack 中的 order_id、数量、价格，
        让上层能够把“本地下单意图”和“broker 订单编号”稳定串起来。
        """
        with self._lock:
            trade_ctx = self._trade_ctx
            futu = self._futu
            if trade_ctx is None or futu is None:
                return OrderSubmission(
                    account_id=self._config.account_id,
                    broker_order_id=None,
                    accepted=False,
                    message="trade context is not connected",
                    submitted_qty=intent.qty,
                    submitted_price=intent.limit_price,
                )
            ret, data = trade_ctx.place_order(
                price=float(intent.limit_price),
                qty=int(intent.qty),
                code=intent.code,
                trd_side=self._resolve_trd_side(intent.side, futu),
                order_type=futu["OrderType"].NORMAL,
                trd_env=self._resolve_trade_env(futu),
                acc_index=self._config.broker.account_index,
                fill_outside_rth=self._resolve_fill_outside_rth(),
                session=self._resolve_order_session(futu),
            )
        if ret != futu["RET_OK"]:
            return OrderSubmission(
                account_id=self._config.account_id,
                broker_order_id=None,
                accepted=False,
                message=str(data),
                submitted_qty=intent.qty,
                submitted_price=intent.limit_price,
            )

        # submit ack 里会带回 Futu 的 order_id，后续 ORDER_PUSH / DEAL_PUSH 也靠它串起来。
        row = _first_row_dict(data)
        return OrderSubmission(
            account_id=self._config.account_id,
            broker_order_id=_coerce_optional_str(row.get("order_id")) if row is not None else None,
            accepted=True,
            message=_coerce_optional_str(row.get("remark")) if row is not None else None,
            submitted_qty=int(_coerce_optional_float(row.get("qty")) or intent.qty) if row is not None else intent.qty,
            submitted_price=float(_coerce_optional_float(row.get("price")) or intent.limit_price) if row is not None else intent.limit_price,
            raw=row or {},
        )

    def _build_trade_order_handler(self):
        """构建 Futu 订单状态推送处理器，并转换成统一的 OrderUpdate 事件。

        这里不直接改账户状态，而是把原始推送标准化后交给 engine/state store，
        保持 broker 适配层和状态推进层职责分离。
        """
        futu = self._futu
        broker = self

        class TradeOrderHandler(futu["TradeOrderHandlerBase"]):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code != futu["RET_OK"]:
                    broker._event_sink.on_broker_message(
                        logging.ERROR,
                        f"account={broker._config.account_id} order push error: {content}",
                    )
                    return ret_code, content
                if not content.empty:
                    for _, row in content.iterrows():
                        update = OrderUpdate(
                            account_id=broker._config.account_id,
                            broker_order_id=_coerce_optional_str(row.get("order_id")) or "UNKNOWN",
                            code=_coerce_optional_str(row.get("code")),
                            side=_coerce_optional_str(row.get("trd_side")),
                            status=_coerce_optional_str(row.get("order_status")),
                            dealt_qty=int(_coerce_optional_float(row.get("dealt_qty")) or 0),
                            avg_price=_coerce_optional_float(row.get("dealt_avg_price")),
                            raw=row.to_dict(),
                        )
                        broker._event_sink.on_order_update(broker._config.account_id, update)
                        broker._event_sink.on_broker_message(
                            logging.INFO,
                            "ORDER_PUSH "
                            f"account={broker._config.account_id} code={row.get('code')} status={row.get('order_status')} "
                            f"dealt_qty={row.get('dealt_qty')} avg_price={row.get('dealt_avg_price')} side={row.get('trd_side')}",
                        )
                return ret_code, content

        return TradeOrderHandler()

    def _build_trade_deal_handler(self):
        """构建 Futu 成交推送处理器，并转换成统一的 FillEvent 事件。

        成交推送和订单状态推送是两条独立链路，这里专门负责把成交明细补充给上层，
        方便 expected 现金在订单最终结算时使用真实成交额纠偏。
        """
        futu = self._futu
        broker = self

        class TradeDealHandler(futu["TradeDealHandlerBase"]):
            def on_recv_rsp(self, rsp_pb):
                ret_code, content = super().on_recv_rsp(rsp_pb)
                if ret_code != futu["RET_OK"]:
                    broker._event_sink.on_broker_message(
                        logging.ERROR,
                        f"account={broker._config.account_id} deal push error: {content}",
                    )
                    return ret_code, content
                if not content.empty:
                    for _, row in content.iterrows():
                        fill = FillEvent(
                            account_id=broker._config.account_id,
                            broker_order_id=_coerce_optional_str(row.get("order_id")) or "UNKNOWN",
                            code=_coerce_optional_str(row.get("code")),
                            side=_coerce_optional_str(row.get("trd_side")),
                            fill_qty=int(_coerce_optional_float(row.get("qty")) or 0),
                            fill_price=_coerce_optional_float(row.get("price")),
                            raw=row.to_dict(),
                        )
                        broker._event_sink.on_fill(broker._config.account_id, fill)
                        broker._event_sink.on_broker_message(
                            logging.INFO,
                            "DEAL_PUSH "
                            f"account={broker._config.account_id} code={row.get('code')} qty={row.get('qty')} "
                            f"price={row.get('price')} side={row.get('trd_side')}",
                        )
                return ret_code, content

        return TradeDealHandler()

    def _poll_loop(self) -> None:
        """后台轮询循环，按各自节奏定期刷新账户资金和持仓快照。"""
        next_account_poll = 0.0
        next_position_poll = 0.0
        while not self._poll_stop.wait(0.5):
            now = time.monotonic()
            if now >= next_account_poll:
                self._poll_account()
                next_account_poll = now + self._config.broker.account_poll_interval_seconds
            if now >= next_position_poll:
                self._poll_positions()
                next_position_poll = now + self._config.broker.position_poll_interval_seconds

    def _poll_account(self) -> None:
        """主动拉取一次账户资金快照，并回调给事件接收方。

        轮询接口失败时不会抛异常中断线程，而是记录 broker 消息，
        让实盘链路在短暂网络抖动下仍能继续运行。
        """
        with self._lock:
            trade_ctx = self._trade_ctx
            futu = self._futu
            if trade_ctx is None or futu is None:
                return
            ret, data = trade_ctx.accinfo_query(
                trd_env=self._resolve_trade_env(futu),
                acc_index=self._config.broker.account_index,
                currency=futu["Currency"].USD,
            )
        if ret != futu["RET_OK"]:
            self._event_sink.on_broker_message(
                logging.WARNING,
                f"account={self._config.account_id} accinfo_query failed: {data}",
            )
            return
        if data.empty:
            return
        row = data.iloc[0]
        snapshot = AccountSnapshot(
            timestamp=pd.Timestamp.now(tz="UTC"),
            total_assets=_coerce_optional_float(row.get("total_assets")),
            cash=_coerce_optional_float(row.get("cash")),
            available_funds=_coerce_optional_float(row.get("available_funds")),
            buying_power=_coerce_optional_float(row.get("power")),
            currency=_coerce_optional_str(row.get("currency")) or "USD",
            raw=row.to_dict(),
        )
        self._event_sink.on_account(self._config.account_id, snapshot)

    def _poll_positions(self) -> None:
        """主动拉取一次当前持仓快照，并标准化成统一的 PositionSnapshot。"""
        with self._lock:
            trade_ctx = self._trade_ctx
            futu = self._futu
            if trade_ctx is None or futu is None:
                return
            ret, data = trade_ctx.position_list_query(
                trd_env=self._resolve_trade_env(futu),
                acc_index=self._config.broker.account_index,
                refresh_cache=True,
            )
        if ret != futu["RET_OK"]:
            self._event_sink.on_broker_message(
                logging.WARNING,
                f"account={self._config.account_id} position_list_query failed: {data}",
            )
            return
        positions: dict[str, PositionSnapshot] = {}
        for row in data.itertuples(index=False):
            positions[str(row.code)] = PositionSnapshot(
                code=str(row.code),
                qty=int(_coerce_optional_float(row.qty) or 0),
                can_sell_qty=int(_coerce_optional_float(row.can_sell_qty) or 0),
                average_cost=_coerce_optional_float(row.average_cost),
                market_val=_coerce_optional_float(row.market_val),
                unrealized_pl=_coerce_optional_float(row.unrealized_pl),
                realized_pl=_coerce_optional_float(row.realized_pl),
                currency=_coerce_optional_str(row.currency) or "USD",
                raw=row._asdict(),
            )
        self._event_sink.on_positions(self._config.account_id, positions)

    def _resolve_trade_env(self, futu):
        """把配置里的字符串环境映射成 Futu SDK 枚举。"""
        if self._config.broker.trade_env == "SIMULATE":
            return futu["TrdEnv"].SIMULATE
        return futu["TrdEnv"].REAL

    def _resolve_fill_outside_rth(self) -> bool:
        """扩展时段订单需要显式打开 fill_outside_rth。"""
        return self._config.execution.order_session != "RTH"

    def _resolve_order_session(self, futu):
        """把 execution.order_session 映射成 Futu SDK 的时段枚举。"""
        return getattr(futu["Session"], self._config.execution.order_session)

    def _resolve_trd_side(self, side: str, futu):
        """把统一 side 字段映射成 Futu SDK 的买卖方向枚举。"""
        normalized = side.strip().upper()
        if normalized == "BUY":
            return futu["TrdSide"].BUY
        if normalized == "SELL":
            return futu["TrdSide"].SELL
        raise ValueError(f"unsupported order side: {side}")


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        normalized = value.strip().upper()
        if not normalized or normalized == "N/A":
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip()
    if not normalized or normalized.upper() == "N/A":
        return None
    return normalized


def _first_row_dict(frame: Any) -> dict[str, Any] | None:
    if frame is None or not hasattr(frame, "empty") or frame.empty:
        return None
    return frame.iloc[0].to_dict()

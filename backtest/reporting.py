from __future__ import annotations

from collections.abc import Iterable, Mapping
from numbers import Real
from typing import Any

import pandas as pd

from backtest.backtest_common import FilesystemLoadSnapshot


STRATEGY_LABELS = {
    "rsi_reversion": "RSI reversion",
    "ema_cross": "EMA cross",
    "ema_rsi_combo": "EMA + RSI",
    "ema_rsi_bull_range": "EMA + RSI bull range",
    "dual_momentum": "Dual momentum",
    "momentum_monthly": "Momentum monthly",
    "dual_momentum_ema_rsi_hybrid": "Dual momentum + EMA + RSI hybrid",
}

STRATEGY_FREQUENCIES = {
    "rsi_reversion": "minute",
    "ema_cross": "minute",
    "ema_rsi_combo": "minute",
    "ema_rsi_bull_range": "minute",
    "dual_momentum": "daily",
    "momentum_monthly": "daily",
    "dual_momentum_ema_rsi_hybrid": "day+minute",
}

SUMMARY_TABLE_COLUMNS = [
    "strategy",
    "frequency",
    "final_value",
    "return_pct",
    "max_drawdown_pct",
    "trade_count",
    "total_fees",
    "strategy_time_sec",
]

COVERAGE_TABLE_COLUMNS = [
    "code",
    "start",
    "end",
    "status",
    "full_start",
    "full_end",
    "full_status",
]


def format_cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def is_numeric_column(frame: pd.DataFrame, column: str) -> bool:
    has_non_null = False
    for value in frame[column]:
        if pd.isna(value):
            continue
        has_non_null = True
        if isinstance(value, bool) or not isinstance(value, Real):
            return False
    return has_non_null


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    column_values = {column: [format_cell(value) for value in frame[column]] for column in columns}
    numeric_columns = {column: is_numeric_column(frame, column) for column in columns}
    widths = {
        column: max(len(column), *(len(value) for value in column_values[column]))
        for column in columns
    }

    def align(value: str, column: str) -> str:
        if numeric_columns[column]:
            return value.rjust(widths[column])
        return value.ljust(widths[column])

    header = "| " + " | ".join(align(column, column) for column in columns) + " |"
    divider = "| " + " | ".join(
        ("-" * max(widths[column] - 1, 1) + ":") if numeric_columns[column] else "-" * widths[column]
        for column in columns
    ) + " |"
    rows = []
    for row_index in range(len(frame)):
        rows.append(
            "| " + " | ".join(align(column_values[column][row_index], column) for column in columns) + " |"
        )
    return "\n".join([header, divider, *rows])


def build_strategy_summary_row(
    strategy_key: str,
    summary: Mapping[str, Any],
    strategy_time_sec: float,
) -> dict[str, object]:
    return {
        "strategy": STRATEGY_LABELS.get(strategy_key, strategy_key),
        "frequency": STRATEGY_FREQUENCIES.get(strategy_key, "unknown"),
        "final_value": float(summary["final_value"]),
        "return_pct": float(summary["total_return_pct"]),
        "max_drawdown_pct": float(summary["max_drawdown_pct"]),
        "trade_count": int(summary["trade_count"]),
        "total_fees": float(summary.get("total_fees", 0.0)),
        "strategy_time_sec": round(float(strategy_time_sec), 2),
    }


def build_strategy_summary_table(rows: list[dict[str, object]]) -> str:
    frame = pd.DataFrame(rows, columns=SUMMARY_TABLE_COLUMNS)
    return markdown_table(frame, SUMMARY_TABLE_COLUMNS)


def _normalize_observations(observations: Iterable[object]) -> pd.DatetimeIndex:
    normalized = pd.to_datetime(list(observations), errors="coerce")
    normalized = pd.DatetimeIndex(normalized)
    if normalized.tz is not None:
        normalized = normalized.tz_localize(None)
    if normalized.empty:
        return normalized
    return normalized.normalize().dropna().unique().sort_values()


def _format_coverage_value(value: pd.Timestamp | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _clip_observations(
    observations: pd.DatetimeIndex,
    *,
    expected_start: object | None,
    expected_end: object | None,
) -> pd.DatetimeIndex:
    clipped = observations
    if expected_start is not None:
        clipped = clipped[clipped >= pd.Timestamp(expected_start).normalize()]
    if expected_end is not None:
        clipped = clipped[clipped <= pd.Timestamp(expected_end).normalize()]
    return clipped


def _build_reference(
    observations_by_code: Mapping[str, pd.DatetimeIndex],
    *,
    expected_start: object | None = None,
    expected_end: object | None = None,
) -> pd.DatetimeIndex:
    reference = pd.DatetimeIndex([])
    for observed in observations_by_code.values():
        if observed.empty:
            continue
        reference = reference.union(
            _clip_observations(
                observed,
                expected_start=expected_start,
                expected_end=expected_end,
            )
        )
    return reference


def _build_coverage_summary(
    observed: pd.DatetimeIndex,
    reference: pd.DatetimeIndex,
    *,
    no_data_status: str,
) -> tuple[str, str, str]:
    if observed.empty:
        return "-", "-", no_data_status

    start = observed[0]
    end = observed[-1]
    status_details: list[str] = []
    if not reference.empty:
        missing_before = int((reference < start).sum())
        missing_after = int((reference > end).sum())
        shared_span = reference[(reference >= start) & (reference <= end)]
        missing_inside = shared_span.difference(observed)
        if missing_before > 0:
            status_details.append(f"late start ({missing_before} missing before start)")
        if missing_after > 0:
            status_details.append(f"early end ({missing_after} missing after end)")
        if len(missing_inside) > 0:
            first_missing = _format_coverage_value(missing_inside[0])
            status_details.append(
                f"missing {len(missing_inside)} session(s) inside shared span, first {first_missing}"
            )

    return (
        _format_coverage_value(start),
        _format_coverage_value(end),
        "ok" if not status_details else "error: " + "; ".join(status_details),
    )


def observations_by_code_from_frame(frame: pd.DataFrame) -> dict[str, pd.DatetimeIndex]:
    observations_by_code: dict[str, pd.DatetimeIndex] = {}
    for code in frame.columns:
        observations_by_code[str(code)] = _normalize_observations(frame.index[frame[code].notna()].tolist())
    return observations_by_code


def observations_by_code_from_histories(
    histories: Mapping[str, pd.DataFrame],
    *,
    date_column: str = "trade_date",
    time_column: str = "time_key",
) -> dict[str, pd.DatetimeIndex]:
    observations_by_code: dict[str, pd.DatetimeIndex] = {}
    for code, history in histories.items():
        if date_column in history.columns:
            observations = history[date_column].tolist()
        elif time_column in history.columns:
            observations = history[time_column].tolist()
        else:
            raise ValueError(f"history for {code} must contain {date_column!r} or {time_column!r}")
        observations_by_code[str(code)] = _normalize_observations(observations)
    return observations_by_code


def build_data_coverage_rows(
    observations_by_code: Mapping[str, Iterable[object]],
    *,
    expected_start: object | None = None,
    expected_end: object | None = None,
) -> list[dict[str, str]]:
    normalized = {
        str(code): _normalize_observations(observations)
        for code, observations in observations_by_code.items()
    }
    reference = _build_reference(normalized, expected_start=expected_start, expected_end=expected_end)
    full_reference = _build_reference(normalized)

    rows: list[dict[str, str]] = []
    for code in sorted(normalized):
        full_observed = normalized[code]
        observed = _clip_observations(
            full_observed,
            expected_start=expected_start,
            expected_end=expected_end,
        )
        start, end, status = _build_coverage_summary(
            observed,
            reference,
            no_data_status="error: no data in requested window",
        )
        full_start, full_end, full_status = _build_coverage_summary(
            full_observed,
            full_reference,
            no_data_status="error: no data",
        )
        rows.append(
            {
                "code": code,
                "start": start,
                "end": end,
                "status": status,
                "full_start": full_start,
                "full_end": full_end,
                "full_status": full_status,
            }
        )
    return rows


def build_data_coverage_table(
    observations_by_code: Mapping[str, Iterable[object]],
    *,
    expected_start: object | None = None,
    expected_end: object | None = None,
) -> str:
    frame = pd.DataFrame(
        build_data_coverage_rows(
            observations_by_code,
            expected_start=expected_start,
            expected_end=expected_end,
        ),
        columns=COVERAGE_TABLE_COLUMNS,
    )
    return markdown_table(frame, COVERAGE_TABLE_COLUMNS)


def render_data_coverage_sections(
    sections: list[tuple[str, Mapping[str, Iterable[object]]]],
    *,
    expected_start: object | None = None,
    expected_end: object | None = None,
) -> list[str]:
    lines: list[str] = []
    for title, observations_by_code in sections:
        if not observations_by_code:
            continue
        if lines:
            lines.append("")
        lines.append(title)
        lines.append(
            build_data_coverage_table(
                observations_by_code,
                expected_start=expected_start,
                expected_end=expected_end,
            )
        )
    return lines


def render_single_strategy_report(
    strategy_key: str,
    summary: Mapping[str, Any],
    strategy_time_sec: float,
    *,
    total_time_sec: float | None = None,
    load_stats: FilesystemLoadSnapshot | None = None,
    coverage_sections: list[tuple[str, Mapping[str, Iterable[object]]]] | None = None,
    coverage_expected_start: object | None = None,
    coverage_expected_end: object | None = None,
) -> str:
    lines = [
        build_strategy_summary_table([build_strategy_summary_row(strategy_key, summary, strategy_time_sec)]),
        "",
    ]
    if total_time_sec is not None:
        lines.append(f"Backtest total time: {total_time_sec:.2f}s")
    start_time = summary.get("start_time")
    end_time = summary.get("end_time")
    if start_time is not None and end_time is not None:
        lines.append(f"Evaluation window: {start_time} -> {end_time}")
    if load_stats is not None:
        lines.append(f"Filesystem load time: {load_stats.total_load_seconds:.2f}s")
        lines.append(f"Files loaded: {load_stats.files_loaded}")
        lines.append(f"Load operations: {load_stats.load_operations}")
    if coverage_sections:
        lines.append("")
        lines.extend(
            render_data_coverage_sections(
                coverage_sections,
                expected_start=coverage_expected_start if coverage_expected_start is not None else start_time,
                expected_end=coverage_expected_end if coverage_expected_end is not None else end_time,
            )
        )
    return "\n".join(lines)


__all__ = [
    "COVERAGE_TABLE_COLUMNS",
    "STRATEGY_FREQUENCIES",
    "STRATEGY_LABELS",
    "SUMMARY_TABLE_COLUMNS",
    "build_data_coverage_rows",
    "build_data_coverage_table",
    "build_strategy_summary_row",
    "build_strategy_summary_table",
    "markdown_table",
    "observations_by_code_from_frame",
    "observations_by_code_from_histories",
    "render_data_coverage_sections",
    "render_single_strategy_report",
]

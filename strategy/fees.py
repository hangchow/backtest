from __future__ import annotations

from typing import Any


FEE_ACCOUNT_PROFILES: dict[str, dict[str, list[dict[str, Any]]]] = {
    "futu_standard": {
        "HK": [
            {"name": "commission", "basis": "notional", "rate": 0.0003, "min_fee": 3.0, "side": "both"},
            {"name": "platform_fee", "basis": "fixed", "fixed": 15.0, "side": "both"},
            {"name": "settlement_fee", "basis": "notional", "rate": 0.000042, "side": "both"},
            {
                "name": "stamp_duty",
                "basis": "notional",
                "rate": 0.001,
                "min_fee": 1.0,
                "side": "both",
                "exempt_security_types": {"etf", "warrant", "cbbc"},
            },
            {"name": "trading_fee", "basis": "notional", "rate": 0.0000565, "min_fee": 0.01, "side": "both"},
            {"name": "sfc_levy", "basis": "notional", "rate": 0.000027, "min_fee": 0.01, "side": "both"},
            {"name": "afr_levy", "basis": "notional", "rate": 0.0000015, "side": "both"},
        ],
        "US": [
            {
                "name": "commission",
                "basis": "shares",
                "rate": 0.0049,
                "min_fee": 0.99,
                "max_pct_notional": 0.005,
                "side": "both",
            },
            {
                "name": "platform_fee",
                "basis": "shares",
                "rate": 0.005,
                "min_fee": 1.0,
                "max_pct_notional": 0.005,
                "side": "both",
            },
            {"name": "settlement_fee", "basis": "shares", "rate": 0.003, "side": "both"},
            {
                "name": "taf",
                "basis": "shares",
                "rate": 0.000195,
                "min_fee": 0.01,
                "max_fee": 9.79,
                "side": "sell",
            },
        ],
    },
    "futu_alt": {},
}
FEE_ACCOUNT_PROFILES["futu_alt"] = FEE_ACCOUNT_PROFILES["futu_standard"]


def compute_order_fees(
    *,
    fee_account: str | None,
    market: str,
    side: str,
    price: float,
    shares: int,
    security_type: str = "stock",
) -> tuple[float, dict[str, float]]:
    if not fee_account:
        return 0.0, {}
    if shares <= 0:
        return 0.0, {}
    if fee_account not in FEE_ACCOUNT_PROFILES:
        supported = ", ".join(sorted(FEE_ACCOUNT_PROFILES))
        raise ValueError(f"Unsupported fee-account: {fee_account}. Supported: {supported}")

    profile = FEE_ACCOUNT_PROFILES[fee_account]
    if market not in profile:
        raise ValueError(f"fee-account {fee_account} does not define market {market}")

    notional = float(price) * int(shares)
    result: dict[str, float] = {}
    total = 0.0
    for rule in profile[market]:
        rule_side = str(rule.get("side", "both"))
        if rule_side != "both" and rule_side != side:
            continue
        exempt_types = set(rule.get("exempt_security_types", set()))
        if security_type in exempt_types:
            continue

        basis = rule["basis"]
        if basis == "notional":
            fee = notional * float(rule.get("rate", 0.0))
        elif basis == "shares":
            fee = int(shares) * float(rule.get("rate", 0.0))
        elif basis == "fixed":
            fee = float(rule.get("fixed", 0.0))
        else:
            raise ValueError(f"Unsupported fee basis: {basis}")

        min_fee = rule.get("min_fee")
        max_fee = rule.get("max_fee")
        max_pct_notional = rule.get("max_pct_notional")
        if min_fee is not None:
            fee = max(fee, float(min_fee))
        if max_fee is not None:
            fee = min(fee, float(max_fee))
        if max_pct_notional is not None:
            fee = min(fee, notional * float(max_pct_notional))

        fee = round(fee, 2)
        if fee <= 0:
            continue
        result[str(rule["name"])] = fee
        total += fee

    return round(total, 2), result

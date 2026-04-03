from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def add_strategy_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy-config",
        type=Path,
        default=None,
        help="JSON file mapping strategy names to per-strategy parameter overrides.",
    )


def parse_strategy_config_path(argv: list[str] | None = None) -> Path | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--strategy-config", type=Path, default=None)
    known, _ = parser.parse_known_args(argv)
    return known.strategy_config


def _coerce_config_value(strategy_key: str, key: str, value: Any, sample: Any) -> Any:
    if isinstance(sample, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ValueError(f"invalid boolean value for {strategy_key}.{key}: {value!r}")
    if isinstance(sample, int) and not isinstance(sample, bool):
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid integer value for {strategy_key}.{key}: {value!r}") from exc
    if isinstance(sample, float):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid float value for {strategy_key}.{key}: {value!r}") from exc
    if isinstance(sample, str):
        return str(value)
    return value


def _load_strategy_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--strategy-config must be a JSON object")
    return payload


def resolve_single_strategy_defaults(
    strategy_key: str,
    defaults: Mapping[str, Any],
    *,
    argv: list[str] | None = None,
) -> dict[str, Any]:
    resolved = dict(defaults)
    path = parse_strategy_config_path(argv)
    payload = _load_strategy_config(path)
    overrides = payload.get(strategy_key)
    if overrides is None:
        return resolved
    if not isinstance(overrides, Mapping):
        raise ValueError(f"strategy config for {strategy_key} in {path} must be an object")
    for key, value in overrides.items():
        if key not in resolved:
            raise ValueError(f"unsupported parameter in {path}: {strategy_key}.{key}")
        resolved[key] = _coerce_config_value(strategy_key, key, value, resolved[key])
    return resolved


def resolve_batch_strategy_params(
    defaults: Mapping[str, Mapping[str, Any]],
    *,
    path: Path | None,
) -> dict[str, dict[str, Any]]:
    resolved = {strategy_key: dict(values) for strategy_key, values in defaults.items()}
    payload = _load_strategy_config(path)
    for strategy_key, overrides in payload.items():
        if strategy_key not in resolved:
            raise ValueError(f"unsupported strategy in {path}: {strategy_key}")
        if not isinstance(overrides, Mapping):
            raise ValueError(f"strategy config for {strategy_key} in {path} must be an object")
        for key, value in overrides.items():
            if key not in resolved[strategy_key]:
                raise ValueError(f"unsupported parameter in {path}: {strategy_key}.{key}")
            resolved[strategy_key][key] = _coerce_config_value(strategy_key, key, value, resolved[strategy_key][key])
    return resolved


__all__ = [
    "add_strategy_config_arg",
    "parse_strategy_config_path",
    "resolve_batch_strategy_params",
    "resolve_single_strategy_defaults",
]

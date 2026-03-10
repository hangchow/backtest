#!/usr/bin/env python3
"""Compatibility wrapper for historical 1m fetch helpers.

This module keeps backward-compatible imports for scripts/tests that still
reference ``fetch_history_1m`` and preserves CLI behavior for legacy jobs.
"""

from __future__ import annotations

import sys

try:
    from fetch_futu_1m import MINUTE_COLUMNS, main, remove_stale_daily_files, save_daily_files
except ModuleNotFoundError:  # package-style import
    from .fetch_futu_1m import MINUTE_COLUMNS, main, remove_stale_daily_files, save_daily_files

__all__ = [
    "MINUTE_COLUMNS",
    "main",
    "remove_stale_daily_files",
    "save_daily_files",
]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

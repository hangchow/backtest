#!/usr/bin/env python3
"""Compatibility wrapper for historical 1m fetch helpers.

This module keeps backward-compatible imports for scripts/tests that still
reference ``fetch_history_1m``.
"""

from __future__ import annotations

try:
    from fetch_futu_1m import MINUTE_COLUMNS, remove_stale_daily_files, save_daily_files
except ModuleNotFoundError:  # package-style import
    from .fetch_futu_1m import MINUTE_COLUMNS, remove_stale_daily_files, save_daily_files

__all__ = [
    "MINUTE_COLUMNS",
    "remove_stale_daily_files",
    "save_daily_files",
]

"""Compatibility shim for renamed Futu 1-minute fetch script.

This module preserves imports of ``fetch_history_1m`` after the script was
renamed to ``fetch_futu_1m``.
"""

from fetch_futu_1m import *  # noqa: F401,F403

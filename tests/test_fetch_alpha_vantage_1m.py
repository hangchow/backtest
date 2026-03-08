from __future__ import annotations

from datetime import date
import sys
import unittest
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetch_alpha_vantage_1m import convert_to_local_layout, iter_months


class IterMonthsTests(unittest.TestCase):
    def test_iter_months_includes_both_bounds(self) -> None:
        months = iter_months(date(2025, 3, 7), date(2025, 6, 1))

        self.assertEqual(months, ["2025-03", "2025-04", "2025-05", "2025-06"])


class ConvertToLocalLayoutTests(unittest.TestCase):
    def test_convert_to_local_layout_sorts_and_keeps_expected_columns(self) -> None:
        raw = pd.DataFrame(
            {
                "timestamp": [
                    "2025-03-07 09:32:00",
                    "2025-03-06 16:00:00",
                    "2025-03-07 09:30:00",
                    "2025-03-07 09:31:00",
                ],
                "open": [12.0, 10.0, 11.0, 11.5],
                "high": [12.5, 10.5, 11.2, 11.7],
                "low": [11.8, 9.9, 10.8, 11.4],
                "close": [12.2, 10.5, 11.1, 11.6],
                "volume": [300, 100, 200, 250],
            }
        )

        converted = convert_to_local_layout(raw, date(2025, 3, 7), date(2025, 3, 7))

        self.assertEqual(
            list(converted["time_key"]),
            ["2025-03-07 09:30:00", "2025-03-07 09:31:00", "2025-03-07 09:32:00"],
        )
        self.assertEqual(list(converted.columns), ["time_key", "open", "close", "high", "low", "volume"])


if __name__ == "__main__":
    unittest.main()

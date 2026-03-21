from __future__ import annotations

from datetime import date
import sys
import unittest
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fetch_polygon_1m import convert_to_local_layout, iter_month_ranges, with_api_key


class IterMonthRangesTests(unittest.TestCase):
    def test_iter_month_ranges_clips_partial_months(self) -> None:
        # 验证月份区间迭代会正确截断首尾不完整月份。
        ranges = iter_month_ranges(date(2025, 3, 7), date(2025, 5, 2))

        self.assertEqual(
            ranges,
            [
                (date(2025, 3, 7), date(2025, 3, 31)),
                (date(2025, 4, 1), date(2025, 4, 30)),
                (date(2025, 5, 1), date(2025, 5, 2)),
            ],
        )


class WithApiKeyTests(unittest.TestCase):
    def test_with_api_key_preserves_existing_query(self) -> None:
        # 验证追加 API key 时会保留已有查询参数。
        url = with_api_key("https://api.polygon.io/v2/aggs?ticker=MSFT&sort=asc", "secret")

        self.assertIn("ticker=MSFT", url)
        self.assertIn("sort=asc", url)
        self.assertIn("apiKey=secret", url)


class ConvertToLocalLayoutTests(unittest.TestCase):
    def test_convert_to_local_layout_filters_extended_hours_and_formats_et(self) -> None:
        # 验证转换到本地目录布局时会过滤扩展时段并按美东时间格式化。
        raw = pd.DataFrame(
            {
                "t": [
                    1741357740000,  # 2025-03-07 09:29 ET
                    1741357800000,  # 2025-03-07 09:30 ET
                    1741357860000,  # 2025-03-07 09:31 ET
                    1741381200000,  # 2025-03-07 16:00 ET
                ],
                "o": [1.0, 2.0, 3.0, 4.0],
                "c": [1.1, 2.1, 3.1, 4.1],
                "h": [1.2, 2.2, 3.2, 4.2],
                "l": [0.9, 1.9, 2.9, 3.9],
                "v": [10, 20, 30, 40],
            }
        )

        converted = convert_to_local_layout(raw, include_extended_hours=False)

        self.assertEqual(
            list(converted["time_key"]),
            ["2025-03-07 09:30:00", "2025-03-07 09:31:00", "2025-03-07 16:00:00"],
        )
        self.assertEqual(list(converted.columns), ["time_key", "open", "close", "high", "low", "volume"])
        self.assertEqual(list(converted["volume"]), [20, 30, 40])


if __name__ == "__main__":
    unittest.main()

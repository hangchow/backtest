from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fetch_valuesider_holdings import (
    build_data_quality_issues,
    build_holder_count_by_ticker,
    build_summary_by_ticker,
    normalize_security,
    normalize_ticker,
    publish_output_files,
)


class NormalizeTickerTests(unittest.TestCase):
    def test_normalize_ticker_maps_missing_values_to_empty_string(self) -> None:
        self.assertEqual(normalize_ticker(None), "")
        self.assertEqual(normalize_ticker(float("nan")), "")
        self.assertEqual(normalize_ticker(" nan "), "")
        self.assertEqual(normalize_ticker(" GM "), "GM")

    def test_normalize_security_applies_known_overrides(self) -> None:
        self.assertEqual(
            normalize_security("1534615D", "LOTUS BAKERIES"),
            ("LOTB", "LOTUS BAKERIES"),
        )
        self.assertEqual(
            normalize_security("2299955D", "CONSTELLATION SOFTWARE IN-40"),
            ("CSU", "CONSTELLATION SOFTWARE INC"),
        )
        self.assertEqual(
            normalize_security("GOOGL", "ALPHABET INC-CL A"),
            ("GOOGL", "ALPHABET INC-CL A"),
        )


class BuildSummaryByTickerTests(unittest.TestCase):
    def test_build_summary_by_ticker_merges_same_ticker_with_different_stock_names(self) -> None:
        all_df = pd.DataFrame(
            [
                {"ticker": "FERG", "stock": "FERGUSON ENTERPRISES INC", "value": 1_275_229_637.0},
                {"ticker": "FERG", "stock": "FERGUSON PLC", "value": 241_855_659.0},
                {"ticker": "GM", "stock": "GENERAL MOTORS CO GM", "value": 1_234_352_783.0},
                {"ticker": "GM", "stock": "GENERAL MOTORS CO", "value": 819_430_885.0},
                {"ticker": "RBC", "stock": "RBC BEARINGS INC", "value": 1_051_528_440.0},
                {"ticker": "RBC", "stock": "REGAL BELOIT CORP", "value": 452_383_261.0},
                {"ticker": "", "stock": "ASAC II LP UNIT SEALED", "value": 429_104.0},
                {"ticker": None, "stock": "TPHGREENWICH TRUST UNI", "value": 0.0},
                {"ticker": "2299955D", "stock": "CONSTELLATION SOFTWARE IN-40", "value": 0.0},
            ]
        )

        summary_df = build_summary_by_ticker(all_df)

        self.assertEqual(
            float(summary_df.loc[summary_df["ticker"] == "FERG", "value"].iloc[0]),
            1_517_085_296.0,
        )
        self.assertEqual(
            float(summary_df.loc[summary_df["ticker"] == "GM", "value"].iloc[0]),
            2_053_783_668.0,
        )
        self.assertEqual(
            summary_df.loc[summary_df["ticker"] == "GM", "stock"].iloc[0],
            "GENERAL MOTORS CO",
        )
        self.assertEqual(
            float(summary_df.loc[summary_df["ticker"] == "RBC", "value"].iloc[0]),
            1_503_911_701.0,
        )

        self.assertTrue(summary_df.loc[summary_df["ticker"] == ""].empty)
        self.assertTrue(summary_df.loc[summary_df["ticker"] == "2299955D"].empty)

    def test_build_summary_by_ticker_merges_selected_share_classes_under_group_labels(self) -> None:
        all_df = pd.DataFrame(
            [
                {"ticker": "GOOG", "stock": "ALPHABET INC-CL C", "value": 100.0},
                {"ticker": "GOOGL", "stock": "ALPHABET INC-CL A", "value": 300.0},
                {"ticker": "BRK.A", "stock": "BERKSHIRE HATHAWAY INC CL-A", "value": 50.0},
                {"ticker": "BRK.B", "stock": "BERKSHIRE HATHAWAY INC CL-B", "value": 200.0},
            ]
        )

        summary_df = build_summary_by_ticker(all_df)

        self.assertEqual(
            float(summary_df.loc[summary_df["ticker"] == "GOOG/GOOGL", "value"].iloc[0]),
            400.0,
        )
        self.assertEqual(
            summary_df.loc[summary_df["ticker"] == "GOOG/GOOGL", "stock"].iloc[0],
            "ALPHABET INC-CL A",
        )
        self.assertEqual(
            float(summary_df.loc[summary_df["ticker"] == "BRK.A/BRK.B", "value"].iloc[0]),
            250.0,
        )
        self.assertEqual(
            summary_df.loc[summary_df["ticker"] == "BRK.A/BRK.B", "stock"].iloc[0],
            "BERKSHIRE HATHAWAY INC CL-B",
        )
        self.assertTrue(summary_df.loc[summary_df["ticker"] == "GOOG"].empty)
        self.assertTrue(summary_df.loc[summary_df["ticker"] == "GOOGL"].empty)
        self.assertTrue(summary_df.loc[summary_df["ticker"] == "BRK.A"].empty)
        self.assertTrue(summary_df.loc[summary_df["ticker"] == "BRK.B"].empty)


class BuildDataQualityIssuesTests(unittest.TestCase):
    def test_build_data_quality_issues_flags_blank_zero_and_code_like_rows(self) -> None:
        all_df = pd.DataFrame(
            [
                {
                    "investor_slug": "fund-a",
                    "ticker": "",
                    "stock": "ASAC II LP UNIT SEALED",
                    "value": 429_104.0,
                    "value_text": "$429,104",
                    "portfolio_url": "https://example.com/a",
                },
                {
                    "investor_slug": "fund-b",
                    "ticker": "CSU",
                    "stock": "CONSTELLATION SOFTWARE INC",
                    "value": 0.0,
                    "value_text": "$0",
                    "portfolio_url": "https://example.com/b",
                },
                {
                    "investor_slug": "fund-c",
                    "ticker": "AAPL",
                    "stock": "APPLE INC",
                    "value": 1.0,
                    "value_text": "$1",
                    "portfolio_url": "https://example.com/c",
                },
            ]
        )

        issues_df = build_data_quality_issues(all_df)

        self.assertEqual(len(issues_df), 2)
        self.assertEqual(
            issues_df.loc[issues_df["investor_slug"] == "fund-a", "issue_types"].iloc[0],
            "blank_ticker",
        )
        self.assertEqual(
            issues_df.loc[issues_df["investor_slug"] == "fund-b", "issue_types"].iloc[0],
            "nonpositive_value",
        )


class BuildHolderCountByTickerTests(unittest.TestCase):
    def test_build_holder_count_by_ticker_counts_unique_investors_per_clean_ticker(self) -> None:
        all_df = pd.DataFrame(
            [
                {
                    "investor_slug": "fund-a",
                    "ticker": "MSFT",
                    "stock": "MICROSOFT CORP",
                    "value": 100.0,
                },
                {
                    "investor_slug": "fund-b",
                    "ticker": "MSFT",
                    "stock": "MICROSOFT CORP",
                    "value": 200.0,
                },
                {
                    "investor_slug": "fund-a",
                    "ticker": "GM",
                    "stock": "GENERAL MOTORS CO GM",
                    "value": 300.0,
                },
                {
                    "investor_slug": "fund-a",
                    "ticker": "GM",
                    "stock": "GENERAL MOTORS CO",
                    "value": 400.0,
                },
                {
                    "investor_slug": "fund-c",
                    "ticker": "GM",
                    "stock": "GENERAL MOTORS CO",
                    "value": 500.0,
                },
                {
                    "investor_slug": "fund-d",
                    "ticker": "",
                    "stock": "BLANK TICKER INC",
                    "value": 600.0,
                },
                {
                    "investor_slug": "fund-e",
                    "ticker": "CSU",
                    "stock": "CONSTELLATION SOFTWARE INC",
                    "value": 0.0,
                },
            ]
        )

        holder_count_df = build_holder_count_by_ticker(all_df)

        self.assertEqual(
            int(holder_count_df.loc[holder_count_df["ticker"] == "MSFT", "holder_count"].iloc[0]),
            2,
        )
        self.assertEqual(
            int(holder_count_df.loc[holder_count_df["ticker"] == "GM", "holder_count"].iloc[0]),
            2,
        )
        self.assertEqual(
            holder_count_df.loc[holder_count_df["ticker"] == "GM", "stock"].iloc[0],
            "GENERAL MOTORS CO",
        )
        self.assertTrue(holder_count_df.loc[holder_count_df["ticker"] == ""].empty)
        self.assertTrue(holder_count_df.loc[holder_count_df["ticker"] == "CSU"].empty)

    def test_build_holder_count_by_ticker_merges_selected_share_classes_without_double_counting(self) -> None:
        all_df = pd.DataFrame(
            [
                {
                    "investor_slug": "fund-a",
                    "ticker": "GOOG",
                    "stock": "ALPHABET INC-CL C",
                    "value": 100.0,
                },
                {
                    "investor_slug": "fund-a",
                    "ticker": "GOOGL",
                    "stock": "ALPHABET INC-CL A",
                    "value": 120.0,
                },
                {
                    "investor_slug": "fund-b",
                    "ticker": "GOOGL",
                    "stock": "ALPHABET INC-CL A",
                    "value": 140.0,
                },
                {
                    "investor_slug": "fund-c",
                    "ticker": "BRK.A",
                    "stock": "BERKSHIRE HATHAWAY INC CL-A",
                    "value": 80.0,
                },
                {
                    "investor_slug": "fund-c",
                    "ticker": "BRK.B",
                    "stock": "BERKSHIRE HATHAWAY INC CL-B",
                    "value": 200.0,
                },
                {
                    "investor_slug": "fund-d",
                    "ticker": "BRK.B",
                    "stock": "BERKSHIRE HATHAWAY INC CL-B",
                    "value": 60.0,
                },
            ]
        )

        holder_count_df = build_holder_count_by_ticker(all_df)

        self.assertEqual(
            int(
                holder_count_df.loc[
                    holder_count_df["ticker"] == "GOOG/GOOGL", "holder_count"
                ].iloc[0]
            ),
            2,
        )
        self.assertEqual(
            holder_count_df.loc[holder_count_df["ticker"] == "GOOG/GOOGL", "stock"].iloc[0],
            "ALPHABET INC-CL A",
        )
        self.assertEqual(
            int(
                holder_count_df.loc[
                    holder_count_df["ticker"] == "BRK.A/BRK.B", "holder_count"
                ].iloc[0]
            ),
            2,
        )
        self.assertEqual(
            holder_count_df.loc[holder_count_df["ticker"] == "BRK.A/BRK.B", "stock"].iloc[0],
            "BERKSHIRE HATHAWAY INC CL-B",
        )
        self.assertTrue(holder_count_df.loc[holder_count_df["ticker"] == "GOOG"].empty)
        self.assertTrue(holder_count_df.loc[holder_count_df["ticker"] == "GOOGL"].empty)
        self.assertTrue(holder_count_df.loc[holder_count_df["ticker"] == "BRK.A"].empty)
        self.assertTrue(holder_count_df.loc[holder_count_df["ticker"] == "BRK.B"].empty)


class PublishOutputFilesTests(unittest.TestCase):
    def test_publish_output_files_copies_required_files_and_removes_stale_nonpublished_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            publish_dir = Path(tmp) / "publish"
            output_dir.mkdir(parents=True, exist_ok=True)
            publish_dir.mkdir(parents=True, exist_ok=True)

            for filename in (
                "all_holdings.csv",
                "summary_by_ticker.csv",
                "holder_count_by_ticker.csv",
                "data_quality_issues.csv",
            ):
                (output_dir / filename).write_text(filename, encoding="utf-8")

            stale_errors_path = publish_dir / "errors.csv"
            stale_errors_path.write_text("stale", encoding="utf-8")

            publish_output_files(output_dir, publish_dir)

            self.assertEqual(
                (publish_dir / "all_holdings.csv").read_text(encoding="utf-8"),
                "all_holdings.csv",
            )
            self.assertEqual(
                (publish_dir / "summary_by_ticker.csv").read_text(encoding="utf-8"),
                "summary_by_ticker.csv",
            )
            self.assertEqual(
                (publish_dir / "holder_count_by_ticker.csv").read_text(encoding="utf-8"),
                "holder_count_by_ticker.csv",
            )
            self.assertFalse((publish_dir / "data_quality_issues.csv").exists())
            self.assertFalse(stale_errors_path.exists())


if __name__ == "__main__":
    unittest.main()

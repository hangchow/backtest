from __future__ import annotations

import unittest

from livetrading.cli import parse_args


class ParseArgsTests(unittest.TestCase):
    def test_parse_args_accepts_schedule_trigger_time(self) -> None:
        args = parse_args(
            [
                "--quote-config",
                "quote.json",
                "--history-config",
                "history.json",
                "--pool-config",
                "pool.json",
                "--trade-config",
                "trade.json",
                "--schedule-trigger-time",
                "09:20",
            ]
        )

        self.assertEqual(args.schedule_trigger_time, "09:20")

    def test_parse_args_rejects_invalid_schedule_trigger_time(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(
                [
                    "--quote-config",
                    "quote.json",
                    "--trade-config",
                    "trade.json",
                    "--schedule-trigger-time",
                    "9:20:00",
                ]
            )


if __name__ == "__main__":
    unittest.main()

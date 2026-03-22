from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKTEST_MODULES = (
    "backtest.backtest_rsi_reversion",
    "backtest.backtest_ema_cross",
    "backtest.backtest_ema_rsi_combo",
    "backtest.backtest_ema_rsi_bull_range",
    "backtest.backtest_dual_momentum",
    "backtest.backtest_dual_momentum_ema_rsi_hybrid",
    "backtest.backtest_momentum_monthly",
    "backtest.backtest_compare",
)


class BacktestCliEntryTests(unittest.TestCase):
    def run_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_all_backtest_modules_expose_help_via_python_m(self) -> None:
        for module_name in BACKTEST_MODULES:
            with self.subTest(module=module_name):
                result = self.run_command("-m", module_name, "--help")

                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertIn("--market", result.stdout)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class LiveTradingCliEntryTests(unittest.TestCase):
    def run_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_root_script_help_uses_shared_cli(self) -> None:
        result = self.run_command("livetrading.py", "--help")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--quote-config", result.stdout)
        self.assertIn("--trade-config", result.stdout)

    def test_module_help_uses_shared_cli(self) -> None:
        result = self.run_command("-m", "livetrading", "--help")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--quote-config", result.stdout)
        self.assertIn("--trade-config", result.stdout)


if __name__ == "__main__":
    unittest.main()

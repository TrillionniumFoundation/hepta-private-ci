#!/usr/bin/env python3

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class OperationTailTest(unittest.TestCase):
    def test_exact_bounded_result(self) -> None:
        output = subprocess.check_output(
            [
                sys.executable,
                str(ROOT / "inspect_operation_tail.py"),
                "--raw-dir",
                str(ROOT / "raw"),
            ],
            text=True,
        )
        result = json.loads(output)
        expected = json.loads((ROOT / "RESULT.json").read_text())
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()

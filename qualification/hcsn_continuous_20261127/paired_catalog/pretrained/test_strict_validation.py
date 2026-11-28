"""Source-only regressions for fail-closed pretrained catalog validation."""

import ast
import subprocess
import sys
import unittest
from pathlib import Path

from strict_validation import require_integrity


HERE = Path(__file__).resolve().parent
ENTRY_POINTS = ("assets.py", "encode.py", "adapt.py")


class StrictValidationTest(unittest.TestCase):
    def test_entry_points_do_not_use_optimizable_assertions(self):
        for name in ENTRY_POINTS:
            tree = ast.parse((HERE / name).read_text(), filename=name)
            assertions = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
            self.assertEqual(assertions, [], name)

    def test_helper_rejects_false_condition(self):
        with self.assertRaisesRegex(ValueError, "sealed mismatch"):
            require_integrity(False, "sealed mismatch")

    def test_helper_remains_active_with_python_optimization(self):
        code = (
            "from strict_validation import require_integrity\n"
            "try:\n"
            "    require_integrity(False, 'optimized mismatch')\n"
            "except ValueError as exc:\n"
            "    if str(exc) != 'optimized mismatch':\n"
            "        raise SystemExit('wrong validation error')\n"
            "else:\n"
            "    raise SystemExit('validation was skipped')\n"
        )
        result = subprocess.run(
            [sys.executable, "-O", "-c", code],
            cwd=HERE,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

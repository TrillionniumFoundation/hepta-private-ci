from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hepta-knowledge-graph-capacity-curve.py"


class KnowledgeGraphCapacityCurveTests(unittest.TestCase):
    def test_self_test_is_fail_closed_and_executable(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--self-test"],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "PASS_HEPTA_KNOWLEDGE_GRAPH_CAPACITY_CURVE_SELF_TEST",
            result.stdout,
        )

    def test_measurement_requires_exact_source_and_host_identity(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--expected-sha", result.stdout)


if __name__ == "__main__":
    unittest.main()

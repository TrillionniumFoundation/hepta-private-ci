#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hepta-implementation-maps.py"


class ExactHeadImplementationEvidenceTests(unittest.TestCase):
    def test_evidence_binds_current_head_and_discovers_compact_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "implementation-evidence.json"
            subprocess.run(
                [sys.executable, str(SCRIPT), "evidence", "--output", str(output)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip()
            tree = subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
            ).strip()
            self.assertEqual(payload["sourceBase"], {"commit": head, "tree": tree})
            compact = next(
                row for row in payload["modules"] if row["module"] == "compact.engine"
            )
            tests = {
                test
                for operation in compact["operations"]
                for test in operation.get("tests", [])
            }
            self.assertTrue(
                any(
                    test.endswith(
                        "qualified_tests.rs::canonical_path_rejects_live_tombstone_live_resurrection"
                    )
                    for test in tests
                ),
                tests,
            )
            self.assertTrue(
                any("proof_binds_evaluator_attestation_and_candidate_identity" in test for test in tests),
                tests,
            )


if __name__ == "__main__":
    unittest.main()

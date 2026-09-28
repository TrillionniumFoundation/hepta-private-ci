from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hepta-objective-evidence-project.py"
SOURCE = "1" * 40
TREE = "2" * 40
LOG = "3" * 64


def candidate(kind: str, exit_code: int = 0) -> dict:
    return {
        "kind": kind,
        "clean": True,
        "checks": [
            {
                "name": "test",
                "status": "completed",
                "exitCode": exit_code,
                "logSha256": LOG,
            }
        ],
    }


class EvidenceProjectionTest(unittest.TestCase):
    def run_projection(
        self, exact: dict | None, target: dict | None
    ) -> tuple[subprocess.CompletedProcess[str], dict | None]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = [
                sys.executable,
                str(SCRIPT),
                "--source-commit",
                SOURCE,
                "--source-tree",
                TREE,
                "--output",
                str(root / "projection.json"),
            ]
            if exact is not None:
                (root / "exact.json").write_text(json.dumps(exact), encoding="utf-8")
                argv += ["--exact-execution", str(root / "exact.json")]
            if target is not None:
                (root / "target.json").write_text(json.dumps(target), encoding="utf-8")
                argv += ["--target-measurement", str(root / "target.json")]
            completed = subprocess.run(argv, text=True, capture_output=True)
            output = root / "projection.json"
            return completed, json.loads(output.read_text()) if output.exists() else None

    def test_projects_passes_without_promoting_acceptance(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "runId": "17",
            "runAttempt": "1",
            "workflowCommit": "4" * 40,
            "candidates": [candidate("source-head"), candidate("synthetic-merge")],
            "checksPassed": True,
            "errors": [],
        }
        target = {
            "schema": "hepta.objective-target-host-evidence.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "hostProfileId": "ci-host",
            "measurements": [{"path": "ordinary"}],
        }
        completed, value = self.run_projection(exact, target)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        assert value is not None
        self.assertEqual(value["exactExecution"]["sourceHeadQualification"], "passed")
        self.assertEqual(
            value["exactExecution"]["syntheticMergeQualification"], "passed"
        )
        self.assertTrue(value["targetHostMeasurement"]["measurementObserved"])
        self.assertFalse(
            value["targetHostMeasurement"]["selectedDeploymentHostAccepted"]
        )
        self.assertEqual(
            value["truth"],
            {
                "productionImplementation": False,
                "accepted": False,
                "activated": False,
                "released": False,
            },
        )

    def test_incomplete_candidate_is_failed_not_passed(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "candidates": [candidate("source-head", 1)],
            "checksPassed": False,
            "errors": ["observed failure"],
        }
        completed, value = self.run_projection(exact, None)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        assert value is not None
        self.assertEqual(value["exactExecution"]["sourceHeadQualification"], "failed")
        self.assertEqual(
            value["exactExecution"]["syntheticMergeQualification"], "failed"
        )
        self.assertFalse(value["exactExecution"]["checksPassed"])

    def test_source_identity_mismatch_refuses_projection(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": "9" * 40,
            "sourceTree": TREE,
            "candidates": [],
            "checksPassed": False,
            "errors": [],
        }
        completed, value = self.run_projection(exact, None)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()

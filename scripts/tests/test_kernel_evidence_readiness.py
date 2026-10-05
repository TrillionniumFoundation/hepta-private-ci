from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import kernel_evidence_readiness as readiness


SOURCE = "a" * 40
TREE = "b" * 40
BASE = "c" * 40
MERGE = "d" * 40
WORKFLOW = "e" * 40
RUN_ID = "12345"
RUN_ATTEMPT = "2"
RUNNER = "ubuntu24-20260930"
TARGET = "x86_64-unknown-linux-gnu"


class ReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "codex-rs").mkdir()
        (self.root / "codex-rs/Cargo.lock").write_text("lock\n", encoding="utf-8")
        (self.root / "codex-rs/hepta-evidence/migrations").mkdir(parents=True)
        (self.root / "codex-rs/hepta-evidence/migrations/0001.sql").write_text(
            "select 1;\n", encoding="utf-8"
        )
        (self.root / "codex-rs/hepta-evidence/src").mkdir(parents=True)
        (self.root / "codex-rs/hepta-evidence/src/example_tests.rs").write_text(
            "#[test] fn example() {}\n", encoding="utf-8"
        )
        (self.root / "codex-rs/hepta-evidence/tests").mkdir(parents=True)
        (self.root / "codex-rs/hepta-agentd/tests").mkdir(parents=True)
        (self.root / "scripts/tests").mkdir(parents=True)
        (self.root / "scripts/tests/test_example.py").write_text(
            "def test_example(): pass\n", encoding="utf-8"
        )
        (self.root / "docs/modules/kernel.evidence").mkdir(parents=True)
        (self.root / "docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json").write_text(
            "{}\n", encoding="utf-8"
        )
        (self.root / "docs/modules/kernel.evidence/TECHNICAL.md").write_text(
            "technical\n", encoding="utf-8"
        )
        (self.root / "docs/lane-a-foundation/kernel.evidence").mkdir(parents=True)
        (self.root / "docs/lane-a-foundation/kernel.evidence/README.md").write_text(
            "index\n", encoding="utf-8"
        )
        self.checked = self.root / "qualification/kernel-evidence/STATUS_SOURCE.json"
        self.checked.parent.mkdir(parents=True)
        self.checked.write_text(
            json.dumps(
                {
                    "schema": "hepta.kernel-evidence-status-source.v1",
                    "asOfCommit": "1" * 40,
                    "asOfTree": "2" * 40,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.receipts: dict[str, Path] = {}
        for kind in readiness.REQUIRED_QUALIFICATION_RECEIPTS:
            path = self.root / f"{kind}.json"
            value = {
                "schemaVersion": 2,
                "module": "kernel.evidence",
                "receiptKind": "candidate_qualification",
                "kind": kind,
                "sourceHeadSha": SOURCE,
                "sourceHeadTree": TREE,
                "baseSha": BASE,
                "deterministicMergeSha": MERGE
                if kind == "deterministic_merge"
                else None,
                "testedObjectSha": MERGE
                if kind == "deterministic_merge"
                else SOURCE,
                "workflowSha": WORKFLOW,
                "workflowRunId": RUN_ID,
                "workflowRunAttempt": RUN_ATTEMPT,
                "runnerImage": RUNNER,
                "targetTriple": TARGET,
                "status": "passed",
                "passed": True,
                "exitCode": 0,
                "startedAtUnixMs": 100,
                "finishedAtUnixMs": 200,
                "command": "test command",
                "logSha256": "3" * 64,
                "qualificationGranted": False,
                "independentAcceptanceGranted": False,
                "productionActivationGranted": False,
                "releaseGranted": False,
            }
            path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            self.receipts[kind] = path
        self.crash = self.root / "crash"
        self.crash.mkdir()
        for scenario in readiness.REQUIRED_CRASH_SCENARIOS:
            value = {
                "schemaVersion": 2,
                "module": "kernel.evidence",
                "receiptKind": "crash_consistency_scenario",
                "scenario": scenario,
                "sourceHeadSha": SOURCE,
                "sourceHeadTree": TREE,
                "baseSha": BASE,
                "workflowSha": WORKFLOW,
                "workflowRunId": RUN_ID,
                "workflowRunAttempt": RUN_ATTEMPT,
                "runnerImage": RUNNER,
                "targetTriple": TARGET,
                "qualificationClass": "hosted_runner",
                "status": "passed",
                "startedAtUnixMs": 100,
                "finishedAtUnixMs": 200,
                "commands": [
                    {
                        "status": "passed",
                        "exitCode": 0,
                        "timedOut": False,
                        "skippedDetected": False,
                        "missingMarkers": [],
                        "logSha256": "4" * 64,
                        "startedAtUnixMs": 110,
                        "finishedAtUnixMs": 190,
                    }
                ],
                "qualificationGranted": False,
                "targetHostAcceptanceGranted": False,
                "productionActivationGranted": False,
                "releaseGranted": False,
            }
            (self.crash / f"{scenario}.json").write_text(
                json.dumps(value) + "\n", encoding="utf-8"
            )
        self.runtime = self.root / "runtime-status.json"
        self.write_runtime_status(SOURCE, TREE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_runtime_status(self, source: str, tree: str) -> None:
        value = {
            "schema": "hepta.kernel-evidence-runtime-status-source.v1",
            "schemaVersion": 1,
            "module": "kernel.evidence",
            "statusClass": "exact_runtime_qualification",
            "asOfCommit": source,
            "asOfTree": tree,
            "baseSha": BASE,
            "deterministicMergeSha": MERGE,
            "githubSyntheticMergeSha": None,
            "workflowSha": WORKFLOW,
            "finalMergeSha": None,
            "workflowRunId": RUN_ID,
            "workflowRunAttempt": RUN_ATTEMPT,
            "runnerImage": RUNNER,
            "targetTriple": TARGET,
            "authenticatedFrontierAuthorityAccepted": False,
            "externalFrontierActive": False,
            "independentRollbackAnchorAccepted": False,
            "independentAcceptance": False,
            "operatorActivation": False,
            "canaryAccepted": False,
            "promotionApproved": False,
            "releaseApproved": False,
        }
        self.runtime.write_text(json.dumps(value) + "\n", encoding="utf-8")

    def build(self) -> dict[str, object]:
        return readiness.build_manifest(
            root=self.root,
            source_head_sha=SOURCE,
            source_head_tree=TREE,
            base_sha=BASE,
            deterministic_merge_sha=MERGE,
            github_synthetic_merge_sha=None,
            workflow_sha=WORKFLOW,
            final_merge_sha=None,
            workflow_run_id=RUN_ID,
            workflow_run_attempt=RUN_ATTEMPT,
            runner_image=RUNNER,
            target_triple=TARGET,
            runtime_status_source=self.runtime,
            checked_in_status_source=self.checked,
            qualification_receipts=self.receipts,
            artifacts={},
            crash_receipts=self.crash,
        )

    def test_exact_runtime_status_and_receipts_close_repository_readiness(self) -> None:
        value = self.build()
        self.assertTrue(value["readiness"]["repository_controlled_ready"])
        self.assertTrue(value["readiness"]["runtime_status_exact"])
        self.assertFalse(value["readiness"]["external_rollback_anchor_ready"])
        self.assertFalse(value["readiness"]["production_activation"])
        self.assertFalse(value["readiness"]["release_approved"])
        self.assertIn("real_merge_sha_not_requalified", value["blockers"])

    def test_runtime_status_must_match_exact_tested_commit_and_tree(self) -> None:
        self.write_runtime_status("f" * 40, TREE)
        value = self.build()
        self.assertFalse(value["readiness"]["runtime_status_exact"])
        self.assertFalse(value["readiness"]["repository_controlled_ready"])
        self.assertIn("runtime_status_source_identity", value["blockers"])

    def test_old_or_weak_receipt_cannot_pass(self) -> None:
        path = self.receipts["metadata"]
        weak = json.loads(path.read_text(encoding="utf-8"))
        weak["schemaVersion"] = 1
        weak.pop("sourceHeadTree")
        path.write_text(json.dumps(weak) + "\n", encoding="utf-8")
        value = self.build()
        self.assertFalse(value["readiness"]["metadata_qualified"])
        self.assertFalse(value["readiness"]["repository_controlled_ready"])


if __name__ == "__main__":
    unittest.main()

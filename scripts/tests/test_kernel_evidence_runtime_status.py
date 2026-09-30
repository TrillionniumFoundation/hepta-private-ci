from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import kernel_evidence_runtime_status as runtime_status


SOURCE = "a" * 40
TREE = "b" * 40
BASE = "c" * 40
MERGE = "d" * 40
WORKFLOW = "e" * 40
RUN_ID = "12345"
RUN_ATTEMPT = "2"
RUNNER = "ubuntu24-20260930"
TARGET = "x86_64-unknown-linux-gnu"


class RuntimeStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.checked = self.root / "STATUS_SOURCE.json"
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
        for kind in runtime_status.QUALIFICATION_KINDS:
            path = self.root / f"{kind}.json"
            path.write_text(json.dumps(self.receipt(kind)) + "\n", encoding="utf-8")
            self.receipts[kind] = path
        self.crash_summary = self.root / "crash-summary.json"
        self.crash_summary.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "module": "kernel.evidence",
                    "receiptKind": "crash_consistency_matrix",
                    "sourceHeadSha": SOURCE,
                    "sourceHeadTree": TREE,
                    "baseSha": BASE,
                    "workflowSha": WORKFLOW,
                    "workflowRunId": RUN_ID,
                    "workflowRunAttempt": RUN_ATTEMPT,
                    "runnerImage": RUNNER,
                    "targetTriple": TARGET,
                    "passed": True,
                    "scenarioCount": 12,
                    "requiredScenarioCount": 12,
                    "targetHostAcceptanceGranted": False,
                    "productionActivationGranted": False,
                    "releaseGranted": False,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def receipt(kind: str) -> dict[str, object]:
        merge = MERGE if kind == "deterministic_merge" else None
        tested = MERGE if kind == "deterministic_merge" else SOURCE
        return {
            "schemaVersion": 2,
            "module": "kernel.evidence",
            "receiptKind": "candidate_qualification",
            "kind": kind,
            "sourceHeadSha": SOURCE,
            "sourceHeadTree": TREE,
            "baseSha": BASE,
            "deterministicMergeSha": merge,
            "testedObjectSha": tested,
            "workflowSha": WORKFLOW,
            "workflowRunId": RUN_ID,
            "workflowRunAttempt": RUN_ATTEMPT,
            "runnerImage": RUNNER,
            "targetTriple": TARGET,
            "command": "governed command",
            "startedAtUnixMs": 100,
            "finishedAtUnixMs": 200,
            "exitCode": 0,
            "status": "passed",
            "passed": True,
            "logSha256": "3" * 64,
            "qualificationGranted": False,
            "independentAcceptanceGranted": False,
            "productionActivationGranted": False,
            "releaseGranted": False,
        }

    def build(self) -> dict[str, object]:
        return runtime_status.build_status(
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
            checked_in_status_source=self.checked,
            qualification_receipts=self.receipts,
            crash_summary=self.crash_summary,
        )

    def rewrite_receipt(self, kind: str, **changes: object) -> None:
        value = json.loads(self.receipts[kind].read_text(encoding="utf-8"))
        value.update(changes)
        self.receipts[kind].write_text(json.dumps(value) + "\n", encoding="utf-8")

    def rewrite_crash_summary(self, **changes: object) -> None:
        value = json.loads(self.crash_summary.read_text(encoding="utf-8"))
        value.update(changes)
        self.crash_summary.write_text(json.dumps(value) + "\n", encoding="utf-8")

    def test_one_exact_receipt_set_closes_repository_controlled_status(self) -> None:
        value = self.build()
        self.assertTrue(value["exactSourceQualified"])
        self.assertTrue(value["mergeCandidateQualified"])
        self.assertTrue(value["metadataQualified"])
        self.assertTrue(value["publicationDiagnosticsQualified"])
        self.assertTrue(value["crashMatrixQualified"])
        self.assertTrue(value["repositoryControlledReady"])
        self.assertFalse(value["finalMergeRequalified"])
        self.assertFalse(value["externalFrontierActive"])
        self.assertFalse(value["releaseApproved"])

    def test_receipts_from_another_attempt_cannot_be_mixed(self) -> None:
        self.rewrite_receipt("metadata", workflowRunAttempt="3")
        value = self.build()
        self.assertFalse(value["metadataQualified"])
        self.assertFalse(value["repositoryControlledReady"])
        self.assertEqual(
            value["qualificationReceipts"]["metadata"]["error"],
            "receipt identity, execution, or authority boundary is not exact",
        )

    def test_tree_base_workflow_runner_and_target_are_exact(self) -> None:
        fields = (
            ("sourceHeadTree", "f" * 40),
            ("baseSha", "0" * 40),
            ("workflowSha", "9" * 40),
            ("workflowRunId", "999"),
            ("runnerImage", "another-runner"),
            ("targetTriple", "aarch64-unknown-linux-gnu"),
        )
        for field, value in fields:
            with self.subTest(field=field):
                self.setUp_receipts_to_exact()
                self.rewrite_receipt("exact_source", **{field: value})
                status = self.build()
                self.assertFalse(status["exactSourceQualified"])
                self.assertFalse(status["repositoryControlledReady"])

    def setUp_receipts_to_exact(self) -> None:
        for kind, path in self.receipts.items():
            path.write_text(json.dumps(self.receipt(kind)) + "\n", encoding="utf-8")

    def test_merge_receipt_must_test_the_deterministic_merge_object(self) -> None:
        self.rewrite_receipt("deterministic_merge", testedObjectSha=SOURCE)
        value = self.build()
        self.assertFalse(value["mergeCandidateQualified"])
        self.assertFalse(value["repositoryControlledReady"])

    def test_crash_summary_cannot_come_from_another_run_or_runner(self) -> None:
        for field, replacement in (
            ("workflowRunId", "999"),
            ("workflowRunAttempt", "3"),
            ("runnerImage", "other-runner"),
            ("targetTriple", "other-target"),
        ):
            with self.subTest(field=field):
                self.rewrite_crash_summary(**{field: replacement})
                value = self.build()
                self.assertFalse(value["crashMatrixQualified"])
                self.assertFalse(value["repositoryControlledReady"])
                self.rewrite_crash_summary(
                    workflowRunId=RUN_ID,
                    workflowRunAttempt=RUN_ATTEMPT,
                    runnerImage=RUNNER,
                    targetTriple=TARGET,
                )


if __name__ == "__main__":
    unittest.main()

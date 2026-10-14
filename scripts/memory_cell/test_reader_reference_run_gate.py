"""No trained Reader or model result is forged by partial artifact ZIPs."""

import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from reader_reference_run_gate import admit_run, main


EXPECTED_SHA = "a" * 40
RUN_ID = 111
INPUT = dict(id=555, sha="4" * 64)


def fixture(conclusion="success"):
    run = dict(
        id=RUN_ID,
        name="MemoryCell fixed reader reference experiment",
        head_sha=EXPECTED_SHA,
        run_attempt=1,
        status="completed",
        conclusion=conclusion,
    )
    artifacts = [
        dict(
            id=20 + i,
            name=name,
            size_in_bytes=1000 + i,
            digest="sha256:" + str(i + 1) * 64,
            expired=False,
            workflow_run=dict(head_sha=EXPECTED_SHA),
        )
        for i, name in enumerate(
            (
                "memory-reader-reference-smol-1.7b",
                "memory-reader-reference-qwen-3b",
            )
        )
    ]
    return run, dict(total_count=len(artifacts), artifacts=artifacts)


def audit(run, artifacts):
    return admit_run(
        run,
        artifacts,
        expected_run_id=RUN_ID,
        expected_source=EXPECTED_SHA,
        inputs=INPUT,
    )


class ReaderReferenceAdmissionTests(unittest.TestCase):
    def test_only_two_complete_pinned_reader_artifacts_can_replay(self):
        run, artifacts = fixture()
        out = audit(run, artifacts)
        self.assertTrue(out["eligible_for_complete_replay"])
        self.assertEqual(out["replay_download_pins"]["inputs"], INPUT)
        self.assertEqual(out["replay_download_pins"]["qwen"]["id"], 21)
        self.assertFalse(out["production_accepted"])

    def test_model_failure_stays_blocked_even_with_both_zips(self):
        run, artifacts = fixture("failure")
        result = audit(run, artifacts)
        self.assertFalse(result["eligible_for_complete_replay"])
        self.assertEqual(result["blocked_reasons"], ["generating_run_not_successful"])
        self.assertIsNone(result["replay_download_pins"])
        self.assertEqual(result["required_model_artifacts"]["qwen"]["id"], 21)

    def test_cancelled_or_pending_model_cannot_be_replayed(self):
        for status, conclusion in (
            ("completed", "cancelled"),
            ("in_progress", None),
        ):
            run, artifacts = fixture()
            run["status"], run["conclusion"] = status, conclusion
            with self.subTest(status=status):
                self.assertFalse(audit(run, artifacts)["eligible_for_complete_replay"])

    def test_missing_or_expired_artifact_stays_in_failure_census(self):
        run, artifacts = fixture()
        artifacts["artifacts"].pop()
        artifacts["total_count"] = 1
        result = audit(run, artifacts)
        self.assertFalse(result["eligible_for_complete_replay"])
        self.assertTrue(result["blocked_reasons"][0].startswith("missing_"))
        self.assertIsNone(result["required_model_artifacts"]["qwen"])
        run, artifacts = fixture()
        artifacts["artifacts"][1]["expired"] = True
        self.assertFalse(audit(run, artifacts)["eligible_for_complete_replay"])

    def test_forged_model_identity_or_run_source_is_rejected(self):
        for change in ("head", "id", "run_attempt", "tier"):
            run, artifacts = fixture()
            if change == "head":
                run["head_sha"] = "b" * 40
            elif change == "id":
                run["id"] = 112
            elif change == "run_attempt":
                run["run_attempt"] = 2
            else:
                run["name"] = "another workflow"
            with self.subTest(change=change), self.assertRaises(ValueError):
                audit(run, artifacts)

    def test_bad_digest_duplicate_or_cross_sha_fails_closed(self):
        for change in ("digest", "duplicate", "cross-sha", "zero-size"):
            run, artifacts = fixture()
            if change == "digest":
                artifacts["artifacts"][0]["digest"] = "sha256:invalid"
            elif change == "duplicate":
                artifacts["artifacts"][1]["id"] = 20
            elif change == "cross-sha":
                artifacts["artifacts"][0]["workflow_run"]["head_sha"] = "b" * 40
            else:
                artifacts["artifacts"][1]["size_in_bytes"] = 0
            with self.subTest(change=change), self.assertRaises(ValueError):
                audit(run, artifacts)

    def test_cli_writes_failure_receipt_before_refusing_download(self):
        run, artifacts = fixture("failure")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run.json").write_text(json.dumps(run))
            (root / "metadata.json").write_text(json.dumps(artifacts))
            args = [
                "reader_reference_run_gate.py",
                "--run",
                str(root / "run.json"),
                "--artifacts",
                str(root / "metadata.json"),
                "--report",
                str(root / "blocked.json"),
                "--downloads",
                str(root / "downloads.tsv"),
                "--pins",
                str(root / "external-pins.json"),
                "--expected-id",
                str(RUN_ID),
                "--expected-source",
                EXPECTED_SHA,
                "--inputs-id",
                str(INPUT["id"]),
                "--inputs-sha256",
                INPUT["sha"],
            ]
            with (
                patch("sys.argv", args),
                self.assertRaisesRegex(
                    SystemExit, "Unqualified original model execution"
                ),
            ):
                main()
            report = json.loads((root / "blocked.json").read_text())
            self.assertFalse(report["eligible_for_complete_replay"])
            self.assertFalse((root / "downloads.tsv").exists())
            self.assertFalse((root / "external-pins.json").exists())
            self.assertEqual(
                report["blocked_reasons"], ["generating_run_not_successful"]
            )

    def test_extra_untrusted_artifacts_cannot_overwrite_required_names(self):
        run, artifacts = fixture()
        artifacts["artifacts"].append(dict(artifacts["artifacts"][0]))
        artifacts["total_count"] = 3
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            audit(run, artifacts)


if __name__ == "__main__":
    unittest.main()

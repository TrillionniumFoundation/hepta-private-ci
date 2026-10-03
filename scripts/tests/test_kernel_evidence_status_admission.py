"""Test final qualification, artifact binding and durable status publication."""

import argparse
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_kernel_evidence_status as status
import test_kernel_evidence_record_validation as record_tests


class StatusAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = record_tests.ExecutionRecordTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.identity = self.fixture.identity
        self.env = {
            "SOURCE_SHA": "a" * 40,
            "TESTED_SHA": "a" * 40,
            "BASE_SHA": "b" * 40,
            "HEPTA_CI_LANE": "source-head",
            "GITHUB_RUN_ID": "100",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_JOB": "source-head",
            "GITHUB_REPOSITORY": "org/repo",
            "GITHUB_WORKFLOW": "Kernel evidence convergence",
            "GITHUB_EVENT_NAME": "pull_request",
        }
        self.environment = mock.patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.candidate = mock.patch.object(
            status, "candidate_identity", return_value=self.identity
        )
        self.candidate.start()
        self.addCleanup(self.candidate.stop)
        self.git_patch = mock.patch.object(status, "git", side_effect=self.git)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)
        self.args = argparse.Namespace(
            artifact_id="77",
            artifact_url="https://github.com/org/repo/actions/runs/100/artifacts/77",
            artifact_digest="sha256:" + "d" * 64,
        )
        self.artifact = status.normalize_artifact(self.args)
        self.write_records()

    def git(self, *args):
        if args == ("rev-parse", "--show-toplevel"):
            return str(self.root)
        if args[:2] == ("merge-tree", "--write-tree"):
            return self.identity["tree"]
        raise AssertionError(f"unexpected Git command: {args}")

    def write_records(self):
        for name, command in status.EXPECTED_COMMANDS.items():
            record = copy.deepcopy(self.fixture.record)
            record["command"] = command
            (self.root / name).write_text(json.dumps(record), encoding="utf-8")

    def build(self, artifact=True, kind="kernel_evidence_exact_source"):
        return status.build_status(
            self.root, kind=kind, artifact=self.artifact if artifact else None
        )

    def test_retained_exact_source_can_qualify_execution_only(self):
        result = self.build()
        self.assertTrue(result["qualified"], result)
        self.assertTrue(result["exactSourceQualified"])
        self.assertFalse(result["mergeCandidateQualified"])
        for gate in (
            "independentAcceptance",
            "externalFrontierActive",
            "backupRestoreDrilled",
            "canaryAccepted",
            "releaseApproved",
        ):
            self.assertIs(result[gate], False)

    def test_unretained_execution_is_never_final_qualification(self):
        result = self.build(artifact=False)
        self.assertTrue(result["executionPassed"])
        self.assertFalse(result["receiptRetained"])
        self.assertFalse(result["qualified"])
        self.assertFalse(result["exactSourceQualified"])

    def test_missing_record_is_preserved_as_failed_diagnostic(self):
        (self.root / "evidence-tests.json").unlink()
        result = self.build()
        self.assertFalse(result["qualified"])
        self.assertEqual(result["checks"]["evidence-tests"]["status"], "missing")
        self.assertTrue(result["checks"]["docs"]["passed"])

    def test_log_replacement_revokes_final_qualification(self):
        (self.root / "execution.log").write_bytes(b"replacement\n")
        self.assertFalse(self.build()["qualified"])

    def test_dirty_checkout_cannot_qualify(self):
        self.identity["dirty"] = True
        self.assertFalse(self.build()["qualified"])

    def test_missing_run_attempt_or_job_cannot_qualify(self):
        for key in (
            "GITHUB_RUN_ID",
            "GITHUB_RUN_ATTEMPT",
            "GITHUB_JOB",
            "GITHUB_REPOSITORY",
        ):
            with self.subTest(key=key), mock.patch.dict(os.environ, {key: ""}):
                self.assertFalse(self.build()["qualified"])

    def test_artifact_is_bound_to_repository_run_and_id(self):
        original = self.args.artifact_url
        for url in (
            original.replace("org/repo", "other/repo"),
            original.replace("runs/100", "runs/101"),
            original.replace("artifacts/77", "artifacts/78"),
            original + "?download=1",
            original + "#fragment",
            original.replace("https:", "http:"),
            original.replace("github.com", "github.com.evil.invalid"),
            original.replace("github.com", "user@github.com"),
            1,
        ):
            with self.subTest(url=url):
                self.args.artifact_url = url
                with self.assertRaises(ValueError):
                    status.normalize_artifact(self.args)

    def test_incomplete_artifact_tuple_cannot_be_retained(self):
        self.args.artifact_digest = None
        with self.assertRaises(ValueError):
            status.normalize_artifact(self.args)

    def test_artifact_digest_must_be_sha256(self):
        for value in ("", "x" * 64, "d" * 63, None, False):
            with self.subTest(value=value):
                self.args.artifact_digest = value
                with self.assertRaises(ValueError):
                    status.normalize_artifact(self.args)

    def test_direct_artifact_metadata_is_revalidated(self):
        self.artifact["url"] = (
            "https://github.com/other/repo/actions/runs/100/artifacts/77"
        )
        result = self.build()
        self.assertFalse(result["qualified"])
        self.assertFalse(result["receiptRetained"])

    def test_boolean_artifact_id_is_rejected(self):
        self.artifact["id"] = True
        self.assertFalse(self.build()["qualified"])

    def test_merge_tree_is_recomputed_not_just_parent_checked(self):
        self.identity.update(commit="e" * 40, parents=["b" * 40, "a" * 40])
        os.environ.update(TESTED_SHA="e" * 40, HEPTA_CI_LANE="base-merge")
        for name in status.EXPECTED_RECORDS:
            record = json.loads((self.root / name).read_text())
            record.update(
                tested_sha="e" * 40,
                lane="base-merge",
                before=self.identity,
                after=self.identity,
                recomputed_merge_tree=self.identity["tree"],
            )
            (self.root / name).write_text(json.dumps(record))
        result = self.build(kind="kernel_evidence_synthetic_merge")
        self.assertTrue(result["mergeCandidateQualified"], result)
        self.assertFalse(result["exactSourceQualified"])
        with mock.patch.object(
            status,
            "git",
            side_effect=lambda *args: (
                "f" * 40 if args[0] == "merge-tree" else str(self.root)
            ),
        ):
            self.assertFalse(
                self.build(kind="kernel_evidence_synthetic_merge")["qualified"]
            )

    def test_atomic_write_round_trip(self):
        path = self.root / "status.json"
        value = {"qualified": False, "asOfCommit": "a" * 40}
        status.atomic_write_json(path, value)
        self.assertEqual(json.loads(path.read_text()), value)
        self.assertEqual(list(self.root.glob(".status.json.*.tmp")), [])

    def test_fsync_failure_before_replace_preserves_previous_status(self):
        path = self.root / "status.json"
        path.write_text('{"qualified":false}\n')
        with mock.patch.object(status.os, "fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                status.atomic_write_json(path, {"qualified": True})
        self.assertEqual(json.loads(path.read_text()), {"qualified": False})
        self.assertEqual(list(self.root.glob(".status.json.*.tmp")), [])

    def test_nonfinite_status_is_not_published(self):
        path = self.root / "status.json"
        with self.assertRaises(ValueError):
            status.atomic_write_json(path, {"invalid": float("nan")})
        self.assertFalse(path.exists())

    def test_final_status_cli_fails_closed_but_preserves_receipt(self):
        args = argparse.Namespace(
            records=self.root,
            kind="kernel_evidence_exact_source",
            output=self.root / "status.json",
            artifact_id=self.args.artifact_id,
            artifact_url=self.args.artifact_url,
            artifact_digest=self.args.artifact_digest,
            require_qualified=False,
        )
        (self.root / "evidence-tests.json").unlink()
        with (
            mock.patch.object(status, "parse_args", return_value=args),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(status.main(), 1)
        self.assertFalse(json.loads(args.output.read_text())["qualified"])


if __name__ == "__main__":
    unittest.main()

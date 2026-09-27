"""Test receipt/CI control flow only; mocked Cargo is not native test evidence."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "bao_qualify", Path(__file__).with_name("qualify.py")
)
qualify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualify)
PAIR_SPEC = importlib.util.spec_from_file_location(
    "bao_pair_receipts", Path(__file__).with_name("pair_receipts.py")
)
pair_receipts = importlib.util.module_from_spec(PAIR_SPEC)
PAIR_SPEC.loader.exec_module(pair_receipts)
HEAD = "a" * 40
TREE = "b" * 40
MERGE = "c" * 40
MERGE_TREE = "d" * 40
DIGEST = "e" * 64


class QualificationTests(unittest.TestCase):
    def execute(self, statuses, expected=HEAD, dirty="", role="source-head"):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"

            def fake_git(*args):
                if args == ("rev-parse", "HEAD"):
                    return HEAD
                if args == ("rev-parse", "HEAD^{tree}"):
                    return TREE
                return dirty

            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                code = statuses[len(calls) - 1]
                kwargs["stdout"].write(f"synthetic gate status {code}\n".encode())
                return subprocess.CompletedProcess(command, code)

            runtime = {
                "toolchain": {"rustc": "rustc synthetic", "cargo": "cargo synthetic"},
                "os": "synthetic-os",
                "architecture": "synthetic-arch",
            }
            provider = {
                "providerBinarySha256": DIGEST,
                "providerSourceCommit": "f" * 40,
                "providerEvidenceSha256": DIGEST,
            }
            argv = [
                "qualify.py",
                "--expected-sha",
                expected,
                "--candidate-role",
                role,
                "--output",
                str(output),
            ]
            with (
                patch.object(qualify, "git", side_effect=fake_git),
                patch.object(qualify.subprocess, "run", side_effect=fake_run),
                patch.object(qualify, "runtime_identity", return_value=runtime),
                patch.object(qualify, "provider_identity", return_value=provider),
                patch.object(qualify, "sha256_file", return_value=DIGEST),
                patch("sys.argv", argv),
            ):
                code = qualify.main()
            return code, calls, json.loads(
                (output / "receipt.json").read_text(encoding="utf-8")
            )

    def test_all_checks_run_when_format_fails(self):
        code, calls, receipt = self.execute([1, 0, 0, 0])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 4)
        self.assertEqual(
            [row["exitCode"] for row in receipt["checks"]], [1, 0, 0, 0]
        )
        self.assertFalse(receipt["passed"])

    def test_lint_failure_is_not_a_pass(self):
        code, calls, receipt = self.execute([0, 0, 1, 0])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 4)
        self.assertFalse(receipt["passed"])

    def test_wrong_source_and_dirty_source_cannot_pass(self):
        for expected, dirty in [("c" * 40, ""), (HEAD, " M src/lib.rs")]:
            code, _, receipt = self.execute([0, 0, 0, 0], expected, dirty)
            self.assertEqual(code, 1)
            self.assertFalse(receipt["identityClean"])

    def test_clean_all_pass_records_complete_candidate_identity(self):
        code, _, receipt = self.execute([0, 0, 0, 0])
        self.assertEqual(code, 0)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["schema"], "hepta.secrets-native-feedback.v2")
        identity = receipt["candidateIdentity"]
        self.assertEqual((identity["commitSha"], identity["treeSha"]), (HEAD, TREE))
        for field in (
            "toolchain",
            "os",
            "architecture",
            "dependencyLockSha256",
            "providerBinarySha256",
            "manifestSha256",
        ):
            self.assertIn(field, identity)
        self.assertFalse(receipt["providerDynamicE2E"])
        self.assertFalse(receipt["productionExecutionProved"])
        self.assertFalse(receipt["releaseAuthority"])

    def candidate_receipt(self, role, commit, tree):
        return {
            "schema": "hepta.secrets-native-feedback.v2",
            "identityClean": True,
            "passed": True,
            "productionExecutionProved": False,
            "independentAcceptance": False,
            "releaseAuthority": False,
            "candidateIdentity": {
                "role": role,
                "commitSha": commit,
                "treeSha": tree,
                "toolchain": {"rustc": "fixed", "cargo": "fixed"},
                "os": "fixed-os",
                "architecture": "fixed-arch",
                "dependencyLockSha256": DIGEST,
                "providerBinarySha256": DIGEST,
                "providerSourceCommit": "f" * 40,
                "providerEvidenceSha256": DIGEST,
                "manifestSha256": DIGEST,
            },
        }

    def test_pair_receipt_binds_source_merge_and_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            merge = root / "merge.json"
            source.write_text(
                json.dumps(self.candidate_receipt("source-head", HEAD, TREE)),
                encoding="utf-8",
            )
            merge.write_text(
                json.dumps(
                    self.candidate_receipt("synthetic-merge", MERGE, MERGE_TREE)
                ),
                encoding="utf-8",
            )
            receipt, failures = pair_receipts.paired_receipt(source, merge, HEAD)
            self.assertEqual(failures, [])
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["sourceCommitSha"], HEAD)
            self.assertEqual(receipt["sourceTreeSha"], TREE)
            self.assertEqual(receipt["syntheticMergeSha"], MERGE)
            self.assertEqual(receipt["syntheticMergeTreeSha"], MERGE_TREE)
            self.assertEqual(receipt["dependencyLockSha256"], DIGEST)
            self.assertIn("sourceHead", receipt["toolchain"])

    def test_pair_receipt_rejects_failed_or_drifted_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_receipt = self.candidate_receipt("source-head", HEAD, TREE)
            merge_receipt = self.candidate_receipt(
                "synthetic-merge", MERGE, MERGE_TREE
            )
            merge_receipt["passed"] = False
            merge_receipt["candidateIdentity"]["manifestSha256"] = "0" * 64
            source = root / "source.json"
            merge = root / "merge.json"
            source.write_text(json.dumps(source_receipt), encoding="utf-8")
            merge.write_text(json.dumps(merge_receipt), encoding="utf-8")
            receipt, failures = pair_receipts.paired_receipt(source, merge, HEAD)
            self.assertTrue(failures)
            self.assertFalse(receipt["passed"])

    def test_workflow_jobs_do_not_depend_on_document_success(self):
        workflow = (
            qualify.ROOT / ".github/workflows/lane-a-foundation.yml"
        ).read_text(encoding="utf-8")
        for variant in ("head", "merge"):
            block = workflow.split(f"  secrets-native-{variant}:\n", 1)[1].split(
                "\n  secrets-native-", 1
            )[0]
            self.assertNotIn("continue-on-error", block)
            self.assertIn("--expected-sha", block)
            self.assertIn("if-no-files-found: error", block)
        self.assertIn("Verify current implementation, traceability and nonclaims", workflow)
        self.assertIn("Construct deterministic synthetic merge", workflow)


if __name__ == "__main__":
    unittest.main()

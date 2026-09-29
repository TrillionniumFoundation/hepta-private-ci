"""Adversarial verifier fixtures, not evidence that Rust or product tests passed."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import evidence_inventory as inventory
import run_qualification as qualification
import verify_receipts as verifier


class ReceiptVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / "source"
        self.root.mkdir()
        self.evidence = self.directory / "evidence"
        self.evidence.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@invalid.example")
        (self.root / "base").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "change").write_text("source\n")
        self.git("add", ".")
        self.git("commit", "-m", "source")
        self.source = self.git("rev-parse", "HEAD")
        self.execution = {"workflow_sha": self.source,
                          "workflow_ref": "fixture/repository/.github/workflows/qualification.yml@refs/heads/main",
                          "run_id": "7", "run_attempt": "2"}
        self.identities = {kind: qualification.resolve_candidate(self.root, self.source, self.base, kind)
                           for kind in verifier.KINDS}
        self.receipts = {}
        self.artifacts = {}
        for group in qualification.GROUPS:
            for kind in verifier.KINDS:
                name = f"cognitive-types-{group}-{kind}-{self.source}-2"
                artifact = self.evidence / name
                artifact.mkdir()
                output = self.directory / "original-runner-output" / name
                checks = []
                for check_name, argv, cwd in qualification.command_plan(self.root, group, output):
                    log = artifact / (check_name + ".log")
                    log.write_text("synthetic verifier fixture; no production execution\n")
                    checks.append({"name": check_name, "argv": argv, "cwd": str(cwd),
                                   "status": "passed", "exit_code": 0, "error": None,
                                   "started_unix_ns": 1, "finished_unix_ns": 2,
                                   "log": log.name, "log_sha256": verifier.file_digest(log)})
                checks.append({"name": "clean-tree", "status": "passed", "exit_code": 0, "porcelain": ""})
                receipt = {"schema": "hepta.cognitive-types.readonly-execution.v1",
                           "check_plan_version": qualification.CHECK_PLAN_VERSION,
                           "group": group, **self.identities[kind], **self.execution,
                           "qualification_passed": True, "product_acceptance": False,
                           "activation": False, "release": False, "source_worktree": str(self.root),
                           "evidence_directory": str(output), "python_executable": sys.executable,
                           "runner_image": {"os": "fixture-os", "version": "fixture-version", "platform": "fixture"},
                           "checks": checks}
                if group == "native":
                    (artifact / "quality-receipt.json").write_text('{"fixture": "no Rust execution"}\n')
                    (artifact / "mutations").mkdir()
                    (artifact / "mutations/mutation-receipt.json").write_text('{"fixture": "no mutants executed"}\n')
                receipt["evidence_files"] = inventory.collect_inventory(artifact)
                receipt["cargo_target_directory"] = str(output.parent / "cognitive-types-cargo-target")
                self.artifacts[group, kind] = artifact
                self.receipts[group, kind] = receipt
                self.write_receipt(artifact, receipt)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def write_receipt(self, artifact, receipt):
        raw = (json.dumps(receipt, sort_keys=True) + "\n").encode()
        (artifact / "receipt.json").write_bytes(raw)
        (artifact / "receipt.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")

    def verify(self):
        return verifier.verify_matrix(self.root, self.evidence, self.source, self.base, self.execution)

    def assert_resealed_change_rejected(self, change, group="native", kind="exact-head"):
        original = self.receipts[group, kind]
        value = copy.deepcopy(original)
        change(value)
        artifact = self.artifacts[group, kind]
        self.write_receipt(artifact, value)
        try:
            with self.assertRaises(verifier.EvidenceError):
                self.verify()
        finally:
            self.write_receipt(artifact, original)

    def test_complete_matrix_is_consistent_without_product_promotion_or_checkout(self):
        head = self.git("rev-parse", "HEAD")
        report = self.verify()
        self.assertTrue(report["qualification_passed"])
        self.assertEqual(len(report["receipts"]), 6)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("status", "--porcelain"), "")
        for key in ("product_acceptance", "activation", "release"):
            self.assertIs(report[key], False)
        self.assertNotEqual(self.identities["exact-head"]["candidate_commit"],
                            self.identities["synthetic-merge"]["candidate_commit"])

    def test_missing_artifact_is_not_qualification(self):
        shutil.rmtree(self.artifacts["owners", "synthetic-merge"])
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_extra_duplicate_artifact_is_rejected(self):
        shutil.copytree(self.artifacts["native", "exact-head"], self.evidence / "duplicate")
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_every_group_rejects_incomplete_or_duplicate_checks(self):
        for group in qualification.GROUPS:
            for kind in verifier.KINDS:
                for action in (lambda r: r["checks"].pop(0),
                               lambda r: r["checks"].append(copy.deepcopy(r["checks"][0])),
                               lambda r: r["checks"].reverse()):
                    with self.subTest(group=group, kind=kind):
                        self.assert_resealed_change_rejected(action, group, kind)

    def test_resealed_identity_substitutions_are_rejected(self):
        substitutions = {"source_commit": "1" * 40, "source_tree": "2" * 40,
                         "base_commit": "3" * 40, "base_tree": "4" * 40,
                         "candidate_commit": "5" * 40, "candidate_tree": "6" * 40,
                         "workflow_sha": "7" * 40, "workflow_ref": "other-workflow",
                         "run_id": "8", "run_attempt": "1", "group": "owners",
                         "candidate_kind": "synthetic-merge", "identity_valid": 1,
                         "check_plan_version": True}
        for key, value in substitutions.items():
            with self.subTest(field=key):
                self.assert_resealed_change_rejected(lambda r: r.update({key: value}))
        self.assert_resealed_change_rejected(lambda r: r["parents"].reverse(), kind="synthetic-merge")

    def test_success_label_does_not_hide_failed_or_unexecuted_command(self):
        for status in ("failed", "skipped", "pending", "queued", "cancelled", "infrastructure_invalid"):
            with self.subTest(status=status):
                self.assert_resealed_change_rejected(lambda r: r["checks"][0].update(status=status))
        for code in (1, None, False, "0"):
            with self.subTest(exit_code=code):
                self.assert_resealed_change_rejected(lambda r: r["checks"][0].update(exit_code=code))
        self.assert_resealed_change_rejected(lambda r: r["checks"][0].update(error="missing executable"))

    def test_command_substitution_and_weakened_lint_are_rejected(self):
        self.assert_resealed_change_rejected(lambda r: r["checks"][0].update(argv=["true"]))
        self.assert_resealed_change_rejected(lambda r: r["checks"][0].update(cwd="/different/source"))
        self.assert_resealed_change_rejected(lambda r: r["checks"][6]["argv"].remove("warnings"))

    def test_receipt_checksum_is_verified(self):
        artifact = self.artifacts["native", "exact-head"]
        with (artifact / "receipt.json").open("ab") as stream:
            stream.write(b" ")
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_log_checksum_is_verified_even_with_passing_receipt(self):
        artifact = self.artifacts["consumers", "synthetic-merge"]
        (artifact / "package-tests.log").write_text("truncated\n")
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_missing_log_is_rejected(self):
        (self.artifacts["owners", "exact-head"] / "all-targets.log").unlink()
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_symlinked_log_is_not_evidence(self):
        log = self.artifacts["native", "exact-head"] / "format.log"
        other = self.directory / "borrowed.log"
        other.write_bytes(log.read_bytes())
        log.unlink()
        log.symlink_to(other)
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_symlinked_artifact_is_rejected(self):
        artifact = self.artifacts["native", "exact-head"]
        other = self.directory / "borrowed-artifact"
        artifact.rename(other)
        artifact.symlink_to(other, target_is_directory=True)
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_clean_tree_and_claim_boundaries_cannot_be_resealed_away(self):
        for key in ("product_acceptance", "activation", "release"):
            with self.subTest(claim=key):
                self.assert_resealed_change_rejected(lambda r: r.update({key: True}))
        self.assert_resealed_change_rejected(lambda r: r["checks"][-1].update(porcelain=" M source.rs"))
        self.assert_resealed_change_rejected(lambda r: r["runner_image"].pop("version"))
        self.assert_resealed_change_rejected(lambda r: r.update(evidence_directory=str(self.root / "evidence")))
        self.assert_resealed_change_rejected(lambda r: r["checks"][0].update(finished_unix_ns=0))
        self.assert_resealed_change_rejected(lambda r: r["checks"][0].update(log="../format.log"))

    def test_duplicate_json_keys_and_nonfinite_values_are_rejected(self):
        artifact = self.artifacts["native", "exact-head"]
        for raw in (b'{"checks":[],"checks":[]}', b'{"checks":NaN}'):
            with self.subTest(raw=raw):
                (artifact / "receipt.json").write_bytes(raw)
                (artifact / "receipt.sha256").write_text(hashlib.sha256(raw).hexdigest())
                with self.assertRaises(verifier.EvidenceError):
                    verifier.load_receipt(artifact)

    def test_partial_success_cannot_be_sealed_by_runner(self):
        output = self.directory / "finish"
        original = self.receipts["native", "exact-head"]
        shutil.copytree(self.artifacts["native", "exact-head"], output)
        self.assertTrue(qualification.finish_receipt(copy.deepcopy(original), output))
        for checks in ([original["checks"][0]], original["checks"][:-1],
                       original["checks"] + [original["checks"][0]]):
            with self.subTest(count=len(checks)):
                value = copy.deepcopy(original)
                value["checks"] = copy.deepcopy(checks)
                self.assertFalse(qualification.finish_receipt(value, output))
        value = copy.deepcopy(original)
        value["checks"][0]["exit_code"] = False
        self.assertFalse(qualification.finish_receipt(value, output))

    def test_auxiliary_result_tampering_is_rejected(self):
        for kind in verifier.KINDS:
            artifact = self.artifacts["native", kind]
            for name in ("quality-receipt.json", "mutations/mutation-receipt.json"):
                with self.subTest(kind=kind, name=name):
                    path = artifact / name
                    original = path.read_bytes()
                    path.write_bytes(b'{"passed":true}')
                    with self.assertRaises(verifier.EvidenceError):
                        self.verify()
                    path.write_bytes(original)
                    path.unlink()
                    with self.assertRaises(verifier.EvidenceError):
                        self.verify()
                    path.write_bytes(original)

    def test_resealed_inventory_cannot_hide_missing_required_result(self):
        artifact = self.artifacts["native", "exact-head"]
        (artifact / "quality-receipt.json").unlink()
        receipt = copy.deepcopy(self.receipts["native", "exact-head"])
        receipt["evidence_files"] = inventory.collect_inventory(artifact)
        self.write_receipt(artifact, receipt)
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_unrecorded_nested_file_and_boolean_size_are_rejected(self):
        artifact = self.artifacts["native", "exact-head"]
        extra = artifact / "mutations/extra.log"
        extra.write_text("unrecorded")
        with self.assertRaises(verifier.EvidenceError):
            self.verify()
        extra.unlink()
        self.assert_resealed_change_rejected(
            lambda r: r["evidence_files"]["files"][0].update(bytes=False))
        self.assert_resealed_change_rejected(lambda r: r.update(cargo_target_directory="/other/target"))

    def test_runner_refuses_success_when_auxiliary_evidence_is_missing(self):
        output = self.directory / "missing-auxiliary"
        shutil.copytree(self.artifacts["native", "exact-head"], output)
        (output / "mutations/mutation-receipt.json").unlink()
        receipt = copy.deepcopy(self.receipts["native", "exact-head"])
        self.assertFalse(qualification.finish_receipt(receipt, output))
        self.assertIn("evidence_error", receipt)

    def test_dirty_verifier_checkout_is_rejected(self):
        (self.root / "change").write_text("dirty\n")
        with self.assertRaises(verifier.EvidenceError):
            self.verify()

    def test_streaming_log_digest_preserves_all_bytes_and_bounds_display(self):
        log = self.directory / "large.log"
        data = ("first\n" * 400_000 + "尾" * 9000).encode()
        log.write_bytes(data)
        self.assertEqual(qualification.file_sha256(log), hashlib.sha256(data).hexdigest())
        self.assertEqual(qualification.log_tail(log), "尾" * 8000)

    def test_log_tail_handles_empty_and_invalid_utf8(self):
        log = self.directory / "invalid.log"
        log.write_bytes(b"")
        self.assertEqual(qualification.log_tail(log), "")
        log.write_bytes(b"prefix\xfftail")
        self.assertEqual(qualification.log_tail(log), "prefix\ufffdtail")

    def test_resolution_does_not_checkout_the_merge(self):
        before = self.git("rev-parse", "HEAD")
        identity = qualification.resolve_candidate(self.root, self.source, self.base, "synthetic-merge")
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(identity, self.identities["synthetic-merge"])


if __name__ == "__main__":
    unittest.main()

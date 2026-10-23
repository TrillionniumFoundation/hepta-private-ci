"""Adversarial fixtures for fixed-candidate entrypoint evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import entrypoint_evidence as evidence


class EntrypointEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.matrix = self.root / "matrix"
        self.matrix.mkdir()
        self.source = "a" * 40
        self.base = "b" * 40
        self.run_id = "77"
        self.attempt = "2"

    def candidate(self, kind: str) -> dict:
        return {
            "schema": evidence.CANDIDATE_SCHEMA,
            "source_commit": self.source,
            "source_tree": "1" * 40,
            "base_commit": self.base,
            "base_tree": "2" * 40,
            "candidate_kind": kind,
            "candidate_commit": self.source if kind == "exact-head" else "3" * 40,
            "candidate_tree": "4" * 40,
            "parents": ["5" * 40] if kind == "exact-head" else [self.base, self.source],
            "identity_valid": True,
            "product_acceptance": False,
            "activation": False,
            "release": False,
        }

    def artifact_name(self, consumer: str, kind: str) -> str:
        return (
            f"cognitive-types-entrypoint-{consumer}-{kind}-"
            f"{self.source}-{self.attempt}"
        )

    def make_artifact(
        self,
        consumer: str,
        kind: str,
        *,
        list_exit: int = 0,
        test_exit: int = 0,
        listing: str | None = None,
        seal: bool = True,
    ) -> Path:
        directory = self.matrix / self.artifact_name(consumer, kind)
        directory.mkdir()
        candidate = self.candidate(kind)
        (directory / "candidate.json").write_text(
            json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8"
        )
        test_filter = evidence.CONSUMERS[consumer][1]
        if listing is None:
            listing = (
                f"{test_filter}::accepts_current_owner_binding: test\n"
                f"{test_filter}::rejects_stale_or_substituted_binding: test\n"
            )
        (directory / "list.log").write_text(listing, encoding="utf-8")
        (directory / "tests.log").write_text(
            "running 2 tests\ntest result: ok. 2 passed; 0 failed\n",
            encoding="utf-8",
        )
        (directory / "toolchain.log").write_text(
            "rustc 1.90.0\ncargo 1.90.0\n", encoding="utf-8"
        )
        (directory / "source-status.txt").write_bytes(b"")
        passed = evidence.write_result(
            directory / "candidate.json",
            consumer,
            directory / "list.log",
            directory / "tests.log",
            list_exit,
            test_exit,
            directory / "results.json",
        )
        self.assertEqual(
            passed,
            evidence.load_json(directory / "results.json")["execution_passed"],
        )
        if seal:
            sealed = evidence.seal_artifact(
                directory,
                self.source,
                self.base,
                kind,
                consumer,
                self.run_id,
                self.attempt,
            )
            self.assertEqual(sealed, passed)
        return directory

    def make_matrix(self, event: str = "pull_request") -> None:
        kinds = evidence.KINDS if event == "pull_request" else ("exact-head",)
        for kind in kinds:
            for consumer in evidence.CONSUMERS:
                self.make_artifact(consumer, kind)

    def verify(self, event: str = "pull_request") -> dict:
        return evidence.verify_matrix(
            self.matrix,
            self.source,
            self.base,
            event,
            self.run_id,
            self.attempt,
        )

    def reseal_receipt(self, directory: Path, receipt: dict) -> None:
        raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
        (directory / "receipt.json").write_bytes(raw)
        (directory / "receipt.sha256").write_text(
            hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii"
        )

    def test_complete_pull_request_matrix_is_verified_without_promotion(self):
        self.make_matrix()
        report = self.verify()
        self.assertTrue(report["entrypoint_evidence_passed"])
        self.assertEqual(report["artifact_count"], 10)
        for field in (
            "product_acceptance",
            "compatibility_retired",
            "activation",
            "release",
        ):
            self.assertIs(report[field], False)

    def test_push_matrix_requires_exact_head_only(self):
        self.make_matrix("push")
        report = self.verify("push")
        self.assertEqual(report["artifact_count"], 5)

    def test_zero_tests_cannot_pass_even_with_zero_exit_codes(self):
        directory = self.make_artifact(
            "cognitive.read", "exact-head", listing="0 tests, 0 benchmarks\n", seal=False
        )
        result = evidence.load_json(directory / "results.json")
        self.assertFalse(result["execution_passed"])
        self.assertEqual(result["test_count"], 0)
        self.assertFalse(
            evidence.seal_artifact(
                directory,
                self.source,
                self.base,
                "exact-head",
                "cognitive.read",
                self.run_id,
                self.attempt,
            )
        )

    def test_listing_cannot_escape_reviewed_entrypoint_module(self):
        directory = self.make_artifact(
            "cognitive.store",
            "exact-head",
            listing="v2::tests::unrelated_path: test\n",
            seal=False,
        )
        result = evidence.load_json(directory / "results.json")
        self.assertFalse(result["execution_passed"])
        self.assertIn("escaped", result["execution_error"])

    def test_nonzero_test_exit_is_retained_as_refusal(self):
        directory = self.make_artifact(
            "compact.engine", "exact-head", test_exit=101
        )
        receipt = evidence.load_receipt(directory)
        self.assertFalse(receipt["evidence_passed"])
        self.assertIsNotNone(receipt["evidence_error"])

    def test_modified_log_is_rejected_after_sealing(self):
        self.make_matrix()
        directory = next(self.matrix.iterdir())
        with (directory / "tests.log").open("a", encoding="utf-8") as stream:
            stream.write("tampered\n")
        with self.assertRaises(evidence.EvidenceError):
            self.verify()

    def test_missing_extra_or_misnamed_artifact_is_rejected(self):
        self.make_matrix()
        target = next(self.matrix.iterdir())
        target.rename(self.matrix / "wrong-name")
        with self.assertRaises(evidence.EvidenceError):
            self.verify()

    def test_resealed_claim_or_source_substitution_is_rejected(self):
        self.make_matrix()
        directory = next(self.matrix.iterdir())
        original = evidence.load_receipt(directory)
        for field, value in (
            ("product_acceptance", True),
            ("source_commit", "9" * 40),
        ):
            changed = dict(original)
            changed[field] = value
            self.reseal_receipt(directory, changed)
            with self.assertRaises(evidence.EvidenceError):
                self.verify()
            self.reseal_receipt(directory, original)

    def test_duplicate_json_keys_are_rejected(self):
        self.make_matrix()
        directory = next(self.matrix.iterdir())
        raw = b'{"schema":"x","schema":"y"}'
        (directory / "receipt.json").write_bytes(raw)
        (directory / "receipt.sha256").write_text(
            hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii"
        )
        with self.assertRaises(evidence.EvidenceError):
            self.verify()

    def test_symlinked_log_is_rejected(self):
        directory = self.make_artifact(
            "memory.retrieval", "exact-head", seal=False
        )
        log = directory / "tests.log"
        borrowed = self.root / "borrowed.log"
        borrowed.write_bytes(log.read_bytes())
        log.unlink()
        log.symlink_to(borrowed)
        with self.assertRaises(evidence.EvidenceError):
            evidence.seal_artifact(
                directory,
                self.source,
                self.base,
                "exact-head",
                "memory.retrieval",
                self.run_id,
                self.attempt,
            )

    def test_symlinked_receipt_or_checksum_is_rejected(self):
        self.make_matrix()
        directory = next(self.matrix.iterdir())
        for name in ("receipt.json", "receipt.sha256"):
            with self.subTest(name=name):
                target = directory / name
                original = target.read_bytes()
                borrowed = self.root / f"borrowed-{name}"
                borrowed.write_bytes(original)
                target.unlink()
                target.symlink_to(borrowed)
                with self.assertRaises(evidence.EvidenceError):
                    self.verify()
                target.unlink()
                target.write_bytes(original)

    def test_synthetic_merge_parent_substitution_is_rejected(self):
        directory = self.matrix / "merge"
        directory.mkdir()
        candidate = self.candidate("synthetic-merge")
        (directory / "candidate.json").write_text(json.dumps(candidate), encoding="utf-8")
        test_filter = evidence.CONSUMERS["intelligence.control"][1]
        (directory / "list.log").write_text(
            f"{test_filter}::case: test\n", encoding="utf-8"
        )
        (directory / "tests.log").write_text("ok\n", encoding="utf-8")
        (directory / "toolchain.log").write_text("rustc synthetic\n", encoding="utf-8")
        (directory / "source-status.txt").write_bytes(b"")
        evidence.write_result(
            directory / "candidate.json",
            "intelligence.control",
            directory / "list.log",
            directory / "tests.log",
            0,
            0,
            directory / "results.json",
        )
        candidate["parents"].reverse()
        (directory / "candidate.json").write_text(json.dumps(candidate), encoding="utf-8")
        self.assertFalse(
            evidence.seal_artifact(
                directory,
                self.source,
                self.base,
                "synthetic-merge",
                "intelligence.control",
                self.run_id,
                self.attempt,
            )
        )


if __name__ == "__main__":
    unittest.main()

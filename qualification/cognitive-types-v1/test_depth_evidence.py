"""Adversarial depth-evidence fixtures; no product execution is implied."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import depth_evidence as depth


class DepthEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.source = "a" * 40
        self.base = "b" * 40
        self.run_id = "77"
        self.attempt = "2"

    def candidate(self, kind: str) -> dict:
        return {
            "schema": depth.CANDIDATE_SCHEMA,
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

    def results(self, role: str, kind: str, consumer: str | None) -> dict:
        value = {
            "schema": depth.RESULT_SCHEMAS[role],
            "candidate": kind,
            "outcomes": {name: "success" for name in depth.OUTCOMES[role]},
            "activation": False,
            "release": False,
        }
        if role == "consumer":
            value.update(consumer=consumer, package=depth.CONSUMERS[consumer],
                         product_acceptance=False, compatibility_retired=False)
        elif role == "owner":
            value.update(owner_currentness_cached=False, product_acceptance=False)
        else:
            value.update(campaign_is_product_acceptance=False)
        return value

    def populate_files(self, directory: Path, role: str, seconds: str = "180") -> None:
        if role == "consumer":
            names = ("toolchain.log", "format.log", "check.log", "clippy.log", "tests.log")
        elif role == "owner":
            names = ("clippy.log", "store-writer.log", "canonical-recall.log",
                     "shared-experience.log")
        else:
            names = ("toolchain.log", "fuzz.log")
        for name in names:
            (directory / name).write_text(f"synthetic {name}; not execution evidence\n")
        if role == "fuzz":
            (directory / "campaign-seconds.txt").write_text(seconds + "\n")
            (directory / "source-status.txt").write_bytes(b"")
            (directory / "corpus").mkdir()
            (directory / "corpus/modality-span-envelope-v1").write_bytes(b"{}")

    def make_artifact(self, role: str, kind: str, consumer: str | None = None,
                      seconds: str = "180") -> Path:
        if role == "consumer":
            name = f"cognitive-types-consumer-{consumer}-{kind}-{self.source}-{self.attempt}"
        else:
            name = f"cognitive-types-{role}-{kind}-{self.source}-{self.attempt}"
        directory = self.evidence / name
        directory.mkdir()
        (directory / "candidate.json").write_text(
            json.dumps(self.candidate(kind), sort_keys=True) + "\n")
        (directory / "results.json").write_text(
            json.dumps(self.results(role, kind, consumer), sort_keys=True) + "\n")
        self.populate_files(directory, role, seconds)
        depth.seal_artifact(directory, role, self.source, self.base, kind,
                            self.run_id, self.attempt, consumer)
        return directory

    def make_matrix(self, event: str = "pull_request") -> None:
        kinds = depth.KINDS if event == "pull_request" else ("exact-head",)
        seconds = "180" if event == "pull_request" else "900"
        for kind in kinds:
            for consumer in depth.CONSUMERS:
                self.make_artifact("consumer", kind, consumer)
            self.make_artifact("owner", kind)
            self.make_artifact("fuzz", kind, seconds=seconds)

    def verify(self, event: str = "pull_request") -> dict:
        return depth.verify_matrix(self.evidence, self.source, self.base, event,
                                   self.run_id, self.attempt)

    def reseal_receipt(self, directory: Path, receipt: dict) -> None:
        raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
        (directory / "receipt.json").write_bytes(raw)
        (directory / "receipt.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")

    def test_complete_pull_request_matrix_is_verified_without_promotion(self):
        self.make_matrix()
        report = self.verify()
        self.assertTrue(report["depth_evidence_passed"])
        self.assertEqual(report["artifact_count"], 14)
        for field in ("product_acceptance", "compatibility_retired", "activation", "release"):
            self.assertIs(report[field], False)

    def test_complete_scheduled_matrix_requires_exact_head_only(self):
        self.make_matrix("schedule")
        self.assertEqual(self.verify("schedule")["artifact_count"], 7)

    def test_missing_extra_or_misnamed_artifact_is_rejected(self):
        self.make_matrix()
        target = next(self.evidence.iterdir())
        target.rename(self.evidence / "wrong-name")
        with self.assertRaises(depth.EvidenceError):
            self.verify()

    def test_modified_file_is_rejected_even_when_receipt_still_says_passed(self):
        self.make_matrix()
        target = next(self.evidence.glob("cognitive-types-consumer-*/results.json"))
        target.write_text(target.read_text() + " ")
        with self.assertRaises((depth.EvidenceError, ValueError)):
            self.verify()

    def test_resealed_source_or_claim_substitution_is_rejected(self):
        self.make_matrix()
        directory = next(self.evidence.iterdir())
        receipt = depth.load_receipt(directory)
        for key, value in (("source_commit", "9" * 40), ("product_acceptance", True)):
            changed = dict(receipt)
            changed[key] = value
            self.reseal_receipt(directory, changed)
            with self.assertRaises(depth.EvidenceError):
                self.verify()
            self.reseal_receipt(directory, receipt)

    def test_duplicate_json_keys_are_rejected(self):
        self.make_matrix()
        directory = next(self.evidence.iterdir())
        raw = b'{"schema":"x","schema":"y"}'
        (directory / "receipt.json").write_bytes(raw)
        (directory / "receipt.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")
        with self.assertRaises(depth.EvidenceError):
            self.verify()

    def test_symlinked_evidence_is_rejected(self):
        self.make_matrix()
        directory = next(self.evidence.glob("cognitive-types-consumer-*/"))
        log = directory / "tests.log"
        borrowed = self.root / "borrowed.log"
        borrowed.write_bytes(log.read_bytes())
        log.unlink()
        log.symlink_to(borrowed)
        with self.assertRaises((depth.EvidenceError, ValueError)):
            self.verify()

    def test_failed_outcome_is_sealed_as_refusal_not_pass(self):
        directory = self.make_artifact("consumer", "exact-head", "cognitive.read")
        results = self.results("consumer", "exact-head", "cognitive.read")
        results["outcomes"]["test"] = "failure"
        (directory / "results.json").write_text(json.dumps(results, sort_keys=True) + "\n")
        receipt = depth.seal_artifact(directory, "consumer", self.source, self.base,
                                      "exact-head", self.run_id, self.attempt,
                                      "cognitive.read")
        self.assertFalse(receipt["evidence_passed"])
        self.assertIsNotNone(receipt["evidence_error"])

    def test_fuzz_duration_and_clean_source_are_enforced(self):
        with self.assertRaises(depth.EvidenceError):
            self.make_artifact("fuzz", "exact-head", seconds="1")
        directory = self.evidence / "dirty"
        directory.mkdir()
        (directory / "candidate.json").write_text(json.dumps(self.candidate("exact-head")))
        (directory / "results.json").write_text(json.dumps(self.results("fuzz", "exact-head", None)))
        self.populate_files(directory, "fuzz")
        (directory / "source-status.txt").write_text(" M source.rs\n")
        with self.assertRaises(depth.EvidenceError):
            depth.seal_artifact(directory, "fuzz", self.source, self.base, "exact-head",
                                self.run_id, self.attempt)

    def test_synthetic_merge_parent_substitution_is_rejected(self):
        directory = self.evidence / "merge"
        directory.mkdir()
        candidate = self.candidate("synthetic-merge")
        candidate["parents"].reverse()
        (directory / "candidate.json").write_text(json.dumps(candidate))
        (directory / "results.json").write_text(json.dumps(self.results("owner", "synthetic-merge", None)))
        self.populate_files(directory, "owner")
        with self.assertRaises(depth.EvidenceError):
            depth.seal_artifact(directory, "owner", self.source, self.base,
                                "synthetic-merge", self.run_id, self.attempt)


if __name__ == "__main__":
    unittest.main()

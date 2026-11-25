"""Artifact and chronology counterexamples; no simulated human is admitted."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import pft_transfer_gate as gate


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        for name, raw in (
            ("parent.bin", b"parent coordinates"),
            ("child.bin", b"actual changed readout"),
            ("features.bin", b"frozen feature basis"),
        ):
            (self.root / name).write_bytes(raw)
        self.pair = gate.make_handoff(
            self.root,
            "parent.bin",
            "child.bin",
            "features.bin",
            {"dtype": "float64", "dimensions": 8},
        )
        self.digest = gate.identity(self.pair)
        self.parent = gate.identity(self.pair["parent"])
        self.feature = self.pair["parent"]["runtime"]["feature_sha256"]

    def audit(self, pair=None, digest=None):
        return gate.audit_handoff(
            self.root,
            pair or self.pair,
            digest or self.digest,
            self.parent,
            self.feature,
        )

    def test_bound_bytes_only_produce_a_loader_handoff(self):
        observed = self.audit()
        self.assertEqual(
            (observed["status"], observed["loader_status"]),
            ("ARTIFACTS_VERIFIED", "ORIGINAL_LOADER_REQUIRED"),
        )
        self.assertEqual(
            observed["candidate_sha256"], gate.identity(self.pair["candidate"])
        )
        self.assertNotIn("production_adoption", observed)

    def test_candidate_bytes_changed_after_binding(self):
        (self.root / "child.bin").write_bytes(b"different candidate")
        with self.assertRaisesRegex(ValueError, "artifact bytes changed"):
            self.audit()

    def test_rehashed_manifest_does_not_replace_independent_binding(self):
        pair = deepcopy(self.pair)
        pair["candidate"]["files"][1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "handoff changed"):
            self.audit(pair)

    def test_parent_identity_is_checked_separately(self):
        pair = deepcopy(self.pair)
        pair["candidate"]["parent"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "candidate parent"):
            self.audit(pair, gate.identity(pair))

    def test_feature_identity_and_bytes_are_both_checked(self):
        with self.assertRaisesRegex(ValueError, "feature coordinates"):
            gate.audit_handoff(self.root, self.pair, self.digest, self.parent, "0" * 64)
        (self.root / "features.bin").write_bytes(b"different coordinates")
        with self.assertRaisesRegex(ValueError, "artifact bytes changed"):
            self.audit()

    def test_omitted_candidate_checkpoint_cannot_pass(self):
        pair = deepcopy(self.pair)
        pair["candidate"]["files"].pop(1)
        with self.assertRaisesRegex(ValueError, "changed candidate checkpoint"):
            self.audit(pair, gate.identity(pair))

    def test_outside_path_and_symlink_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "inside"):
            gate.descriptor(self.root, "../outside", "base")
        (self.root / "link").symlink_to(self.root / "child.bin")
        with self.assertRaisesRegex(ValueError, "symlink"):
            gate.descriptor(self.root, "link", "weights")

    def test_counterfeit_checker_is_not_executed(self):
        source = self.root / "scripts/cell_experiments"
        source.mkdir(parents=True)
        (source / "paired_source_dispatch.py").write_text(
            "raise RuntimeError('untrusted')"
        )
        with patch.object(
            gate.subprocess, "run", side_effect=AssertionError("must not run")
        ):
            result = gate.audit_original_retention(self.root, self.root)
        self.assertEqual(result["status"], "CHECKER_SOURCE_UNAVAILABLE")
        self.assertIn("paired_source_dispatch.py", result["mismatched_or_missing"])


class FutureContradictionTests(unittest.TestCase):
    def setUp(self):
        # These are authored guard fixtures, not original enrollment evidence.
        self.record = dict(
            schema="hepta.cell-experiments.record.v1",
            origin_kind="authorized_agent_run",
            exposure="unexposed",
            split="confirmation",
            authorization=dict(training_allowed=False, evaluation_allowed=True),
        )
        self.freeze = dict(
            schema="hepta.paired-intake.freeze-observation.v1",
            study_sha256="1" * 64,
            freeze_sha256="2" * 64,
            sequence=5,
        )
        self.arrival = {
            **self.freeze,
            "schema": "hepta.paired-intake.first-observation.v1",
            "sequence": 6,
            "record_sha256": gate.identity(self.record),
        }

    def test_declarations_cannot_establish_authentication(self):
        observed = gate.reject_future_contradictions(
            self.record, self.freeze, self.arrival
        )
        self.assertEqual(observed["status"], "ORIGINAL_INTAKE_REQUIRED")

    def test_synthetic_and_exposed_records_cannot_be_real_b(self):
        for key, value in (("origin_kind", "synthetic"), ("exposure", "development")):
            with self.subTest(key=key):
                record = {**self.record, key: value}
                arrival = {**self.arrival, "record_sha256": gate.identity(record)}
                with self.assertRaisesRegex(ValueError, "cannot establish real B"):
                    gate.reject_future_contradictions(record, self.freeze, arrival)

    def test_before_freeze_equal_sequence_and_boolean_sequence_rejected(self):
        for sequence in (4, 5, True):
            with self.subTest(sequence=sequence):
                with self.assertRaisesRegex(ValueError, "does not follow"):
                    gate.reject_future_contradictions(
                        self.record, self.freeze, {**self.arrival, "sequence": sequence}
                    )

    def test_other_freeze_and_changed_record_rejected(self):
        for key, value, message in (
            ("freeze_sha256", "3" * 64, "another"),
            ("record_sha256", "4" * 64, "record changed"),
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, message):
                    gate.reject_future_contradictions(
                        self.record, self.freeze, {**self.arrival, key: value}
                    )


if __name__ == "__main__":
    unittest.main()

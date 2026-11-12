"""Keep the Q24 material owner closed to unregistered production callers."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

from rust_source_marker_support import source_marker_span


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "q24_model_proposal_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "cell_q24_model_proposal.rs"
CURRENT = AGENT + "cell_q24_model_current_owner.rs"
ADMISSION = AGENT + "cell_q24_model_proposal_admission.rs"
LANE = AGENT + "cell_q24_training_model_lane.rs"
TRAINER = AGENT + "cell_composed_q24_training_owner.rs"
BOUND = AGENT + "cell_q24_source_bound_stage.rs"
BOUNDARIES = {
    "cell_q24_model_material_owner_" + method: (LANE,)
    for method in ("create", "recover", "commit", "readback")
}
BOUNDARIES.update({
    "cell_q24_current_model_owner_" + method: (LANE,)
    for method in ("create", "recover", "commit", "readback")
})
BOUNDARIES.update({
    "learning_original_training_model_" + method: (BOUND,)
    for method in ("create", "recover", "commit", "readback")
})


class Q24ModelProposalSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in (OWNER, CURRENT, ADMISSION, LANE, TRAINER, BOUND)
        }

    def rejects(self, path, function, marker, *, within=None):
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        self.assertEqual(code.count(function), 1, function)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        assert end is not None
        if within is not None:
            function_code = code[start : end + 1]
            self.assertEqual(function_code.count(within), 1, within)
            start += function_code.index(within)
            branch_end = PROOF._rust_item_end(code, start)
            self.assertIsNotNone(branch_end)
            assert branch_end is not None
            self.assertLessEqual(branch_end, end)
            end = branch_end
        body = source[start : end + 1]
        self.assertEqual(body.count(marker), 1, marker)
        offset = start + body.index(marker)
        changed = source[:offset] + source[offset + len(marker) :]
        rows = [
            row for row in self.manifest["protected_file"] if row["path"] == path
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_model_borrows_original_lane_and_host_entrypoints_remain_closed(self):
        for identifier, expected in BOUNDARIES.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                sources = dict(self.sources)
                method = row.symbol.rsplit("::", 1)[-1]
                sources[AGENT + "unregistered_model_proposal.rs"] = (
                    f"fn extra(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())


        # The split current-material impl contains the Model owner type, but
        # both readbacks belong to its original durable journal. Reverting
        # either real call independently must reproduce the closed scanner
        # refusal, never add this file to the Model-owner caller allowlist.
        original = (ROOT / CURRENT).read_text()
        row = self.boundaries["cell_q24_model_material_owner_readback"]
        call = (
            "ProductEvaluationExecutionStoreV1::readback("
            "&mut self.journal, &admission.key(self.binding))"
        )
        for function in (
            "fn commit_current_material_or_readback<",
            "fn read_current_material<",
        ):
            with self.subTest(function=function):
                code = self.sources[CURRENT]
                self.assertEqual(code.count(function), 1)
                start = code.index(function)
                end = PROOF._rust_item_end(code, start)
                self.assertIsNotNone(end)
                assert end is not None
                first, after = source_marker_span(original, call, start, end + 1)
                reverted = (
                    original[:first]
                    + "self.journal.readback(&admission.key(self.binding))"
                    + original[after:]
                )
                sources = dict(self.sources)
                sources[CURRENT] = PROOF._strip_cfg_test_items(
                    PROOF._strip_rust_non_code(reverted)
                )
                with self.assertRaisesRegex(
                    PROOF.VerificationFailure,
                    "unresolved possible CellQ24ModelProposalOwnerV1::readback receiver",
                ):
                    PROOF._verify_boundary(ROOT, row, sources, ())

    def test_original_training_header_and_receipt_bindings_cannot_be_removed(self):
        for marker in (
            "original_binding(dataset_cut, &original) != owner_binding",
            "original.evidence_digest() != training.evidence_digest",
        ):
            with self.subTest(marker=marker):
                self.rejects(ADMISSION, "fn validate<", marker)

    def test_complete_generator_identity_and_signature_checks_cannot_be_removed(self):
        for marker in (
            "LearningEvidenceRoleV1::Generator",
            "learning_iteration_receipt_signing_bytes_v1(training)?",
            "verified.principal() != &inputs.qualification.product().generator",
            "verified.trust_digest() != cut.owners.evidence_trust_digest",
        ):
            with self.subTest(marker=marker):
                self.rejects(ADMISSION, "fn validate<", marker)

    def test_original_manifests_and_qualified_evaluation_are_required(self):
        for marker in (
            "validate_manifest(bundle, manifest)",
            "prepare_cell_learning_evaluation_v1(",
            "LearningEvaluationDispositionV1::Qualified",
            "coordinator.record(evaluation.clone(), evaluation.observed_unix_seconds)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(ADMISSION, "fn validate<", marker)

    def test_final_readback_cannot_skip_current_witness(self):
        self.rejects(OWNER, "fn decode_current(", "self.require_current()?")

    def test_commit_cannot_skip_durable_claim_completion_or_witness(self):
        for marker in (
            "self.journal.claim(key)",
            "self.journal.complete(key, payload)",
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, "fn complete_admitted(", marker)

    def test_owner_creation_cannot_skip_original_trainer(self):
        self.rejects(
            OWNER, "fn create<", "admission::owner_binding(trainer, &dataset_cut)?"
        )
        self.rejects(
            OWNER, "fn recover<", "admission::owner_binding(trainer, &dataset_cut)?"
        )

    def test_readback_preserves_original_bytes_and_timestamp(self):
        for marker in ("self.encode(at)? != bytes", "coordinator.record(receipt.clone(), at)?"):
            with self.subTest(marker=marker):
                self.rejects(ADMISSION, "fn decode(", marker)

    def test_owner_clock_cannot_be_replaced_by_request_time(self):
        for function, marker in (
            ("fn commit_or_readback<", "let now = self.now()?"),
            ("fn readback<", "self.admit(trainer, inputs, self.now()?)?"),
            ("fn now(", "SystemTime::now()"),
        ):
            with self.subTest(function=function):
                self.rejects(OWNER, function, marker)
        self.rejects(ADMISSION, "fn validate<", "&request")

    def test_shared_lane_cannot_skip_original_completion_or_exact_attestation(self):
        for function, markers in (
            ("fn in_model_lane<", (
                ".try_acquire_owned()", "self.owners.try_lock()",
                ".require_original_dataset_scope(",
                "let original = owners.read_original_completion()?",
                "work(&mut owners.training, &original, &proof)",
                "let current = owners",
                "if current.receipt != original.receipt || current.attestation != original.attestation",
            )),
            ("fn require_original_training(", (
                "inputs.training_cut.receipts.last() != Some(&completed.receipt)",
                "inputs.training_attestation != &completed.attestation",
            )),
        ):
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    self.rejects(LANE, function, marker)

    def test_current_cannot_skip_physical_bytes_second_witness_or_permanent_fence(self):
        for path in (OWNER, TRAINER):
            for marker in (
                "let before = self.witness.current()?",
                "self.journal.read_current_anchor()?",
                "let after = self.witness.current()?",
                "self.fenced = true",
            ):
                with self.subTest(path=path, marker=marker):
                    self.rejects(
                        path, "fn require_current(", marker,
                        within="if result.is_err()" if marker == "self.fenced = true" else None,
                    )


if __name__ == "__main__":
    unittest.main()

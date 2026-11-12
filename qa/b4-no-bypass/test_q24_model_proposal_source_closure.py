"""Keep the Q24 material owner closed to unregistered production callers."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


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
ADMISSION = AGENT + "cell_q24_model_proposal_admission.rs"
FACTORY = AGENT + "root_q24_model_factory.rs"
PROJECTION = AGENT + "cell_q24_model_projection.rs"
BOUNDARIES = tuple(
    "cell_q24_model_material_owner_" + method
    for method in ("create", "recover", "commit", "readback")
)


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
            for path in (OWNER, ADMISSION, FACTORY, PROJECTION)
        }

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
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

    def test_owner_entrypoints_require_original_root_factory(self):
        for identifier in BOUNDARIES:
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, (FACTORY,))
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(
                        ROOT, replace(row, product_callers=()), self.sources, ()
                    )
                sources = dict(self.sources)
                method = row.symbol.rsplit("::", 1)[-1]
                sources[AGENT + "unregistered_model_proposal.rs"] = (
                    f"fn extra(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
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
                self.rejects(PROJECTION, "fn project_original_qualified_model<", marker)

    def test_original_manifests_and_qualified_evaluation_are_required(self):
        for marker in (
            "validate_manifest(bundle, manifest)",
            "prepare_cell_learning_evaluation_v1(",
            "LearningEvaluationDispositionV1::Qualified",
            "coordinator.record(evaluation.clone(), evaluation.observed_unix_seconds)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(PROJECTION, "fn project_original_qualified_model<", marker)

    def test_final_readback_cannot_skip_current_witness(self):
        self.rejects(OWNER, "fn decode_current(", "self.require_current()?")

    def test_root_projection_requires_actual_b_borrow_and_complete_original_cut(self):
        for marker in (
            "scope.validate_snapshot(training)?",
            "original.observation.stage() != LearningIterationStageV1::Training",
            "dataset.record(receipt.clone(), receipt.observed_unix_seconds)?",
            "dataset.snapshot().head_digest != original.predecessor",
            "training_attestation: actual.training_attestation()",
            "runner: actual.runner()", "evaluation: actual.execution()",
            "qualification: actual.qualification()",
            "project_original_qualified_model(&inputs, now)?",
            "projected.cut.receipts.last() != Some(actual.receipt())",
            "proposal_binding: projected.key(owner).binding_digest.to_string()",
        ):
            with self.subTest(marker=marker):
                self.rejects(PROJECTION, "fn project_original_root_model(", marker)

    def test_commit_cannot_skip_durable_claim_completion_or_witness(self):
        for marker in (
            "self.journal.claim(&key)",
            "self.journal.complete(&key, &payload)",
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, "fn commit_or_readback<", marker)

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
        self.rejects(PROJECTION, "fn project_original_qualified_model<", "&request")


if __name__ == "__main__":
    unittest.main()

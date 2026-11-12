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

    def test_model_factory_attaches_only_the_actual_learning_b_custodian(self):
        path = AGENT + "authority_host_q24_model_b_binding.rs"
        for marker in (
            "original.require_original_learning(self)?",
            "factory.original_b.is_some()",
            "factory.profile.wire_schema() != 2",
            "serde_json::to_vec(&self.profile)",
            "factory.original_b = Some(original)",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "fn attach_original_model_b(", marker)

    def test_model_b_borrow_comes_from_the_complete_actual_root_context(self):
        path = AGENT + "authority_host_q24_evaluation_operation.rs"
        for marker in (
            "let end = self.end.min(frame_end)",
            "OriginalBRecord::inspect(&self.record, end,",
            "initial: &actual,\n                        writer_proof: &proof",
            "not_send: PhantomData",
            "Ok((value?, after, before, authorities))",
            "require_files(files, enrollment, now)?",
        ):
            with self.subTest(marker=marker):
                if marker == "require_files(files, enrollment, now)?":
                    # The final physical postcheck is independently required.
                    marker = "let now = service.original_learning_unix_seconds()?;\n            require_files(files, enrollment, now)?"
                self.rejects(path, "fn with_operation<T>(", marker)

    def test_root_model_uses_the_actual_b_callback_before_binding(self):
        path = AGENT + "authority_host_q24_model_b_transport.rs"
        for marker in (
            "request.schema != 2", "request.request_id != *next_request_id",
            "request.original_b != original.original_binding().to_string()",
            "with_original_completed_evaluation(",
            "crate::OriginalRootBEvaluationBorrowV1::writer_proof(&actual)",
            "project_original_root_model(&actual, &scope, now)",
            "material: projection.proposal_binding.clone()",
            "before.material.as_ref() != Some(&projection.proposal_binding)",
            "compare_and_set(factory.profile.store_owner(), &before, &after)",
            "original_factory_lease(service, &after)? != reply.lease",
            "owner_alive(owner_pidfd, frame_end)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "fn serve_original_b_model_request(", marker)

    def test_original_factory_cannot_bypass_b_or_extend_the_frame(self):
        path = AGENT + "authority_host_q24_model_transport.rs"
        for marker in (
            "exchange_with_original_deadline(|bytes, frame_end|",
            "original_b::serve_original_b_model_request(",
            "factory.original_b.is_some()",
            "matches!(&request.command, Command::Bind { .. })",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "fn serve_q24_model_factory_with_end(", marker)
        self.rejects(path, "fn original_factory_lease(", "service.issuer.revocations()?")

    def test_actual_root_response_precedes_the_sole_model_writer(self):
        path = AGENT + "root_q24_model_b_client.rs"
        for marker in (
            "self.fenced = true", "self.profile.require_files(&journal, &witness_file)?",
            "CellQ24ModelProposalOwnerV1::create_from_original_root(",
            "CellQ24ModelProposalOwnerV1::recover_from_original_root(",
            "after.projection != material.projection", "current.lease != bound.lease",
            "let receipt = result.map_err(original_model_error)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "fn operate_original_b(", marker)
        for marker in (
            "transport.read(&request).await", "response.original_b != request.original_b",
            "response.binding != self.profile.binding()", "response.request_id != request_id",
            "projection: response.projection", "original_root_model_key(&material)",
            "validate_reply(&command, &response.reply)?", "self.transport = Some(transport)",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "fn exchange_original_b<'a, 'read>(", marker)

    def test_root_model_projection_keeps_the_actual_training_and_qualified_b(self):
        path = AGENT + "cell_q24_model_root_admission.rs"
        for marker in (
            "original.scope().validate_snapshot(training)?", "trained != original.training_receipt()",
            "LearningEvaluationDispositionV1::Qualified", "dataset.snapshot().head_digest != trained.predecessor",
            "trained.evidence_digest", "original.projection() != &expected",
            "proposal_binding: admission.key(binding).binding_digest.to_string()",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "fn validate_original_root_material(", marker)

    def test_root_writer_cannot_skip_original_projection_or_source_postcheck(self):
        path = AGENT + "cell_q24_model_root_owner.rs"
        for function in ("create_from_original_root", "recover_from_original_root",
                         "commit_original_root", "read_original_root"):
            with self.subTest(function=function):
                self.rejects(path, "fn " + function + "(", "original.require_current_training_source()?")
        for marker in ("observed.dataset != self.dataset_cut", "observed.scope != self.scope",
                       "observed.binding != self.binding"):
            self.rejects(path, "fn admit_original_root(", marker)

    def test_commit_cannot_skip_durable_claim_completion_or_witness(self):
        for marker in (
            "self.journal.claim(&key)",
            "self.journal.complete(&key, &payload)",
        ):
            with self.subTest(marker=marker):
                self.rejects(OWNER, "fn commit_admitted(", marker)

    def test_shared_model_journal_kernels_keep_original_witness_and_pending(self):
        for function, marker in (
            ("fn create_bound(", "witness.current()?.is_some()"),
            ("fn create_bound(", "compare_and_swap(None, anchor(journal.anchor())?)"),
            ("fn recover_bound(", "compare_and_swap(Some(minimum), current)"),
            ("fn commit_or_readback<", "self.commit_admitted(&admission, now)"),
            ("fn readback<", "self.read_admitted(&admission)"),
        ):
            with self.subTest(function=function, marker=marker):
                self.rejects(OWNER, function, marker)

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

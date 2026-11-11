"""Guard original Evaluation receipt custody without assembling production ports.

These are source closure and mutation checks. Native signed-owner tests establish
behavior separately; neither suite establishes ordinary production role custody.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_evaluation_receipt_owner_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "neuron_cell_evaluation_receipt_owner.rs"
CALLERS = {
    "cell_learning_evaluation_receipt_prepare": (
        AGENT + "learning_iteration_evaluation_evidence.rs",
        AGENT + "cell_q24_model_proposal_admission.rs",
        OWNER,
    ),
    "learning_evidence_original_owner_readback": (
        AGENT + "learning_iteration_evaluation_evidence.rs",
        AGENT + "learning_iteration_generation_evidence.rs",
        OWNER,
        AGENT + "circuit_next_use_receipt_owner.rs",
        AGENT + "circuit_selection_receipt_owner.rs",
        AGENT + "cell_q24_training_source.rs",
        AGENT + "circuit_model_selection_receipt_sources.rs",
        AGENT + "neuron_cell_evaluation_qualification_sources.rs",
    ),
    "cell_completed_evaluation_readback": (OWNER,),
    "learning_original_evaluation_key": (
        AGENT + "neuron_cell_evaluation_owner.rs",
        OWNER,
        AGENT + "neuron_cell_evaluation_qualification_binding.rs",
    ),
}


class OriginalEvaluationReceiptOwnerSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.rows = [row for row in cls.manifest["protected_file"] if row["path"] == OWNER]
        cls.source = (ROOT / OWNER).read_text()
        paths = {
            path
            for identifier in CALLERS
            for path in (
                cls.boundaries[identifier].definition_path,
                *cls.boundaries[identifier].product_callers,
            )
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }

    def rejects_source(self, changed):
        self.assertTrue(self.rows)
        self.assertNotEqual(self.source, changed)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / OWNER
            target.parent.mkdir(parents=True)
            target.write_text(self.source)
            manifest = {"protected_file": self.rows}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def rejects(self, function, marker, replacement=""):
        code = PROOF._strip_rust_non_code(self.source)
        self.assertEqual(code.count(function), 1, function)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        assert end is not None
        body = self.source[start : end + 1]
        self.assertEqual(body.count(marker), 1, (function, marker))
        offset = start + body.index(marker)
        self.rejects_source(self.source[:offset] + replacement + self.source[offset + len(marker) :])

    def reject_unregistered_caller(self, row):
        method = row.symbol.rsplit("::", 1)[-1]
        call = (
            f"fn unexpected(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
            if row.receiver_type
            else f"fn unexpected() {{ {row.symbol}(); }}"
        )
        sources = dict(self.sources)
        sources[AGENT + "unregistered_evaluation_receipt_owner.rs"] = call
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, sources, ())

    def test_four_original_read_edges_have_exact_typed_registered_callers(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, inventory)
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                without_owner = tuple(path for path in callers if path != OWNER)
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(
                        ROOT, replace(row, product_callers=without_owner), self.sources, ()
                    )
                self.reject_unregistered_caller(row)

    def test_four_receipt_ports_and_stage_assembly_remain_closed(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for suffix in ("create", "recover", "attest", "readback"):
            identifier = "learning_original_evaluation_receipt_" + suffix
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, inventory)
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, ())
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                self.reject_unregistered_caller(row)
        for identifier in (
            "cell_learning_evaluation_original_readback",
            "learning_evidence_original_owner_constructor",
            "root_learning_original_stage_assembly",
        ):
            self.assertEqual(self.boundaries[identifier].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_exact_training_scope_and_enrolled_key_precede_journal_custody(self):
        for function in ("fn create(", "fn recover("):
            marker = "validate_config(&config, &key)?"
            with self.subTest(function=function):
                self.rejects(function, marker)
                statement = "let (execution, saved) = " + marker + ";"
                self.rejects(function, statement, "if false { " + statement + " }")
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(config.training.clone())?",
            "config.scope.validate_snapshot(&config.training)?",
            "coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)",
            "key.verifying_key().to_bytes() != signing.signer.verifying_key",
            "signing.signer.principal.principal_id != config.training.owners.evaluator",
            "config.training.owners.evidence_trust_digest != signing.verifier.trust_digest()",
            "config.training.request.envelope.objective_digest != signing.verifier.objective_digest()",
            "config.plan.product_plan() != &signing.plan",
            "signing.verifier.require_signer_binding(",
            "product_evaluation_execution_key_v1(",
            "config.training.head_digest.as_array()",
            "config.scope.binding().as_array()",
            "execution.binding_digest.as_array()",
            "signing.verifier.trust_digest().as_array()",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn validate_config(", marker)

    def test_original_execution_and_sealed_qualification_bind_full_recovered_history(self):
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(source.snapshot.clone())?",
            "self.config.scope.validate_snapshot(source.snapshot)?",
            "source.snapshot.request != self.config.training.request",
            "starts_with(&self.config.training.receipts)",
            "source.context.evaluator != self.config.signing.signer.principal",
            "let clock = || now()",
            "runner.readback_completed(",
            "clock: &clock,",
            "key: &self.execution,",
            "prepare_cell_learning_evaluation_v1(",
            "get(self.config.training.receipts.len())",
            ".is_some_and(|saved| saved != &receipt)",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn prepare<", marker)

    def test_current_original_sources_and_durable_pending_precede_exact_signature(self):
        for marker in (
            "if now()? >= self.config.training.request.envelope.expiry_unix_seconds",
            "let prepared = self.prepare(&mut source)?",
            "readback(source.snapshot, self.training()?)",
            "self.authenticate_roles(&source, &prepared.1, &training)?",
            "if self.prepare(&mut source)? != prepared",
            "learning_iteration_receipt_signing_bytes_v1(&prepared.0)?",
            "self.journal.commit_once(&self.saved, ||",
            "let issued_at = now()?",
            "if issued_at >= self.config.training.request.envelope.expiry_unix_seconds",
            "key.sign(&signed.signing_bytes()).to_bytes()",
            "config.verifier.verify(",
            "learning_owner_evidence::encode(&payload, &signed)",
            "self.authenticate_completed(&mut source, prepared, &bytes)",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn attest_original_completion<", marker)
        for marker in (
            "if now()? >= self.config.training.request.envelope.expiry_unix_seconds",
            "if issued_at >= self.config.training.request.envelope.expiry_unix_seconds",
        ):
            with self.subTest(deadline=marker):
                self.rejects("fn attest_original_completion<", marker, marker.replace(">=", ">"))

    def test_actual_time_full_principals_and_controller_separation_remain_required(self):
        for marker in (
            "let now = now()?",
            "config.verifier.require_signer_binding(",
            "LearningEvidenceRoleV1::Generator",
            "learning_iteration_receipt_signing_bytes_v1(self.training()?)?",
            "qualification_bundle(execution, source.context)?",
            "evaluation_signing_payload_v2(",
            "LearningEvidenceRoleV1::Evaluator",
            "generator.principal() != &source.context.generator",
            "generator.principal().principal_id != self.config.training.owners.trainer",
            "evaluator.principal() != &config.signer.principal",
            "evaluator.controller_id() != &config.signer.controller_id",
            "verify_signed_actor_separation(&generator, &evaluator, now)?",
        ):
            with self.subTest(marker=marker):
                # The Evaluator role occurs both in enrollment and verification.
                if marker == "LearningEvidenceRoleV1::Evaluator":
                    marker = "let evaluator = config.verifier.verify(\n            " + marker
                    self.rejects_source(self.source.replace(marker, "let evaluator = unchecked(", 1))
                else:
                    self.rejects("fn authenticate_roles<", marker)
        self.rejects("fn now(", "SystemTime::now()")

    def test_original_signature_readback_revalidates_sources_and_witness_before_ack(self):
        for marker in (
            "let prepared = self.prepare(&mut source)?",
            "let bytes = self.journal.read(&self.saved)?",
            "self.authenticate_completed(&mut source, prepared, &bytes)",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn readback<", marker)
        for marker in (
            "learning_owner_evidence::decode(bytes)?",
            "if payload != learning_iteration_receipt_signing_bytes_v1(&prepared.0)?",
            "readback(source.snapshot, self.training()?)",
            "if self.prepare(source)? != prepared",
            "self.authenticate_roles(source, &prepared.1, &training)?",
            ".verify(LearningEvidenceRoleV1::Evaluator, &signed, &payload, now()?)?",
            "verified.principal() != &config.signer.principal",
            "verified.controller_id() != &config.signer.controller_id",
            "signed.evidence_id != evidence_id(self.saved.binding_digest)?",
            "if self.journal.read(&self.saved)? != bytes",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn authenticate_completed<", marker)

    def test_original_execution_adapter_rejects_writes_and_substituted_namespace(self):
        for function in ("fn claim(", "fn complete("):
            with self.subTest(function=function):
                self.rejects(function, "Err(ProductEvaluationExecutionStoreErrorV1::Rejected)")
        for marker in (
            "if key != self.key",
            "return Err(ProductEvaluationExecutionStoreErrorV1::Conflict)",
            "ProductEvaluationExecutionStoreV1::readback(self.inner, key)",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn readback(", marker)

    def test_owner_cannot_generate_keys_replace_trust_or_assemble_stage_authority(self):
        for marker in (
            "SigningKey::generate",
            "SigningKey::from_bytes",
            "LearningEvidenceVerifierV1::new",
            "LearningEvidenceTrustV1",
            "File::open",
            "UnixStream::connect",
            "with_root_learning_stage_owners(",
            "LearningIterationStageOwnerPortsV1 for",
            "evaluate_or_readback(",
            "qualify_and_persist(",
            "unwrap_or",
            "permit_all",
        ):
            with self.subTest(marker=marker):
                self.rejects_source(self.source + "\n" + marker + "\n")


if __name__ == "__main__":
    unittest.main()

"""Protect complete independent NoUpdate retention without promoting it to Adopt.

These source mutations qualify only the closed caller graph and required checks.
They do not supply original owners, a deployed host or daemon/Root cold recovery.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "evaluated_retention_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CONTEXT = AGENT + "circuit_evaluated_retention_context.rs"
PUBLICATION = AGENT + "circuit_evaluated_retention_publication.rs"
RECOVERY = AGENT + "circuit_evaluated_retention_recovery.rs"
PREPARE = "fn prepare_original_circuit_evaluated_retention_v1<"
PUBLISH = "fn publish_and_retain_original_evidence("
RECOVER = "fn recover_original_circuit_evaluated_retention_v1<"
EXPECTED = {
    "learning_evaluated_retention_context": (),
    "learning_evaluated_retention_context_recover": (),
    "learning_evaluated_retention_prepare": (),
    "learning_evaluated_retention_publish": (),
    "learning_evaluated_retention_preserve_original_evidence": (),
    "learning_evaluated_retention_recover": (),
    "learning_original_training_command_client_readback": (
        AGENT + "cell_q24_no_update_stage_state.rs",
        AGENT + "circuit_learning_retained_context.rs",
        AGENT + "circuit_retained_version_state.rs",
        CONTEXT,
    ),
    "learning_original_evaluation_command_readback": (
        AGENT + "cell_q24_candidate_stage_evaluation.rs",
        CONTEXT,
    ),
}


class EvaluatedRetentionClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = start
        for _ in range(occurrence + 1):
            chosen = source.index(marker, offset, end + 1)
            offset = chosen + len(marker)
        self.verifies(path, source)
        changed = source[:chosen] + replacement + source[chosen + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure, msg=f"{function}: {marker}"):
            self.verifies(path, changed)

    def test_only_exact_original_readback_edges_are_open_and_factories_remain_closed(self):
        paths = {
            path for identifier in EXPECTED for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                receiver = f"owner: &{row.receiver_type}" if row.receiver_type else ""
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unregistered_evaluated_retention.rs"] = (
                    f"fn unexpected({receiver}) {{ {call}; }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_cold_constructor_cannot_become_new_work_or_skip_original_authentication(self):
        for function, origin, access in (
            ("fn from_original_evaluation(", "Origin::Fresh", "PublicationAccess::NewWork"),
            ("fn recover_original_evaluation(", "Origin::Readback", "PublicationAccess::Readback"),
        ):
            for marker in (
                "training: &OriginalCellQ24TrainingCommandReceiptV1",
                "evaluation: &OriginalCellEvaluationCommandReceiptV1",
                "training: training.clone()", "evaluation: evaluation.clone()",
                f"origin: {origin}", f"context.authenticate(now()?, {access})?",
            ):
                with self.subTest(function=function, marker=marker):
                    self.rejects(CONTEXT, function, marker)
        self.rejects(CONTEXT, "fn recover_original_evaluation(", "origin: Origin::Readback", "origin: Origin::Fresh")
        self.rejects(CONTEXT, "fn authenticate(", "self.origin != Origin::Fresh", "self.origin == Origin::Fresh")

    def test_four_original_receipts_and_complete_negative_candidate_are_required(self):
        for marker in (
            "self.scope.validate_snapshot(snapshot)?", "snapshot.receipts.len() != 4",
            "coordinator.next_stage() != Some(LearningIterationStageV1::Selection)",
            "snapshot.training_no_update_v2().is_some()",
            "snapshot.receipts.get(2) != Some(self.training.receipt())",
            "snapshot.receipts.last() != Some(self.evaluation.receipt())",
            "self.evaluation.training_attestation() != self.training.attestation()",
            "snapshot.owners.evidence_trust_digest != self.verifier.trust_digest()",
            "snapshot.request.envelope.objective_digest != self.verifier.objective_digest()",
            "disposition: LearningEvaluationDispositionV1::NoUpdate",
            "let candidate = coordinator", "== snapshot",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONTEXT, "fn authenticate(", marker)
        self.rejects(CONTEXT, "fn authenticate(", "snapshot.receipts.len() != 4", "snapshot.receipts.len() != 3")
        self.rejects(CONTEXT, "fn authenticate(", "disposition: LearningEvaluationDispositionV1::NoUpdate", "disposition: LearningEvaluationDispositionV1::Qualified")

    def test_original_signatures_roles_and_expiry_cannot_be_replaced_by_digest_matches(self):
        for marker in (
            "LearningEvidenceRoleV1::Generator", "LearningEvidenceRoleV1::Evaluator",
            "&receipt.actor_id != actor", "receipt.observed_unix_seconds > signature.issued_at",
            "signature.issued_at > at", "self.verifier.verify(",
            "&learning_iteration_receipt_signing_bytes_v1(receipt)?",
            "&evidence.principal().principal_id != actor",
            "verify_signed_actor_separation(&verified[0], &verified[1], at)?",
            "at >= snapshot.request.envelope.expiry_unix_seconds",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONTEXT, "fn authenticate(", marker)

    def test_both_original_owners_are_reread_before_final_fresh_authentication(self):
        for marker in (
            "self.authenticate(started, access)?",
            "OriginalCellQ24TrainingCommandClientV1::readback(trainer).await?",
            "if training != self.training",
            "OriginalCellEvaluationCommandClientV1::readback(evaluator).await?",
            "if evaluation != self.evaluation", "if finished < started",
            "self.authenticate(finished, access)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONTEXT, "fn require_current(", marker)
        for marker in ("if training != self.training", "if evaluation != self.evaluation"):
            self.rejects(CONTEXT, "fn require_current(", marker, marker.replace(" != ", " == "))

    def test_prepare_keeps_real_artifact_selection_fences_and_postprepare_uncertainty(self):
        for marker in (
            "binding::require_inputs_for_request(&context.snapshot().request, &inputs)?",
            "QueuedPublicationFence::new()", "context.authenticate(started, PublicationAccess::NewWork)?",
            "binding::require_inputs_for_request(&coordinator.snapshot().request, &inputs)?",
            "learning_retained_task_operation_id_v1(&coordinator)?",
            "load_original_selection(&inputs.authorities, inputs.selection)?",
            "selected.manifest() != &inputs.target.config.manifest",
            "if before < started", "context.authenticate(before, PublicationAccess::NewWork)?",
            "prepare_agentd_generation_cold_same_model_task_v1(",
            "operation_id: operation.to_string()", "if after < before",
            ".authenticate(after, PublicationAccess::NewWork)", "drop(queued)",
        ):
            with self.subTest(marker=marker):
                self.rejects(PUBLICATION, PREPARE, marker)
        for occurrence in range(2):
            self.rejects(PUBLICATION, PREPARE, "require_not_cancelled(&cancelled)?", occurrence=occurrence)
            self.rejects(PUBLICATION, PREPARE, ".require_current(&trainer, &evaluator, PublicationAccess::NewWork)", occurrence=occurrence)

    def test_publish_preserves_uncertainty_and_rechecks_original_owners_and_task(self):
        for marker in (
            "signed: SignedFinalUseGrant",
            ".require_current(&self.trainer, &self.evaluator, PublicationAccess::NewWork)",
            "QueuedPublicationFence::new()", "require_not_cancelled(&cancelled).map_err(uncertain)?",
            "PreparedAgentdGenerationUpdateV1::publish(prepared, &signed).map_err(uncertain)?",
            ".into_circuit_feature_task(definition, source, completed)",
            "if now().map_err(uncertain)? < started", "drop(queued)",
            ".require_current(&trainer, &evaluator, PublicationAccess::NewWork)",
            "if finished < started", ".authenticate(finished, PublicationAccess::NewWork)",
        ):
            with self.subTest(marker=marker):
                self.rejects(PUBLICATION, PUBLISH, marker)
        for marker in (
            "let started = now().map_err(uncertain)?",
            "binding::require_published_decision(&coordinator, &task).map_err(uncertain)?",
        ):
            for occurrence in range(2):
                self.rejects(PUBLICATION, PUBLISH, marker, occurrence=occurrence)
        self.rejects(PUBLICATION, PUBLISH, "require_not_cancelled(&cancelled).map_err(uncertain)?", "require_not_cancelled(&cancelled)?")
        self.rejects(PUBLICATION, PUBLISH, ".map_err(uncertain)?", occurrence=0)

    def test_continuation_custody_keeps_same_clients_behind_the_internal_consuming_call(self):
        for marker in (
            "self,", "signed: SignedFinalUseGrant",
            "self.publish_and_retain_original_evidence(signed)", ".await",
            ".map(|(task, _trainer, _evaluator)| task)",
        ):
            self.rejects(PUBLICATION, "fn publish_original_retained_task(", marker)
        for marker in (
            "self,", "OriginalCellQ24TrainingCommandClientV1,",
            "OriginalCellEvaluationCommandClientV1,",
            "let task = tokio::task::spawn_blocking(",
            "Ok((task, trainer, evaluator))",
        ):
            self.rejects(PUBLICATION, PUBLISH, marker)
        source = (ROOT / PUBLICATION).read_text()
        self.verifies(PUBLICATION, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(PUBLICATION, source.replace(
                "pub(crate) async fn publish_and_retain_original_evidence(",
                "pub async fn publish_and_retain_original_evidence(", 1))

    def test_cold_recovery_keeps_original_intent_and_cannot_repeat_effects(self):
        for marker in (
            "if intent_digest.is_zero()", "learning_retained_task_operation_id_v1(&coordinator)?",
            "load_original_selection(&authorities, selection)?", "recover_agentd_generation_update_v1(",
            "operation_id: operation.to_string()", "intent_digest,",
            "ready.recover_circuit_feature_task(", "original_source.as_ref()", "&original_identity",
        ):
            with self.subTest(marker=marker):
                self.rejects(RECOVERY, RECOVER, marker)
        for marker in (
            ".require_current(&trainer, &evaluator, PublicationAccess::Readback)",
            "binding::require_published_decision(&coordinator, &task)?", "if finished < started",
            "context.authenticate(finished, PublicationAccess::Readback)?",
        ):
            for occurrence in range(2):
                self.rejects(RECOVERY, RECOVER, marker, occurrence=occurrence)
        self.rejects(RECOVERY, RECOVER, "intent_digest,", occurrence=1)

    def test_no_signer_writer_candidate_upgrade_or_fresh_recovery_capability_can_be_added(self):
        for path, forbidden in (
            (CONTEXT, "SigningKey"), (CONTEXT, "execute_training"), (CONTEXT, "execute_evaluation"),
            (CONTEXT, "File::create"), (PUBLICATION, "RootResidentLearningEffectGateV3"),
            (PUBLICATION, "prepare_agentd_generation_cold_drained_update_v1"),
            (RECOVERY, "SignedFinalUseGrant"), (RECOVERY, "prepare_agentd_generation_cold_same_model_task_v1"),
            (RECOVERY, "PreparedAgentdGenerationUpdateV1::publish"),
            (RECOVERY, "PublicationAccess::NewWork"),
        ):
            with self.subTest(path=path, forbidden=forbidden):
                source = (ROOT / path).read_text()
                self.verifies(path, source)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, source + f"\nfn shortcut() {{ {forbidden}(); }}\n")

    def test_exports_retain_the_original_linux_boundary(self):
        source = (ROOT / AGENT / "lib.rs").read_text()
        attribute = '#[cfg(target_os = "linux")]\n'
        for name in (
            "OriginalCircuitEvaluatedRetentionContextV1", "OriginalCircuitEvaluatedRetentionRecoveryV1",
            "PreparedOriginalCircuitEvaluatedRetentionV1", "prepare_original_circuit_evaluated_retention_v1",
            "recover_original_circuit_evaluated_retention_v1",
        ):
            with self.subTest(export=name):
                export = f"pub use circuit_feature_current::{name};"
                self.assertEqual(source.count(attribute + export), 1)
                self.assertNotIn(attribute + export, source.replace(attribute + export, export, 1))


if __name__ == "__main__":
    unittest.main()

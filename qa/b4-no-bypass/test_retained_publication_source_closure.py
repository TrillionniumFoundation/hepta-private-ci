"""Keep retained publication on original NoUpdate, selection and FinalUse owners.

These lexical mutation controls protect the actual call graph; seven separate
native cases exercise original ordinary A/C and version-file mechanisms.
Neither inventory is a deployed owner or a positive-learning qualification.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "retained_publication_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
MAIN = AGENT + "circuit_learning_retained_publication.rs"
CONTEXT = AGENT + "circuit_learning_retained_context.rs"
BINDING = AGENT + "circuit_learning_retained_binding.rs"
RECOVERY = AGENT + "circuit_learning_retained_recovery.rs"
EXPECTED = {
    "learning_retained_publication_context": ('codex-rs/hepta-agentd/src/circuit_retained_version_context.rs',),
    "learning_retained_publication_prepare": ('codex-rs/hepta-agentd/src/circuit_retained_version_effect.rs',),
    "learning_retained_publication_publish": (),
    "learning_retained_publication_recover": (),
    "learning_original_training_command_client_readback": ('codex-rs/hepta-agentd/src/cell_q24_no_update_stage_state.rs', 'codex-rs/hepta-agentd/src/circuit_learning_retained_context.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_state.rs', 'codex-rs/hepta-agentd/src/circuit_evaluated_retention_context.rs'),
}


class RetainedPublicationClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        self.rejects_source(path, source[:offset] + source[offset + len(marker):])

    def rejects_source(self, path, changed):
        source = (ROOT / path).read_text()
        rows = [
            row for row in self.manifest["protected_file"] if row["path"] == path
        ]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_only_original_readback_edge_opens_and_host_factories_stay_closed(self):
        paths = {
            path
            for identifier in EXPECTED
            for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(
                    identifier,
                    self.manifest["privileged_inventory"]["required_boundary_ids"],
                )
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                receiver = (
                    f"owner: &{row.receiver_type}" if row.receiver_type else ""
                )
                call = f"owner.{method}()" if row.receiver_type else f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unregistered_retained_publication.rs"] = (
                    f"fn unexpected({receiver}) {{ {call}; }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_version_final_artifact_read_follows_control_and_source_io(self):
        path = AGENT + "circuit_retained_version_state.rs"
        source = (ROOT / path).read_text()
        last = "let last = state.observe_phase()?;"
        artifact = "let after = state.artifacts.read_current()?;"
        self.assertIn(last + "\n        " + artifact, source)
        self.rejects_source(path, source.replace(
            last + "\n        " + artifact,
            artifact + "\n        " + last,
            1,
        ))
        for marker in (
            "artifact::require_same(&before, &after)?",
            "if first != last",
            ".require_fresh(started, PublicationAccess::Readback)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "fn read_original(", marker)

    def test_version_exports_remain_inside_the_linux_module_boundary(self):
        source = (ROOT / AGENT / "lib.rs").read_text()
        names = (
            "OriginalCircuitRetainedVersionClientV1",
            "OriginalCircuitRetainedVersionHostV1",
            "OriginalCircuitRetainedVersionRecoveryV1",
            "OriginalCircuitRetainedArtifactCheckpointV1",
            "OriginalCircuitRetainedTaskInputsV1",
            "OriginalCircuitRetainedVersionErrorV1",
            "OriginalCircuitRetainedVersionPublicationV1",
            "OriginalCircuitRetainedVersionReadbackV1",
            "OriginalCircuitRetainedPublicationContextV1",
        )
        attribute = '#[cfg(target_os = "linux")]\n'

        def require_linux_exports(text):
            self.assertIn(attribute + "mod circuit_feature_current;", text)
            for name in names:
                self.assertIn(attribute + f"pub use circuit_feature_current::{name};", text)

        require_linux_exports(source)
        for name in names:
            export = f"pub use circuit_feature_current::{name};"
            with self.subTest(export=name):
                changed = source.replace(attribute + export, export, 1)
                with self.assertRaises(AssertionError):
                    require_linux_exports(changed)

    def test_context_requires_actual_opaque_training_and_strict_no_update(self):
        for marker in (
            "original: &OriginalCellQ24TrainingCommandReceiptV1",
            "coordinator.next_stage() != Some(LearningIterationStageV1::Training)",
            "coordinator.snapshot().receipts.len() != 2",
            "original.receipt().clone()",
            "training_evidence: original.attestation().clone()",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONTEXT, "fn from_original_training(", marker)
        for marker in (
            "self.scope.validate_snapshot(&self.training)?",
            "self.training.receipts.len() != 3",
            "LearningIterationObservationV1::TrainingNoUpdateV2(_)",
            "LearningEvidenceRoleV1::Generator",
            "receipt.observed_unix_seconds != self.training_evidence.issued_at",
            "verified.principal().principal_id != self.training.owners.trainer",
            "at >= self.training.request.envelope.expiry_unix_seconds",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONTEXT, "fn authenticate(", marker)

    def test_training_is_live_and_complete_original_signature_never_renews(self):
        for marker in (
            "self.authenticate(started, access)?",
            "OriginalCellQ24TrainingCommandClientV1::readback(trainer).await?",
            "self.training.receipts.last() != Some(actual.receipt())",
            "&self.training_evidence != actual.attestation()",
            "if finished < started",
            "self.authenticate(finished, access)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(CONTEXT, "fn require_training_current(", marker)

    def test_prepare_keeps_original_selection_and_actual_no_update_operation(self):
        for marker in (
            "binding::require_inputs(&context, &inputs)?",
            "learning_retained_task_operation_id_v1(&coordinator)?",
            "load_original_selection(",
            "selected.manifest() != &inputs.target.config.manifest",
            "if before < started",
            ".authenticate(before, PublicationAccess::NewWork)?",
            "prepare_agentd_generation_cold_same_model_task_v1(",
            "if after < before",
            ".authenticate(after, PublicationAccess::NewWork)",
        ):
            with self.subTest(marker=marker):
                self.rejects(MAIN, "fn prepare_original_circuit_retained_publication_v1<", marker)
        self.rejects(MAIN, "fn load_original_selection(", "AgentdSelectedGenerationV1::load(")
        self.rejects(MAIN, "fn load_original_selection(", "authorities.now()?")

    def test_publish_consumes_separate_exact_final_use_and_checks_original_current(self):
        for marker in (
            "PreparedAgentdGenerationUpdateV1::publish(prepared, &signed)",
            ".into_circuit_feature_task(",
            "binding::require_published(",
            "now().map_err(uncertain)? < started",
            "drop(queued)",
            "Ok::<_, OriginalCircuitRetainedPublicationErrorV1>(task)",
        ):
            with self.subTest(marker=marker):
                self.rejects(MAIN, "fn publish_and_retain_original_trainer(", marker)
        for marker in (
            "require_published_decision(&coordinator, task)?",
            "context.authenticate(finished, access)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(BINDING, "fn require_published(", marker)
        for marker in (
            "task.require_current()?",
            "require_previous(request, previous)?",
            ".selection(original, coordinator, &previous.manifest)?",
            "task.require_bundle(&request.selected_bundle)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(BINDING, "fn require_published_decision(", marker)

    def test_distinct_c_uses_actual_task_content_not_nonce_or_new_run_alone(self):
        for marker in (
            "context.authenticate(now()?, PublicationAccess::NewWork)?",
            "require_inputs_for_request(&context.training.request, inputs)",
        ):
            with self.subTest(marker=marker):
                self.rejects(BINDING, "fn require_inputs<", marker)
        for marker in (
            "inputs.completed.binding != expected",
            "next.manifest != inputs.predecessor.config.manifest",
            "source.scope.run_id == inputs.completed.source.input().scope.run_id",
            "source.observation == inputs.completed.source.input().observation",
            "source.scope.agent_id != request.agent_id",
            "source.scope.cell_id != request.cell_id",
            "crate::circuit_feature_task_digest_v1(definition, source)?",
            "next.source_frontier",
        ):
            with self.subTest(marker=marker):
                self.rejects(BINDING, "fn require_inputs_for_request<", marker)
        for marker in (
            "previous.source.history_digest().as_str()",
            "request.completed_task_receipt.to_string()",
            "input.scope.run_id != request.source_run_id",
            "previous.receipt.checkpoint_after != previous.source.checkpoint_digest()",
        ):
            with self.subTest(marker=marker):
                self.rejects(BINDING, "fn require_previous(", marker)

    def test_cold_unknown_only_reads_exact_original_files_and_does_not_prepare(self):
        for marker in (
            "if intent_digest.is_zero()",
            "PublicationAccess::Readback",
            "learning_retained_task_operation_id_v1(&coordinator)?",
            "recover_agentd_generation_update_v1(",
            "ready.recover_circuit_feature_task(",
            "original_source.as_ref()",
            "binding::require_published(",
            "Ok::<_, OriginalCircuitRetainedPublicationErrorV1>(task)",
        ):
            with self.subTest(marker=marker):
                self.rejects(RECOVERY, "fn recover_original_circuit_retained_publication_v1<", marker)
        source = (ROOT / RECOVERY).read_text()
        self.rejects_source(
            RECOVERY,
            source + "\nfn forbidden_retry() { prepare_agentd_generation_cold_same_model_task_v1(); }\n",
        )

    def test_dropped_queued_work_cannot_send_a_new_publication(self):
        self.rejects(MAIN, "fn drop(", "self.cancelled.store(true, Ordering::Release)")
        self.rejects(MAIN, "fn require_not_cancelled(", "cancelled.load(Ordering::Acquire)")
        for function in (
            "fn prepare_original_circuit_retained_publication_v1<",
            "fn publish_and_retain_original_trainer(",
        ):
            with self.subTest(function=function):
                self.rejects(MAIN, function, "QueuedPublicationFence::new()")
                self.rejects(MAIN, function, "require_not_cancelled(&cancelled)?")

    def test_no_resident_grant_candidate_upgrade_or_local_signer_shortcut(self):
        source = (ROOT / MAIN).read_text()
        for forbidden in (
            "RootResidentLearningEffectGateV3",
            "SigningKey",
            "prepare_agentd_generation_cold_drained_update_v1",
            "LearningArtifactOwnerService::publish",
        ):
            with self.subTest(forbidden=forbidden):
                self.rejects_source(MAIN, source + f"\nfn shortcut() {{ {forbidden}(); }}\n")
        source = (ROOT / CONTEXT).read_text()
        self.rejects_source(
            CONTEXT,
            source + "\npub fn from_checkpoint() {}\n",
        )


if __name__ == "__main__":
    unittest.main()

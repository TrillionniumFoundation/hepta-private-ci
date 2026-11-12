"""Original ordinary lanes remain a closed set of actual authority receivers."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ordinary_original_callers_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
A = "codex-rs/hepta-agentd/src/"
N = "codex-rs/hepta-neuron/src/"
ACTUAL = {
    "learning_original_evaluation_key": (A + "authority_host_q24_evaluation_execution.rs",),
    "root_q24_factory_live_observation": (A + "cell_q24_learning_operation_lane.rs",),
    "learning_original_generation_receipt_require_context": (A + "cell_q24_learning_generation_operation.rs",),
    "learning_original_generation_receipt_observe_original_selection": (A + "cell_q24_learning_generation_operation.rs",),
    "learning_original_q24_stage_require_current": (A + "circuit_feature_historical_handoff.rs",),
    "learning_original_q24_stage_prepared": (
        A + "circuit_feature_historical_handoff.rs", A + "production_post_a_c_task.rs",
    ),
    "root_generation_journal_original_observer": (N + "cell_generation_unpublished_observer.rs",),
    "root_artifact_original_reader_open": (A + "production_post_a_artifacts.rs",),
    "root_artifact_original_withdrawal_bind": (A + "production_post_a_artifacts.rs",),
    "root_generation_connection_original_binding": (A + "root_generation_initial_source_capture.rs",),
    "root_generation_publication_handoff_until": (A + "cell_q24_publication_root_stage.rs",),
    "q24_successor_running_admission": (A + "cell_q24_publication_successor_grant.rs", A + "production_post_a_continuation.rs",),
    "root_original_publication_stream_until": (A + "root_independent_b_client_connect.rs", A + "root_independent_b_source_client.rs",),
    "root_initial_learning_trust_activation": (A + "authority_host_q24_evaluation_admission.rs",),
    "cell_original_physical_witness_codec": (A + "authority_host_successor_files_read.rs",),
    "root_historical_task_read_original_session": (A + "root_post_a_learning_client.rs",),
    "root_historical_task_read_receipt_client": (A + "learning_iteration_historical_source.rs", A + "root_post_a_learning_client.rs",),
    "root_historical_recipient_trust_activation": (A + "root_historical_learning_operation.rs",),
    "cell_q24_historical_dataset_task_receipt": (A + "cell_q24_dataset_historical_ledger.rs",),
    "root_publication_fixed_version": (A + "authority_host_publication_grant.rs",),
    "root_publication_reserved_version": (A + "authority_host_publication_grant_store.rs",),
    "root_publication_original_frame_deadline": (A + "authority_host_initial_peer_runtime.rs",),
    "q24_training_original_operation_evidence": (A + "cell_q24_training_b_plan.rs",),
    "q24_training_original_operation_evidence_current": (A + "root_independent_b_candidate_data.rs", A + "root_independent_b_plan.rs",),
    "historical_stage_original_source": (A + "learning_iteration_successor.rs",),
}
TYPED = {
    "root_generation_publication_original_stream": "RootGenerationCurrentClient",
    "artifact_original_acknowledged_readback": "LearningArtifactOwnerService",
    "root_initial_artifact_same_session": "RootGenerationPublicationConnectionV1",
    "root_initial_learning_trust_bind": "RootInitialLearningTrustFilesV1",
    "root_initial_learning_trust_payload": "RegisteredInitialLearningTrustV1",
}
OTHER = (
    "learning_original_q24_with_original_q24_stage_owners",
    "learning_original_q24_training_files",
    "q24_publication_embedded_admission",
    "q24_root_artifact_qualified_phase",
    "q24_root_retained_phase",
    "root_generation_publication_purpose_connect",
    "root_initial_artifact_revalidate",
    "q24_training_original_operation",
    "q24_root_checkpoint_original_pair",
    "q24_runtime_original_checkpoint",
    "historical_stage_current_admission",
    "post_a_artifact_existing_owner_open",
)


class OrdinaryOriginalCallersSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(manifest)}
        paths = {
            A + "cell_q24_learning_historical_stage.rs",
            A + "production_post_a_q24_owners.rs",
            A + "root_historical_task_read_inputs.rs",
            A + "root_generation_initial_client.rs",
            A + "authority_host_historical_task.rs",
            A + "cell_q24_dataset_historical_task.rs",
            A + "root_historical_task_connection.rs",
            A + "root_historical_task_read_client.rs",
            A + "production_launcher.rs",
            A + "production_launcher_late_writer.rs",
            A + "authority_host_learning_session.rs",
            A + "authority_host_historical_read.rs",
            A + "authority_host_post_a_derive.rs",
            A + "cell_q24_task_ledger_recovery_support.rs",
            A + "cell_q24_learning_stage_owners.rs",
            A + "root_independent_b_source_client.rs",
        }
        for identifier in (*ACTUAL, *TYPED, *OTHER):
            row = cls.boundaries[identifier]
            paths.add(row.definition_path)
            paths.update(row.product_callers)
        cls.index = {
            p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text()))
            for p in paths
        }

    def test_actual_ordinary_callers_cannot_be_omitted(self):
        for identifier, actual in ACTUAL.items():
            row = self.boundaries[identifier]
            with self.subTest(boundary=identifier):
                PROOF._verify_boundary(ROOT, row, self.index, ())
                for caller in actual:
                    self.assertIn(caller, row.product_callers)
                    reduced = tuple(p for p in row.product_callers if p != caller)
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(
                            ROOT, replace(row, product_callers=reduced), self.index, ()
                        )

    def test_same_method_name_does_not_grant_an_unrelated_type_authority(self):
        for identifier, receiver_type in TYPED.items():
            row = self.boundaries[identifier]
            with self.subTest(boundary=identifier):
                self.assertEqual(row.receiver_type, receiver_type)
                self.assertIsNone(row.call_pattern)
                PROOF._verify_boundary(ROOT, row, self.index, ())
                method = row.symbol.rsplit("::", 1)[1]
                for call in (
                    f"fn bypass() {{ {row.symbol}(); }}",
                    f"fn bypass(owner: &mut {receiver_type}) {{ owner.{method}(); }}",
                ):
                    extra = dict(self.index)
                    extra[A + "unregistered_original_authority.rs"] = call
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, row, extra, ())

    def test_current_material_and_original_deadline_routes_are_real(self):
        for identifier in OTHER:
            with self.subTest(boundary=identifier):
                PROOF._verify_boundary(ROOT, self.boundaries[identifier], self.index, ())
        self.assertEqual(
            self.boundaries["root_generation_publication_purpose_connect"].product_callers, ()
        )
        self.assertEqual(
            self.boundaries["root_generation_publication_handoff_until"].product_callers,
            (A + "cell_q24_publication_root_stage.rs",),
        )


if __name__ == "__main__":
    unittest.main()

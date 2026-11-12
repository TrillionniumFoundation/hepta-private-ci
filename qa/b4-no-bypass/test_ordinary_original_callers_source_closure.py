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
}
TYPED = {
    "root_generation_publication_original_stream": "RootGenerationCurrentClient",
    "artifact_original_acknowledged_readback": "LearningArtifactOwnerService",
}
OTHER = (
    "learning_original_q24_with_original_q24_stage_owners",
    "learning_original_q24_training_files",
    "q24_publication_embedded_admission",
    "q24_root_artifact_qualified_phase",
    "q24_root_retained_phase",
    "root_generation_publication_purpose_connect",
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

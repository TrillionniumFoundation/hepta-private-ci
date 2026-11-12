"""Keep Root publication on the existing original owner capabilities."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "root_publication_existing_owner_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CALLERS = {
    "learning_artifact_verified_current_view": (
        AGENT + "cognitive_ranker.rs",
        AGENT + "neuron_generation_update_selection.rs",
        "codex-rs/hepta-intelligence/src/ndu_stochastic_admission.rs",
        AGENT + "neuron_generation_update_selection_root.rs",
    ),
    "root_learning_live_profile_action": (
        AGENT + "authority_host_q24_model_registration.rs",
        AGENT + "authority_host_q24_model_transport.rs",
        AGENT + "authority_host_generation_publication_enrollment.rs",
        AGENT + "authority_host_generation_publication_transport.rs",
        AGENT + "authority_host_original_publication_route.rs",
        AGENT + "authority_host_historical_read.rs",
        AGENT + "authority_host_historical_read_session.rs",
        AGENT + "authority_host_derived_learning_registration.rs",
        AGENT + "authority_host_post_a_provider.rs",
        AGENT + "authority_host_q24_model_registration_v2.rs",
        AGENT + "authority_host_publication_registration.rs",
    ),
    "q24_publication_original_b_manifest": (
        AGENT + "cell_q24_publication_driver.rs",
        AGENT + "cell_q24_publication_root_stage.rs",
    ),
    "q24_publication_original_lane": (
        AGENT + "cell_q24_publication_driver.rs",
        AGENT + "cell_q24_publication_current.rs",
        AGENT + "cell_q24_publication_root_stage.rs",
        AGENT + "cell_q24_publication_successor_current.rs",
        AGENT + "cell_q24_publication_historical_recovery.rs",
    ),
}


class RootPublicationExistingOwnerSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        paths = {
            path
            for identifier, expected in CALLERS.items()
            for path in (
                cls.boundaries[identifier].definition_path,
                *expected,
                *cls.boundaries[identifier].product_callers,
            )
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }

    def test_original_owner_edges_keep_exact_registered_callers(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for identifier, expected in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, inventory)
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_each_actual_caller_must_remain_declared(self):
        for identifier, expected in CALLERS.items():
            row = self.boundaries[identifier]
            for omitted in expected:
                with self.subTest(boundary=identifier, omitted=omitted):
                    declared = tuple(
                        path for path in row.product_callers if path != omitted
                    )
                    self.assertNotEqual(declared, row.product_callers)
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(
                            ROOT,
                            replace(row, product_callers=declared),
                            self.sources,
                            (),
                        )

    def test_same_original_typed_call_cannot_move_to_an_unregistered_file(self):
        for identifier, expected in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                # Preserve the real receiver declarations and imports. This
                # mutant changes only the source path's custody registration.
                sources = dict(self.sources)
                sources[AGENT + "unregistered_publication_owner.rs"] = (
                    self.sources[expected[-1]]
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())


if __name__ == "__main__":
    unittest.main()

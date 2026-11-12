"""Close actual independent B routes without granting data authority."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
SPEC = importlib.util.spec_from_file_location(
    "original_b_routes_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)

EXPECTED = {
    "register": ("authority_host_post_a_learning",),
    "reopen": ("authority_host_post_a_learning",),
    "route": ("authority_host_post_a_learning",),
    "same_learning": ("authority_host_q24_evaluation_route", "authority_host_q24_model_b_binding"),
    "native_prepare": ("authority_host_q24_evaluation_serve",),
    "native_complete": ("authority_host_q24_evaluation_serve",),
    "native_readback": ("authority_host_q24_evaluation_serve", "authority_host_q24_model_b_transport"),
    "signed_source": ("authority_host_q24_evaluation_source_serve",),
    "take_source_offer": ("authority_host_post_a_worker",),
    "custodian": ("authority_host_post_a_learning",),
    "parts": ("authority_host_post_a_worker",),
    "bind": ("authority_host_learning_session",),
    "send_evaluation": ("authority_host_post_a_worker",),
    "receive_evaluation": ("production_post_a_q24_handoff",),
    "send_source": ("authority_host_post_a_worker",),
    "receive_source": ("root_independent_b_source_cli",),
    "source_command": ("bin/hepta-authority-host",),
    "source_submit": ("root_independent_b_source_cli",),
    "source_route": ("authority_host_q24_evaluation_route",),
    "source_peer": ("authority_host_q24_evaluation_source_route",),
    "source_data": ("root_independent_b_source_client",),
    "connect": ("production_post_a_q24",),
    "client_complete": ("cell_q24_learning_evaluation_root",),
    "client_readback": ("cell_q24_learning_evaluation_root",),
    "install": ("production_post_a_q24",),
    "stage_execute": ("cell_q24_learning_historical_operation",),
    "stage_readback": ("cell_q24_learning_b_operation", "cell_q24_learning_model_root"),
    "manifest": ("cell_q24_publication_material",),
    "plan_signature": ("cell_q24_learning_evaluation_root",),
    "source_input_open": ("authority_host_q24_evaluation_registration",),
    "provider": ("authority_host_q24_evaluation_execute",),
    "record_register": ("authority_host_q24_evaluation_registration",),
    "record_open": ("authority_host_q24_evaluation_registration",),
    "record_inspect": (
        "authority_host_q24_evaluation_registration", "authority_host_q24_evaluation_route",
        "authority_host_q24_evaluation_operation", "authority_host_q24_evaluation_prepare",
        "authority_host_q24_evaluation_ingress",
    ),
}


class OriginalBRouteSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {
            cls.boundaries["root_independent_b_" + name].definition_path for name in EXPECTED
        }
        paths.update(AGENT + path + ".rs" for callers in EXPECTED.values() for path in callers)
        paths.update(AGENT + path + ".rs" for path in (
            "authority_host_q24_evaluation_host", "root_independent_b_client",
            "cell_q24_learning_stage_owners", "cell_q24_training_stage_operation",
        ))
        cls.sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }

    def test_actual_closed_sets_and_privileged_inventory(self):
        for name, callers in EXPECTED.items():
            identifier = "root_independent_b_" + name
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, tuple(AGENT + path + ".rs" for path in callers))
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_removing_a_real_caller_cannot_pass(self):
        for name in EXPECTED:
            identifier = "root_independent_b_" + name
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_unregistered_product_cannot_invoke_b_entrypoints(self):
        for name in EXPECTED:
            identifier = "root_independent_b_" + name
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = (
                    f"fn extra(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                    if row.receiver_type else f"fn extra() {{ {row.symbol}(); }}"
                )
                sources = {**self.sources, AGENT + "unregistered_b_authority.rs": extra}
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())


if __name__ == "__main__":
    unittest.main()

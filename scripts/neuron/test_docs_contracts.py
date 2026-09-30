import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/modules/neuron.runtime"


class NeuronDocumentationContractTests(unittest.TestCase):
    def test_readme_local_links_resolve(self):
        readme = (DOCS / "README.md").read_text(encoding="utf-8")
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", readme)
        checked = 0
        for target in links:
            if "://" in target or target.startswith("#"):
                continue
            path_text = target.split("#", 1)[0]
            if not path_text:
                continue
            path = (DOCS / path_text).resolve()
            self.assertTrue(path.exists(), f"broken README link: {target}")
            checked += 1
        self.assertGreaterEqual(checked, 8)

    def test_module_spec_is_the_only_current_status_source(self):
        spec = json.loads((DOCS / "MODULE_SPEC.json").read_text(encoding="utf-8"))
        generated = json.loads(
            (DOCS / "IMPLEMENTATION_MAP.generated.json").read_text(encoding="utf-8")
        )
        compatibility = json.loads(
            (DOCS / "IMPLEMENTATION_MAP.json").read_text(encoding="utf-8")
        )
        self.assertEqual(generated["generatedFrom"], "docs/modules/neuron.runtime/MODULE_SPEC.json")
        self.assertEqual(compatibility["status"], "compatibility-pointer")
        self.assertEqual(compatibility["sourceOfTruth"], "MODULE_SPEC.json")
        self.assertEqual(
            set(compatibility),
            {
                "schemaVersion",
                "status",
                "sourceOfTruth",
                "canonicalGeneratedMap",
                "note",
            },
        )
        self.assertFalse(spec["claimBoundary"]["productionActivation"])
        self.assertFalse(spec["claimBoundary"]["release"])

    def test_product_lifecycle_symbols_are_ordinary_source(self):
        product = (
            ROOT / "codex-rs/hepta-agentd/src/neuron_runtime_v2_product.rs"
        ).read_text(encoding="utf-8")
        config = (ROOT / "codex-rs/hepta-agentd/src/config.rs").read_text(encoding="utf-8")
        runtime = (ROOT / "codex-rs/hepta-agentd/src/runtime.rs").read_text(encoding="utf-8")
        state = (ROOT / "codex-rs/hepta-agentd/src/state.rs").read_text(encoding="utf-8")
        for symbol in (
            "AgentdNeuronTickProviderV2",
            "AgentdNeuronRuntimeV2Config",
            "AgentdNeuronRuntimeV2Host",
            "restart_stopped",
            "begin_quiesce",
            "shutdown",
        ):
            self.assertIn(symbol, product)
        self.assertIn("with_neuron_runtime_v2", config)
        self.assertIn("take_neuron_runtime_v2", config)
        self.assertIn("host.begin_quiesce()?", runtime)
        self.assertIn("host.shutdown()", runtime)
        self.assertIn("prepare_for_composition_with_durable_neuron_v2", state)

    def test_control_error_actions_are_documented_and_stable(self):
        source = (
            ROOT / "codex-rs/hepta-agentd/src/neuron_runtime_v2_errors.rs"
        ).read_text(encoding="utf-8")
        generated_actions = (DOCS / "ERROR_ACTIONS.generated.md").read_text(
            encoding="utf-8"
        )
        for code in (
            "owner_busy",
            "owner_poisoned",
            "controller_busy",
            "controller_poisoned",
            "not_serving",
            "invalid_lifecycle_transition",
            "generation_conflict",
            "pending_recovery",
            "unknown_generation",
        ):
            self.assertIn(f'"{code}"', source)
            self.assertIn(f"`{code}`", generated_actions)
        for method in (
            "retry_class",
            "operator_action",
            "is_terminal",
            "is_reconstruction_required",
            "operation_identity",
        ):
            self.assertIn(f"fn {method}", source)

    def test_joint_rollback_gap_is_formal_and_blocking(self):
        security = (DOCS / "V2_SECURITY_BOUNDARY.md").read_text(encoding="utf-8")
        self.assertIn("NR-SEC-ROLLBACK-001", security)
        self.assertIn("open_security_gap", security)
        for claim in (
            "productExecutionProved",
            "independentAcceptance",
            "productionActivation",
            "release",
        ):
            self.assertIn(claim, security)

    def test_source_writers_and_migration_payloads_are_absent(self):
        self.assertFalse((ROOT / ".github/neuron-agentd-integration.patch").exists())
        self.assertFalse((ROOT / "scripts/neuron_runtime_apply_gate_repair.sh").exists())
        self.assertFalse(
            (ROOT / ".github/workflows/neuron-runtime-gate-fix-once.yml").exists()
        )
        self.assertFalse(
            (ROOT / ".github/workflows/neuron-runtime-product-materialize-once.yml").exists()
        )
        for workflow in (ROOT / ".github/workflows").glob("*neuron*.yml"):
            value = workflow.read_text(encoding="utf-8")
            self.assertNotIn("contents: write", value, str(workflow))

    def test_target_host_validator_keeps_activation_separate(self):
        validator = (ROOT / "scripts/neuron/target_host_acceptance.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"productExecutionProved": True', validator)
        self.assertIn('"productionActivation": False', validator)
        self.assertIn('"release": False', validator)


if __name__ == "__main__":
    unittest.main()

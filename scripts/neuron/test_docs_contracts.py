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
        self.assertEqual(
            generated["generatedFrom"],
            "docs/modules/neuron.runtime/MODULE_SPEC.json",
        )
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
        documents = {item["path"] for item in spec["documents"]}
        self.assertIn(
            "docs/modules/neuron.runtime/V2_SECURITY_BOUNDARY.md",
            documents,
        )
        self.assertIn(
            "docs/modules/neuron.runtime/V3_SEGMENT_MANIFEST.md",
            documents,
        )
        operation_states = {
            item["id"]: item["state"] for item in spec["operations"]
        }
        self.assertEqual(
            operation_states["target_host_product_evidence"],
            "source_implemented_external_receipt_validator_no_target_host_receipt_and_no_activation",
        )
        self.assertEqual(
            operation_states["v3_segment_manifest_contract"],
            "design_and_validator_implemented_not_runtime_selected_not_migrated",
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
        workflow = (
            ROOT / ".github/workflows/neuron-runtime-target-host-acceptance.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('"productExecutionProved": True', validator)
        self.assertIn('"productionActivation": False', validator)
        self.assertIn('"release": False', validator)
        self.assertIn("permissions:\n  actions: read\n  contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("contents: write", workflow)

    def test_v3_manifest_is_separate_and_non_activating(self):
        design = (DOCS / "V3_SEGMENT_MANIFEST.md").read_text(encoding="utf-8")
        validator = (ROOT / "scripts/neuron/segment_manifest_v3.py").read_text(
            encoding="utf-8"
        )
        for identifier in ("HPTNGM03", "HPTNGS03", "HPTNGI03", "HPTNGW03"):
            self.assertIn(identifier, design)
            self.assertIn(identifier, validator)
        self.assertIn("HPTNGS02", design)
        self.assertIn('"migrationQualified": True', validator)
        self.assertIn('"productionActivation": False', validator)
        self.assertIn('"release": False', validator)


if __name__ == "__main__":
    unittest.main()

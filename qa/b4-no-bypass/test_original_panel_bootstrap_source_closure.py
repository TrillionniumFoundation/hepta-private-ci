"""Keep the explicit V2 panel at original Material and Trainer custody gates.

These mutations check the source contract. They are neither native execution nor
evidence that an external launcher retained this declaration before task A.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_panel_bootstrap_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "cell_q24_material_receipt_owner.rs"
BINDING = AGENT + "cell_q24_material_receipt_binding.rs"
TRAINING = AGENT + "cell_q24_training_bootstrap.rs"
BUILD = AGENT + "cell_q24_training_bootstrap_build.rs"
EXPECTED = {
    "learning_original_material_config_v2": [],
    "learning_original_material_create_v2": [],
    "learning_original_material_recover_v2": [],
    "learning_original_training_bootstrap_config_v2": [],
    "learning_original_training_bootstrap_create_v2": [],
    "learning_original_training_bootstrap_recover_v2": [],
    "learning_original_material_create": [],
    "learning_original_material_recover": []
}
MUTATIONS = {
    "material": [
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn from_original(",
            "marker": "binding::require_panel_initial(&original, Some(panel.as_ref()))?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn create_v2(",
            "marker": "binding::validate_config(&original, &experience_key, &dataset_key)?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn create_v2(",
            "marker": "binding::require_panel_initial(&original, Some(panel.as_ref()))?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn create_v2(",
            "marker": "Self::create(files, original, experience_key, dataset_key)?"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn create_v2(",
            "marker": "owner.panel = Some(panel);"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn create(",
            "marker": "panel: None,"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn recover_v2(",
            "marker": "binding::validate_config(&original, &experience_key, &dataset_key)?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn recover_v2(",
            "marker": "binding::require_panel_initial(&original, Some(panel.as_ref()))?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn recover_v2(",
            "marker": "Self::recover(files, original, experience_key, dataset_key)?"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn recover_v2(",
            "marker": "owner.panel = Some(panel);"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn recover(",
            "marker": "panel: None,"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn attest_experience(",
            "marker": "binding::require_panel_initial(&self.config, self.panel.as_deref())?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_owner.rs",
            "function": "fn read_experience(",
            "marker": "binding::require_panel_initial(&self.config, self.panel.as_deref())?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_binding.rs",
            "function": "fn require_panel_initial(",
            "marker": "if let Some(panel) = panel {"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_binding.rs",
            "function": "fn require_panel_initial(",
            "marker": "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_initial(panel, &config.initial)"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_material_receipt_binding.rs",
            "function": "fn require_panel_initial(",
            "marker": ".map_err(|_| invalid("
        }
    ],
    "training": [
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn from_original(",
            "marker": "require_panel_initial(&original, Some(panel.as_ref()))?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn require_panel_initial(",
            "marker": "if let Some(panel) = panel {"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn require_panel_initial(",
            "marker": "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_initial("
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn require_panel_initial(",
            "marker": "&config.material.initial,"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn from_original_custody_v2(",
            "marker": "let OriginalCellQ24TrainingBootstrapConfigV2 { original, panel } = config;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn from_original_custody_v2(",
            "marker": "Origin::Fresh,"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn from_original_custody_v2(",
            "marker": "Some(panel),"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn from_original_custody(",
            "marker": "None,"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn recover_original_custody_v2(",
            "marker": "let OriginalCellQ24TrainingBootstrapConfigV2 { original, panel } = config;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn recover_original_custody_v2(",
            "marker": "Origin::Recovered,"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn recover_original_custody_v2(",
            "marker": "Some(panel),"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn recover_original_custody(",
            "marker": "None,"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn bind_original_custody(",
            "marker": "require_panel_initial(&config, panel.as_deref())?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs",
            "function": "fn bind_original_custody(",
            "marker": "panel,"
        }
    ],
    "cut": [
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn require_fresh_cut(",
            "marker": "require_panel_initial(&self.config, self.panel.as_deref())?;"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn require_fresh_cut(",
            "marker": "if let Some(panel) = self.panel.as_deref() {"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn require_fresh_cut(",
            "marker": "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_training("
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn require_fresh_cut(",
            "marker": "cut.snapshot(),"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn build_original_owner(",
            "marker": "let panel = self.panel.clone();"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn build_original_owner(",
            "marker": "if let Some(panel) = panel.as_deref() {"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn build_original_owner(",
            "marker": "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_initial("
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn build_original_owner(",
            "marker": "&material_config.initial,"
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn build_original_owner(",
            "marker": "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_training("
        },
        {
            "path": "codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_build.rs",
            "function": "fn build_original_owner(",
            "marker": "original_cut.snapshot(),"
        }
    ]
}


class OriginalPanelBootstrapClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def function(self, source, marker):
        code = self.code(source)
        self.assertEqual(code.count(marker), 1)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return code[start:end + 1], start, end

    def verifies(self, path, source):
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

    def rejects_group(self, group):
        for case in MUTATIONS[group]:
            path, function, marker = (
                case["path"], case["function"], case["marker"]
            )
            source = (ROOT / path).read_text()
            _, start, end = self.function(source, function)
            offset = source.index(marker, start, end + 1)
            self.verifies(path, source)
            for replacement in ("", "/* " + marker + " */"):
                changed = source[:offset] + replacement + source[offset + len(marker):]
                with self.subTest(group=group, function=function, marker=marker,
                                  replacement=replacement):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(path, changed)

    def test_new_v2_factories_and_legacy_delegation_have_exact_callers(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, tuple(expected))
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(sources)
                changed[AGENT + "unregistered_panel_bootstrap.rs"] = (
                    f"fn escape() {{ {row.receiver_type}::{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_v2_metadata_cannot_become_public_custody_or_deserialized_authority(self):
        for path in (OWNER, TRAINING):
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            for marker in ("original:", "panel:"):
                changed = source.replace("    " + marker, "    pub " + marker, 1)
                self.assertNotEqual(changed, source)
                with self.subTest(path=path, marker=marker):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(path, changed)

    def test_material_policy_precedes_both_original_journals_and_each_current_read(self):
        self.rejects_group("material")

    def test_training_v2_retains_policy_while_v1_has_no_implicit_upgrade(self):
        self.rejects_group("training")

    def test_actual_dataset_and_queued_writer_require_the_retained_full_policy(self):
        self.rejects_group("cut")

    def require_policy_depths(self, source):
        checks = (
            ("fn require_fresh_cut(", "if let Some(panel) = self.panel.as_deref() {", 1),
            ("fn require_fresh_cut(", "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_training(", 2),
            ("fn build_original_owner(", "if let Some(panel) = panel.as_deref() {", 2),
            ("fn build_original_owner(", "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_initial(", 3),
            ("fn build_original_owner(", "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_training(", 3),
        )
        for function, marker, depth in checks:
            body, _, _ = self.function(source, function)
            if body.count(marker) != 1:
                raise PROOF.VerificationFailure("unique original panel operation check")
            prefix = body[:body.index(marker)]
            if prefix.count("{") - prefix.count("}") != depth:
                raise PROOF.VerificationFailure("unconditional panel check within its original lane")

    def test_policy_calls_cannot_move_under_an_extra_condition(self):
        source = (ROOT / BUILD).read_text()
        self.verifies(BUILD, source)
        self.require_policy_depths(source)
        for function, marker in (
            ("fn require_fresh_cut(", "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_training("),
            ("fn build_original_owner(", "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_initial("),
            ("fn build_original_owner(", "OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_training("),
        ):
            _, start, end = self.function(source, function)
            offset = source.index(marker, start, end + 1)
            stop = source.index("?;", offset, end + 1) + 2
            call = source[offset:stop]
            changed = source[:offset] + "if unrelated_condition() { " + call + " }" + source[stop:]
            with self.subTest(function=function, marker=marker):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.require_policy_depths(changed)

    def test_no_policy_bridge_can_acquire_keys_peers_or_cross_host_arc_identity(self):
        for path in (OWNER, BINDING, TRAINING, BUILD):
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            for marker in (
                "SigningKey::generate(value);",
                "UnixStream::connect(value);",
                "File::open(value);",
                "Arc::ptr_eq(value, value);",
                "Deserialize::deserialize(value);",
            ):
                with self.subTest(path=path, marker=marker):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(path, source + "\nfn escape() { " + marker + " }\n")


if __name__ == "__main__":
    unittest.main()

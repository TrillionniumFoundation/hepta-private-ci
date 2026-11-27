"""Controls for qualification cfg scope and inert Objective source custody."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from hepta_lane_e_source import CUSTODY, FEATURE, mask_qualification_items

SCRIPTS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "lane_e_writer_scope", SCRIPTS / "hepta-lane-e-closure.py"
)
assert SPEC and SPEC.loader
lane = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lane
SPEC.loader.exec_module(lane)

CFG = f'#[cfg(feature = "{FEATURE}")]\n'
WRITER = "pub fn record() { LedgerEvent::Decision(value); }\n"


class ProductWriterScopeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.write("codex-rs/Cargo.toml", "[workspace]\nmembers = []\n")
        self.agent_manifest = (
            '[package]\nname = "codex-hepta-agentd"\nversion = "0.0.0"\n'
            '[features]\ndefault = ["production-cognitive-write"]\n'
            "production-cognitive-write = []\n"
            f'{FEATURE} = ["codex-hepta-learning-ledger/qualification-legacy-write"]\n'
            '[dependencies]\ncodex-hepta-learning-ledger = { path = "../hepta-learning-ledger" }\n'
        )
        self.write("codex-rs/hepta-agentd/Cargo.toml", self.agent_manifest)
        self.write(
            "codex-rs/hepta-learning-ledger/Cargo.toml",
            '[package]\nname = "codex-hepta-learning-ledger"\nversion = "0.0.0"\n'
            "[features]\ndefault = []\nqualification-legacy-write = []\n",
        )
        self.source = "codex-rs/hepta-agentd/src/lib.rs"
        self.write(self.source, CFG + WRITER)

    def write(self, relative, source):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def codes(self):
        with patch.object(lane, "ROOT", self.root):
            findings = lane.Findings()
            lane.verify_product_writer_exclusivity(findings)
        return [finding.code for finding in findings.items]

    def assert_raw_blocked(self):
        self.assertIn("legacy_learning_writer_product_bypass", self.codes())

    def test_positive_feature_covers_complete_import_and_owner_method(self):
        self.write(
            self.source,
            CFG + "use ledger::DurableLearningJournal;\n"
            "impl AgentdIntelligenceProductRunnerV1 {\n"
            + CFG
            + "#[allow(clippy::too_many_arguments)]\n"
            + WRITER
            + "}\n",
        )
        self.assertEqual(self.codes(), [])

    def test_adjacent_ungated_item_and_removed_gate_still_block(self):
        for source in [CFG + WRITER + WRITER.replace("record", "other"), WRITER]:
            with self.subTest(source=source):
                self.write(self.source, source)
                self.assert_raw_blocked()

    def test_nested_comments_strings_raw_strings_and_characters_preserve_extent(self):
        source = (
            CFG + "fn fixture() {\n"
            'let ordinary = "\\"} ]"; let raw = r###"} #[cfg(feature = \\"fake\\")]"###;\n'
            "let byte = b'}'; let character = '\\u{7d}';\n"
            "/* { /* nested } */ ] */ if ready { LedgerEvent::Decision(value); }\n"
            "}\n"
        )
        self.write(self.source, source)
        self.assertEqual(self.codes(), [])
        self.assertEqual(
            mask_qualification_items(source).count("\n"), source.count("\n")
        )
        self.write(self.source, source + WRITER)
        self.assert_raw_blocked()

    def test_comment_or_string_cfg_does_not_protect_real_item(self):
        for prefix in [
            "// " + CFG,
            "/* " + CFG + " */\n",
            'const TEXT: &str = r##"' + CFG + '"##;\n',
        ]:
            with self.subTest(prefix=prefix):
                self.write(self.source, prefix + WRITER)
                self.assert_raw_blocked()

    def test_unknown_cfg_attributes_and_scopes_do_not_earn_exemption(self):
        for source in [
            f'#[cfg(any(feature = "{FEATURE}", unix))]\n' + WRITER,
            f'#[cfg(not(feature = "{FEATURE}"))]\n' + WRITER,
            f'#[cfg_attr(unix, cfg(feature = "{FEATURE}"))]\n' + WRITER,
            "#[unknown_attribute]\n" + CFG + WRITER,
            CFG + "#[unknown_attribute]\n" + WRITER,
            "macro_rules! emitted { () => { " + CFG + WRITER + " }; }\n",
            "#[unknown_attribute]\nimpl AgentdIntelligenceProductRunnerV1 {\n"
            + CFG
            + WRITER
            + "}\n",
            "fn outer() {\n" + CFG + WRITER + "}\n",
        ]:
            with self.subTest(source=source):
                self.write(self.source, source)
                self.assert_raw_blocked()

    def test_unclosed_lexical_or_item_scope_retains_raw_scan(self):
        for suffix in ["/* open", 'const BAD: &str = r###"open;', "fn incomplete("]:
            with self.subTest(suffix=suffix):
                self.write(self.source, CFG + WRITER + suffix)
                self.assert_raw_blocked()

    def test_default_and_transitive_local_features_cannot_enable_legacy(self):
        for replacement in [
            f'default = ["{FEATURE}"]',
            f'default = ["bridge"]\nbridge = ["{FEATURE}"]',
        ]:
            with self.subTest(replacement=replacement):
                self.write(
                    "codex-rs/hepta-agentd/Cargo.toml",
                    self.agent_manifest.replace(
                        'default = ["production-cognitive-write"]', replacement
                    ),
                )
                self.assert_raw_blocked()

    def test_normal_target_renamed_and_forwarded_dependencies_cannot_enable_legacy(
        self,
    ):
        prefix = '[package]\nname = "product"\nversion = "0.0.0"\n'
        for dependency in [
            f'[dependencies]\ncodex-hepta-agentd = {{ path = "../hepta-agentd", features = ["{FEATURE}"] }}\n',
            f'[target.\'cfg(unix)\'.dependencies]\nhost = {{ package = "codex-hepta-agentd", path = "../hepta-agentd", features = ["{FEATURE}"] }}\n',
            '[dependencies]\nhost = { package = "codex-hepta-agentd", path = "../hepta-agentd" }\n'
            f'[features]\ndefault = ["bridge"]\nbridge = ["host/{FEATURE}"]\n',
        ]:
            with self.subTest(dependency=dependency):
                self.write("codex-rs/product/Cargo.toml", prefix + dependency)
                self.assert_raw_blocked()

    def test_inherited_workspace_normal_dependency_cannot_enable_legacy(self):
        self.write(
            "codex-rs/Cargo.toml",
            "[workspace]\nmembers = []\n[workspace.dependencies]\n"
            f'host = {{ package = "codex-hepta-agentd", path = "hepta-agentd", features = ["{FEATURE}"] }}\n',
        )
        self.write(
            "codex-rs/product/Cargo.toml",
            '[package]\nname = "product"\nversion = "0.0.0"\n'
            "[dependencies]\nhost = { workspace = true }\n",
        )
        self.assert_raw_blocked()

    def test_ledger_default_and_normal_features_block_but_dev_dependency_does_not(self):
        path = "codex-rs/hepta-agentd/Cargo.toml"
        dev = (
            "[dev-dependencies]\ncodex-hepta-learning-ledger = "
            '{ path = "../hepta-learning-ledger", features = ["qualification-legacy-write"] }\n'
        )
        self.write(path, self.agent_manifest + dev)
        self.assertEqual(self.codes(), [])
        self.write(
            path,
            self.agent_manifest.replace(
                'path = "../hepta-learning-ledger"',
                'path = "../hepta-learning-ledger", features = ["qualification-legacy-write"]',
            ),
        )
        self.assert_raw_blocked()
        self.write(path, self.agent_manifest)
        ledger = self.root / "codex-rs/hepta-learning-ledger/Cargo.toml"
        ledger.write_text(
            ledger.read_text().replace(
                "default = []", 'default = ["qualification-legacy-write"]'
            )
        )
        self.assert_raw_blocked()

    def test_other_product_normal_build_and_target_ledger_features_block(self):
        for table in [
            "dependencies",
            "build-dependencies",
            "target.'cfg(unix)'.dependencies",
        ]:
            with self.subTest(table=table):
                self.write(
                    "codex-rs/another-product/Cargo.toml",
                    '[package]\nname = "another-product"\nversion = "0.0.0"\n'
                    f'[{table}]\nledger = {{ package = "codex-hepta-learning-ledger", path = "../hepta-learning-ledger", features = ["qualification-legacy-write"] }}\n',
                )
                self.assert_raw_blocked()

    def test_unindexed_local_dependency_does_not_authorize_a_cfg_exemption(self):
        self.write(
            "outside-inventory/Cargo.toml",
            '[package]\nname = "outside"\nversion = "0.0.0"\n',
        )
        self.write(
            "codex-rs/another-product/Cargo.toml",
            '[package]\nname = "another-product"\nversion = "0.0.0"\n'
            '[dependencies]\noutside = { path = "../../outside-inventory" }\n',
        )
        self.assert_raw_blocked()

    def test_inner_attribute_with_a_preceding_item_keeps_the_entire_raw_scan(self):
        self.write(
            self.source,
            "#![unproved_attribute]\nconst FIRST: u8 = 1;\n" + CFG + WRITER,
        )
        self.assert_raw_blocked()

    def test_missing_or_invalid_cargo_proof_keeps_raw_rule(self):
        path = self.root / "codex-rs/hepta-agentd/Cargo.toml"
        for invalid in [
            "[invalid",
            self.agent_manifest.replace(
                'default = ["production-cognitive-write"]',
                f'default = "{FEATURE}"',
            ),
        ]:
            with self.subTest(invalid=invalid):
                path.write_text(invalid)
                self.assert_raw_blocked()
        path.unlink()
        self.assert_raw_blocked()

    def test_same_cfg_in_another_product_crate_does_not_exempt_it(self):
        self.write("codex-rs/another-product/src/lib.rs", CFG + WRITER)
        self.assert_raw_blocked()

    def test_literal_path_include_and_cfg_attr_cannot_reintroduce_custody(self):
        archived = (
            self.root / CUSTODY / "codex-rs/hepta-agentd/src/objective_ingress.rs"
        )
        self.write(archived.relative_to(self.root), "pub fn historical() {}\n")
        for source in [
            f'#[path = "{archived}"] mod old;\n',
            f'include!("{archived}");\n',
            f'include!(r#"{archived}"#);\n',
            f'#[cfg_attr(unix, path = "{archived}")] mod old;\n',
            f'#[cfg_attr(any(unix, windows), cfg_attr(unix, path = "{archived}"))] mod old;\n',
        ]:
            with self.subTest(source=source):
                self.write(self.source, source)
                self.assertIn("legacy_learning_source_import_unproved", self.codes())

    def test_cross_package_source_include_cannot_borrow_agentd_cfg_proof(self):
        target = self.root / self.source
        for source in [
            f'#[path = "{target}"] mod borrowed;\n',
            f'include!("{target}");\n',
        ]:
            with self.subTest(source=source):
                self.write("codex-rs/another-product/src/lib.rs", source)
                self.assertIn("legacy_learning_source_import_unproved", self.codes())

    def test_non_path_attribute_fields_are_not_source_imports(self):
        for source in [
            "#[instrument(skip(config), fields(path = ?config.path))] fn open() {}",
            '#[instrument(name = "request", fields(http.method = %method, api.path = path))] fn call() {}',
        ]:
            with self.subTest(source=source):
                self.write(self.source, source)
                self.assertEqual(self.codes(), [])

    def test_unproved_source_include_is_a_failure_not_an_archive_exemption(self):
        for source in [
            'include!(env!("UNPROVED_SOURCE"));\n',
            'include!(concat!("prefix", "/objective_ingress.rs"));\n',
            "#[path = unknown!()] mod old;\n",
        ]:
            with self.subTest(source=source):
                self.write(self.source, source)
                self.assertIn("legacy_learning_source_import_unproved", self.codes())


if __name__ == "__main__":
    unittest.main()

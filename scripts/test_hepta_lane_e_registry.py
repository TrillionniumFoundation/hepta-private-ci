"""Exercise registered source navigation and preserve actual authority boundaries."""

import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "lane_e_registry", SCRIPTS / "hepta-lane-e-closure.py"
)
assert SPEC and SPEC.loader
lane = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lane
SPEC.loader.exec_module(lane)


class RegisteredSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch = patch.object(lane, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.modules = []
        self.cases = []
        for index, module in enumerate(sorted(lane.EXPECTED_MODULES)):
            source = f"owners/{index}/lib.rs"
            self.write(
                source,
                "pub fn calculate() {}\n#[test] fn behavior() { assert_eq!(2 + 2, 4); }\n",
            )
            guide = f"guides/{index}.md"
            self.write(guide, "Source guide, independent of trace labels.\n")
            self.modules.append(
                {
                    "module": module,
                    "sourceRoot": f"owners/{index}",
                    "stableGuide": guide,
                    "dossier": guide,
                    "nativeMapping": guide,
                    "productionContract": guide,
                    "remainingRepositoryGaps": [],
                    "remainingExternalEvidence": [
                        "independent owner evidence required"
                    ],
                    "operations": [
                        {
                            "operation": "calculate",
                            "nativeSymbol": "crate::calculate",
                            "source": source,
                            "status": "implemented",
                        }
                    ],
                }
            )
            self.cases.append(
                {
                    "id": f"behavior-{index}",
                    "module": module,
                    "status": "native_test_mapped",
                    "tests": [{"source": source, "function": "behavior"}],
                }
            )
        self.matrix = {
            "schema": "hepta.lane-e-implementation-matrix.v1",
            "authorityDelta": "none",
            "capabilityClosureState": "external_evidence_required",
            "modules": self.modules,
            "externalGates": [
                {
                    "id": identity,
                    "repositoryMaySelfCertify": False,
                    "state": "external_evidence_required",
                }
                for identity in lane.EXPECTED_EXTERNAL_GATES
            ],
            "crossCrateQualification": {
                "source": "owners/0/lib.rs",
                "test": "behavior",
            },
        }
        self.trace = {
            "schema": "hepta.lane-e-test-traceability.v1",
            "cases": self.cases,
            "crossCrateCases": [{"source": "owners/0/lib.rs", "function": "behavior"}],
            "productBoundaryCases": [
                {"source": "owners/1/lib.rs", "function": "behavior"}
            ],
        }

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def verify(self):
        findings = lane.Findings()
        modules = lane.verify_matrix(self.matrix, findings)
        lane.verify_traceability(self.trace, modules, findings)
        return findings.items

    def test_new_registered_operations_and_behaviors_use_their_current_source(self):
        self.assertEqual(self.verify(), [])
        for index in range(12):
            name = f"new_operation_{index}"
            source = f"extensions/{index}.rs"
            self.write(
                source,
                f"pub fn {name}() {{}}\n#[test] fn exercises_{name}() {{ assert!(true); }}\n",
            )
            self.modules[0]["operations"].append(
                {
                    "operation": name,
                    "nativeSymbol": f"crate::{name}",
                    "source": source,
                    "status": "implemented",
                }
            )
            self.cases.append(
                {
                    "id": f"extension-{index}",
                    "module": self.modules[0]["module"],
                    "status": "native_test_mapped",
                    "tests": [{"source": source, "function": f"exercises_{name}"}],
                }
            )
            self.assertEqual(self.verify(), [])
        self.write("extensions/11.rs", "pub fn renamed() {}\n")
        codes = {finding.code for finding in self.verify()}
        self.assertIn("native_symbol_unresolved", codes)
        self.assertIn("test_function_unresolved", codes)

    def test_registration_uniqueness_and_behavior_coverage_are_required(self):
        self.modules[0]["operations"].append(
            copy.deepcopy(self.modules[0]["operations"][0])
        )
        self.assertIn(
            "duplicate_or_empty_operation", {finding.code for finding in self.verify()}
        )
        self.modules[0]["operations"].pop()
        self.cases.pop()
        self.assertIn(
            "case_module_coverage", {finding.code for finding in self.verify()}
        )

    def test_external_evidence_cannot_be_self_certified(self):
        self.matrix["externalGates"][0]["repositoryMaySelfCertify"] = True
        self.assertIn(
            "external_gate_self_certified", {finding.code for finding in self.verify()}
        )

    def test_raw_product_writer_bypass_still_blocks(self):
        self.write(
            "codex-rs/real-product/src/lib.rs",
            "fn write() { LedgerEvent::Decision(value); }\n",
        )
        findings = lane.Findings()
        lane.verify_product_writer_exclusivity(findings)
        self.assertEqual(
            [finding.code for finding in findings.items],
            ["legacy_learning_writer_product_bypass"],
        )


class ProductWriterClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch = patch.object(lane, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.manifest = self.root / "codex-rs/product/Cargo.toml"
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text(
            '[package]\nname = "product"\n[features]\ndefault = []\n'
            'qualification-legacy-learning-write = ["ledger/qualification-legacy-write"]\n'
        )
        self.source = self.manifest.parent / "src/lib.rs"
        self.source.parent.mkdir()

    def verify(self, source):
        self.source.write_text(source)
        findings = lane.Findings()
        lane.verify_product_writer_exclusivity(findings)
        return findings.items

    def test_read_only_record_patterns_and_read_trait_import_are_not_appends(self):
        self.assertEqual(
            self.verify("""
use codex_hepta_learning_ledger::DurableLearningJournal;
fn id(event: &LedgerEvent) {
    match event {
        LedgerEvent::Decision(value) => &value.record_id,
        LedgerEvent::Outcome(value) => &value.record_id,
        LedgerEvent::Credit(value) => &value.record_id,
        LedgerEvent::Revocation(value) => &value.record_id,
    }
}
"""),
            [],
        )

    def test_exhaustive_legacy_rejection_and_ignored_arms_are_reads(self):
        source = """
#[derive(Clone, Debug)]
pub struct Material { pub generation: u64 }
fn read(event: &LedgerEvent) {
    match event {
        LedgerEvent::Decision(_) | LedgerEvent::Outcome(_) => {
            return Err("authenticated records required");
        }
        LedgerEvent::Credit(_) | LedgerEvent::Revocation(_) => {}
        _ => {}
    }
}
"""
        self.assertEqual(self.verify(source), [])
        # Only patterns disappear. A constructor in the same arm still blocks.
        findings = self.verify(source.replace(
            'return Err("authenticated records required");',
            'journal.append(head, LedgerEvent::Outcome(value));',
        ))
        self.assertTrue(any("Outcome" in finding.message for finding in findings))

    def test_wildcard_match_exemption_cannot_cross_macro_or_unknown_attribute(self):
        sources = [
            "fn product() { transform!(LedgerEvent::Decision(_) => {}); }",
            "#[rewrite] fn product(event: LedgerEvent) { match event { LedgerEvent::Decision(_) => {} } }",
            "#[rewrite] mod product { fn read(event: LedgerEvent) { match event { LedgerEvent::Credit(_) => {} } } }",
            "#[derive(Clone)] fn product(event: LedgerEvent) { match event { LedgerEvent::Outcome(_) => {} } }",
            "#[derive(Clone)] pub struct Material { field: transform!(LedgerEvent::Revocation(_) => {}) }",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(self.verify(source))

    def test_explicit_disabled_qualification_function_is_not_product_write(self):
        self.assertEqual(
            self.verify("""
#[cfg(feature = "qualification-legacy-learning-write")]
#[allow(clippy::too_many_arguments)]
pub fn fixture() {
    if ready() { journal.append_qualification(head, LedgerEvent::Decision(value)); }
}
"""),
            [],
        )

    def test_adjacent_product_function_is_not_hidden_by_qualification_attribute(self):
        findings = self.verify("""
#[cfg(feature = "qualification-legacy-learning-write")]
fn fixture() { LedgerEvent::Decision(value); }
fn product() { LedgerEvent::Outcome(value); }
""")
        self.assertEqual(len(findings), 1)
        self.assertIn("Outcome", findings[0].message)

    def test_runtime_cfg_and_unknown_compile_condition_never_exempt_writes(self):
        for source in [
            'fn product() { if cfg!(feature = "qualification-legacy-learning-write") { LedgerEvent::Decision(value); } }',
            '#[cfg(any(feature = "qualification-legacy-learning-write", feature = "product"))]\nfn product() { LedgerEvent::Decision(value); }',
            '#[cfg(feature = "qualification-legacy-learning-write")]\nfn broken() { LedgerEvent::Decision(value);',
        ]:
            with self.subTest(source=source):
                self.assertTrue(self.verify(source))

    def test_default_feature_cannot_turn_qualification_into_product_write(self):
        self.manifest.write_text(
            '[package]\nname = "product"\n[features]\n'
            'default = ["enabled"]\nenabled = ["qualification-legacy-learning-write"]\n'
            'qualification-legacy-learning-write = ["ledger/qualification-legacy-write"]\n'
        )
        self.assertTrue(
            self.verify("""
#[cfg(feature = "qualification-legacy-learning-write")]
fn product() { LedgerEvent::Decision(value); }
""")
        )

    def test_normal_consumer_cannot_enable_qualification_for_product_writer(self):
        consumer = self.root / "codex-rs/consumer/Cargo.toml"
        consumer.parent.mkdir()
        consumer.write_text(
            '[package]\nname = "consumer"\n[dependencies]\n'
            'renamed = { package = "product", path = "../product", features = ["qualification-legacy-learning-write"] }\n'
        )
        self.assertTrue(
            self.verify("""
#[cfg(feature = "qualification-legacy-learning-write")]
fn product() { LedgerEvent::Decision(value); }
""")
        )

    def test_consumer_feature_alias_and_workspace_inheritance_do_not_hide_enablement(
        self,
    ):
        self.manifest.write_text(
            self.manifest.read_text()
            + 'indirect = ["qualification-legacy-learning-write"]\n'
        )
        workspace = self.root / "codex-rs/Cargo.toml"
        workspace.write_text(
            '[workspace.dependencies]\nrenamed = { package = "product", path = "product" }\n'
        )
        consumer = self.root / "codex-rs/consumer/Cargo.toml"
        consumer.parent.mkdir()
        for activation in [
            '[dependencies]\nrenamed = { workspace = true, features = ["indirect"] }\n',
            '[features]\ndefault = ["renamed/indirect"]\n[dependencies]\nrenamed = { workspace = true }\n',
        ]:
            consumer.write_text('[package]\nname = "consumer"\n' + activation)
            with self.subTest(activation=activation):
                self.assertTrue(
                    self.verify("""
#[cfg(feature = "qualification-legacy-learning-write")]
fn product() { LedgerEvent::Decision(value); }
""")
                )

    def test_transitive_default_or_optional_consumer_route_prevents_exemption(self):
        mid = self.root / "codex-rs/mid/Cargo.toml"
        mid.parent.mkdir()
        mid.write_text(
            '[package]\nname = "mid"\n[features]\ndefault = []\n'
            'enable = ["product/qualification-legacy-learning-write"]\n'
            '[dependencies]\nproduct = { path = "../product", optional = true }\n'
        )
        source = """
#[cfg(feature = "qualification-legacy-learning-write")]
fn product() { LedgerEvent::Decision(value); }
"""
        # A declared opt-in route is already enough to deny the exemption.
        with self.subTest(route="declared_optional_feature"):
            self.assertTrue(self.verify(source))
        app = self.root / "codex-rs/app/Cargo.toml"
        app.parent.mkdir()
        app.write_text(
            '[package]\nname = "app"\n[features]\ndefault = ["mid/enable"]\n'
            '[dependencies]\nmid = { path = "../mid" }\n'
        )
        with self.subTest(route="transitive_app_default"):
            self.assertTrue(self.verify(source))

    def test_dependency_alias_is_resolved_in_its_own_workspace(self):
        for directory, package in [("a", "product"), ("z", "unrelated")]:
            workspace = self.root / "codex-rs" / directory
            workspace.mkdir()
            (workspace / "Cargo.toml").write_text(
                '[workspace.dependencies]\nrenamed = { package = "'
                + package
                + '", path = "../'
                + package
                + '" }\n'
            )
            member = workspace / "member"
            member.mkdir()
            (member / "Cargo.toml").write_text(
                '[package]\nname = "' + directory + '-consumer"\n'
                '[features]\ndefault = ["renamed/qualification-legacy-learning-write"]\n'
                "[dependencies]\nrenamed = { workspace = true }\n"
            )
        source = """
#[cfg(feature = "qualification-legacy-learning-write")]
fn product() { LedgerEvent::Decision(value); }
"""
        original_rglob = Path.rglob
        with patch.object(
            Path,
            "rglob",
            lambda path, pattern: iter(sorted(original_rglob(path, pattern))),
        ):
            self.assertTrue(self.verify(source))
            consumer = self.root / "codex-rs/a/member/Cargo.toml"
            consumer.write_text(
                consumer.read_text().replace(
                    'default = ["renamed/qualification-legacy-learning-write"]',
                    "default = []",
                )
            )
            self.assertEqual(self.verify(source), [])

    def test_string_dependency_and_nondefault_route_prevent_exemption(self):
        consumer = self.root / "codex-rs/consumer/Cargo.toml"
        consumer.parent.mkdir()
        consumer.write_text(
            '[package]\nname = "consumer"\n'
            '[features]\ndefault = []\nopt_in = ["product/qualification-legacy-learning-write"]\n'
            '[dependencies]\nproduct = "1"\n'
        )
        self.assertTrue(
            self.verify("""
#[cfg(feature = "qualification-legacy-learning-write")]
fn product() { LedgerEvent::Decision(value); }
""")
        )

    def test_explicit_workspace_takes_precedence_over_nearest_workspace(self):
        for directory, package in [("selected", "product"), ("nearest", "unrelated")]:
            workspace = self.root / "codex-rs" / directory
            workspace.mkdir()
            (workspace / "Cargo.toml").write_text(
                '[workspace.dependencies]\nrenamed = { package = "'
                + package
                + '", path = "../'
                + package
                + '" }\n'
            )
        consumer = self.root / "codex-rs/nearest/member/Cargo.toml"
        consumer.parent.mkdir()
        consumer.write_text(
            '[package]\nname = "consumer"\nworkspace = "../../selected"\n'
            '[features]\ndefault = []\noptional_route = ["renamed/qualification-legacy-learning-write"]\n'
            "[dependencies]\nrenamed = { workspace = true }\n"
        )
        self.assertTrue(
            self.verify("""
#[cfg(feature = "qualification-legacy-learning-write")]
fn product() { LedgerEvent::Decision(value); }
""")
        )

    def test_unknown_outer_attributes_cannot_establish_read_or_cfg_exemption(self):
        for source in [
            '#[rewrite]\n#[cfg(feature = "qualification-legacy-learning-write")]\nfn product() { LedgerEvent::Decision(value); }',
            '#[cfg(feature = "qualification-legacy-learning-write")]\n#[rewrite]\nfn product() { LedgerEvent::Decision(value); }',
            '#[rewrite]\nmod product { #[cfg(feature = "qualification-legacy-learning-write")] fn write() { LedgerEvent::Decision(value); } }',
            "#[rewrite]\nfn product(event: LedgerEvent) { match event { LedgerEvent::Decision(value) => &value.record_id, } }",
        ]:
            with self.subTest(source=source):
                self.assertTrue(self.verify(source))

    def test_alias_and_grouped_variant_import_cannot_hide_raw_constructor(self):
        for source in [
            "use codex_hepta_learning_ledger::LedgerEvent as Event; fn product() { Event::Decision(value); }",
            "use codex_hepta_learning_ledger::LedgerEvent::{Decision as D}; fn product() { D(value); }",
            "use codex_hepta_learning_ledger::LedgerEvent::*; fn product() { Decision(value); }",
        ]:
            with self.subTest(source=source):
                self.assertTrue(self.verify(source))

    def test_comments_and_literals_do_not_claim_a_writer(self):
        self.assertEqual(
            self.verify("""
// LedgerEvent::Decision(value)
/* LedgerEvent::Outcome(value) */
const NOTE: &str = r###"LedgerEvent::Revocation(value)"###;
"""),
            [],
        )

    def test_qualification_attribute_in_literal_cannot_hide_next_real_write(self):
        self.assertTrue(
            self.verify("""
const NOTE: &str = r#"#[cfg(feature = "qualification-legacy-learning-write")]
fn fixture() { LedgerEvent::Decision(value); }"#;
fn product() { LedgerEvent::Outcome(value); }
""")
        )

    def test_macro_tokens_never_claim_a_read_only_match_exemption(self):
        self.assertTrue(
            self.verify("""
fn product() {
    transform!(LedgerEvent::Decision(value) => &value.record_id,);
}
""")
        )

    def test_macro_tokens_cannot_claim_a_compile_time_qualification_boundary(self):
        self.assertTrue(
            self.verify("""
transform! {
    #[cfg(feature = "qualification-legacy-learning-write")]
    fn product() { LedgerEvent::Decision(value); }
}
""")
        )

    def test_trait_read_import_does_not_hide_legacy_method_write(self):
        self.assertTrue(
            self.verify("""
use codex_hepta_learning_ledger::DurableLearningJournal;
fn product() { journal.append_decision(head, decision); }
""")
        )

    def test_ufcs_and_trait_alias_do_not_hide_legacy_write(self):
        for source in [
            "fn product() { DurableLedger::append_qualification(journal, head, event); }",
            "fn product() { let write = DurableLedger::append_qualification; write(journal, head, event); }",
            "use codex_hepta_learning_ledger::DurableLearningJournal as Journal; fn product() { Journal::append_decision(journal, head, decision); }",
            "use codex_hepta_learning_ledger::DurableLearningJournal as Journal; fn product() { let write = Journal::append_decision; write(journal, head, decision); }",
            "fn product<T: DurableLearningJournal>() { <T as DurableLearningJournal>::append_decision(journal, head, decision); }",
            "use codex_hepta_learning_ledger::DurableLearningJournal; fn product() { DurableLedger::append_decision(journal, head, decision); }",
            "use codex_hepta_learning_ledger::DurableLearningJournal; use codex_hepta_learning_ledger::DurableLedger as Ledger; fn product() { let write = Ledger::append_decision; write(journal, head, decision); }",
        ]:
            with self.subTest(source=source):
                self.assertTrue(self.verify(source))


class DefaultAuthoritySurfaceTests(unittest.TestCase):
    def test_unsigned_direct_alias_and_wildcard_exports_are_rejected(self):
        for source in [
            "pub\nfn decide_independently() {}",
            "pub use closure::{decide_independently as renamed, Other};",
            "pub use closure::*;",
            "pub use module::evaluate;",
        ]:
            with self.subTest(source=source):
                self.assertTrue(lane.unsigned_root_exports(source))

    def test_signed_api_and_explicit_trusted_module_preserve_default_boundary(self):
        source = """
        // pub use closure::decide_independently;
        const NOTE: &str = "pub fn evaluate() {}";
        pub(crate) use closure::decide_independently;
        pub use signed_evaluation::decide_with_signed_evidence_v2;
        #[cfg(feature = "trusted-inprocess-eval")]
        pub mod trusted_inprocess { pub fn decide_independently() {} }
        """
        self.assertEqual(lane.unsigned_root_exports(source), set())


if __name__ == "__main__":
    unittest.main()

"""Exercise registered source navigation and preserve actual authority boundaries."""

import copy
import importlib.util
import json
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
        matrix_patch = patch.object(
            lane,
            "MATRIX_PATH",
            self.root / "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json",
        )
        matrix_patch.start()
        self.addCleanup(matrix_patch.stop)
        self.modules = []
        self.cases = []
        canonical_modules = []
        for index, module in enumerate(sorted(lane.EXPECTED_MODULES)):
            source = f"owners/{index}/lib.rs"
            self.write(
                source,
                "pub fn calculate() {}\n#[test] fn behavior() { assert_eq!(2 + 2, 4); }\n",
            )
            guide = f"guides/{index}.md"
            self.write(guide, "Source guide, independent of trace labels.\n")
            dossier = f"qualification/module-execution-dossiers/detail/{module}.md"
            case_id = f"BEHAVIOR-{index:02d}"
            self.write(
                dossier, f"- {case_id}: calculate uses its current owner source.\n"
            )
            canonical_modules.append(
                {"id": module, "rootBindings": [{"path": f"owners/{index}"}]}
            )
            self.modules.append(
                {
                    "module": module,
                    "sourceRoot": f"owners/{index}",
                    "stableGuide": guide,
                    "dossier": dossier,
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
                    "id": case_id,
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
        self.write(
            "docs/modules/MODULES.json", json.dumps({"modules": canonical_modules})
        )
        self.register_matrix()

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def verify(self):
        findings = lane.Findings()
        modules = lane.verify_matrix(self.matrix, findings)
        lane.verify_traceability(self.trace, modules, findings)
        return findings.items

    def register_matrix(self):
        self.write(
            "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json", json.dumps(self.matrix)
        )

    def test_new_registered_operations_and_behaviors_use_their_current_source(self):
        self.assertEqual(self.verify(), [])
        for index in range(12):
            name = f"new_operation_{index}"
            source = f"owners/0/extensions/{index}.rs"
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
                    "id": f"EXTENSION-{index:02d}",
                    "module": self.modules[0]["module"],
                    "status": "native_test_mapped",
                    "tests": [{"source": source, "function": f"exercises_{name}"}],
                }
            )
            # Editing a supplied navigation document is insufficient. Register
            # both the owner source binding and its behavioral dossier case.
            codes = {finding.code for finding in self.verify()}
            self.assertIn("operation_closed_world", codes)
            self.assertIn("case_closed_world", codes)
            self.register_matrix()
            dossier = self.root / self.modules[0]["dossier"]
            dossier.write_text(
                dossier.read_text()
                + f"- EXTENSION-{index:02d}: exercise the new owner entrypoint.\n"
            )
            self.assertEqual(self.verify(), [])
        self.write("owners/0/extensions/11.rs", "pub fn renamed() {}\n")
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

    def test_foreign_owner_symlink_file_is_rejected_before_source_read(self):
        self.assertEqual(self.verify(), [])
        source = self.root / "owners/0/lib.rs"
        source.unlink()
        source.symlink_to(self.root / "owners/1/lib.rs")
        codes = {finding.code for finding in self.verify()}
        self.assertIn("invalid_path", codes)
        self.assertIn("operation_source_missing", codes)
        self.assertIn("test_source_missing", codes)

    def test_foreign_owner_symlink_directory_is_rejected_before_source_read(self):
        self.assertEqual(self.verify(), [])
        owner = self.root / "owners/0"
        owner.rename(self.root / "owners/original")
        owner.symlink_to(self.root / "owners/1", target_is_directory=True)
        codes = {finding.code for finding in self.verify()}
        self.assertIn("invalid_path", codes)
        self.assertIn("operation_source_missing", codes)
        self.assertIn("test_source_missing", codes)

    def test_canonical_registry_files_cannot_follow_external_symlinks(self):
        self.assertEqual(self.verify(), [])
        for relative, expected in (
            ("docs/modules/MODULES.json", "canonical_registry_invalid"),
            (
                "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json",
                "canonical_operation_registry_invalid",
            ),
            (self.modules[0]["dossier"], "canonical_case_registry_invalid"),
        ):
            with self.subTest(registry=relative):
                registry = self.root / relative
                contents = registry.read_text()
                # The external target contains valid unchanged registry bytes;
                # accepting it would admit bytes outside the candidate checkout.
                with tempfile.TemporaryDirectory() as external_directory:
                    external = Path(external_directory) / "registry"
                    external.write_text(contents)
                    registry.unlink()
                    registry.symlink_to(external)
                    self.assertIn(expected, {f.code for f in self.verify()})
                    registry.unlink()
                    registry.write_text(contents)
                self.assertEqual(self.verify(), [])

    def test_comments_literals_and_docs_cannot_forge_current_source_or_behavior(self):
        for source in (
            "// pub fn calculate() {}\n// #[test] fn behavior() {}\n",
            "/* pub fn calculate() {}\n#[test] fn behavior() {} */\n",
            'const NOTE: &str = "pub fn calculate() {} fn behavior() {}";\n',
            'const NOTE: &str = r##"pub fn calculate() {} fn behavior() {}"##;\n',
            "/// ```rust\n/// pub fn calculate() {}\n/// fn behavior() {}\n/// ```\n",
        ):
            with self.subTest(source=source):
                self.write("owners/0/lib.rs", source + "pub fn unrelated() {}\n")
                codes = {finding.code for finding in self.verify()}
                self.assertIn("native_symbol_unresolved", codes)
                self.assertIn("cross_crate_test_missing", codes)
                self.assertIn("test_function_unresolved", codes)
                self.assertIn("cross_case_unresolved", codes)
                self.trace["productBoundaryCases"][0]["source"] = "owners/0/lib.rs"
                codes = {finding.code for finding in self.verify()}
                self.assertIn("boundary_function_unresolved", codes)

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


class DefaultAuthoritySurfaceTests(unittest.TestCase):
    def test_source_symbols_distinguish_types_methods_and_free_functions(self):
        self.assertTrue(lane.verify_symbol("pub struct Demo;", "crate::Demo"))
        self.assertTrue(
            lane.verify_symbol(
                "pub struct Demo; impl Demo { pub fn execute(&self) {} }",
                "crate::Demo::execute",
            )
        )
        self.assertTrue(lane.verify_symbol("pub fn execute() {}", "crate::execute"))
        self.assertFalse(
            lane.verify_symbol("pub fn execute() {}", "<Demo as Contract>::execute")
        )
        for source in (
            "pub struct Demo; impl Demo {} pub fn execute() {}",
            "pub struct Demo; pub struct Other; impl Demo {} "
            "impl Other { pub fn execute() {} }",
            "pub struct Demo; impl Demo { pub fn unrelated() { fn execute() {} } }",
            "pub fn unrelated() { struct Demo; "
            "impl Demo { pub fn execute(&self) {} } }",
            "mod nested { pub struct Demo; impl Demo { pub fn execute(&self) {} } }",
            "pub struct Demo; pub fn unrelated() { struct Demo; "
            "impl Demo { pub fn execute(&self) {} } }",
        ):
            with self.subTest(source=source):
                self.assertFalse(lane.verify_symbol(source, "crate::Demo::execute"))
        self.assertFalse(
            lane.verify_symbol(
                "pub struct Demo; impl Demo { pub fn execute(&self) {} }",
                "crate::execute",
            )
        )
        for source in (
            "// pub struct Demo;\npub fn unrelated() {}",
            'const NOTE: &str = "pub struct Demo;";',
            "pub fn Demo() {}",
            "pub fn unrelated() { struct Demo; }",
            "mod nested { pub struct Demo; }",
        ):
            with self.subTest(source=source):
                self.assertFalse(lane.verify_symbol(source, "crate::Demo"))

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

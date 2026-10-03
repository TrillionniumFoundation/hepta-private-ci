"""Exercise registered source navigation and preserve actual authority boundaries."""

import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
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

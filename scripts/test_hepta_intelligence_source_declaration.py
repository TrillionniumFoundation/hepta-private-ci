"""Exercise the explicit source-only schema adapter in real Git checkouts."""

import copy
import unittest

import test_hepta_implementation_maps as provenance_tests

maps = provenance_tests.maps


class IntelligenceSourceDeclarationTests(unittest.TestCase):
    git = provenance_tests.SourceIdentityTests.git
    write = provenance_tests.SourceIdentityTests.write
    commit = provenance_tests.SourceIdentityTests.commit
    module = provenance_tests.SourceIdentityTests.module
    row = provenance_tests.SourceIdentityTests.row
    save_maps = provenance_tests.SourceIdentityTests.save_maps
    change_maps = provenance_tests.SourceIdentityTests.change_maps
    verify = provenance_tests.SourceIdentityTests.verify
    reject = provenance_tests.SourceIdentityTests.reject

    def setUp(self):
        provenance_tests.SourceIdentityTests.setUp(self)
        self.module_row = copy.deepcopy(self.modules[0])
        self.module_row["id"] = "intelligence.control"
        self.module_row["technicalDocument"] = (
            "docs/modules/intelligence.control/TECHNICAL.md"
        )
        self.modules[0] = self.module_row
        self.write("docs/modules/MODULES.json", {"modules": self.modules})
        self.write(
            "docs/modules/intelligence.control/TECHNICAL.md",
            "Pending source declaration",
        )
        self.write(
            "docs/readiness/READINESS.json",
            {
                "implementationLanes": [
                    {"id": "test-lane", "modules": ["intelligence.control", "beta"]}
                ],
            },
        )
        self.declaration = {
            "schema": maps.INTELLIGENCE_DECLARATION_SCHEMA,
            "schemaVersion": 1,
            "module": "intelligence.control",
            "declaredRoots": ["src/alpha"],
            "technicalGuide": "docs/modules/intelligence.control/TECHNICAL.md",
            "validatedAndProjectedBy": "scripts/hepta-intelligence-control-status.py",
            "sourceIdentity": {
                "policy": "ci_exact_head_artifact_v2",
                "commit": "CI_EXACT_HEAD",
                "lane": "tracked",
                "executionStatus": "pending",
                "commitMustEqualCheckoutHead": True,
            },
            "sourceBindings": [
                {"sourcePath": "src/alpha/lib.rs", "symbols": ["calculate"]}
            ],
            "statusMatrix": {
                field: False
                for field in (
                    "nativeBuildVerified",
                    "exactHeadExecuted",
                    "syntheticMergeExecuted",
                    "defaultBinaryProfileComposed",
                    "realProcessProviderE2E",
                    "targetHostQualified",
                    "independentAcceptance",
                    "activation",
                    "release",
                    "allRequirementsClosed",
                )
            },
        }
        self.write(
            "scripts/hepta-intelligence-control-status.py",
            """
import json
from pathlib import Path
def validate_declarations():
    docs = Path(__file__).resolve().parents[1] / 'docs/modules/intelligence.control'
    return (json.loads((docs / 'IMPLEMENTATION_MAP.json').read_text()),
            json.loads((docs / 'TEST_TRACEABILITY.json').read_text()))
""",
        )
        self.write(
            "docs/modules/intelligence.control/TEST_TRACEABILITY.json",
            {
                "ordinaryProductTests": [
                    {"sourcePath": "tests/native.rs", "name": "qualified"}
                ],
                "qualificationOnlyTests": [],
            },
        )
        self.save_declaration()
        self.commit("registered pending source declaration")

    def save_declaration(self):
        self.write(
            "docs/modules/intelligence.control/IMPLEMENTATION_MAP.json",
            self.declaration,
        )

    def test_pending_declaration_is_counted_separately_without_historical_anchor(self):
        result = self.verify()
        self.assertEqual(result["trackedSourceDeclarationMaps"], 1)
        self.assertEqual(result["sourceObservationCount"], 1)
        self.assertFalse(result["productionImplementationProved"])
        self.assertNotIn("sourceBase", self.declaration)

    def test_adapter_rejects_every_execution_acceptance_and_release_promotion(self):
        for field in self.declaration["statusMatrix"]:
            with self.subTest(field=field):
                self.declaration["statusMatrix"][field] = True
                self.save_declaration()
                self.commit("hostile promotion")
                self.reject()
                self.declaration["statusMatrix"][field] = False

    def test_adapter_rejects_wrong_head_identity_and_schema_module_substitution(self):
        for key, value in (
            ("schema", "hepta.module-implementation-map.v3"),
            ("schemaVersion", True),
            ("module", "beta"),
            ("sourceIdentity", {"commit": "0" * 40}),
            ("validatedAndProjectedBy", "scripts/other.py"),
        ):
            with self.subTest(key=key):
                original = copy.deepcopy(self.declaration)
                self.declaration[key] = value
                self.save_declaration()
                self.commit("hostile schema identity")
                self.reject()
                self.declaration = original

    def test_adapter_rejects_registry_root_drift_and_untracked_evidence(self):
        self.declaration["declaredRoots"] = ["src/beta"]
        self.save_declaration()
        self.commit("wrong registered root")
        self.reject()
        self.declaration["declaredRoots"] = ["src/alpha"]
        self.declaration["sourceBindings"].append(
            {"sourcePath": "src/alpha/untracked.rs"}
        )
        self.save_declaration()
        self.commit("missing declared source")
        self.write("src/alpha/untracked.rs", "pub fn missing() {}\n")
        self.reject()

    def test_owner_validator_failure_is_never_downgraded_to_navigation_success(self):
        self.write(
            "scripts/hepta-intelligence-control-status.py",
            """
def validate_declarations():
    raise ValueError('owner rejects malformed source/test declaration')
""",
        )
        self.commit("owner validator rejects declaration")
        with self.assertRaisesRegex(SystemExit, "owner rejects malformed"):
            self.verify()

    def test_symlinked_registered_verifier_and_source_evidence_reject(self):
        verifier = self.root / "scripts/hepta-intelligence-control-status.py"
        self.write("scripts/linked-owner.py", verifier.read_text())
        verifier.unlink()
        verifier.symlink_to("linked-owner.py")
        self.commit("linked verifier")
        self.reject()


if __name__ == "__main__":
    unittest.main()

"""Qualification-only implementation contract test suite."""
from implementation_contract_tests_core import *  # noqa: F403
from implementation_contract_tests_system import *  # noqa: F403
from implementation_contract_tests_bindings import *  # noqa: F403

import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import implementation_contracts as contracts


class ConservativeProfileStateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.profile_path = self.root / contracts.REL / "IMPLEMENTATION_PROFILES.json"
        shutil.copytree(contracts.ROOT / contracts.REL, self.root / contracts.REL)
        self.profiles = contracts.read_json(self.profile_path)
        completion = contracts.read_json(
            contracts.ROOT / contracts.REL / "IMPLEMENTATION_COMPLETION.json"
        )
        paths = set(self.profiles["readWith"])
        paths.update(
            path
            for requirement in completion["designRequirements"]
            for path in requirement["documents"]
        )
        for relative in paths:
            source = contracts.ROOT / relative
            destination = self.root / relative
            if source.is_file() and not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        self.states = {
            "kernel.operations": "durable_source_implemented_product_execution_pending",
            "neuron.runtime": "source_owner_implemented_not_product_evidence",
        }

    def write_profiles(self, profiles):
        self.profile_path.write_text(contracts.json.dumps(profiles), encoding="utf-8")

    def verify_baseline(self):
        self.write_profiles(self.profiles)
        result = contracts.verify_bundle(self.root)
        self.assertEqual(result["modules"], 40)
        self.assertFalse(result["nativeProductTestsExecuted"])
        self.assertFalse(result["allGapsClosed"])

    def test_real_bundle_accepts_both_registered_conservative_states(self):
        rows = {row["module"]: row for row in self.profiles["modules"]}
        self.assertEqual(
            {module: rows[module]["implementationState"] for module in self.states},
            self.states,
        )
        self.verify_baseline()

    def test_unknown_states_still_reject(self):
        self.verify_baseline()
        for module in self.states:
            with self.subTest(module=module):
                profiles = deepcopy(self.profiles)
                row = next(row for row in profiles["modules"] if row["module"] == module)
                row["implementationState"] = "unknown_source_or_execution_claim"
                self.write_profiles(profiles)
                with self.assertRaisesRegex(contracts.Invalid, "false source or deployment closure"):
                    contracts.verify_bundle(self.root)

    def test_all_four_positive_row_claim_mutations_still_reject(self):
        self.verify_baseline()
        for module in self.states:
            for field in ("productTestsExecuted", "deploymentQualified"):
                with self.subTest(module=module, field=field):
                    profiles = deepcopy(self.profiles)
                    row = next(row for row in profiles["modules"] if row["module"] == module)
                    row[field] = True
                    self.write_profiles(profiles)
                    with self.assertRaisesRegex(contracts.Invalid, "false source or deployment closure"):
                        contracts.verify_bundle(self.root)

    def test_native_mapping_requirement_still_rejects_false(self):
        self.verify_baseline()
        for module in self.states:
            with self.subTest(module=module):
                profiles = deepcopy(self.profiles)
                row = next(row for row in profiles["modules"] if row["module"] == module)
                row["nativeMappingRequired"] = False
                self.write_profiles(profiles)
                with self.assertRaisesRegex(contracts.Invalid, "false source or deployment closure"):
                    contracts.verify_bundle(self.root)

    def test_every_global_positive_capability_claim_still_rejects(self):
        self.verify_baseline()
        for field in self.profiles["claimBoundary"]:
            with self.subTest(field=field):
                profiles = deepcopy(self.profiles)
                profiles["claimBoundary"][field] = True
                self.write_profiles(profiles)
                with self.assertRaisesRegex(contracts.Invalid, "positive document capability claim"):
                    contracts.verify_bundle(self.root)


if __name__ == "__main__":
    import unittest
    unittest.main()

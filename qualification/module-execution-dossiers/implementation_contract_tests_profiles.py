"""Verify exported source profiles without upgrading their evidence claims."""

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import implementation_contracts as contracts


class ImplementationProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile_path = self.root / contracts.REL / "IMPLEMENTATION_PROFILES.json"
        self.profiles = contracts.read_json(
            contracts.ROOT / contracts.REL / "IMPLEMENTATION_PROFILES.json"
        )
        completion = contracts.read_json(
            contracts.ROOT / contracts.REL / "IMPLEMENTATION_COMPLETION.json"
        )
        paths = {
            str(contracts.REL / name)
            for name in (
                "IMPLEMENTATION_PROFILES.json",
                "IMPLEMENTATION_COMPLETION.json",
                "NATIVE_BINDINGS.json",
            )
        }
        paths.update(self.profiles["readWith"])
        for requirement in completion["designRequirements"]:
            paths.update(requirement["documents"])
        for relative in paths:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(contracts.ROOT / relative, destination)

    def write_profiles(self, profiles):
        self.profile_path.write_text(json.dumps(profiles), encoding="utf-8")

    def test_current_source_profiles_pass_without_product_evidence(self):
        report = contracts.verify_bundle(self.root)
        self.assertEqual(
            report,
            {
                "kind": "documentation_bundle_conformance",
                "modules": 40,
                "designRequirements": 16,
                "sourceObservations": 40,
                "repositoryBindingsChecked": False,
                "nativeProductTestsExecuted": False,
                "independentReview": False,
                "allGapsClosed": False,
            },
        )

    def test_source_states_cannot_promote_or_coerce_product_flags(self):
        for module in ("kernel.operations", "neuron.runtime"):
            for flag in ("productTestsExecuted", "deploymentQualified"):
                for value in (True, 0, 1, "false", None, []):
                    with self.subTest(module=module, flag=flag, value=value):
                        profiles = deepcopy(self.profiles)
                        row = next(
                            r for r in profiles["modules"] if r["module"] == module
                        )
                        row[flag] = value
                        self.write_profiles(profiles)
                        with self.assertRaisesRegex(
                            contracts.Invalid, "false source or deployment closure"
                        ):
                            contracts.verify_bundle(self.root)

    def test_source_states_require_both_product_flags(self):
        for module in ("kernel.operations", "neuron.runtime"):
            for flag in ("productTestsExecuted", "deploymentQualified"):
                with self.subTest(module=module, flag=flag):
                    profiles = deepcopy(self.profiles)
                    row = next(r for r in profiles["modules"] if r["module"] == module)
                    del row[flag]
                    self.write_profiles(profiles)
                    with self.assertRaisesRegex(
                        contracts.Invalid, "false source or deployment closure"
                    ):
                        contracts.verify_bundle(self.root)

    def test_unknown_missing_or_untyped_source_state_rejects(self):
        for module in ("kernel.operations", "neuron.runtime"):
            for value in ("production_qualified", "unknown_state", None, 0, []):
                with self.subTest(module=module, value=value):
                    profiles = deepcopy(self.profiles)
                    row = next(r for r in profiles["modules"] if r["module"] == module)
                    if value is None:
                        del row["implementationState"]
                    else:
                        row["implementationState"] = value
                    self.write_profiles(profiles)
                    with self.assertRaisesRegex(
                        contracts.Invalid, "false source or deployment closure"
                    ):
                        contracts.verify_bundle(self.root)

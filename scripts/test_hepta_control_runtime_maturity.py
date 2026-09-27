"""Closed-world and non-authorizing maturity projection regression tests."""
import copy
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "control_maturity", Path(__file__).with_name("hepta-control-runtime-maturity.py"))
assert spec is not None and spec.loader is not None
maturity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maturity)


def fixture():
    return {
        "schema": "hepta.control-runtime-maturity.v1", "schemaVersion": 1,
        "module": "control.runtime", "authorityDelta": "none",
        "sourceObservation": {"selfAuthenticatingTrackedShaClaim": False,
                              "historicalBaseCommit": "a" * 40},
        "externalGovernance": {key: False for key in maturity.GOVERNANCE},
        "subsystems": {key: {"state": "source_candidate", "productionComposed": False}
                       for _, key in maturity.SUBSYSTEMS},
        "productCallerState": "read_only_candidate", "productionWriterState": "not_composed",
        "completion": {"activationState": "not_established"},
    }


class MaturityTests(unittest.TestCase):
    def test_valid_closed_manifest(self):
        maturity.validate_manifest(fixture())

    def test_missing_governance_is_not_vacuously_accepted(self):
        value = fixture()
        value["externalGovernance"] = {}
        with self.assertRaises(ValueError):
            maturity.validate_manifest(value)

    def test_only_literal_false_is_accepted(self):
        for bad in (0, None, "", [], {}, True, "false"):
            with self.subTest(bad=bad):
                value = fixture()
                value["externalGovernance"]["activation"] = bad
                with self.assertRaises(ValueError):
                    maturity.validate_manifest(value)

    def test_missing_and_unknown_subsystems_reject(self):
        for missing in (True, False):
            value = fixture()
            if missing:
                del value["subsystems"]["organHost"]
            else:
                value["subsystems"]["unregistered"] = {"state": "done", "productionComposed": False}
            with self.assertRaises(ValueError):
                maturity.validate_manifest(value)

    def test_boolean_is_not_a_schema_version(self):
        value = fixture()
        value["schemaVersion"] = True
        with self.assertRaises(ValueError):
            maturity.validate_manifest(value)

    def test_non_boolean_composition_rejects(self):
        value = fixture()
        value["subsystems"]["plannerKernel"]["productionComposed"] = "false"
        with self.assertRaises(ValueError):
            maturity.validate_manifest(value)

    def test_projection_preserves_historical_provenance_and_operations(self):
        original = {"sourceBase": {"commit": "b" * 40}, "operations": [{"operation": "prepare_plan"}]}
        before = copy.deepcopy(original)
        projected = maturity.projected_map(fixture(), original)
        self.assertEqual(original, before)
        self.assertEqual(projected["sourceBase"], before["sourceBase"])
        self.assertEqual(projected["operations"], before["operations"])

    def test_signature_and_anchor_references_do_not_become_verified_authority(self):
        text = maturity.render_current(fixture())
        self.assertIn("not a cryptographic signature verification", text)
        self.assertIn("not an independently verified non-regressing anchor", text)

    def test_read_only_cli_modes(self):
        self.assertEqual(maturity.parse_mode([]), "check")
        self.assertEqual(maturity.parse_mode(["check"]), "check")
        self.assertEqual(maturity.parse_mode(["--check"]), "check")
        self.assertEqual(maturity.parse_mode(["sync"]), "sync")
        with self.assertRaises(SystemExit):
            maturity.parse_mode(["sync", "--check"])


if __name__ == "__main__":
    unittest.main()

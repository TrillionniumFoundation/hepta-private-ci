"""Exercise the new declarations with original artifact reads, never model fits."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

import hepta_cell_joint_config as joint
from hepta_cell_research_gate import Evidence
import hepta_prospective_comparison as comparison


class ProspectiveComparisonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def artifact(self, name, content):
        raw = content.encode()
        (self.root / name).write_bytes(raw)
        return {
            "path": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    def contract(self, kind):
        common = {name: self.artifact(name, name) for name in comparison.COMMON}
        parent = self.artifact("parent", "original improver")
        arms = []
        for role, mode in comparison.ROLES[kind].items():
            implementation = (
                parent
                if kind == "improver_inheritance" and role != "new_improver"
                else self.artifact(role, "implementation:" + role)
            )
            arms.append(
                {
                    "role": role,
                    "mode": mode,
                    "implementation": implementation,
                    "parent_improver_sha256": parent["sha256"]
                    if kind == "improver_inheritance"
                    else None,
                    "fixed_inputs": {
                        name: value["sha256"] for name, value in common.items()
                    },
                }
            )
        return {
            "schema": comparison.SCHEMA,
            "comparison": kind,
            "registration": self.artifact(
                "registration", "prospective registered plan"
            ),
            "common": common,
            "arms": arms,
        }

    def inspect(self, contract):
        with joint.directory_root(self.root) as descriptor:
            evidence = Evidence(descriptor)
            result = comparison.review(contract, evidence)
            evidence.finish()
            return result

    def test_complete_panels_bind_originals_without_scientific_admission(self):
        for kind in comparison.ROLES:
            with self.subTest(kind=kind):
                document = self.contract(kind)
                result = self.inspect(document)
                self.assertEqual(
                    result["fixed_inputs"], document["arms"][0]["fixed_inputs"]
                )
                self.assertTrue(result["mechanical_ready"])
                self.assertFalse(result["research_advancement"])
                self.assertFalse(result["preregistration_verified"])
                self.assertFalse(result["hidden_evaluation_verified"])
                self.assertFalse(result["matched_opportunity_verified"])

    def test_missing_controls_and_renaming_cannot_complete_panel(self):
        for kind in comparison.ROLES:
            document = self.contract(kind)
            for transform in ("drop", "duplicate", "rename", "mode"):
                changed = deepcopy(document)
                if transform == "drop":
                    changed["arms"].pop()
                elif transform == "duplicate":
                    changed["arms"][-1] = changed["arms"][0]
                elif transform == "rename":
                    changed["arms"][-1]["role"] = "other"
                else:
                    changed["arms"][-1]["mode"] = "unsupported"
                with (
                    self.subTest(kind=kind, change=transform),
                    self.assertRaises(ValueError),
                ):
                    self.inspect(changed)

    def test_each_arm_must_keep_initial_system_history_and_all_fixed_inputs(self):
        for kind in comparison.ROLES:
            document = self.contract(kind)
            for position in range(len(document["arms"])):
                for name in comparison.COMMON:
                    changed = deepcopy(document)
                    changed["arms"][position]["fixed_inputs"][name] = "0" * 64
                    with (
                        self.subTest(kind=kind, arm=position, input=name),
                        self.assertRaises(ValueError),
                    ):
                        self.inspect(changed)

    def test_non_improver_panels_cannot_declare_inheritance(self):
        for kind in comparison.ROLES.keys() - {"improver_inheritance"}:
            document = self.contract(kind)
            for arm in document["arms"]:
                arm["parent_improver_sha256"] = "0" * 64
                with (
                    self.subTest(kind=kind, arm=arm["role"]),
                    self.assertRaises(ValueError),
                ):
                    self.inspect(document)
                arm["parent_improver_sha256"] = None

    def test_improver_update_requires_parent_bytes_and_isolated_controls(self):
        document = self.contract("improver_inheritance")
        for position in range(4):
            changed = deepcopy(document)
            changed["arms"][position]["parent_improver_sha256"] = "0" * 64
            with self.subTest(parent=position), self.assertRaises(ValueError):
                self.inspect(changed)
        for position in (1, 2, 3):
            changed = deepcopy(document)
            changed["arms"][position]["implementation"] = document["arms"][
                0 if position == 1 else 1
            ]["implementation"]
            with self.subTest(implementation=position), self.assertRaises(ValueError):
                self.inspect(changed)

    def test_original_byte_changes_and_caller_promotion_flags_rejected(self):
        document = self.contract("temporal_kernel")
        for binding in (
            document["registration"],
            document["common"]["original_history"],
            document["arms"][0]["implementation"],
        ):
            path = self.root / binding["path"]
            raw = path.read_bytes()
            path.write_bytes(raw + b"changed")
            with self.assertRaises(ValueError):
                self.inspect(document)
            path.write_bytes(raw)
        document["research_advancement"] = True
        with self.assertRaises(ValueError):
            self.inspect(document)


if __name__ == "__main__":
    unittest.main()

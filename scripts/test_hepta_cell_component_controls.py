"""Exercise real gate artifact reads. All configurations and outcomes are fixtures."""

import copy
import unittest

import hepta_cell_component_controls as controls
import test_hepta_cell_research_gate as fixtures
import test_hepta_cell_research_units as unit_fixtures


class ComponentControlTests(unittest.TestCase):
    setUp = unit_fixtures.ResearchUnitsTests.setUp
    git = fixtures.ResearchGateTests.git
    bind = fixtures.ResearchGateTests.bind
    assess = fixtures.ResearchGateTests.assess
    put = fixtures.ResearchGateTests.put
    screen = unit_fixtures.ResearchUnitsTests.screen
    experiment = unit_fixtures.ResearchUnitsTests.experiment

    def panel(self, kind="single_class"):
        name = "ORG-1" if kind == "full_system" else "MEM-1"
        record = self.experiment(name)
        common = {key: self.bind(key + ".bin", key.encode()) for key in controls.COMMON}
        components = {
            key: self.bind(key + ".bin", key.encode())
            for key in ("PERC", "MEM", "PRED", "CTRL", "VERIFY", "ACT", "LEARN")
        }
        graph = self.bind("graph.bin", b"fixed organization")
        configurations = {}
        for arm in ("candidate", *self.protocol["experiments"][name]["baselines"]):
            selected = copy.deepcopy(components)
            selected["MEM"] = self.bind(arm + "-memory.bin", arm.encode())
            configurations[arm] = {
                "schema": "hepta.cell-arm-configuration.v1",
                "arm_id": arm,
                "role": "candidate"
                if arm == "candidate"
                else ("matched_control" if kind == "single_class" else "strong_agent"),
                "fixed_inputs": copy.deepcopy(common),
                "components": selected
                if kind == "single_class" or arm == "candidate"
                else None,
                "organization": graph,
                "implementation": self.bind(
                    arm + "-implementation.bin", (arm + " code").encode()
                ),
            }
        document = {
            "schema": controls.SCHEMA,
            "comparison": kind,
            "target_component": "MEM" if kind == "single_class" else None,
            "common": common,
            "arms": {},
        }
        record["design"]["schema"] = "hepta.cell-research-design.v2"
        return record, document, configurations

    def bind_panel(self, record, document, configurations):
        document["arms"] = {
            arm: self.bind(arm + "-config.json", config)
            for arm, config in configurations.items()
        }
        record["design"]["controls"] = self.bind("controls.json", document)

    def inspect(self, record, document, configurations):
        self.bind_panel(record, document, configurations)
        return self.screen(record)

    def test_original_single_class_controls_enable_only_mechanical_screen(self):
        result = self.inspect(*self.panel())
        self.assertTrue(result["numerical_screen_ready"])
        self.assertTrue(result["control_design_integrity_verified"])
        checked = result["component_controls"]
        self.assertTrue(checked["component_isolation_integrity_verified"])
        for key in (
            "actual_execution_verified",
            "complete_cost_verified",
            "strong_control_quality_verified",
            "preregistration_verified",
            "authority_granted",
            "research_advancement",
            "component_semantics_verified",
        ):
            self.assertFalse(checked[key])
        self.assertFalse(result["new_milestone_eligible"])
        self.assertFalse(self.assess()["authority_granted"])

    def test_old_design_keeps_arithmetic_but_cannot_complete_screen(self):
        result = self.screen(self.experiment())
        self.assertTrue(result["descriptive_threshold_met"])
        self.assertFalse(result["numerical_screen_ready"])
        self.assertFalse(result["control_design_integrity_verified"])
        self.assertIn("CONTROL_DESIGN_UNVERIFIED", result["blockers"])

    def test_legacy_experiment_plus_new_control_design_still_cannot_pass_screen(self):
        self.protocol["schema"] = "hepta.cell-research-protocol.v1"
        for spec in self.protocol["experiments"].values():
            del spec["sampling"]
        self.manifest["protocol"] = self.bind("protocol.json", self.protocol)
        record, document, configurations = self.panel()
        self.bind_panel(record, document, configurations)
        record["registry"]["attempt_ids"] = [
            row["attempt_id"] for row in record["attempts"]["rows"]
        ]
        result = fixtures.ResearchGateTests.screen(self, record)
        self.assertTrue(result["control_design_integrity_verified"])
        self.assertTrue(result["descriptive_threshold_met"])
        self.assertFalse(result["numerical_screen_ready"])

    def test_each_non_target_component_and_organization_must_stay_fixed(self):
        for key in ("PERC", "PRED", "CTRL", "VERIFY", "ACT", "LEARN", "organization"):
            with self.subTest(changed=key):
                record, document, configurations = self.panel()
                changed = self.bind("changed.bin", b"different original")
                if key == "organization":
                    configurations["rag"][key] = changed
                else:
                    configurations["rag"]["components"][key] = changed
                with self.assertRaisesRegex(ValueError, "non-target mechanism"):
                    self.inspect(record, document, configurations)

    def test_every_arm_reads_and_matches_model_tools_budget_and_fixed_inputs(self):
        for arm in ("candidate", "rag", "rag_uniform_replay", "recurrent"):
            for key in controls.COMMON:
                with self.subTest(arm=arm, changed=key):
                    record, document, configurations = self.panel()
                    configurations[arm]["fixed_inputs"][key] = self.bind(
                        "changed-input.bin", b"changed"
                    )
                    with self.assertRaisesRegex(ValueError, "changes a fixed input"):
                        self.inspect(record, document, configurations)

    def test_full_system_accepts_agent_and_workflow_without_cell_facade(self):
        record, document, configurations = self.panel("full_system")
        baseline = "fixed_graph_strong_scheduler"
        configurations[baseline]["role"] = "strong_workflow"
        configurations[baseline]["organization"] = self.bind(
            "workflow.bin", b"different workflow"
        )
        checked = self.inspect(record, document, configurations)["component_controls"]
        self.assertEqual(checked["arm_roles"][baseline], "strong_workflow")
        self.assertIsNone(checked["declared_configurations"][baseline]["components"])
        self.assertFalse(checked["component_isolation_integrity_verified"])
        configurations[baseline]["role"] = "matched_control"
        with self.assertRaisesRegex(ValueError, "identity or role"):
            self.inspect(record, document, configurations)

    def test_organization_cannot_relabel_single_class_controls_as_system_comparison(
        self,
    ):
        record, document, configurations = self.panel("full_system")
        document.update(comparison="single_class", target_component="MEM")
        with self.assertRaisesRegex(ValueError, "requires full-system controls"):
            self.inspect(record, document, configurations)

    def test_missing_arms_components_target_change_or_identity_are_rejected(self):
        for change in (
            "missing-arm",
            "renamed-arm",
            "missing-component",
            "wrong-target",
            "unchanged-target",
            "wrong-identity",
            "wrong-schema",
            "wrong-scope",
        ):
            record, document, configurations = self.panel()
            if change == "missing-arm":
                del configurations["rag"]
            elif change == "renamed-arm":
                configurations["other"] = configurations.pop("rag")
            elif change == "missing-component":
                del configurations["rag"]["components"]["ACT"]
            elif change == "wrong-target":
                document["target_component"] = "ACT"
            elif change == "unchanged-target":
                configurations["rag"]["components"]["MEM"] = configurations[
                    "candidate"
                ]["components"]["MEM"]
            elif change == "wrong-identity":
                configurations["rag"]["arm_id"] = "other"
            elif change == "wrong-scope":
                document.update(comparison="full_system", target_component=None)
            else:
                configurations["rag"]["schema"] = "hepta.cell-arm-configuration.v0"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.inspect(record, document, configurations)

    def test_config_and_component_byte_replacements_fail_after_binding(self):
        record, document, configurations = self.panel()
        self.inspect(record, document, configurations)
        for binding in (
            document["arms"]["rag"],
            configurations["rag"]["components"]["MEM"],
        ):
            path = self.artifacts / binding["path"]
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            with self.assertRaisesRegex(
                ValueError, "artifact bytes or identity changed"
            ):
                self.screen(record)
            path.write_bytes(raw)


if __name__ == "__main__":
    unittest.main()

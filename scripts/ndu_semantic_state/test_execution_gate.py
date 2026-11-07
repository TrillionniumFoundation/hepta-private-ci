"""Adversarial, synthetic-only preflight tests; no real study or model runs."""

from copy import deepcopy
import json
import unittest

from PIL import Image

from ndu_portfolio.example_factorial import example
from ndu_portfolio.factorial import COSTS, RESEARCH
from ndu_semantic_state import test_materials
from ndu_semantic_state.execution_gate import SCHEMA, actor_public_input, inspect_execution


class ExecutionGateTests(unittest.TestCase):
    def setUp(self):
        self.material = test_materials.MaterialAdmissionTests()
        self.material.setUp()
        self.addCleanup(self.material.tearDown)
        self.root = self.material.root
        self.protocol, _, _ = example()
        self.protocol["tasks"] = [task for task in self.protocol["tasks"]
                                  if (task["split"], task["cohort"]) != ("train", "retention")]
        self.material.manifest["cases"], self.material.registry["sources"] = [], []
        family_map = dict(zip(("text_sufficient", "complementary", "asymmetric", "prepare_then_gain",
                               "stop_worthwhile"), test_materials.TASK_FAMILIES))
        for index, task in enumerate(self.protocol["tasks"]):
            split = "retention" if task["cohort"] == "retention" else {
                "train": "train", "validation": "development", "test": "confirmation"}[task["split"]]
            text = self.material.write(f"public-{index}.txt", f"Visible input {index}.".encode())
            image_path = self.root / f"public-{index}.png"
            Image.new("RGB", (2, 1), (index, 11, 9)).save(image_path)
            image = self.material.binding(image_path.name)
            reference = self.material.write(f"private-{index}.txt", b"HIDDEN ANSWER NEVER IN ACTOR INPUT")
            evidence = self.write(f"evidence-{index}.json", {"fixture_only": index})
            family = family_map[task["family"]]
            self.material.manifest["cases"].append({"id": task["task_id"], "source_id": task["source_group"],
                "source_family": task["cluster_id"], "split": split, "task_family": family,
                "text": text, "image": image, "reference": reference, "source_evidence": evidence})
            self.material.registry["sources"].append({"source_id": task["source_group"],
                "source_family": task["cluster_id"], "allowed_split": split,
                "text_sha256s": [text["sha256"]], "image_sha256s": [image["sha256"]],
                "source_evidence_sha256": evidence["sha256"], "used_in_training": split == "train",
                "previously_observed": split != "confirmation", "case_bindings": [{"case_id": task["task_id"],
                    "task_family": family, "text_sha256": text["sha256"], "image_sha256": image["sha256"],
                    "reference_sha256": reference["sha256"]}]})
        self.material.save()
        self.manifest_pin = self.material.binding("manifest.json")["sha256"]
        self.protocol["dataset_digest"] = self.manifest_pin
        executable = self.material.write("provider.py", b"raise RuntimeError('must never execute fixtures')\n")
        objective = self.write("objective.json", {"fixture": "external objective"})
        evaluator = self.material.write("evaluator.py", b"raise RuntimeError('not a real evaluator')\n")
        meter = self.material.write("meter.py", b"raise RuntimeError('not a physical meter')\n")
        self.protocol.update(objective_digest=objective["sha256"], evaluator_digest=evaluator["sha256"],
                             measurement_digest=meter["sha256"])
        providers = {}
        for key, profile in self.protocol["profiles"].items():
            regime, arm = key.split(":")
            core = profile["core"]
            model = self.material.write(f"{regime}-{core}.weights", f"fixture model {regime} {core}".encode())
            policy = self.material.write(f"{regime}-{arm}.policy", f"fixture policy {key}".encode())
            initial = self.material.write(f"{core}-initial.weights", f"initial fixture {core}".encode())
            profile.update(data_digest=self.manifest_pin, objective_digest=objective["sha256"],
                model_digest=model["sha256"], policy_digest=policy["sha256"], initial_content_digest=initial["sha256"])
            providers[key] = {"principal": "actor-fixture", "executable": executable,
                              "model": model, "policy": policy, "initial_content": initial}
        calibration = self.write("cost-conversion.json", {"fixture_only": "not calibrated"})
        self.cost = {"schema": "hepta.physical-cost-contract.v1", "cost_unit": self.protocol["cost_unit"],
            "cost_weight": self.protocol["cost_weight"], "attribution": {name: f"fixture allocation {name}" for name in COSTS},
            "research_categories": list(RESEARCH), "physical_fields": ["wall_seconds", "peak_bytes", "energy_joules", "actual_charges"],
            "unknown_value": None, "attempt_scope": "all_started_attempts", "conversion_evidence": calibration}
        self.plan = {"schema": SCHEMA, "experiment_id": self.material.manifest["experiment_id"],
            "stage": "confirmation", "material_manifest": self.material.binding("manifest.json"),
            "source_registry": self.material.binding("registry.json"), "protocol": None, "providers": providers,
            "objective": objective, "meter": meter,
            "evaluator": {"principal": "evaluator-fixture", "executable": evaluator,
                "rubric": self.write("rubric.json", {"fixture_only": True}),
                "isolation_evidence": self.write("isolation.json", {"fixture_only": True})},
            "cost_contract": self.write("cost.json", self.cost),
            "power_plan": self.write("power.json", {"fixture_only": True}),
            "power_review": self.write("power-review.json", {"fixture_only": True}),
            "native_owner": {"kind": "hepta-cell-journal", "adapter": executable,
                "contract": self.write("owner-contract.json", {"fixture_only": True}),
                "receipt_inventory": self.write("owner-inventory.json", {"fixture_only": True})}}
        self.save()

    def write(self, name, value):
        return self.material.write(name, json.dumps(value, sort_keys=True, allow_nan=False).encode())

    def save(self):
        self.plan["protocol"] = self.write("protocol.json", self.protocol)
        self.plan_pin = self.write("execution.json", self.plan)["sha256"]

    def inspect(self, **overrides):
        arguments = {"expected_plan_sha256": self.plan_pin, "expected_manifest_sha256": self.manifest_pin,
                     "expected_registry_sha256": self.material.pin}
        return inspect_execution(self.root, "execution.json", **(arguments | overrides))

    def public(self, case_id="train/new/0", split="train"):
        return actor_public_input(self.root, "manifest.json", "registry.json",
            expected_manifest_sha256=self.manifest_pin, expected_registry_sha256=self.material.pin,
            case_id=case_id, split=split)

    def test_complete_static_bindings_never_grant_execution_or_learning_authority(self):
        report = self.inspect()
        self.assertEqual(set(report["checks"].values()), {"VERIFIED"})
        self.assertEqual({key: report[key] for key in ("outcome", "native_receipt_verification",
            "evaluator_isolation_verification", "execution_started", "execution_authorized",
            "scientific_admission", "adoption_authorized")}, {
                "outcome": "Inconclusive", "native_receipt_verification": "NOT_IMPLEMENTED",
                "evaluator_isolation_verification": "NOT_IMPLEMENTED", "execution_started": False,
                "execution_authorized": False, "scientific_admission": False, "adoption_authorized": False})
        self.assertEqual(len([key for key in report["checks"] if key.endswith(":model")]), 16)

    def test_real_flag_and_matching_owner_hashes_cannot_promote_a_fixture(self):
        self.protocol["evidence_kind"] = "real"
        self.save()
        report = self.inspect()
        self.assertEqual(report["outcome"], "Inconclusive")
        self.assertIn("native_authentication_not_implemented", [item["code"] for item in report["blockers"]])
        self.plan["native_owner"]["verified"] = True
        self.save()
        self.assertEqual(self.inspect()["outcome"], "Failed")

    def test_missing_providers_are_all_listed_and_no_rows_are_inferred(self):
        self.plan["providers"] = {}
        self.save()
        report = self.inspect()
        self.assertEqual(report["outcome"], "Inconclusive")
        self.assertEqual({item["scope"] for item in report["blockers"] if item["code"] == "missing_provider"},
                         set(self.protocol["profiles"]))

    def test_extra_provider_and_extra_real_fields_are_rejected(self):
        for change in (lambda: self.plan.update(real=True),
                       lambda: self.plan["providers"].update({"frozen:oracle": self.plan["providers"]["frozen:A"]})):
            original = deepcopy(self.plan)
            change()
            self.save()
            self.assertEqual(self.inspect()["outcome"], "Failed")
            self.plan = original

    def test_wrong_model_identity_and_modified_provider_bytes_fail(self):
        self.protocol["profiles"]["joint:D"]["model_digest"] = "a" * 64
        self.save()
        self.assertEqual(self.inspect()["checks"]["provider:joint:D:model"], "FAILED")
        (self.root / "provider.py").write_text("changed executor")
        self.assertEqual(self.inspect()["checks"]["provider:frozen:A:executable"], "FAILED")

    def test_actor_cannot_be_its_declared_independent_evaluator(self):
        self.plan["evaluator"]["principal"] = "actor-fixture"
        self.save()
        self.assertEqual(self.inspect()["checks"]["evaluator_identity"], "FAILED")

    def test_external_pins_cannot_be_replaced_by_pins_inside_plan(self):
        self.material.manifest["experiment_id"] = "relabelled"
        self.material.save()
        self.plan["material_manifest"] = self.material.binding("manifest.json")
        self.save()
        self.assertEqual(self.inspect()["checks"]["material_manifest"], "FAILED")

    def test_missing_external_pin_is_unknown_not_an_unpinned_fallback(self):
        report = self.inspect(expected_manifest_sha256=None)
        self.assertEqual(report["outcome"], "Inconclusive")
        self.assertEqual(report["checks"], {"manifest_pin": "MISSING"})

    def test_missing_file_is_inconclusive_and_tampered_file_is_failed(self):
        path = self.root / "public-0.txt"
        path.unlink()
        self.assertEqual(self.inspect()["outcome"], "Inconclusive")
        path.write_text("different public input")
        self.assertEqual(self.inspect()["outcome"], "Failed")

    def test_source_and_family_mapping_cannot_be_changed_in_factorial_only(self):
        for field, value in (("source_group", "invented-group"), ("family", "complementary")):
            original = self.protocol["tasks"][0][field]
            self.protocol["tasks"][0][field] = value
            self.save()
            self.assertEqual(self.inspect()["checks"]["task_mapping"], "FAILED")
            self.protocol["tasks"][0][field] = original

    def test_missing_cost_power_and_owner_evidence_remains_unknown(self):
        for field in ("cost_contract", "power_plan", "power_review", "native_owner"):
            self.plan[field] = None
        self.save()
        report = self.inspect()
        self.assertEqual(report["outcome"], "Inconclusive")
        self.assertEqual(report["checks"]["power_plan"], "MISSING")
        self.assertIn("missing_native_owner", [item["code"] for item in report["blockers"]])

    def test_zero_replacement_of_unknown_costs_and_discarded_failures_fail(self):
        for field, value in (("unknown_value", 0), ("attempt_scope", "success_only"), ("cost_weight", 0)):
            original = self.cost[field]
            self.cost[field] = value
            self.plan["cost_contract"] = self.write("cost.json", self.cost)
            self.save()
            self.assertEqual(self.inspect()["checks"]["cost_contract_structure"], "FAILED")
            self.cost[field] = original

    def test_nonobject_and_duplicate_key_artifacts_report_failure(self):
        self.plan["protocol"] = self.write("not-object.json", None)
        self.plan_pin = self.write("execution.json", self.plan)["sha256"]
        self.assertEqual(self.inspect()["outcome"], "Failed")
        duplicate = b'{"schema":"one","schema":"two"}'
        self.plan_pin = self.material.write("execution.json", duplicate)["sha256"]
        self.assertEqual(self.inspect()["outcome"], "Failed")

    def test_actor_receives_only_current_text_and_immutable_pixels(self):
        public = self.public()
        self.assertEqual(set(public), {"text", "image_rgb"})
        self.assertEqual(public["text"], "Visible input 0.")
        self.assertEqual(public["image_rgb"].tolist(), [[[0, 11, 9], [0, 11, 9]]])
        with self.assertRaises(ValueError):
            public["image_rgb"].setflags(write=True)

    def test_actor_cannot_relabel_confirmation_as_training(self):
        with self.assertRaisesRegex(ValueError, "original split"):
            self.public("test/new/0", "train")

    def test_actor_projection_rejects_reference_rebinding_and_future_fields(self):
        case = self.material.manifest["cases"][0]
        original = deepcopy(case)
        for field, value in (("reference", case["text"]), ("future_score", 1.0)):
            case[field] = value
            self.material.save()
            self.manifest_pin = self.material.binding("manifest.json")["sha256"]
            with self.assertRaises(ValueError):
                self.public()
            case.clear()
            case.update(original)


if __name__ == "__main__":
    unittest.main()

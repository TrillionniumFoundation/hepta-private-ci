"""Synthetic validator tests, never measured structure evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import validate as gate


HERE = Path(__file__).resolve().parent


def small_plan():
    plan = json.loads((HERE / "PLAN.json").read_text())
    plan.update(seeds=[9101], families=["inventory_policy"], axes=["wording_ood"], minimum_cases_per_family_axis=1,
                minimum_unknown_cases_per_family=1, minimum_distinct_wording_groups=1,
                minimum_retained_capabilities=1, retention_cycles=[0, 1])
    return plan


def split_fixture():
    return {
        "training": {"case_ids": ["train"], "expression_groups": ["train-expression"], "entity_ids": ["entity"], "task_ids": ["task"]},
        "calibration": {"case_ids": ["cal"], "expression_groups": ["cal-expression"], "entity_ids": [], "task_ids": []},
        "cases": [
            {"id": "held", "known": True, "family": "inventory_policy", "axis": "wording_ood", "expression_group": "held-expression", "entity_id": "entity", "task_id": "task", "expected": {"value": 7, "trace": [2, 7]}},
            {"id": "unknown", "known": False, "family": "inventory_policy", "axis": "unknown"},
        ],
    }


def observations(plan, cases):
    return {"observations": [{"seed": seed, "arm": arm, "case_id": row["id"], "accepted": row["known"], "output": row.get("expected")}
        for seed in plan["seeds"] for arm in plan["arms"] for row in cases.values()]}


def costs_fixture(plan):
    return {"runs": [{"seed": seed, "arm": arm, "orchestrator_started_ns": 1, "orchestrator_finished_ns": 101,
        "phases": {phase: {"attempt_ids": ["fit-completed", "fit-failed"], "metrics": {
            metric: {"lower": 1, "upper": 1, "unobserved_ns": 0} for metric in plan["cost_weights"]}}
            for phase in plan["cost_phases"]}} for seed in plan["seeds"] for arm in plan["arms"]]}


def retention_fixture(plan):
    registration = {"retained_capability_ids": ["ability"], "retained_expected_sha256": {"ability": gate.canonical_digest(7)}}
    retention = {"observations": [{"seed": seed, "arm": arm, "cycle": cycle, "capability_id": "ability", "accepted": True, "expected": 7, "output": 7}
        for seed in plan["seeds"] for arm in plan["arms"] for cycle in plan["retention_cycles"]]}
    deletion = {"runs": [{"seed": seed, "arm": arm, "revoked_output_exposed": False, "deleted_source_id": "old", "active_training_source_ids": ["retained"], "retained_outputs": {"ability": 7}, "independent_clean_rebuild_outputs": {"ability": 7}}
        for seed in plan["seeds"] for arm in plan["arms"]]}
    return registration, retention, deletion


def training_fixture(plan):
    identities = {"initial": "a" * 64, "final": "b" * 64, "gradients": "c" * 64, "contract": "d" * 64}
    contract = {field: "d" * 64 if field.endswith("_sha256") else 100 for field in plan["matching_fields"]}
    registration = {"artifact_sha256": "e" * 64, "source_manifest_sha256": "d" * 64, "registered_at_unix_ns": 1, "held_opened_unix_ns": 30, "contracts": {}}
    runs = []
    for seed in plan["seeds"]:
        for arm in plan["arms"]:
            registration["contracts"][f"{seed}|{arm}"] = copy.deepcopy(contract)
            runs.append({"seed": seed, "arm": arm, "registration_sha256": "e" * 64, "source_manifest_sha256": "d" * 64,
                "contract": copy.deepcopy(contract), "training_compute_units": 10,
                "attempts": [{"id": "fit", "started_unix_ns": 10, "finished_unix_ns": 20, "status": "completed", "optimization_steps": 1}],
                "gradient_trace_sha256": "c" * 64, "initial_parameters_sha256": "a" * 64, "final_parameters_sha256": "b" * 64})
    return {"runs": runs}, registration, identities


class GateTests(unittest.TestCase):
    def codes(self, findings):
        return {item["code"] for item in findings.items}

    def test_no_new_measurements_is_held_despite_asserted_pass(self):
        manifest = {"schema": "hepta.cell-structure.result-pack.v1", "evidence_kind": "no_new_measurements", "plan_sha256": "a" * 64, "prior_evidence_sha256": "b" * 64, "artifacts": [], "passed": True}
        result = gate.validate(small_plan(), "a" * 64, "b" * 64, manifest, HERE)
        self.assertEqual((result["status"], result["registered_structure_gate_passed"], result["production_authority"]), ("held", False, False))

    def test_native_pss_or_ndu_cannot_substitute_for_structure(self):
        for kind in ("native_agent_pss", "ndu_single_task", "loopback_only_migration"):
            with self.subTest(kind=kind):
                manifest = {"schema": "hepta.cell-structure.result-pack.v1", "evidence_kind": kind, "plan_sha256": "a" * 64, "prior_evidence_sha256": "b" * 64, "artifacts": []}
                result = gate.validate(small_plan(), "a" * 64, "b" * 64, manifest, HERE)
                self.assertEqual(result["status"], "invalid")

    def test_prior_negative_and_unknown_results_remain_visible(self):
        prior = json.loads((HERE / "PRIOR_EVIDENCE.json").read_text())
        self.assertTrue(prior["formal"]["audit_integrity_passed"])
        self.assertEqual([(r["split_admitted"], r["merge_admitted"]) for r in prior["formal"]["structure"]], [(False, False)] * 3)
        self.assertFalse(prior["longrun"]["cost_boundary"]["full_cost_exact"])
        self.assertIsNone(prior["longrun"]["cost_boundary"]["interrupted_attempt_cpu_seconds"])

    def test_changed_frozen_prior_is_invalid(self):
        manifest = {"schema": "hepta.cell-structure.result-pack.v1", "evidence_kind": "no_new_measurements", "plan_sha256": "a" * 64, "prior_evidence_sha256": "c" * 64, "artifacts": []}
        self.assertEqual(gate.validate(small_plan(), "a" * 64, "b" * 64, manifest, HERE)["status"], "invalid")

    def test_held_wording_leak_is_rejected(self):
        data = split_fixture()
        data["training"]["expression_groups"].append("held-expression")
        findings = gate.Findings()
        gate.check_splits(small_plan(), data, findings)
        self.assertIn("ood_identity_leaked", self.codes(findings))

    def test_reject_all_does_not_count_as_unknown_safety_success(self):
        plan, findings = small_plan(), gate.Findings()
        cases = gate.check_splits(plan, split_fixture(), findings)
        data = observations(plan, cases)
        for row in data["observations"]:
            if row["arm"] == "dynamic_cells":
                row["accepted"] = False
        scores = gate.measure_scores(plan, cases, data, findings)
        self.assertEqual(scores[(9101, "dynamic_cells", "inventory_policy", "wording_ood")]["accuracy"], 0)
        self.assertIn("known_coverage_failed", self.codes(findings))

    def test_duplicate_rows_do_not_inflate_evidence(self):
        plan, findings = small_plan(), gate.Findings()
        cases = gate.check_splits(plan, split_fixture(), findings)
        data = observations(plan, cases)
        data["observations"].append(copy.deepcopy(data["observations"][0]))
        gate.measure_scores(plan, cases, data, findings)
        self.assertIn("duplicate_observation", self.codes(findings))

    def test_unknown_interrupted_cost_stays_unbounded(self):
        plan, findings = small_plan(), gate.Findings()
        data = costs_fixture(plan)
        data["runs"][0]["phases"]["training"]["metrics"]["cpu_ns"]["upper"] = None
        costs = gate.measure_costs(plan, data, {}, findings)
        self.assertFalse(costs[(9101, "dynamic_cells")]["bounded"])
        self.assertIn("unbounded_or_unknown_lifecycle_cost", self.codes(findings))

    def test_failed_candidate_cost_cannot_be_omitted(self):
        plan, findings = small_plan(), gate.Findings()
        data = costs_fixture(plan)
        for run in data["runs"]:
            for phase in run["phases"].values():
                phase["attempt_ids"] = ["fit-completed"]
        gate.measure_costs(plan, data, {(9101, "dynamic_cells"): {"fit-completed", "fit-failed"}}, findings)
        self.assertIn("failed_or_selected_candidate_cost_omitted", self.codes(findings))

    def test_equal_parameters_do_not_excuse_unequal_feature_exposure(self):
        plan, findings = small_plan(), gate.Findings()
        training, registration, identities = training_fixture(plan)
        run = next(run for run in training["runs"] if run["arm"] == "fixed_experts")
        run["contract"]["feature_presentations"] = 200
        registration["contracts"]["9101|fixed_experts"]["feature_presentations"] = 200
        gate.check_training(plan, training, registration, identities, findings)
        self.assertIn("unmatched_information_or_budget", self.codes(findings))

    def test_evaluator_cannot_open_held_before_last_training_exit(self):
        plan, findings = small_plan(), gate.Findings()
        training, registration, identities = training_fixture(plan)
        registration["held_opened_unix_ns"] = 15
        gate.check_training(plan, training, registration, identities, findings)
        self.assertIn("held_opened_before_training_exit", self.codes(findings))

    def test_training_compute_requires_finite_nonnegative_number(self):
        for value in (-1, float("nan"), float("inf"), True, "10", None):
            with self.subTest(value=value):
                plan, findings = small_plan(), gate.Findings()
                training, registration, identities = training_fixture(plan)
                training["runs"][0]["training_compute_units"] = value
                gate.check_training(plan, training, registration, identities, findings)
                self.assertEqual(self.codes(findings), {"invalid_training_compute"})
                self.assertEqual(findings.result()["status"], "invalid")

    def test_missing_cost_coverage_is_not_assumed_zero(self):
        plan, findings = small_plan(), gate.Findings()
        data = costs_fixture(plan)
        del data["runs"][0]["phases"]["migration"]["metrics"]["network_bytes"]["unobserved_ns"]
        gate.measure_costs(plan, data, {}, findings)
        self.assertIn("cost_coverage_unknown", self.codes(findings))

    def test_equal_quality_higher_full_cost_has_no_net_gain(self):
        plan, findings = small_plan(), gate.Findings()
        cases = gate.check_splits(plan, split_fixture(), findings)
        scores = gate.measure_scores(plan, cases, observations(plan, cases), findings)
        costs = {(9101, arm): {"lower": 10, "upper": 10, "bounded": True} for arm in plan["arms"]}
        costs[(9101, "dynamic_cells")]["upper"] = 12
        gate.check_benefits(plan, scores, costs, findings)
        self.assertIn("same_budget_net_benefit_not_established", self.codes(findings))

    def test_changed_retention_gold_is_not_learning(self):
        plan, findings = small_plan(), gate.Findings()
        registration, retention, deletion = retention_fixture(plan)
        retention["observations"][1].update(expected=999, output=999)
        gate.check_retention_and_deletion(plan, registration, retention, deletion, findings)
        self.assertIn("retained_target_changed_after_registration", self.codes(findings))

    def test_retention_acceptance_requires_boolean_and_never_coerces(self):
        for value in ("false", 1, 0, None, []):
            with self.subTest(value=value):
                plan, findings = small_plan(), gate.Findings()
                registration, retention, deletion = retention_fixture(plan)
                retention["observations"][0]["accepted"] = value
                gate.check_retention_and_deletion(plan, registration, retention, deletion, findings)
                self.assertIn("invalid_retention_acceptance_value", self.codes(findings))
                self.assertIn("initial_retained_capability_missing", self.codes(findings))
                self.assertEqual(findings.result()["status"], "invalid")

    def test_deletion_cannot_keep_source_in_active_lineage(self):
        plan, findings = small_plan(), gate.Findings()
        registration, retention, deletion = retention_fixture(plan)
        deletion["runs"][0]["active_training_source_ids"].append("old")
        gate.check_retention_and_deletion(plan, registration, retention, deletion, findings)
        self.assertIn("revocation_or_deleted_lineage_failed", self.codes(findings))

    def test_clean_rebuild_agreement_cannot_hide_post_deletion_capability_loss(self):
        plan, findings = small_plan(), gate.Findings()
        registration, retention, deletion = retention_fixture(plan)
        for run in deletion["runs"]:
            run["retained_outputs"] = {"ability": 999}
            run["independent_clean_rebuild_outputs"] = {"ability": 999}
        gate.check_retention_and_deletion(plan, registration, retention, deletion, findings)
        self.assertEqual(self.codes(findings), {"post_deletion_retained_capability_failed"})
        self.assertEqual(findings.result()["status"], "failed")

    def test_loopback_with_two_node_labels_is_not_physical_migration(self):
        plan, findings = small_plan(), gate.Findings()
        hosts = {"hosts": [{"id": name, "kind": "physical_machine", "machine_fingerprint_sha256": "a" * 64, "observed_transport_address": "127.0.0.1", "inventory_evidence_sha256": "b" * 64} for name in ("node-a", "node-b")]}
        gate.check_structure_and_migration(plan, {"events": []}, hosts, {"observations": []}, {}, {"inventory": "b" * 64}, findings)
        self.assertIn("distinct_physical_hosts_missing", self.codes(findings))
        self.assertIn("physical_host_evidence_missing", self.codes(findings))

    def test_structure_acceptance_requires_boolean_and_never_coerces(self):
        for value in (True, False, "false", 1, 0, None, []):
            with self.subTest(value=value):
                plan, findings = small_plan(), gate.Findings()
                parameters = [{"parameter_artifact_sha256": digest} for digest in ("a" * 64, "b" * 64)]
                events = [{"seed": 9101, "arm": arm, "accepted": value,
                    "decision_partition": "train", "kind": "split",
                    "before_graph": {"nodes": parameters[:1]}, "after_graph": {"nodes": parameters},
                    "fresh_reader_artifact_sha256s": ["a" * 64, "b" * 64]}
                    for arm in (plan["primary_candidate"], plan["network_candidate"])]
                gate.check_structure_and_migration(plan, {"events": events}, {"hosts": []}, {"observations": []}, {}, {"first": "a" * 64, "second": "b" * 64}, findings)
                self.assertEqual("invalid_structure_acceptance_value" in self.codes(findings), type(value) is not bool)
                self.assertEqual("executed_structure_change_missing" in self.codes(findings), value is not True)
                if type(value) is not bool:
                    self.assertEqual(findings.result()["status"], "invalid")

    def test_mutated_artifact_and_parent_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "receipt.json"
            path.write_text('{"measured":false}')
            original = path.read_bytes()
            descriptor = {"id": "r", "kind": "registration", "path": "receipt.json", "bytes": len(original), "sha256": gate.sha256(original)}
            path.write_text('{"measured":true}')
            findings = gate.Findings()
            gate.load_artifacts({"artifacts": [descriptor], "required_artifact_kinds": ["registration"]}, root, findings)
            self.assertIn("artifact_identity_mismatch", self.codes(findings))
            descriptor["path"] = "../receipt.json"
            gate.load_artifacts({"artifacts": [descriptor]}, root, findings)
            self.assertIn("unsafe_artifact_path", self.codes(findings))

    def test_synthetic_fixture_cannot_publish_a_structure_claim(self):
        manifest = {"schema": "hepta.cell-structure.result-pack.v1", "evidence_kind": "synthetic_fixture", "plan_sha256": "a" * 64, "prior_evidence_sha256": "b" * 64, "artifacts": []}
        result = gate.validate(small_plan(), "a" * 64, "b" * 64, manifest, HERE)
        self.assertEqual((result["status"], result["registered_structure_gate_passed"], result["general_intelligence_claim_supported"]), ("held", False, False))


if __name__ == "__main__":
    unittest.main()

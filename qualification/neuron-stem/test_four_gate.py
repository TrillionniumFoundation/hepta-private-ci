"""Adversarial model-free checks; all generated evidence is explicitly synthetic."""
from datetime import datetime, timezone
import hashlib
from itertools import product
import math
from pathlib import Path
import tempfile
import unittest

from four_gate_common import (
    digest, grouped_interval, lifecycle, read_pinned, strict_loads, write_once,
)
from four_gate_compute import (
    ACTIVE_BPS, ARMS, REPEAT_BPS, SCALES, encoding_key, measure_arm, review_compute, workload_key,
)
from four_gate_outcomes import causal_depth, review_ndu, review_reasoning
from four_gate_review import review_all, validate_plan
from test_four_gate_fixtures import (
    lifecycle_fixture, nodes_fixture, outcomes_fixture, plan_fixture, schedule_fixture,
)


def synthetic_arm(arm, schedule, plan):
    pipeline = digest(["FIXTURE pipeline", arm])
    keys = [encoding_key(row, arm, pipeline) for row in schedule]
    forward_keys = list(dict.fromkeys(keys)) if arm == "feature_reuse" else keys
    sample = {"source_sha": plan["source_sha"], "pipeline_sha256": pipeline,
              "weights_sha256": digest("FIXTURE weights"), "host_sha256": digest("FIXTURE host"),
              "environment_sha256": digest("FIXTURE environment"), "peak_rss_bytes": 1000,
              "resident_stem_copies": 1, "lifecycle": lifecycle_fixture(arm, 100, 100),
              "encoder_forwards": [{"id": "forward-0", "keys": forward_keys,
                                    "token_count": len(forward_keys), "start_ns": 1, "end_ns": 2}],
              "requests": []}
    index = {key: i for i, key in enumerate(forward_keys)}
    for i, row in enumerate(schedule):
        sample["requests"].append({"request_id": row["request_id"], "cell_id": row["cell_id"],
                                   "encoder_event_id": "forward-0",
                                   "encoder_slot": index[keys[i]] if arm == "feature_reuse" else i,
                                   "start_ns": 0, "end_ns": 10, "outcome": "succeeded"})
    return sample


class FourGateCommonTests(unittest.TestCase):
    def test_reject_ambiguous_and_nonfinite_json(self):
        for text in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":1e9999}', '{"x":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_loads(text)

    def test_byte_pin_and_write_once(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "row.json"
            write_once(target, {"value": 1})
            raw = target.read_bytes()
            ref = {"path": target.name, "sha256": hashlib.sha256(raw).hexdigest()}
            self.assertEqual(read_pinned(directory, ref), {"value": 1})
            with self.assertRaises(FileExistsError):
                write_once(target, {"value": 2})
            self.assertEqual(target.read_bytes(), raw)
            with self.assertRaises(ValueError):
                read_pinned(directory, {**ref, "sha256": "e" * 64})

    def test_path_escape_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "item"
            file.write_text('{}')
            (Path(directory) / "alias").symlink_to(file)
            for name in ("../item", "alias", str(file)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    read_pinned(directory, {"path": name, "sha256": hashlib.sha256(b'{}').hexdigest()})

    def test_invalid_output_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.json"
            with self.assertRaises(ValueError):
                write_once(path, {"score": math.nan})
            self.assertFalse(path.exists())

    def test_cluster_replication_does_not_increase_sample_size(self):
        args = dict(alpha=.05, replicates=1000, seed=1, min_groups=3)
        small = grouped_interval([("a", .2), ("b", -.1)], **args)
        large = grouped_interval([("a", .2)] * 4096 + [("b", -.1)] * 4096, **args)
        self.assertEqual(small["groups"], large["groups"])
        self.assertAlmostEqual(small["lcb"], large["lcb"])
        self.assertFalse(large["enough_groups"])

    def test_lifecycle_rejects_double_charged_job(self):
        sample = lifecycle_fixture("test")
        sample["training"]["job_id"] = sample["inference"]["job_id"]
        with self.assertRaisesRegex(ValueError, "multiple lifecycle"):
            lifecycle(sample, ["cpu_ns", "wall_ns"])

    def test_missing_required_energy_is_not_zero(self):
        with self.assertRaisesRegex(ValueError, "energy"):
            lifecycle(lifecycle_fixture("test"), ["energy_uj"])

    def test_missing_gates_are_blocked_and_never_promote(self):
        plan = plan_fixture()
        bundle = {"schema": "hepta.four-gate.evidence-bundle.v1", "plan_sha256": digest(plan),
                  "evidence": {gate: None for gate in ("compute", "learning", "reasoning", "ndu")}}
        report = review_all(plan, bundle, ".")
        self.assertEqual({g["status"] for g in report["gates"].values()}, {"blocked_missing_evidence"})
        self.assertFalse(report["all_offline_diagnostics_passed"])
        self.assertFalse(report["production_promotion_permitted"])
        self.assertFalse(report["real_world_learning_or_reasoning_established"])

    def test_real_observations_require_200_groups(self):
        plan = plan_fixture()
        plan["evidence_kind"] = "observed"
        with self.assertRaises(ValueError):
            validate_plan(plan, datetime.now(timezone.utc))

    def test_no_fabricated_future_calendar_window(self):
        plan = plan_fixture()
        with self.assertRaisesRegex(ValueError, "do not yet exist"):
            validate_plan(plan, datetime(2026, 9, 3, tzinfo=timezone.utc))

    def test_overlapping_windows_rejected(self):
        plan = plan_fixture()
        plan["windows"]["future_2"] = plan["windows"]["future_1"]
        with self.assertRaisesRegex(ValueError, "overlapping"):
            validate_plan(plan, datetime.now(timezone.utc))


class FourGateComputeTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan_fixture()
        self.schedule = schedule_fixture(repeats=True)

    def test_weights_shared_but_rows_not_reused(self):
        joint = measure_arm("joint_batch", self.schedule,
                            synthetic_arm("joint_batch", self.schedule, self.plan), self.plan)
        shared = measure_arm("feature_reuse", self.schedule,
                             synthetic_arm("feature_reuse", self.schedule, self.plan), self.plan)
        self.assertEqual((joint["encoder_calls"], shared["encoder_calls"]), (1, 1))
        self.assertEqual((joint["encoder_rows"], shared["encoder_rows"]), (4, 1))
        self.assertEqual(shared["reused_requests"], 3)

    def test_cross_scope_reuse_rejected(self):
        sample = synthetic_arm("feature_reuse", self.schedule, self.plan)
        self.schedule[-1]["scope"] = "other"
        with self.assertRaisesRegex(ValueError, "scope/generation/input"):
            measure_arm("feature_reuse", self.schedule, sample, self.plan)

    def test_joint_arm_cannot_alias_encoder_slot(self):
        sample = synthetic_arm("joint_batch", self.schedule, self.plan)
        sample["requests"][-1]["encoder_slot"] = 0
        with self.assertRaises(ValueError):
            measure_arm("joint_batch", self.schedule, sample, self.plan)

    def test_missing_failed_request_is_not_filtered(self):
        sample = synthetic_arm("feature_reuse", self.schedule, self.plan)
        sample["requests"].pop()
        with self.assertRaisesRegex(ValueError, "disappear"):
            measure_arm("feature_reuse", self.schedule, sample, self.plan)

    def test_failed_request_in_latency_and_success_denominator(self):
        sample = synthetic_arm("feature_reuse", self.schedule, self.plan)
        sample["requests"][-1].update(outcome="failed", end_ns=100)
        report = measure_arm("feature_reuse", self.schedule, sample, self.plan)
        self.assertEqual(report["successful_requests"], 3)
        self.assertGreater(report["p99_end_to_end_ns_all_outcomes"], 90)

    def test_incomplete_scale_matrix_rejected(self):
        with self.assertRaisesRegex(ValueError, "36-workload"):
            review_compute(self.plan, {"schema": "hepta.four-gate.compute-traces.v1", "workloads": []})

    def test_full_36_workload_matrix_and_repeat_ratio(self):
        evidence = {"schema": "hepta.four-gate.compute-traces.v1", "workloads": []}
        for cells, active, repeat in product(SCALES, ACTIVE_BPS, REPEAT_BPS):
            active_cells = math.ceil(cells * active / 10000)
            size = max(10, active_cells)
            schedule = schedule_fixture(size)
            unique = max(1, round(size * (1 - repeat / 10000)))
            for i, row in enumerate(schedule):
                row["cell_id"] = i % active_cells
                row["state_sha256"] = digest(["fixture state", i % unique])
            key = workload_key(cells, active, repeat)
            self.plan["compute"]["schedule_sha256s"][key] = digest(schedule)
            evidence["workloads"].append({"cells": cells, "active_bps": active, "repeat_bps": repeat,
                                         "schedule": schedule,
                                         "arms": {arm: synthetic_arm(arm, schedule, self.plan) for arm in ARMS}})
        report = review_compute(self.plan, evidence)
        self.assertEqual(report["status"], "diagnostic_pass")
        self.assertEqual(len(report["metrics"]), 36)
        evidence["workloads"][0]["schedule"][-1]["state_sha256"] = evidence["workloads"][0]["schedule"][0]["state_sha256"]
        self.plan["compute"]["schedule_sha256s"]["64:500:0"] = digest(evidence["workloads"][0]["schedule"])
        with self.assertRaisesRegex(ValueError, "repeat ratio"):
            review_compute(self.plan, evidence)


class FourGateOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan_fixture()

    def test_parallel_cells_do_not_add_sequential_depth(self):
        root = digest("root")
        left = nodes_fixture(root, 1, "left")
        right = nodes_fixture(root, 1, "right")
        self.assertEqual(causal_depth(left + right, root)["learned_depth"], 1)

    def test_retry_does_not_add_learned_depth(self):
        root = digest("root")
        nodes = nodes_fixture(root)
        nodes.append({"id": "retry", "kind": "transport_retry", "parents": [nodes[-1]["id"]],
                      "start_ns": 20, "end_ns": 30, "input_refs": [nodes[-1]["output_sha256"]],
                      "output_sha256": nodes[-1]["output_sha256"]})
        self.assertEqual(causal_depth(nodes, root)["learned_depth"], 2)

    def test_future_label_or_missing_causal_edge_rejected(self):
        root = digest("root")
        for mutate in (lambda n: n[-1].update(input_refs=[digest("terminal label")]),
                       lambda n: n[-1].update(parents=[]),
                       lambda n: n[-1].update(start_ns=0)):
            nodes = nodes_fixture(root)
            mutate(nodes)
            with self.assertRaises(ValueError):
                causal_depth(nodes, root)

    def test_reasoning_diagnostic_never_authorizes(self):
        report = review_reasoning(self.plan, outcomes_fixture(self.plan))
        self.assertEqual(report["status"], "diagnostic_pass")
        self.assertFalse(report["production_promotion_permitted"])
        self.assertEqual(len(report["metrics"]["paired_comparisons"]), 20)

    def test_more_compute_cannot_masquerade_as_reasoning_gain(self):
        evidence = outcomes_fixture(self.plan)
        for row in evidence["episodes"]:
            if row["arm"] == "fixed_depth":
                row["cost"]["cpu_ns"] = 20
        evidence["arms"]["fixed_depth"]["lifecycle"]["inference"]["cost"]["cpu_ns"] *= 2
        report = review_reasoning(self.plan, evidence)
        self.assertEqual(report["status"], "not_passed")

    def test_training_structure_leakage(self):
        evidence = outcomes_fixture(self.plan)
        evidence["cases"][0]["structure_sha256"] = evidence["training_structure_sha256s"][0]
        with self.assertRaisesRegex(ValueError, "structure reused"):
            review_reasoning(self.plan, evidence)

    def test_missing_task_stratum(self):
        evidence = outcomes_fixture(self.plan)
        evidence["cases"] = [c for c in evidence["cases"] if c["stratum"] != "counterfactual"]
        with self.assertRaisesRegex(ValueError, "coverage"):
            review_reasoning(self.plan, evidence)

    def test_ood_gain_cannot_be_pooled_away(self):
        evidence = outcomes_fixture(self.plan)
        for row in evidence["episodes"]:
            if "counterfactual" in row["case_id"] and row["arm"] == "fixed_depth":
                row["external_outcome"]["score"] = 0
        self.assertEqual(review_reasoning(self.plan, evidence)["status"], "not_passed")

    def test_model_cannot_observe_its_own_success(self):
        evidence = outcomes_fixture(self.plan)
        evidence["episodes"][0]["external_outcome"]["observer_id"] = "FIXTURE model runner"
        with self.assertRaisesRegex(ValueError, "self-labelled"):
            review_reasoning(self.plan, evidence)

    def test_unobserved_censoring_not_zero_reward(self):
        evidence = outcomes_fixture(self.plan)
        evidence["episodes"][0]["status"] = "censored"
        with self.assertRaisesRegex(ValueError, "censoring estimator"):
            review_reasoning(self.plan, evidence)

    def test_new_stem_not_attributed_to_system2(self):
        evidence = outcomes_fixture(self.plan)
        evidence["arms"]["fixed_depth"]["stem_sha256"] = digest("stronger model")
        with self.assertRaisesRegex(ValueError, "changed Stem"):
            review_reasoning(self.plan, evidence)

    def test_ndu_external_benefit_and_stochastic_increment(self):
        report = review_ndu(self.plan, outcomes_fixture(self.plan, "ndu"))
        self.assertEqual(report["status"], "diagnostic_pass")
        self.assertEqual(len(report["metrics"]["paired_comparisons"]), 10)
        self.assertFalse(report["metrics"]["general_fbsde_conformance_established"])

    def test_training_search_cost_reverses_apparent_ndu_win(self):
        evidence = outcomes_fixture(self.plan, "ndu")
        evidence["arms"]["ndu_stochastic"]["lifecycle"]["training"]["cost"]["cpu_ns"] = 100_000
        report = review_ndu(self.plan, evidence)
        self.assertEqual(report["status"], "not_passed")

    def test_internal_utility_alone_cannot_win(self):
        evidence = outcomes_fixture(self.plan, "ndu")
        for row in evidence["episodes"]:
            row["external_outcome"]["score"] = .5
            row["internal_utility"] = 1_000_000 if "ndu" in row["arm"] else 0
        self.assertEqual(review_ndu(self.plan, evidence)["status"], "not_passed")

    def test_nonlinear_recursive_profile_not_silently_discounted(self):
        evidence = outcomes_fixture(self.plan, "ndu")
        evidence["utility_profile"] = "arbitrary-fbsde"
        with self.assertRaisesRegex(ValueError, "general recursive"):
            review_ndu(self.plan, evidence)

    def test_mutable_objective_rejected(self):
        evidence = outcomes_fixture(self.plan, "ndu")
        evidence["arms"]["ndu_stochastic"]["objective_sha256"] = digest("easier objective")
        with self.assertRaisesRegex(ValueError, "objective drift"):
            review_ndu(self.plan, evidence)

    def test_missing_physical_compute_charge_rejected(self):
        evidence = outcomes_fixture(self.plan, "ndu")
        evidence["episodes"][0]["cost"]["cpu_ns"] = 0
        with self.assertRaisesRegex(ValueError, "physical inference"):
            review_ndu(self.plan, evidence)


if __name__ == "__main__":
    unittest.main()

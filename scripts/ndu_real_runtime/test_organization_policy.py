"""Adversarial ORG-1 reference checks; fixtures confer no runtime authority."""

import copy
import hashlib
import json
import os
import unittest

from . import test_causal_topology
from .causal_topology import ARMS, validate_topology_receipt
from .metering import canonical_sha
from .organization_policy import review_organization


class OrganizationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_causal_topology.TopologyEvidenceTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.root = self.helper.root
        self.sequence = 0
        self.build()

    def artifact(self, value, *, raw=None):
        self.sequence += 1
        path = self.root / f"org-{self.sequence}.json"
        data = json.dumps(value, sort_keys=True).encode() if raw is None else raw
        path.write_bytes(data)
        return {
            "path": path.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def amend(self, reference, update):
        value = json.loads((self.root / reference["path"]).read_bytes())
        update(value)
        reference.update(self.artifact(value))

    def topology(self, kind):
        helper = self.helper
        dynamic = helper.fixture(kind, "dynamic-" + kind)
        fixed = copy.deepcopy(dynamic)
        fixed.update(run_id="fixed-" + kind, arm_id=ARMS[0], artifacts={})
        fixed["transition"] = {"kind": "no_change", "consumed": [], "produced": []}
        graph = helper.read(dynamic, "before_graph")
        state = helper.read(dynamic, "before_state")
        for key, value in (
            ("before_graph", graph),
            ("after_graph", graph),
            ("before_state", state),
            ("after_state", state),
        ):
            helper.write(fixed, key, value)
        values = {name: canonical_sha(value) for name, value in state["states"].items()}
        helper.write(
            fixed,
            "migration",
            {
                "mode": "preserve",
                "policy_sha256": "d" * 64,
                "before_state_sha256": fixed["artifacts"]["before_state"]["sha256"],
                "after_state_sha256": fixed["artifacts"]["after_state"]["sha256"],
                "source_values": values,
                "target_values": values,
            },
        )
        trace = [
            {"type": "dispatch", "node_id": n["id"], "state_owner": n["state_owner"]}
            for n in graph["nodes"]
        ] + [
            {
                "type": "message",
                "from": a,
                "to": b,
                "bytes": 4,
                "cost_event_id": "messages",
            }
            for a, b in graph["edges"]
        ]
        trace.append(
            {"type": "encode", "input_sha256": "e" * 64, "cost_event_id": "reencoding"}
        )
        for index, row in enumerate(trace):
            row.update(
                sequence=index,
                run_id=fixed["run_id"],
                task_id="task-2",
                generation=graph["generation"],
                graph_sha256=canonical_sha(graph),
            )
        helper.write(fixed, "trace", trace)
        costs = helper.read(dynamic, "costs")
        for row in costs:
            row["methods"] = [ARMS[0]]
        helper.write(fixed, "costs", costs)
        helper.write(fixed, "recovery", helper.read(dynamic, "recovery"))
        return helper.seal(fixed), dynamic

    def build(self, kind="split"):
        fixed, dynamic = self.topology(kind)
        inventory = self.artifact(
            {
                "schema": "hepta.org1.capabilities.v1",
                "protected": ["recovery:lost_ack"],
            }
        )
        contracts = {
            "initial_artifacts_sha256": "1" * 64,
            "objective_sha256": "2" * 64,
            "scheduler_sha256": fixed["adaptive_scheduler_sha256"],
            "scheduler_tuning_sha256": "3" * 64,
            "evaluation_sha256": "4" * 64,
            "before_graph_sha256": canonical_sha(
                self.helper.read(fixed, "before_graph")
            ),
            "before_state_sha256": fixed["artifacts"]["before_state"]["sha256"],
            "capability_inventory_sha256": inventory["sha256"],
        }
        roster = [
            {
                "pair_id": f"ordinary-{seed}-{task}",
                "task_id": task,
                "seed": seed,
                "panel": "ordinary",
                "capability_id": None,
            }
            for seed in (11, 29)
            for task in ("task-a", "task-b")
        ] + [
            {
                "pair_id": "retention",
                "task_id": "old-skill",
                "seed": 11,
                "panel": "retention",
                "capability_id": None,
            },
            {
                "pair_id": "rare",
                "task_id": "lost-ack",
                "seed": 29,
                "panel": "rare_fault",
                "capability_id": "recovery:lost_ack",
            },
        ]
        axes = [
            "cpu_seconds",
            "accelerator_seconds",
            "transferred_bytes",
            "resident_byte_seconds",
        ]
        self.protocol = {
            "schema": "hepta.org1.protocol.v1",
            "scope": "synthetic_reference",
            "operation": kind,
            "candidate_id": "candidate-1",
            "contracts": contracts,
            "trigger_rule": {
                "kind": "stable_cluster",
                "metric": "cluster_stability",
                "minimum_windows": 2,
                "minimum_samples_per_window": 4,
                "minimum_value": 0.8,
            },
            "roster": roster,
            "protected_capabilities": [
                {
                    "capability_id": "recovery:lost_ack",
                    "minimum_score": 0.95,
                    "maximum_drop": 0.02,
                }
            ],
            "required_cost_axes": axes,
            "utility_rates": dict(zip(axes, (1.0, 1.0, 1e-6, 1e-9))),
            "budget": {axis: 1000.0 for axis in axes},
            "minimum_mean_net_gain": 0.05,
            "maximum_retention_drop": 0.02,
            "comparison_method": "finite_paired_panel",
        }
        self.evidence = {
            "schema": "hepta.org1.evidence.v1",
            "capability_inventory": inventory,
            "trigger_windows": [
                self.artifact(
                    {
                        "window_id": f"window-{i}",
                        "start": i * 20,
                        "end": i * 20 + 10,
                        "samples": 4,
                        "sample_ids": [f"sample-{i}-{j}" for j in range(4)],
                        "value": 0.9,
                        "cluster_id": "stable-task-family",
                    }
                )
                for i in range(2)
            ],
            "fixed_topology": fixed,
            "dynamic_topology": dynamic,
            "arms": {},
        }
        stages = (
            "search",
            "training",
            "evaluation",
            "inference",
            "communication",
            "loading",
            "migration",
            "relearning",
            "maintenance",
            "recovery",
        )
        for arm in ARMS:
            self.evidence["arms"][arm] = {
                "contracts": copy.deepcopy(contracts),
                "trials": [
                    self.artifact(
                        {
                            "pair_id": row["pair_id"],
                            "task_id": row["task_id"],
                            "seed": row["seed"],
                            "status": "completed",
                            "score": (0.5 if arm == ARMS[0] else 0.8)
                            if row["panel"] == "ordinary"
                            else 1.0,
                        }
                    )
                    for row in roster
                ],
                "costs": [
                    self.artifact(
                        {
                            "event_id": arm + ":" + stage,
                            "stage": stage,
                            "values": dict(
                                zip(
                                    axes,
                                    (
                                        0.01,
                                        0.0,
                                        100.0 if stage == "communication" else 0.0,
                                        0.0,
                                    ),
                                )
                            ),
                        }
                    )
                    for stage in stages
                ],
            }
        self.seal_protocol()

    def seal_protocol(self):
        self.protocol_pin = canonical_sha(self.protocol)
        self.evidence["protocol_sha256"] = self.protocol_pin
        for ref in self.evidence["trigger_windows"]:
            self.amend(ref, lambda row: row.update(protocol_sha256=self.protocol_pin))
        for arm, topology in zip(ARMS, ("fixed_topology", "dynamic_topology")):
            for ref in (
                self.evidence["arms"][arm]["trials"]
                + self.evidence["arms"][arm]["costs"]
            ):
                self.amend(
                    ref,
                    lambda row: row.update(
                        arm_id=arm,
                        run_id=self.evidence[topology]["run_id"],
                        protocol_sha256=self.protocol_pin,
                    ),
                )

    def review(self, *, observer_pins=None, protocol_pin=None):
        pins = [
            self.evidence[key]["artifacts"]["owner"]["sha256"]
            for key in ("fixed_topology", "dynamic_topology")
        ]
        return review_organization(
            self.protocol,
            self.evidence,
            self.root,
            trusted_protocol_sha256=self.protocol_pin
            if protocol_pin is None
            else protocol_pin,
            trusted_observer_sha256=pins if observer_pins is None else observer_pins,
        )

    def assert_held(self, *, reason=None):
        result = self.review()
        self.assertEqual(
            (result["status"], result["finite_panel_passed"]), ("HOLD", False)
        )
        if reason is not None:
            self.assertTrue(
                any(reason in r for r in result["reasons"]), result["reasons"]
            )
        return result

    def test_all_structural_fixtures_pass_only_the_finite_reference_screen(self):
        for kind in ("split", "merge", "rewire"):
            with self.subTest(kind=kind):
                self.build(kind)
                result = self.review()
                self.assertEqual(
                    (
                        result["status"],
                        result["planned_pairs"],
                        result["observed_pairs"],
                    ),
                    ("REFERENCE_CONSISTENT", 6, 6),
                )
                self.assertTrue(result["proposal_trigger_supported"])
                self.assertTrue(result["finite_panel_passed"])
                self.assertAlmostEqual(result["mean_net_gain"], 0.3)
                self.assertEqual(
                    (result["scientific_acceptance"], result["decision"]),
                    ("HOLD", "NoUpdate"),
                )
                self.assertFalse(
                    any(
                        result[k]
                        for k in (
                            "benefit_proven",
                            "adoption_authorized",
                            "runtime_authority",
                            "full_physical_cost_known",
                            "measurement_authenticity_verified",
                            "inventory_completeness_verified",
                            "preregistration_verified",
                        )
                    )
                )

    def test_protocol_pin_and_external_observer_are_required(self):
        result = self.review(observer_pins=[])
        self.assertIn("TOPOLOGY_EVIDENCE_BLOCKED", result["reasons"])
        self.protocol["minimum_mean_net_gain"] = 0.01
        self.assert_held(reason="FROZEN_PROTOCOL_MISMATCH")

    def test_raw_bytes_and_safe_paths_are_checked(self):
        reference = self.evidence["trigger_windows"][0]
        path = self.root / reference["path"]
        path.write_bytes(path.read_bytes() + b" ")
        reference["bytes"] += 1
        with self.assertRaises(ValueError):
            self.review()
        reference["path"] = "../outside.json"
        with self.assertRaises(ValueError):
            self.review()

    def test_a_read_updating_access_time_does_not_change_artifact_identity(self):
        path = self.root / self.evidence["capability_inventory"]["path"]
        os.utime(path, ns=(0, path.stat().st_mtime_ns))
        self.assertEqual(self.review()["status"], "REFERENCE_CONSISTENT")

    def test_duplicate_json_fields_and_nonfinite_originals_are_rejected(self):
        ref = self.evidence["arms"][ARMS[1]]["trials"][0]
        for raw in (b'{"score": 0, "score": 1}', b'{"score": NaN}'):
            with self.subTest(raw=raw):
                ref.update(self.artifact(None, raw=raw))
                with self.assertRaises(ValueError):
                    self.review()

    def test_costs_cannot_hide_unknown_missing_or_duplicate_work(self):
        costs = self.evidence["arms"][ARMS[1]]["costs"]
        original = copy.deepcopy(costs)
        self.amend(costs[0], lambda row: row["values"].update(cpu_seconds=None))
        result = self.assert_held(reason="UNKNOWN_COST")
        self.assertIsNone(result["cost_totals"][ARMS[1]]["cpu_seconds"])
        self.assertIsNone(result["mean_net_gain"])
        costs[:] = original[:-1]
        self.assert_held(reason="MISSING_COST_STAGES")
        costs[:] = original
        self.amend(costs[-1], lambda row: row.update(event_id=ARMS[1] + ":search"))
        with self.assertRaises(ValueError):
            self.review()

    def test_all_cost_axes_reject_boolean_negative_or_infinite_values(self):
        ref = self.evidence["arms"][ARMS[1]]["costs"][0]
        for value in (True, -1.0, float("inf")):
            with self.subTest(value=value):
                self.amend(
                    ref, lambda row: row["values"].update(accelerator_seconds=value)
                )
                with self.assertRaises(ValueError):
                    self.review()

    def test_loading_overhead_is_charged_and_can_erase_task_gain(self):
        ref = self.evidence["arms"][ARMS[1]]["costs"][5]
        self.amend(ref, lambda row: row["values"].update(cpu_seconds=2.01))
        result = self.assert_held(reason="NET_GAIN_NOT_SUFFICIENT")
        self.assertAlmostEqual(result["mean_net_gain"], -0.2)

    def test_existing_topology_cpu_and_message_costs_are_resource_lower_bounds(self):
        self.amend(
            self.evidence["arms"][ARMS[1]]["costs"][4],
            lambda row: row["values"].update(transferred_bytes=99.0),
        )
        self.assert_held()
        self.build()
        dynamic = self.evidence["dynamic_topology"]
        costs = self.helper.read(dynamic, "costs")
        costs[0]["measurements"]["cpu_seconds"] = 0.2
        self.helper.write(dynamic, "costs", costs)
        self.helper.seal(dynamic)
        self.assert_held()

    def test_missing_duplicate_and_unresolved_trials_never_shrink_the_roster(self):
        trials = self.evidence["arms"][ARMS[1]]["trials"]
        original = copy.deepcopy(trials)
        trials.pop(0)
        result = self.assert_held(reason="INCOMPLETE_TRIAL_DENOMINATOR")
        self.assertEqual((result["planned_pairs"], result["observed_pairs"]), (6, 5))
        self.assertIsNone(result["mean_net_gain"])
        trials[:] = original + [original[0]]
        with self.assertRaises(ValueError):
            self.review()
        trials[:] = original
        self.amend(trials[0], lambda row: row.update(status="unresolved", score=None))
        self.assert_held(reason="UNRESOLVED_TRIAL")

    def test_failures_are_scored_zero_and_keep_their_costs(self):
        trials = self.evidence["arms"][ARMS[1]]["trials"]
        for ref in trials[:2]:
            self.amend(ref, lambda row: row.update(status="failed", score=None))
        result = self.assert_held(reason="NET_GAIN_NOT_SUFFICIENT")
        self.assertEqual(result["observed_pairs"], 6)
        self.assertAlmostEqual(result["mean_net_gain"], -0.1)
        self.assertAlmostEqual(result["cost_totals"][ARMS[1]]["cpu_seconds"], 0.1)
        self.amend(trials[0], lambda row: row.update(score=1.0))
        with self.assertRaises(ValueError):
            self.review()

    def test_trigger_requires_repetition_and_distinct_observation_samples(self):
        windows = self.evidence["trigger_windows"]
        original = copy.deepcopy(windows)
        windows.pop()
        self.assert_held(reason="TRIGGER_NOT_REPRODUCED")
        windows[:] = original
        self.amend(
            windows[1],
            lambda row: row.update(sample_ids=[f"sample-0-{j}" for j in range(4)]),
        )
        with self.assertRaises(ValueError):
            self.review()

    def test_interference_is_recomputed_from_paired_observations(self):
        self.protocol["trigger_rule"].update(
            kind="learning_interference",
            metric="paired_heldout_score_drop",
            minimum_value=0.2,
        )
        self.seal_protocol()
        for ref in self.evidence["trigger_windows"]:
            self.amend(
                ref,
                lambda row: row.update(
                    control_scores=[0.8] * 4,
                    updated_scores=[0.5] * 4,
                    intervention_sha256="8" * 64,
                    value=0.3,
                ),
            )
        self.assertEqual(self.review()["status"], "REFERENCE_CONSISTENT")
        self.amend(
            self.evidence["trigger_windows"][1], lambda row: row.update(value=0.9)
        )
        with self.assertRaises(ValueError):
            self.review()

    def test_capacity_pressure_is_recomputed_from_usage_and_limits(self):
        self.protocol["trigger_rule"].update(
            kind="capacity_bottleneck", metric="measured_capacity_pressure"
        )
        self.seal_protocol()
        for ref in self.evidence["trigger_windows"]:
            self.amend(
                ref,
                lambda row: row.update(used=[9.0] * 4, capacity=[10.0] * 4, value=0.9),
            )
        self.assertEqual(self.review()["status"], "REFERENCE_CONSISTENT")
        self.amend(
            self.evidence["trigger_windows"][1], lambda row: row.update(value=1.0)
        )
        with self.assertRaises(ValueError):
            self.review()

    def test_new_pair_names_cannot_duplicate_the_same_seeded_task(self):
        self.protocol["roster"][1].update(task_id=self.protocol["roster"][0]["task_id"])
        self.seal_protocol()
        with self.assertRaises(ValueError):
            self.review()

    def test_low_utilization_and_retirement_are_not_structural_authority(self):
        self.protocol["trigger_rule"].update(
            kind="low_utilization", metric="usage_fraction"
        )
        self.seal_protocol()
        with self.assertRaises(ValueError):
            self.review()
        self.build()
        self.protocol["operation"] = "retire"
        self.seal_protocol()
        with self.assertRaises(ValueError):
            self.review()

    def test_two_failed_retention_trials_do_not_establish_capability_retention(self):
        for arm in ARMS:
            ref = self.evidence["arms"][arm]["trials"][-2]
            self.amend(ref, lambda row: row.update(status="failed", score=None))
        result = self.assert_held(reason="RETENTION_FAILURE")
        self.assertEqual(result["observed_pairs"], result["planned_pairs"])
        self.assertGreater(
            result["mean_net_gain"], self.protocol["minimum_mean_net_gain"]
        )

    def test_rare_recovery_loss_blocks_even_with_ordinary_task_gain(self):
        self.build("merge")
        ref = self.evidence["arms"][ARMS[1]]["trials"][-1]
        self.amend(ref, lambda row: row.update(score=0.8))
        result = self.assert_held(reason="PROTECTED_CAPABILITY_LOSS:recovery:lost_ack")
        self.assertGreater(
            result["mean_net_gain"], self.protocol["minimum_mean_net_gain"]
        )

    def test_protected_inventory_cannot_be_relabelled_or_omitted(self):
        self.protocol["protected_capabilities"][0]["capability_id"] = "easy-fault"
        self.seal_protocol()
        self.assert_held(reason="PROTECTED_CAPABILITY_INVENTORY_MISMATCH")
        self.build()
        self.protocol["roster"].pop()
        for arm in ARMS:
            self.evidence["arms"][arm]["trials"].pop()
        self.seal_protocol()
        self.assert_held(reason="PROTECTED_CAPABILITY_PANEL_INCOMPLETE")

    def test_actual_initial_state_is_bound_beyond_legacy_pair_validation(self):
        helper, dynamic = self.helper, self.evidence["dynamic_topology"]
        state = helper.read(dynamic, "before_state")
        state["states"]["a"] = [7.0]
        helper.write(dynamic, "before_state", state)
        migration = helper.read(dynamic, "migration")
        migration["before_state_sha256"] = dynamic["artifacts"]["before_state"][
            "sha256"
        ]
        migration["source_values"]["a"] = canonical_sha([7.0])
        helper.write(dynamic, "migration", migration)
        recovery = helper.read(dynamic, "recovery")
        recovery["restored_state"] = state
        helper.write(dynamic, "recovery", recovery)
        helper.seal(dynamic)
        pins = [
            self.evidence[k]["artifacts"]["owner"]["sha256"]
            for k in ("fixed_topology", "dynamic_topology")
        ]
        for receipt in (self.evidence["fixed_topology"], dynamic):
            old = validate_topology_receipt(
                receipt, self.root, trusted_observer_sha256=pins
            )
            self.assertEqual(old["status"], "EVIDENCE_CONSISTENT")
        self.assert_held(reason="INITIAL_STATE_MISMATCH")

    def test_scheduler_contract_cannot_be_changed_only_for_the_candidate(self):
        dynamic = self.evidence["dynamic_topology"]
        dynamic["adaptive_scheduler_sha256"] = "9" * 64
        self.helper.seal(dynamic)
        self.assert_held(reason="SCHEDULER_MISMATCH")

    def test_original_trial_and_cost_files_cannot_be_swapped_between_arms(self):
        for collection in ("trials", "costs"):
            with self.subTest(collection=collection):
                self.build()
                first, second = (self.evidence["arms"][arm] for arm in ARMS)
                first[collection], second[collection] = (
                    second[collection],
                    first[collection],
                )
                try:
                    result = self.review()
                except ValueError:
                    continue
                self.assertEqual(result["status"], "HOLD", result)


if __name__ == "__main__":
    unittest.main()

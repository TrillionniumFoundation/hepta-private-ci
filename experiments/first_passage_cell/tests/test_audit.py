"""Hand-computed renewal ledgers and adversarial cohort/accounting checks.

These fixtures do not call the simulator, value model, kernel, or training code.
The main path is WAIT, WAIT, REPAIR, STOP. Its inactive intervals are
[.10,.16], [.48,.54], [.90,.96], and [1.00,1.06], so its 1.5 elapsed
seconds contain 1.26 active seconds, three failures and one paid .20 repair.
The net score is .6*1.26 - .5*3 - .20 = -.944.
"""

import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from ..audit import audit_episode, audit_run, bootstrap_comparison


HERE = Path(__file__).resolve().parents[1]


def hand_episode():
    """Literal timeline and arithmetic, independently specified by hand."""
    scenario = {"identity": "confirmation:1103:hand", "level": 1.3,
                "inputs": [0.2, -0.1], "repair_cost": 0.2,
                "noise_seed": 912, "regime": "nominal"}
    # before=(level,time,pending), after=(level,time,pending), followed by
    # independently calculated activity, running reward, costs and net scores.
    cases = [
        {"action": "wait", "before": (1.3, 0.0, 0.0), "after": (1.02, 0.5, 0.04),
         "remaining": 2.0, "active": 0.42, "events": [(0.10, 1), (0.48, 2)],
         "running": 0.252, "failure_cost": 1.0, "action_cost": 0.0,
         "reward": -0.748, "cumulative": -0.748, "counter": 2, "done": False},
        {"action": "wait", "before": (1.02, 0.5, 0.04), "after": (0.85, 1.0, 0.0),
         "remaining": 1.5, "active": 0.40, "events": [(0.90, 3)],
         "running": 0.240, "failure_cost": 0.5, "action_cost": 0.0,
         "reward": -0.260, "cumulative": -1.008, "counter": 5, "done": False},
        {"action": "repair", "before": (0.85, 1.0, 0.0), "after": (1.3, 1.5, 0.0),
         "remaining": 1.0, "active": 0.44, "events": [],
         "running": 0.264, "failure_cost": 0.0, "action_cost": 0.2,
         "reward": 0.064, "cumulative": -0.944, "counter": 7, "done": False},
        {"action": "stop", "before": (1.3, 1.5, 0.0), "after": (1.3, 1.5, 0.0),
         "remaining": 0.5, "active": 0.0, "events": [],
         "running": 0.0, "failure_cost": 0.0, "action_cost": 0.0,
         "reward": 0.0, "cumulative": -0.944, "counter": 7, "done": True},
    ]
    rows = []
    for index, case in enumerate(cases):
        level, start, pending = case["before"]
        next_level, end, next_pending = case["after"]
        rows.append({
            "scenario_id": scenario["identity"], "action": case["action"],
            "observation": {"level": level, "time": start,
                            "refractory_remaining": pending, "inputs": [0.2, -0.1],
                            "repair_cost": 0.2, "remaining_duration": case["remaining"],
                            "decision_index": index,
                            "legal_actions": ["wait", "stop"] if pending else ["wait", "repair", "stop"]},
            "outcome": {"level": next_level, "time": end,
                        "elapsed_duration": end - start, "active_duration": case["active"],
                        "refractory_remaining": next_pending,
                        "failure_count": len(case["events"]),
                        "events": [{"kind": "first_passage", "time": time, "ordinal": ordinal}
                                   for time, ordinal in case["events"]],
                        "random_counter": case["counter"]},
            "interventions": [{"time": 1.0, "kind": "repair"}] if index == 2 else [],
            "running_reward": case["running"], "failure_cost": case["failure_cost"],
            "action_cost": case["action_cost"], "reward": case["reward"],
            "cumulative_reward": case["cumulative"], "done": case["done"],
            "decision": {"action": case["action"].upper(), "values": None},
        })
    rows[0]["decision"]["values"] = {"actions": {"WAIT": {"value": -0.5}}}
    return {"phase": "confirmation", "seed": 1103, "arm": "endogenous_renewal",
            "scenario": scenario, "records": rows, "total_reward": -0.944}


def stop_episode(index=0, arm="ordinary_first_event", cost=0.2):
    """A zero-time STOP has exactly zero score, irrespective of public price."""
    identity = f"confirmation:1103:{index}"
    scenario = {"identity": identity, "level": 1.3, "inputs": [0.2, -0.1],
                "repair_cost": cost, "noise_seed": 912 + index, "regime": "nominal"}
    row = {"scenario_id": identity, "action": "stop", "done": True,
           "observation": {"level": 1.3, "time": 0.0, "refractory_remaining": 0.0,
                           "inputs": [0.2, -0.1], "repair_cost": cost,
                           "remaining_duration": 2.0, "decision_index": 0,
                           "legal_actions": ["wait", "repair", "stop"]},
           "outcome": {"level": 1.3, "time": 0.0, "elapsed_duration": 0.0,
                       "active_duration": 0.0, "refractory_remaining": 0.0,
                       "failure_count": 0, "events": [], "random_counter": 0},
           "interventions": [], "running_reward": 0.0, "failure_cost": 0.0,
           "action_cost": 0.0, "reward": 0.0, "cumulative_reward": 0.0}
    return {"phase": "confirmation", "seed": 1103, "arm": arm,
            "scenario": scenario, "records": [row], "total_reward": 0.0}


def write_cohort(folder, episodes):
    path = Path(folder) / "hand-ledgers.jsonl.gz"
    with gzip.open(path, "wt") as stream:
        for episode in episodes:
            stream.write(json.dumps(episode, separators=(",", ":"), allow_nan=False) + "\n")
    return path


class LedgerArithmeticTests(unittest.TestCase):
    def test_hand_computed_multi_event_repair_and_stop(self):
        result = audit_episode(hand_episode())
        self.assertAlmostEqual(result["total_reward"], -0.944)
        self.assertAlmostEqual(result["active_time"], 1.26)
        self.assertEqual(result["failures"], 3)
        self.assertEqual(result["repairs"], 1)
        self.assertEqual(result["paid_repair_cost"], 0.2)
        self.assertEqual(result["elapsed"], 1.5)
        self.assertEqual(result["decisions"], 4)
        self.assertTrue(result["stopped"])
        self.assertEqual(result["initial_plan_value"], -0.5)
        self.assertAlmostEqual(result["realized_minus_initial_plan"], -0.444)

    def test_false_activity_is_rejected_even_with_consistent_scores(self):
        episode = hand_episode()
        row = episode["records"][0]
        row["outcome"]["active_duration"] = 0.43
        row["running_reward"] = 0.258
        row["reward"] = -0.742
        for item in episode["records"]:
            item["cumulative_reward"] += 0.006
        episode["total_reward"] += 0.006
        with self.assertRaisesRegex(ValueError, "active-time"):
            audit_episode(episode)

    def test_discounted_repair_bill_is_rejected_even_with_consistent_scores(self):
        episode = hand_episode()
        episode["records"][2]["action_cost"] = 0.1
        episode["records"][2]["reward"] = 0.164
        for row in episode["records"][2:]:
            row["cumulative_reward"] += 0.1
        episode["total_reward"] += 0.1
        with self.assertRaisesRegex(ValueError, "action_cost"):
            audit_episode(episode)

    def test_impossible_or_out_of_window_event_times_are_rejected(self):
        for bad_time in (0.14, 0.51, float("nan")):
            with self.subTest(time=bad_time):
                episode = hand_episode()
                episode["records"][0]["outcome"]["events"][1]["time"] = bad_time
                with self.assertRaisesRegex(ValueError, "Events violate"):
                    audit_episode(episode)

    def test_control_deadline_event_is_counted_and_refractory_is_carried(self):
        episode = stop_episode()
        first = copy.deepcopy(episode["records"][0])
        first.update({"action": "wait", "done": False, "running_reward": 0.3,
                      "failure_cost": 0.5, "reward": -0.2, "cumulative_reward": -0.2})
        first["outcome"].update({"level": 1.02, "time": 0.5, "elapsed_duration": 0.5,
                                  "active_duration": 0.5, "refractory_remaining": 0.06,
                                  "failure_count": 1, "random_counter": 1,
                                  "events": [{"kind": "first_passage", "time": 0.5, "ordinal": 1}]})
        final = episode["records"][0]
        final["observation"].update({"level": 1.02, "time": 0.5, "refractory_remaining": 0.06,
                                      "decision_index": 1, "remaining_duration": 1.5,
                                      "legal_actions": ["wait", "stop"]})
        final["outcome"].update({"level": 1.02, "time": 0.5, "refractory_remaining": 0.06,
                                  "random_counter": 1})
        final["cumulative_reward"] = -0.2
        episode.update({"records": [first, final], "total_reward": -0.2})
        result = audit_episode(episode)
        self.assertAlmostEqual(result["total_reward"], -0.2)
        self.assertEqual(result["active_time"], 0.5)
        self.assertEqual(result["failures"], 1)

    def test_communication_cannot_be_relabelled_as_a_physical_event(self):
        episode = hand_episode()
        episode["records"][0]["outcome"]["events"][0]["kind"] = "communication"
        with self.assertRaisesRegex(ValueError, "Event kind"):
            audit_episode(episode)

    def test_actual_action_must_equal_the_retained_policy_decision(self):
        episode = hand_episode()
        episode["records"][2]["decision"]["action"] = "WAIT"
        with self.assertRaisesRegex(ValueError, "Scored action"):
            audit_episode(episode)

    def test_stop_cannot_consume_randomness_or_keep_episode_open(self):
        episode = stop_episode()
        episode["records"][0]["outcome"]["random_counter"] = 1
        with self.assertRaisesRegex(ValueError, "consumed randomness"):
            audit_episode(episode)
        episode = stop_episode()
        episode["records"][0]["done"] = False
        with self.assertRaisesRegex(ValueError, "Termination"):
            audit_episode(episode)


class PairedCohortTests(unittest.TestCase):
    def test_one_missing_arm_episode_cannot_be_silently_dropped(self):
        # Preserve all 256 scenario identities in the first arm. Remove only
        # one paired outcome from the second arm; no constants are patched.
        episodes = [stop_episode(i) for i in range(256)]
        episodes += [stop_episode(i, "endogenous_renewal") for i in range(255)]
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            write_cohort(folder, episodes)
            with self.assertRaisesRegex(ValueError, "Incomplete cohort for 1103/endogenous_renewal"):
                audit_run(folder)

    def test_duplicate_outcomes_are_not_extra_replication(self):
        episode = stop_episode()
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            write_cohort(folder, [episode, copy.deepcopy(episode)])
            with self.assertRaisesRegex(ValueError, "Duplicate evaluation"):
                audit_run(folder)

    def test_paired_arms_must_receive_the_same_public_price(self):
        episodes = [stop_episode(0, "ordinary_first_event", 0.2),
                    stop_episode(0, "endogenous_renewal", 0.3)]
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            write_cohort(folder, episodes)
            with self.assertRaisesRegex(ValueError, "different scenarios"):
                audit_run(folder)


class StatisticsGateTests(unittest.TestCase):
    def test_constant_positive_paired_gain_has_known_interval(self):
        result = bootstrap_comparison(np.full((8, 256), 0.01),
                                      np.random.default_rng(9), replicates=32)
        np.testing.assert_allclose(result["empirical_family_adjusted_interval"], [0.01, 0.01],
                                   rtol=0, atol=1e-15)
        self.assertAlmostEqual(result["individual_interval_level"], 59 / 60)
        self.assertEqual(result["family_size"], 3)
        self.assertTrue(result["pass"])
        self.assertFalse(result["population_guarantee"])

    def test_shared_large_returns_cannot_make_zero_paired_gain_pass(self):
        result = bootstrap_comparison(np.zeros((8, 256)),
                                      np.random.default_rng(10), replicates=32)
        self.assertEqual(result["empirical_family_adjusted_interval"], [0.0, 0.0])
        self.assertFalse(result["pass"])

    def test_positive_overall_mean_does_not_hide_a_negative_model_seed(self):
        gain = np.full((8, 256), 0.04)
        gain[0] = -0.001
        result = bootstrap_comparison(gain, np.random.default_rng(11), replicates=32)
        self.assertGreater(result["mean_gain"], 0.005)
        self.assertFalse(result["all_seed_means_positive"])
        self.assertFalse(result["pass"])

    def test_wrong_replication_unit_and_nonfinite_results_are_rejected(self):
        for value in (np.zeros(2048), np.zeros((8, 255)), np.full((8, 256), np.nan)):
            with self.subTest(shape=value.shape):
                with self.assertRaisesRegex(ValueError, "8 seeds by 256 episodes"):
                    bootstrap_comparison(value, np.random.default_rng(12), replicates=2)


if __name__ == "__main__":
    unittest.main()

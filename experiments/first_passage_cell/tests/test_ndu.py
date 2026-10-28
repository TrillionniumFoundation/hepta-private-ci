"""Native source/profile binding and independently checked value propagation."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import itertools
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from experiments.first_passage_cell.cell import CellParameters, sample_hitting_time
from experiments.first_passage_cell.ndu import NativeNduPort, Q32, q32, recursive_reference
from experiments.first_passage_cell.task import MaintenanceTask, scenarios, true_parameters
from experiments.first_passage_cell.value import action_values, renewal_moments, select_action


def observation(distance=0.4, cost=0.2, remaining=2.0, pending=0.0):
    return {"task_profile": "hepta-maintenance-renewal-v1", "level": 0.12 + distance,
            "time": 2.0 - remaining, "inputs": [0.0, 0.0], "repair_cost": cost,
            "remaining_duration": remaining, "refractory_remaining": pending,
            "decision_index": int((2.0 - remaining) / 0.5),
            "legal_actions": ["wait", "stop"] if pending else ["wait", "repair", "stop"]}


class RenewalValueTests(unittest.TestCase):
    def test_full_renewal_matches_independent_inverse_gaussian_quadrature(self):
        base = true_parameters()
        for mu, distance, horizon in ((-0.55, 0.02, 0.5), (-0.55, 0.3, 2.0),
                                     (-0.55, 0.0, 2.0), (-1.2, 0.1, 2.0),
                                     (0.0, 0.2, 2.0), (0.4, 0.2, 2.0)):
            parameters = replace(base, drift=mu)
            actual = renewal_moments(parameters, distance, (0.0, 0.0), horizon)
            reference = renewal_moments(parameters, distance, (0.0, 0.0), horizon, method="quad")
            with self.subTest(mu=mu, distance=distance):
                self.assertAlmostEqual(actual["expected_failures"], reference["expected_failures"], delta=2e-10)
                self.assertAlmostEqual(actual["active_time"], reference["active_time"], delta=2e-9)
                self.assertLessEqual(actual["active_time"], horizon)
                self.assertGreaterEqual(actual["active_time"], 0.0)

    def test_independent_event_sampling_checks_multiple_failures_and_time(self):
        parameters = replace(true_parameters(), drift=-0.95, reset_gap=0.42)
        count, horizon, distance = 10000, 2.0, 0.15
        rng = np.random.Generator(np.random.Philox(837611))
        rows = []
        for _ in range(count):
            remaining, active, failures, gap = horizon, 0.0, 0, distance
            while remaining > 0:
                hit = sample_hitting_time(gap, parameters.drift, parameters.sigma, rng)
                run = min(hit, remaining)
                active += run
                remaining -= run
                if hit > run:
                    break
                failures += 1
                remaining = max(0.0, remaining - parameters.refractory)
                gap = parameters.reset_gap
            rows.append((active, failures))
        samples = np.asarray(rows)
        predicted = renewal_moments(parameters, distance, (0.0, 0.0), horizon)
        target = [predicted["active_time"], predicted["expected_failures"]]
        error = np.abs(samples.mean(axis=0) - target)
        allowance = 5 * samples.std(axis=0, ddof=1) / np.sqrt(count) + 1e-4
        self.assertTrue(np.all(error < allowance), (error, allowance))
        self.assertGreater(target[1], 2.0)

    def test_cost_is_charged_once_and_refractory_uses_observed_level(self):
        parameters = true_parameters()
        cheap = action_values(parameters, observation(cost=0.05))
        costly = action_values(parameters, observation(cost=0.4))
        self.assertAlmostEqual(cheap["actions"]["REPAIR"]["value"] - costly["actions"]["REPAIR"]["value"], 0.35)
        self.assertEqual(cheap["actions"]["WAIT"], costly["actions"]["WAIT"])
        for row in cheap["actions"].values():
            self.assertAlmostEqual(row["value"], sum(e["instant"] for e in row["events"]))
        obs = observation(distance=0.7, pending=0.03)
        value = action_values(parameters, obs)["actions"]["WAIT"]
        reference = renewal_moments(parameters, 0.7, (0.0, 0.0), 1.97)
        self.assertAlmostEqual(value["expected_active_time"], reference["active_time"])
        self.assertAlmostEqual(value["expected_failure_count"], reference["expected_failures"])

    def test_threshold_and_bias_change_decisions_without_changing_task_utility(self):
        parameters, obs = true_parameters(), observation(distance=0.4, cost=0.05)
        low = select_action(parameters, obs, "learned_threshold", threshold=0.1)
        high = select_action(parameters, obs, "learned_threshold", threshold=0.8)
        self.assertEqual(low["action"], "WAIT")
        self.assertEqual(high["action"], "REPAIR")
        self.assertEqual(low["values"], high["values"])
        minus = select_action(parameters, obs, "endogenous", bias=-0.08)
        plus = select_action(parameters, obs, "endogenous", bias=0.08)
        self.assertEqual(minus["values"], plus["values"])
        cache = {}
        first = select_action(parameters, obs, "endogenous", forecast_cache=cache)
        second = select_action(parameters, obs, "endogenous", bias=0.01, forecast_cache=cache)
        self.assertIs(first["values"], second["values"])


class NativeNduTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = Path(__file__).resolve().parents[4] / "native_build/NATIVE_BUILD.json"
        cls.manifest = Path(os.environ.get("HEPTA_FIRST_PASSAGE_NATIVE", default))
        cls.native = NativeNduPort(cls.manifest)

    def test_relative_binary_path_is_resolved_against_manifest(self):
        original = json.loads(self.manifest.read_text())
        with tempfile.TemporaryDirectory(prefix="first-passage-portable-") as directory:
            folder = Path(directory)
            (folder / "native").symlink_to(self.native.binary)
            original["binary"] = "native"
            manifest = folder / "NATIVE_BUILD.json"
            manifest.write_text(json.dumps(original))
            portable = NativeNduPort(manifest, expected_binary_sha256=self.native.binary_sha256)
            actual = portable.evaluate_paths({"STOP": {"events": [{"instant": 0.0}]}},
                                               {"test": "portable-relative-binary"})
            self.assertEqual(actual["action_values"], {"STOP": 0.0})
            self.assertEqual(portable.source_manifest_sha256, self.native.source_manifest_sha256)

    def test_explicit_abstain_is_preserved_or_rejected_without_rewriting(self):
        supplied = {"events": [{"instant": 0.0, "discount": 0.75}]}
        receipt = self.native.evaluate_paths({"abstain": supplied}, {"test": "explicit-abstain"})
        self.assertEqual(receipt["request"]["candidates"][0]["events"][0]["discount_q32"], q32(0.75))
        self.assertEqual(receipt["action_values"], {"ABSTAIN": 0.0})
        for name in ("ABSTAIN", "abstain"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.native.evaluate_paths({name: {"events": [{"instant": 1.0}]}},
                                           {"test": "invalid-explicit-abstain"})
        with self.assertRaises(ValueError):
            self.native.evaluate_paths({"STOP": supplied, "ABSTAIN": supplied},
                                       {"test": "duplicate-stop-abstain"})

    def test_original_recursive_contract_matches_complete_finite_tree(self):
        probabilities = [Fraction(1, 4), Fraction(1, 2), Fraction(3, 4)]
        discounts = [Fraction(9, 10), Fraction(3, 4), Fraction(1)]
        paths, weights, expected = {}, {}, Fraction(0)
        for bits in itertools.product((0, 1), repeat=3):
            name, probability, accumulated = "leaf" + "".join(map(str, bits)), Fraction(1), Fraction(0)
            rewards = [Fraction(3, 10) - Fraction(bit, 2) - (Fraction(1, 5) if i == 0 else 0)
                       for i, bit in enumerate(bits)]
            for i, bit in enumerate(bits):
                probability *= probabilities[i] if bit else 1 - probabilities[i]
            for reward, discount in reversed(list(zip(rewards, discounts))):
                accumulated = reward + discount * accumulated
            paths[name] = {"events": [{"instant": float(r), "discount": float(d)}
                                      for r, d in zip(rewards, discounts)]}
            weights[name.upper()] = probability
            expected += probability * accumulated
        receipt = self.native.evaluate_paths(paths, {"test": "finite-tree-3-depth-complete-8-leaves"})
        actual = sum(float(weight) * receipt["action_values"][name] for name, weight in weights.items())
        self.assertLess(abs(actual - float(expected)), 5 / Q32)
        self.assertEqual(receipt["response"]["authority"], "DENY_ALL")
        self.assertFalse(receipt["response"]["safety_certificate"])
        self.assertEqual(len(weights), 8)

    def test_native_signed_ties_even_and_later_values(self):
        paths = {"tie" + str(i): {"events": [{"instant": 0.0, "discount": 0.5}],
                                  "terminal": i / Q32} for i in (1, 3, -1, -3)}
        receipt = self.native.evaluate_paths(paths, {"test": "signed-half-way"})
        self.assertEqual({k: round(v * Q32) for k, v in receipt["action_values"].items()},
                         {"TIE1": 0, "TIE3": 2, "TIE-1": 0, "TIE-3": -2, "ABSTAIN": 0})
        self.assertEqual([q32(i / (2 * Q32)) for i in (1, 3, -1, -3)], [0, 2, 0, -2])
        values, count = recursive_reference([(q32(-0.2), Q32), (q32(0.9), Q32)])
        self.assertEqual(values, [q32(-0.2) + q32(0.9), q32(0.9), 0])
        self.assertEqual(count, 0)

    def test_native_forecast_uses_original_values_and_explicit_stop_mapping(self):
        parameters, obs = true_parameters(), observation()
        answer = select_action(parameters, obs, "endogenous", native=self.native)
        receipt = answer["native_receipt"]
        self.assertEqual(receipt["native_candidate_to_action"], {"abstain": "STOP", "wait": "WAIT", "repair": "REPAIR"})
        self.assertEqual(receipt["snapshot"]["plan_policy"] if "plan_policy" in receipt["snapshot"] else
                         receipt["snapshot"]["profile"]["plan_policy"], "WAIT_AFTER_CURRENT")
        self.assertFalse(receipt["snapshot"]["bias_is_reward"])
        for name, row in answer["values"]["actions"].items():
            self.assertAlmostEqual(receipt["action_values"][name], row["value"], delta=5 / Q32)

    def test_profile_clock_model_checkpoint_and_source_mismatches_fail(self):
        parameters, obs = true_parameters(), observation()
        forecast = action_values(parameters, obs)
        for context in ({"recursive_profile": "unregistered-entropic"}, {"horizon": 0.5},
                        {"model_digest": "1" * 64}, {"task_checkpoint_digest": "0" * 64}):
            with self.subTest(context=context), self.assertRaises(ValueError):
                self.native.evaluate_forecast(parameters, obs, forecast, policy="endogenous", bias=0, context=context)
        invalid = deepcopy(forecast)
        invalid["profile"]["running_rate"] = 0.7
        with self.assertRaises(ValueError):
            self.native.evaluate_forecast(parameters, obs, invalid, policy="endogenous", bias=0)
        with self.assertRaises(ValueError):
            NativeNduPort(self.manifest, expected_binary_sha256="0" * 64)

    def test_native_realized_return_uses_actual_followup_and_rejects_splicing(self):
        task = MaintenanceTask(scenarios(837711, 1, "diagnostic")[0])
        initial = task.observation()
        checkpoint = task.checkpoint()["sha256"]
        for action in ("repair", "wait", "wait", "wait"):
            task.step(action if action in task.observation()["legal_actions"] else "wait")
        receipt = self.native.evaluate_realized(true_parameters(), initial, task.ledger,
                                                context={"task_checkpoint_digest": checkpoint})
        self.assertAlmostEqual(receipt["realized_return"], task.total_reward)
        self.assertAlmostEqual(receipt["realized_native_return"], task.total_reward, delta=5 / Q32)
        malformed = deepcopy(task.ledger)
        malformed[1]["observation"]["level"] += 0.01
        with self.assertRaises(ValueError):
            self.native.evaluate_realized(true_parameters(), initial, malformed)
        malformed = deepcopy(task.ledger)
        malformed[0]["action_cost"] *= 2
        with self.assertRaises(ValueError):
            self.native.evaluate_realized(true_parameters(), initial, malformed)
        stopped = MaintenanceTask(scenarios(837712, 1, "diagnostic")[0])
        start = stopped.observation()
        stopped.step("stop")
        self.assertEqual(self.native.evaluate_realized(true_parameters(), start, stopped.ledger)["realized_native_return"], 0.0)
        stopped.ledger[0]["done"] = False
        with self.assertRaises(ValueError):
            self.native.evaluate_realized(true_parameters(), start, stopped.ledger)


if __name__ == "__main__":
    unittest.main()

"""Behavioral controls for learning, calibration and a frozen small matrix."""

from dataclasses import replace
from itertools import product
import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import torch
from . import finite as f
from .evaluation import (
    BASELINES,
    baseline,
    rollout,
    run_experiment,
    control_factorial,
    draw,
    sampled_transition,
    tune_fixed,
)
from .learning import (
    calibrate,
    fit_candidate,
    load_candidate,
    save_candidate,
    state_key,
)


class LearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.model = f.Model(max_steps=4, deadline=5)
        cls.roots = (f.State(budget=18), f.State(text_grade=1, budget=24))
        cls.candidate = fit_candidate(cls.roots, cls.model, seed=17, epochs=80)
        cls.pairs = [
            (s, a)
            for s in sorted(f.reachable_states(cls.roots, cls.model), key=state_key)
            for a in f.legal_actions(s, cls.model)
            if f.uncertain(s, a, cls.model)
        ]
        cls.groups = {
            f"cal-{i}": random.Random(i).sample(cls.pairs, min(8, len(cls.pairs)))
            for i in range(12)
        }

    def test_training_updates_only_uncertain_support(self):
        receipt = self.candidate.receipt
        self.assertLess(receipt["final_mse"], receipt["initial_mse"])
        self.assertEqual(receipt["supported_pairs"], len(self.pairs))
        self.assertEqual(receipt["terminal_training_targets"], 0)
        for state, action in self.pairs:
            self.assertNotIn(action.verb, {"STOP", "SUBMIT"})
            self.assertIn((state_key(state), action.name), self.candidate.support)

    def test_fixed_features_and_reset_execution_do_not_mutate(self):
        fixed = fit_candidate(
            self.roots, self.model, seed=19, trainable_features=False, epochs=20
        )
        torch.testing.assert_close(
            fixed.initial[0], fixed.network.hidden.weight, rtol=0, atol=0
        )
        state, action = self.pairs[0]
        before = {k: v.clone() for k, v in self.candidate.network.state_dict().items()}
        self.candidate.predict(state, action, "reset")
        for key, value in before.items():
            torch.testing.assert_close(
                value, self.candidate.network.state_dict()[key], rtol=0, atol=0
            )
        self.assertEqual(
            fixed.predict(state, action, "trained"),
            fixed.predict(state, action, "reset"),
        )

    def test_calibration_source_and_small_sample_boundary(self):
        with self.assertRaisesRegex(ValueError, "disjoint"):
            calibrate(
                self.candidate, self.model, self.groups, training_sources=("cal-0",)
            )
        with self.assertRaisesRegex(ValueError, "model differs"):
            calibrate(self.candidate, replace(self.model, risk=0.3), self.groups)
        result = calibrate(self.candidate, self.model, {"one": self.pairs[:1]})
        self.assertIsNone(result["radius"])
        result = calibrate(self.candidate, self.model, self.groups)
        self.assertEqual(result["rank"], 12)
        self.assertEqual(result["radius"], max(result["group_max_residuals"]))

    def test_pinned_cold_checkpoint_and_changed_bytes(self):
        calibrate(self.candidate, self.model, self.groups)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.json"
            receipt = save_candidate(self.candidate, path)
            loaded = load_candidate(path, receipt["sha256"], self.model)
            for state, action in self.pairs[:5]:
                for mode in ("trained", "reset"):
                    self.assertEqual(
                        loaded.predict(state, action, mode),
                        self.candidate.predict(state, action, mode),
                    )
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "pin differs"):
                load_candidate(path, receipt["sha256"], self.model)

    def test_cold_load_rejects_inconsistent_calibration_and_feature_profile(self):
        calibrate(self.candidate, self.model, self.groups)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.json"
            save_candidate(self.candidate, path)
            original = json.loads(path.read_bytes())
            record = original["calibrations"]["trained"]
            changes = (
                ("radius", -0.1),
                ("radius", False),
                ("radius", float("nan")),
                ("radius", float("inf")),
                ("radius", record["radius"] + 1),
                ("radius", None),
                ("groups", record["groups"] + 1),
                ("groups", True),
                ("rank", record["rank"] - 1),
                ("rank", True),
                ("pairs", record["groups"] - 1),
                ("source_ids", [record["source_ids"][0]] * record["groups"]),
                ("group_max_residuals", [False] * record["groups"]),
                ("residual_cdf", [[0.0, 0.0]] * record["groups"]),
                ("mode", "reset"),
                ("alpha", float("nan")),
                ("conditional_coverage_guarantee", True),
            )
            for field, value in changes:
                with self.subTest(field=field, value=value):
                    modified = json.loads(json.dumps(original))
                    modified["calibrations"]["trained"][field] = value
                    raw = json.dumps(modified).encode()
                    path.write_bytes(raw)
                    with self.assertRaises(ValueError):
                        load_candidate(
                            path, hashlib.sha256(raw).hexdigest(), self.model
                        )
            modified = json.loads(json.dumps(original))
            for row in modified["weights"]["hidden.weight"]:
                row.append(0.0)
            for row in modified["initial"][0]:
                row.append(0.0)
            raw = json.dumps(modified).encode()
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "network shape"):
                load_candidate(path, hashlib.sha256(raw).hexdigest(), self.model)
            # A genuine n+1 small-sample refusal remains a valid checkpoint.
            calibrate(self.candidate, self.model, {"one": self.pairs[:1]}, mode="reset")
            small_path = Path(temp) / "small.json"
            receipt = save_candidate(self.candidate, small_path)
            loaded = load_candidate(small_path, receipt["sha256"], self.model)
            self.assertIsNone(loaded.calibrations["reset"]["radius"])
            _, observation = loaded.choose(self.roots[0], self.model, mode="reset")
            self.assertTrue(observation["fallback"])

    def test_delayed_read_keeps_the_same_pending_packet(self):
        ready = f.State(budget=24, time=1, steps=1, ready_at=1)
        delayed = replace(ready, budget=20, time=2, steps=2)
        for seed in (3, 5, 7, 11, 19):
            with self.subTest(seed=seed):
                early, _ = sampled_transition(ready, f.READ, self.model, seed)
                later, _ = sampled_transition(delayed, f.READ, self.model, seed)
                self.assertEqual(early.signal, later.signal)
                self.assertEqual(draw(seed, ready, f.READ), draw(seed, delayed, f.READ))
                self.assertNotEqual(
                    draw(seed, ready, f.REPAIR_IMAGE),
                    draw(seed, delayed, f.REPAIR_IMAGE),
                )
                self.assertNotEqual(
                    draw(seed, ready, f.READ),
                    draw(seed, replace(ready, ready_at=0), f.READ),
                )

    def test_unknown_support_rejects_uncertain_continuation(self):
        calibrate(self.candidate, self.model, self.groups)
        unsupported = replace(self.candidate, support=frozenset())
        state = self.pairs[0][0]
        action, receipt = unsupported.choose(state, self.model)
        self.assertTrue(receipt["fallback"])
        self.assertFalse(f.uncertain(state, action, self.model))

    def test_online_candidate_does_not_read_teacher_scores(self):
        calibrate(self.candidate, self.model, self.groups)
        with patch.object(
            f, "exact_scores", side_effect=AssertionError("online teacher read")
        ):
            action, _ = self.candidate.choose(self.roots[0], self.model)
        self.assertIn(action, f.legal_actions(self.roots[0], self.model))

    def test_finite_fees_and_prophet_coupling_bound(self):
        for seed in (3, 5, 7):
            oracle = rollout(
                self.roots[0],
                self.model,
                baseline("privileged-oracle", self.model, seed),
                seed,
            )
            for method in BASELINES:
                result = rollout(
                    self.roots[0], self.model, baseline(method, self.model, seed), seed
                )
                self.assertEqual(
                    result["credits"], sum(result["cost_categories"].values())
                )
                self.assertEqual(
                    result["credits"], sum(row["credits"] for row in result["steps"])
                )
                self.assertLessEqual(
                    result["net_utility"], oracle["net_utility"] + 1e-12
                )

    def test_small_matrix_freezes_before_future_and_retains_no_update(self):
        with tempfile.TemporaryDirectory() as temp:
            report = run_experiment(
                self.roots[:1],
                f.Model(max_steps=3, deadline=4),
                epochs=4,
                calibration_sources=10,
                future_sources=8,
                output=Path(temp) / "run",
            )
            self.assertEqual(report["decision"], "no-update")
            self.assertFalse(report["production_adoption"])
            self.assertEqual(len(report["fits"]), 6)
            self.assertEqual(
                report["summaries"]["dynamic/trainable/trained"]["episodes"], 24
            )
            self.assertEqual(len(report["coverage"]), 12)
            self.assertEqual(len(report["freeze"]["candidate_parameter_sha256"]), 6)
            self.assertEqual(report["fixed_policy_tuning"]["schedule_attempts"], 40)
            self.assertIn("tuned-fixed", report["paired_contrasts"])
            self.assertEqual(
                report["control_factorial"]["values"]["A"],
                report["control_factorial"]["values"]["C"],
            )
            self.assertTrue(
                report["registration"]["future_outcomes_materialized_after_freeze"]
            )
            self.assertNotIn("future_draws_frozen_before_fit", report["registration"])
            json.dumps(report, allow_nan=False)
        with self.assertRaisesRegex(ValueError, "overlap"):
            run_experiment(self.roots, self.model, seeds=(11, 29, 100000), epochs=1)

    def test_control_factorial_distinguishes_fixed_execution_from_hidden_reset(self):
        fixed = [{"net_utility": 1.0}, {"net_utility": 3.0}]
        left = [[{"net_utility": 2.0 + i}, {"net_utility": 4.0 + i}] for i in range(3)]
        right = [[{"net_utility": 4.0 + i}, {"net_utility": 6.0 + i}] for i in range(3)]
        matrix = control_factorial(
            {
                "static-quota": fixed,
                "dynamic/fixed/trained": left,
                "dynamic/trainable/trained": right,
            },
            (11, 29, 47),
        )
        self.assertEqual(matrix["values"]["A"], matrix["values"]["C"])
        self.assertEqual(
            matrix["contrasts"]["training_difference/fixed_execution"]["mean"], 0.0
        )
        self.assertEqual(matrix["contrasts"]["interaction"]["mean"], 2.0)
        self.assertEqual(
            matrix["contrasts"]["dynamic_minus_fixed/fixed_hidden"]["mean"], 2.0
        )
        self.assertEqual(matrix["additional_fits"], 0)
        self.assertFalse(matrix["duplicated_matrix_values_are_new_executions"])

    def test_tuned_fixed_uses_registered_calibration_grid_and_freezes_selection(self):
        grid = [
            list(s)
            for n in range(4)
            for s in product(("text", "image", "both"), repeat=n)
        ]
        tuning = tune_fixed(self.roots, self.model, (100001, 100002, 100003), grid)
        self.assertEqual(tuning["schedule_attempts"], 40)
        self.assertEqual(tuning["calibration_episodes"], 120)
        selected = tuning["trials"][tuning["selected_index"]]
        self.assertEqual(
            selected["mean_net_utility"],
            max(t["mean_net_utility"] for t in tuning["trials"]),
        )
        self.assertTrue(
            all(r["seed"] < 200000 for t in tuning["trials"] for r in t["samples"])
        )
        with patch(
            "scripts.ndu_bimodal.evaluation.tune_fixed",
            side_effect=AssertionError("future retuning"),
        ):
            frozen = baseline(
                "tuned-fixed",
                self.model,
                200001,
                fixed_schedule=tuning["selected_schedule"],
            )
            result = rollout(self.roots[0], self.model, frozen, 200001)
        self.assertLessEqual(result["credits"], self.roots[0].budget)


if __name__ == "__main__":
    unittest.main()

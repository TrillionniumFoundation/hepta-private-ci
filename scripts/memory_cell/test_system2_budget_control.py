"""Budget/return mechanics and full runner with explicitly synthetic fixture ports."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import torch

from system2_ablation import model_digest
from system2_budget_control import (
    ARMS,
    LIMITS,
    choose,
    collect_training,
    episode,
    fit,
    make_head,
    state_features,
)
from system2_budget_trial import aggregate, calibration, cohort, run
from system2_verified_search import ExactLabels, digest, verify

PROOF = ["n0", "n1", "+", "n2", "+", "n3", "*"]


def simulated_search(
    numbers, goal, arm, budget, critic, *, terminal_policy, successor_limit
):
    """A bounded fixed-policy fixture, not an observation of the native search."""
    found = (
        tuple(numbers) == (1, 2, 3, 4)
        and arm == "value_search"
        and successor_limit > 128
    )
    return dict(
        found=found,
        proof=PROOF if found else None,
        budget_exhausted=not found,
        costs=dict(
            popped_states=1,
            generated_successors=100 if found else successor_limit,
            critic_examples=0,
            verifier_calls=int(found),
        ),
        seconds=0.0,
    )


class Fixed(torch.nn.Module):
    def __init__(self, logits):
        super().__init__()
        self.logits = logits

    def forward(self, x):
        return torch.tensor([self.logits], dtype=x.dtype).repeat(len(x), 1)


class BudgetControlTests(unittest.TestCase):
    def test_features_bind_observed_budget_and_question(self):
        first = state_features((1, 2, 3, 4), 256, 64)
        self.assertEqual(len(first), 15)
        self.assertNotEqual(first, state_features((1, 2, 3, 4), 1024, 256))
        self.assertNotEqual(first, state_features((1, 1, 1, 1), 256, 64))
        for total, spent in ((True, 0), (256, True), (256, 256), (0, 0)):
            with self.assertRaises(ValueError):
                state_features((1, 2, 3, 4), total, spent)

    def test_labels_are_fixed_policy_rollouts_not_reachability(self):
        with (
            patch("system2_budget_control.search", side_effect=simulated_search),
            patch.object(
                ExactLabels, "_solve", side_effect=AssertionError("oracle called")
            ),
        ):
            x, y, rows = collect_training([(1, 2, 3, 4), (1, 1, 1, 1)], None)
        self.assertEqual(tuple(x.shape), (4, 15))
        self.assertEqual(tuple(y.shape), (4, 4))
        self.assertEqual(
            y[:, :2].tolist(), [[0.0, 1.0], [0.0, 1.0], [0.0, 0.0], [0.0, 0.0]]
        )
        self.assertEqual(sum(len(r["executions"]) for r in rows), 12)
        self.assertAlmostEqual(float(y[0, 3]), 100 / 192, places=6)

    def test_successful_probe_does_not_invent_tail_targets(self):
        def success(*args, **kwargs):
            result = simulated_search(*args, **kwargs)
            result.update(found=True, proof=PROOF)
            result["costs"]["generated_successors"] = 1
            return result

        with patch("system2_budget_control.search", side_effect=success) as calls:
            with self.assertRaisesRegex(ValueError, "no observed"):
                collect_training([(1, 2, 3, 4)], None)
        self.assertEqual(calls.call_count, 2)

    def test_real_fit_and_shuffle_preserve_inputs_initialization_and_steps(self):
        with patch("system2_budget_control.search", side_effect=simulated_search):
            x, y, _ = collect_training([(1, 2, 3, 4), (1, 1, 1, 1)], None)
        before = (x.clone(), y.clone())
        a, ra = fit(x, y, steps=4)
        b, rb = fit(x, y, shuffled=True, steps=4)
        self.assertEqual(ra["before"], rb["before"])
        self.assertEqual((ra["steps"], ra["examples"]), (rb["steps"], rb["examples"]))
        self.assertNotEqual(ra["before"], ra["after"])
        self.assertEqual(sum(p.numel() for p in a.parameters()), 324)
        self.assertFalse(any(p.requires_grad for m in (a, b) for p in m.parameters()))
        self.assertTrue(torch.equal(x, before[0]) and torch.equal(y, before[1]))
        self.assertEqual(sorted(rb["target_permutation"]), list(range(len(x))))

    def test_cost_changes_choice_without_changing_probability(self):
        model = Fixed([0.2, 0.04, 20.0, -20.0])
        context = state_features((1, 2, 3, 4), 1024, 256)
        aware = choose(model, context, 768)
        blind = choose(model, context, 768, cost_aware=False)
        self.assertEqual(aware["probability"], blind["probability"])
        self.assertEqual(aware["action"], "value_search")
        self.assertEqual(blind["action"], "heuristic_search")
        self.assertEqual(
            choose(Fixed([-20.0, -20.0, 20.0, 20.0]), context, 768)["action"], "stop"
        )

    def test_probe_and_tail_both_charge_against_one_total(self):
        with patch("system2_budget_control.search", side_effect=simulated_search):
            for total in LIMITS:
                row = episode((1, 2, 3, 4), total, "probe_heuristic", None)
                self.assertEqual(row["costs"]["generated_successors"], total)
                self.assertEqual(
                    [e["successor_limit"] for e in row["executions"]],
                    [total // 4, total - total // 4],
                )
                self.assertFalse(row["certified_impossible"])
                self.assertLess(row["utility"], 0)

    def test_stop_keeps_sunk_probe_cost(self):
        with patch("system2_budget_control.search", side_effect=simulated_search):
            row = episode((1, 2, 3, 4), 256, "probe_stop", None)
        self.assertEqual(len(row["executions"]), 1)
        self.assertEqual(row["decision"]["action"], "stop")
        self.assertFalse(row["found"])
        self.assertLess(row["utility"], 0)

    def test_decision_persisted_before_chosen_outcome(self):
        events = []

        def observed(*args, **kwargs):
            events.append("child")
            return simulated_search(*args, **kwargs)

        with patch("system2_budget_control.search", side_effect=observed):
            row = episode(
                (1, 2, 3, 4),
                256,
                "probe_value",
                None,
                decision_sink=lambda _: events.append("decision"),
            )
        self.assertEqual(events, ["child", "decision", "child"])
        self.assertTrue(verify(row["numbers"], 24, row["proof"]))

    def test_bad_proof_is_execution_failure_not_positive_training_label(self):
        def forged(*args, **kwargs):
            result = simulated_search(*args, **kwargs)
            result.update(found=True, proof=["n0"] * 7)
            return result

        with patch("system2_budget_control.search", side_effect=forged):
            row = episode((1, 2, 3, 4), 256, "direct_value", None)
            with self.assertRaises(ValueError):
                collect_training([(1, 2, 3, 4)], None)
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["utility"])

    def test_failed_tail_preserves_probe_and_incomplete_cost_flag(self):
        def broken(*args, **kwargs):
            if args[2] == "value_search":
                raise RuntimeError("fixture tail failure")
            return simulated_search(*args, **kwargs)

        with patch("system2_budget_control.search", side_effect=broken):
            row = episode((1, 2, 3, 4), 256, "probe_value", None)
        self.assertEqual(row["costs"]["generated_successors"], 64)
        self.assertEqual(
            [e["status"] for e in row["executions"]], ["completed", "failed"]
        )
        self.assertTrue(row["costs_may_be_incomplete"])
        self.assertIsNone(row["utility"])

    def test_controller_rejects_unfrozen_or_nonfinite_models(self):
        context = state_features((1, 2, 3, 4), 256, 64)
        for model in (make_head(), Fixed([float("nan")] * 4)):
            with self.assertRaises(ValueError):
                choose(model, context, 192)

    def test_all_arms_use_runtime_proof_verifier_without_oracle(self):
        head = make_head().eval().requires_grad_(False)
        before = model_digest(head)
        with (
            patch("system2_budget_control.search", side_effect=simulated_search),
            patch.object(
                ExactLabels, "_solve", side_effect=AssertionError("runtime oracle")
            ),
        ):
            for arm in ARMS:
                result = episode((1, 2, 3, 4), 256, arm, None, head)
                self.assertEqual(result["status"], "completed")
                self.assertLessEqual(result["costs"]["generated_successors"], 256)
        self.assertEqual(before, model_digest(head))

    def test_unchosen_actions_get_posthoc_calibration_targets(self):
        head = Fixed([20.0, -20.0, 0.0, 0.0])
        with patch("system2_budget_control.search", side_effect=simulated_search):
            rows = [
                episode((1, 2, 3, 4), 256, a, None, head)
                for a in ("learned", "probe_heuristic", "probe_value")
            ]
        for row in rows:
            row["query_id"] = "fixture"
        report = calibration(rows)["learned"]
        self.assertEqual(report["observed_action_targets"], 2)
        self.assertGreater(report["brier_score"], 0.9)
        self.assertFalse(report["calibration_established"])

    def test_full_runner_freezes_and_seals_before_eval_oracle(self):
        # Fixture ports exercise the actual runner; no native result is claimed.
        child = make_head().eval().requires_grad_(False)
        real_label = ExactLabels._solve
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "trial"

            def guarded(labeler, *args):
                self.assertTrue((output / "prediction-seal.json").is_file())
                self.assertTrue((output / "freeze.json").is_file())
                return real_label(labeler, *args)

            groups = {"previous_tasks": [(1, 1, 1, 1)], "next_48_tasks": [(2, 2, 2, 2)]}
            with (
                patch(
                    "system2_budget_trial.read_parent",
                    return_value=({}, {"value": child}, [], {"fixture": True}),
                ),
                patch(
                    "system2_budget_trial.cohort", return_value=([(1, 2, 3, 4)], groups)
                ),
                patch("system2_budget_control.search", side_effect=simulated_search),
                patch.object(ExactLabels, "_solve", guarded),
            ):
                result = run(Path("fixture.zip"), output, source_commit="a" * 40)
            self.assertEqual(
                (result["planned"], result["recorded"], result["failed"]), (32, 32, 0)
            )
            self.assertEqual(
                len((output / "predictions.jsonl").read_text().splitlines()), 32
            )
            self.assertFalse(
                json.loads((output / "summary.json").read_text())["production_accepted"]
            )

    def test_failed_episode_cannot_disappear_from_utility_denominator(self):
        rows = [
            dict(
                status="completed",
                utility=0.5,
                verified_solution=True,
                solvable=True,
                seconds=1.0,
                costs={
                    k: 0
                    for k in (
                        "popped_states",
                        "generated_successors",
                        "critic_examples",
                        "verifier_calls",
                    )
                },
                controller_calls=0,
                budget=256,
            )
        ]
        rows.append(
            rows[0] | dict(status="failed", utility=None, verified_solution=False)
        )
        report = aggregate(rows)
        self.assertEqual((report["planned"], report["failed"]), (2, 1))
        self.assertLess(report["utility_bounds"][0], 0.25)
        self.assertEqual(report["utility_bounds"][1], 0.75)

    def test_new_multisets_exclude_previous_training_and_both_eval_slices(self):
        import itertools

        catalogue = sorted(
            itertools.combinations_with_replacement(range(1, 10), 4),
            key=lambda n: digest(("verified-search-v1", n)),
        )
        train, groups = cohort(
            dict(training=catalogue[:12], evaluation=catalogue[12:36])
        )
        self.assertEqual(groups["next_48_tasks"], catalogue[60:108])
        self.assertFalse(set(train) & set(groups["next_48_tasks"]))
        self.assertFalse(set(groups["previous_tasks"]) & set(groups["next_48_tasks"]))


if __name__ == "__main__":
    unittest.main()

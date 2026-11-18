"""Behavioral checks for the bounded, explicitly simulated control contract."""

from dataclasses import asdict, replace
import math
import unittest
from unittest.mock import patch

from scripts.ndu_bimodal import finite as f


def exhaustive_value(state, model):
    """Independent un-memoized tree backup with direct exponential arithmetic."""
    values = []
    for action in f.legal_actions(state, model):
        if action in (f.STOP, f.SUBMIT):
            values.append(f.terminal_value(state, model, action))
            continue
        outcomes = [
            (
                p,
                exhaustive_value(next_state, model)
                - model.utility_per_credit * cost.total,
            )
            for p, next_state, cost in model.transitions(state, action)
        ]
        if model.risk:
            floor = min(value for _, value in outcomes)
            value = (
                floor
                - math.log(
                    sum(
                        p * math.exp(-model.risk * (value - floor))
                        for p, value in outcomes
                    )
                )
                / model.risk
            )
        else:
            value = sum(p * value for p, value in outcomes)
        values.append(value)
    return max(values)


class FiniteContractTests(unittest.TestCase):
    def test_memoized_dp_matches_independent_exhaustive_tree(self):
        for risk in (0.0, 0.7, 30.0):
            model = f.Model(deadline=3, max_steps=3, risk=risk)
            for state in (
                f.State(budget=18),
                f.State(text_grade=1, image_grade=0, budget=21),
                f.State(text_grade=0, image_grade=1, budget=24, ready_at=0),
            ):
                with self.subTest(risk=risk, state=state):
                    self.assertAlmostEqual(
                        f.exact_value(state, model),
                        exhaustive_value(state, model),
                        places=12,
                    )

    def test_one_repair_closed_form_and_risk_penalty(self):
        state = f.State(text_grade=1, image_grade=0, budget=18, time=4, steps=4)
        neutral = f.Model(risk=0)
        high = replace(neutral, risk=40)
        # The last repair costs four credits. Success permits complete SUBMIT
        # at 0.46 + 0.08 - 0.05; failure leaves a 0.20 draft.
        expected = 0.5 * (0.49 - 0.04) + 0.5 * (0.20 - 0.04)
        self.assertAlmostEqual(f.exact_scores(state, neutral)[f.REPAIR_IMAGE], expected)
        self.assertLess(
            f.exact_scores(state, high)[f.REPAIR_IMAGE],
            f.exact_scores(state, neutral)[f.REPAIR_IMAGE],
        )
        self.assertEqual(
            f.terminal_value(state, neutral), f.terminal_value(state, high)
        )

    def test_wait_then_read_obeys_arrival_and_cannot_repeat(self):
        model, initial = f.Model(), f.State(budget=32, ready_at=2)
        self.assertNotIn(f.READ, f.legal_actions(initial, model))
        with self.assertRaises(ValueError):
            model.transitions(initial, f.READ)
        _, ready, wait_cost = model.transitions(initial, f.WAIT)[0]
        self.assertEqual(
            ready,
            replace(initial, budget=initial.budget - wait_cost.total, time=2, steps=1),
        )
        self.assertNotIn(f.WAIT, f.legal_actions(ready, model))
        rows = model.transitions(ready, f.READ)
        self.assertAlmostEqual(sum(p for p, _, _ in rows), 1)
        for _, observed, _ in rows:
            self.assertFalse(observed.requested)
            self.assertNotIn(f.READ, f.legal_actions(observed, model))
            self.assertNotIn(f.WAIT, f.legal_actions(observed, model))
        no_pending = replace(initial, requested=False)
        self.assertNotIn(f.WAIT, f.legal_actions(no_pending, model))

    def test_uncertainty_tracks_future_opportunity_not_only_next_branch(self):
        model, state = f.Model(), f.State()
        self.assertEqual(len(model.transitions(state, f.WAIT)), 1)
        self.assertTrue(f.uncertain(state, f.WAIT, model))
        with self.assertRaises(ValueError):
            f.known_score(state, f.WAIT, model)
        late = replace(state, time=4, steps=4)
        # READ has two signals, but no room to use either after it.
        self.assertEqual(len(model.transitions(late, f.READ)), 2)
        self.assertFalse(f.uncertain(late, f.READ, model))
        with patch.object(
            f, "exact_scores", side_effect=AssertionError("teacher leaked")
        ):
            self.assertAlmostEqual(
                f.known_score(late, f.READ, model),
                f.terminal_value(late, model)
                - model.utility_per_credit * model.cost(late, f.READ).total,
            )
        complete = replace(state, text_grade=2, image_grade=2)
        self.assertFalse(f.uncertain(complete, f.WAIT, model))
        for action in (f.STOP, f.SUBMIT):
            self.assertFalse(f.uncertain(complete, action, model))
            self.assertEqual(
                f.known_score(complete, action, model),
                f.terminal_value(complete, model, action),
            )

    def test_every_reachable_edge_pays_once_and_reserves_termination(self):
        model = f.Model(deadline=4, max_steps=4)
        states = f.reachable_states(
            [f.State(budget=24), f.State(text_grade=1, image_grade=1, budget=30)],
            model,
        )
        totals = {name: 0 for name in asdict(f.Cost())}
        self.assertGreater(len(states), 20)
        for state in states:
            self.assertIn(f.STOP, f.legal_actions(state, model))
            for action in f.legal_actions(state, model):
                cost = model.cost(state, action)
                for name, value in asdict(cost).items():
                    self.assertGreaterEqual(value, 0)
                    totals[name] += value
                if action in (f.STOP, f.SUBMIT):
                    continue
                rows = model.transitions(state, action)
                self.assertAlmostEqual(sum(p for p, _, _ in rows), 1)
                for p, successor, paid in rows:
                    self.assertGreater(p, 0)
                    self.assertEqual(paid, cost)
                    self.assertEqual(successor.budget, state.budget - cost.total)
                    self.assertEqual(
                        successor.time, state.time + model.duration(state, action)
                    )
                    self.assertEqual(successor.steps, state.steps + 1)
                    self.assertGreaterEqual(successor.budget, 5)
                    self.assertLess(successor.time, model.deadline)
                    self.assertLess(successor.steps, model.max_steps)
        self.assertTrue(all(value > 0 for value in totals.values()), totals)
        self.assertEqual(f.legal_actions(f.State(budget=0), model), (f.STOP,))

    def test_joint_repair_marginals_and_modality_allocation(self):
        state = f.State(budget=32, signal=0, requested=False)
        model = f.Model()
        rows = model.transitions(state, f.REPAIR_BOTH)
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(sum(p for p, _, _ in rows), 1)
        for modality in ("text", "image"):
            actual = sum(
                p
                for p, successor, _ in rows
                if getattr(successor, modality + "_grade")
                > getattr(state, modality + "_grade")
            )
            self.assertAlmostEqual(actual, model.success(state, modality))
        self.assertEqual(sum(f.REPAIR_BOTH.shares), 1)
        self.assertGreater(model.cost(state, f.REPAIR_BOTH).coordination, 0)
        self.assertNotIn(
            f.REPAIR_TEXT, f.legal_actions(replace(state, text_grade=2), model)
        )

    def test_rejects_unknown_and_nonfinite_contract_inputs(self):
        for change in (
            {"text_grade": True},
            {"image_grade": 3},
            {"budget": -1},
            {"signal": 2},
            {"signal": 0},
            {"ready_at": 11},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                f.State(**change)
        for change in (
            {"risk": float("nan")},
            {"unread_success": 1.1},
            {"deadline": 0},
            {"max_steps": True},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                f.Model(**change)
        with self.assertRaises(ValueError):
            f.Cost(reuse=-1)
        with self.assertRaises(ValueError):
            f.legal_actions(f.State(time=7), f.Model())
        with self.assertRaises(ValueError):
            f.reachable_states([f.State()], f.Model(), limit=1)
        with self.assertRaises(ValueError):
            f.Action("READ", "audio")

    def test_features_have_public_causal_state_and_no_future_draw(self):
        root = f.State(budget=32)
        changed = replace(root, ready_at=2)
        a = f.numeric_features(root, f.REPAIR_TEXT)
        b = f.numeric_features(changed, f.REPAIR_TEXT)
        self.assertEqual(len(a), 16)
        self.assertNotEqual(a, b)
        self.assertTrue(all(math.isfinite(value) for value in a))
        self.assertNotEqual(a, f.numeric_features(root, f.REPAIR_IMAGE))
        self.assertEqual(
            a, f.numeric_features(replace(root), f.Action("REPAIR", "text"))
        )


if __name__ == "__main__":
    unittest.main()

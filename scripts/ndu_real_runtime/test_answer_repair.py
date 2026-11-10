"""Manufactured contracts; these tests are not evidence of native efficacy."""

from copy import deepcopy
import unittest

import numpy as np

from . import answer_repair as repair


def plan():
    sources = [f"fit{i}" for i in range(40)]
    return dict(
        schema="ndu.ctrl.answer-repair-plan.v1",
        original_fit_sources=sources,
        inner_train_sources=sources[:32],
        inner_tune_sources=sources[32:],
        future_sources=[f"future{i}" for i in range(37)],
        excluded_sources=[f"excluded{i}" for i in range(20)],
        **{
            k: "a" * 64
            for k in (
                "fit_records_sha256",
                "base_weights_sha256",
                "source_inventory_sha256",
                "normalizer_sha256",
            )
        },
        trials=[dict(learning_rate=0.1, l2=0.0), dict(learning_rate=0.03, l2=0.1)],
        steps=12,
    )


def row(source):
    return dict(
        source_id=source,
        observation_id=source + "/state",
        role="train",
        encoded=[[0.0] * 24, [1.0] + [0.0] * 23, [1.0] + [0.0] * 23],
        positives=[1, 2],
    )


class AnswerRepairTests(unittest.TestCase):
    def test_marginal_duplicate_positives_and_unchanged_bias(self):
        p = plan()
        rows = [row(s) for s in p["original_fit_sources"]]
        initial = [-0.1] + [0.0] * 23
        head = repair.fit(rows, p, initial, 17.0)
        self.assertEqual(head["unchanged_shared_bias"], 17.0)
        self.assertEqual(len(head["trials"]), 2)
        self.assertEqual(head["selection"], "NoUpdate")
        self.assertGreater(head["weights"][0], initial[0])
        self.assertLess(head["fitting"]["nll"], repair.measure(rows, initial)["nll"])
        self.assertEqual(repair.select(head, rows[0]["encoded"]), 1)
        future = [row(s) for s in p["future_sources"]]
        frozen = deepcopy(head)
        self.assertEqual(repair.evaluate(head, future, p)["quality_gain"], 1.0)
        self.assertEqual(head, frozen)

    def test_duplicate_states_do_not_change_source_weight_or_conflicting_targets(self):
        p = plan()
        rows = [row(s) for s in p["original_fit_sources"]]
        duplicate = dict(rows[0], observation_id="repeat")
        self.assertEqual(
            repair.fit(rows, p, [0.0] * 24, 0.0),
            repair.fit(rows + [duplicate] * 9, p, [0.0] * 24, 0.0),
        )
        duplicate["positives"] = [0]
        with self.assertRaisesRegex(ValueError, "conflicting labels"):
            repair.validate_rows(rows + [duplicate], p["original_fit_sources"])

    def test_no_positive_candidate_is_not_an_invented_target(self):
        p = plan()
        rows = [dict(row(s), positives=[]) for s in p["original_fit_sources"]]
        self.assertIsNone(repair.measure(rows, [0.0] * 24)["nll"])
        self.assertEqual(repair.measure(rows, [0.0] * 24)["quality"], 0.0)
        with self.assertRaisesRegex(ValueError, "never invent"):
            repair.fit(rows, p, [0.0] * 24, 0.0)

    def test_source_leakage_partial_future_and_changed_plan_rejected(self):
        p = plan()
        rows = [row(s) for s in p["original_fit_sources"]]
        head = repair.fit(rows, p, [0.0] * 24, 0.0)
        with self.assertRaises(ValueError):
            repair.fit(rows + [row("future0")], p, [0.0] * 24, 0.0)
        with self.assertRaises(ValueError):
            repair.evaluate(head, [row("future0")], p)
        altered = dict(p, steps=13)
        with self.assertRaises(ValueError):
            repair.evaluate(head, [row(s) for s in p["future_sources"]], altered)
        altered = deepcopy(p)
        altered["future_sources"][0] = "fit0"
        with self.assertRaises(ValueError):
            repair.validate_plan(altered)

    def test_stable_marginal_gradient_when_positive_mass_underflows(self):
        p = plan()
        p["steps"] = 2
        rows = [row(s) for s in p["original_fit_sources"]]
        head = repair.fit(rows, p, [-1000.0] + [0.0] * 23, 0.0)
        self.assertTrue(np.isfinite(head["weights"]).all())
        self.assertTrue(np.isfinite(head["fitting"]["nll"]))

    def test_dimension_bounds_indices_pins_and_budget(self):
        for encoded in ([[0] * 23], [[float("nan")] * 24], [[1.1] * 24], []):
            with self.assertRaises(ValueError):
                repair.features(encoded)
        for change in (
            dict(steps=0),
            dict(fit_records_sha256="missing"),
            dict(trials=[dict(learning_rate=float("nan"), l2=0)]),
        ):
            with self.assertRaises(ValueError):
                repair.validate_plan(dict(plan(), **change))
        r = row("s")
        r["positives"] = [True]
        with self.assertRaises(ValueError):
            repair.validate_rows([r], {"s"})


if __name__ == "__main__":
    unittest.main()

"""Mechanism tests on declared fixtures; these are not policy-gain evidence."""

from dataclasses import replace
import unittest

from .metacontrol import ObservedContinuation, PublicControlState, fit_heads


class MetacontrolTests(unittest.TestCase):
    def state(self, feature=1.0, *, pending=False):
        return PublicControlState(
            (feature,), (0.5, 0.5), pending, 0.0, ("WRITE_TEXT", "STOP"), 10.0
        )

    def rows(self, prefix, groups=12, *, cost=0.02, selected=True, effect=True):
        result = []
        for group in range(groups):
            for feature in (-1.0, 1.0):
                result.append(
                    ObservedContinuation(
                        source_group=f"{prefix}/{group}",
                        decision_id=f"{prefix}/{group}/{feature}",
                        state=self.state(feature),
                        action="WRITE_TEXT",
                        stop_quality=0.4,
                        continuation_quality=0.6 if feature > 0 else 0.2,
                        incremental_cost=cost,
                        full_cost_observed=False,
                        selected_used=selected,
                        effect_occurred=(feature > 0) if effect else None,
                        identity_receipt_sha256="a" * 64
                        if selected is not None
                        else None,
                        effect_receipt_sha256="b" * 64 if effect else None,
                    )
                )
        return result

    def test_zero_reward_does_not_become_failed_execution(self):
        rows = self.rows("train")
        model = fit_heads(rows)
        wrong = model.predict(self.state(-1.0), "WRITE_TEXT")
        useful = model.predict(self.state(1.0), "WRITE_TEXT")
        self.assertGreater(wrong["selected_used_probability"], 0.9)
        self.assertLess(wrong["effect_occurred_probability"], 0.1)
        self.assertGreater(useful["effect_occurred_probability"], 0.9)
        self.assertLess(wrong["net_gain"], -0.2)
        self.assertGreater(useful["net_gain"], 0.17)
        self.assertEqual(
            model.identity_head["status"], "single_class_smoothed_base_rate"
        )
        self.assertEqual(model.effect_head["status"], "two_class_logistic")

    def test_missing_labels_and_missing_cost_are_not_zero_imputed(self):
        rows = self.rows("train", selected=None, effect=False)
        rows.append(
            replace(
                rows[0],
                decision_id="unknown",
                incremental_cost=None,
                source_group="unknown",
            )
        )
        model = fit_heads(rows)
        prediction = model.predict(self.state(), "WRITE_TEXT")
        self.assertIsNone(prediction["selected_used_probability"])
        self.assertIsNone(prediction["effect_occurred_probability"])
        self.assertEqual(model.receipt["known_cost_rows"], len(rows) - 1)
        model.calibrate(self.rows("calibration", selected=None, effect=False))
        future = model.diagnostics(self.rows("future", selected=None, effect=False))
        self.assertIsNone(future["selected_used"]["brier"])
        self.assertIsNone(future["effect_occurred"]["ece"])
        self.assertEqual(future["selected_used"]["missing_labels"], 24)
        self.assertFalse(future["full_cost_observed"])
        raw = json.dumps(model.snapshot()).encode()
        restored = load_heads(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(restored.identity(), model.identity())
        snapshot = model.snapshot()
        snapshot["identity"] = {**model.identity_head, "labelled_source_groups": 0}
        raw = json.dumps(snapshot).encode()
        with self.assertRaisesRegex(ValueError, "probability head field"):
            load_heads(raw, hashlib.sha256(raw).hexdigest())

    def test_observed_cost_changes_stop_comparison_without_probability_product(self):
        cheap = fit_heads(self.rows("cheap"))
        expensive = fit_heads(self.rows("expensive", cost=0.5))
        bounds = {"WRITE_TEXT": 1.0}
        self.assertEqual(
            cheap.choose(self.state(), action_cost_bounds=bounds)[0], "WRITE_TEXT"
        )
        self.assertEqual(
            expensive.choose(self.state(), action_cost_bounds=bounds)[0], "STOP"
        )
        # Value is fitted from unconditional observed net gain, not p(use)*gain.
        cheap.identity_head["constant"] = 0.01
        self.assertEqual(
            cheap.choose(self.state(), action_cost_bounds=bounds)[0], "WRITE_TEXT"
        )

    def test_unknown_or_exhausted_budget_never_uses_nonterminal_fallback(self):
        model = fit_heads(self.rows("train"))
        self.assertEqual(
            model.choose(self.state(), light_action="WRITE_TEXT")[0], "STOP"
        )
        for budget, cost, reserve in ((0.0, 1.0, 0.0), (10.0, 9.0, 2.0)):
            chosen, detail = model.choose(
                replace(self.state(), remaining_budget=budget),
                light_action="WRITE_TEXT",
                action_cost_bounds={"WRITE_TEXT": cost},
                finalization_reserve=reserve,
            )
            self.assertEqual(chosen, "STOP")
            self.assertTrue(detail["owner_predispatch_budget_check_required"])


if __name__ == "__main__":
    unittest.main()

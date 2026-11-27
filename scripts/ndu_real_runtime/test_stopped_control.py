"""Decision-relevant regression cases for conditional terminal macros."""

import copy
import math
import unittest

from .conditional_particles import ConditionalResidualBank, UnsupportedCondition
from .controllers import ControlPlan, PublicState
from .stopped_control import PROFILE_SHA256, StoppedController, TerminalCenter

BINDING = {
    "weights_sha256": "a" * 64,
    "source_sha256": "b" * 64,
    "profile_sha256": PROFILE_SHA256,
}


def record(group, action, utility, seconds=1.0, *, context=0.0):
    return {
        "public_features": [context, 0.0],
        "action": action,
        "predicted_next_features": [0.0, 0.0],
        "observed_next_features": [0.0, 0.0],
        "predicted_duration_seconds": 1.0,
        "observed_duration_seconds": seconds,
        "predicted_utility": 0.5,
        "observed_utility": utility,
        "source_group": group,
        "split": "calibration",
    }


def bank(rows, **settings):
    return ConditionalResidualBank.fit(
        rows,
        binding=BINDING,
        fit_source_groups=["fit"],
        feature_scale=[1.0, 1.0],
        **settings,
    )


class Centers:
    binding = BINDING

    def center(self, state, action):
        return TerminalCenter((0.0, 0.0), 0.5, 1.0)


def control(law, *, risk=0.0, margin=0.0, clock=lambda: 0.0):
    return StoppedController(
        Centers(),
        law,
        ControlPlan(horizon=1, particles=2, risk=risk),
        practical_margin=margin,
        clock=clock,
    )


def state(*actions, remaining=20.0, context=0.0):
    return PublicState((context, 0.0), remaining, 0, (*actions, "STOP"))


class StoppedControlTests(unittest.TestCase):
    def test_risk_changes_the_chosen_action_on_a_real_terminal_lottery(self):
        law = bank(
            [
                record("c1", "STOP", 0.55),
                record("c2", "STOP", 0.55),
                record("c1", "WRITE_TEXT", 0.2),
                record("c2", "WRITE_TEXT", 1.0),
            ]
        )
        query = state("WRITE_TEXT")
        action, receipt = control(law).choose(query)
        self.assertEqual(action, "WRITE_TEXT")
        self.assertEqual(receipt["required_execution_macro"], ["WRITE_TEXT", "STOP"])
        self.assertAlmostEqual(receipt["predicted_increment_over_stop"], 0.05)
        action, receipt = control(law, risk=4.0).choose(query)
        self.assertEqual(action, "STOP")
        self.assertTrue(
            receipt["diagnostics"]["WRITE_TEXT"]["terminal_value_risk_sensitive"]
        )

    def test_terminal_cost_can_reverse_a_quality_only_preference(self):
        law = bank(
            [
                record("c1", "STOP", 0.5),
                record("c2", "STOP", 0.5),
                record("c1", "WRITE_TEXT", 0.6, 15.0),
                record("c2", "WRITE_TEXT", 0.6, 15.0),
            ]
        )
        action, receipt = control(law).choose(state("WRITE_TEXT"))
        self.assertEqual(action, "STOP")
        self.assertAlmostEqual(receipt["predicted_values"]["STOP"], 0.49)
        self.assertAlmostEqual(receipt["predicted_values"]["WRITE_TEXT"], 0.45)

    def test_stop_has_the_same_random_cost_treatment_as_continuing(self):
        law = bank(
            [
                record("c1", "STOP", 0.6, 1.0),
                record("c2", "STOP", 0.6, 9.0),
                record("c1", "WRITE_TEXT", 0.58, 2.0),
                record("c2", "WRITE_TEXT", 0.58, 2.0),
            ]
        )
        action, receipt = control(law, risk=1.0).choose(state("WRITE_TEXT"))
        self.assertEqual(action, "WRITE_TEXT")
        self.assertTrue(receipt["diagnostics"]["STOP"]["terminal_value_risk_sensitive"])

    def test_practical_margin_preserves_stop_and_ties_preserve_stop(self):
        law = bank(
            [
                record("c1", "STOP", 0.5),
                record("c2", "STOP", 0.5),
                record("c1", "WRITE_TEXT", 0.51),
                record("c2", "WRITE_TEXT", 0.51),
            ]
        )
        self.assertEqual(
            control(law, margin=0.02).choose(state("WRITE_TEXT"))[0], "STOP"
        )

    def test_budget_rechecks_after_measured_planning_and_retains_stop(self):
        law = bank(
            [
                record("c1", "STOP", 0.2),
                record("c2", "STOP", 0.2),
                record("c1", "WRITE_TEXT", 0.9, 4.0),
                record("c2", "WRITE_TEXT", 0.9, 4.0),
            ]
        )
        clock = iter([0.0, 2.0, 2.1])
        action, receipt = control(law, clock=lambda: next(clock)).choose(
            state("WRITE_TEXT", remaining=5.0)
        )
        self.assertEqual(action, "STOP")
        self.assertEqual(receipt["over_budget_actions"], ["WRITE_TEXT"])
        self.assertEqual(receipt["planning_seconds"], 2.1)

    def test_sparse_action_is_named_and_missing_stop_is_a_refusal(self):
        law = bank([record("c1", "STOP", 0.5), record("c2", "STOP", 0.5)])
        action, receipt = control(law).choose(state("READ_ROI"))
        self.assertEqual(action, "STOP")
        self.assertIn("READ_ROI", receipt["unsupported_actions"])
        law = bank([record("c1", "READ_ROI", 0.5), record("c2", "READ_ROI", 0.5)])
        with self.assertRaises(UnsupportedCondition):
            control(law).choose(state("READ_ROI"))

    def test_state_noise_alone_is_not_terminal_value_risk(self):
        rows = [record("c1", "READ_ROI", 0.5), record("c2", "READ_ROI", 0.5)]
        rows[1]["observed_next_features"] = [1.0, 0.0]
        _, diagnostic = control(bank(rows)).scenarios(state("READ_ROI"), "READ_ROI")
        self.assertTrue(diagnostic["risk_sensitive_support"])
        self.assertFalse(diagnostic["terminal_value_risk_sensitive"])

    def test_log_domain_reconstruction_avoids_intermediate_overflow(self):
        rows = [record("c1", "READ_ROI", 0.5), record("c2", "READ_ROI", 0.5)]
        for row in rows:
            row["predicted_duration_seconds"] = 1e-320

        class Tiny(Centers):
            def center(self, state, action):
                return TerminalCenter((0.0, 0.0), 0.5, 1e-320)

        policy = StoppedController(
            Tiny(), bank(rows), ControlPlan(horizon=1, particles=2)
        )
        outcomes, _ = policy.scenarios(state("READ_ROI"), "READ_ROI")
        for _, seconds, _ in outcomes:
            self.assertTrue(math.isclose(seconds, 1.0, rel_tol=1e-12))

    def test_wrong_cost_profile_and_active_predictor_are_refused(self):
        law = bank([record("c1", "STOP", 0.5), record("c2", "STOP", 0.5)])
        wrong = copy.deepcopy(law.to_dict())
        wrong["binding"]["profile_sha256"] = "c" * 64
        from .objective import canonical_sha

        old = ConditionalResidualBank.from_dict(
            wrong,
            expected_sha256=canonical_sha(wrong),
            expected_binding=wrong["binding"],
        )
        with self.assertRaisesRegex(ValueError, "cost semantics"):
            control(old)
        predictor = Centers()
        predictor.binding = dict(BINDING, weights_sha256="d" * 64)
        with self.assertRaisesRegex(ValueError, "predictor"):
            StoppedController(predictor, law, ControlPlan(horizon=1, particles=2))

    def test_boolean_terminal_predictions_are_refused(self):
        for center in (
            TerminalCenter((False, 0.0), 0.5, 1.0),
            TerminalCenter((0.0, 0.0), True, 1.0),
            TerminalCenter((0.0, 0.0), 0.5, True),
            TerminalCenter((10**400, 0.0), 0.5, 1.0),
        ):
            with self.assertRaises(ValueError):
                center.validate(2)


if __name__ == "__main__":
    unittest.main()

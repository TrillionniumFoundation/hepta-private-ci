"""Behavior tests for complete-moment planning and honest physical-tail limits."""

from dataclasses import asdict, replace
import math
import unittest

from ..unified_20261028.profile import CostEvent, DeliveredOutcome, NduProfile, digest
from .control_actor import fit_actor
from .control_table import TableActor, fit_table
from .profile_contract import Prices, WorkBudget, support_status
from .tail_calibration import CalibrationPlan, calibrate_actual, unobserved_cost_witness


def profile(gamma=2.0, aggregation="population"):
    return NduProfile(digest("objective"), digest("observer"), digest("continuation"),
                      gamma=gamma, aggregation=aggregation, utility_bounds=(0.0, 1.0),
                      required_modalities=("text", "audio", "image", "video"))


def context(p):
    return {"feedback": 1, "owner_abstained": False, "media_units_remaining": 1,
            "emission_public_features": [0.0] * 16, "profile_sha256": p.digest}


def fitting_rows(p):
    rows = []
    for source, keep in (("source-a", 0.0), ("source-b", 1.0)):
        for action, value in (("keep", keep), ("swap", .4)):
            rows.append({"event_id": source + action, "source_id": source,
                         "context_id": source, "profile_sha256": p.digest, "split": "train",
                         "sampling_design": "paired_complete_actions", "selected_action": action,
                         "net_return": value, "boundary_context": context(p)})
    return rows


def calibration_fixture(p, costs=(.01, .02, .03, .04)):
    sources = tuple(f"fresh-{i}" for i in range(len(costs)))
    policy = digest("frozen-policy")
    plan = CalibrationPlan(p.digest, policy, digest("pre-execution-source-freeze"), sources, ("training-source",))
    rows = []
    for index, (source, cost) in enumerate(zip(sources, costs)):
        event = f"event-{index}"
        outcome = DeliveredOutcome(source, event, source, .8,
            (CostEvent(event + ":all-physical-cost", cost),),
            tuple((name, digest(name + event)) for name in p.required_modalities),
            p.observer_sha256, p.objective_sha256, p.continuation_sha256)
        rows.append({"event_id": event, "context_id": source, "source_id": source, "split": "calibration",
                     "profile_sha256": p.digest, "policy_sha256": policy, "calibration_plan_sha256": plan.digest,
                     "selected_action": "keep", "executed_action": "keep", "outcome": asdict(outcome),
                     "net_return": .8 - cost, "cpu_admission_threshold_exceeded": cost > 1,
                     "decision": {"policy_sha256": policy, "predicted_complete_moments": {"keep": .3, "swap": .4}}})
    return plan, rows


class CompleteMomentTests(unittest.TestCase):
    def test_risk_actor_reverses_mean_choice_from_whole_outcome_law(self):
        risk, mean = profile(), profile(0.0)
        risk_actor, _ = fit_actor(fitting_rows(risk), risk, steps=4)
        mean_actor, _ = fit_actor(fitting_rows(mean), mean, steps=4)
        self.assertEqual(risk_actor.choose(context(risk))[0], "swap")
        self.assertEqual(mean_actor.choose(context(mean))[0], "keep")
        self.assertAlmostEqual(risk_actor.predict(context(risk))["keep"], (1 + math.exp(-2)) / 2, places=12)
        self.assertAlmostEqual(risk_actor.predict(context(risk))["swap"], math.exp(-.8), places=12)

    def test_actual_cost_tail_changes_plan_even_when_average_cost_is_unchanged(self):
        p = profile()
        steady, variable = fitting_rows(p), fitting_rows(p)
        # Both keep laws have mean net return .5. One has correlated rare cost
        # and the other is constant; averaging cost before exp would miss this.
        for row in steady:
            if row["selected_action"] == "keep":
                row["net_return"] = .5
        steady_actor, _ = fit_actor(steady, p, steps=3)
        variable_actor, _ = fit_actor(variable, p, steps=3)
        self.assertEqual(steady_actor.choose(context(p))[0], "keep")
        self.assertEqual(variable_actor.choose(context(p))[0], "swap")

    def test_profile_and_independent_source_guards_are_active(self):
        p = profile()
        rows = fitting_rows(p)
        with self.assertRaisesRegex(ValueError, "counted twice"):
            fit_actor(rows + [rows[0]], p)
        conditional = profile(aggregation="conditional")
        with self.assertRaisesRegex(ValueError, "pooled population"):
            fit_actor(fitting_rows(conditional), conditional)
        actor, _ = fit_actor(rows, p, steps=2)
        with self.assertRaisesRegex(ValueError, "different profiles"):
            actor.choose(context(profile(0)))


class SourceTableTests(unittest.TestCase):
    def test_extra_rollouts_do_not_turn_one_source_into_more_population_mass(self):
        p = profile()
        rows = fitting_rows(p)
        # Nine extra legitimate draws from the favorable source would reverse
        # a row-weighted plan. They do not change its population source mass.
        for draw in range(1, 10):
            for row in fitting_rows(p)[2:]:
                rows.append({**row, "event_id": row["event_id"] + f"-draw-{draw}"})
        actor, _ = fit_table(rows, p)
        self.assertEqual(actor.choose(context(p))[0], "swap")
        expected = (1 + math.exp(-2)) / 2
        self.assertAlmostEqual(actor.predict(context(p))["keep"], expected, places=14)
        row_weighted = sum(math.exp(-2 * row["net_return"]) for row in rows
                           if row["selected_action"] == "keep") / 11
        self.assertLess(row_weighted, math.exp(-.8))
        restored = TableActor.from_dict(actor.to_dict())
        self.assertEqual(restored.digest, actor.digest)
        self.assertEqual(restored.choose(context(p)), actor.choose(context(p)))
        rows[0]["split"] = "calibration"
        with self.assertRaisesRegex(ValueError, "actual training"):
            fit_table(rows, p)


class ActualTailTests(unittest.TestCase):
    def test_complete_return_probability_has_bound_but_ndu_moment_does_not(self):
        p = profile()
        plan, rows = calibration_fixture(p)
        result = calibrate_actual(rows, p, plan)
        self.assertAlmostEqual(result["return_violation_probability_upper"], 1 - (.05 / 2) ** .25)
        self.assertEqual((result["ndu_moment_upper"], result["ndu_ce_lower"], result["ndu_tail_blocker_closed"]),
                         (None, None, False))
        # Exact duplicate logs do not become extra independent observations.
        self.assertEqual(calibrate_actual(rows + [rows[0]], p, plan), result)

    def test_large_real_cpu_cost_is_retained_without_clipping_or_omission(self):
        p = profile()
        plan, rows = calibration_fixture(p, (.01, .02, .03, 1000.0))
        result = calibrate_actual(rows, p, plan)
        self.assertEqual(result["observed_return_violations"], 1)
        self.assertLess(result["empirical_complete_return_ce"], -998)
        self.assertAlmostEqual(result["mean_actual_total_cost"], 250.015)
        with self.assertRaisesRegex(ValueError, "Every frozen"):
            calibrate_actual(rows[:-1], p, plan)

    def test_selected_policy_and_conditional_scope_cannot_be_swapped(self):
        p = profile()
        plan, rows = calibration_fixture(p)
        changed = [dict(row) for row in rows]
        changed[0]["policy_sha256"] = digest("different-actual-policy")
        with self.assertRaisesRegex(ValueError, "Actual selected policy"):
            calibrate_actual(changed, p, plan)
        conditional = profile(aggregation="conditional")
        conditional_plan, conditional_rows = calibration_fixture(conditional)
        with self.assertRaisesRegex(ValueError, "pooling different"):
            calibrate_actual(conditional_rows, conditional, conditional_plan)
        with self.assertRaisesRegex(ValueError, "disjoint"):
            replace(plan, excluded_source_ids=plan.source_ids)

    def test_unseen_rare_cost_defeats_any_data_only_finite_moment_limit(self):
        result = unobserved_cost_witness(n=1000, miss_probability=.99,
                                        proposed_moment_upper=1e12, gamma=2)
        self.assertAlmostEqual(result["all_n_costs_appear_zero_probability"], .99, places=12)
        self.assertTrue(result["proposed_upper_is_violated"])
        self.assertFalse(support_status(WorkBudget(), Prices())["finite_total_physical_cost_support_proved"])


if __name__ == "__main__":
    unittest.main()

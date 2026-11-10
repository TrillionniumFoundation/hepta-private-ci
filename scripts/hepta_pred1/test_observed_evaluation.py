"""Synthetic declarations only, including the positive conditional-gate fixture."""

from dataclasses import replace
import json
import unittest

from .contracts import Evidence, crps_score
from .observed_evaluation import (
    COST_FIELDS,
    ObservedDecision,
    PairedRegistration,
    UtilityContract,
    evaluate_observed,
    observed_to_dict,
    paired_adoption_gate,
    score_forecast,
    score_observed,
    validate_forecast,
)


class ObservedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.contract = UtilityContract("fixture_work", 0.1, 0.2, max_wall_seconds=10, max_total_cost=10)
        self.prediction = {
            "success_probability": 0.8,
            "duration_values": [0.5, 2.5],
            "duration_probabilities": [0.25, 0.75],
            "cost_values": [0.2, 1.1],
            "cost_probabilities": [0.5, 0.5],
        }

    def decision(self, group="g0", policy="candidate", **changes):
        evidence = Evidence(
            observation_status="terminal", outcome=1, time_kind="exact",
            time_lower=1.1, final_cost=0.35, observed_at=3.6,
            receipt_ref=f"fixture-receipt:{group}:{policy}",
        )
        values = dict(
            sample_id=f"fixture:{group}:{policy}", task_group=group, split="confirm",
            policy_id=policy, chosen_action="read", executed_action="read",
            execution_ref=f"fixture-exec:{group}:{policy}", decision_at=2,
            prediction_at=1, clock_id="fixture-clock", information_set_digest="a" * 64,
            budget_contract_digest=self.contract.digest, prediction=self.prediction, evidence=evidence,
            full_wall_seconds=1.6, costs={key: 0.35 if key == "action" else 0.01 for key in COST_FIELDS},
        )
        values.update(changes)
        return ObservedDecision(**values)

    def registration(self, **changes):
        values = dict(
            registration_ref="fixture-registration", clock_id="fixture-clock", frozen_at=0,
            candidate_policy_id="candidate", parent_policy_id="parent",
            task_groups=tuple(f"g{i}" for i in range(6)), excluded_task_groups=("old-train",),
            budget_contract_digest=self.contract.digest, utility_contract_digest=self.contract.digest,
            assignment_evidence_ref="fixture-randomized-pair-declaration",
            owner_evidence_ref="fixture-only-owner-declaration", independent_groups=True,
            new_confirmation=True,
        )
        values.update(changes)
        return PairedRegistration(**values)

    def pairs(self):
        records = []
        for i in range(6):
            for policy, outcome in (("candidate", 1), ("parent", 0)):
                decision = self.decision(f"g{i}", policy, source="declared_owner")
                records.append(replace(decision, evidence=replace(decision.evidence, outcome=outcome)))
        return records

    def test_off_grid_continuous_scores_and_full_ledger_utility(self):
        result = score_observed(self.decision(), self.contract)
        self.assertAlmostEqual(result["quality_brier"], 0.04)
        self.assertAlmostEqual(result["duration_crps"], 0.825)
        self.assertAlmostEqual(result["cost_crps"], 0.225)
        self.assertAlmostEqual(result["actual_net_utility"], 0.756)
        self.assertEqual(result["duration_quantiles"], [
            {"level": 0.1, "prediction": 0.5, "covered": False},
            {"level": 0.5, "prediction": 2.5, "covered": True},
            {"level": 0.9, "prediction": 2.5, "covered": True},
        ])
        self.assertIsNone(result["counterfactual_policy_value"])

    def test_sparse_duplicate_atoms_match_independent_quadratic_crps(self):
        forecast = {**self.prediction, "duration_values": [3, 0, 1, 1], "duration_probabilities": [0.3, 0, 0.3, 0.4]}
        result = score_observed(self.decision(prediction=forecast), self.contract)
        self.assertAlmostEqual(result["duration_crps"], crps_score([3, 0, 1, 1], [0.3, 0, 0.3, 0.4], 1.1))

    def test_preexecution_validation_export_and_retrospective_scoring(self):
        copied = validate_forecast(self.prediction)
        copied["duration_values"][0] = 90
        self.assertEqual(self.prediction["duration_values"], [0.5, 2.5])
        original = self.decision()
        encoded = json.loads(json.dumps(observed_to_dict(original), allow_nan=False))
        encoded["evidence"] = Evidence(**encoded["evidence"])
        self.assertEqual(ObservedDecision(**encoded), original)
        retrospective = score_forecast(self.prediction, original.evidence)
        observed = score_observed(original, self.contract)
        self.assertEqual(retrospective, {key: observed[key] for key in retrospective})
        self.assertNotIn("actual_net_utility", retrospective)
        with self.assertRaisesRegex(ValueError, "digest"):
            score_observed(original, UtilityContract("changed_unit", 0.1, 0.2))

    def test_forecast_and_ledger_are_frozen_and_future_receipts_rejected(self):
        costs = {key: 0.35 if key == "action" else 0 for key in COST_FIELDS}
        decision = self.decision(costs=costs)
        before = score_observed(decision, self.contract)
        self.prediction["duration_values"][0] = 900
        costs["action"] = 99
        self.assertEqual(score_observed(decision, self.contract), before)
        with self.assertRaises(TypeError):
            decision.prediction["success_probability"] = 1
        with self.assertRaises(TypeError):
            decision.costs["action"] = 1
        for changes in ({"prediction_at": 3}, {"decision_at": 3.6}, {"decision_at": 3.7}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "precede"):
                replace(decision, **changes)

    def test_unknown_cancel_censor_and_interval_never_become_exact_labels(self):
        records = []
        for i, status in enumerate(("receipt_missing", "cancel_requested", "verified_ongoing")):
            options = dict(observation_status=status, observed_at=3.6)
            if status == "verified_ongoing":
                options.update(time_kind="right_censored", time_lower=1.1, nonoccurrence_witness="fixture-witness")
            record = self.decision(f"g{i}", evidence=Evidence(**options))
            records.append(record)
            score = score_observed(record, self.contract)
            self.assertEqual([score[k] for k in ("quality_brier", "duration_crps", "cost_crps", "actual_net_utility")], [None] * 4)
        interval = replace(self.decision("g3").evidence, time_kind="interval", time_lower=1, time_upper=2)
        records.append(self.decision("g3", evidence=interval))
        report = evaluate_observed(records, self.contract)
        summary = report["summaries"][0]
        self.assertEqual(summary["observation_status_counts"], {"receipt_missing": 1, "cancel_requested": 1, "verified_ongoing": 1, "terminal": 1})
        self.assertEqual(summary["metrics"]["duration_crps"], {"observed_count": 0, "mean": None})
        self.assertEqual(summary["metrics"]["quality_brier"]["observed_count"], 1)
        self.assertEqual(report["decision"], "NoUpdate")

    def test_unexecuted_and_other_actions_have_no_factual_scores(self):
        for changes in ({"executed_action": None, "execution_ref": None}, {"executed_action": "other"}):
            result = score_observed(self.decision(**changes), self.contract)
            self.assertFalse(result["executed_choice_observed"])
            self.assertEqual([result[k] for k in ("quality_brier", "duration_crps", "cost_crps", "actual_net_utility")], [None] * 4)

    def test_full_wall_includes_decision_to_receipt_waiting(self):
        e = Evidence(observation_status="terminal", outcome=1, time_kind="exact",
                     time_lower=0.017, final_cost=0.35, observed_at=14,
                     receipt_ref="fixture-queued-effect")
        with self.assertRaisesRegex(ValueError, "decision-to-receipt"):
            self.decision(decision_at=12, prediction_at=11.9, evidence=e, full_wall_seconds=0.017)
        record = self.decision(decision_at=12, prediction_at=11.9, evidence=e, full_wall_seconds=2)
        self.assertIsNotNone(score_observed(record, self.contract)["actual_net_utility"])
        # Keep the separate duration bound even when the declared receipt span is shorter.
        with self.assertRaisesRegex(ValueError, "exact effect duration"):
            replace(record, evidence=replace(e, time_lower=3, time_upper=3))

    def test_missing_cost_or_wall_blocks_utility_even_with_zero_penalty(self):
        zero = UtilityContract("fixture_work", 0, 0)
        original = self.decision(budget_contract_digest=zero.digest)
        for key in COST_FIELDS:
            record = replace(original, costs={**original.costs, key: None})
            result = score_observed(record, zero)
            self.assertEqual(result["missing_cost_items"], [key])
            self.assertIsNone(result["actual_net_utility"])
            self.assertIsNone(result["full_cost"])
        self.assertIsNone(score_observed(replace(original, full_wall_seconds=None), zero)["actual_net_utility"])
        for changes in ({"full_wall_seconds": 1}, {"costs": {**original.costs, "action": 0.36}}):
            with self.assertRaises(ValueError):
                replace(original, **changes)

    def test_duplicate_or_reused_units_and_split_leaks_are_rejected(self):
        original = self.decision()
        cases = [
            replace(original, sample_id="second"),
            replace(original, task_group="g1"),
            replace(original, sample_id="second", task_group="g1"),
            replace(original, sample_id="second", policy_id="other", split="train", execution_ref="new", evidence=replace(original.evidence, receipt_ref="new")),
        ]
        for duplicate in cases:
            with self.subTest(duplicate=duplicate.sample_id), self.assertRaisesRegex(ValueError, "duplicate|reused|splits"):
                evaluate_observed([original, duplicate], self.contract)

    def test_reliability_bins_are_observed_only_and_sources_remain_separate(self):
        first = self.decision(prediction={**self.prediction, "success_probability": 1})
        second = self.decision("g1", prediction={**self.prediction, "success_probability": 1}, evidence=replace(first.evidence, outcome=0, receipt_ref="second"))
        third = self.decision("g2", source="declared_owner")
        report = evaluate_observed([first, second, third], self.contract)
        self.assertEqual(len(report["summaries"]), 2)
        fixture = next(r for r in report["summaries"] if r["source"] == "fixture")
        self.assertEqual(fixture["success_reliability_bins"][-1], {"lower": 0.9, "upper": 1.0, "count": 2, "mean_prediction": 1.0, "outcome_rate": 0.5})

    def test_conditional_paired_gate_uses_realized_utility_and_never_activates(self):
        result = paired_adoption_gate(self.pairs(), self.contract, self.registration())
        self.assertEqual({k: result[k] for k in ("decision", "candidate_eligible", "production_activation", "paired_groups", "mean_net_gain", "one_sided_signflip_p", "reasons")}, {
            "decision": "CandidateEligible", "candidate_eligible": True, "production_activation": False,
            "paired_groups": 6, "mean_net_gain": 1.0, "one_sided_signflip_p": 1 / 64, "reasons": [],
        })
        self.assertIn("not authentication", result["verification_scope"])

    def test_missing_registration_clock_design_groups_and_budget_fail_closed(self):
        rows, registration = self.pairs(), self.registration()
        registrations = [
            None, replace(registration, new_confirmation=False),
            replace(registration, independent_groups=False), replace(registration, frozen_at=1),
            replace(registration, clock_id="other-monotonic-clock"),
            replace(registration, assignment_evidence_ref=None), replace(registration, owner_evidence_ref=None),
            replace(registration, excluded_task_groups=("g0",)),
            replace(registration, budget_contract_digest="c" * 64),
            replace(registration, utility_contract_digest="c" * 64),
        ]
        for candidate in registrations:
            result = paired_adoption_gate(rows, self.contract, candidate)
            self.assertEqual(result["decision"], "NoUpdate")
            self.assertTrue(result["reasons"])
        variants = [
            rows[:-1], rows + [rows[0]],
            [replace(rows[0], source="fixture"), *rows[1:]],
            [replace(rows[0], information_set_digest="c" * 64), *rows[1:]],
            [replace(rows[0], costs={**rows[0].costs, "validation": None}), *rows[1:]],
        ]
        for candidate in variants:
            self.assertEqual(paired_adoption_gate(candidate, self.contract, registration)["decision"], "NoUpdate")

    def test_budget_caps_are_bound_and_unknown_caps_cannot_qualify(self):
        rows, registration = self.pairs(), self.registration()
        changed = replace(self.contract, max_wall_seconds=20)
        self.assertNotEqual(changed.digest, self.contract.digest)
        with self.assertRaisesRegex(ValueError, "digest"):
            score_observed(rows[0], changed)
        mixed = [replace(rows[0], budget_contract_digest=changed.digest), *rows[1:]]
        self.assertEqual(paired_adoption_gate(mixed, self.contract, registration)["decision"], "NoUpdate")
        for field in ("max_wall_seconds", "max_total_cost"):
            unknown = replace(self.contract, **{field: None})
            records = [replace(row, budget_contract_digest=unknown.digest) for row in rows]
            reg = replace(registration, budget_contract_digest=unknown.digest, utility_contract_digest=unknown.digest)
            score = score_observed(records[0], unknown)
            self.assertIsNotNone(score["actual_net_utility"])
            self.assertIsNone(score["within_budget"])
            result = paired_adoption_gate(records, unknown, reg)
            self.assertEqual(result["decision"], "NoUpdate")
            self.assertIn("explicit_shared_budget_limits_missing", result["reasons"])

    def test_overspend_or_time_overrun_blocks_adoption_without_dropping_rows(self):
        rows = self.pairs()
        for bad in (
            replace(rows[0], full_wall_seconds=11),
            replace(rows[0], costs={**rows[0].costs, "inference": 11}),
        ):
            records = [bad, *rows[1:]]
            report = evaluate_observed(records, self.contract)
            self.assertEqual(len(report["per_sample"]), 12)
            bad_score = report["per_sample"][0]
            self.assertIsNotNone(bad_score["actual_net_utility"])
            self.assertFalse(bad_score["within_budget"])
            result = paired_adoption_gate(records, self.contract, self.registration())
            self.assertEqual(result["decision"], "NoUpdate")
            self.assertEqual(result["paired_groups"], 6)
            self.assertEqual(result["over_budget_samples"], [bad.sample_id])
            self.assertFalse(result["within_budget"])
            self.assertIn("actual_shared_budget_limit_exceeded", result["reasons"])

    def test_better_calibration_but_worse_actual_utility_keeps_parent(self):
        rows = []
        for i in range(6):
            for policy, p, cost in (("candidate", 0.99, 2), ("parent", 0.5, 0.35)):
                d = self.decision(f"g{i}", policy, source="declared_owner", prediction={**self.prediction, "success_probability": p})
                rows.append(replace(d, evidence=replace(d.evidence, final_cost=cost), costs={**d.costs, "action": cost}))
        self.assertLess(score_observed(rows[0], self.contract)["quality_brier"], score_observed(rows[1], self.contract)["quality_brier"])
        result = paired_adoption_gate(rows, self.contract, self.registration())
        self.assertEqual(result["decision"], "NoUpdate")
        self.assertLess(result["mean_net_gain"], 0)

    def test_malformed_predictions_cannot_be_scored(self):
        for changes in (
            {"success_probability": float("nan")}, {"success_probability": True},
            {"duration_probabilities": [0.3, 0.3]}, {"duration_values": [-1, 2.5]},
            {"cost_values": [float("inf"), 1.1]},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.decision(prediction={**self.prediction, **changes})


if __name__ == "__main__":
    unittest.main()

"""Adversarial synthetic inventory tests; no training or scientific results."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from qualification.hcsn_regenerative import experiment_registry as r
except ModuleNotFoundError as error:
    if error.name != "qualification":
        raise
    import experiment_registry as r


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def synthetic_plan():
    plan = r.proposed_plan()
    plan["study_id"] = "synthetic-inventory-fixture-only"
    plan["bindings"] = {key: digest(key) for key in r.BINDINGS}
    for arm, profile in plan["arms"].items():
        profile.update(active_parameters=128, persistent_state_bytes=64)
        for field in r.ARM_EVIDENCE:
            profile[field] = digest(arm + field)
    plan["fit_budget"] = dict(zip(r.UNIT_FIELDS, (4, 8, 32)))
    plan["search_budget"] = dict(zip(r.UNIT_FIELDS, (1, 2, 8)))
    plan["total_cost_limits_per_fit"] = dict.fromkeys(r.COST_FIELDS, 10000)
    plan.update(minimum_useful_effect=0.1, retention_margin=0.02)
    return plan


def pair(plan, fit=None, phase="training", status="completed", attempt_id="a", units=None, cost=None):
    fit = fit or r.fit_roster(plan)[0]
    common = dict(attempt_id=attempt_id, study_id=plan["study_id"], plan_digest=r.validate_plan(plan),
                  **fit, source_digest=plan["bindings"]["source"], phase=phase,
                  components=list(r.COMPONENTS), native_receipt_sha256=None)
    if units is None:
        units = (plan["fit_budget"] if phase == "training" else plan["search_budget"]
                 if phase == "search" else dict.fromkeys(r.UNIT_FIELDS, 0))
    if cost is None:
        cost = dict(zip(r.COST_FIELDS, (2.0, 1.0, 100, 50, 3.0, 0.5)))
    start = r.seal_event(dict(common, kind="start"))
    terminal = r.seal_event(dict(common, kind="terminal", status=status, units=dict(units), cost=dict(cost),
                                 model_sha256=digest(fit["fit_id"]) if status == "completed" else None))
    return [start, terminal]


def complete_inventory(plan):
    return [event for fit in r.fit_roster(plan) for phase in r.PHASES
            for event in pair(plan, fit, phase=phase, attempt_id=fit["fit_id"] + ":" + phase)]


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.plan = synthetic_plan()

    def audit(self, events, plan=None):
        plan = plan or self.plan
        return r.audit_registry(plan, events, r.validate_plan(plan))

    def test_absence_stays_unknown_not_zero_or_completed(self):
        report = self.audit([], r.proposed_plan())
        self.assertEqual({row["state"] for row in report["fits"]}, {"not_started"})
        self.assertEqual(report["expected_training_fits"], 27)
        self.assertEqual(report["costs"]["known_totals_or_peak"], dict.fromkeys(r.COST_FIELDS))
        self.assertEqual((report["status"], report["registration"], report["original_campaign_completion_credit"],
                          report["ndu_factorial_completion_credit"]), ("HOLD", "UNREGISTERED", 0, 0))

    def test_episode_resampling_cannot_manufacture_fits(self):
        original = r.fit_roster(self.plan)
        self.plan["episode_seeds"] = list(range(100))
        self.assertEqual(r.fit_roster(self.plan), original)
        self.plan["training_seeds"].append(9901)
        self.assertEqual(len(r.fit_roster(self.plan)), len(original) + 9)

    def test_duplicate_or_boolean_training_seed_rejected(self):
        for seeds in ([1, 1, 2], [True, 2, 3]):
            with self.subTest(seeds=seeds), self.assertRaises(ValueError):
                plan = copy.deepcopy(self.plan)
                plan["training_seeds"] = seeds
                r.validate_plan(plan)

    def test_capacity_mismatch_not_hidden_by_other_unknown_capacity(self):
        self.plan["arms"]["smooth_dual"].update(active_parameters=129, persistent_state_bytes=None)
        with self.assertRaisesRegex(ValueError, "capacities must match"):
            r.validate_plan(self.plan)

    def test_ablations_cannot_change_unrelated_mechanisms(self):
        for arm, field, value in (("smooth_dual", "clock", "tick"), ("endpoint", "reset", False),
                                  ("hx_dual", "refractory", 1)):
            with self.subTest(arm=arm), self.assertRaises(ValueError):
                plan = copy.deepcopy(self.plan)
                plan["arms"][arm][field] = value
                r.validate_plan(plan)

    def test_conditional_boundary_requires_a_different_candidate(self):
        self.plan["arms"]["hx_dual"]["boundary"] = "conditional"
        with self.assertRaises(ValueError):
            r.validate_plan(self.plan)
        plan = synthetic_plan()
        plan["conditional_boundary"]["status"] = "SUPPORTED"
        with self.assertRaises(ValueError):
            r.validate_plan(plan)

    def test_plan_edit_cannot_reuse_retained_pin(self):
        pin = r.validate_plan(self.plan)
        self.plan["minimum_useful_effect"] *= 0.5
        with self.assertRaisesRegex(ValueError, "retained external pin"):
            r.audit_registry(self.plan, [], pin)

    def test_self_reported_registration_rejected(self):
        self.plan["registration"] = "REGISTERED"
        with self.assertRaises(ValueError):
            r.validate_plan(self.plan)

    def test_original_campaign_contract_cannot_be_rebudgeted(self):
        self.plan["original_campaign"]["expected_runs"] = 27
        with self.assertRaises(ValueError):
            r.validate_plan(self.plan)

    def test_receipt_without_start_rejected(self):
        with self.assertRaisesRegex(ValueError, "without original start"):
            self.audit(pair(self.plan)[1:])

    def test_orphan_start_is_unresolved_and_cost_unknown(self):
        report = self.audit(pair(self.plan)[:1])
        self.assertEqual(report["fits"][0]["state"], "unresolved")
        self.assertEqual(report["fits"][0]["unresolved_attempts"], ["a"])
        self.assertEqual(report["costs"]["unresolved_attempts"], 1)
        self.assertIn("complete_physical_cost_unknown", report["blockers"])

    def test_terminal_rebinding_rejected_even_with_fresh_checksum(self):
        events = pair(self.plan)
        events[1] = r.seal_event(dict(events[1], phase="search"))
        with self.assertRaisesRegex(ValueError, "rebinds phase"):
            self.audit(events)

    def test_duplicate_terminal_cannot_replace_adverse_result(self):
        events = pair(self.plan, status="oom", units=dict.fromkeys(r.UNIT_FIELDS, 0))
        replacement = pair(self.plan)[1]
        with self.assertRaisesRegex(ValueError, "Duplicate immutable terminal"):
            self.audit(events + [replacement])

    def test_unknown_failed_budget_is_retained_not_zero_filled(self):
        events = pair(self.plan, status="failed", units=dict.fromkeys(r.UNIT_FIELDS))
        report = self.audit(events)
        self.assertEqual(report["fits"][0]["retained_adverse_attempts"], ["a"])
        self.assertEqual(report["fits"][0]["state"], "failed")
        self.assertEqual(report["fits"][0]["submitted_units"]["training"],
                         {unit: {"known_submitted": None, "unknown_terminal_attempts": 1} for unit in r.UNIT_FIELDS})
        self.assertTrue(any(x.startswith("submitted_budget_unknown:") for x in report["blockers"]))

    def test_failure_then_retry_includes_both_costs_and_submissions(self):
        events = pair(self.plan, status="oom", units=dict(zip(r.UNIT_FIELDS, (0, 2, 8))))
        events += pair(self.plan, attempt_id="retry")
        report = self.audit(events)
        self.assertEqual(report["status"], "FAILED_BUDGET")
        self.assertEqual(report["fits"][0]["retained_adverse_attempts"], ["a"])
        self.assertEqual(report["costs"]["known_totals_or_peak"]["wall_seconds"], 4.0)
        self.assertEqual({row["unit"] for row in report["overruns"]}, {"examples_submitted", "tokens_submitted"})

    def test_failed_search_costs_and_budget_cannot_disappear(self):
        events = pair(self.plan, phase="search", status="failed")
        events += pair(self.plan, phase="search", attempt_id="search_retry")
        report = self.audit(events)
        self.assertEqual({row["phase"] for row in report["overruns"]}, {"search"})
        self.assertEqual(report["costs"]["known_totals_or_peak"]["energy_joules"], 6.0)

    def test_cost_limit_includes_failed_attempt(self):
        self.plan["total_cost_limits_per_fit"]["energy_joules"] = 2.0
        report = self.audit(pair(self.plan, status="oom"))
        self.assertEqual(report["status"], "FAILED_BUDGET")
        self.assertEqual(report["overruns"], [dict(fit_id=r.fit_roster(self.plan)[0]["fit_id"], phase="all",
                                                  unit="energy_joules", observed=3.0, limit=2.0)])

    def test_peak_is_maximum_and_components_do_not_double_count_totals(self):
        events = pair(self.plan)
        events += pair(self.plan, phase="evaluation", attempt_id="eval")
        report = self.audit(events)
        known = report["costs"]["known_totals_or_peak"]
        self.assertEqual((known["wall_seconds"], known["peak_gpu_bytes"], known["peak_host_bytes"]), (4.0, 50, 100))

    def test_short_success_is_not_full_budget_evidence(self):
        report = self.audit(pair(self.plan, units=dict(zip(r.UNIT_FIELDS, (2, 4, 16)))))
        self.assertTrue(any(x.startswith("incomplete_frozen_budget:") for x in report["blockers"]))
        self.assertEqual(report["status"], "HOLD")

    def test_multiple_successes_remain_visible_and_ambiguous(self):
        report = self.audit(pair(self.plan) + pair(self.plan, attempt_id="selected_second"))
        self.assertEqual((report["fits"][0]["state"], report["fits"][0]["started_attempts"]), ("ambiguous", 2))
        self.assertEqual(report["costs"]["known_totals_or_peak"]["energy_joules"], 6.0)
        self.assertTrue(any(x.startswith("multiple_successes_allow_selection:") for x in report["blockers"]))

    def test_checkpoint_reuse_does_not_prove_independent_training(self):
        fits = r.fit_roster(self.plan)
        events = pair(self.plan, fits[0]) + pair(self.plan, fits[1], attempt_id="fit2")
        events[-1] = r.seal_event(dict(events[-1], model_sha256=events[1]["model_sha256"]))
        self.assertIn("trained_model_identity_reused", self.audit(events)["blockers"])

    def test_evaluator_cannot_switch_trained_weights(self):
        events = pair(self.plan) + pair(self.plan, phase="evaluation", attempt_id="eval")
        events[-1] = r.seal_event(dict(events[-1], model_sha256=digest("substituted")))
        with self.assertRaisesRegex(ValueError, "Evaluation rebinds"):
            self.audit(events)

    def test_foreign_campaign_source_or_seed_rejected(self):
        for key, value in (("study_id", r.ORIGINAL_CAMPAIGN), ("source_digest", digest("foreign")),
                           ("training_seed", self.plan["episode_seeds"][0])):
            with self.subTest(field=key), self.assertRaises(ValueError):
                events = [r.seal_event(dict(e, **{key: value})) for e in pair(self.plan)]
                self.audit(events)

    def test_unknown_energy_remains_unknown_with_known_other_costs(self):
        events = complete_inventory(self.plan)
        events[1]["cost"]["energy_joules"] = None
        events[1] = r.seal_event(events[1])
        report = self.audit(events)
        self.assertEqual(report["costs"]["unknown_terminal_fields"]["energy_joules"], 1)
        self.assertIn("complete_physical_cost_unknown", report["blockers"])
        self.assertEqual((report["deployment_cost_gate"], report["scaling_gate"]), ("HOLD", "HOLD"))

    def test_unresolved_terminal_cannot_make_partial_costs_complete(self):
        events = complete_inventory(self.plan)
        events[-1] = r.seal_event(dict(events[-1], status="unresolved"))
        report = self.audit(events)
        self.assertEqual((report["costs"]["unresolved_attempts"], report["costs"]["missing_terminal_attempts"]), (1, 0))
        self.assertIn("complete_physical_cost_unknown", report["blockers"])
        self.assertTrue(any(x.startswith("evaluation_or_deployment_incomplete:") for x in report["blockers"]))

    def test_unknown_cost_field_must_be_explicit_null(self):
        events = pair(self.plan)
        del events[1]["cost"]["energy_joules"]
        events[1] = r.seal_event(events[1])
        with self.assertRaisesRegex(ValueError, "missing or unknown fields"):
            self.audit(events)

    def test_negative_boolean_and_nonfinite_costs_rejected(self):
        for value in (-1, True, float("nan"), float("inf"), 10**400):
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                events = pair(self.plan)
                events[1]["cost"]["energy_joules"] = value
                events[1] = r.seal_event(events[1])
                self.audit(events)

    def test_finite_inputs_cannot_overflow_into_a_cost_claim(self):
        events = pair(self.plan) + pair(self.plan, phase="evaluation", attempt_id="eval")
        for index in (1, 3):
            events[index]["cost"]["wall_seconds"] = 1e308
            events[index] = r.seal_event(events[index])
        with self.assertRaisesRegex(ValueError, "aggregate wall_seconds"):
            self.audit(events)

    def test_event_mutation_is_detected_without_resealing(self):
        events = pair(self.plan)
        events[1]["cost"]["energy_joules"] = 0
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.audit(events)

    def test_self_reported_authenticated_bool_is_not_an_interface(self):
        events = pair(self.plan)
        events[1] = r.seal_event(dict(events[1], authenticated=True))
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            self.audit(events)
        self.plan["authenticated"] = True
        with self.assertRaises(ValueError):
            r.validate_plan(self.plan)

    def test_complete_self_consistent_inventory_still_cannot_pass(self):
        events = complete_inventory(self.plan)
        events = [r.seal_event(dict(e, native_receipt_sha256=digest(e["attempt_id"] + e["kind"]))) for e in events]
        before = copy.deepcopy((self.plan, events))
        report = self.audit(events)
        self.assertEqual({row["state"] for row in report["fits"]}, {"completed"})
        self.assertEqual((report["status"], report["registration"], report["native_receipt_authentication"],
                          report["adoption_authorized"], report["scientific_benefit_established"]),
                         ("HOLD", "UNREGISTERED", "NOT_IMPLEMENTED", False, False))
        self.assertEqual((self.plan, events), before)

    def test_missing_cost_scope_cannot_be_hidden_by_complete_training(self):
        events = pair(self.plan)
        events = [r.seal_event(dict(e, components=["core"])) for e in events]
        report = self.audit(events)
        self.assertEqual(report["fits"][0]["missing_components"], ["decoder", "encoder", "state_storage"])
        self.assertEqual(report["fits"][0]["missing_cost_phases"], ["deployment", "evaluation", "search"])

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in ('{"status":"failed","status":"completed"}', '{"energy":NaN}', '{"energy":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                r.strict_json(raw)

    def test_cli_returns_nonadmission_exit_and_preserves_unset_real_budgets(self):
        module = Path(r.__file__).resolve()
        draft = subprocess.run([sys.executable, "-B", str(module), "--draft"], capture_output=True, text=True, check=True)
        plan = json.loads(draft.stdout)
        self.assertEqual(set(plan["fit_budget"].values()), {None})
        self.assertIsNone(plan["minimum_useful_effect"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path/"plan.json").write_text(draft.stdout)
            (path/"events.json").write_text("[]")
            command = [sys.executable, "-B", str(module), "--plan", str(path/"plan.json"),
                       "--events", str(path/"events.json"), "--expected-plan-digest", r.validate_plan(plan)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "HOLD")
            result = subprocess.run(command[:-1] + [digest("wrong-pin")], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()

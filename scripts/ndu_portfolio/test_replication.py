"""Crossed inference and adversarial accounting tests; all data are synthetic."""

import copy
import unittest

import numpy as np

from .example_factorial import example
from . import factorial as f
from .replication import audit_replicates, crossed_interval, design_digest, seal_fit, validate_plan


def replicated_example():
    p, rows, _ = example()
    plan = {"schema": "ndu-replicated-factorial-v1", "registered_at": p["registered_at"],
        "design_digest": design_digest(p), "fits": [{"fit_id": f"fit-{i}", "training_seed": 100+i} for i in range(4)],
        "bootstrap_samples": 10000, "bootstrap_seed": 551,
        "power": {"method": "crossed-normal-planning-v1", "family_size": 20, "alpha": .05, "power": .8,
            "effect_above_margin": .1, "fit_variance": .0001, "source_variance": .0001,
            "interaction_variance": .0001, "pilot_sha256": f.canonical_digest("synthetic pilot"),
            "pilot_frozen_at": "2026-10-31T00:00:00Z", "pilot_source_groups": ["synthetic-pilot-only"],
            "pilot_fit_run_ids": ["synthetic-pilot-fit"]}}
    records = []
    for fit in plan["fits"]:
        fid = fit["fit_id"]
        protocol, episodes = copy.deepcopy(p), copy.deepcopy(rows)
        for key, profile in protocol["profiles"].items():
            # Frozen content remains shared. Fit-specific trained artifacts are
            # independent identities even when outcomes happen to be equal.
            if key.startswith("joint:"):
                profile["model_digest"] = f.canonical_digest([fid, key, "model"])
            profile["policy_digest"] = f.canonical_digest([fid, key, "policy"])
            profile["research_costs"]["evaluation"] = 150  # Covers all 160 episodes at 0.9 units each.
        for row in episodes:
            profile = protocol["profiles"][f'{row["regime"]}:{row["arm"]}']
            row.update(model_digest=profile["model_digest"], policy_digest=profile["policy_digest"],
                       run_id=f'{fid}/{row["run_id"]}', attempt_ids=[f'{fid}/{a}' for a in row["attempt_ids"]])
        selection = f.select_comparators(protocol, episodes[:1280], "2026-11-03T00:00:00Z")
        attempts = []
        for key, profile in protocol["profiles"].items():
            for phase, cost in profile["research_costs"].items():
                identity = f"{fid}/{key}/{phase}"
                day, hour = ("04", "02") if phase == "evaluation" else ("01", "01")
                attempts.append({"attempt_id": identity, "phase": phase, "profile": key, "status": "success",
                    "cost": cost, "receipt_digest": f.canonical_digest(identity),
                    "started_at": f"2026-11-{day}T{hour}:00:00Z", "finished_at": f"2026-11-{day}T{hour}:00:01Z"})
        record = {**fit, "fit_run_id": f"independent-trainer/{fid}", "status": "complete",
            "training_receipt_digest": f.canonical_digest([fid, "native-receipt-fixture"]),
            "research_attempts": attempts, "protocol": protocol, "rows": episodes, "selection": selection}
        record["fit_lock"] = seal_fit(record)
        records.append(record)
    return plan, records


class ReplicationTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.records = replicated_example()

    def run_audit(self):
        return audit_replicates(self.plan, self.records, expected_plan_digest=f.canonical_digest(self.plan))

    def test_complete_four_fit_matrix_and_all_contrasts_remain_non_authorizing(self):
        result = self.run_audit()
        self.assertEqual((result["planned_fits"], result["complete_fits"]), (4, 4))
        self.assertEqual(len(result["contrasts"]), 20)
        self.assertEqual(result["research_total"], 4 * 16 * 260)
        self.assertEqual(result["inference_cost_ledger"]["all_observed_episodes"]["episodes"], 10240)
        self.assertAlmostEqual(result["contrasts"]["joint:D-B"]["estimate"], .29)
        self.assertEqual(result["contrasts"]["joint:D-B"]["independent_fits"], 4)
        self.assertEqual(result["scientific_admission"], "HOLD")
        self.assertFalse(result["adoption_authorized"])

    def test_episode_seed_relabel_cannot_replace_independent_fit(self):
        self.records[1]["training_receipt_digest"] = self.records[0]["training_receipt_digest"]
        with self.assertRaisesRegex(f.InvalidEvidence, "reused independent fit receipt"):
            self.run_audit()

    def test_missing_fit_and_reused_episode_execution_rejected(self):
        original = self.records.pop()
        with self.assertRaisesRegex(f.InvalidEvidence, "fit roster"):
            self.run_audit()
        self.records.append(original)
        self.records[1]["rows"][-1]["run_id"] = self.records[0]["rows"][-1]["run_id"]
        with self.assertRaisesRegex(f.InvalidEvidence, "reused across"):
            self.run_audit()

    def test_failed_fit_keeps_cost_and_prevents_survivor_only_inference(self):
        record = self.records[-1]
        record.update(status="failed", protocol=None, selection=None, rows=[])
        record["research_attempts"][0]["status"] = "failed"
        result = self.run_audit()
        self.assertEqual(result["complete_fits"], 3)
        self.assertEqual(result["research_total"], 16640)
        self.assertTrue(all(c["ci"] is None for c in result["contrasts"].values()))
        self.assertEqual(result["fits"][record["fit_id"]]["failed_attempts"], 1)

    def test_all_failed_fits_still_report_twenty_hold_contrasts(self):
        for record in self.records:
            record.update(status="failed", protocol=None, selection=None, rows=[])
        result = self.run_audit()
        self.assertEqual(len(result["contrasts"]), 20)
        self.assertEqual(result["complete_fits"], 0)

    def test_partial_failed_fit_outputs_are_retained_without_survivor_inference(self):
        record = self.records[0]
        partial = record["rows"][:7]
        record.update(status="failed", rows=partial)
        result = self.run_audit()
        observed = result["fits"][record["fit_id"]]
        self.assertEqual(observed["retained_partial_rows"], 7)
        self.assertEqual(observed["retained_partial_rows_digest"], f.canonical_digest(partial))
        self.assertTrue(all(c["ci"] is None for c in result["contrasts"].values()))

    def test_partial_failed_fit_cannot_hide_observed_evaluation_cost(self):
        record = self.records[0]
        record.update(status="failed", rows=record["rows"][:7], research_attempts=record["research_attempts"][:1])
        result = self.run_audit()
        self.assertIsNone(result["research_total"])
        self.assertIsNone(result["fits"][record["fit_id"]]["research_total"])
        self.assertTrue(any("evaluation_cost_not_covered" in x for x in result["unknowns"]))
        self.assertGreater(result["fits"][record["fit_id"]]["research_known_lower_bound"], 80)

    def test_undercovered_evaluation_cannot_produce_finite_amortized_benefit(self):
        record = self.records[0]
        record["protocol"]["profiles"]["joint:D"]["research_costs"]["evaluation"] = 1
        for attempt in record["research_attempts"]:
            if attempt["profile"] == "joint:D" and attempt["phase"] == "evaluation":
                attempt["cost"] = 1
        result = self.run_audit()
        self.assertIsNone(result["D_minus_strongest_amortized_ci_at_deployments"]["joint:100"])
        self.assertEqual(result["contrasts"]["joint:D-strongest"]["statistical_gate"], "HOLD")

    def test_unresolved_original_job_needs_no_fabricated_end_time(self):
        record = self.records[0]
        record.update(status="unresolved", rows=[])
        record["research_attempts"][0].update(status="unresolved", finished_at=None, cost=None)
        result = self.run_audit()
        self.assertIsNone(result["research_total"])
        self.assertIn("fit-0:unresolved", result["unknowns"])

    def test_planned_fit_not_started_needs_no_fabricated_training_receipt(self):
        self.records[0].update(status="not_started", fit_run_id=None, training_receipt_digest=None,
                               research_attempts=[], rows=[], protocol=None, selection=None, fit_lock=None)
        result = self.run_audit()
        self.assertEqual(result["fits"]["fit-0"]["attempts"], 0)
        self.assertIsNone(result["research_total"])
        self.assertEqual(result["complete_fits"], 3)

    def test_frozen_model_cannot_change_across_fit_identities(self):
        self.records[0]["protocol"]["profiles"]["frozen:D"]["model_digest"] = f.canonical_digest("changed frozen model")
        with self.assertRaisesRegex(f.InvalidEvidence, "registered design"):
            self.run_audit()

    def test_unknown_cost_is_not_zero_and_training_receipt_mutation_rejected(self):
        attempt = self.records[0]["research_attempts"][0]
        attempt["cost"] = None
        with self.assertRaisesRegex(f.InvalidEvidence, "receipt lock changed"):
            self.run_audit()
        self.records[0]["fit_lock"] = seal_fit(self.records[0])
        result = self.run_audit()
        self.assertIsNone(result["research_total"])
        self.assertTrue(result["unknowns"])

    def test_cost_summary_cannot_omit_failed_search(self):
        attempt = copy.deepcopy(self.records[0]["research_attempts"][1])
        attempt.update(attempt_id="new-failed-search", status="failed", cost=5)
        self.records[0]["research_attempts"].append(attempt)
        self.records[0]["fit_lock"] = seal_fit(self.records[0])
        with self.assertRaisesRegex(f.InvalidEvidence, "ledger/profile cost differs"):
            self.run_audit()

    def test_wrong_plan_pin_and_post_registration_pilot_rejected(self):
        with self.assertRaisesRegex(f.InvalidEvidence, "plan pin"):
            validate_plan(self.plan, "0" * 64)
        self.plan["power"]["pilot_frozen_at"] = self.plan["registered_at"]
        with self.assertRaisesRegex(f.InvalidEvidence, "pilot must precede"):
            self.run_audit()

    def test_pilot_confirmation_leakage_rejected(self):
        self.plan["power"]["pilot_source_groups"] = ["test-new-0"]
        with self.assertRaisesRegex(f.InvalidEvidence, "pilot leaks"):
            self.run_audit()

    def test_opportunity_and_training_seed_drift_rejected(self):
        self.records[0]["training_seed"] += 100
        with self.assertRaisesRegex(f.InvalidEvidence, "training seed differs"):
            self.run_audit()
        self.records[0]["training_seed"] -= 100
        self.records[0]["protocol"]["profiles"]["joint:D"]["budget"]["search_trials"] += 1
        with self.assertRaisesRegex(f.InvalidEvidence, "registered design"):
            self.run_audit()

    def test_fit_variance_cannot_be_cured_by_infinite_episodes(self):
        self.plan["power"]["fit_variance"] = 1
        result = validate_plan(self.plan, f.canonical_digest(self.plan))
        self.assertIsNone(result["required_source_groups_per_test_cohort"])
        self.assertEqual(result["status"], "MORE_INDEPENDENT_FITS_REQUIRED")
        audit = self.run_audit()
        self.assertTrue(all(c["statistical_gate"] == "HOLD" for c in audit["contrasts"].values()))

    def test_crossed_interval_keeps_fit_uncertainty_when_sources_are_duplicated(self):
        matrix = np.repeat(np.array([-.3, -.1, .1, .3])[:, None], 20, axis=1)
        kwargs = {"draws": 20000, "seed": 19, "alpha": .05}
        ci = crossed_interval(matrix, **kwargs)
        many = crossed_interval(np.tile(matrix, (1, 10)), **kwargs)
        self.assertLess(ci[0], -.1); self.assertGreater(ci[1], .1)
        self.assertAlmostEqual(many[1] - many[0], ci[1] - ci[0], places=10)

    def test_power_reacts_to_effect_variance_and_multiplicity(self):
        self.plan["power"].update(effect_above_margin=.02, fit_variance=.000001, source_variance=.01)
        n = validate_plan(self.plan, f.canonical_digest(self.plan))["required_source_groups_per_test_cohort"]
        self.plan["power"]["effect_above_margin"] = .01
        larger = validate_plan(self.plan, f.canonical_digest(self.plan))["required_source_groups_per_test_cohort"]
        self.assertGreater(larger, n * 3)
        self.plan["power"]["family_size"] = 1
        with self.assertRaisesRegex(f.InvalidEvidence, "all 20"):
            self.run_audit()


if __name__ == "__main__":
    unittest.main()

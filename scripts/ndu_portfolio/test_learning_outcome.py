"""Adversarial fixtures for a bounded declaration audit, not native evidence."""

import copy
import unittest

from .factorial import COSTS
from .generation import digest
from .learning_outcome import GATES, audit


def fixture():
    contract = {
        "schema": "ndu-learning-outcome-contract-v1",
        "operation_id": "synthetic-iteration",
        "source_task_id": "task-old",
        "source_run_id": "run-old",
        "trainer_id": "trainer",
        "evaluator_id": "independent-evaluator",
        "registered_at": "2026-11-01T00:00:00Z",
        "deadline_at": "2026-11-01T01:00:00Z",
        "cost_unit": "synthetic-units",
        "maximum_cost": 100,
        "expected_candidate_ids": ["candidate-1"],
    }
    for field in (
        "incumbent_manifest_digest",
        "incumbent_checkpoint_digest",
        "objective_digest",
        "source_registry_digest",
        "source_bundle_digest",
        "evaluator_digest",
    ):
        contract[field] = digest(field)

    def job(name, phase, candidate, minute):
        return {
            "job_id": name,
            "candidate_id": candidate,
            "phase": phase,
            "status": "succeeded",
            "started_at": f"2026-11-01T00:{minute:02d}:00Z",
            "ended_at": f"2026-11-01T00:{minute + 1:02d}:00Z",
            "receipt_digest": digest(name),
            "artifact_digest": digest("candidate-model") if candidate else None,
            "costs": {c: 1.0 for c in COSTS},
        }

    evidence = {
        "schema": "ndu-learning-outcome-evidence-v1",
        "operation_id": contract["operation_id"],
        "contract_digest": digest(contract),
        "completed_at": "2026-11-01T00:10:00Z",
        "stop_reason": "candidates_exhausted",
        "failure_receipt_digest": None,
        "jobs": [
            job("dataset-job", "dataset", None, 1),
            job("training-job", "training", "candidate-1", 3),
            job("evaluation-job", "evaluation", "candidate-1", 5),
            job("terminal-meter-job", "evaluation", None, 7),
        ],
        "data_admission": {
            "source_registry_digest": contract["source_registry_digest"],
            "objective_digest": contract["objective_digest"],
            "receipt_digest": digest("dataset-job"),
            "scanned_rows": 10,
            "eligible_rows": 10,
            "excluded_rows": 0,
            "complete": True,
            "job_id": "dataset-job",
        },
        "candidates": [
            {
                "candidate_id": "candidate-1",
                "status": "evaluated",
                "manifest_digest": digest("candidate-model"),
                "objective_digest": contract["objective_digest"],
                "evaluator_id": contract["evaluator_id"],
                "evaluation_receipt_digest": digest("evaluation-job"),
                "gates": {g: "PASS" for g in GATES},
                "job_ids": ["training-job", "evaluation-job"],
            }
        ],
        "terminal_evaluation": None,
    }
    evidence["candidates"][0]["gates"]["external_net_gain"] = "FAIL"
    bind_terminal(contract, evidence)
    return contract, evidence


def bind_terminal(contract, evidence):
    evidence["terminal_evaluation"] = {
        key: contract[key]
        for key in (
            "evaluator_id",
            "evaluator_digest",
            "objective_digest",
            "incumbent_manifest_digest",
        )
    }
    evidence["terminal_evaluation"].update(
        receipt_digest=digest("terminal-evaluation"),
        meter_job_id="terminal-meter-job",
        data_admission_digest=digest(evidence["data_admission"]),
        candidate_inventory_digest=digest(evidence["candidates"]),
        job_inventory_digest=digest(evidence["jobs"]),
    )


def skipped(evidence, status):
    evidence["jobs"] = [job for job in evidence["jobs"] if job["candidate_id"] is None]
    evidence["candidates"][0].update(
        status=status,
        manifest_digest=None,
        evaluation_receipt_digest=None,
        gates={g: "HOLD" for g in GATES},
        job_ids=[],
    )


def continuation(contract, evidence):
    return {
        "operation_id": contract["operation_id"],
        "decision_evidence_digest": digest(evidence),
        "prior_task_id": contract["source_task_id"],
        "prior_run_id": contract["source_run_id"],
        "task_id": "task-next",
        "run_id": "run-next",
        "manifest_digest": contract["incumbent_manifest_digest"],
        "source_checkpoint_digest": contract["incumbent_checkpoint_digest"],
        "checkpoint_digest": digest("next-checkpoint"),
        "committed_step_receipt_digest": digest("actual-step"),
        "final_use_receipt_digest": digest("signed-final-use"),
        "purpose": "agentd.cell-generation.next-task-same-model",
    }


class LearningOutcomeContract(unittest.TestCase):
    def setUp(self):
        self.c, self.e = fixture()
        self.pin = digest(self.c)

    def run_audit(self, *, rebind=True, **kwargs):
        if rebind:
            bind_terminal(self.c, self.e)
        return audit(self.c, self.e, expected_contract_digest=self.pin, **kwargs)

    def test_finite_negative_result_and_adoptable_are_conditional(self):
        negative = self.run_audit()
        self.e["candidates"][0]["gates"]["external_net_gain"] = "PASS"
        positive = self.run_audit()
        self.assertEqual(
            [negative["conditional_outcome"], positive["conditional_outcome"]],
            ["NoUpdate", "Adoptable"],
        )
        for result in (negative, positive):
            self.assertEqual(
                (
                    result["outcome"],
                    result["status"],
                    result["adoption_authorized"],
                    result["reward_eligible"],
                    result["chain_submission"],
                    result["global_optimality_claim"],
                ),
                ("Inconclusive", "HOLD", False, False, None, False),
            )
            self.assertEqual(
                result["native_receipt_verification"],
                {"verified": False, "status": "NOT_IMPLEMENTED"},
            )

    def test_missing_material_is_not_no_eligible_data(self):
        self.e["data_admission"] = None
        self.e["stop_reason"] = "no_eligible_data"
        skipped(self.e, "skipped_no_data")
        result = self.run_audit()
        self.assertEqual(result["conditional_outcome"], "Inconclusive")
        self.assertIn("missing_data_admission", result["reasons"])

    def test_complete_empty_admission_can_support_conditional_noupdate(self):
        self.e["data_admission"].update(eligible_rows=0, excluded_rows=10)
        self.e["stop_reason"] = "no_eligible_data"
        skipped(self.e, "skipped_no_data")
        self.assertEqual(self.run_audit()["conditional_outcome"], "NoUpdate")
        self.e["data_admission"]["complete"] = False
        self.assertEqual(self.run_audit()["conditional_outcome"], "Inconclusive")

    def test_missing_independent_terminal_evaluation_is_inconclusive(self):
        self.e["terminal_evaluation"] = None
        result = self.run_audit(rebind=False)
        self.assertEqual(result["conditional_outcome"], "Inconclusive")
        self.assertEqual(
            (
                result["costs"]["known_subtotal"],
                result["costs"]["recorded_ledger_total"],
                result["costs"]["total"],
                result["costs"]["coverage"],
            ),
            (36.0, 36.0, None, "incomplete"),
        )

    def test_unknown_cost_is_retained(self):
        self.e["jobs"][0]["costs"]["sync"] = None
        result = self.run_audit()
        self.assertEqual(result["conditional_outcome"], "Inconclusive")
        self.assertEqual(
            result["costs"],
            {
                "known_subtotal": 35.0,
                "total": None,
                "unknowns": ["dataset-job:sync"],
                "recorded_ledger_total": None,
                "coverage": "incomplete",
                "unit": "synthetic-units",
                "jobs": 4,
            },
        )

    def test_missing_candidate_cannot_disappear(self):
        self.e["data_admission"].update(eligible_rows=0, excluded_rows=10)
        self.e["stop_reason"] = "no_eligible_data"
        skipped(self.e, "skipped_no_data")
        self.e["candidates"] = []
        result = self.run_audit()
        self.assertEqual(result["conditional_outcome"], "Inconclusive")
        self.assertIn("incomplete_candidate_inventory", result["reasons"])

    def test_unlisted_failed_attempt_is_rejected(self):
        self.e["jobs"].append(
            {
                **copy.deepcopy(self.e["jobs"][1]),
                "job_id": "hidden-failure",
                "status": "failed",
            }
        )
        with self.assertRaisesRegex(ValueError, "unlisted candidate job"):
            self.run_audit()

    def test_infrastructure_failure_and_overrun_are_retained(self):
        self.e["failure_receipt_digest"] = digest("infrastructure-failure")
        self.e["stop_reason"] = "execution_failed"
        result = self.run_audit()
        self.assertEqual(
            (result["conditional_outcome"], result["costs"]["total"]), ("Failed", 36.0)
        )
        self.e["failure_receipt_digest"] = None
        self.e["stop_reason"] = "candidates_exhausted"
        self.e["jobs"][1]["costs"]["retry"] = 101
        self.assertIn("budget_overrun", self.run_audit()["reasons"])
        self.assertEqual(self.run_audit()["conditional_outcome"], "Failed")

    def test_reconciled_failed_trial_does_not_veto_completed_decision(self):
        self.c["expected_candidate_ids"].append("candidate-failed")
        self.pin = digest(self.c)
        self.e["contract_digest"] = self.pin
        trial = {
            **copy.deepcopy(self.e["jobs"][1]),
            "job_id": "failed-trial",
            "candidate_id": "candidate-failed",
            "status": "failed",
            "receipt_digest": digest("failed-trial"),
        }
        self.e["jobs"].append(trial)
        self.e["candidates"].append(
            {
                **copy.deepcopy(self.e["candidates"][0]),
                "candidate_id": "candidate-failed",
                "status": "failed",
                "manifest_digest": None,
                "evaluation_receipt_digest": None,
                "gates": {g: "HOLD" for g in GATES},
                "job_ids": ["failed-trial"],
            }
        )
        negative = self.run_audit()
        self.assertEqual(
            (negative["conditional_outcome"], negative["costs"]["total"]),
            ("NoUpdate", 45.0),
        )
        self.e["candidates"][0]["gates"]["external_net_gain"] = "PASS"
        self.assertEqual(self.run_audit()["conditional_outcome"], "Adoptable")
        self.e["candidates"] = self.e["candidates"][1:]
        self.e["jobs"] = [self.e["jobs"][0], trial, self.e["jobs"][3]]
        self.c["expected_candidate_ids"] = ["candidate-failed"]
        self.pin = digest(self.c)
        self.e["contract_digest"] = self.pin
        self.assertEqual(self.run_audit()["conditional_outcome"], "Inconclusive")
        self.e["stop_reason"] = "budget_stop"
        self.e["completed_at"] = self.c["deadline_at"]
        self.assertEqual(self.run_audit()["conditional_outcome"], "NoUpdate")

    def test_failed_retry_cost_survives_successful_candidate(self):
        failed_job = {
            **copy.deepcopy(self.e["jobs"][1]),
            "job_id": "failed-retry",
            "status": "failed",
            "receipt_digest": digest("failed-retry"),
        }
        self.e["jobs"].append(failed_job)
        self.e["candidates"][0]["job_ids"].append("failed-retry")
        self.e["candidates"][0]["gates"]["external_net_gain"] = "PASS"
        result = self.run_audit()
        self.assertEqual(
            (result["conditional_outcome"], result["costs"]["total"]),
            ("Adoptable", 45.0),
        )
        self.e["jobs"][1]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "construction job missing"):
            self.run_audit()

    def test_early_budget_stop_is_not_a_posthoc_escape(self):
        self.e["stop_reason"] = "budget_stop"
        skipped(self.e, "skipped_budget")
        self.assertEqual(self.run_audit()["conditional_outcome"], "Inconclusive")
        self.e["completed_at"] = self.c["deadline_at"]
        self.assertEqual(self.run_audit()["conditional_outcome"], "NoUpdate")

    def test_unresolved_job_or_candidate_is_not_negative_evidence(self):
        self.e["jobs"].append(
            {
                **copy.deepcopy(self.e["jobs"][1]),
                "job_id": "unresolved-retry",
                "status": "unresolved",
                "receipt_digest": None,
            }
        )
        self.e["candidates"][0]["job_ids"].append("unresolved-retry")
        self.assertEqual(self.run_audit()["conditional_outcome"], "Inconclusive")

    def test_unknown_evaluation_gate_is_not_rejection(self):
        self.e["candidates"][0]["gates"]["retention"] = "HOLD"
        self.assertEqual(self.run_audit()["conditional_outcome"], "Inconclusive")

    def test_source_pin_and_terminal_inventory_mutation_fail(self):
        self.c["source_bundle_digest"] = digest("different-source")
        self.e["contract_digest"] = digest(self.c)
        with self.assertRaisesRegex(ValueError, "externally pinned contract"):
            self.run_audit()
        self.c, self.e = fixture()
        self.e["jobs"][0]["costs"]["encoder"] += 1
        with self.assertRaisesRegex(ValueError, "terminal inventory"):
            self.run_audit(rebind=False)

    def test_self_declared_authentication_is_not_accepted(self):
        self.e["native_receipts_verified"] = True
        with self.assertRaisesRegex(ValueError, "exact fields"):
            self.run_audit()

    def test_same_identity_cannot_evaluate_itself(self):
        self.c["evaluator_id"] = self.c["trainer_id"]
        self.pin = digest(self.c)
        self.e["contract_digest"] = self.pin
        with self.assertRaisesRegex(ValueError, "independent evaluator"):
            self.run_audit()

    def test_zero_delta_and_unbound_evaluation_receipt_rejected(self):
        self.e["candidates"][0]["manifest_digest"] = self.c["incumbent_manifest_digest"]
        with self.assertRaisesRegex(ValueError, "zero delta"):
            self.run_audit()
        self.e["candidates"][0]["manifest_digest"] = digest("candidate-model")
        self.e["candidates"][0]["evaluation_receipt_digest"] = digest(
            "unrelated-evaluation"
        )
        with self.assertRaisesRegex(ValueError, "receipt mismatched"):
            self.run_audit()

    def test_actual_incumbent_use_requires_separate_bound_receipt(self):
        result = self.run_audit()
        self.assertEqual(
            result["incumbent_continuation"],
            {"status": "NOT_SUPPLIED", "verified": False},
        )
        receipt = continuation(self.c, self.e)
        result = self.run_audit(next_task=receipt)
        self.assertFalse(result["incumbent_continuation"]["verified"])
        self.assertEqual(result["outcome"], "Inconclusive")
        for field, value in (
            ("manifest_digest", digest("different-model")),
            ("run_id", self.c["source_run_id"]),
            ("purpose", "agentd.cell-generation.replace"),
        ):
            bad = {**receipt, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_audit(next_task=bad)

    def test_evaluation_binds_constructed_artifact_and_cannot_precede_reconstruction(
        self,
    ):
        for index in (1, 2):
            with self.subTest(job=index):
                contract, evidence = fixture()
                evidence["jobs"][index]["artifact_digest"] = digest("unrelated-model")
                bind_terminal(contract, evidence)
                with self.assertRaisesRegex(ValueError, "artifact does not match"):
                    audit(contract, evidence, expected_contract_digest=digest(contract))
        later = {
            **copy.deepcopy(self.e["jobs"][1]),
            "job_id": "later-construction",
            "started_at": "2026-11-01T00:06:00Z",
            "ended_at": "2026-11-01T00:06:30Z",
            "receipt_digest": digest("later-construction"),
        }
        self.e["jobs"].append(later)
        self.e["candidates"][0]["job_ids"].append(later["job_id"])
        with self.assertRaisesRegex(
            ValueError, "evaluation precedes successful construction"
        ):
            self.run_audit()

    def test_no_data_terminal_evaluation_requires_a_separate_metered_job(self):
        self.e["data_admission"].update(eligible_rows=0, excluded_rows=10)
        self.e["stop_reason"] = "no_eligible_data"
        skipped(self.e, "skipped_no_data")
        self.e["jobs"] = self.e["jobs"][:1]
        result = self.run_audit()
        self.assertEqual(result["conditional_outcome"], "Inconclusive")
        self.assertIn("missing_terminal_evaluation_meter_job", result["reasons"])
        self.assertEqual(
            (
                result["costs"]["known_subtotal"],
                result["costs"]["recorded_ledger_total"],
                result["costs"]["total"],
                result["costs"]["coverage"],
            ),
            (9.0, 9.0, None, "incomplete"),
        )
        self.assertIn("terminal_meter:terminal-meter-job", result["costs"]["unknowns"])
        self.e["jobs"] = []
        self.e["data_admission"] = None
        empty = self.run_audit()
        self.assertEqual(
            (empty["costs"]["known_subtotal"], empty["costs"]["total"]), (0.0, None)
        )
        self.assertIn("job_inventory:missing", empty["costs"]["unknowns"])
        self.c, self.e = fixture()
        self.e["jobs"][3]["receipt_digest"] = None
        missing = self.run_audit()
        self.assertEqual(
            (missing["costs"]["known_subtotal"], missing["costs"]["total"]),
            (36.0, None),
        )
        self.c, self.e = fixture()
        self.e["jobs"][1]["receipt_digest"] = None
        missing = self.run_audit()
        self.assertEqual(
            (missing["costs"]["recorded_ledger_total"], missing["costs"]["total"]),
            (36.0, None),
        )
        self.assertIn("job_meter:training-job", missing["costs"]["unknowns"])
        self.c, self.e = fixture()
        self.e["jobs"][3]["receipt_digest"] = digest("terminal-evaluation")
        with self.assertRaisesRegex(ValueError, "meter receipt must differ"):
            self.run_audit()
        self.c, self.e = fixture()
        self.e["jobs"][3]["artifact_digest"] = digest("terminal-evaluation")
        with self.assertRaisesRegex(
            ValueError, "cannot bind the signed terminal artifact"
        ):
            self.run_audit()

    def test_training_and_search_cannot_hide_in_unowned_shared_work(self):
        for phase in ("training", "search"):
            with self.subTest(phase=phase):
                contract, evidence = fixture()
                evidence["jobs"].append(
                    {
                        **copy.deepcopy(evidence["jobs"][1]),
                        "job_id": "unowned-job",
                        "candidate_id": None,
                        "phase": phase,
                    }
                )
                bind_terminal(contract, evidence)
                with self.assertRaisesRegex(
                    ValueError, "must belong to a registered candidate"
                ):
                    audit(contract, evidence, expected_contract_digest=digest(contract))

    def test_source_checkpoint_is_not_next_task_execution_evidence(self):
        receipt = continuation(self.c, self.e)
        receipt["checkpoint_digest"] = self.c["incumbent_checkpoint_digest"]
        with self.assertRaisesRegex(ValueError, "distinct owner checkpoint"):
            self.run_audit(next_task=receipt)


if __name__ == "__main__":
    unittest.main()

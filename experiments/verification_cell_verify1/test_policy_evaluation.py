"""Real SQLite composition fixtures, not independent business-task evidence."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .check_opportunities import CheckOpportunityJournal
from .checker_effects import CheckerSpec, EffectScope, PairedPanel, fit_checker_effects
from .contracts import digest
from .cost_ledger import CostItem, CostReceipt
from .policy_evaluation import evaluate_policy_journals, freeze_evaluation_spec
from .prospective import FrozenAttempt, ShadowJournal
from .shadow_risk import Prediction, Snapshot, Target, TerminalLabel
from .shadow_schedule import observation_context
from .treatment import TreatmentJournal


class PolicyEvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.target = Target("fixture", "named_property_wrong", 3, digest("readonly"))
        self.roster = tuple(
            FrozenAttempt(str(i), "one-fixture-source", digest(i)) for i in range(3)
        )
        self.snapshots = tuple(
            Snapshot(
                row.trajectory_id,
                row.source_group,
                row.subject_sha256,
                self.target,
                0,
                (1,),
            )
            for row in self.roster
        )
        self.checker = CheckerSpec("readback", digest("checker"), 0.1)
        scope = EffectScope(
            self.target.domain,
            self.target.event,
            0,
            3,
            self.target.continuation_policy_sha256,
            observation_context(self.snapshots[0]),
        )
        panels = tuple(
            PairedPanel(
                str(i),
                "training",
                digest([i, "subject"]),
                scope,
                ("readback",),
                (self.checker.version_sha256,),
                ("fail" if i % 2 else "pass",),
                bool(i % 2),
                digest([i, "label"]),
                (digest([i, "reply"]),),
            )
            for i in range(8)
        )
        self.effects = fit_checker_effects(
            panels,
            scope=scope,
            checkers=(self.checker,),
            training_groups=("training",),
            heldout_groups=("one-fixture-source",),
        )
        self.policies, self.items, self.receipts = {}, {}, {}
        for policy in ("fixed", "learned", "none", "oracle"):
            shadow = ShadowJournal.create(
                self.directory / (policy + ".sqlite"),
                target=self.target,
                roster=self.roster,
                frontiers=(0, 2),
                risk_model_sha256=digest([policy, "risk"]),
                checker_model_sha256=self.effects.model_sha256,
                scheduler_sha256=digest(policy),
                producer_id="fixture-producer",
                evaluator_id="fixture-reader",
                evaluator_version_sha256=digest("fixture-rubric"),
            )
            self.policies[policy] = TreatmentJournal.create(shadow, (self.checker,))
            self.items[policy] = (
                CostItem(policy + "/base", "run", "other", policy, "clock"),
            ) + tuple(
                CostItem(
                    policy + "/" + row.trajectory_id,
                    row.trajectory_id,
                    "checker",
                    policy,
                    "clock",
                )
                for row in self.roster
            )
            self.receipts[policy] = [
                CostReceipt(
                    item,
                    "completed" if i == 0 else "not_run",
                    0,
                    10**9 if i == 0 else 0,
                    0.2 if i == 0 else 0,
                    100 if i == 0 else 0,
                    1 if i == 0 else 0,
                    0,
                    digest([policy, i, "cost"]),
                    (),
                )
                for i, item in enumerate(self.items[policy])
            ]
        self.spec = freeze_evaluation_spec(
            self.items,
            utility_unit="fixture-loss",
            rates=dict(
                wall_seconds=1,
                process_cpu_seconds=0,
                energy_joules=0,
                external_charge=0,
            ),
            losses=dict(
                accept=dict(correct=0, error=10),
                reject=dict(correct=2, error=0),
                interrupted=dict(correct=1, error=1),
                unknown=dict(correct=3, error=3),
            ),
        )
        self.opportunities = CheckOpportunityJournal.create(
            self.policies["fixed"],
            policies={
                name: journal.shadow.manifest_sha256
                for name, journal in self.policies.items()
            },
            frontier=0,
            checker_id="readback",
            offer_numerator=1,
            offer_denominator=2,
            free_view_schema_sha256=digest("all-fixture-acks"),
            mandatory_contract_sha256=digest("host-gates"),
            evaluation_spec_sha256=digest(self.spec),
        )
        self.predictions = {}

    def observe(self, *, bind=True, probability=0.3):
        for i, snapshot in enumerate(self.snapshots):
            for name, journal in self.policies.items():
                prediction = Prediction(
                    snapshot, (probability, 0.25, None)[i], digest([name, "risk"])
                )
                journal.shadow.record(prediction)
                self.predictions[name, str(i)] = prediction
            # A fixed draw is only a software test fixture, never claimed random-source evidence.
            with patch(
                "experiments.verification_cell_verify1.check_opportunities.secrets.randbelow",
                return_value=0,
            ):
                self.opportunities.reserve(
                    str(i),
                    digest([i, "original-free-bytes"]),
                    eligible=True,
                    eligibility_evidence_sha256=digest([i, "eligible"]),
                )
            if bind:
                for name, journal in self.policies.items():
                    if name != "fixed":
                        self.opportunities.bind_policy(
                            journal,
                            str(i),
                            free_evidence_sha256=digest([i, "original-free-bytes"]),
                        )

    def finish(
        self,
        truths=(True, False, False),
        *,
        missing_last=False,
        dispositions=("accept", "reject", "unknown"),
    ):
        for journal in self.policies.values():
            for i, (disposition, truth) in enumerate(zip(dispositions, truths)):
                journal.record_disposition(
                    str(i),
                    disposition,
                    hard_checks_complete=True,
                    gate_evidence_sha256=digest([i, "original-gate"]),
                )
                journal.shadow.finish(str(i), disposition)
                if missing_last and i == 2:
                    continue
                label = TerminalLabel(
                    str(i),
                    "one-fixture-source",
                    digest(i),
                    self.target,
                    disposition,
                    truth,
                    3,
                    digest([i, "fixture-truth"]) if truth is not None else None,
                    "fixture-unobserved" if truth is None else None,
                )
                # Original legacy fixture path; deliberately not independent authentication.
                journal.shadow.label(
                    label,
                    evaluator_id="fixture-reader",
                    authenticate=lambda *args: True,
                )

    def evaluate(self, **changes):
        options = dict(
            specification=self.spec,
            cost_rosters=self.items,
            cost_receipts=self.receipts,
        )
        options.update(changes)
        return evaluate_policy_journals(self.opportunities, self.policies, **options)

    def start_check(self, operation_id="learned/0"):
        journal = self.policies["learned"]
        choice = journal.choose(
            self.predictions["learned", "0"],
            self.effects,
            (),
            ("accept", "reject"),
            ((0, 100), (5, 5)),
            1,
            hard_checks_complete=True,
        )
        self.assertEqual(choice["status"], "check")
        self.opportunities.start_optional(
            journal, choice["record_sha256"], operation_id
        )
        return journal

    def test_four_actual_journals_join_original_opportunities_and_keep_qualification_hold(
        self,
    ):
        self.observe()
        self.finish()
        result = self.evaluate()
        self.assertTrue(result["common_free_snapshot_bindings_complete"])
        row = result["policies"]["learned"]
        self.assertEqual(
            (
                row["planned"],
                row["accepted_count"],
                row["observed_false_accept_count"],
                row["postdecision_clean_reject_count"],
                row["by_disposition"]["unknown"],
            ),
            (3, 1, 1, 1, 1),
        )
        self.assertEqual(row["observed_accepted_error_bounds"], [1, 1])
        self.assertAlmostEqual(row["declared_mean_net_utility"], -5 - 1 / 3)
        self.assertIsNone(row["property_or_authority_false_reject_rate"])
        self.assertEqual(
            row["label_authentication"]["legacy_labels_without_attestations"], 3
        )
        self.assertFalse(row["label_authentication"]["all_roster_labels_reverified"])
        self.assertEqual(result["scientific_admission"], "HOLD")
        self.assertEqual(self.evaluate(), result)

    def test_missing_outcomes_predictions_and_costs_keep_planned_denominators(self):
        self.observe()
        self.finish(missing_last=True)
        self.receipts["learned"] = []
        row = self.evaluate()["policies"]["learned"]
        self.assertEqual(
            (
                row["planned"],
                row["known_terminal_labels"],
                row["missing_terminal_label_records"],
                row["unknown_terminal_labels"],
            ),
            (3, 2, 1, 1),
        )
        self.assertEqual(row["calibration"]["missing_or_unsupported_predictions"], 1)
        self.assertIsNone(row["declared_mean_net_utility"])
        self.assertIsNone(row["cost"]["totals"]["wall_seconds"])

    def test_unmeasured_energy_never_becomes_complete_zero_priced_utility(self):
        self.observe()
        self.finish()
        self.receipts["learned"][0] = replace(
            self.receipts["learned"][0],
            energy_joules=None,
            measurement_gaps=("energy unavailable",),
        )
        row = self.evaluate()["policies"]["learned"]
        self.assertEqual(row["cost"]["declared_receipt_utility"], 1)
        self.assertIsNone(row["declared_mean_net_utility"])

    def test_missing_consumption_cannot_be_called_shared_information(self):
        self.observe(bind=False)
        result = self.evaluate()
        self.assertFalse(result["common_free_snapshot_bindings_complete"])
        self.assertEqual(
            result["policies"]["learned"]["opportunity_consumption"][
                "missing_consumption_ids"
            ],
            ["0", "1", "2"],
        )
        self.assertIsNone(
            result["policies"]["learned"]["observed_accepted_error_bounds"]
        )

    def test_posthoc_spec_or_cost_denominator_change_refuses(self):
        for key, value in (
            ("rates", {**self.spec["rates"], "wall_seconds": 0}),
            ("bins", [0, 0.5, 1]),
            ("losses", {**self.spec["losses"], "reject": dict(correct=0, error=0)}),
        ):
            specification = {**self.spec, key: value}
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "after freeze"),
            ):
                self.evaluate(specification=specification)
        with self.assertRaisesRegex(ValueError, "after freeze"):
            self.evaluate(
                cost_rosters={**self.items, "learned": self.items["learned"][:1]},
                cost_receipts={
                    **self.receipts,
                    "learned": self.receipts["learned"][:1],
                },
            )

    def test_extreme_wrong_probability_preserves_infinite_log_loss(self):
        self.observe(probability=0)
        self.finish()
        metrics = self.evaluate()["policies"]["learned"]["calibration"]
        self.assertEqual(metrics["infinite_log_loss_count"], 1)
        self.assertIsNone(metrics["log_loss_known"])
        self.assertAlmostEqual(metrics["brier_known"], 0.53125)

    def test_same_physical_journal_cannot_count_as_two_policies(self):
        self.policies["learned"] = TreatmentJournal(
            ShadowJournal(self.policies["fixed"].shadow.path)
        )
        with self.assertRaisesRegex(ValueError, "physical policy journal"):
            self.evaluate()

    def test_revalidate_corrupted_frozen_cost_dataclasses(self):
        for attribute, value in (
            ("process_cpu_seconds", -1),
            ("finished_ns", -1),
            ("status", "unregistered"),
        ):
            receipts = deepcopy(self.receipts)
            object.__setattr__(receipts["learned"][0], attribute, value)
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                self.evaluate(cost_receipts=receipts)
        items = deepcopy(self.items)
        object.__setattr__(items["learned"][0], "stage", "unregistered")
        with self.assertRaises(ValueError):
            self.evaluate(cost_rosters=items)

    def test_original_optional_execution_cannot_be_reported_not_run_or_cheaper(self):
        self.observe()
        journal = self.start_check()
        with self.assertRaisesRegex(ValueError, "not-run"):
            self.evaluate()
        item = self.items["learned"][1]
        measured = CostReceipt(
            item,
            "completed",
            10**9,
            2 * 10**9,
            0.2,
            100,
            1,
            0,
            digest("optional-cost"),
            (),
        )
        self.receipts["learned"][1] = measured
        journal.complete(
            "learned/0",
            "fail",
            digest("original-checker-reply"),
            dict(wall_seconds=1, cpu_seconds=0.2, energy_joules=1),
        )
        self.finish()
        row = self.evaluate()["policies"]["learned"]
        self.assertEqual(
            (
                row["actual_optional_starts"],
                row["actual_optional_completions"],
                row["pending_optional_operation_ids"],
            ),
            (1, 1, []),
        )
        self.assertEqual(row["exposure_at_disposition"]["checked"], 1)
        self.receipts["learned"][1] = replace(measured, process_cpu_seconds=0)
        with self.assertRaisesRegex(ValueError, "contradicts its original"):
            self.evaluate()

    def test_frozen_cost_roster_cannot_omit_an_actual_optional_start(self):
        self.observe()
        self.start_check("not-in-frozen-cost-roster")
        with self.assertRaisesRegex(ValueError, "actual optional operation missing"):
            self.evaluate()

    def test_pending_original_operation_keeps_net_utility_unavailable(self):
        self.observe()
        self.start_check()
        self.receipts["learned"][1] = replace(
            self.receipts["learned"][1], status="completed"
        )
        self.finish(dispositions=("reject", "reject", "unknown"))
        row = self.evaluate()["policies"]["learned"]
        self.assertEqual(row["pending_optional_operation_ids"], ["learned/0"])
        self.assertTrue(row["cost"]["declared_roster_complete"])
        self.assertIsNotNone(row["declared_mean_terminal_utility"])
        self.assertIsNone(row["declared_mean_net_utility"])


if __name__ == "__main__":
    unittest.main()

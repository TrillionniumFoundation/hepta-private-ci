"""Manufactured execution records test accounting, never actual policy benefit."""

from copy import deepcopy
import unittest

from .macro_cohort import FACTORIAL, digest, evaluate, validate_plan


def plan_fixture():
    arms = []
    for cell, (content, control) in FACTORIAL.items():
        arms.append(
            {
                "arm_id": cell,
                "content_mode": content,
                "control_mode": control,
                "policy": "conditional" if control == "on" else "light",
                "content_sha256": ("a" if content == "off" else "b") * 64,
                "critic_context_sha256": ("c" if content == "off" else "d") * 64,
            }
        )
    return {
        "schema": "ndu.real.macro-cohort.v1",
        "contexts": [
            {"source_id": "a", "case_id": "one", "seed": 7},
            {"source_id": "b", "case_id": "one", "seed": 7},
            {"source_id": "b", "case_id": "two", "seed": 11},
        ],
        "arms": arms,
        "partitions": {
            "fit": ["fit"],
            "calibration": ["cal"],
            "evaluation": ["a", "b"],
        },
        "shared": {
            key: "e" * 64
            for key in (
                "action_sha256",
                "legal_actions_sha256",
                "settlement_sha256",
                "evaluator_sha256",
                "utility_sha256",
                "tariff_sha256",
            )
        },
        "one_off_costs": {
            arm["arm_id"]: {"fit": 0.3, "calibration": 0.0, "tuning": 0.0}
            for arm in arms
        },
        "factorial": {cell: cell for cell in FACTORIAL},
    }


def rows_fixture(plan):
    rows = []
    for context in plan["contexts"]:
        for arm in plan["arms"]:
            rows.append(
                {
                    **context,
                    "arm_id": arm["arm_id"],
                    "status": "COMPLETED",
                    "execution_id": f"execution-{len(rows)}",
                    "shared_sha256": digest(plan["shared"]),
                    "content_sha256": arm["content_sha256"],
                    "critic_context_sha256": arm["critic_context_sha256"],
                    "quality": 0.0 if context["source_id"] == "a" else 1.0,
                    "task_cost": 0.02,
                    "full_cost_observed": True,
                    "evidence_sha256": "f" * 64,
                    "evidence_kind": "fixture",
                }
            )
    return rows


class RegisteredMacroCohortTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan_fixture()
        self.rows = rows_fixture(self.plan)
        self.pin = digest(self.plan)

    def report(self, rows=None, plan=None):
        return evaluate(
            self.plan if plan is None else plan,
            self.rows if rows is None else rows,
            expected_plan_sha256=self.pin,
            allow_fixtures=True,
        )

    def test_complete_factorial_uses_source_equal_full_cost_values(self):
        report = self.report()
        self.assertEqual(report["planned_executions"], 12)
        self.assertTrue(report["registered_full_cost_comparison_complete"])
        self.assertEqual(report["arms"]["off_off"]["primary_quality"], 0.5)
        self.assertAlmostEqual(report["arms"]["off_off"]["primary_full_cost_net"], 0.38)
        self.assertAlmostEqual(report["factorial"]["source_equal_interaction"], 0.0)
        changed = deepcopy(self.rows)
        for row in changed:
            if row["arm_id"] == "on_on":
                row["quality"] = 0.8
        self.assertAlmostEqual(
            self.report(changed)["factorial"]["source_equal_interaction"], 0.3
        )

    def test_entire_source_omission_cannot_shrink_denominator(self):
        report = self.report([r for r in self.rows if r["source_id"] != "a"])
        arm = report["arms"]["off_off"]
        self.assertEqual((arm["planned"], arm["planned_sources"]), (3, 2))
        self.assertEqual((arm["missing_records"], arm["statuses"]["UNKNOWN"]), (1, 1))
        self.assertIsNone(arm["primary_quality"])
        self.assertIsNone(arm["primary_full_cost_net"])
        self.assertEqual(arm["observed_subset"]["quality"], 1)
        self.assertIsNone(report["factorial"]["source_equal_interaction"])

    def test_absent_arm_remains_in_report_and_swapped_seed_is_rejected(self):
        report = self.report([r for r in self.rows if r["arm_id"] != "on_on"])
        self.assertEqual(report["arms"]["on_on"]["missing_records"], 3)
        self.assertIsNone(report["factorial"]["source_equal_interaction"])
        for field, replacement in (
            ("seed", 999),
            ("case_id", "replaced"),
            ("seed", True),
        ):
            rows = deepcopy(self.rows)
            rows[0][field] = replacement
            with (
                self.subTest(field=field, replacement=replacement),
                self.assertRaises(ValueError),
            ):
                self.report(rows)

    def test_unresolved_terminal_states_preserve_cost_without_score(self):
        for status in ("NOT_STARTED", "RUNNING", "UNKNOWN", "FAILED", "CANCELLED"):
            rows = deepcopy(self.rows)
            rows[0].update(status=status, quality=None, task_cost=0.05)
            if status == "NOT_STARTED":
                rows[0]["execution_id"] = None
            report = self.report(rows)
            arm = report["arms"]["off_off"]
            with self.subTest(status=status):
                self.assertEqual(arm["statuses"][status], 1)
                self.assertAlmostEqual(arm["observed_task_cost_total"], 0.09)
                self.assertIsNone(arm["primary_full_cost_net"])

    def test_observed_zero_remains_distinct_from_missing_outcome(self):
        self.assertEqual(self.report()["arms"]["off_off"]["admitted_completed"], 3)
        rows = deepcopy(self.rows)
        rows[0].update(status="UNKNOWN", quality=None)
        arm = self.report(rows)["arms"]["off_off"]
        self.assertEqual(arm["admitted_completed"], 2)
        self.assertIsNone(arm["primary_quality"])
        rows[0]["quality"] = 0.0
        with self.assertRaises(ValueError):
            self.report(rows)

    def test_missing_costs_and_one_off_cost_never_become_free(self):
        rows = deepcopy(self.rows)
        rows[0].update(task_cost=None, full_cost_observed=False)
        self.assertIsNone(self.report(rows)["arms"]["off_off"]["primary_full_cost_net"])
        self.plan["one_off_costs"]["off_off"]["calibration"] = None
        self.pin = digest(self.plan)
        report = self.report()
        self.assertIsNone(report["arms"]["off_off"]["one_off_cost_total"])
        self.assertIsNone(report["factorial"]["source_equal_interaction"])

    def test_measured_contrasts_remain_available_with_unknown_full_costs(self):
        for costs in self.plan["one_off_costs"].values():
            costs.update(fit=None, calibration=None, tuning=None)
        self.pin = digest(self.plan)
        for row in self.rows:
            row["full_cost_observed"] = False
            if row["arm_id"] == "on_on":
                row["quality"] = 0.8
                row["task_cost"] = 0.1 if row["source_id"] == "a" else 0.2
        report = self.report()
        arm = report["arms"]["on_on"]
        self.assertAlmostEqual(arm["primary_observed_task_cost_net"], 0.65)
        self.assertIsNone(arm["primary_full_cost_net"])
        self.assertIsNone(arm["one_off_cost_total"])
        pair = next(
            p
            for p in report["paired_contrasts"]
            if (p["candidate"], p["baseline"]) == ("off_off", "on_on")
        )
        self.assertAlmostEqual(pair["quality"]["source_equal_difference"], -0.3)
        self.assertAlmostEqual(
            pair["observed_task_cost_net"]["source_equal_difference"], -0.17
        )
        factorial = report["factorial"]
        self.assertAlmostEqual(factorial["quality"]["source_equal_interaction"], 0.3)
        self.assertAlmostEqual(
            factorial["observed_task_cost_net"]["source_equal_interaction"], 0.17
        )
        self.assertIsNone(pair["source_equal_full_cost_difference"])
        self.assertIsNone(factorial["source_equal_interaction"])
        self.assertFalse(report["registered_full_cost_comparison_complete"])
        self.assertFalse(report["adoption_authorized"])
        self.assertEqual(report["decision"], "NoUpdate")

    def test_missing_record_keeps_measured_pair_and_factorial_denominators(self):
        rows = [r for r in self.rows if (r["source_id"], r["arm_id"]) != ("a", "on_on")]
        report = self.report(rows)
        pair = next(
            p
            for p in report["paired_contrasts"]
            if (p["candidate"], p["baseline"]) == ("off_off", "on_on")
        )
        for metric in ("quality", "observed_task_cost_net"):
            for comparison, field in (
                (pair[metric], "source_equal_difference"),
                (report["factorial"][metric], "source_equal_interaction"),
            ):
                with self.subTest(metric=metric, field=field):
                    self.assertEqual(
                        comparison,
                        {
                            "planned_contexts": 3,
                            "paired_contexts": 2,
                            "planned_sources": 2,
                            "paired_sources": 1,
                            field: None,
                            "observed_subset": {"contexts": 2, "sources": 1, field: 0},
                        },
                    )
        self.assertEqual(report["arms"]["on_on"]["statuses"]["UNKNOWN"], 1)
        self.assertIsNone(report["arms"]["on_on"]["primary_observed_task_cost_net"])

    def test_unknown_task_cost_does_not_hide_known_paired_quality(self):
        rows = deepcopy(self.rows)
        rows[0].update(task_cost=None, full_cost_observed=False)
        report = self.report(rows)
        pair = report["paired_contrasts"][0]
        self.assertEqual(pair["quality"]["paired_contexts"], 3)
        self.assertEqual(pair["quality"]["source_equal_difference"], 0)
        self.assertEqual(pair["observed_task_cost_net"]["paired_contexts"], 2)
        self.assertIsNone(pair["observed_task_cost_net"]["source_equal_difference"])
        self.assertEqual(report["factorial"]["quality"]["source_equal_interaction"], 0)
        self.assertIsNone(
            report["factorial"]["observed_task_cost_net"]["source_equal_interaction"]
        )

    def test_factorial_requires_content_parameter_separation(self):
        # Separate critic labels cannot establish a content-learning treatment.
        plan = deepcopy(self.plan)
        for arm in plan["arms"]:
            if arm["content_mode"] == "on":
                arm["content_sha256"] = plan["arms"][0]["content_sha256"]
        with self.assertRaisesRegex(ValueError, "distinct parameter pins"):
            validate_plan(plan, expected_plan_sha256=digest(plan))

    def test_duplicate_execution_or_context_cannot_fill_two_arms(self):
        for variant in ("execution", "row"):
            rows = deepcopy(self.rows)
            if variant == "execution":
                rows[1]["execution_id"] = rows[0]["execution_id"]
            else:
                rows[1] = deepcopy(rows[0])
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                self.report(rows)

    def test_record_identity_drift_fails_closed(self):
        for field in ("shared_sha256", "content_sha256", "critic_context_sha256"):
            rows = deepcopy(self.rows)
            rows[0][field] = "0" * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.report(rows)

    def test_plan_pin_partition_and_duplicate_roster_are_validated(self):
        plan = deepcopy(self.plan)
        plan["contexts"].pop()
        with self.assertRaises(ValueError):
            self.report(plan=plan)
        for change in ("duplicate", "leak", "missing_source"):
            plan = deepcopy(self.plan)
            if change == "duplicate":
                plan["contexts"].append(deepcopy(plan["contexts"][0]))
            elif change == "leak":
                plan["partitions"]["fit"].append("a")
            else:
                plan["partitions"]["evaluation"].append("absent")
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_plan(plan, expected_plan_sha256=digest(plan))

    def test_factorial_cannot_alias_or_relabel_an_arm(self):
        for change in ("alias", "mode", "content"):
            plan = deepcopy(self.plan)
            if change == "alias":
                plan["factorial"]["on_on"] = "off_off"
            elif change == "mode":
                plan["arms"][0]["content_mode"] = "on"
            else:
                plan["arms"][1]["content_sha256"] = "0" * 64
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_plan(plan, expected_plan_sha256=digest(plan))

    def test_reports_and_validation_do_not_mutate_registered_inputs(self):
        before = deepcopy((self.plan, self.rows))
        self.report()
        _, arms = validate_plan(self.plan, expected_plan_sha256=self.pin)
        arms["off_off"]["content_sha256"] = "0" * 64
        self.assertEqual((self.plan, self.rows), before)

    def test_factorial_rejects_policy_substitution_between_content_modes(self):
        for arm_id, replacement in (("on_off", "STOP"), ("on_on", "point")):
            plan = deepcopy(self.plan)
            for arm in plan["arms"]:
                if arm["arm_id"] == arm_id:
                    arm["policy"] = replacement
            with self.subTest(arm_id=arm_id), self.assertRaises(ValueError):
                validate_plan(plan, expected_plan_sha256=digest(plan))

    def test_fixture_requires_opt_in_and_terminal_needs_evidence(self):
        with self.assertRaises(ValueError):
            evaluate(self.plan, self.rows, expected_plan_sha256=self.pin)
        for field in ("evidence_sha256", "quality", "execution_id"):
            rows = deepcopy(self.rows)
            rows[0][field] = None
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.report(rows)


if __name__ == "__main__":
    unittest.main()

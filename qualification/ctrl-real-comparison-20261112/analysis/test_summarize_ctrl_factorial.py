"""Manufactured arithmetic witnesses; never native execution or benefit evidence."""

from copy import deepcopy
import unittest

from ndu_real_runtime import macro_cohort
import summarize_ctrl_factorial as summarizer


def fixture(contexts):
    arms = [
        {
            "arm_id": mode + "/" + policy,
            "content_mode": "off" if mode == "frozen" else "on",
            "control_mode": "on"
            if policy in {"point", "unconditional", "conditional"}
            else "off",
            "policy": policy,
            "content_sha256": ("a" if mode == "frozen" else "b") * 64,
            "critic_context_sha256": ("c" if mode == "frozen" else "d") * 64,
        }
        for mode in summarizer.MODES
        for policy in summarizer.METHODS
    ]
    plan = {
        "schema": "ndu.real.macro-cohort.v1",
        "contexts": contexts,
        "arms": arms,
        "partitions": {
            "fit": ["training"],
            "calibration": ["calibration"],
            "evaluation": sorted({row["source_id"] for row in contexts}),
        },
        "shared": {key: "e" * 64 for key in macro_cohort.SHARED},
        "one_off_costs": {
            arm["arm_id"]: {key: None for key in ("fit", "calibration", "tuning")}
            for arm in arms
        },
        "factorial": dict(summarizer.FACTORIAL),
    }
    rows = [
        {
            **context,
            "arm_id": arm["arm_id"],
            "status": "COMPLETED",
            "execution_id": f"fixture-{index}-{arm['arm_id']}",
            "shared_sha256": macro_cohort.digest(plan["shared"]),
            "content_sha256": arm["content_sha256"],
            "critic_context_sha256": arm["critic_context_sha256"],
            "quality": 0.0,
            "task_cost": 0.05,
            "full_cost_observed": False,
            "evidence_sha256": "f" * 64,
            "evidence_kind": "fixture",
        }
        for index, context in enumerate(contexts)
        for arm in arms
    ]
    return plan, rows


def retained_report(plan, rows, actions=None):
    return {
        "schema": "ctrl.content-control-factorial-report.v1",
        "factorial_sha256": "9" * 64,
        "plan": plan,
        "rows": rows,
        "cohort": macro_cohort.evaluate(
            plan,
            rows,
            expected_plan_sha256=macro_cohort.digest(plan),
            allow_fixtures=True,
        ),
        "observed_actions": {} if actions is None else actions,
        "matched_initial_physical_frontiers": len(
            {summarizer.context(row) for row in rows if row["status"] == "COMPLETED"}
        ),
    }


class SummaryArithmeticTests(unittest.TestCase):
    def test_complete_48_by_12_hand_arithmetic_reverse_pairs_and_stored_tamper(self):
        plan, rows = fixture(
            [
                {"source_id": f"s{source}", "case_id": f"c{case}", "seed": 7}
                for source in range(16)
                for case in range(3)
            ]
        )
        offsets = {
            "frozen": (0, 0.01, 0.05, 0.03, 0.04, 0.20),
            "adapted": (0.10, 0.11, 0.18, 0.16, 0.19, 0.40),
        }
        costs = {
            "frozen": (0.01, 0.03, 0.02, 0.03, 0.03, 0.05),
            "adapted": (0.02, 0.05, 0.04, 0.05, 0.05, 0.08),
        }
        for row in rows:
            mode, policy = row["arm_id"].split("/")
            index = summarizer.METHODS.index(policy)
            row["quality"] = (
                0.1
                + int(row["source_id"][1:]) * 0.01
                + int(row["case_id"][1:]) * 0.005
                + offsets[mode][index]
            )
            row["task_cost"] = costs[mode][index]
        report = retained_report(plan, rows)
        reversed_pair = next(
            row
            for row in report["cohort"]["paired_contrasts"]
            if row["candidate"] == "frozen/STOP"
            and row["baseline"] == "frozen/conditional"
        )
        self.assertAlmostEqual(
            reversed_pair["quality"]["source_equal_difference"], -0.20
        )
        self.assertEqual(reversed_pair["paired_contexts"], 0)
        result = summarizer.summarize(report, allow_fixtures=True)
        self.assertTrue(result["stored_mean_audit"]["all_match"])
        self.assertTrue(
            result["denominators"]["matches_16_sources_48_contexts_576_executions"]
        )
        self.assertEqual(result["denominators"]["contexts_completed_all_arms"], 48)
        for mode, baseline, quality, net in (
            ("frozen", "STOP", 0.20, 0.16),
            ("frozen", "tuned-fixed", 0.15, 0.12),
            ("adapted", "STOP", 0.30, 0.24),
            ("adapted", "tuned-fixed", 0.22, 0.18),
        ):
            contrast = result["conditional_contrasts"][
                f"{mode}/conditional minus {mode}/{baseline}"
            ]
            for metric, expected in (
                ("quality", quality),
                ("observed_task_cost_net", net),
            ):
                self.assertEqual(
                    (contrast[metric]["contexts"], contrast[metric]["sources"]),
                    (48, 16),
                )
                self.assertAlmostEqual(contrast[metric]["primary"], expected)
        self.assertAlmostEqual(result["factorial_DID"]["quality"]["primary"], 0.10)
        self.assertAlmostEqual(
            result["factorial_DID"]["observed_task_cost_net"]["primary"], 0.08
        )
        self.assertFalse(result["limits"]["full_cost_benefit_established"])
        changed = deepcopy(report)
        pair = next(
            row
            for row in changed["cohort"]["paired_contrasts"]
            if row["candidate"] == "frozen/STOP"
            and row["baseline"] == "frozen/conditional"
        )
        pair["quality"]["source_equal_difference"] += 0.125
        audited = summarizer.summarize(changed, allow_fixtures=True)
        self.assertEqual(audited["stored_mean_audit"]["mismatch_count"], 1)
        self.assertFalse(audited["stored_mean_audit"]["all_match"])
        self.assertAlmostEqual(
            audited["conditional_contrasts"]["frozen/conditional minus frozen/STOP"][
                "quality"
            ]["primary"],
            0.20,
        )

    def test_unequal_sources_missing_row_and_unknown_cost_use_four_cell_intersection(
        self,
    ):
        contexts = [
            {"source_id": "a" if i == 0 else "b", "case_id": str(i), "seed": 7}
            for i in range(4)
        ]
        plan, rows = fixture(contexts)
        qualities = {
            "frozen/STOP": [0, 0.1, 0.2, 0.3],
            "frozen/conditional": [0.9, 0.5, 0.3, 0.4],
            "adapted/STOP": [0.2, 0.2, 0.2, 0.2],
            "adapted/conditional": [0.6, 0.9, 0.7, 0.5],
        }
        for row in rows:
            if row["arm_id"] in qualities:
                row["quality"] = qualities[row["arm_id"]][int(row["case_id"])]
            if (row["arm_id"], row["case_id"]) == ("frozen/STOP", "2"):
                row["task_cost"] = None
            if (row["arm_id"], row["case_id"]) == ("frozen/light", "0"):
                row.update(status="FAILED", quality=None, task_cost=0.4)
        rows = [
            row
            for row in rows
            if (row["arm_id"], row["case_id"]) != ("adapted/conditional", "0")
        ]
        result = summarizer.summarize(retained_report(plan, rows), allow_fixtures=True)
        self.assertTrue(result["stored_mean_audit"]["all_match"])
        self.assertEqual(result["denominators"]["missing_records"], 1)
        frozen = result["conditional_contrasts"]["frozen/conditional minus frozen/STOP"]
        adapted = result["conditional_contrasts"][
            "adapted/conditional minus adapted/STOP"
        ]
        self.assertAlmostEqual(frozen["quality"]["primary"], 0.55)
        self.assertIsNone(frozen["observed_task_cost_net"]["primary"])
        self.assertAlmostEqual(
            frozen["observed_task_cost_net"]["observed_subset"], 0.575
        )
        self.assertEqual(
            (
                frozen["observed_task_cost_net"]["contexts"],
                frozen["observed_task_cost_net"]["sources"],
            ),
            (3, 2),
        )
        self.assertIsNone(adapted["quality"]["primary"])
        self.assertAlmostEqual(adapted["quality"]["observed_subset"], 0.5)
        for metric, count, mean in (
            ("quality", 3, 0.3),
            ("observed_task_cost_net", 2, 0.25),
        ):
            did = result["factorial_DID"][metric]
            self.assertIsNone(did["primary"])
            self.assertEqual((did["contexts"], did["sources"]), (count, 1))
            self.assertAlmostEqual(did["observed_subset"], mean)
        naive = (
            adapted["quality"]["observed_subset"] - frozen["quality"]["observed_subset"]
        )
        self.assertAlmostEqual(naive, -0.05)
        self.assertNotAlmostEqual(
            result["factorial_DID"]["quality"]["observed_subset"], naive
        )
        light = result["arms"]["frozen/light"]
        self.assertAlmostEqual(
            light["observed_task_cost_total_including_failures"], 0.55
        )
        self.assertEqual(light["quality"]["contexts"], 3)
        self.assertAlmostEqual(result["arms"]["frozen/STOP"]["quality"]["primary"], 0.1)

    def test_actions_preserve_unknowns_seed_ambiguity_and_completed_multiset(self):
        plan, rows = fixture(
            [
                {"source_id": "s", "case_id": "c", "seed": 0},
                {"source_id": "s", "case_id": "c", "seed": 1},
                {"source_id": "t", "case_id": "d", "seed": 0},
            ]
        )
        arm = "frozen/conditional"
        for row in rows:
            if row["arm_id"] == arm and row["seed"] == 1:
                row.update(status="UNKNOWN", quality=None, task_cost=None)
        actions = {
            arm: [
                {
                    "source_id": "s",
                    "case_id": "c",
                    "macro": "READ",
                    "read_attribution": {
                        "read_executed": True,
                        "selected_text_changed": True,
                        "candidate_inventory_changed": False,
                    },
                },
                {
                    "source_id": "t",
                    "case_id": "d",
                    "macro": "STOP",
                    "read_attribution": {"read_executed": False},
                },
            ]
        }
        report = retained_report(plan, rows, actions)
        result = summarizer.summarize(report, allow_fixtures=True)
        observed = result["arms"][arm]["actions"]
        self.assertEqual(
            (
                observed["READ"],
                observed["STOP"],
                observed["missing_for_completed"],
                observed["unresolved_planned"],
            ),
            (1, 1, 0, 1),
        )
        self.assertTrue(observed["matches_completed_multiset"])
        self.assertEqual(observed["seed_ambiguous_records"], 1)
        self.assertEqual(
            result["read_flag_count_order"], ["known", "true", "false", "unknown"]
        )
        flags = dict(zip(result["read_flag_columns"], observed["read_flag_counts"]))
        self.assertEqual(flags["selected_text_changed"], [1, 1, 0, 0])
        self.assertEqual(flags["candidate_inventory_changed"], [1, 0, 1, 0])
        self.assertEqual(flags["semantic_information_gain"], [0, 0, 0, 1])
        absent = result["arms"]["frozen/STOP"]["actions"]
        self.assertEqual(absent["missing_for_completed"], 3)
        self.assertFalse(absent["matches_completed_multiset"])
        self.assertTrue(all(row == [0, 0, 0, 0] for row in absent["read_flag_counts"]))
        excess = deepcopy(report)
        excess["observed_actions"][arm].append(deepcopy(actions[arm][0]))
        with self.assertRaisesRegex(ValueError, "exceeds completed"):
            summarizer.summarize(excess, allow_fixtures=True)
        for malformed in (False, 0, []):
            changed = deepcopy(report)
            changed["observed_actions"][arm][0]["read_attribution"] = malformed
            with self.subTest(attribution=malformed), self.assertRaises(ValueError):
                summarizer.summarize(changed, allow_fixtures=True)
        changed = deepcopy(report)
        changed["rows"][0]["seed"] = False
        with self.assertRaises(ValueError):
            summarizer.summarize(changed, allow_fixtures=True)


if __name__ == "__main__":
    unittest.main()

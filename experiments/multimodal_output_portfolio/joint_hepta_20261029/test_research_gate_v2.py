"""Acceptance failures, source pairing, and lifecycle-cost sensitivity."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .research_gate_v2 import (LIFECYCLE_COMPONENTS, analyse_panel,
                               claim_confirmation, default_plan, read_seal, seal_plan)


def small_plan(stage="development"):
    plan = default_plan(stage)
    plan.update(arms=["candidate", "baseline"], widths=[8], source_ids=[0, 1, 2],
                seeds=[17, 29] if stage == "development" else [101, 211],
                bootstrap_replicates=400,
                comparisons=[{"id": "effect", "left": "candidate", "right": "baseline",
                              "metric": "net_ce", "threshold": 0.0}])
    return plan


def measured_rows(plan, improvement=0.1):
    rows = []
    for width in plan["widths"]:
        for seed in plan["seeds"]:
            for source in plan["source_ids"]:
                for draw in range(plan["draws_per_source"]):
                    for arm in plan["arms"]:
                        # Common stochastic context must cancel in a paired shift.
                        utility = 0.3 + 0.05 * source + 0.01 * (seed % 7) + 0.001 * draw
                        utility += improvement if arm == "candidate" else 0
                        rows.append({"width": width, "seed": seed, "source": source,
                                     "draw": draw, "arm": arm, "utility": utility,
                                     "net_with_audit_close": utility - 0.02,
                                     "failure": None, "profile_sha256": "a" * 64,
                                     "source_namespace": plan["source_namespace"]})
    return rows


def ledger(plan):
    return {f"{seed}:{width}:{arm}": {component: 0.0 for component in LIFECYCLE_COMPONENTS}
            for seed in plan["seeds"] for width in plan["widths"] for arm in plan["arms"]}


class ResearchGateTests(unittest.TestCase):
    def test_paired_shift_survives_crossed_resampling(self):
        plan = small_plan()
        report = analyse_panel(plan, measured_rows(plan))
        effect = report["effects"][0]
        self.assertAlmostEqual(effect["difference"], 0.1, places=12)
        for bound in effect["bonferroni_interval"]:
            self.assertAlmostEqual(bound, 0.1, places=12)
        self.assertTrue(report["development_admission_pass"])
        self.assertFalse(report["research_qualified"])

    def test_missing_duplicate_namespace_and_profile_fail_closed(self):
        plan = small_plan()
        rows = measured_rows(plan)
        changes = [rows[:-1], rows + [rows[0]]]
        for key, value in (("source_namespace", "test"), ("profile_sha256", "b" * 64),
                           ("net_with_audit_close", float("nan"))):
            changed = deepcopy(rows)
            changed[0][key] = value
            changes.append(changed)
        for changed in changes:
            with self.subTest(rows=len(changed)), self.assertRaises(ValueError):
                analyse_panel(plan, changed)

    def test_one_training_seed_regression_blocks_admission(self):
        plan = small_plan()
        rows = measured_rows(plan, improvement=0.4)
        for row in rows:
            if row["seed"] == 29 and row["arm"] == "candidate":
                row["utility"] -= 0.5
                row["net_with_audit_close"] -= 0.5
        report = analyse_panel(plan, rows)
        self.assertFalse(report["development_admission_pass"])
        self.assertLess(report["effects"][0]["per_seed_difference"]["29"], 0)

    def test_training_seed_is_an_inference_axis_not_extra_entropic_risk(self):
        plan = small_plan()
        rows = measured_rows(plan, improvement=0.0)
        for row in rows:
            if row["arm"] == "candidate":
                improvement = 0.4 if row["seed"] == 17 else -0.2
                row["utility"] += improvement
                row["net_with_audit_close"] += improvement
        report = analyse_panel(plan, rows)
        self.assertAlmostEqual(report["effects"][0]["difference"], (0.4 - 0.2) / 2, places=12)

    def test_full_lifecycle_cost_can_reverse_serving_benefit(self):
        plan = small_plan("confirmation")
        rows = measured_rows(plan)
        with self.assertRaises(ValueError):
            analyse_panel(plan, rows)
        costs = ledger(plan)
        initial = analyse_panel(plan, rows, costs)
        self.assertTrue(initial["research_qualified"])
        for key in costs:
            if key.endswith(":candidate"):
                costs[key]["candidate_selection"] = 0.2 * plan["amortization_episodes"]
        expensive = analyse_panel(plan, rows, costs)
        self.assertAlmostEqual(expensive["effects"][0]["difference"], -0.1, places=12)
        self.assertFalse(expensive["research_qualified"])

    def test_failure_rows_must_keep_failure_utility_and_cost(self):
        plan = small_plan()
        rows = measured_rows(plan)
        rows[0].update(failure="timeout", utility=-1.0, net_with_audit_close=-1.07)
        report = analyse_panel(plan, rows)
        self.assertEqual(report["failures_by_arm"], {"candidate": 1})
        rows[0]["utility"] = 0.5
        with self.assertRaises(ValueError):
            analyse_panel(plan, rows)

    def test_registered_noninferiority_and_cost_saving_are_distinct(self):
        plan = small_plan()
        plan["comparisons"] = [
            {"id": "quality", "left": "candidate", "right": "baseline",
             "metric": "utility_ce", "threshold": -0.01},
            {"id": "cost", "left": "candidate", "right": "baseline",
             "metric": "cost_saving", "threshold": 0.0}]
        plan["bootstrap_replicates"] = 800
        rows = measured_rows(plan, improvement=-0.005)
        for row in rows:
            if row["arm"] == "candidate":
                row["net_with_audit_close"] += 0.01
        report = analyse_panel(plan, rows)
        self.assertTrue(report["development_admission_pass"])
        plan["comparisons"][0]["threshold"] = 0.0
        self.assertFalse(analyse_panel(plan, rows)["development_admission_pass"])

    def test_insufficient_resamples_do_not_qualify(self):
        plan = small_plan()
        plan["bootstrap_replicates"] = 2
        report = analyse_panel(plan, measured_rows(plan))
        self.assertFalse(report["bootstrap"]["adequate_tail_resamples"])
        self.assertFalse(report["development_admission_pass"])

    def test_seal_detects_mutation_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            seal_plan(small_plan(), path)
            with self.assertRaises(FileExistsError):
                seal_plan(small_plan(), path)
            value = json.loads(path.read_text())
            value["plan"]["comparisons"][0]["threshold"] = -1.0
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                read_seal(path)

    def test_confirmation_guard_rejects_no_go_and_second_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            dev, confirm = small_plan(), small_plan("confirmation")
            seal_plan(dev, directory / "dev.json")
            seal_plan(confirm, directory / "confirm.json")
            candidates = {key: "c" * 64 for key in ledger(confirm)}
            no_go = analyse_panel(dev, measured_rows(dev, improvement=-0.1))
            args = (directory / "confirm.json", no_go, candidates, directory / "claim.json")
            with self.assertRaises(ValueError):
                claim_confirmation(*args, sealed_development_plan=directory / "dev.json")
            self.assertFalse((directory / "claim.json").exists())
            passed = analyse_panel(dev, measured_rows(dev))
            args = (directory / "confirm.json", passed, candidates, directory / "claim.json")
            claim_confirmation(*args, sealed_development_plan=directory / "dev.json")
            with self.assertRaises(FileExistsError):
                claim_confirmation(*args, sealed_development_plan=directory / "dev.json")

    def test_old_namespace_and_changed_comparisons_cannot_be_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            dev, confirm = small_plan(), small_plan("confirmation")
            confirm["source_namespace"] = "test"
            with self.assertRaises(ValueError):
                seal_plan(confirm, directory / "old.json")
            confirm = small_plan("confirmation")
            confirm["seeds"] = [43, 101]
            with self.assertRaises(ValueError):
                seal_plan(confirm, directory / "old-seed.json")
            confirm = small_plan("confirmation")
            confirm["comparisons"][0]["threshold"] = -0.2
            seal_plan(confirm, directory / "confirm.json")
            seal_plan(dev, directory / "dev.json")
            passed = analyse_panel(dev, measured_rows(dev))
            with self.assertRaises(ValueError):
                claim_confirmation(directory / "confirm.json", passed,
                                   {key: "c" * 64 for key in ledger(confirm)},
                                   directory / "claim.json",
                                   sealed_development_plan=directory / "dev.json")

    def test_confirmation_can_tighten_registered_noninferiority(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            dev, confirm = small_plan(), small_plan("confirmation")
            dev["comparisons"][0]["threshold"] = -0.005
            seal_plan(confirm, directory / "confirm.json")
            seal_plan(dev, directory / "dev.json")
            report = analyse_panel(dev, measured_rows(dev))
            result = claim_confirmation(directory / "confirm.json", report,
                                        {key: "c" * 64 for key in ledger(confirm)},
                                        directory / "claim.json",
                                        sealed_development_plan=directory / "dev.json")
            self.assertEqual(result["source_namespace"], confirm["source_namespace"])


if __name__ == "__main__":
    unittest.main()

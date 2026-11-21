"""Independent artificial receipts only; never opens a campaign attempt."""
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from .receipts import ARMS, SEEDS, TASKS, costs, normalize
from .summarize import bind_allocation, comparisons, complete_grid, inspect_stage, process_totals


def artificial_readout():
    cases, final = {}, []
    for task in TASKS:
        for seed in SEEDS:
            key = f"{task}/{seed}"
            arms = {}
            for method in ARMS["readout"]:
                status = "no_update" if method == "local_bp" else "selected"
                arms[method] = {"status": status, "dev_mse": 2. if status == "no_update" else .5,
                                "zero_dev_mse": 1., "weight": [0., 0.], "bias": 0.}
                for split in ("final_iid", "final_clock"):
                    mse = 1. if method == "local_bp" else 1.005
                    final.append({"case": key, "method": method, "split": split, "status": status,
                                  "mse": mse, "sample_squared_errors": [mse, mse], "target": [1., 1.],
                                  "prediction": [1-math.sqrt(mse)] * 2,
                                  "data_sha256": "toy", "ids": [key+split+"/0", key+split+"/1"]})
            cases[key] = {"methods": arms, "eligible_parameters": 3}
    rows, issues = normalize("readout", {"seeds": SEEDS, "final": 2}, {"cases": cases}, {"results": final})
    for row in rows:
        row["admitted"] = row["cell_valid"]
    return rows, issues, final, cases


class SummaryTests(unittest.TestCase):
    def test_seed_units_and_noupdate_are_not_multiplied_by_clock(self):
        rows, issues, _, _ = artificial_readout()
        self.assertEqual(issues, [])
        self.assertEqual(len(rows), 144)
        decisions = [r for r in rows if r["phase"] == "fit" and r["status"] == "no_update"]
        self.assertEqual(len(decisions), 12)
        pairs = comparisons(rows)
        self.assertTrue(all(x["n_admitted_seeds"] == 3 for x in pairs))
        self.assertTrue(all(x["quality_tolerance_screen"] == "meets" for x in pairs))
        self.assertTrue(all(abs(p["difference"] - .005) < 1e-9 and p["tau"] == .01
                            for x in pairs for p in x["paired"]))

    def test_missing_seed_prevents_quality_screen(self):
        rows, _, _, _ = artificial_readout()
        for row in rows:
            if row["seed"] == SEEDS[-1] and row["method"] == "direct":
                row.update(cell_valid=False, admitted=False, status="failed", value=None)
        direct = [x for x in comparisons(rows) if x["left"] == "direct"]
        self.assertTrue(all(x["quality_tolerance_screen"] == "incomplete" and x["n_admitted_seeds"] == 2 for x in direct))

    def test_missing_split_is_retained_as_missing(self):
        _, _, final, cases = artificial_readout()
        del final[0]["split"]
        del final[1]
        rows, issues = normalize("readout", {"seeds": SEEDS, "final": 2}, {"cases": cases}, {"results": final})
        self.assertEqual(sum(r["phase"] == "final" and not r["cell_valid"] for r in rows), 2)
        self.assertIn("unplanned or duplicate final rows exist", issues)

    def test_cumulative_sidecars_are_validated_as_prefixes_not_added(self):
        with tempfile.TemporaryDirectory() as directory:
            root, lines, tail = Path(directory), [], "0" * 64
            budget = {"wall_seconds": 180, "forward_examples": 10}
            for operation, wall, phase in ((0, 2., "selection"), (1, 5., "final")):
                records = [{"kind": "reserve", "operation": operation, "name": "artificial", "charge": {"forward_examples": 1}},
                           {"kind": "settle", "operation": operation, "status": "completed", "cumulative_wall_seconds": wall}]
                for record in records:
                    record.update(previous=tail, identity="toy", budget=budget)
                    tail = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                    record["hash"] = tail
                    lines.append(json.dumps(record))
                (root / (phase + ".cost.json")).write_text(json.dumps({"tail": tail, "pending": None,
                    "wall_seconds": wall+.1, "wall_overrun_seconds": 0, "forward_examples": operation+1}))
            (root / "cost.jsonl").write_text("\n".join(lines)+"\n")
            issues = []
            result = costs(root, {"budget": budget}, "toy", {}, issues)
            self.assertEqual(issues, [])
            self.assertEqual(result["cumulative_ledger_wall_seconds"], 5.)
            self.assertEqual(result["reserved_work"], {"forward_examples": 2})
            self.assertEqual(len(result["sidecars"]), 2)

    def test_whole_process_cost_includes_each_phase_once_and_preserves_unknown(self):
        stages = [{"stage": s, "outer": {"phases": {p: {"process": {"wall_seconds": v}}
                   for p, v in (("fit", 2.), ("final", 3.), ("freeze", 1.))},
                   "registration": {"plan_sha256": "common", "setup_wall_seconds": .5}}} for s in ARMS]
        result = process_totals(stages)
        self.assertEqual(result["complete_fit_final_child_seconds"], 25.)
        self.assertEqual(result["observed_freeze_child_seconds_separate"], 5.)
        self.assertEqual(result["registration_setup_seconds_by_plan"], {"common": .5})
        broken = copy.deepcopy(stages)
        broken[0]["outer"]["phases"]["final"] = None
        result = process_totals(broken)
        self.assertIsNone(result["complete_fit_final_child_seconds"])
        self.assertEqual(result["observed_fit_final_child_seconds"], 22.)
        broken[0]["outer"]["phases"]["fit"] = {"process": None}
        result = process_totals(broken)
        self.assertIsNone(result["complete_fit_final_child_seconds"])
        self.assertIn("readout/fit", result["unknown_process_phases"])

    def test_missing_whole_stage_is_incomplete_and_not_an_empty_success(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = inspect_stage("readout", Path(directory) / "missing-stage", None, {})
            self.assertEqual(len(stage["rows"]), 144)
            self.assertEqual(stage["counts"]["fit"]["admitted"], 0)
            self.assertEqual(stage["counts"]["final"]["admitted"], 0)
            self.assertTrue(stage["issues"])
            self.assertFalse(complete_grid(stage["rows"], []))
            self.assertFalse(complete_grid([], []))

    def test_wrong_allocation_hash_cannot_report_complete(self):
        rows, _, _, _ = artificial_readout()
        allocation = {"seeds": SEEDS, "source_git_sha": "toy-source", "stages": {s: {"namespace": s} for s in ARMS}}
        record = {"plan_sha256": "original", "source_git_sha": "toy-source", "namespace": "readout",
                  "source_files": {"qualification/hcsn_sixwork/CONFIRMATORY_PLAN.md": "protocol"}}
        stage = {"stage": "readout", "rows": rows, "outer": {"record": record},
                 "counts": {p: {"admitted": 1} for p in ("fit", "final")}}
        issues = bind_allocation([stage], allocation, "changed-allocation", "protocol")
        self.assertTrue(issues)
        self.assertTrue(all(not r["admitted"] for r in stage["rows"]))


if __name__ == "__main__":
    unittest.main()

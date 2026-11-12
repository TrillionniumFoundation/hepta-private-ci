"""Synthetic contract tests; their success is not PERC task-benefit evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from perc1.schema import Invalid, canonical, sha
from perc1.terminal_comparison import (
    COMPONENTS,
    CONTROLS,
    METRICS,
    STAGES,
    compare,
    main,
)


def panel():
    components = {c: sha(c.encode()) for c in COMPONENTS}
    arms = {a: {"11": dict(components)} for a in ("candidate", *CONTROLS)}
    for stage in COMPONENTS:
        arms["ablated_" + stage] = {
            "11": dict(components, **{stage: sha((stage + "-removed").encode())})
        }
    tasks = [
        {
            "task_id": f"task-{i}",
            "source_group": f"source-{i}",
            "task_sha256": sha(str(i).encode()),
            "target_known": i == 0,
        }
        for i in range(2)
    ]
    frozen = {
        "schema": "perc1.terminal-panel.v1",
        "tasks": tasks,
        "seeds": [11],
        "arms": arms,
        "ablations": {c: "ablated_" + c for c in COMPONENTS},
        "cost_weights": {m: 1e-3 for m in METRICS},
        "failure_quality": {"FAILED": 0, "CANCELLED": None},
        "results": [],
    }
    originals = {}
    for task in tasks:
        for arm in arms:
            row = {
                "schema": "perc1.terminal-result.v1",
                **{k: v for k, v in task.items() if k != "target_known"},
                "seed": 11,
                "arm": arm,
                "components": arms[arm]["11"],
                "information": "hidden_roi"
                if arm == "direct_roi_ocr" and not task["target_known"]
                else "public",
                "status": "COMPLETED",
                "quality": 1 if arm == "candidate" else 0.5,
                "attempts": 1,
                "recoveries": 0,
                "costs": {
                    "accounting": "inclusive_envelope",
                    "complete": True,
                    "stages": {s: {m: 1 for m in METRICS} for s in STAGES},
                    "envelope": {m: 10 for m in METRICS},
                },
            }
            raw = canonical(row)
            originals[sha(raw)] = raw
            frozen["results"].append(
                {"task_id": task["task_id"], "seed": 11, "arm": arm, "sha256": sha(raw)}
            )
    return frozen, originals


def change(frozen, originals, arm, edit, task="task-0"):
    binding = next(
        b for b in frozen["results"] if b["task_id"] == task and b["arm"] == arm
    )
    row = json.loads(originals.pop(binding["sha256"]))
    edit(row)
    raw = canonical(row)
    binding["sha256"] = sha(raw)
    originals[sha(raw)] = raw


class TerminalComparisonTests(unittest.TestCase):
    def test_complete_panel_retains_all_pairs_and_separates_private_roi(self):
        report = compare(*panel())
        self.assertEqual(
            (report["status"], report["adoption"], report["row_count"]),
            ("HOLD", "NoUpdate", 18),
        )
        control = report["comparisons"]["candidate_vs_direct_roi_ocr"]
        self.assertEqual(
            (
                control["fair"]["pair_count"],
                control["oracle_upper_bound"]["pair_count"],
            ),
            (1, 1),
        )
        self.assertEqual(
            report["comparisons"]["encoding"]["fair"]["equal_source_group_mean"],
            {"quality_delta": 0.5, "cost_delta": 0, "net_delta": 0.5},
        )

    def test_inclusive_envelope_is_not_added_to_nested_stages(self):
        frozen, originals = panel()
        change(
            frozen,
            originals,
            "candidate",
            lambda row: row["costs"].update(
                accounting="exclusive_stages", envelope=None
            ),
        )
        rows = compare(frozen, originals)["rows"]
        costs = [
            r["cost"]["by_metric"]["wall_ns"] for r in rows if r["arm"] == "candidate"
        ]
        self.assertEqual(costs, [8, 10])

    def test_missing_physical_metric_propagates_null_even_at_zero_weight(self):
        frozen, originals = panel()
        frozen["cost_weights"]["energy_joules"] = 0
        change(
            frozen,
            originals,
            "candidate",
            lambda row: row["costs"]["stages"]["shared_load"].update(
                energy_joules=None
            ),
        )
        report = compare(frozen, originals)
        self.assertIsNone(report["rows"][0]["net_utility"])
        self.assertIsNone(
            report["comparisons"]["encoding"]["fair"]["equal_source_group_mean"][
                "net_delta"
            ]
        )
        self.assertEqual(report["comparisons"]["encoding"]["fair"]["pair_count"], 2)

    def test_unknown_failures_and_recovery_are_never_dropped(self):
        frozen, originals = panel()
        change(
            frozen,
            originals,
            "candidate",
            lambda row: row.update(
                status="UNKNOWN", quality=None, attempts=3, recoveries=1
            ),
        )
        change(
            frozen,
            originals,
            "full_ocr",
            lambda row: row.update(status="FAILED", quality=None),
        )
        change(
            frozen,
            originals,
            "random_region",
            lambda row: row.update(status="CANCELLED", quality=None),
        )
        report = compare(frozen, originals)
        self.assertEqual(
            (report["row_count"], report["attempts"], report["recoveries"]), (18, 20, 1)
        )
        values = {r["arm"]: r for r in report["rows"] if r["task_id"] == "task-0"}
        self.assertEqual(
            [
                values[a]["utility_quality"]
                for a in ("candidate", "full_ocr", "random_region")
            ],
            [None, 0, None],
        )
        frozen["failure_quality"]["FAILED"] = None
        self.assertIsNone(
            next(
                r for r in compare(frozen, originals)["rows"] if r["status"] == "FAILED"
            )["net_utility"]
        )

    def test_missing_duplicate_and_reused_cells_are_rejected(self):
        for kind in ("missing", "duplicate", "reuse"):
            with self.subTest(kind=kind):
                frozen, originals = panel()
                if kind == "missing":
                    frozen["results"].pop()
                elif kind == "duplicate":
                    frozen["results"].append(copy.deepcopy(frozen["results"][0]))
                else:
                    frozen["results"][1]["sha256"] = frozen["results"][0]["sha256"]
                with self.assertRaises(Invalid):
                    compare(frozen, originals)

    def test_original_hash_and_bound_task_seed_components_cannot_drift(self):
        for field, value in (
            ("source_group", "other"),
            ("task_sha256", "0" * 64),
            ("seed", True),
            ("components", {}),
        ):
            with self.subTest(field=field):
                frozen, originals = panel()
                change(
                    frozen,
                    originals,
                    "candidate",
                    lambda row: row.update({field: value}),
                )
                with self.assertRaises(Invalid):
                    compare(frozen, originals)
        frozen, originals = panel()
        originals[next(iter(originals))] += b" "
        with self.assertRaisesRegex(Invalid, "SHA"):
            compare(frozen, originals)

    def test_private_control_leak_and_multicomponent_ablation_are_rejected(self):
        frozen, originals = panel()
        change(
            frozen,
            originals,
            "public_feature_rule",
            lambda row: row.update(information="hidden_roi"),
        )
        with self.assertRaisesRegex(Invalid, "private ROI"):
            compare(frozen, originals)
        frozen, originals = panel()
        frozen["arms"]["ablated_encoding"]["11"]["selection"] = "0" * 64
        with self.assertRaisesRegex(Invalid, "declared component"):
            compare(frozen, originals)

    def test_cost_boundary_excludes_unobserved_and_contradictory_totals(self):
        frozen, originals = panel()
        change(
            frozen,
            originals,
            "candidate",
            lambda row: row["costs"].update(complete=False),
        )
        self.assertIsNone(compare(frozen, originals)["rows"][0]["net_utility"])
        for edit in (
            lambda row: row["costs"]["envelope"].update(wall_ns=0),
            lambda row: row["costs"].update(accounting="exclusive_stages"),
            lambda row: row["costs"]["stages"].pop("recovery"),
        ):
            frozen, originals = panel()
            change(frozen, originals, "candidate", edit)
            with self.assertRaises(Invalid):
                compare(frozen, originals)

    def test_duplicate_json_and_nonfinite_originals_are_not_normalized_away(self):
        for corrupt in (
            lambda raw: raw[:-1] + b',"quality":0}',
            lambda raw: raw.replace(b'"quality":1', b'"quality":NaN'),
        ):
            frozen, originals = panel()
            binding = frozen["results"][0]
            raw = corrupt(originals.pop(binding["sha256"]))
            binding["sha256"] = sha(raw)
            originals[sha(raw)] = raw
            with self.assertRaises(ValueError):
                compare(frozen, originals)

    def test_source_group_means_do_not_count_task_repetitions_as_new_groups(self):
        frozen, originals = panel()
        task = dict(frozen["tasks"][0], task_id="task-2", task_sha256=sha(b"task-2"))
        frozen["tasks"].append(task)
        for binding in list(frozen["results"]):
            if binding["task_id"] == "task-0":
                row = json.loads(originals[binding["sha256"]])
                row.update(task_id="task-2", task_sha256=task["task_sha256"])
                raw = canonical(row)
                originals[sha(raw)] = raw
                frozen["results"].append(
                    dict(binding, task_id="task-2", sha256=sha(raw))
                )
        change(frozen, originals, "candidate", lambda row: row.update(quality=0))
        result = compare(frozen, originals)["comparisons"]["candidate_vs_full_ocr"][
            "fair"
        ]
        self.assertEqual((result["task_count"], result["source_group_count"]), (3, 2))
        self.assertEqual(result["equal_source_group_mean"]["quality_delta"], 0.25)

    def test_cli_retains_missing_original_failure_and_refuses_overwrite(self):
        frozen, originals = panel()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = canonical(frozen)
            (root / "manifest.json").write_bytes(raw)
            args = [
                "--manifest",
                str(root / "manifest.json"),
                "--manifest-sha256",
                sha(raw),
                "--originals",
                str(root),
                "--output",
                str(root / "report.json"),
            ]
            self.assertEqual(main(args), 2)
            failure = (root / "report.json").read_bytes()
            self.assertEqual(json.loads(failure)["status"], "INVALID_EVIDENCE")
            for pin, data in originals.items():
                (root / (pin + ".json")).write_bytes(data)
            with self.assertRaises(FileExistsError):
                main(args)
            self.assertEqual((root / "report.json").read_bytes(), failure)
            args[-1] = str(root / "complete.json")
            self.assertEqual(main(args), 0)
            self.assertEqual(
                json.loads((root / "complete.json").read_bytes())["status"], "HOLD"
            )


if __name__ == "__main__":
    unittest.main()

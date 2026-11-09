"""Prospective denominator checks; fixtures do not establish model benefit."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from .causal_analysis import paired_contrast
from .factorial_report import FAMILIES, REQUIRED_SOURCES, build_report, generate
from .metering import atomic_json, file_sha
from .study import freeze, select_sources


class FactorialReportTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "design": {
                "training_seeds": [11, 13],
                "regimes": ["frozen"],
                "memory_modes": ["reset"],
                "controller": {},
                "estimand": "matched_training",
                "arms": {
                    f"{core}_{controller}": [core, controller, "reset"]
                    for core in ("ordinary", "hepta")
                    for controller in ("light", "ndu", "tuned_fixed", "voi", "mpc")
                },
            },
            "independent_fit_roster": [
                {"fit_id": "f1", "training_seed": 11},
                {"fit_id": "f2", "training_seed": 13},
            ],
        }
        self.selected = {
            "groups": {"pilot_new": ["s1", "s2"], "pilot_retention": ["r1", "r2"]},
            "cases": {
                category: [
                    {
                        "id": source + family,
                        "source_id": source,
                        "role": role,
                        "task_family": family,
                    }
                    for source in sources
                    for family in families
                ]
                for category, sources, families, role in (
                    ("pilot_new", ["s1", "s2"], FAMILIES, "development"),
                    (
                        "pilot_retention",
                        ["r1", "r2"],
                        ("retention",),
                        "retention_validation",
                    ),
                )
            },
        }
        self.rows = []
        for fit in self.plan["independent_fit_roster"]:
            for arm, (core, controller, mode) in self.plan["design"]["arms"].items():
                for cases in self.selected["cases"].values():
                    for case in cases:
                        self.rows.append(
                            {
                                **fit,
                                "arm": arm,
                                "core": core,
                                "controller": controller,
                                "memory_mode": mode,
                                "regime": "frozen",
                                "estimand": "matched_training",
                                "case_id": case["id"],
                                "source_group_id": case["source_id"],
                                "split": case["role"],
                                "task_family": case["task_family"],
                                "original_operation_id": fit["fit_id"]
                                + arm
                                + case["id"],
                                "terminal_status": "Completed",
                                "analysis_utility": 0.02 * (core == "hepta")
                                + 0.03 * (controller == "ndu")
                                + 0.04 * (core == "hepta" and controller == "ndu"),
                            }
                        )

    def comparison(self, report, contrast, panel="overall", split="development"):
        return next(
            row["descriptive"]
            for row in report["comparisons"]
            if (row["contrast"], row["panel"], row["split"]) == (contrast, panel, split)
        )

    def test_all_five_effects_and_six_strong_controls_remain_in_report(self):
        report = build_report(self.plan, self.selected, self.rows, draws=100)
        for name, expected in {
            "B-A": 0.03,
            "D-C": 0.07,
            "C-A": 0.02,
            "D-B": 0.06,
            "(D-C)-(B-A)": 0.04,
        }.items():
            self.assertAlmostEqual(self.comparison(report, name)["mean"], expected)
        overall = [
            row
            for row in report["comparisons"]
            if row["panel"] == "overall" and row["split"] == "development"
        ]
        self.assertEqual(len(overall), 11)
        self.assertEqual(self.comparison(report, "B-A")["planned_rows"], 40)
        self.assertEqual(report["independent_training_repeats"], 2)
        self.assertTrue(report["coverage"]["development"]["required_roster_coverage"])
        self.assertEqual(report["scientific_acceptance"], "HOLD")
        self.assertIsNone(report["energy_joules"])

    def test_missing_pair_blocks_overall_despite_complete_preparation_subgroup(self):
        self.rows = [
            row
            for row in self.rows
            if not (
                row["fit_id"] == "f1"
                and row["arm"] == "hepta_ndu"
                and row["case_id"] == "s1text_sufficient"
            )
        ]
        report = build_report(self.plan, self.selected, self.rows, draws=100)
        self.assertIsNone(self.comparison(report, "D-C")["mean"])
        self.assertIsNotNone(
            self.comparison(report, "D-C", "preparation_required")["mean"]
        )
        self.assertFalse(report["family_panels_replace_overall"])

    def test_favorable_subgroup_cannot_replace_negative_overall(self):
        for row in self.rows:
            row["analysis_utility"] = (
                (1 if row["task_family"] == "preparation_required" else -0.5)
                if row["controller"] == "ndu"
                else 0
            )
        report = build_report(self.plan, self.selected, self.rows, draws=100)
        self.assertGreater(
            self.comparison(report, "B-A", "preparation_required")["mean"], 0
        )
        self.assertLess(self.comparison(report, "B-A")["mean"], 0)
        self.assertFalse(report["confirmatory_use"])

    def test_omitted_family_and_retention_remain_visible(self):
        self.selected["cases"]["pilot_new"] = [
            case
            for case in self.selected["cases"]["pilot_new"]
            if case["task_family"] != "preparation_required"
        ]
        self.selected["cases"]["pilot_retention"] = []
        self.rows = [
            row
            for row in self.rows
            if row["task_family"] not in {"preparation_required", "retention"}
        ]
        report = build_report(self.plan, self.selected, self.rows, draws=100)
        self.assertFalse(report["coverage"]["development"]["required_roster_coverage"])
        self.assertFalse(
            report["coverage"]["retention_validation"]["required_roster_coverage"]
        )
        self.assertEqual(
            self.comparison(report, "B-A", "preparation_required")["status"],
            "NO_PLANNED_CASES",
        )
        self.assertIsNone(
            self.comparison(report, "B-A", split="retention_validation")["mean"]
        )

    def test_family_drift_duplicate_attempt_and_fit_alias_rejected(self):
        for field, value in (
            ("task_family", "preparation_required"),
            ("training_seed", 999),
            ("estimand", "deployment_state_ablation"),
        ):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = value
            with self.assertRaises(ValueError):
                build_report(self.plan, self.selected, rows, draws=100)
        with self.assertRaisesRegex(ValueError, "operation"):
            build_report(
                self.plan, self.selected, self.rows + [self.rows[0]], draws=100
            )

    def test_unknown_nan_and_budget_stop_are_not_complete(self):
        for value, status in (
            (float("nan"), "Completed"),
            (float("inf"), "Completed"),
            (10**400, "Completed"),
            (0.7, "BudgetStop"),
        ):
            rows = copy.deepcopy(self.rows)
            rows[0].update(analysis_utility=value, terminal_status=status)
            report = build_report(self.plan, self.selected, rows, draws=100)
            self.assertIsNone(self.comparison(report, "B-A")["mean"])

    def test_generic_contrast_rejects_family_drift_and_overflow(self):
        cases = [
            {
                "case_id": "case",
                "source_group_id": "source",
                "split": "development",
                "task_family": "text_sufficient",
            }
        ]
        rows = [
            {
                **cases[0],
                "fit_id": "f1",
                "condition_id": arm,
                "terminal_status": "Completed",
                "analysis_utility": value,
            }
            for arm, value in (("control", -1e308), ("candidate", 1e308))
        ]
        with self.assertRaisesRegex(ValueError, "finite range"):
            paired_contrast(
                rows, {"candidate": 1, "control": -1}, ["f1"], cases, draws=100
            )
        rows[0]["task_family"] = "preparation_required"
        with self.assertRaisesRegex(ValueError, "family"):
            paired_contrast(
                rows, {"candidate": 1, "control": -1}, ["f1"], cases, draws=100
            )

    def write_bound_inputs(self, root, *, include_analysis=True):
        repository = Path(__file__).resolve().parents[2]
        self.plan["execution"] = {"repository_root": str(repository)}
        names = [
            "__init__",
            "causal_analysis",
            "causal_protocol",
            "metering",
            "span_meter",
        ]
        if include_analysis:
            names.append("factorial_report")
        self.plan["source_pins"] = [
            {"path": str(path), "sha256": file_sha(path), "bytes": path.stat().st_size}
            for name in names
            for path in [repository / "scripts/ndu_real_runtime" / (name + ".py")]
        ]
        common = repository / "scripts/ndu_real_materials/common.py"
        self.plan["source_pins"].append(
            {
                "path": str(common),
                "sha256": file_sha(common),
                "bytes": common.stat().st_size,
            }
        )
        init = repository / "scripts/ndu_real_materials/__init__.py"
        self.plan["source_pins"].append(
            {"path": str(init), "sha256": file_sha(init), "bytes": init.stat().st_size}
        )
        self.plan["selected_sources_sha256"] = atomic_json(
            root / "selected-sources.json", self.selected
        )
        plan_sha = atomic_json(root / "PILOT_PLAN.json", self.plan)
        profiles = {}
        for row in self.rows:
            identity = row["fit_id"] + row["arm"]
            row.update(
                profile_id=identity, model_sha256="1" * 64, policy_sha256="2" * 64
            )
            profiles[identity] = {
                key: row[key]
                for key in (
                    "profile_id",
                    "fit_id",
                    "regime",
                    "arm",
                    "model_sha256",
                    "policy_sha256",
                )
            }
        lock_sha = atomic_json(
            root / "selection-lock.json",
            {
                "pilot_plan_sha256": plan_sha,
                "selected": [{"profile": value} for value in profiles.values()],
            },
        )
        for row in self.rows:
            row["selection_lock_sha256"] = lock_sha
        (root / "paired-rows.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in self.rows)
        )
        return plan_sha, file_sha(root / "paired-rows.jsonl")

    def test_prospective_source_bound_report_and_changed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_sha, rows_sha = self.write_bound_inputs(root)
            result = generate(root, plan_sha, rows_sha, draws=100)
            self.assertEqual(result["input_sha256"]["paired-rows.jsonl"], rows_sha)
            with (root / "paired-rows.jsonl").open("a") as stream:
                stream.write("{}\n")
            with self.assertRaisesRegex(ValueError, "expected bytes"):
                generate(root, plan_sha, rows_sha, draws=100)

    def test_old_plan_cannot_acquire_new_analysis_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_sha, rows_sha = self.write_bound_inputs(root, include_analysis=False)
            with self.assertRaisesRegex(ValueError, "prospectively frozen"):
                generate(root, plan_sha, rows_sha, draws=100)

    def catalog(self):
        return [
            {
                "id": source + family,
                "source_id": source,
                "role": role,
                "episode_group": source + "-episode",
                "task_family": family,
            }
            for role, sources, families in (
                ("train", ["t1", "t2"], FAMILIES),
                ("development", ["s1"], FAMILIES),
                ("retention_validation", ["r1"], ("retention",)),
            )
            for source in sources
            for family in families
        ]

    def design_for_freeze(self):
        return {
            **self.plan["design"],
            "study_id": "prospective-contract-fixture",
            "source_selection": {
                "training_groups": 1,
                "tuning_groups": 1,
                "pilot_new_groups": 1,
                "pilot_retention_groups": 1,
            },
        }

    def test_five_distinct_wrong_family_names_cannot_freeze(self):
        for role, old_family, wrong_family in (
            ("development", "preparation_required", "unplanned_family"),
            ("train", "continuation_not_worthwhile", "unplanned_stop"),
            ("retention_validation", "retention", "text_sufficient"),
        ):
            with self.subTest(role=role):
                catalog = self.catalog()
                for case in catalog:
                    if case["role"] == role and case["task_family"] == old_family:
                        case["task_family"] = wrong_family
                with self.assertRaisesRegex(ValueError, "required family coverage"):
                    select_sources(catalog, self.design_for_freeze())

    def test_new_freeze_produces_runnable_source_bound_report_without_manual_pins(self):
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materials = root / "materials"
            (materials / "private").mkdir(parents=True)
            atomic_json(
                materials / "registration-final.json", {"registry_sha256": "1" * 64}
            )
            reference_sha = atomic_json(
                materials / "private/reference-index.v2.json", {}
            )
            atomic_json(materials / "pilot-catalog.json", {"cases": self.catalog()})
            exposure_sha = atomic_json(
                root / "exposure.json", {"quarantined_source_groups": []}
            )
            design_path = root / "design.json"
            atomic_json(design_path, self.design_for_freeze())
            run = root / "new-run"
            plan = freeze(
                {
                    "material_root": str(materials),
                    "repository_root": str(repository),
                    "reference_index_sha256": reference_sha,
                    "rubric_sha256": "2" * 64,
                    "source_exposure_ledger_path": str(root / "exposure.json"),
                    "source_exposure_ledger_sha256": exposure_sha,
                },
                design_path,
                run,
            )
            pinned = {
                Path(item["path"]).relative_to(repository).as_posix()
                for item in plan["source_pins"]
            }
            self.assertTrue(REQUIRED_SOURCES <= pinned)
            plan_sha = file_sha(run / "PILOT_PLAN.json")
            atomic_json(
                run / "selection-lock.json",
                {"pilot_plan_sha256": plan_sha, "selected": []},
            )
            (run / "paired-rows.jsonl").write_text("")
            report = generate(
                run, plan_sha, file_sha(run / "paired-rows.jsonl"), draws=100
            )
            self.assertTrue(
                report["coverage"]["development"]["required_roster_coverage"]
            )
            self.assertEqual(self.comparison(report, "B-A")["status"], "INCOMPLETE")
            self.assertEqual(self.comparison(report, "B-A")["planned_rows"], 20)
            self.assertEqual(report["scientific_acceptance"], "HOLD")


if __name__ == "__main__":
    unittest.main()

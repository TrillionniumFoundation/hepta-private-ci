"""Contract fixtures only: these tests are not real task or adoption evidence."""

from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

from .causal_b import record_inventory, run_matched_grid, smoke_design
from .controllers import ControlPlan
from .fit_loop import training_sequences
from .matrix import profile_candidates, tune
from .metering import atomic_json, canonical_sha, file_sha
from .test_recursive_contract import numerical_records
from .training_grid import fit_grid, model_index
from .trajectory import grouped_batches


class CausalBContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.records = self.root / "numerical-fixture.jsonl"
        self.records.write_text(
            "".join(json.dumps(row) + "\n" for row in numerical_records(ControlPlan()))
        )

    def plans(self):
        paths = {}
        for mode in ("reset", "persistent"):
            path = self.root / (mode + ".json")
            atomic_json(path, {"control": asdict(ControlPlan(memory_mode=mode))})
            paths[mode] = path
        return paths

    def test_legacy_inventory_retains_four_independent_seeds(self):
        plan = fit_grid(
            str(self.records), file_sha(self.records), str(self.root / "models")
        )
        self.assertEqual(
            plan["counts"],
            {
                "independent_seed_groups": 4,
                "content": 8,
                "frozen_shared": 24,
                "joint": 120,
            },
        )
        self.assertEqual(
            {job["observation_policy"] for job in plan["jobs"]}, {"legacy"}
        )

    def test_paired_grid_has_mode_bound_dependencies_and_index(self):
        plan = fit_grid(
            str(self.records),
            file_sha(self.records),
            str(self.root / "models"),
            seeds=(11, 13),
            head_lrs=(0.003,),
            control_plans=self.plans(),
            observation_policy="matched_episodes",
        )
        self.assertEqual(
            plan["counts"],
            {
                "independent_seed_groups": 2,
                "content": 8,
                "frozen_shared": 8,
                "joint": 40,
            },
        )
        jobs = {job["job_id"]: job for job in plan["jobs"]}
        for job in jobs.values():
            for dependency in job["depends_on"]:
                base = jobs[dependency]
                self.assertEqual(
                    (job["seed"], job["core"], job["memory_mode"]),
                    (base["seed"], base["core"], base["memory_mode"]),
                )
        index = model_index(plan)
        self.assertEqual(len(index["fits"]), 48)
        self.assertEqual(
            {row["memory_mode"] for row in index["fits"]}, {"reset", "persistent"}
        )

    def test_paired_control_change_is_rejected(self):
        paths = self.plans()
        paths["persistent"].write_text(
            json.dumps(
                {"control": asdict(ControlPlan(memory_mode="persistent", horizon=1))}
            )
        )
        with self.assertRaisesRegex(ValueError, "only in memory_mode"):
            fit_grid(
                str(self.records),
                file_sha(self.records),
                str(self.root / "models"),
                control_plans=paths,
                observation_policy="matched_episodes",
            )

    def test_matching_preserves_rows_and_optimizer_boundaries(self):
        rows = numerical_records(ControlPlan())
        for index, row in enumerate(rows):
            row["first_content"] = index == 0
        legacy, _ = training_sequences(rows, "content", "reset", "legacy")
        self.assertEqual(len(legacy), 1)
        schedules = []
        for mode in ("reset", "persistent"):
            selected, groups = training_sequences(
                rows, "content", mode, "matched_episodes"
            )
            self.assertEqual(selected, rows)
            order = list(range(len(groups)))
            random.Random(17).shuffle(order)
            schedules.append(list(grouped_batches(groups, order, 2)))
        self.assertEqual(schedules[0], schedules[1])
        self.assertEqual(len(schedules[0][0][0]), 3)

    def test_record_inventory_requires_complete_original_v2(self):
        inventory = record_inventory(self.records, file_sha(self.records))
        self.assertEqual((inventory["rows"], inventory["complete_episodes"]), (3, 1))
        self.assertFalse(inventory["material_authority_reverified_by_cloud_trainer"])
        with self.assertRaisesRegex(ValueError, "frozen digest"):
            record_inventory(self.records, "0" * 64)
        lines = self.records.read_text().splitlines()
        self.records.write_text("\n".join(lines[1:]) + "\n")
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            record_inventory(self.records, file_sha(self.records))

    def test_budget_blocks_admission_without_shrinking_the_grid(self):
        design = smoke_design("contract-only", training_wall_seconds=1)
        output = self.root / "blocked"
        output.mkdir()
        config = {
            "python": sys.executable,
            "scripts_root": str(self.root),
            "repository_root": str(self.root),
            "pillow_path": str(self.root),
        }
        with patch("ndu_real_runtime.pipeline.run_training_job") as dispatch:
            index = run_matched_grid(output, self.records, design, config)
        dispatch.assert_not_called()
        result = json.loads((output / "fit-results.json").read_text())
        self.assertEqual(result["status_counts"], {"budget_stopped": 56})
        self.assertEqual(result["independent_seed_groups_complete"], 0)
        self.assertEqual(len(index["content"] + index["fits"]), 56)
        self.assertEqual(len(result["paired_training_audit"]), 28)
        self.assertTrue(
            all(not row["complete"] for row in result["paired_training_audit"])
        )
        with self.assertRaises(FileExistsError):
            run_matched_grid(output, self.records, design, config)

    def test_profile_does_not_substitute_reset_for_missing_persistent_fit(self):
        design = smoke_design("profile-contract")
        design["regimes"] = ["joint"]
        design["arms"] = {
            mode: ["ordinary", "light", mode] for mode in ("reset", "persistent")
        }
        model = self.root / "model"
        model.mkdir()
        (model / "weights.pt").write_bytes(b"not-a-real-model-contract-fixture")
        atomic_json(
            model / "receipt.json",
            {
                "memory_mode": "reset",
                "observation_policy": "matched_episodes",
                "control_profile_sha256": canonical_sha(asdict(ControlPlan())),
            },
        )
        index = {
            "content": [],
            "fits": [
                {
                    "seed": 11,
                    "core": "ordinary",
                    "regime": "joint",
                    "controller": "light",
                    "trial_index": 0,
                    "memory_mode": "reset",
                    "observation_policy": "matched_episodes",
                    "status": "completed",
                    "directory": str(model),
                    "weights_sha256": file_sha(model / "weights.pt"),
                    "receipt_sha256": file_sha(model / "receipt.json"),
                }
            ],
        }
        plan = {
            "design": design,
            "independent_fit_roster": [{"fit_id": "f1", "training_seed": 11}],
            "source_pins": [],
        }
        with patch("ndu_real_runtime.matrix.verify_plan", return_value=(plan, {})):
            result = profile_candidates(self.root, index)
        self.assertEqual([row["memory_mode"] for row in result["profiles"]], ["reset"])
        self.assertEqual(
            [row["memory_mode"] for row in result["unavailable"]], ["persistent"]
        )

    def test_one_trial_selection_keeps_comparators_separate_by_mode(self):
        design = smoke_design("selection-contract")
        design["regimes"] = ["joint"]
        plan = {
            "design": design,
            "execution_run_id": "fixture",
            "execution": {},
            "independent_fit_roster": [{"fit_id": "f1", "training_seed": 11}],
            "source_pins": [],
        }
        design["budgets"]["phase_wall_seconds"] = 120
        atomic_json(self.root / "PILOT_PLAN.json", plan)
        index = self.root / "model-index.json"
        atomic_json(index, {})
        (self.root / "search").mkdir()
        atomic_json(self.root / "search/phase-result.json", {})
        profiles = [
            {
                "profile_id": arm,
                "fit_id": "f1",
                "regime": "joint",
                "arm": arm,
                "core": spec[0],
                "controller": spec[1],
                "memory_mode": spec[2],
                "trial_index": 0,
            }
            for arm, spec in design["arms"].items()
        ]
        observations = [
            {
                **profile,
                "case_id": "case",
                "source_group_id": "source",
                "deployment_wall_seconds": 1,
                "terminal_status": "Completed",
                "analysis_utility": 0.9 if profile["controller"] == "mpc" else 0.8,
            }
            for profile in profiles
        ]
        with (
            patch(
                "ndu_real_runtime.matrix.verify_plan",
                return_value=(plan, {"cases": {"tuning": [{"id": "case"}]}}),
            ),
            patch(
                "ndu_real_runtime.matrix.profile_candidates",
                return_value={"profiles": profiles, "unavailable": []},
            ),
            patch("ndu_real_runtime.matrix.run_requests", return_value={}),
            patch("ndu_real_runtime.matrix.retained_rows", return_value=observations),
        ):
            lock = tune(self.root, index)
        self.assertTrue(lock["all_planned_candidates_accounted"])
        self.assertTrue(lock["all_search_trials_complete"])
        self.assertTrue(lock["complete_profile_selection"])
        self.assertEqual(
            [
                (row["memory_mode"], row["available_comparator_profiles"])
                for row in lock["strongest"]
            ],
            [("reset", 6), ("persistent", 6)],
        )

    @unittest.skipUnless(
        importlib.util.find_spec("torch"),
        "Torch qualification runs in the matched cloud runtime",
    )
    def test_ordinary_hepta_share_actual_initial_parameter_bytes(self):
        import torch
        from .neural import ReceiptPortfolioModel
        from .training import parameter_sha

        with torch.random.fork_rng(devices=[]):
            hashes = []
            for core in ("ordinary", "hepta"):
                torch.manual_seed(104729)
                hashes.append(parameter_sha(ReceiptPortfolioModel(core)))
        self.assertEqual(hashes[0], hashes[1])


if __name__ == "__main__":
    unittest.main()

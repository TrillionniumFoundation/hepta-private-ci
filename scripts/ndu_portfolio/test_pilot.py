"""Actual file/fit integration with explicit fixtures; never real-task evidence."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

from . import pilot_cli
from .pilot_data import (
    CASE_IDS,
    SUCCESS,
    make_plan,
    read_plan,
    score_episode,
    training_rows,
)
from .real_execution import _sha, _write
from .real_predictor import Opportunity, PredictiveModel, fit_predictive
from .test_real_execution import ArtifactFixture, PublicRecordingEncoder


PROFILE = dict(
    device="cpu",
    dtype="bfloat16",
    threads=2,
    cpu_tariff=0.0,
    wall_tariff=1.0,
    cost_weight=0.001,
    episode_wall_seconds=10.0,
    episode_cost=10.0,
    phase_wall_seconds=120.0,
)


class PilotContracts(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)

    def fixture(self, root):
        cases = []
        for index, case_id in enumerate(CASE_IDS):
            path = root / f"reference-{index}.json"
            _write(
                path,
                {
                    "image": "fixture.jpg",
                    "question": "fixture request",
                    "answer_type": "other",
                    "answerable": 1,
                    "answers": [
                        {"answer": "hidden_reference_only", "answer_confidence": "yes"}
                        for _ in range(10)
                    ],
                },
            )
            cases.append(
                {
                    "id": case_id,
                    "project_split": "development" if index < 3 else "train",
                    "source_group_id": f"fixture-source-{index}",
                    "episode_group_id": f"fixture-episode-{index}",
                    "reference": {
                        "path": path.name,
                        "sha256": _sha(path),
                        "bytes": path.stat().st_size,
                    },
                }
            )
        return cases

    def collect_fixture(self, root):
        cases, backend = self.fixture(root), ArtifactFixture()
        plan = make_plan("a" * 40, PROFILE)
        args = SimpleNamespace(pool=root, output=root / "collection")
        public = {
            "text": "public fixture request",
            "image_rgb": np.zeros((8, 8, 3), dtype=np.uint8),
        }
        with (
            patch.object(
                pilot_cli,
                "load_pool",
                return_value=(cases, {"scientific_admission": False}),
            ),
            patch.object(pilot_cli, "backend_for", return_value=backend),
            patch.object(
                pilot_cli,
                "FrozenSmolEncoder",
                side_effect=lambda _: PublicRecordingEncoder(),
            ),
            patch(
                "ndu_semantic_state.source_pool.load_candidate_public_case",
                return_value=public,
            ),
            patch.object(
                pilot_cli,
                "score_episode",
                side_effect=AssertionError("online reference scoring is forbidden"),
            ),
        ):
            result = pilot_cli.collect(plan, args)
        self.assertEqual(len(result["entries"]), 18)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(
            all("hidden_reference_only" not in prompt for _, prompt in backend.calls)
        )
        return plan, cases, result

    def test_real_file_collection_offline_grading_and_small_physical_fit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan, cases, collection = self.collect_fixture(root)
            input_path = root / "collection/PHASE.json"
            args = SimpleNamespace(
                pool=root,
                output=root / "score",
                input=input_path,
                input_sha256=_sha(input_path),
                input_phase="collect",
            )
            with patch.object(pilot_cli, "load_pool", return_value=(cases, {})):
                scored = pilot_cli.score(plan, args)
            self.assertTrue(scored["full_collection_complete"])
            self.assertEqual(scored["training_rows"], 18)
            rows = json.loads((root / "score/TRAINING_ROWS.json").read_text())
            self.assertEqual(
                {r["source_group"] for r in rows},
                {f"fixture-source-{i}" for i in range(3, 9)},
            )
            self.assertEqual({r["action"] for r in rows}, {"perceive", "text"})
            self.assertTrue(
                all(r["execution_receipt"] != r["evaluator_receipt"] for r in rows)
            )
            report = fit_predictive(
                PredictiveModel(4, width=4),
                rows,
                replace(Opportunity(**plan["opportunity"]), updates=1),
                allowed_sources={r["source_group"] for r in rows},
                regime="joint",
                seed=17,
                output=root / "fit",
            )
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["critic_target"], "conditional_exponential_moment")
            self.assertEqual(report["supported_actions"], ["perceive", "text"])

    def test_mutated_delivered_bytes_are_not_silently_scored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, cases, collection = self.collect_fixture(root)
            entry = collection["entries"][0]
            directory = root / "collection" / entry["key"]
            trace = json.loads((directory / "episode.json").read_text())
            (directory / trace["selected"][0]["path"]).write_text("replaced output")
            with self.assertRaisesRegex(ValueError, "binding differs"):
                score_episode(root, cases[0], directory, entry["episode_sha256"])

    def test_missing_physical_cost_cannot_be_filled_with_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, cases, collection = self.collect_fixture(root)
            entry = collection["entries"][6]
            directory = root / "collection" / entry["key"]
            trace, grade = score_episode(
                root, cases[3], directory, entry["episode_sha256"]
            )
            event = trace["observations"][0]["event_cursor"]
            del trace["events"][event]["cost"]
            with self.assertRaises(KeyError):
                training_rows(cases[3], trace, grade)

    def test_failed_source_or_development_cannot_supply_fit_rows(self):
        with self.assertRaisesRegex(ValueError, "Only completed"):
            training_rows({"project_split": "development"}, {"status": SUCCESS}, {})
        with self.assertRaisesRegex(ValueError, "Only completed"):
            training_rows({"project_split": "train"}, {"status": "failed"}, {})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = make_plan("a" * 40, PROFILE)
            prior = {
                "phase": "score_collect",
                "plan_digest": pilot_cli.digest(plan),
                "status": "completed",
                "full_collection_complete": False,
                "entries": [],
            }
            _write(root / "PHASE.json", prior)
            with self.assertRaisesRegex(ValueError, "reduced-data fit"):
                pilot_cli.fit(
                    plan,
                    SimpleNamespace(
                        input=root / "PHASE.json",
                        input_sha256=_sha(root / "PHASE.json"),
                    ),
                )

    def test_plan_pin_and_phase_budget_cannot_be_reinterpreted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = make_plan("a" * 40, PROFILE)
            _write(root / "PLAN.json", plan)
            pin = _sha(root / "PLAN.json")
            self.assertEqual(read_plan(root / "PLAN.json", pin), plan)
            plan["fit_seeds"].append(55)
            _write(root / "PLAN.json", plan)
            with self.assertRaisesRegex(ValueError, "external pin"):
                read_plan(root / "PLAN.json", pin)
            with self.assertRaisesRegex(ValueError, "roster changed"):
                read_plan(root / "PLAN.json", _sha(root / "PLAN.json"))
            # perf_counter has an arbitrary origin, including on fresh CI hosts.
            # Exercise the registered 120-second boundary with a 10-second reserve.
            for origin in (0.0, 1_000_000.0):
                for elapsed, allowed in ((109.0, True), (110.0, False), (111.0, False)):
                    with self.subTest(origin=origin, elapsed=elapsed):
                        row = {"status": "not_started"}
                        with patch.object(
                            pilot_cli.time,
                            "perf_counter",
                            return_value=origin + elapsed,
                        ):
                            self.assertEqual(
                                pilot_cli.before_task(plan, origin, row, 10.0), allowed
                            )
                        self.assertEqual(
                            row["status"],
                            "not_started"
                            if allowed
                            else "not_started_budget_exhausted",
                        )


if __name__ == "__main__":
    unittest.main()

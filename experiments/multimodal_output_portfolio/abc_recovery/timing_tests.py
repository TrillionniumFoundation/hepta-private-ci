"""Synthetic scheduling and job-boundary tests; no registered benchmark is run."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from ..v6.data import Observation, Target
from ..v6.observer import Recognizer
from ..v7.data import VIEWS
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from .control import Feedback, PROFILES
from .critic import ActionCritic, FiniteHorizonCritic
from .timing import ARMS, SEEDS, TIMING_VIEWS, _identities, _jobs, _prepare_inputs, _resident_job, _summaries
from .trees import stable_seed


class TimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def setUp(self):
        self.observation = Observation(torch.zeros(1, 1, 28, 56), torch.ones(1, 1, 28, 56),
                                       torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]))
        self.target = Target(torch.zeros(1, 1, 28, 56), torch.tensor([[1, 3, 14, 4, 14, 5, 7, 2]]), torch.zeros(1, 2, dtype=torch.long))
        self.bundle = {"feedback": object(), "profiles": {}, "route": None, "static": {"plan": ()}}
        self.job = {"seed": 17, "arm": "output_ndu", "policy": "fixed", "case": 608,
                    "view": "clean", "scenario": 0, "round": 0}

    def success(self):
        return {"wall_ns": 101, "cpu_ns": 83, "path": (), "work": {"critic_calls": 1, "planner_critic_calls": 1},
                "pixels": self.target.pixels, "captions": ["left 0 right 0 relation equal"],
                "raw": [{"image_sha256": "synthetic-image", "text_sha256": "synthetic-text", "required_output_complete": True}]}

    def score(self):
        return [{"joint_loss": .0, "utility": 1., "caption_valid": True, "text_fact": 0.,
                 "relation": 0., "image_fact": 0., "crossmodal_disagreement": 0., "pixel_mse": 0.}]

    def test_full_policy_schedule_is_shuffled_once_without_deleting_rounds(self):
        jobs = _jobs((17, 29), ARMS, (608, 609), ("clean",), 2, 2)
        repeated = _jobs((17, 29), ARMS, (608, 609), ("clean",), 2, 2)
        self.assertEqual(jobs, repeated)
        self.assertEqual(len(jobs), 2 * 18 * 2 * 1 * 2 * 2)
        self.assertEqual(len({tuple(sorted(row.items())) for row in jobs}), len(jobs))
        for arm in ARMS:
            group = [row for row in jobs if row["arm"] == arm]
            self.assertEqual({row["round"] for row in group}, {0, 1})
            self.assertEqual(len({row["policy"] for row in group}), 12 if arm == "output_ndu" else 3)
        self.assertNotEqual(jobs, sorted(jobs, key=lambda row: tuple(row.values())))

    def test_observations_use_full_128_batch_and_one_seed_for_all_views(self):
        calls = []
        def fake(corpus, role, count, seed, *, view, offset):
            calls.append((role, count, seed, view, offset))
            return SimpleNamespace(view=view)
        with patch("experiments.multimodal_output_portfolio.abc_recovery.timing.make_batch", side_effect=fake):
            for views in (TIMING_VIEWS, VIEWS):
                result = _prepare_inputs(object(), views)
                self.assertEqual(tuple(result), views)
        self.assertEqual(calls, [("development", 128, stable_seed("observation", "development", 608), view, 608) for view in TIMING_VIEWS + VIEWS])

    def test_scoring_follows_resident_clock_and_rng_key_ignores_arm_policy_round(self):
        events, keys = [], []
        def episode(*args, **kwargs):
            events.append("episode-ended")
            keys.append(kwargs["actual_stream_key"])
            self.assertEqual(kwargs["planning_seed"], stable_seed("planning", 17))
            self.assertNotIn("target", kwargs)
            return self.success()
        def observer(*args):
            self.assertEqual(events[-1], "episode-ended" if len(events) % 3 == 1 else "scored")
            events.append("scored")
            return self.score()
        with patch("experiments.multimodal_output_portfolio.abc_recovery.timing.resident_episode", side_effect=episode), patch("experiments.multimodal_output_portfolio.abc_recovery.timing.observe_tensors", side_effect=observer):
            rows = [_resident_job(job, object(), self.bundle, self.observation, self.target,
                                  {"primary": object(), "secondary": object()}, Path("synthetic-unused.zip"))
                    for job in (self.job, dict(self.job, arm="output_mean", policy="tuned_static", round=1))]
        self.assertEqual(keys, [(17, 608, "clean", 0)] * 2)
        for row in rows:
            self.assertEqual((row["wall_ns"], row["cpu_ns"]), (101, 83))
            self.assertEqual(row["work"], {"critic_calls": 1, "planner_critic_calls": 1})
            self.assertTrue(all(score["joint_fact_correct"] for score in row["observer_scores"].values()))

    def test_real_generation_exception_keeps_observed_cost_and_explicit_penalty(self):
        with patch("experiments.multimodal_output_portfolio.abc_recovery.timing.resident_episode", side_effect=RuntimeError("synthetic actual invocation failure")), patch("experiments.multimodal_output_portfolio.abc_recovery.timing.observe_tensors") as observer:
            row = _resident_job(self.job, object(), self.bundle, self.observation, self.target,
                                {"primary": object(), "secondary": object()}, Path("synthetic-unused.zip"))
        self.assertEqual(row["status"], "generation_failed")
        self.assertGreater(row["wall_ns"], 0)
        self.assertIn("RuntimeError", row["traceback"])
        self.assertFalse(row["work_complete"])
        self.assertEqual(row["score_origin"], "registered_generation_failure_penalty")
        self.assertEqual(row["observer_scores"]["primary"], {"joint_loss": 1., "utility": -1., "joint_fact_correct": False, "required_output_complete": False})
        observer.assert_not_called()

    def test_observer_exception_preserves_completed_output_and_marks_missing_label(self):
        with patch("experiments.multimodal_output_portfolio.abc_recovery.timing.resident_episode", return_value=self.success()), patch("experiments.multimodal_output_portfolio.abc_recovery.timing.observe_tensors", side_effect=[RuntimeError("observer failed"), self.score()]):
            row = _resident_job(self.job, object(), self.bundle, self.observation, self.target,
                                {"primary": object(), "secondary": object()}, Path("synthetic-unused.zip"))
        self.assertEqual(row["status"], "offline_scoring_failed")
        self.assertIsNone(row["observer_scores"]["primary"])
        self.assertEqual(row["observer_scores"]["secondary"]["utility"], 1.)
        self.assertTrue(row["required_output_complete"])
        self.assertEqual((row["wall_ns"], row["cpu_ns"]), (101, 83))

    def test_policy_hash_covers_weights_normalization_and_profile(self):
        with torch.random.fork_rng(devices=[]):
            torch.random.set_rng_state(torch.Generator().manual_seed(7).get_state())
            snapshot = Snapshot(SlotPortfolio())
            observer = Recognizer().eval().requires_grad_(False)
        heads = [ActionCritic(673, 2., h, h, 4).eval().requires_grad_(False) for h in (1, 2)]
        feedback = Feedback(FiniteHorizonCritic(*heads), dict(PROFILES["feedback"]))
        bundle = {"feedback": feedback, "profiles": {}, "route": None, "static": {"plan": ()}}
        args = ({(17, "output_mean"): snapshot}, {(17, "output_mean"): bundle}, {"primary": observer, "secondary": observer})
        original = _identities(*args)
        with torch.no_grad():
            heads[0].feature_mean[0] += 1
        changed = _identities(*args)
        self.assertNotEqual(original["policies"], changed["policies"])
        self.assertEqual(original["models"], changed["models"])
        feedback.profile["draft_mode"] = "masked"
        self.assertNotEqual(changed["policies"], _identities(*args)["policies"])

    def test_summary_preserves_full_census_missing_scores_and_source_groups(self):
        score = {"utility": 1., "joint_loss": 0., "joint_fact_correct": True, "required_output_complete": True}
        for views, expected in ((TIMING_VIEWS, 8640), (VIEWS, 23040)):
            rows = []
            for job in _jobs(SEEDS, ARMS, range(608, 616), views, 2, 2):
                rows.append({**job, "wall_ns": 101, "cpu_ns": 83, "raw": None, "status": "completed",
                             "required_output_complete": True, "observer_scores": {"primary": score, "secondary": score}})
            self.assertEqual(len(rows), expected)
            rows[0] = {**rows[0], "status": "offline_scoring_failed", "observer_scores": {"primary": None, "secondary": score}}
            def summarize(array, **kwargs):
                self.assertEqual(array.shape, (5, 8, len(views), 2, 2))
                return {"source_groups": array.shape[1], "training_seeds": array.shape[0]}
            with patch("experiments.multimodal_output_portfolio.abc_recovery.timing.cost_summary", side_effect=summarize):
                conditions, _, _ = _summaries(rows, views)
                first = conditions[rows[0]["arm"] + "/" + rows[0]["policy"]]
                self.assertIsNone(first["quality_including_explicit_generation_failure_penalties"]["primary"]["means"])
                self.assertEqual(first["physical_required_output_complete_rate"], 1.)
                self.assertEqual(first["cost"]["wall_ms"], {"source_groups": 8, "training_seeds": 5})
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    _summaries(rows + [rows[0]], views)
                with self.assertRaisesRegex(ValueError, "Incomplete"):
                    _summaries(rows[1:], views)


if __name__ == "__main__":
    unittest.main()

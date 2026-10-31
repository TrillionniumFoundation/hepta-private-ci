"""Synthetic resident requests: causal costs, pairing, evidence and census."""

import hashlib
import io
import unittest
from unittest.mock import patch

import numpy as np
import torch

from ..abc_recovery.control import PLANS
from ..abc_recovery.runtime import public_features
from ..v6.data import Target
from ..v7.model import SlotPortfolio
from .design.common_history_data import public_observation
from .observability import PublicDigitSensor
from .settings import ARMS, FIXED_PLAN, SEEDS
from ..v7.data import VIEWS
from .timing import POLICIES, TIMING_PROFILE, deserialize_terminal, owner_rng, policy_order, request
from .timing_analysis import aggregate, validate_rows


class ScriptedController:
    def __init__(self, mode="base", stop=False, fail_second=False):
        self.mode, self.stop, self.fail_second = mode, stop, fail_second

    def choose(self, values, remaining):
        if self.mode == "base" and torch.any(values[:, 672:762] != 0):
            raise AssertionError("Base mode unexpectedly used sensor columns")
        if self.fail_second and remaining == 1:
            raise RuntimeError("synthetic second decision failed")
        return torch.tensor([0 if self.stop else 2 if remaining == 2 else 3])

    def choose_plan(self, values):
        return torch.tensor([PLANS.index(FIXED_PLAN)])


class ScriptedLegacy:
    def action(self, model, frame, work):
        public_features(model, frame, work=work)
        work["critic_calls"] += 1
        return "refine_image" if frame.remaining == 2 else "refine_text"


class TimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(713)
            cls.model = SlotPortfolio().eval().requires_grad_(False)
            cls.sensor = PublicDigitSensor(714).eval().requires_grad_(False)

    def execute(self, policy, controller=None, sensor=None):
        return request(self.model, public_observation(0), policy,
            controller=controller or ScriptedController(), legacy=ScriptedLegacy(), sensor=sensor,
            static_plan_index=PLANS.index(FIXED_PLAN), seed=17, case=0, view="both_missing", scenario=0)

    def test_only_selected_paths_execute_and_shared_paths_share_actual_outputs(self):
        outputs = []
        with patch.object(self.sensor, "forward", side_effect=AssertionError("A base policy ran the sensor")):
            for policy in POLICIES:
                row, raw = self.execute(policy, sensor=self.sensor)
                self.assertEqual(row["status"], "completed", row["error"])
                self.assertEqual(tuple(row["completed_path"]), FIXED_PLAN)
                self.assertEqual(row["work"]["emission_calls"], 3)
                self.assertEqual(row["work"]["encoder_examples"], 1)
                self.assertGreater(row["request_wall_ns"], 0)
                pixels, tokens, _ = deserialize_terminal(raw, row["payload_sha256"])
                outputs.append((pixels, tokens))
                if policy == "feedback":
                    self.assertEqual(row["work"]["critic_calls"], 2)
                if policy == "one_shot":
                    self.assertEqual(row["work"]["route_head_calls"], 1)
                    self.assertNotIn("critic_calls", row["work"])
        self.assertTrue(all(torch.equal(a, outputs[0][0]) and torch.equal(b, outputs[0][1]) for a, b in outputs))
        row, _ = self.execute("feedback", ScriptedController(stop=True))
        self.assertEqual(row["completed_path"], [])
        self.assertEqual(row["work"]["emission_calls"], 1)
        self.assertEqual(row["work"]["critic_calls"], 1)

    def test_enriched_input_is_cached_and_only_observed_drafts_are_charged(self):
        for policy, draft_calls in (("feedback", 2), ("one_shot", 1)):
            row, _ = self.execute(policy, ScriptedController(mode="enriched"), self.sensor)
            self.assertEqual(row["status"], "completed", row["error"])
            self.assertEqual(row["work"]["public_input_sensor_calls"], 1)
            self.assertEqual(row["work"]["public_draft_sensor_calls"], draft_calls)
            self.assertEqual(row["work"]["public_draft_sensor_panel_examples"], 2 * draft_calls)
        first = owner_rng(17, 0, "clean", 0, ("refine_image",)).get_state()
        changed = owner_rng(17, 0, "clean", 1, ("refine_image",)).get_state()
        self.assertFalse(torch.equal(first, changed))

    def test_failed_decision_retains_actual_elapsed_work_and_no_fabricated_output(self):
        row, raw = self.execute("feedback", ScriptedController(fail_second=True))
        self.assertEqual(row["status"], "request_failed")
        self.assertEqual(row["completed_path"], ["refine_image"])
        self.assertEqual(row["work"]["emission_calls"], 2)
        self.assertEqual(row["error"]["stage"], "public_policy")
        self.assertGreater(row["request_cpu_ns"], 0)
        self.assertIsNone(raw)
        with self.assertRaisesRegex(ValueError, "public request"):
            request(self.model, Target(torch.zeros(1, 1, 28, 56), torch.zeros(1, 8), torch.zeros(1, 2)), "fixed",
                controller=None, legacy=None, sensor=None, static_plan_index=0, seed=17, case=0, view="clean", scenario=0)

    def test_payload_and_inner_content_corruption_are_both_rejected(self):
        row, raw = self.execute("fixed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            deserialize_terminal(raw[:-1], row["payload_sha256"])
        with np.load(io.BytesIO(raw), allow_pickle=False) as saved:
            record = {key: saved[key].copy() for key in saved.files}
        record["pixels_bits"][0, 0] ^= 1
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **record)
        changed = buffer.getvalue()
        with self.assertRaisesRegex(ValueError, "identity differs"):
            deserialize_terminal(changed, hashlib.sha256(changed).hexdigest())

    def census(self):
        sources = [(f"synthetic:{2 * case}", f"synthetic:{2 * case + 1}") for case in range(16)]
        entries = {(seed, arm): {"selection": {"selected_nonfeedback": "fixed" if i % 2 == 0 else "static"}} for i, seed in enumerate(SEEDS) for arm in ARMS}
        rows, group = [], 0
        for seed in SEEDS:
            for arm in ARMS:
                for view in VIEWS:
                    for case in range(16):
                        for scenario in range(2):
                            for position, policy in enumerate(policy_order(group)):
                                row = {"seed": seed, "arm": arm, "policy": policy, "case": case, "view": view,
                                    "scenario": scenario, "group_ordinal": group, "order_position": position,
                                    "stream_identity_without_arm_or_policy": [seed, case, view, scenario],
                                    "source_ids": sources[case], "selected_nonfeedback": entries[seed, arm]["selection"]["selected_nonfeedback"],
                                    "status": "completed", "work": {}, "completed_path": [], "required_output_complete": True,
                                    "request_wall_ns": 1e6 * (1 + POLICIES.index(policy)), "request_cpu_ns": 1e6,
                                    "archive_append_wall_ns": 10., "archive_append_cpu_ns": 10., "scoring_wall_ns": 20., "scoring_cpu_ns": 20.}
                                metric = {"utility": .1 * POLICIES.index(policy), "joint_loss": .4,
                                    "joint_fact_correct": 0., "required_output_complete": 1., "text_fact": .5,
                                    "relation": .5, "image_fact": .5, "crossmodal_disagreement": .5, "pixel_mse": .5}
                                row["observer_scores"] = {name: dict(metric) for name in ("primary", "secondary")}
                                rows.append(row)
                            group += 1
        return rows, entries, sources

    def test_census_rejects_missing_replays_wrong_sources_and_unpaired_order(self):
        rows, entries, sources = self.census()
        validate_rows(rows, entries, sources)
        for mutation, message in (({"source_ids": sources[1]}, "source"),
                                  ({"order_position": 4}, "rotation"),
                                  ({"selected_nonfeedback": "one_shot"}, "reference")):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, message):
                validate_rows([{**rows[0], **mutation}, *rows[1:]], entries, sources)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            validate_rows(rows[:-1], entries, sources)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_rows([*rows, rows[0]], entries, sources)

    def test_statistics_keep_frozen_per_seed_reference_and_failures_block_quality(self):
        rows, entries, sources = self.census()
        with patch.dict(TIMING_PROFILE["bootstrap"], {"replicates": 8}):
            result = aggregate(rows, entries, sources)
        chosen = result["comparisons"]["output_ndu/feedback-minus-selected_nonfeedback"]
        self.assertEqual(chosen["frozen_reference_policy_per_training_seed"],
            {str(seed): entries[seed, "output_ndu"]["selection"]["selected_nonfeedback"] for seed in SEEDS})
        self.assertAlmostEqual(chosen["cost_increase"]["wall_ms"]["point_estimates"]["mean"], 2.6)
        self.assertEqual(chosen["cost_increase"]["wall_ms"]["counts"]["source_pairs"], 16)
        self.assertFalse(result["rows_are_independent_sample_size"])
        rows[0] = {**rows[0], "status": "request_failed", "observer_scores": {}, "required_output_complete": False}
        with patch.dict(TIMING_PROFILE["bootstrap"], {"replicates": 8}):
            failed = aggregate(rows, entries, sources)
        self.assertEqual(failed["requests"], 19200)
        self.assertEqual(failed["status"], "completed_with_failures")
        self.assertFalse(failed["conditions"]["sft_continuation/fixed"]["observers"]["primary"]["quality_inference_available"])
        self.assertEqual(failed["conditions"]["sft_continuation/fixed"]["cost"]["wall_ms"]["counts"]["observed_rows"], 1280)


if __name__ == "__main__":
    unittest.main()

"""Executed host/geometry regressions; these do not establish model quality."""

import copy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from ndu_real_materials.common import binding, write_json
from .action_effects import observation_key, public_actions
from .controllers import ControlPlan
from .episode import EpisodeHost
from .ocr import candidate_features


class ActionEffectsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / "source.png"
        image = Image.new("RGB", (40, 20), "white")
        image.paste("black", (20, 0, 40, 20))
        image.save(source)
        overview = self.root / "overview.png"
        image.resize((10, 5)).save(overview)
        self.packet = {
            "schema": "ndu.real.public-case.v1",
            "case_id": "effect-regression",
            "prompt": "Read the total",
            "public_text": "TOTAL 12.50",
            "overview": binding(overview, self.root),
            "source_size": {"width": 40, "height": 20},
            "initial_delivery": {"text": None, "image": None},
            "requirements": {"text": True, "image": True},
            "action_contract": {},
        }
        write_json(self.root / "case.json", self.packet)
        write_json(
            self.root / "reference.json",
            {
                "role": "development",
                "case_id": "effect-regression",
                "source_group": "one-source",
                "episode_group": "one-episode",
                "source_image": binding(source, self.root),
            },
        )
        plan = ControlPlan()
        write_json(
            self.root / "control.json",
            {
                "control": asdict(plan),
                "episode_wall_seconds": 60.0,
                "seed": 0,
                "fixed_schedule": [],
            },
        )
        self.host = EpisodeHost(
            {
                "material_root": str(self.root),
                "latency_weight": plan.latency_weight,
                "episode_wall_seconds": 60.0,
            },
            {
                "role": "development",
                "id": "effect-regression",
                "source_id": "one-source",
                "episode_group": "one-episode",
                "packet": binding(self.root / "case.json", self.root),
                "reference": binding(self.root / "reference.json", self.root),
            },
            {
                "original_operation_id": "observed-effects",
                "control_plan": str(self.root / "control.json"),
                "weights": str(self.root / "unused-weights.pt"),
                "model_sha256": "a" * 64,
            },
            self.root / "episode",
        )
        self.addCleanup(self.host.meter.finish)
        self.identity = {
            "case_id": "effect-regression",
            "weights_sha256": "a" * 64,
            "utility_profile_sha256": self.host.utility_profile_sha256,
            "control_profile_sha256": self.host.control_profile_sha256,
            "memory_mode": "reset",
        }
        self.host.callback({"schema": "ndu.real.actor-ready.v1", **self.identity})

    def execute(self, name, arguments=None):
        value = {
            "schema": "ndu.real.actor-observation.v1",
            **self.identity,
            "step": len(self.host.steps),
            "parameters_unchanged": True,
            "action": {
                "schema": "ndu.real.actor-action.v1",
                "action": name,
                "arguments": arguments or {},
            },
        }
        self.host.callback(value)
        return value["action_effect"]

    def test_prepare_read_and_stop_have_distinct_executed_effects(self):
        first = self.execute("PREPARE_ROI", {"bbox": [0, 0, 20, 20]})
        self.assertEqual(first["changed"], ["preparation"])
        second = self.execute("READ_ROI")
        self.assertEqual(second["changed"], ["observation"])
        self.assertNotIn("READ_ROI", public_actions(self.packet, self.host.last_public))
        with self.assertRaisesRegex(ValueError, "public support"):
            self.execute("READ_ROI")
        self.assertEqual(len(self.host.steps), 2)
        terminal = self.execute("STOP")
        self.assertEqual(terminal["outcome"], "terminal")
        self.assertEqual(terminal["changed"], [])
        self.assertIsNone(second["semantic_quality_gain"])

    def test_new_preparation_reenables_a_real_different_crop(self):
        self.execute("PREPARE_ROI", {"bbox": [0, 0, 20, 20]})
        self.execute("READ_ROI")
        first = copy.deepcopy(self.host.observation)
        self.execute("PREPARE_ROI", {"bbox": [20, 0, 40, 20]})
        self.assertIn("READ_ROI", public_actions(self.packet, self.host.last_public))
        self.execute("READ_ROI")
        self.assertNotEqual(first["sha256"], self.host.observation["sha256"])
        with Image.open(self.host.public / self.host.observation["path"]) as crop:
            self.assertEqual(crop.getpixel((0, 0)), (0, 0, 0))

    def test_repeated_output_is_not_counted_as_content_progress(self):
        first = self.execute("WRITE_TEXT", {"text": "12.50"})
        self.assertEqual(first["changed"], ["text"])
        repeated = self.execute("WRITE_TEXT", {"text": "12.50"})
        self.assertEqual(repeated["outcome"], "no_public_change")
        box = {"bbox": [0, 0, 20, 20]}
        self.assertEqual(self.execute("RENDER_IMAGE", box)["changed"], ["image"])
        old_path = self.host.delivery["image"]["path"]
        effect = self.execute("RENDER_IMAGE", box)
        self.assertNotEqual(old_path, self.host.delivery["image"]["path"])
        self.assertEqual(effect["outcome"], "no_public_change")
        self.assertEqual(effect["before"], effect["after"])

    def test_identical_pixel_crops_keep_distinct_source_coordinates(self):
        image_path = self.root / "identical.png"
        Image.new("RGB", (20, 20), "white").save(image_path)
        observed = {
            "path": "identical.png",
            "sha256": binding(image_path, self.root)["sha256"],
            "kind": "roi",
            "bbox": [0, 0, 20, 20],
        }
        moved = {**observed, "bbox": [20, 0, 40, 20]}
        self.assertNotEqual(
            observation_key(self.packet, observed), observation_key(self.packet, moved)
        )
        self.assertEqual(
            observation_key(self.packet, observed),
            observation_key(self.packet, {**observed, "path": "renamed.png"}),
        )
        lines = [
            {
                "text": "12.50",
                "bbox": [0, 0, 10, 10],
                "origin": "pixel_ocr",
                "confidence": 1.0,
            }
        ]
        encoded = [
            candidate_features(
                lines,
                prompt=self.packet["prompt"],
                image_path=image_path,
                source_size=(40, 20),
                observation_bbox=row["bbox"],
            )
            for row in (observed, moved)
        ]
        self.assertEqual(encoded[0][0][0]["bbox"], [0, 0, 10, 10])
        self.assertEqual(encoded[1][0][0]["bbox"], [20, 0, 30, 10])
        self.assertFalse(np.array_equal(encoded[0][1], encoded[1][1]))


if __name__ == "__main__":
    unittest.main()

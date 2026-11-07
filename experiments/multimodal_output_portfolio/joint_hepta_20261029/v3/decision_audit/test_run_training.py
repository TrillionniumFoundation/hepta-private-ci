"""Orchestration guards only; mocked calls are not neural execution evidence."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import run_training as module


class TrainingOrchestration(unittest.TestCase):
    def exercise(self, text, image):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            root = Path(folder)
            source = root / "evidence" / "real_20261105"; source.mkdir(parents=True)
            data = b"fixture bytes; image decoding is outside this orchestration test"
            (source / "input.png").write_bytes(data)
            (source / "REVIEW.json").write_text(json.dumps({
                "source_sha": "a" * 40,
                "original_file_manifest": [{"path": "real/input.png",
                    "sha256": hashlib.sha256(data).hexdigest()}]}))
            with patch.object(module, "__file__", str(root / "runner.py")), \
                    patch.object(module, "train_text", return_value=text) as text_call, \
                    patch.object(module, "train_image", return_value=image) as image_call, \
                    patch.object(module, "AdaptedLocalModels") as backend, \
                    patch.object(module, "run", return_value={"status": "delivered",
                        "error": None, "selected": []}) as runtime:
                result = module.execute("fixture-models", root / "out", "b" * 40)
                return result, text_call, image_call, backend, runtime

    def test_unqualified_image_checkpoint_cannot_fall_back_to_frozen(self):
        okay = {"status": "completed", "completed_updates": 2,
                "checkpoint": {"path": "model.safetensors", "sha256": "c" * 64}}
        result, _, _, backend, runtime = self.exercise(okay, {**okay, "checkpoint_qualified": False})
        self.assertEqual(result["completed_generators"], 1)
        self.assertEqual(result["inference"]["status"], "not_run_unqualified_training")
        backend.assert_not_called(); runtime.assert_not_called()

    def test_cancelled_training_does_not_start_another_generator(self):
        result, _, image, backend, runtime = self.exercise(
            {"status": "cancelled", "completed_updates": 1, "checkpoint": None}, {})
        self.assertEqual(result["completed_generators"], 0)
        self.assertEqual(result["stages"][1]["status"], "not_run_after_cancellation")
        image.assert_not_called(); backend.assert_not_called(); runtime.assert_not_called()

    def test_both_admitted_checkpoints_use_one_fixed_real_runtime_interface(self):
        okay = {"status": "completed", "completed_updates": 2,
                "checkpoint": {"path": "model.safetensors", "sha256": "c" * 64}}
        result, text, image, backend, runtime = self.exercise(okay, {**okay, "checkpoint_qualified": True})
        self.assertEqual(result["completed_generators"], 2)
        self.assertEqual(result["holdout_count"], 0)
        self.assertFalse(result["joint_training_efficacy"])
        self.assertEqual(set(backend.call_args.args[2]), {"vlm", "sd"})
        self.assertEqual(runtime.call_args.args[2].actions, module.ACTIONS)
        self.assertEqual(runtime.call_args.args[0].instruction, module.INSTRUCTION)
        self.assertEqual(text.call_args.kwargs["steps"], 2)
        self.assertEqual(image.call_args.kwargs["steps"], 2)


if __name__ == "__main__":
    unittest.main()

"""Targeted checks of cross-codec observation, secrecy, and supplied-law control."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from .media import emit, readback
from .model import PublicTask, choose_initial, exact_diagnostic, fit_posterior


class MechanismTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())

    def test_real_codecs_and_fault_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for code in range(4):
                for fault in range(3):
                    paths = emit(Path(tmp) / f"{code}-{fault}", code, fault)
                    observed = readback(paths)
                    self.assertEqual((observed["codes"]["text"], observed["fault_class"]), (code, fault))
                    self.assertEqual(observed["target_supplied"], False)
            checked = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,nb_frames,r_frame_rate",
                                      "-of", "json", paths["video"]], check=True, capture_output=True, text=True)
            stream = json.loads(checked.stdout)["streams"][0]
            self.assertEqual((stream["codec_name"], stream["width"], stream["height"], stream["nb_frames"], stream["r_frame_rate"]),
                             ("rawvideo", 16, 16, "4", "4/1"))
            decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", paths["video"], "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                     check=True, capture_output=True)
            self.assertEqual(len(decoded.stdout), 4 * 16 * 16 * 3)

    def test_target_cannot_be_passed_to_public_policy(self):
        with self.assertRaises(TypeError):
            PublicTask(cue=1, target=2)
        with self.assertRaises(TypeError):
            choose_initial({"cue": 1, "target": 2}, np.zeros((4, 3)), "mean", self.spec)

    def test_existing_bellman_matches_full_finite_policy_enumeration(self):
        for law in self.spec["target_law_by_cue"]:
            result = exact_diagnostic(self.spec, law)
            self.assertLess(result["absolute_error"], 1e-8)
            self.assertEqual(int(result["bellman_action"]), result["enumerated_action"])

    def test_posterior_training_updates_and_identifies_risk_ranking(self):
        weights, receipt = fit_posterior(self.spec)
        self.assertNotEqual(receipt["initial_parameter_sha256"], receipt["final_parameter_sha256"])
        self.assertGreater(receipt["nll_before_and_last_update"][0], receipt["nll_before_and_last_update"][1])
        self.assertNotEqual(choose_initial(PublicTask(0), weights, "mean", self.spec)[0],
                            choose_initial(PublicTask(0), weights, "risk", self.spec)[0])


if __name__ == "__main__":
    unittest.main()

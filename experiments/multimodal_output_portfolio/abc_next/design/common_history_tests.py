"""Synthetic integration checks; no registered source or trained model is read."""

from collections import Counter
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, public_digest, public_frame, transition
from ...v6.data import SourceSplit
from ...v7.model import SlotPortfolio, observation_digest
from .common_history_data import offline_utilities, private_targets, public_observation, replicate_public_run, stream_seed
from .common_history_run import collect_phase


class ZeroReader(torch.nn.Module):
    def forward(self, pixels):
        result = torch.zeros(len(pixels), 10)
        result[:, 0] = 1
        return result


class CommonHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def setUp(self):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(29041)
            self.model = SlotPortfolio().eval().requires_grad_(False)
        images = torch.stack([torch.full((1, 28, 28), value, dtype=torch.uint8) for value in (0, 255, 64, 192)])
        self.pool = SourceSplit(images, torch.tensor([0, 1, 2, 3]), ("a", "b", "c", "d"), ("a", "b", "c", "d"))

    @torch.inference_mode()
    def test_private_targets_do_not_change_public_history_and_swaps_are_offline(self):
        observation = public_observation(0)
        digest = observation_digest(observation)
        ordinary = private_targets(self.pool, 0, 2, 0)
        swapped = private_targets(self.pool, 0, 2, 1)
        self.assertTrue(torch.equal(swapped.labels, ordinary.labels.flip(1)))
        self.assertTrue(torch.equal(swapped.pixels[..., :28], ordinary.pixels[..., 28:]))
        self.assertEqual(observation_digest(public_observation(0)), digest)
        self.assertEqual(observation.pixels.count_nonzero().item(), 0)
        self.assertEqual(observation.mask.count_nonzero().item(), 0)
        roots = [initialize(self.model, public_observation(0), generator=torch.Generator().manual_seed(919)) for _ in (ordinary, swapped)]
        self.assertEqual(public_digest(public_frame(roots[0])), public_digest(public_frame(roots[1])))

    @torch.inference_mode()
    def test_counterfactual_branches_preserve_root_and_declared_determinism(self):
        root = replace(initialize(self.model, public_observation(1), generator=torch.Generator().manual_seed(919)), remaining=1)
        digest = public_digest(public_frame(root))
        for replicas in (3, 5):
            parent = replicate_public_run(root, replicas)
            for action in ("stop", "refine_semantic"):
                child = transition(self.model, parent, action, generator=torch.Generator().manual_seed(720))
                self.assertTrue(torch.equal(child.pixels, root.pixels.repeat(replicas, 1, 1, 1)))
                self.assertTrue(torch.equal(child.tokens, root.tokens.repeat(replicas, 1)))
                self.assertIsNone(child.ledger[-1]["innovation_rng_before_sha256"])
                self.assertTrue(child.done)
            self.assertEqual(public_digest(public_frame(root)), digest)
        streams = [stream_seed(phase, history, action) for phase in ("fit", "evaluation")
                   for history in range(8) for action in ("stop", "refine_semantic", "refine_image", "refine_text", "couple")]
        self.assertEqual(len(streams), len(set(streams)))

    @torch.inference_mode()
    def test_actual_closed_media_to_complete_target_census(self):
        root = replace(initialize(self.model, public_observation(0), generator=torch.Generator().manual_seed(221)), remaining=1)
        target = private_targets(self.pool, 0, 2, 0)
        snapshot = type("SyntheticSnapshot", (), {"_model": self.model})()
        timings, work = {}, Counter()
        with tempfile.TemporaryDirectory() as directory:
            values, receipt = collect_phase("synthetic", 3, [root], snapshot, {0: target},
                {"primary": ZeroReader()}, Path(directory), timings, work)
            self.assertEqual(values["primary"].shape, (1, 2, 3, 5))
            self.assertEqual(receipt["actual_terminal_media_rows"], 15)
            self.assertEqual(receipt["target_scoring_rows_per_observer"], 30)
            np.testing.assert_allclose(values["primary"][0, :, :, 1], values["primary"][0, :, :, 0] - .002, atol=1e-14)
            self.assertEqual(work["sampled_bernoulli_variables"], 3 * 3 * 28 * 56)
            self.assertTrue((Path(directory) / "synthetic-actual-media.zip").is_file())
        with self.assertRaisesRegex(ValueError, "census"):
            offline_utilities(ZeroReader(), root.pixels, ["left 0 right 0 relation equal"], target, 3, [0, .002])


if __name__ == "__main__":
    unittest.main()

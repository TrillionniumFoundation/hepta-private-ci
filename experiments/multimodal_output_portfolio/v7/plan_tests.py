"""Controlled initialization, raw initial trace, and metric-scope invariants."""

from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from .data import make_batch
from .metric import EndpointLabeler, MetricContract
from .model import SlotPortfolio
from .model_tests import fixture_corpus
from .plans import ALLOCATION_PLAN, ControlledSnapshot, PLANS, PlanHead, load_snapshot
from .snapshot import Snapshot


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def test_actual_initial_trace_and_no_content_ablation(self):
        torch.manual_seed(31)
        base = Snapshot(SlotPortfolio())
        gate = PlanHead()
        with torch.no_grad():
            gate.net[-1].weight.zero_()
            gate.net[-1].bias[:] = torch.tensor([5., 0., 0., 0.])
        snapshot = ControlledSnapshot(base, gate)
        observation = make_batch(fixture_corpus(), "train", 1, 81, "clean").observation
        state = snapshot.encode(observation, 99)
        replay = base.encode(observation, 99)
        for index in range(3):
            self.assertEqual(state.initial_state_keys[index], base.state_key(replay))
            for block, name in zip(state.initial_tensor_bits[index], ("h", "image", "text", "context")):
                restored = np.array(block, dtype=np.uint32).view(np.float32).reshape(1, 96)
                self.assertTrue(np.array_equal(restored, getattr(replay, name).numpy()))
            if index < 2:
                replay = base.step(replay, PLANS[0][index])
        self.assertEqual(state.initial_actions, PLANS[0])
        self.assertEqual(state.step_count, 2)
        self.assertTrue(torch.equal(state.neural.h, replay.h))
        allocation = snapshot.encode(observation, 99, content_control=False)
        self.assertEqual(allocation.initial_actions, ALLOCATION_PLAN)
        self.assertTrue(torch.equal(allocation.neural.h, base.encode(observation, 99).h))
        for action in ("refine_image", "refine_text"):
            allocation = snapshot.step(allocation, action)
        self.assertEqual(allocation.step_count, 4)
        self.assertTrue(torch.equal(allocation.neural.h, base.encode(observation, 99).h))
        with self.assertRaises(ValueError):
            snapshot.step(allocation, "couple")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate.pt"
            sha = snapshot.save(path)
            restored = load_snapshot(path, expected_file_sha256=sha)
            second = restored.encode(observation, 99)
            self.assertEqual(snapshot.state_key(state), restored.state_key(second))
            self.assertTrue(torch.equal(snapshot.decode(state).token_ids, restored.decode(second).token_ids))
            self.assertTrue(torch.equal(snapshot.semantic_probabilities(state),
                                        restored.semantic_probabilities(second)))

    def test_metric_scope_cannot_exceed_declared_required_modalities(self):
        contract = MetricContract("proxy", 15, 3, -1., 1., "a" * 64,
                                  (("producer", "b" * 64),), "quantized_media_payloads")
        self.assertEqual(len(contract.validate()), 64)
        with self.assertRaises(ValueError):
            MetricContract("invalid", 3, 15, -1., 1., "a" * 64,
                           (("producer", "b" * 64),), "full_codec_containers").validate()
        base = Snapshot(SlotPortfolio())
        batch = make_batch(fixture_corpus(), "train", 1, 10, "clean")
        state = base.encode(batch.observation)
        labeler = EndpointLabeler(contract, lambda *_: [{"utility": 1.1, "raw_sha256": {"test": "c" * 64}}],
                                   lambda: None)
        with self.assertRaises(ValueError):
            labeler.label(base, state, batch.target)


if __name__ == "__main__":
    unittest.main()

"""Physical-output and causal intervention tests; no model-quality assertions."""

import json
from pathlib import Path
import tempfile
import unittest

import torch

from .media import read_bundle, utility, write_read
from .mechanism_data import batch
from .model import ACTIONS, JointGenerator, tensor_digest
from .runtime import execute, make_profile


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(237)
        self.model = JointGenerator(width=8)
        self.public, self.target = batch([3], "unit")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_episode(self, name, **kwargs):
        return execute(self.model, self.public, lambda output: utility(output, self.target).item(),
                       self.root / name, seed=89, context_id="unit.3", source_id="unit-source.3", **kwargs)

    def test_actual_four_files_and_single_ledger(self):
        result = self.run_episode("actual", strategy="fixed", deterministic_emission=True)
        readback, identities = read_bundle(self.root / "actual" / "outputs")
        self.assertEqual(dict(result.record["outcome"]["artifact_sha256"]), identities)
        self.assertEqual(result.record["events"][-1]["terminal_kind"], "delivered")
        self.assertAlmostEqual(result.net_return, utility(readback, self.target).item()-result.record["actual_cost"])
        self.assertTrue(result.record["contract_validated"])
        self.assertTrue(result.terminal_state.stopped)
        with self.assertRaises(ValueError):
            self.model.advance(result.terminal_state, "shared", self.public)
        self.assertEqual(json.loads((self.root/"actual"/"TRAJECTORY.json").read_text())["net_return"], result.net_return)

    def test_feedback_changes_subsequent_action_and_file_bytes(self):
        # A deliberate controller intervention tests the route, not training success.
        with torch.no_grad():
            for p in self.model.actor.parameters():
                p.zero_()
            self.model.actor[0].weight[0, 2*self.model.width] = 2
            self.model.actor[-1].weight[ACTIONS.index("image"), 0] = 10
            self.model.actor[-1].weight[ACTIONS.index("audio"), 0] = -10
            self.model.actor[-1].bias[ACTIONS.index("stop")] = -20
        kwargs = {"prefix": ("shared", "verify"), "strategy": "greedy", "deterministic_emission": True}
        positive = self.run_episode("positive", feedback_override=torch.tensor([[1., 0., 0.]]), **kwargs)
        negative = self.run_episode("negative", feedback_override=torch.tensor([[-1., 0., 0.]]), **kwargs)
        self.assertEqual(positive.record["actions"][2]["action"], "image")
        self.assertEqual(negative.record["actions"][2]["action"], "audio")
        self.assertNotEqual(positive.record["outcome"]["artifact_sha256"], negative.record["outcome"]["artifact_sha256"])

    def test_joint_score_reaches_real_generator_and_actor(self):
        result = self.run_episode("gradient", prefix=("shared", "verify"))
        result.log_probability.backward()
        for prefix in ("core.", "encoder_fusion.", "actor.", "emissions.image.", "emissions.audio.", "emissions.video.", "emissions.text."):
            values = [p.grad for n, p in self.model.named_parameters() if n.startswith(prefix) and p.grad is not None]
            self.assertTrue(values, prefix)
            self.assertTrue(all(torch.isfinite(v).all() for v in values), prefix)
            self.assertGreater(sum(v.abs().sum().item() for v in values), 0, prefix)

    def test_codec_coalescing_and_natural_clock(self):
        sample = {m: v.clone() for m, v in self.target.items()}
        sample["video"][:] = sample["video"][:, :1]
        reopened, _ = write_read(sample, self.root / "static", audio_rate=512, frame_ms=500)
        self.assertEqual(tuple(reopened["video"].shape), (1,4,3,16,16))
        self.assertTrue(torch.equal(reopened["video"][:, 0], reopened["video"][:, -1]))
        sample["audio"][0, 0] = float("nan")
        with self.assertRaises(ValueError):
            write_read(sample, self.root/"bad")

    def test_target_field_rejected_and_hepta_intervention_changes_output(self):
        with self.assertRaises(ValueError):
            self.model.encode({**self.public, "target": self.target})
        before = self.run_episode("before", strategy="fixed", deterministic_emission=True)
        with torch.no_grad():
            self.model.core.layers[0].raw_diffusion.add_(0.3)
        after = self.run_episode("after", strategy="fixed", deterministic_emission=True)
        self.assertNotEqual(before.record["outcome"]["artifact_sha256"], after.record["outcome"]["artifact_sha256"])

    def test_observer_failure_remains_in_return_law(self):
        def broken(_):
            raise ValueError("intentional observer failure")
        result = execute(self.model, self.public, broken, self.root/"failure", seed=3,
                         context_id="unit.3", source_id="source.3", strategy="fixed")
        self.assertEqual(result.record["outcome"]["terminal_kind"], "failed")
        self.assertLess(result.net_return, -1.0)
        self.assertTrue(result.record["contract_validated"])


if __name__ == "__main__":
    unittest.main()

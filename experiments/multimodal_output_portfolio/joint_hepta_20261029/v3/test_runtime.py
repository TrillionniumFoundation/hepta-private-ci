"""Integration contracts for charged initial delivery and genuine paired states."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from ..learning import critic_log_moment_loss
from ..mechanism_data import batch
from ..media import utility
from ..model import ACTIONS, tensor_digest
from .model import JointGenerator
from .profile import make_profile
from .runtime import clone_snapshot, execute, start_snapshot
from .training import group_hashes, joint_train


class RuntimeIntegration(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2); torch.manual_seed(7)
        self.model = JointGenerator(width=8)
        self.public, self.target = batch([1], "v3.integration.source")
        self.profile = make_profile()
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_episode(self, name, **options):
        return execute(self.model, self.public, lambda rb: utility(rb, self.target).item(),
            self.directory/name, seed=31, context_id="ctx", source_id="src",
            profile=self.profile, **options)

    def test_initial_stop_is_in_law_and_has_actor_and_content_gradients(self):
        state = self.model.encode(self.public)
        law, _ = self.model.policy(state, 1.0)
        self.assertTrue(bool(torch.isfinite(law).all()))
        (-law[0, -1]).backward()
        self.assertGreater(float(self.model.actor[-1].weight.grad[-1].abs().sum()), 0)
        self.model.zero_grad(set_to_none=True)
        episode = self.run_episode("stop", strategy="stop")
        self.assertEqual([a["action"] for a in episode.record["actions"]], ["stop"])
        self.assertIsNone(episode.record["failure"])
        episode.log_probability.backward()
        self.assertGreater(float(self.model.encoder_fusion[0].weight.grad.abs().sum()), 0)
        self.assertEqual(set(episode.record["outcome"]["artifact_sha256"]), {"image", "audio", "video", "text"})

    def test_frozen_prefix_has_same_first_budget_and_independent_named_noise(self):
        with torch.no_grad():
            snapshot = start_snapshot(self.model, self.public, seed=31, profile=self.profile)
            before = snapshot.digest
            stop = self.run_episode("a", strategy="stop", initial_snapshot=snapshot)
            verify = self.run_episode("b", strategy="stop", prefix=("verify",), initial_snapshot=snapshot)
        self.assertEqual(snapshot.digest, before)
        self.assertEqual(stop.record["initial_snapshot_sha256"], verify.record["initial_snapshot_sha256"])
        self.assertEqual(stop.record["actions"][0]["before_budget"], snapshot.budget)
        self.assertEqual(verify.record["actions"][0]["before_budget"], snapshot.budget)
        self.assertEqual(stop.record["outcome"]["artifact_sha256"], verify.record["outcome"]["artifact_sha256"])
        self.assertGreater(verify.record["actual_cost"], stop.record["actual_cost"])

    def test_snapshot_rejects_changed_content_input_model_and_ledger(self):
        snapshot = start_snapshot(self.model, self.public, seed=31, profile=self.profile)
        for name, damaged in (("budget", replace(snapshot, budget=snapshot.budget-1)),
                              ("hash", replace(snapshot, state_hash="00"*32))):
            with self.assertRaisesRegex(ValueError, "Snapshot"):
                self.run_episode(name, strategy="stop", initial_snapshot=damaged)
        copied = clone_snapshot(snapshot)
        copied.state.shared.add_(1)
        self.assertEqual(tensor_digest(snapshot.state.tensors()), snapshot.state_hash)
        with self.assertRaises(ValueError):
            self.run_episode("content", strategy="stop", initial_snapshot=copied)
        self.public["tokens"][0, 0] += 1
        with self.assertRaises(ValueError):
            self.run_episode("input", strategy="stop", initial_snapshot=snapshot)
        self.public["tokens"][0, 0] -= 1
        with torch.no_grad():
            self.model.actor[-1].bias.add_(0.01)
        with self.assertRaises(ValueError):
            self.run_episode("weight", strategy="stop", initial_snapshot=snapshot)

    def test_final_return_and_critic_targets_include_stop_delivery_and_audit(self):
        episode = self.run_episode("accounting", strategy="stop")
        record = episode.record; events = record["events"]
        self.assertAlmostEqual(sum(e["amount"] for e in events), record["actual_cost"], places=12)
        self.assertAlmostEqual(record["outcome"]["delivered_utility"]-record["actual_cost"], episode.net_return, places=12)
        self.assertAlmostEqual(episode.suffix_returns[0], episode.suffix_returns[-1], places=12)
        self.assertEqual(len(episode.critic_values), len(episode.suffix_returns))
        self.assertEqual(episode.score_terms[-1].prefix_cost, events[0]["amount"])
        sidecar = json.loads((self.directory/"accounting"/"SEAL_COST.json").read_text())
        self.assertEqual(sidecar["net_return_through_seal"], episode.net_return)
        # From the first charged action boundary onward the meter is continuous:
        # final identity/hash checks and record bookkeeping cannot disappear.
        for left, right in zip(events[1:], events[2:]):
            self.assertAlmostEqual(right["meter_cpu_end"]-left["meter_cpu_end"], right["cpu_seconds"], places=10)
            self.assertAlmostEqual(right["meter_wall_end"]-left["meter_wall_end"], right["wall_seconds"], places=10)

    def test_failed_independent_observer_is_retained_and_charged(self):
        def fail(_):
            raise RuntimeError("observer unavailable")
        episode = execute(self.model, self.public, fail, self.directory/"failure", seed=31,
                          context_id="ctx", source_id="src", strategy="stop", profile=self.profile)
        self.assertIn("observer unavailable", episode.record["failure"])
        self.assertLess(episode.net_return, -1.0)
        self.assertTrue((self.directory/"failure"/"outputs"/"image.png").is_file())
        self.assertGreater(sum(e["amount"] for e in episode.record["events"] if e["action"] == "failure"), 0)
        self.assertAlmostEqual(episode.record["actual_cost"], sum(e["amount"] for e in episode.record["events"]), places=12)

    def test_deduplication_expires_after_content_change(self):
        model = JointGenerator(width=8, verify_mode="deduplicate")
        state = model.encode(self.public)
        state, _ = model.advance(state, "verify", self.public)
        self.assertFalse(bool(torch.isfinite(model.policy(state, 1.0)[0][0, ACTIONS.index("verify")])))
        state, _ = model.advance(state, "shared", self.public)
        self.assertTrue(bool(torch.isfinite(model.policy(state, 1.0)[0][0, ACTIONS.index("verify")])))

    def test_frozen_content_arm_trains_actor_critic_without_weight_drift(self):
        protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
        protocol.update(joint_updates=2, joint_batch=2)
        before = group_hashes(self.model)
        result = joint_train(self.model, content="frozen", policy="dynamic", protocol=protocol,
                            seed=201, directory=self.directory/"training", profile=self.profile)
        after = group_hashes(self.model)
        self.assertEqual(before["generator"], after["generator"])
        self.assertNotEqual(before["actor"], after["actor"])
        self.assertNotEqual(before["critic"], after["critic"])
        self.assertEqual(result["failures"], 0)

    def test_critic_fitting_cannot_modify_content_via_features(self):
        state = self.model.encode(self.public)
        _, prediction = self.model.policy(state, 1.0)
        loss, _ = critic_log_moment_loss(prediction, [0.1])
        loss.backward()
        self.assertIsNone(self.model.encoder_fusion[0].weight.grad)
        self.assertGreater(float(self.model.critic[-1].weight.grad.abs().sum()), 0)


if __name__ == "__main__":
    unittest.main()

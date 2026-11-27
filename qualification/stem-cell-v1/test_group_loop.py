import unittest
from dataclasses import replace

import torch

from group_core import Core
from group_critic import fit_critic
from group_features import FeatureIdentity, FeatureSnapshotV2, content_digest
from group_loop import execute_group
from group_tasks import make_tasks


class RecordingCore(Core):
    def __init__(self):
        super().__init__(8, hidden_dim=16)
        self.feedback_seen = []

    def step(self, tokens, state=None, feedback=None, mask=None):
        self.feedback_seen.append(feedback.detach().clone())
        return super().step(tokens, state, feedback, mask)


class GroupLoopTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(31)
        torch.set_num_threads(1)
        self.tokens = torch.randn(5, 8)
        self.model = Core(8, hidden_dim=16).eval().requires_grad_(False)
        with torch.no_grad():
            initial = self.model(self.tokens.unsqueeze(0)).argmax(1).item()
        self.task = next(t for t in make_tasks("test", 24, seed=22) if t.target != initial)
        self.snapshot = self.snapshot_for(self.task)
        def rows(split, prefix):
            return [dict(features=[.2, .1, .3, .1, .25, .75], stop_success=False,
                         continue_success=False, split=split, source_group=prefix + str(i))
                    for i in range(4)]
        self.critic = fit_critic(rows("validation_fit", "fit"),
                                 rows("validation_calibration", "cal"), cutoff_ns=1, steps=4)

    def snapshot_for(self, task):
        identity = FeatureIdentity("agent:test", 1, "test-revision", "a" * 64,
                                   "b" * 64, content_digest(task.text.encode()), "text")
        return FeatureSnapshotV2(identity, self.tokens, torch.ones(5, dtype=torch.bool))

    def test_online_callbacks_never_use_final_target(self):
        changed = replace(self.task, target=(self.task.target + 1) % 8)
        first = execute_group(self.task, self.model, self.snapshot, self.critic, mode="fixed", max_steps=3)
        second = execute_group(changed, self.model, self.snapshot, self.critic, mode="fixed", max_steps=3)
        for key in ("candidate", "status", "workspace_bindings", "verifier_statuses"):
            self.assertEqual(first[key], second[key])
        self.assertNotEqual(first["status"], "callback_failed")
        self.assertEqual([b["step"] for b in first["workspace_bindings"]], [1, 2, 3])
        self.assertEqual(first["work_observation"]["unknown_operators"], {})

    def test_fixed_depth_preserves_supported_feedback_for_next_state(self):
        model = RecordingCore()
        with torch.no_grad():
            model.head.weight.zero_()
            model.head.bias.zero_()
            model.head.bias[self.task.target] = 1
        model.eval().requires_grad_(False)
        result = execute_group(self.task, model, self.snapshot, self.critic, mode="fixed", max_steps=3)
        self.assertEqual(result["status"], "verifier_accepted_not_independent_eval")
        self.assertEqual(result["workspace_steps"], 3)
        self.assertEqual([f[0, 0].item() for f in model.feedback_seen], [0., 1., 1.])

    def test_ndu_conservatively_stops_with_real_model_and_frozen_critic(self):
        result = execute_group(self.task, self.model, self.snapshot, self.critic, mode="ndu")
        self.assertEqual(result["status"], "ndu_stop:no_supported_net_gain")
        self.assertEqual(result["workspace_steps"], 1)
        self.assertEqual(result["work_observation"]["unknown_operators"], {})
        self.assertFalse(result["ndu_decisions"][0]["continue_computation"])
        binding = result["workspace_bindings"][0]["valuation_binding"]
        self.assertEqual(binding["feature_sha256"], self.snapshot.digest)
        self.assertEqual(binding["critic_sha256"], self.critic.params_sha256)
        self.critic.assert_frozen()

    def test_rejects_unfrozen_model_and_mismatched_feature_input(self):
        self.model.train()
        with self.assertRaises(ValueError):
            execute_group(self.task, self.model, self.snapshot, self.critic)
        self.model.eval()
        changed = replace(self.task, text=self.task.text + "\nChanged public evidence.")
        with self.assertRaises(ValueError):
            execute_group(changed, self.model, self.snapshot, self.critic)


if __name__ == "__main__":
    unittest.main()

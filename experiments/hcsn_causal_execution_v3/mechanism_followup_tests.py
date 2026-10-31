"""Behavioral parity and causal-scope tests, using development worlds only."""

import copy
import unittest

import numpy as np
import torch

from experiments.hcsn_mechanism_content_v2 import mechanism as old
from experiments.hcsn_mechanism_content_v2.renewal import Physics, RenewalCore
from .mechanism_followup import policy, rollout


class MechanismFollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_unsuppressed_and_both_match_frozen_v2_rollouts(self):
        config = old.Config(particles=4)
        for seed in (734911, 734912):
            episode = old.make_episode(seed, config)
            for controller, intervention in (("lightweight", "none"), ("task_value", "none"),
                                              ("task_value", "both")):
                baseline = old.run_arm(RenewalCore(), controller, episode, config,
                                       suppress_events=intervention == "both")
                candidate = rollout(RenewalCore(), controller, episode, config, intervention)
                for name, expected in zip(("trace", "access", "predictions"), baseline[1:], strict=True):
                    self.assertEqual(candidate[name], expected)
                for key in ("accuracy", "nll", "brier", "net_reward", "reads", "mandatory_outputs"):
                    self.assertEqual(candidate["summary"][key], baseline[0][key])

    def test_current_only_cannot_change_pre_first_read_planning(self):
        config = old.Config()
        for seed in (734911, 734912, 734913):
            episode = old.make_episode(seed, config)
            obs = old.Observation(0., episode["initial_x"], 0., [.2] * 5, False)
            physics, matrix = Physics(**episode["calibration"]["estimated"]), old.transition_matrix(5)
            args = ("task_value", obs, 0, config.budget, physics, matrix, config, 734914)
            unmodified = policy(RenewalCore(), *args, "none")
            current = policy(RenewalCore(), *args, "current")
            hypothetical = policy(RenewalCore(), *args, "hypothetical")
            both = policy(RenewalCore(), *args, "both")
            self.assertEqual(unmodified, current)
            self.assertEqual(hypothetical, both)
            self.assertNotEqual(unmodified[1]["candidate_values"], hypothetical[1]["candidate_values"])

    def test_fixed_action_replay_preserves_actions_and_unsuppressed_outputs(self):
        config = old.Config()
        episode = old.make_episode(734912, config)
        reference = rollout(RenewalCore(), "task_value", episode, config)
        schedule = {row["tick"]: row["executed_action"] for row in reference["trace"]}
        for intervention in ("current", "hypothetical", "both"):
            changed = rollout(RenewalCore(), "fixed_action_replay", episode, config, intervention, schedule)
            self.assertEqual(reference["predictions"], changed["predictions"])
            self.assertEqual(reference["access"], changed["access"])
            self.assertEqual(schedule, {row["tick"]: row["executed_action"] for row in changed["trace"]})

    def test_unobserved_future_payload_cannot_change_initial_action(self):
        config = old.Config()
        original = old.make_episode(734911, config)
        altered = copy.deepcopy(original)
        altered["path"]["content"] = [(label + 2) % config.classes for label in original["path"]["content"]]
        altered["path"]["x"] = [3 * x for x in original["path"]["x"]]
        for intervention in ("none", "current", "hypothetical", "both"):
            left = rollout(RenewalCore(), "task_value", original, config, intervention)
            right = rollout(RenewalCore(), "task_value", altered, config, intervention)
            first_read = min((r["reveal_tick"] for r in left["access"]), default=config.ticks + 1)
            self.assertEqual([r for r in left["trace"] if r["tick"] < first_read],
                             [r for r in right["trace"] if r["tick"] < first_read])


if __name__ == "__main__":
    unittest.main()

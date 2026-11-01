"""Planner/owner compatibility checks before any new confirmation world."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from ..addressed_decision_r15_20261101.execution import run_episode
from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from .compression import BlockLaw, pack, unpack
from .execution import AnchoredPlanner, execute


class ExecutionTests(unittest.TestCase):
    def test_original_execution_and_boundary_recovery(self):
        law = BlockLaw.from_payload(Law().export())
        for domain in ("iid", "ood"):
            episode = make_episode(law, 160610000000001, domain)
            for policy, pattern in (("value", "stop"), ("fixed", "stop"), ("fixed", "read")):
                original = run_episode(law, episode, policy=policy, pattern=pattern)
                with tempfile.TemporaryDirectory() as directory:
                    replay = execute(law, episode, policy, pattern, checkpoint_path=Path(directory) / "state.json")
                self.assertEqual(original["queries"], replay["queries"])

    def test_compressed_checkpoint_preserves_actions(self):
        law = BlockLaw.from_payload(Law().export())
        for kind in ("block", "anchored"):
            episode = make_episode(law, 160610000000003, "ood")
            plain = execute(law, episode, representation=kind)
            with tempfile.TemporaryDirectory() as directory:
                restored = execute(law, episode, representation=kind, checkpoint_path=Path(directory) / "state.json")
            self.assertEqual(plain["queries"], restored["queries"])

    def test_anchored_values_match_scalar_information_tree(self):
        law = BlockLaw.from_payload(Law().export())
        planner = AnchoredPlanner(law, .35, projection="block")
        p = unpack(pack(law.initial_prior(2))) @ law.transition(.73)

        def enumerate_tree(belief, remaining):
            values = {"STOP": float(np.max(belief @ law.transition(remaining * .35) @ law.reward))}
            if not remaining:
                return values
            values["WAIT"] = max(enumerate_tree(belief @ law.transition(.35), remaining - 1).values()) - .003 * .35
            for action, slots, emission, fee in (("READ", 1, law.E_read, .025), ("REFRESH", 2, law.E_refresh, .07)):
                if slots > remaining:
                    continue
                propagated = belief @ law.transition(slots * .35)
                gain = 0.
                for token in range(emission.shape[1]):
                    numerator = propagated * emission[:, token]
                    probability = float(numerator.sum())
                    if probability:
                        posterior = unpack(pack(numerator / probability))
                        gain += probability * max(enumerate_tree(posterior, remaining - slots).values())
                values[action] = gain - fee - .003 * .35 * slots
            return values

        for horizon in range(4):
            actual, expected = planner.values(p, horizon), enumerate_tree(p, horizon)
            self.assertEqual(actual.keys(), expected.keys())
            np.testing.assert_allclose(list(actual.values()), list(expected.values()), rtol=0, atol=2e-14)


if __name__ == "__main__":
    unittest.main()

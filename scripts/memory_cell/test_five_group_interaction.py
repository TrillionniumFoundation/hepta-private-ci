"""Prove the controller can change candidate order with state: fixtures only."""
from pathlib import Path
import tempfile
import unittest

import torch

import five_causal_experiments as c
import five_group_search as g


class StateCandidateInteractionTests(unittest.TestCase):
    def model(self):
        model = g.GroupValueCell(2, 2).eval()
        with torch.no_grad():
            model.project.weight.copy_(torch.eye(2))
            model.project.bias.zero_()
            model.proposal.weight.copy_(torch.tensor([[0., 0., 1., 1.]]))
            model.proposal.bias.zero_()
        return model

    def test_state_can_reverse_same_candidates_with_identical_weights(self):
        model = self.model()
        candidates = torch.eye(2)
        first = model.predict(candidates, torch.tensor([3., -3.]))
        second = model.predict(candidates, torch.tensor([-3., 3.]))
        self.assertEqual(int(first.argmax()), 0)
        self.assertEqual(int(second.argmax()), 1)
        self.assertGreater(float(first[0]), float(first[1]))
        self.assertGreater(float(second[1]), float(second[0]))

    def test_zero_state_preserves_unmodulated_candidate_scores(self):
        model = self.model()
        candidates = torch.eye(2)
        state = torch.zeros(2)
        plain = torch.sigmoid(model.proposal(torch.cat((state.expand(2, -1), torch.tanh(model.project(candidates))), -1))).flatten()
        self.assertTrue(torch.equal(model.predict(candidates, state), plain))

    def test_rank_difference_has_nonzero_state_gradient(self):
        model = self.model()
        state = torch.zeros(2, requires_grad=True)
        values = model.predict(torch.eye(2), state)
        (values[0] - values[1]).backward()
        self.assertGreater(float(state.grad[0]), 0)
        self.assertLess(float(state.grad[1]), 0)

    def test_no_added_parameters_and_explicit_new_architecture(self):
        model = g.GroupValueCell(384, 32)
        self.assertEqual(sum(p.numel() for p in model.parameters()), 18786)
        self.assertEqual(g.ARCHITECTURE, "state-candidate-interaction-v2")

    def test_old_unversioned_controller_cannot_be_loaded_as_new_semantics(self):
        bindings = {k: c.digest(k) for k in c.BINDINGS}
        bindings["action_menu"] = c.digest(g.MENU)
        bindings["preprocessor"] = c.digest(g.PREPROCESSOR)
        spec = {"schema": g.SCHEMA, "profile": g.PROFILE, "scope": "fixture", "purpose": "test",
                "generation": "one", "menu": g.MENU, "reader_checkpoint_sha256": "a"*64,
                "maximum_reader_calls": 2, "call_cost": 0.1, "confidence_threshold": 0.8,
                "bindings": bindings, "controller": {}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"bundles").mkdir()
            sha = c.digest(spec)
            (root/"bundles"/(sha+".json")).write_bytes(c.canonical(spec))
            with self.assertRaisesRegex(c.Invalid, "unregistered Group architecture"):
                g.NativeGroupOwner(root, sha)


if __name__ == "__main__":
    unittest.main()

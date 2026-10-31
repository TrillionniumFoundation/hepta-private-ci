"""Boundary, paired-label and durable-action tests, with no holdout access."""

from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from ...abc_recovery.runtime import PublicFrame, RunState, public_frame
from ...v6.data import Observation
from ...v7.model import State
from .features import DIM, from_frame
from .models import Bundle, Head, action_values, fit_pair, load, save
from . import rollout


def frame(remaining=2):
    latent = torch.arange(96).float()[None] / 96
    state = State(latent, latent + 1, latent + 2, latent + 3, 'private-checkpoint', 'private-source')
    pixels = torch.arange(1568).reshape(1, 1, 28, 56).remainder(2).float()
    tokens = torch.arange(8)[None]
    return PublicFrame(state, pixels, tokens, remaining)


class ControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_features_strip_owner_identity_and_reject_owner_port(self):
        view = frame()
        run = RunState(view.state, view.pixels, view.tokens, 2, torch.zeros(1), torch.zeros(1),
                       view.state.h, 'full', 'adaptive', 'persistent', ({'private_target': 'A'},))
        other = replace(run, state=replace(run.state, source_digest='different'), ledger=({'private_target': 'B'},))
        self.assertTrue(torch.equal(from_frame(public_frame(run)), from_frame(public_frame(other))))
        self.assertEqual(from_frame(public_frame(run)).shape, (1, DIM))
        self.assertLessEqual(DIM, 512)
        with self.assertRaises(TypeError):
            from_frame(run)
        with self.assertRaises(ValueError):
            from_frame(replace(view, pixels=torch.full_like(view.pixels, float('nan'))))
        with self.assertRaises(ValueError):
            from_frame(replace(view, pixels=torch.full_like(view.pixels, .5)))

    def test_child_actual_pixels_tokens_and_budget_affect_public_contract(self):
        view = frame()
        baseline = from_frame(view)
        pixels = from_frame(replace(view, pixels=1 - view.pixels))
        caption = from_frame(replace(view, tokens=torch.full_like(view.tokens, 9)))
        child = from_frame(replace(view, remaining=1))
        self.assertTrue(torch.equal(baseline[:, :384], pixels[:, :384]))
        self.assertFalse(torch.equal(baseline, pixels))
        self.assertFalse(torch.equal(baseline, caption))
        self.assertFalse(torch.equal(baseline, child))

    def test_cross_source_backup_uses_selected_child_not_future_best(self):
        public = torch.zeros(4, 5, DIM)
        public[:, :, 0] = torch.arange(4)[:, None]
        public[:, :, -1] = torch.tensor([1., .5, .5, .5, .5])
        utilities = torch.arange(84).float().reshape(4, 21) / 100
        calls = []
        class Fixed:
            def __call__(self, x):
                return torch.tensor([.1, .2, -.1, .3]).expand(len(x), -1)
        def fit(x, target, **kwargs):
            calls.append((x.clone(), target.clone()))
            return Fixed(), []
        with patch('experiments.multimodal_output_portfolio.closure_20261025.control.models.fit_head', side_effect=fit):
            fit_pair(public, utilities, torch.arange(4), 99)
        self.assertEqual(sorted(torch.unique(calls[0][0][:, 0]).tolist()), [1., 3.])
        self.assertEqual(sorted(torch.unique(calls[1][0][:, 0]).tolist()), [0., 2.])
        selected_paths = torch.tensor([7, 11, 15, 19])
        expected = torch.exp(-2 * (utilities[:, selected_paths] - .004)) - torch.exp(-2 * utilities[:, :1])
        self.assertTrue(torch.allclose(calls[2][1][-4:], expected))
        hindsight = torch.exp(-2 * (utilities[:, 5:].reshape(4, 4, 4).max(-1).values - .004)) - torch.exp(-2 * utilities[:, :1])
        self.assertFalse(torch.allclose(expected, hindsight))

    def test_dominated_action_fallback_and_nonfinite_checkpoint(self):
        bundle = Bundle(Head(4, 4, 1), Head(4, 5, 2), None)
        x = from_frame(frame(1))
        actor, pair, take, confidence, values = bundle.propose(x, 1)
        self.assertFalse(bool(take.any()))
        self.assertFalse(bool((actor == 1).any() or (pair == 1).any()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bundle.pt'
            save(bundle, path)
            restored = load(path)
            self.assertTrue(torch.equal(action_values(bundle.critic, x, 1), action_values(restored.critic, x, 1)))
            payload = torch.load(path, weights_only=True)
            payload['critic']['state']['mean'][0] = float('nan')
            torch.save(payload, path)
            with self.assertRaises(ValueError):
                load(path)

    def test_actual_commit_precedes_transition_and_terminal_readback(self):
        view = frame()
        run = RunState(view.state, view.pixels, view.tokens, 2, torch.zeros(1), torch.zeros(1),
                       view.state.h, 'full', 'adaptive', 'persistent', ())
        observation = Observation(view.pixels, torch.ones_like(view.pixels), view.tokens)
        class Old:
            def choose(self, features, remaining):
                return torch.zeros(1, dtype=torch.long)
        class Cache:
            def __init__(self, *args):
                pass
            def read(self, public):
                return torch.zeros(1, 763)
        with tempfile.TemporaryDirectory() as directory:
            media_path, commit_path = Path(directory) / 'media', Path(directory) / 'commit'
            with media_path.open('w+b') as media, commit_path.open('w') as commits:
                def transition(model, current, action, generator):
                    durable = json.loads(commit_path.read_text())
                    self.assertEqual(durable['action'], action)
                    self.assertEqual(durable['decision_index'], 0)
                    return replace(current, done=True)
                with patch.object(rollout, 'initialize', return_value=run), patch.object(rollout, 'transition', side_effect=transition), patch.object(rollout, 'ExactFeatureCache', Cache):
                    row, drafts = rollout.request(None, observation, old=Old(), bundle=None, sensor=None,
                        policy='cached_teacher', seed=17, case=0, view='clean', draw=0, media=media, commitments=commits,
                        evaluation={'initial_namespace': 'unit-initial', 'future_namespace': 'unit-future'})
                self.assertEqual(row['status'], 'completed')
                self.assertEqual(drafts, [])
            pixels, tokens, _ = rollout.decode(media_path.read_bytes())
            self.assertTrue(torch.equal(pixels, view.pixels))
            self.assertTrue(torch.equal(tokens, view.tokens))


if __name__ == '__main__':
    unittest.main()

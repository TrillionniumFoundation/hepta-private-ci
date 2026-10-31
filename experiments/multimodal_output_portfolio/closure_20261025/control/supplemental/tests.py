"""Committed plans ignore later features while actual reads remain costed."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from ....abc_recovery.control import PLANS
from ....abc_recovery.runtime import RunState
from ....v6.data import Observation
from ..control_tests import frame
from . import run as runner


class SupplementalTests(unittest.TestCase):
    def test_root_plan_is_committed_while_child_is_really_read(self):
        torch.set_num_threads(1)
        view = frame()
        initial = RunState(view.state, view.pixels, view.tokens, 2, torch.zeros(1), torch.zeros(1),
                           view.state.h, 'full', 'adaptive', 'persistent', ())
        observation = Observation(view.pixels, torch.ones_like(view.pixels), view.tokens)
        for policy in ('strong_nonfeedback', 'fixed_allocation'):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                reads, plans = [], []
                class Cache:
                    def __init__(self, *args):
                        pass
                    def read(self, public):
                        reads.append(public.remaining)
                        return torch.full((1, 763), 1. if public.remaining == 2 else -999.)
                class Old:
                    def choose_plan(self, feature):
                        plans.append(feature.clone())
                        return torch.tensor([12])
                commit_path = Path(directory) / 'commit'
                with (Path(directory) / 'media').open('w+b') as media, commit_path.open('w') as commits:
                    def transition(model, current, action, generator):
                        entries = list(map(json.loads, commit_path.read_text().splitlines()))
                        self.assertEqual(entries[-1]['action'], action)
                        return replace(current, remaining=current.remaining - 1, done=current.remaining == 1)
                    with patch.object(runner, 'initialize', return_value=initial), patch.object(runner, 'transition', side_effect=transition), patch.object(runner, 'ExactFeatureCache', Cache):
                        row = runner.request(None, observation, Old(), None, policy=policy,
                            reference={'selected_nonfeedback': 'one_shot', 'static_plan_index': 0}, seed=17, case=0,
                            view='clean', draw=0, evaluation={'initial_namespace': 'test-i', 'future_namespace': 'test-f'},
                            media=media, commitments=commits)
                self.assertEqual(row['status'], 'completed')
                self.assertEqual(reads, [2, 1])
                self.assertEqual(row['path'], list(PLANS[12]) if policy == 'strong_nonfeedback' else ['refine_image', 'refine_text'])
                self.assertEqual(len(plans), int(policy == 'strong_nonfeedback'))
                if plans:
                    self.assertTrue(torch.equal(plans[0], torch.ones(1, 763)))


if __name__ == '__main__':
    unittest.main()

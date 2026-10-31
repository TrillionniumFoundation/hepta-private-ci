"""Synthetic causal-order and private-target-isolation integration checks."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

from ..abc_recovery.runtime import ACTIONS, transition
from ..abc_recovery.runtime_tests import observation_fixture
from ..abc_recovery.trees import METRICS
from ..v6.data import Target
from ..v7.model import SlotPortfolio
from .execute import execute_view


class NewPolicy:
    mode = "base"

    def choose_plan(self, values):
        return torch.tensor([0, 8])

    def choose(self, values, remaining):
        return torch.tensor([1, 2]) if remaining == 2 else torch.full((len(values),), 4)


class OldPolicy:
    def choose(self, values, remaining):
        return torch.full((len(values),), 4 if remaining == 2 else 0)


class ExecutionTests(unittest.TestCase):
    def test_real_branch_commits_before_draws_and_never_uses_private_target(self):
        torch.set_num_threads(2)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(211)
            model = SlotPortfolio().eval().requires_grad_(False)
        observation = observation_fixture(2)
        batch = SimpleNamespace(source_ids=(("synthetic-a", "synthetic-b"), ("synthetic-c", "synthetic-d")))
        snapshots = []
        with tempfile.TemporaryDirectory() as temporary:
            for truth in (0, 9):
                destination = Path(temporary) / str(truth)
                target = Target(torch.full_like(observation.pixels, truth / 9),
                                torch.full((2, 8), truth, dtype=torch.long), torch.full((2, 2), truth))
                transitions, scored = [], []

                def committed_step(actual_model, parent, action, *, generator):
                    self.assertFalse(scored, "Private outcomes were scored before all decisions finished")
                    root = json.loads((destination / "root-decisions.json").read_text())
                    self.assertFalse(root["future_draws_started"])
                    if parent.remaining == 1:
                        first = ACTIONS.index(parent.ledger[-1]["action"])
                        receipt = json.loads((destination / f"child-{first}-decisions.json").read_text())
                        self.assertFalse(receipt["grandchild_draws_started"])
                    transitions.append(action)
                    return transition(actual_model, parent, action, generator=generator)

                def offline_score(judges, pixels, captions, private):
                    self.assertTrue((destination / "selected-media.npz").is_file())
                    self.assertEqual(private, target)
                    scored.append(len(pixels))
                    return {"primary": {key: torch.full((len(pixels),), float(truth)) for key in METRICS}}

                with patch("experiments.multimodal_output_portfolio.abc_next.execute.paired_batch", return_value=(batch, observation, target)), \
                     patch("experiments.multimodal_output_portfolio.abc_next.execute.transition", side_effect=committed_step), \
                     patch("experiments.multimodal_output_portfolio.abc_next.execute.input_evidence", side_effect=AssertionError("base policy must not run public sensor")), \
                     patch("experiments.multimodal_output_portfolio.abc_next.execute.scores", side_effect=offline_score):
                    paths, _, _, summary = execute_view(SimpleNamespace(_model=model), NewPolicy(), OldPolicy(), None,
                        None, {"primary": None}, destination, role="synthetic-only", start=0, count=2,
                        scenarios=1, training_seed=17, view="clean", static_index=0)
                self.assertGreater(len(transitions), 0)
                self.assertEqual(scored, [2] * 5)
                self.assertEqual(summary["selected_policy_rows"], 10)
                np.testing.assert_array_equal(paths.numpy(), [[11, 0, 0, 8, 4], [11, 0, 8, 12, 4]])
                with np.load(destination / "selected-media.npz", allow_pickle=False) as saved:
                    snapshots.append((saved["pixels_bits"].copy(), saved["tokens"].copy(), saved["output_sha256"].copy()))
            for actual, alternate in zip(*snapshots):
                np.testing.assert_array_equal(actual, alternate)


if __name__ == "__main__":
    unittest.main()

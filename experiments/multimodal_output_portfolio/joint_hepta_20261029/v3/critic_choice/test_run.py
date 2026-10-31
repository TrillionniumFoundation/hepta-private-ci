"""Actual first-choice interventions, target isolation and planning cost tests."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import torch

from ...mechanism_data import batch
from ...media import utility
from ...model import tensor_digest
from ..model import JointGenerator
from ..profile import make_profile
from ..runtime import start_snapshot
from .run import ARMS, choose_first, content_actor_hash, evaluate_draw


class CriticChoiceTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(61)
        self.original = JointGenerator(width=8, mode="ordinary").eval()
        self.calibrated = deepcopy(self.original)
        with torch.no_grad():
            for model in (self.original, self.calibrated):
                for parameter in model.critic.parameters():
                    parameter.zero_()
                for parameter in model.delivery_critic.parameters():
                    parameter.zero_()
            self.original.delivery_critic[-1].bias.fill_(2.)
            self.calibrated.delivery_critic[-1].bias.fill_(-2.)
        self.public, self.target = batch([1], "critic-choice-test-only")
        self.profile = make_profile()
        with torch.no_grad():
            self.snapshot = start_snapshot(self.original, self.public, seed=51, profile=self.profile)

    def test_value_heads_change_first_choice_without_content_or_actor_change(self):
        before = tensor_digest(self.snapshot.state.tensors())
        a, _ = choose_first(self.original, self.snapshot, self.public, self.profile)
        b, _ = choose_first(self.calibrated, self.snapshot, self.public, self.profile)
        self.assertEqual(a, "image")
        self.assertEqual(b, "stop")
        self.assertEqual(content_actor_hash(self.original), content_actor_hash(self.calibrated))
        self.assertEqual(tensor_digest(self.snapshot.state.tensors()), before)

    def test_actual_calibrated_stop_preserves_emission_but_pays_for_all_planning(self):
        with tempfile.TemporaryDirectory() as temporary:
            rows = evaluate_draw(self.original, self.calibrated, self.public,
                lambda readback: utility(readback, self.target).item(), self.snapshot, Path(temporary) / "draw",
                source_id="critic-consumer-test", draw=0, seed=31, profile=self.profile)
            by_arm = {row["arm"]: row for row in rows}
            self.assertEqual(set(by_arm), set(ARMS))
            calibrated, stop = by_arm["calibrated_critic_first"], by_arm["stop"]
            self.assertEqual(calibrated["selected_first_action"], "stop")
            self.assertEqual(calibrated["readback"]["readback_sha256"], stop["readback"]["readback_sha256"])
            self.assertGreater(calibrated["planning_cost"], 0.)
            self.assertGreater(calibrated["actual_cost"], stop["actual_cost"])
            self.assertEqual(len({r["common_prefix_snapshot_sha256"] for r in rows}), 1)
            self.assertEqual(len({r["common_future_randomness_sha256"] for r in rows}), 1)
            for row in rows:
                self.assertIsNone(row["failure"])
                self.assertAlmostEqual(row["actual_cost"], sum(e["amount"] for e in row["events"]), places=12)
                self.assertAlmostEqual(row["net_return"], row["utility"]-row["actual_cost"], places=12)


if __name__ == "__main__":
    unittest.main()

"""Compare actual credit gradients against a separately assembled dense loss."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import torch
import current_credit as credit
from cell_experiments.test_matched_info_sft_v4 import ToyDecoder


class CreditTests(unittest.TestCase):
    def test_verified_earlier_action_and_correction_share_credit_without_changing_work(self):
        turns = [
            {"input_ids": [0, 1, 2], "labels": [-100, 1, 2], "target_verified": True},
            {"input_ids": [0, 3, 4], "labels": [-100, 3, 4], "target_verified": False},
            {"input_ids": [0, 2, 4], "labels": [-100, 2, 4], "target_verified": True},
        ]
        original, traces, measured = copy.deepcopy(turns), {}, {}
        for mode in credit.MODES:
            actual, expected = ToyDecoder(), ToyDecoder()
            measured[mode] = credit.backward_group(torch, actual, turns, mode, 0, 8, "cpu")
            selected = range(3) if mode == "all_observed" else (0, 2)
            objectives = [torch.nn.functional.cross_entropy(
                expected.weight[torch.tensor(turns[i]["input_ids"][:-1])].float(),
                torch.tensor(turns[i]["labels"][1:])) for i in selected]
            loss = sum(objectives) / len(objectives)
            loss.backward()
            torch.testing.assert_close(actual.weight.grad, expected.weight.grad, rtol=1e-7, atol=1e-9)
            self.assertAlmostEqual(measured[mode]["loss"], float(loss.detach()), places=6)
            self.assertEqual(actual.backwards, 3)
            traces[mode] = actual.calls
        self.assertEqual(turns, original)
        self.assertEqual(traces["all_observed"], traces["verified_credit"])
        for key in ("model_forwards", "model_backwards", "head_positions", "input_tokens", "padded_positions"):
            self.assertEqual(measured["all_observed"][key], measured["verified_credit"][key])
        self.assertEqual(measured["all_observed"]["supervised_positions"], 6)
        self.assertEqual(measured["verified_credit"]["supervised_positions"], 4)

    def test_unverified_only_cannot_silently_make_zero_update(self):
        model = ToyDecoder()
        with self.assertRaisesRegex(ValueError, "nonempty objective"):
            credit.backward_group(torch, model, [{"input_ids": [0, 1], "labels": [-100, 1],
                "target_verified": False}], "verified_credit", 0, 8, "cpu")
        self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()

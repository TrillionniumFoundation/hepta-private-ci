"""Compare matched gradients with independently assembled dense CE objectives."""

import copy
from types import SimpleNamespace
import unittest

import torch

from . import matched_info_sft_v4 as matched


class ToyDecoder(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(
            torch.arange(25, dtype=torch.float64).reshape(5, 5) / 20
        )
        self.calls, self.backwards = [], 0
        self.weight.register_hook(self.count_backward)

    def count_backward(self, gradient):
        self.backwards += 1
        return gradient

    def forward(self, input_ids, attention_mask, use_cache, logits_to_keep):
        self.calls.append(
            (input_ids.tolist(), attention_mask.tolist(), logits_to_keep.tolist())
        )
        return SimpleNamespace(logits=self.weight[input_ids[:, logits_to_keep]])


class MatchedInformationTests(unittest.TestCase):
    def test_identical_forward_backward_shapes_and_exact_treatment_gradient(self):
        turns = [
            {"input_ids": [0, 1, 2], "labels": [-100, 1, 2], "final_target": False},
            {
                "input_ids": [0, 3, 4, 2],
                "labels": [-100, -100, 4, 2],
                "final_target": True,
            },
        ]
        untouched, results, traces = copy.deepcopy(turns), {}, {}
        for mode in ("final_only", "all_actions"):
            model = ToyDecoder()
            measured = matched.backward_group(torch, model, turns, mode, 0, 8, "cpu")
            expected = ToyDecoder()
            logits = [
                expected.weight[torch.tensor([0, 1])],
                expected.weight[torch.tensor([3, 4])],
            ]
            losses = [
                torch.nn.functional.cross_entropy(
                    logits[0].float(), torch.tensor([1, 2])
                ),
                torch.nn.functional.cross_entropy(
                    logits[1].float(), torch.tensor([4, 2])
                ),
            ]
            objective = (
                losses[1] if mode == "final_only" else (losses[0] + losses[1]) / 2
            )
            objective.backward()
            torch.testing.assert_close(
                model.weight.grad, expected.weight.grad, rtol=1e-7, atol=1e-9
            )
            self.assertAlmostEqual(
                measured["loss"], float(objective.detach()), places=6
            )
            self.assertEqual(model.backwards, 2)
            results[mode], traces[mode] = measured, model.calls
        self.assertEqual(traces["final_only"], traces["all_actions"])
        self.assertEqual(
            {
                key: results["final_only"][key]
                for key in (
                    "head_positions",
                    "model_forwards",
                    "model_backwards",
                    "input_tokens",
                    "padded_positions",
                )
            },
            {
                key: results["all_actions"][key]
                for key in (
                    "head_positions",
                    "model_forwards",
                    "model_backwards",
                    "input_tokens",
                    "padded_positions",
                )
            },
        )
        self.assertNotEqual(
            results["final_only"]["supervised_positions"],
            results["all_actions"]["supervised_positions"],
        )
        self.assertEqual(turns, untouched)

    def test_missing_final_target_cannot_be_a_silent_zero_update(self):
        model = ToyDecoder()
        turns = [{"input_ids": [0, 1], "labels": [-100, 1], "final_target": False}]
        with self.assertRaisesRegex(ValueError, "nonempty objective"):
            matched.backward_group(torch, model, turns, "final_only", 0, 4, "cpu")
        self.assertIsNone(model.weight.grad)
        self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()

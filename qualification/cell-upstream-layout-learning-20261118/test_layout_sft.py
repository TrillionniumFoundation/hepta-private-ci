"""Numerically test target partitioning with the actual inherited loss and backward functions."""

import copy
import importlib
from types import SimpleNamespace
import unittest

import layout_context as ctx
import torch

layout = importlib.import_module("layout_sft")


class CausalNumericalFixture(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = torch.nn.Embedding(17, 7, dtype=torch.float64)
        self.head = torch.nn.Linear(7, 17, bias=False, dtype=torch.float64)

    def forward(self, input_ids, attention_mask, use_cache, logits_to_keep):
        self.assertions = (use_cache is False, input_ids.shape == attention_mask.shape)
        hidden = (self.embedding(input_ids) * attention_mask.unsqueeze(-1)).cumsum(1)
        return SimpleNamespace(logits=self.head(hidden[:, logits_to_keep]))


class PartitionNumerics(unittest.TestCase):
    def test_exact_target_partition_and_gradient_equivalence(self):
        torch.manual_seed(1729)
        torch.set_num_threads(2)
        dense = CausalNumericalFixture()
        split = copy.deepcopy(dense)
        ids = [1, 2, 3, 5, 7, 8, 4, 3, 11, 12, 10, 13, 15, 4, 8, 9]
        labels = [-100] * 5 + ids[5:]
        labels[9] = -100
        turn = {
            "input_ids": ids,
            "labels": labels,
            "prefix_tokens": 5,
            "final_target": True,
        }
        parts = layout.partition_target(turn, 3)
        positive = [(i, value) for i, value in enumerate(labels) if value != -100]
        self.assertEqual(
            [
                (i, value)
                for part in parts
                for i, value in enumerate(part["labels"])
                if value != -100
            ],
            positive,
        )
        self.assertTrue(all(part["input_ids"] == ids for part in parts))
        padded = 20
        input_ids = torch.tensor([ids + [0] * (padded - len(ids))])
        mask = torch.tensor([[1] * len(ids) + [0] * (padded - len(ids))])
        full_labels = torch.tensor([labels + [-100] * (padded - len(ids))])
        loss, count = layout.numeric.selected_token_loss(
            dense, input_ids, mask, full_labels
        )
        loss.backward()
        measured = layout.backward_group(
            torch, split, parts, "native_feedback", 0, padded, "cpu"
        )
        self.assertEqual(count, measured["supervised_positions"])
        self.assertEqual(
            (len(parts), len(parts), count, padded * len(parts)),
            tuple(
                measured[key]
                for key in (
                    "model_forwards",
                    "model_backwards",
                    "head_positions",
                    "padded_positions",
                )
            ),
        )
        self.assertAlmostEqual(float(loss), measured["loss"], places=6)
        differences = []
        for (name, parameter), (other_name, other) in zip(
            dense.named_parameters(), split.named_parameters()
        ):
            self.assertEqual(name, other_name)
            torch.testing.assert_close(parameter.grad, other.grad, rtol=2e-6, atol=2e-7)
            differences.append(float((parameter.grad - other.grad).abs().max()))
        print(
            ctx.data.canonical(
                {
                    "actual_torch_version": torch.__version__,
                    "fixture": "CPU float64 causal parameters; inherited loss deliberately casts logits to float32",
                    "dense_loss": float(loss),
                    "partitioned_loss": measured["loss"],
                    "max_absolute_gradient_difference": max(differences),
                    "target_positions": count,
                    "full_sequence_forwards": len(parts),
                    "model_generation_calls": 0,
                    "research_optimizer_updates": 0,
                }
            ).decode(),
            flush=True,
        )

    def test_rejects_empty_or_noncausal_target(self):
        for labels in ([-100, -100], [1, -100]):
            with self.assertRaises(ValueError):
                layout.partition_target({"input_ids": [1, 2], "labels": labels})

    def test_evidence_fields_are_identical_and_unverified_actions_untrained(self):
        record = {
            "task": {"input": "original task"},
            "observed_answer": "actual failed answer",
            "observed_feedback": "actual verifier failure",
            "final_answer": "verified maintainer target",
        }
        identity = layout.information(record)
        document = layout.evidence_messages(record, "document_evidence")
        native = layout.evidence_messages(record, "native_feedback")
        self.assertEqual(
            [message["content"] for message in native],
            [
                record["task"]["input"],
                record["observed_answer"],
                record["observed_feedback"],
            ],
        )
        self.assertTrue(
            all(
                value in document[0]["content"]
                for value in (
                    record["task"]["input"],
                    record["observed_answer"],
                    record["observed_feedback"],
                )
            )
        )
        changed = copy.deepcopy(record)
        changed["observed_feedback"] = "different feedback"
        self.assertNotEqual(identity, layout.information(changed))
        self.assertNotIn(record["final_answer"], document[0]["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

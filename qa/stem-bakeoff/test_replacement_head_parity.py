"""Toy source/torch fixtures do NOT demonstrate original checkpoint execution."""
import unittest
from types import SimpleNamespace
import torch
from replacement_head_parity import (frozen_encode_rows, project_untrained,
                                     train_and_replay, HEAD_PARAMETERS)


def _rows():
    return {split: [{"source_id": f"{split}-{i}", "source_group_id": f"{split}-{i}",
                    "label": i % 4, "text": "business news sample"}
                   for i in range(8)] for split in
            ("train", "calibration", "future_1", "future_2", "ood")}


class FakeEncoder(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.emb = torch.nn.Embedding(10, 640)
        self.calls = 0
    def forward(self, input_ids, attention_mask):
        self.calls += 1
        return SimpleNamespace(last_hidden_state=self.emb(input_ids))


def tokenizer(text, **kwargs):
    return {"input_ids": torch.tensor([[1, 2, 3, 4]], dtype=torch.long),
            "attention_mask": torch.tensor([[1, 1, 1, 0]], dtype=torch.long)}


def train_fn(x, y, c, cy):
    torch.manual_seed(7)
    m = torch.nn.Linear(256, 4)
    optimizer = torch.optim.AdamW(m.parameters(), lr=0.05, weight_decay=0.0)
    for _ in range(200):
        optimizer.zero_grad()
        torch.nn.functional.cross_entropy(m(x), y).backward()
        optimizer.step()
    m.eval()
    return m, 1.0, {"seed": 7, "optimizer": "AdamW", "steps": 200,
                    "learning_rate": 0.05, "head_parameters": 1028}


def score_fn(rows):
    return {"count": len(rows), "predicted_sum": sum(sum(r["probabilities"]) for r in rows)}


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def test_real_encoder_calls_and_fixed_head_budget(self):
        model = FakeEncoder().eval().requires_grad_(False)
        rows = _rows()
        x, calls = frozen_encode_rows(model, tokenizer, rows, pooling="last_nonpad")
        self.assertEqual(calls, 40)
        self.assertEqual(model.calls, 40)
        self.assertEqual(x["future_1"].shape, (8, 640))
        d1, digest, width = project_untrained(x)
        d2, digest2, _ = project_untrained(x)
        self.assertEqual(digest, digest2)
        self.assertTrue(torch.equal(d1["train"], d2["train"]))
        self.assertEqual(width, 640)
        report, artifact = train_and_replay(x, rows, train_fn=train_fn, score_fn=score_fn)
        self.assertEqual(report["trained_head_parameter_count"], HEAD_PARAMETERS)
        self.assertEqual(report["output_width"], 256)
        self.assertTrue(report["head_reloaded_identical_logits"])
        self.assertEqual(len(artifact), report["head_artifact_bytes"])
        self.assertEqual(report["authority"], "DENY_ALL")
        self.assertFalse(report["production_activation_allowed"])

    def test_training_cannot_use_mislabeled_or_missing_cohort(self):
        rows = _rows()
        x = {key: torch.randn(8, 640) for key in rows}
        del x["future_2"]
        with self.assertRaisesRegex(ValueError, "all five"):
            train_and_replay(x, rows, train_fn=train_fn, score_fn=score_fn)
        x["future_2"] = torch.randn(8, 640)
        rows["train"][0]["label"] = 99
        with self.assertRaisesRegex(ValueError, "source class"):
            train_and_replay(x, rows, train_fn=train_fn, score_fn=score_fn)

    def test_frozen_state_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, "frozen"):
            frozen_encode_rows(FakeEncoder(), tokenizer, _rows(), pooling="cls")

    def test_projection_rejects_nan_and_different_widths(self):
        with self.assertRaises(ValueError):
            project_untrained({"train": torch.ones((2, 640)),
                               "test": torch.ones((2, 768))})
        with self.assertRaises(ValueError):
            project_untrained({"train": torch.full((2, 640), float('nan'))})

    def test_bad_trained_head_size_rejected(self):
        rows = _rows()
        x = {key: torch.randn(8, 640) for key in rows}
        def wrong(*args):
            m = torch.nn.Linear(256, 4)
            return m, 1.0, {"seed": 7, "optimizer": "AdamW", "steps": 199,
                            "learning_rate": .05, "head_parameters": 1028}
        with self.assertRaisesRegex(ValueError, "Head budget"):
            train_and_replay(x, rows, train_fn=wrong, score_fn=score_fn)


if __name__ == "__main__":
    unittest.main()

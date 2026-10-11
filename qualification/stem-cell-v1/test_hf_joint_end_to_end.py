"""Small but REAL PyTorch training smoke against a synthetic HF model fixture.

The tiny fake Encoder never represents a real DeBERTa/ModernBERT checkpoint;
the work here validates the entire native-Python research execution path
while refusing downloads, fake zero-shot predictions or production authority.
"""
import hashlib
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest

from decision_421m import input_fingerprint
from hf_joint_decision_runner import run
from model_runner import snapshot_digest


@contextmanager
def scoped_fake_transformers(module):
    """Restore only one import slot, not every Torch submodule imported in test."""
    missing = object()
    previous = sys.modules.get("transformers", missing)
    sys.modules["transformers"] = module
    try:
        yield
    finally:
        if previous is missing:
            sys.modules.pop("transformers", None)
        else:
            sys.modules["transformers"] = previous


@unittest.skipUnless(importlib.util.find_spec("torch") is not None,
                     "optional CPU PyTorch is not installed")
class FullPipelineModelFreeTests(unittest.TestCase):
    def test_complete_local_forward_head_training_prediction_and_receipt(self):
        import torch

        class FakeParameterCount:
            def numel(self):
                # Metadata fixture only; no 435M parameter tensor is allocated.
                return 435_000_000

            def requires_grad_(self, enabled):
                return self

        class FakeTokenizer:
            def __call__(self, text, return_tensors, truncation):
                values = [ord(char) % 64 for char in text][:48]
                ids = torch.tensor([values], dtype=torch.long)
                return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}

        class FakeEncoder:
            config = SimpleNamespace(hidden_size=16, max_position_embeddings=512)

            def to(self, device):
                return self

            def eval(self):
                return self

            def parameters(self):
                return (FakeParameterCount(),)

            def __call__(self, **inputs):
                values = inputs["input_ids"].float().unsqueeze(-1)
                states = torch.cat(
                    [values / (index + 1) for index in range(16)], dim=-1)
                return SimpleNamespace(last_hidden_state=states)

        fake_hf = ModuleType("transformers")
        fake_hf.__version__ = "synthetic-fixture-only"
        fake_hf.AutoTokenizer = SimpleNamespace(
            from_pretrained=lambda *a, **kw: FakeTokenizer())
        fake_hf.AutoModel = SimpleNamespace(
            from_pretrained=lambda *a, **kw: FakeEncoder())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "checkpoint"
            model.mkdir()
            (model / "config.json").write_text('{"fixture_only": true}')
            data = root / "dataset.jsonl"
            rows = []
            for day, split in enumerate((
                    "train", "calibration", "held_out",
                    "future_1", "future_2", "ood"), 1):
                for i in range(4):
                    case = f"{split}-{i}"
                    rows.append({
                        "sample_id": case, "source_group": case,
                        "episode_id": case, "split": split, "language": "en",
                        "label": i % 2, "scope": "authorized-test-scope",
                        "state": "state " + case, "question": "choose next step",
                        "options": ["stay", "go"],
                        "event_time": f"2026-01-0{day}T12:00:00Z",
                    })
            data.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8")
            output = root / "predictions.jsonl"
            args = SimpleNamespace(
                model_key="deberta_v3_large",
                upstream_revision="a" * 40,
                expected_snapshot_sha256=snapshot_digest(model),
                expected_dataset_sha256=hashlib.sha256(data.read_bytes()).hexdigest(),
                license_approved=True, adapter_reviewed=True,
                train_steps=4, trainable_budget=262144,
                batch_size=4, context_tokens=512, seed=7347,
                device="cpu", dtype="fp32",
                snapshot=str(model), dataset=str(data), output=str(output))
            with scoped_fake_transformers(fake_hf):
                receipt = run(args)
            predictions = [
                json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(len(predictions), 20)
            self.assertEqual(receipt["scored_count"], 20)
            self.assertTrue(0 < receipt["trainable_parameters"] <= 262144)
            self.assertEqual(receipt["train_steps"], 4)
            self.assertEqual(receipt["truncated_input_count"], 0)
            self.assertFalse(receipt["checkpoint_zero_shot_score_emitted"])
            self.assertFalse(receipt["production_promotion_permitted"])
            self.assertEqual(receipt["model_source"], "microsoft/deberta-v3-large")
            self.assertEqual(receipt["output_predictions_sha256"],
                             hashlib.sha256(output.read_bytes()).hexdigest())
            source_by_id = {row["sample_id"]: row for row in rows}
            self.assertTrue(all(
                output_row["input_digest"] == input_fingerprint(
                    source_by_id[output_row["sample_id"]])
                for output_row in predictions))
            self.assertTrue(all(
                len(row["logits"]) == 2 and
                row["arm"] == "deberta_v3_large:equal_budget" and
                "label" not in row and "external_ndu_utility" not in row
                for row in predictions))
            with scoped_fake_transformers(fake_hf):
                with self.assertRaises(FileExistsError):
                    run(args)


if __name__ == "__main__":
    unittest.main()

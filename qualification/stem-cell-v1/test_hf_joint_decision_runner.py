"""No-model HF Decision Head contract tests; never counted as real weights."""
import copy
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

from hf_joint_decision_runner import (
    HF_KEYS, build_head, head_sha256, head_width, render_joint,
    snapshot_validation, train_head, validate_encoder_loading_info,
    vectorize_case, vectorize_scope_batch, verify_loaded_safetensors,
)


class DecisionHeadContractTests(unittest.TestCase):
    def test_full_ordered_input_contains_every_option_but_not_gold_label(self):
        row = {"state": "state", "question": "what next",
               "options": ["go", "stay"], "label": 999}
        rendered = render_joint(row)
        self.assertIn("Option 0: go", rendered)
        self.assertIn("Option 1: stay", rendered)
        self.assertNotIn("999", rendered)
        self.assertLess(rendered.index("go"), rendered.index("stay"))
        invalid = dict(row)
        invalid["options"] = ["go", ""]
        with self.assertRaisesRegex(ValueError, "empty legal"):
            render_joint(invalid)

    def test_physical_parameters_fit_and_unsupported_model_rejected(self):
        self.assertEqual(HF_KEYS, {"deberta_v3_large", "modernbert_large"})
        width, count = head_width(1024, 2, 262144)
        self.assertEqual(count, width * (1024 + 2 + 1) + 2)
        self.assertLessEqual(count, 262144)
        self.assertGreater(count, 260000)
        with self.assertRaisesRegex(ValueError, "budget"):
            head_width(1024, 3, 3)

    def test_weights_file_cannot_mask_randomized_or_ignored_layers(self):
        valid = {
            "missing_keys": [], "unexpected_keys": [],
            "mismatched_keys": [], "error_msgs": [],
        }
        result = validate_encoder_loading_info(valid)
        self.assertTrue(result["complete"])
        self.assertEqual(result["missing_keys"], 0)
        for kind in valid:
            invalid = {key: list(value) for key, value in valid.items()}
            invalid[kind] = ["layer.example"]
            with self.assertRaisesRegex(ValueError, "partially initialized"):
                validate_encoder_loading_info(invalid)
        with self.assertRaisesRegex(ValueError, "complete loading report"):
            validate_encoder_loading_info({"missing_keys": []})
        with self.assertRaisesRegex(ValueError, "invalid field"):
            validate_encoder_loading_info({
                **valid, "missing_keys": "not-an-array"})

    def test_unapproved_model_revision_denied_before_model_load(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root / "weights"
            snapshot.mkdir()
            (snapshot / "config.json").write_text("{}")
            dataset = root / "dataset"
            dataset.write_text("{}")
            dataset_sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
            args = SimpleNamespace(
                model_key="wrong", upstream_revision="a" * 40,
                expected_snapshot_sha256="b" * 64,
                expected_dataset_sha256=dataset_sha,
                license_approved=True, adapter_reviewed=True,
                dtype="fp32", train_steps=100, batch_size=16,
                context_tokens=512, trainable_budget=262144,
                seed=7347, snapshot=str(snapshot),
                dataset=str(dataset), output=str(root / "out"),
            )
            with self.assertRaisesRegex(ValueError, "only DeBERTa"):
                snapshot_validation(args)
            args.model_key = "deberta_v3_large"
            args.license_approved = False
            with self.assertRaisesRegex(ValueError, "license"):
                snapshot_validation(args)
            args.license_approved = True
            args.upstream_revision = "unversioned-main"
            with self.assertRaisesRegex(ValueError, "pinned"):
                snapshot_validation(args)
            args.upstream_revision = "a" * 40
            from model_runner import snapshot_digest
            args.expected_snapshot_sha256 = snapshot_digest(snapshot)
            with self.assertRaisesRegex(ValueError, "reviewed local safetensors"):
                snapshot_validation(args)


@unittest.skipUnless(importlib.util.find_spec("torch") is not None,
                     "optional CPU PyTorch is not installed")
class TorchHeadEvidenceTests(unittest.TestCase):
    def test_padding_mask_is_respected_and_no_silent_truncation(self):
        import torch

        class Tokenizer:
            def __call__(self, text, return_tensors, truncation):
                return {"input_ids": torch.tensor([[0, 3, 4]]),
                        "attention_mask": torch.tensor([[0, 1, 1]])}

        class Model:
            def __call__(self, **_kwargs):
                return SimpleNamespace(last_hidden_state=torch.tensor(
                    [[[999., 999.], [2., 4.], [4., 6.]]]))

        row = {"state": "state", "question": "question",
               "options": ["x", "y"]}
        value, n_tokens = vectorize_case(
            torch, Model(), Tokenizer(), row, "cpu", max_tokens=2)
        self.assertEqual(n_tokens, 2)
        self.assertEqual(value.tolist(), [3., 5.])
        with self.assertRaisesRegex(ValueError, "no silent truncation"):
            vectorize_case(torch, Model(), Tokenizer(), row, "cpu", max_tokens=1)

    def test_physical_scope_batch_matches_single_frozen_encoder_for_padding(self):
        import torch

        class Tokenizer:
            def __call__(self, text, return_tensors, truncation):
                ids = [1 + ord(c) % 31 for c in text]
                ids = ids[:80]
                tensor = torch.tensor([ids], dtype=torch.long)
                return {"input_ids": tensor, "attention_mask": torch.ones_like(tensor)}

            def pad(self, records, padding, return_tensors):
                width = max(len(record["input_ids"]) for record in records)
                ids = torch.zeros((len(records), width), dtype=torch.long)
                mask = torch.zeros_like(ids)
                for index, record in enumerate(records):
                    length = len(record["input_ids"])
                    ids[index, :length] = torch.tensor(record["input_ids"])
                    mask[index, :length] = 1
                return {"input_ids": ids, "attention_mask": mask}

        class Encoder:
            calls = 0

            def __call__(self, **inputs):
                self.calls += 1
                v = inputs["input_ids"].float()
                return SimpleNamespace(last_hidden_state=torch.stack(
                    [v, v * 0.5], dim=-1))

        tok = Tokenizer()
        batch_model = Encoder()
        a = {"scope": "alpha", "state": "s", "question": "q",
             "options": ["left", "right"]}
        b = {"scope": "alpha", "state": "a much longer state", "question": "q",
             "options": ["left", "right"]}
        results = vectorize_scope_batch(
            torch, batch_model, tok, [a, b], "cpu", max_tokens=512)
        self.assertEqual(batch_model.calls, 1)
        single_model = Encoder()
        for row, (feature, count) in zip((a, b), results):
            expected, expected_count = vectorize_case(
                torch, single_model, tok, row, "cpu", max_tokens=512)
            self.assertEqual(count, expected_count)
            self.assertTrue(torch.allclose(feature, expected))
        self.assertEqual(single_model.calls, 2)
        with self.assertRaisesRegex(ValueError, "cross-Scope"):
            vectorize_scope_batch(
                torch, Encoder(), tok, [a, {**b, "scope": "beta"}],
                "cpu", max_tokens=512)
        with self.assertRaisesRegex(ValueError, "silently truncate"):
            vectorize_scope_batch(
                torch, Encoder(), tok, [a, b], "cpu", max_tokens=4)
        with self.assertRaisesRegex(ValueError, "2..32"):
            vectorize_scope_batch(torch, Encoder(), tok, [a], "cpu", max_tokens=512)

    def test_actual_head_update_changes_weights_within_exact_budget(self):
        import torch
        torch.manual_seed(1234)
        head, params = build_head(torch, 16, 2, 2048)
        initial = head_sha256(head)
        features = torch.randn(10, 16)
        labels = torch.randint(0, 2, (10,))
        learned = train_head(
            torch, head, features, labels,
            batch_size=4, steps=5, seed=7347)
        self.assertNotEqual(initial, learned)
        self.assertLessEqual(params, 2048)
        self.assertEqual(len(learned), 64)
        self.assertFalse(any(p.grad is None for p in head.parameters()))

    def test_runtime_weights_must_equal_pinned_tensor_bytes(self):
        import torch

        class FakeReader:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def keys(self):
                return ["encoder.value"]

            def get_tensor(self, name):
                self.asserted_name = name
                return torch.tensor([self.value], dtype=torch.float32)

        fake_module = ModuleType("safetensors")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "model.safetensors").write_bytes(b"synthetic weight-file bytes")
            original = sys.modules.get("safetensors")
            present = "safetensors" in sys.modules
            try:
                fake_module.safe_open = lambda *_args, **_kwargs: FakeReader(.5)
                sys.modules["safetensors"] = fake_module
                model = SimpleNamespace(
                    state_dict=lambda: {"encoder.value": torch.tensor([.5])})
                receipt = verify_loaded_safetensors(torch, model, root)
                self.assertEqual(receipt["tensor_elements"], 1)
                self.assertTrue(receipt["all_state_dict_tensors_compared"])
                fake_module.safe_open = lambda *_args, **_kwargs: FakeReader(.4)
                with self.assertRaisesRegex(ValueError, "differs from pinned"):
                    verify_loaded_safetensors(torch, model, root)
                fake_module.safe_open = lambda *_args, **_kwargs: FakeReader(.5)
                broken_model = SimpleNamespace(
                    state_dict=lambda: {"encoder.other": torch.tensor([.5])})
                with self.assertRaisesRegex(ValueError, "unexpected safetensors"):
                    verify_loaded_safetensors(torch, broken_model, root)
            finally:
                if present:
                    sys.modules["safetensors"] = original
                else:
                    sys.modules.pop("safetensors", None)

    def test_same_seed_data_and_initialization_replays_identically(self):
        import torch
        torch.manual_seed(2)
        head, _ = build_head(torch, 8, 2, 2048)
        control = copy.deepcopy(head)
        features = torch.randn(8, 8)
        labels = torch.tensor([0, 1, 1, 0, 1, 0, 0, 1])
        first = train_head(
            torch, head, features, labels,
            batch_size=4, steps=5, seed=7347)
        second = train_head(
            torch, control, features, labels,
            batch_size=4, steps=5, seed=7347)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

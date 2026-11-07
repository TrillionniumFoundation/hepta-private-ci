"""Tiny neural contracts only; these tests are not pretrained-model efficacy."""

import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import torch
from torch import nn

from . import train_adapter as training
from .dual_runtime import digest_file


class TensorHashTests(unittest.TestCase):
    def test_singleton_strides_and_scalar_keep_exact_bfloat16_bytes(self):
        payload = struct.pack("=4H", 0x3F80, 0x8000, 0x7FC1, 0x4000)
        source = torch.frombuffer(bytearray(payload), dtype=torch.bfloat16)
        cases = (
            (source.as_strided((4, 1, 1), (1, 320, 320)), payload),
            (source[:1].as_strided((1, 1), (320, 320)), payload[:2]),
            (source[0], payload[:2]),
        )
        for value, raw in cases:
            with self.subTest(shape=tuple(value.shape), stride=value.stride()):
                self.assertTrue(value.is_contiguous())
                expected = hashlib.sha256(
                    str((tuple(value.shape), str(value.dtype))).encode() + raw
                ).hexdigest()
                self.assertEqual(training.tensor_hash(value), expected)

    def test_hash_uses_logical_values_without_storage_padding_or_mutation(self):
        source = torch.arange(24, dtype=torch.float32).reshape(4, 6)
        before = source.clone()
        cases = (source, source.t(), source[1:3, 1::2], source[:1].expand(3, 6), source[:0])
        for value in cases:
            with self.subTest(shape=tuple(value.shape), stride=value.stride()):
                expected = hashlib.sha256(
                    str((tuple(value.shape), str(value.dtype))).encode()
                    + value.numpy().tobytes(order="C")
                ).hexdigest()
                self.assertEqual(training.tensor_hash(value), expected)
        self.assertTrue(torch.equal(source, before))

    def test_parameter_fingerprint_keeps_shape_dtype_name_and_value_bindings(self):
        value = torch.tensor([1.0, 2.0], requires_grad=True)
        module = nn.Module()
        module.register_parameter("weight", nn.Parameter(value.detach().as_strided((2, 1), (1, 320))))
        before = training.parameter_hashes(module)
        canonical = nn.Module()
        canonical.register_parameter("weight", nn.Parameter(value.detach().reshape(2, 1).clone()))
        self.assertEqual(before, training.parameter_hashes(canonical))
        self.assertNotEqual(training.tensor_hash(value), training.tensor_hash(value.reshape(2, 1)))
        self.assertNotEqual(training.tensor_hash(value), training.tensor_hash(value.view(torch.int32)))
        self.assertNotEqual(training.fingerprint(before), training.fingerprint({"renamed": before["weight"]}))
        with torch.no_grad():
            module.weight[0, 0] += 1
        self.assertNotEqual(before, training.parameter_hashes(module))
        self.assertTrue(module.weight.requires_grad)
        self.assertIsNone(module.weight.grad)


class TinyModel(nn.Module):
    def __init__(self):
        super().__init__()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(43)
            self.embedding = nn.Embedding(8, 4)
            self.image_encoder = nn.Linear(3, 4, bias=False)
            self.lm_head = nn.Linear(4, 8, bias=False)
            self.lm_head.weight = self.embedding.weight
        self.eval().requires_grad_(False)

    def get_output_embeddings(self):
        return self.lm_head

    def forward(self, input_ids, pixel_values, **kwargs):
        vision = self.image_encoder(pixel_values.float().mean((-1, -2)))[:, None]
        return SimpleNamespace(logits=self.lm_head(self.embedding(input_ids) + vision))


class Processor:
    broken = False

    def apply_chat_template(self, messages, **kwargs):
        return "a long visual and assistant prefix" if len(messages) == 1 else "the complete conversation"

    def __call__(self, text, images, **kwargs):
        ids = [1, 2, 3] if text.startswith("a long") else [1, 2, 3, 4, 5]
        if self.broken and not text.startswith("a long"):
            ids[1] = 7
        value = torch.tensor([ids])
        return {"input_ids": value, "attention_mask": torch.ones_like(value),
                "pixel_values": torch.ones(1, 3, 4, 4)}


class Backend:
    instance = None
    processor_type = Processor

    def __init__(self, *args):
        self.model, self.processor = TinyModel(), self.processor_type()
        Backend.instance = self

    def _activate(self, key):
        if key != "vlm":
            raise AssertionError("The image generator must remain unused by this trainer")

    def identity(self):
        return {"backend": "tiny_contract_test_not_pretrained"}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/dev/shm" if Path("/dev/shm").is_dir() else None)
        self.root = Path(self.temp.name)
        self.image = self.root / "input.png"; Image.new("RGB", (8, 8), "red").save(self.image)
        self.row = {"source_id": "one-source", "image_path": str(self.image),
                    "image_sha256": digest_file(self.image), "instruction": "Describe it.", "target": "A red square."}
        self.manifest = self.root / "train.json"
        self.manifest.write_text(json.dumps({"schema": "hepta.real-adapter-training-data.v1",
                                            "role": "training_only", "examples": [self.row]}))

    def tearDown(self):
        self.temp.cleanup()

    def run_training(self, **kwargs):
        with patch.object(training, "LocalModels", Backend):
            return training.train(self.root, self.manifest, self.root / "output", "a" * 40,
                                  digest_file(self.manifest), steps=3, learning_rate=.1, **kwargs)

    def test_update_freezes_tied_backbone_and_reload_controls_actual_logits(self):
        report = self.run_training()
        self.assertEqual((report["status"], report["base_changed_parameter_tensors"],
                          report["completed_updates"], report["observed_training_source_count"]), ("completed", 0, 3, 1))
        self.assertGreater(report["adapter_changed_parameter_values"], 0)
        self.assertEqual((report["reload_probe"]["equal"], report["reload_probe"]["max_abs_diff"]), (True, 0.0))
        model = Backend.instance.model
        inputs, _, _ = training.prepare_inputs(Processor(), self.row)
        with torch.inference_mode():
            baseline = model(**inputs).logits
        path = self.root / "output" / report["checkpoint"]["path"]
        _, handle = training.load_adapter(model, path, report["checkpoint"]["sha256"])
        with torch.inference_mode():
            first = model(**inputs).logits
        self.assertFalse(torch.equal(baseline, first))
        handle.remove()
        _, handle = training.load_adapter(model, path, report["checkpoint"]["sha256"])
        with torch.inference_mode():
            second = model(**inputs).logits
        self.assertTrue(torch.equal(first, second)); handle.remove()
        receipt = json.loads((self.root / "output" / "cost_receipt.json").read_text())
        self.assertGreater(receipt["cpu_seconds"], 0)
        self.assertIn("full_base_parameter_hash_after", [e["kind"] for e in receipt["events"]])
        with torch.no_grad():
            model.embedding.weight[0, 0] += 1
        with self.assertRaisesRegex(ValueError, "different backbone"):
            training.load_adapter(model, path, report["checkpoint"]["sha256"])

    def test_target_mask_is_processor_aligned_and_never_string_counted(self):
        _, labels, counts = training.prepare_inputs(Processor(), self.row)
        self.assertEqual(labels.tolist(), [[-100, -100, -100, 4, 5]])
        self.assertEqual(counts, {"prefix_tokens": 3, "answer_tokens": 2})
        processor = Processor(); processor.broken = True
        with self.assertRaisesRegex(ValueError, "alignment"):
            training.prepare_inputs(processor, self.row)
        with self.assertRaisesRegex(ValueError, "token limit"):
            training.prepare_inputs(Processor(), self.row, max_answer_tokens=1)

    def test_failed_forward_preparation_remains_in_training_costs(self):
        with patch.object(Processor, "broken", True):
            report = self.run_training()
        self.assertEqual((report["status"], report["completed_updates"], report["checkpoint"]), ("failed", 0, None))
        receipt = json.loads((self.root / "output" / "cost_receipt.json").read_text())
        kinds = [e["kind"] for e in receipt["events"]]
        self.assertTrue({"update_started", "failure", "full_base_parameter_hash_after", "report_write"} <= set(kinds))
        self.assertGreater(receipt["cpu_seconds"], 0)

    def test_changed_source_or_duplicate_source_is_not_admitted(self):
        Image.new("RGB", (8, 8), "blue").save(self.image)
        report = self.run_training()
        self.assertEqual((report["status"], report["completed_updates"]), ("failed", 0))
        self.assertIn("Input bytes", report["error"]["message"])
        data = json.loads(self.manifest.read_text()); data["examples"].append(dict(self.row, source_id="fake-independent"))
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "distinct source/image"):
            training.read_examples(self.manifest, digest_file(self.manifest))

    def test_final_hash_overrun_revokes_checkpoint_but_retains_artifact_and_cost(self):
        original, clock = training.parameter_hashes, {"now": 0., "adapter_calls": 0}
        def late_hash(module):
            if isinstance(module, training.OutputAdapter):
                clock["adapter_calls"] += 1
                if clock["adapter_calls"] == 2:
                    clock["now"] = 2.
            return original(module)
        with patch.object(training, "parameter_hashes", side_effect=late_hash), \
                patch.object(training.time, "process_time", side_effect=lambda: clock["now"]), \
                patch.object(training.time, "perf_counter", side_effect=lambda: clock["now"]):
            report = self.run_training(cpu_budget=1., wall_budget=1.)
        self.assertEqual((report["status"], report["checkpoint"]), ("timeout", None))
        self.assertTrue((self.root / "output" / report["checkpoint_artifact"]["path"]).is_file())
        receipt = json.loads((self.root / "output" / "cost_receipt.json").read_text())
        self.assertEqual((receipt["cpu_seconds"], receipt["wall_seconds"], receipt["qualified_checkpoint"]), (2., 2., None))

    def test_final_hash_failure_still_seals_report_and_failure_costs(self):
        original, count = training.parameter_hashes, [0]
        def broken_hash(module):
            if isinstance(module, training.OutputAdapter):
                count[0] += 1
                if count[0] == 2:
                    raise RuntimeError("injected final hash failure")
            return original(module)
        with patch.object(training, "parameter_hashes", side_effect=broken_hash):
            report = self.run_training()
        self.assertEqual((report["status"], report["checkpoint"]), ("failed", None))
        self.assertTrue((self.root / "output" / "report.json").is_file())
        receipt = json.loads((self.root / "output" / "cost_receipt.json").read_text())
        self.assertIn("finalization_failure", [e["kind"] for e in receipt["events"]])
        self.assertGreater(receipt["cpu_seconds"], 0)

    def test_exhausted_allowance_is_failed_training_not_free_success(self):
        report = self.run_training(cpu_budget=1e-12)
        self.assertEqual((report["status"], report["completed_updates"], report["checkpoint"]), ("timeout", 0, None))
        self.assertTrue((self.root / "output" / "cost_receipt.json").is_file())


if __name__ == "__main__":
    unittest.main()

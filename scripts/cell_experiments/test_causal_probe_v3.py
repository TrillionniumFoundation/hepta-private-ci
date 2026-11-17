"""Probe binding/behavior tests use fake backends, never actual model weights."""

from contextlib import nullcontext
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from . import causal_probe_v3 as probe, data


class Tensor:
    def __init__(self, rows):
        self.rows, self.shape = rows, (len(rows), len(rows[0]))

    def to(self, device):
        self.device = device
        return self

    def __getitem__(self, key):
        row, tail = key
        return SimpleNamespace(tolist=lambda: self.rows[row][tail])


class FakeTokenizer:
    bos_token_id, eos_token_id, pad_token_id = None, 2, 0

    def __init__(self):
        self.count, self.rendered, self.messages = 3, None, None
        self.raw = '  ```json\n{"untouched":true}\n```\n'

    def get_chat_template(self):
        return "{{ messages }}"

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        self.messages = copy.deepcopy(messages)
        return json.dumps(messages) + "assistant:"

    def __call__(self, rendered, *, return_tensors, add_special_tokens):
        self.rendered = rendered
        return {
            "input_ids": Tensor([[1] * self.count]),
            "attention_mask": Tensor([[1] * self.count]),
        }

    def decode(self, tokens, **options):
        self.decode_options = options
        return self.raw


class FakeModel:
    def __init__(self):
        self.produced, self.calls, self.device = [5, 6, 3], [], "cpu"

    def to(self, device):
        self.device = device
        return self

    def parameters(self):
        return [
            SimpleNamespace(
                device=self.device, dtype="float32", is_floating_point=lambda: True
            )
        ]

    def eval(self):
        self.training = False

    def requires_grad_(self, enabled):
        self.grad_enabled = enabled

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return Tensor([kwargs["input_ids"].rows[0] + self.produced])


class Generation:
    def __init__(self, **kwargs):
        self.values = copy.deepcopy(kwargs)

    def to_dict(self):
        return copy.deepcopy(self.values)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / "snapshot"
        self.base.mkdir()
        documents = {
            "config.json": {
                "model_type": "qwen2",
                "architectures": ["Qwen2ForCausalLM"],
                "vocab_size": 64,
                "max_position_embeddings": 128,
            },
            "tokenizer_config.json": {
                "chat_template": "{{ messages }}",
                "bos_token": None,
                "eos_token": "<eos>",
                "pad_token": "<pad>",
            },
            "tokenizer.json": {
                "model": {"vocab": {"hello": 1}},
                "added_tokens": [
                    {"content": "<eos>", "id": 2},
                    {"content": "<pad>", "id": 0},
                ],
            },
            "generation_config.json": {
                "bos_token_id": 3,
                "eos_token_id": [2, 3],
                "pad_token_id": 0,
                "do_sample": True,
            },
        }
        for name, document in documents.items():
            (self.base / name).write_text(json.dumps(document))
        (self.base / "model.safetensors").write_bytes(
            b"ENGINEERING-STUB-NOT-MODEL-WEIGHTS"
        )
        versions = patch.object(
            probe, "_versions", return_value={"engineering_backend": "1"}
        )
        versions.start()
        self.addCleanup(versions.stop)
        self.manifest = self.build()
        self.tokenizer, self.model = FakeTokenizer(), FakeModel()
        self.cuda = SimpleNamespace(
            is_available=Mock(return_value=True),
            device_count=Mock(return_value=3),
            device=Mock(side_effect=lambda index: nullcontext()),
            is_bf16_supported=Mock(return_value=True),
            mem_get_info=Mock(return_value=(probe.MIN_CUDA_FREE_BYTES, 8 * 1024**3)),
            get_device_properties=Mock(
                return_value=SimpleNamespace(name="fake GPU", major=8, minor=0)
            ),
        )
        self.torch = SimpleNamespace(
            device=lambda value: value,
            set_num_threads=Mock(),
            float32="float32",
            bfloat16="bfloat16",
            cuda=self.cuda,
            inference_mode=nullcontext,
        )
        self.backend = SimpleNamespace(
            AutoTokenizer=SimpleNamespace(
                from_pretrained=Mock(return_value=self.tokenizer)
            ),
            AutoModelForCausalLM=SimpleNamespace(
                from_pretrained=Mock(return_value=self.model)
            ),
            GenerationConfig=Generation,
        )

    def build(self, **runtime):
        return probe.build_manifest(
            self.root,
            "snapshot",
            revision="1" * 40,
            device=runtime.pop("device", "cpu"),
            dtype=runtime.pop("dtype", "float32"),
            max_input_tokens=16,
            max_new_tokens=3,
            **runtime,
        )

    def load(self, manifest=None):
        with patch.object(probe, "_libraries", return_value=(self.torch, self.backend)):
            predictor = probe.Predictor(manifest or self.manifest, self.root)
        self.addCleanup(predictor.close)
        return predictor

    def test_changed_or_added_files_are_rejected_before_backend_import(self):
        weight = self.base / "model.safetensors"
        original = weight.read_bytes()
        for changed in (True, False):
            with self.subTest(changed=changed):
                if changed:
                    weight.write_bytes(original + b"changed")
                else:
                    weight.write_bytes(original)
                    (self.base / "extra.safetensors").write_bytes(b"unbound")
                with patch.object(probe, "_libraries") as libraries:
                    with self.assertRaisesRegex(ValueError, "inventory"):
                        probe.Predictor(self.manifest, self.root)
                    libraries.assert_not_called()

    def test_exact_shard_inventory_and_symlinks_fail_closed(self):
        (self.base / "model.safetensors").rename(self.base / "model-1.safetensors")
        index = {
            "weight_map": {"one": "model-1.safetensors", "two": "model-2.safetensors"}
        }
        (self.base / "model.safetensors.index.json").write_text(json.dumps(index))
        with self.assertRaisesRegex(ValueError, "shard index"):
            self.build()
        (self.base / "model-2.safetensors").write_bytes(b"SECOND-ENGINEERING-STUB")
        sharded = self.build()
        self.assertEqual(probe.verify_model(sharded, self.root), data.digest(sharded))
        (self.base / "tokenizer-link.json").symlink_to(self.base / "tokenizer.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.build()
        with self.assertRaisesRegex(ValueError, "inside"):
            probe.build_manifest(
                self.root,
                "../outside",
                revision="1" * 40,
                device="cpu",
                dtype="float32",
            )

    def test_template_generation_and_backend_changes_fail_before_loading(self):
        for key, value in (
            ("chat_template_sha256", "0" * 64),
            (
                "generation",
                {**self.manifest["runtime"]["generation"], "do_sample": True},
            ),
        ):
            manifest = copy.deepcopy(self.manifest)
            manifest["runtime"][key] = value
            with self.subTest(key=key), patch.object(probe, "_libraries") as libraries:
                with self.assertRaises(ValueError):
                    probe.Predictor(manifest, self.root)
                libraries.assert_not_called()
        with patch.object(
            probe, "_versions", return_value={"engineering_backend": "2"}
        ):
            with self.assertRaisesRegex(ValueError, "versions"):
                probe.verify_model(self.manifest, self.root)

    def test_explicit_device_and_token_budgets_are_required(self):
        for settings in (
            {"device": "cuda", "dtype": "bfloat16"},
            {"device": "cpu", "dtype": "bfloat16"},
            {"device": "cuda:0", "dtype": "float32"},
            {"min_cuda_free_bytes": probe.MIN_CUDA_FREE_BYTES - 1},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.build(**settings)
        manifest = copy.deepcopy(self.manifest)
        manifest["runtime"]["max_input_tokens"] = 127
        with self.assertRaisesRegex(ValueError, "context window"):
            probe.verify_model(manifest, self.root)

    def test_cuda_checks_selected_device_and_never_falls_back(self):
        manifest = self.build(device="cuda:2", dtype="bfloat16")
        for name, failed in (
            ("is_available", False),
            ("device_count", 2),
            ("is_bf16_supported", False),
            ("mem_get_info", (probe.MIN_CUDA_FREE_BYTES - 1, 8 * 1024**3)),
        ):
            function = getattr(self.cuda, name)
            original = function.return_value
            function.return_value = failed
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.load(manifest)
            function.return_value = original
            self.backend.AutoModelForCausalLM.from_pretrained.assert_not_called()
        report = probe.check_device(self.torch, manifest["runtime"])
        self.assertEqual(report["device"], "cuda:2")
        self.cuda.mem_get_info.assert_called_with(2)
        self.cuda.get_device_properties.assert_called_with(2)

    def test_local_load_and_whitelisted_native_history_preserve_raw_answer(self):
        predictor = self.load()
        request = {
            "record_id": "engineering-request",
            "final_answer": "SECRET-GOLD",
            "trajectory": [{"content": "SECRET-TRAJECTORY"}],
            "task": {
                "input": "Write a test",
                "verifier": {"expected": "SECRET-ORACLE"},
                "messages": [
                    {"role": "user", "content": "Write a test"},
                    {"role": "assistant", "content": "invalid action"},
                    {"role": "tool", "content": "JSON validation failed"},
                ],
            },
        }
        output = predictor.predict(request)
        self.assertEqual(output["answer"], self.tokenizer.raw)
        self.assertNotIn("SECRET-", self.tokenizer.rendered)
        self.assertEqual(
            self.tokenizer.messages[-1],
            {
                "role": "user",
                "content": "Tool observation:\nJSON validation failed",
            },
        )
        self.assertEqual(
            self.tokenizer.decode_options,
            {
                "skip_special_tokens": True,
                "clean_up_tokenization_spaces": False,
            },
        )
        self.assertEqual(
            (
                output["input_tokens"],
                output["output_tokens"],
                output["output_token_ids"],
            ),
            (3, 3, [5, 6, 3]),
        )
        self.assertEqual(output["loaded_model_digest"], data.digest(self.manifest))
        self.assertEqual(
            output["messages_sha256"], data.digest(request["task"]["messages"])
        )
        self.assertEqual(
            (output["finish_reason"], output["hit_output_limit"]), ("eos_token", False)
        )
        self.backend.AutoModelForCausalLM.from_pretrained.assert_called_once_with(
            str(self.base),
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype="float32",
            attn_implementation="eager",
        )
        self.assertFalse(self.model.training or self.model.grad_enabled)

    def test_no_truncation_and_actual_cap_or_eos_termination(self):
        predictor = self.load()
        request = {"task": {"input": "bounded"}}
        self.tokenizer.count = 17
        with self.assertRaisesRegex(ValueError, "no truncation"):
            predictor.predict(request)
        self.assertEqual(self.model.calls, [])
        self.tokenizer.count = 3
        for produced, expected in (
            ([5, 6, 7], (True, "max_new_tokens")),
            ([5, 2], (False, "eos_token")),
        ):
            self.model.produced = produced
            output = predictor.predict(request)
            self.assertEqual(
                (output["hit_output_limit"], output["finish_reason"]), expected
            )
            self.assertEqual(output["output_token_ids"], produced)
        predictor.generation.values["do_sample"] = True
        with self.assertRaisesRegex(ValueError, "generation configuration changed"):
            predictor.predict(request)
        predictor.close()
        with self.assertRaisesRegex(ValueError, "closed"):
            predictor.predict(request)


if __name__ == "__main__":
    unittest.main()

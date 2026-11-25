"""Real file substitutions around fake loaders; no model or training is executed."""

import copy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from . import coding_sft


class CodingLoadIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.root = self.home / "materials"
        for directory in ("base", "adapter"):
            (self.root / directory).mkdir(parents=True)
        for name in (
            "model.safetensors",
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ):
            (self.root / "base" / name).write_bytes(b"{}")
        for name in ("adapter_model.safetensors", "adapter_config.json"):
            (self.root / "adapter" / name).write_bytes(b"{}")
        self.manifest = dict(
            schema=coding_sft.MODEL_SCHEMA,
            family=coding_sft.FAMILY,
            parent=None,
            files=coding_sft.inventory(self.root, list(self.root.rglob("*.*")), "base"),
            runtime=dict(
                base_directory="base",
                adapter_directory="adapter",
                max_input_tokens=128,
                max_new_tokens=8,
            ),
        )
        self.expected = copy.deepcopy(self.manifest)
        self.model = Mock()
        self.tokenizer = SimpleNamespace(pad_token_id=0)
        self.tokenizer_load = Mock(return_value=self.tokenizer)
        self.model_load = Mock(return_value=self.model)
        self.adapter_load = Mock(return_value=self.model)
        libraries = (
            SimpleNamespace(set_num_threads=Mock(), float32="fixture-float32"),
            SimpleNamespace(
                AutoTokenizer=SimpleNamespace(from_pretrained=self.tokenizer_load),
                AutoModelForCausalLM=SimpleNamespace(from_pretrained=self.model_load),
            ),
            SimpleNamespace(
                PeftModel=SimpleNamespace(from_pretrained=self.adapter_load)
            ),
        )
        loader = patch.object(coding_sft, "_libraries", return_value=libraries)
        loader.start()
        self.addCleanup(loader.stop)

    def test_unchanged_materials_keep_the_original_identity_and_trainable_setting(self):
        result = coding_sft._load(self.manifest, self.root, trainable=True)
        self.assertEqual(
            result, (self.model, self.tokenizer, coding_sft.digest(self.expected))
        )
        self.adapter_load.assert_called_once_with(
            self.model,
            str(self.root / "adapter"),
            is_trainable=True,
            local_files_only=True,
        )

    def test_base_weight_replacement_during_load_is_rejected(self):
        def replace(*args, **kwargs):
            (self.root / "base/model.safetensors").write_bytes(b"changed")
            return self.model

        self.model_load.side_effect = replace
        with self.assertRaisesRegex(ValueError, "artifact identity mismatch"):
            coding_sft._load(self.manifest, self.root)

    def test_tokenizer_replacement_during_load_is_rejected(self):
        def replace(*args, **kwargs):
            (self.root / "base/tokenizer.json").write_bytes(b"changed")
            return self.tokenizer

        self.tokenizer_load.side_effect = replace
        with self.assertRaisesRegex(ValueError, "artifact identity mismatch"):
            coding_sft._load(self.manifest, self.root)

    def test_adapter_replacement_during_load_is_rejected(self):
        def replace(*args, **kwargs):
            (self.root / "adapter/adapter_model.safetensors").write_bytes(b"changed")
            return self.model

        self.adapter_load.side_effect = replace
        with self.assertRaisesRegex(ValueError, "artifact identity mismatch"):
            coding_sft._load(self.manifest, self.root)

    def test_new_unbound_loadable_file_is_rejected(self):
        def inject(*args, **kwargs):
            (self.root / "base/pytorch_model.bin").write_bytes(b"unbound")
            return self.model

        self.model_load.side_effect = inject
        with self.assertRaisesRegex(ValueError, "unbound loadable file"):
            coding_sft._load(self.manifest, self.root)

    def test_caller_mutation_during_load_cannot_redirect_the_adapter(self):
        def mutate_caller(*args, **kwargs):
            self.manifest["runtime"]["adapter_directory"] = "unbound"
            self.manifest["runtime"]["max_new_tokens"] = 1024
            return self.model

        self.model_load.side_effect = mutate_caller
        result = coding_sft._load(self.manifest, self.root)
        self.assertEqual(
            result, (self.model, self.tokenizer, coding_sft.digest(self.expected))
        )
        self.adapter_load.assert_called_once_with(
            self.model,
            str(self.root / "adapter"),
            is_trainable=False,
            local_files_only=True,
        )

    def test_predictor_keeps_its_own_manifest_after_caller_changes(self):
        predictor = coding_sft.Predictor(self.manifest, self.root)
        self.manifest["runtime"]["max_new_tokens"] = 1024
        self.manifest["files"][0]["sha256"] = "f" * 64
        self.assertEqual(predictor.manifest, self.expected)
        self.assertEqual(predictor.model_digest, coding_sft.digest(self.expected))

    def test_relative_material_root_is_fixed_before_backend_changes_directory(self):
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        other = self.home / "other"
        other.mkdir()
        os.chdir(self.home)

        def move(*args, **kwargs):
            os.chdir(other)
            return self.tokenizer

        self.tokenizer_load.side_effect = move
        coding_sft._load(self.manifest, Path("materials"))
        self.model_load.assert_called_once_with(
            str(self.root / "base"),
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype="fixture-float32",
            attn_implementation="eager",
        )
        self.adapter_load.assert_called_once_with(
            self.model,
            str(self.root / "adapter"),
            is_trainable=False,
            local_files_only=True,
        )


if __name__ == "__main__":
    unittest.main()

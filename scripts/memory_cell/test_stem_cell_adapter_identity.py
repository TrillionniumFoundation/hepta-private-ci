"""Real tiny-PEFT tests of gradient context and tensor/container identity."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from peft import get_peft_model_state_dict
from safetensors.torch import save as save_tensors

from stem_cell import sha256
from stem_cell_adapter import tensor_state_digest
from test_stem_cell_adapter_transformer import Pool, Query, fit, tiny_encoder


class AdapterIdentityTests(unittest.TestCase):
    def test_state_digest_binds_bits_names_shape_dtype_not_mapping_order(self):
        state = {"a": torch.tensor([1.0, -0.0]), "b": torch.tensor([2.0])}
        expected = tensor_state_digest(state)
        self.assertEqual(
            expected, tensor_state_digest(dict(reversed(list(state.items()))))
        )
        for changed in (
            {"a": torch.tensor([1.0, 0.0]), "b": state["b"]},
            {"a": state["a"].reshape(1, 2), "b": state["b"]},
            {"a": state["a"].double(), "b": state["b"]},
            {"renamed": state["a"], "b": state["b"]},
        ):
            self.assertNotEqual(expected, tensor_state_digest(changed))
        with self.assertRaises(ValueError):
            tensor_state_digest({"bad": torch.tensor([float("nan")])})

    def test_same_tensors_different_valid_containers_keep_representation_identity(self):
        encoder = tiny_encoder()
        fit(encoder)
        state = get_peft_model_state_dict(encoder.model)
        first = save_tensors(state, metadata={"container": "first"})
        second = save_tensors(state, metadata={"container": "second"})
        self.assertNotEqual(sha256(first), sha256(second))
        identity = encoder.identity
        # Integrity verification must never depend on reserializing a container.
        with patch.object(
            encoder, "tensor_bytes", side_effect=AssertionError("serialization")
        ):
            encoder.verify_frozen()
        self.assertEqual(encoder.identity, identity)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "adapter"
            with patch.object(encoder, "tensor_bytes", return_value=second):
                metadata = encoder.export(directory)
            self.assertEqual(metadata["tensor_sha256"], sha256(second))
            self.assertEqual(
                metadata["tensor_state_sha256"], tensor_state_digest(state)
            )
            restored = tiny_encoder()
            restored.restore_into(
                directory,
                expected_metadata=metadata,
                allowed_roots={"root"},
                revoked=set(),
            )
            before, _ = encoder.encode(Query(), "family", Pool(), revoked=set())
            after, _ = restored.encode(Query(), "family", Pool(), revoked=set())
            self.assertEqual(before.seal(), after.seal())
            self.assertEqual(restored.identity, identity)
            # A different valid file still fails the ORIGINAL byte pin.
            (directory / "adapter.safetensors").write_bytes(first)
            with self.assertRaisesRegex(ValueError, "restore identity"):
                tiny_encoder().restore_into(
                    directory,
                    expected_metadata=metadata,
                    allowed_roots={"root"},
                    revoked=set(),
                )

    def test_training_inside_no_grad_is_local_and_restores_callers_mode(self):
        encoder = tiny_encoder()
        with torch.no_grad():
            self.assertFalse(torch.is_grad_enabled())
            receipt = fit(encoder)
            self.assertFalse(torch.is_grad_enabled())
        self.assertTrue(receipt["gradient_context_enabled"])
        self.assertGreater(receipt["adapter_delta_squared_norm"], 0)
        encoder.verify_frozen()

    def test_inference_mode_training_rejects_without_partial_mutation(self):
        encoder = tiny_encoder()
        before = tensor_state_digest(get_peft_model_state_dict(encoder.model))
        with torch.inference_mode():
            with self.assertRaisesRegex(ValueError, "inference-mode"):
                fit(encoder)
        self.assertEqual(
            before, tensor_state_digest(get_peft_model_state_dict(encoder.model))
        )
        self.assertFalse(encoder.frozen)

    def test_base_and_adapter_mutations_have_distinct_failure_reasons(self):
        base = tiny_encoder()
        fit(base)
        with torch.no_grad():
            for name, parameter in base.model.named_parameters():
                if "lora_" not in name:
                    parameter.add_(0.01)
                    break
        with self.assertRaisesRegex(ValueError, "base-weight digest"):
            base.verify_frozen()
        adapter = tiny_encoder()
        fit(adapter)
        with torch.no_grad():
            for name, parameter in adapter.model.named_parameters():
                if "lora_" in name:
                    parameter.add_(0.01)
                    break
        with self.assertRaisesRegex(ValueError, "adapter-state digest"):
            adapter.verify_frozen()

    def test_state_pin_cannot_be_relabelled_by_matching_file_hash(self):
        encoder = tiny_encoder()
        fit(encoder)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "adapter"
            metadata = encoder.export(directory)
            metadata["tensor_state_sha256"] = "0" * 64
            (directory / "adapter.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "canonical tensor-state"):
                tiny_encoder().restore_into(
                    directory,
                    expected_metadata=metadata,
                    allowed_roots={"root"},
                    revoked=set(),
                )


if __name__ == "__main__":
    unittest.main()

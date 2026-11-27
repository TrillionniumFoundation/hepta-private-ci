"""Actual serialization, quantization, source-admission and baseline regressions."""

import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

import torch
from safetensors.torch import save

from checkpoint_codec import decode_checkpoint, encode_checkpoint
from exact_baselines import measure_baselines
from parametric_owner import Frontier, ParametricOwner
from quantized_adapter import (
    MAGIC,
    canonical_bytes,
    decode_tensors,
    encode_tensors,
    state_digest,
)
from tensor_contract import read_candidate, sha256, tensor_layout


class CheckpointCodecTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.parent = self.directory / "parent"
        self.parent.mkdir()
        self.state = {
            "layer.lora_A.weight": torch.tensor(
                [[-0.23, 0.0, 0.91], [0.64, -0.35, 0.12], [0.31, -0.4, 0.9]]
            ),
            "layer.lora_B.weight": torch.zeros((2, 3)),
        }
        config = canonical_bytes(
            dict(r=3, lora_alpha=6, target_modules=["q_proj", "v_proj"])
        )
        tensors = save(self.state, metadata={"format": "pt"})
        self.lineage = dict(
            schema="hepta.memory-lora-candidate.v2",
            base_identity="b" * 64,
            scope="codec-test",
            roots=["a" * 64],
            tensor_layout=tensor_layout(self.state),
            adapter_sha256=sha256(tensors),
            config_sha256=sha256(config),
            training=dict(
                adapter_state_sha256=state_digest(self.state), steps=9, roots=["a" * 64]
            ),
            model_install_authority=False,
            production_accepted=False,
        )
        self.manifest = sha256(canonical_bytes(self.lineage))
        for name, payload in (
            ("lineage.json", canonical_bytes(self.lineage)),
            ("adapter_config.json", config),
            ("adapter_model.safetensors", tensors),
        ):
            (self.parent / name).write_bytes(payload)

    def tearDown(self):
        self.temporary.cleanup()

    def encode(self, bits=8, label="packed", revoked=()):
        return encode_checkpoint(
            self.parent,
            self.directory / label,
            expected_manifest_sha256=self.manifest,
            allowed_roots={"a" * 64},
            revoked_roots=set(revoked),
            bits=bits,
        )

    def test_quantization_actual_error_bounds_and_determinism(self):
        for bits in (4, 8):
            packed, metrics = encode_tensors(self.state, bits)
            repeated, repeated_metrics = encode_tensors(self.state, bits)
            self.assertEqual((packed, metrics), (repeated, repeated_metrics))
            decoded = decode_tensors(
                packed, expected_layout=tensor_layout(self.state), expected_bits=bits
            )
            for name in self.state:
                scale = float(self.state[name].abs().max()) / ((1 << (bits - 1)) - 1)
                self.assertLessEqual(
                    float((self.state[name] - decoded[name]).abs().max()),
                    scale / 2 + 1e-7,
                )
            self.assertEqual(metrics["decoded_state_sha256"], state_digest(decoded))
            self.assertNotEqual(
                metrics["source_state_sha256"], metrics["decoded_state_sha256"]
            )

    def test_derived_checkpoint_retains_ancestry_and_owner_admits_new_identity(self):
        original = {p.name: p.read_bytes() for p in self.parent.iterdir()}
        encoded = self.encode(4)
        output = self.directory / "decoded"
        receipt = decode_checkpoint(
            self.directory / "packed",
            output,
            expected_codec_sha256=encoded["codec_manifest_sha256"],
            allowed_roots={"a" * 64},
            revoked_roots=set(),
        )
        state, roots, manifest = read_candidate(
            output,
            expected_manifest_sha256=receipt["manifest_sha256"],
            base_identity="b" * 64,
            scope="codec-test",
            expected_layout=tensor_layout(self.state),
            expected_config=json.loads(original["adapter_config.json"]),
            allowed_roots={"a" * 64},
            revoked_roots=set(),
        )
        self.assertEqual(roots, frozenset({"a" * 64}))
        self.assertNotEqual(receipt["manifest_sha256"], self.manifest)
        self.assertEqual(manifest["training"]["optimizer_steps"], 0)
        self.assertEqual(
            manifest["training"]["learned_parent_manifest_sha256"], self.manifest
        )
        self.assertEqual(
            (output / "source-lineage.json").read_bytes(), original["lineage.json"]
        )
        self.assertEqual(receipt["adapter_state_sha256"], state_digest(state))
        owner = ParametricOwner(self.directory / "owner.sqlite3")
        provider = lambda: Frontier("codec-test")
        owner.activate(
            "derived",
            output,
            receipt["manifest_sha256"],
            scope="codec-test",
            expected_current=None,
            generation=0,
            provider=provider,
            allowed_roots={"a" * 64},
        )
        self.assertEqual(
            owner.invoke(
                "derived", "codec-test", provider, lambda active: active.roots
            ),
            ("a" * 64,),
        )
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.parent.iterdir()}, original
        )
        self.assertEqual(
            encoded["packed_artifact_bytes"],
            sum(p.stat().st_size for p in (self.directory / "packed").iterdir()),
        )
        self.assertEqual(
            receipt["materialized_checkpoint_bytes"],
            sum(p.stat().st_size for p in output.iterdir()),
        )

    def test_revocation_rejects_before_derivation_and_before_materialization(self):
        with self.assertRaises(ValueError):
            self.encode(revoked={"a" * 64})
        self.assertFalse((self.directory / "packed").exists())
        encoded = self.encode()
        with self.assertRaises(ValueError):
            decode_checkpoint(
                self.directory / "packed",
                self.directory / "decoded",
                expected_codec_sha256=encoded["codec_manifest_sha256"],
                allowed_roots={"a" * 64},
                revoked_roots={"a" * 64},
            )
        self.assertFalse((self.directory / "decoded").exists())

    def test_corruption_truncation_and_reserved_codes_are_rejected(self):
        encoded = self.encode()
        packed_file = self.directory / "packed" / "adapter.quantized"
        packed = packed_file.read_bytes()
        packed_file.write_bytes(packed[:-1] + bytes([packed[-1] ^ 1]))
        with self.assertRaises(ValueError):
            decode_checkpoint(
                self.directory / "packed",
                self.directory / "decoded",
                expected_codec_sha256=encoded["codec_manifest_sha256"],
                allowed_roots={"a" * 64},
                revoked_roots=set(),
            )
        layout = tensor_layout(self.state)
        for malformed in (
            packed[:-1],
            packed + b"x",
            b"wrong",
            MAGIC + struct.pack("<Q", 2**63),
        ):
            with self.subTest(payload=len(malformed)), self.assertRaises(ValueError):
                decode_tensors(malformed, expected_layout=layout)
        reserved = packed[:-1] + b"\x80"
        with self.assertRaises(ValueError):
            decode_tensors(reserved, expected_layout=layout)
        four, _ = encode_tensors({"odd": torch.ones((1, 1))}, 4)
        with self.assertRaises(ValueError):
            decode_tensors(
                four[:-1] + b"\xfe",
                expected_layout={"odd": {"shape": [1, 1], "dtype": "torch.float32"}},
            )

    def test_nonfinite_invalid_layout_and_precision_binding(self):
        invalid = [
            dict(a=torch.ones(1)),
            dict(a=torch.ones(1, 2).double()),
            dict(a=torch.zeros(0, 2)),
            dict(a=torch.tensor([[float("nan")]])),
        ]
        for state in invalid:
            with self.subTest(state=state), self.assertRaises(ValueError):
                encode_tensors(state, 8)
        packed, _ = encode_tensors(self.state, 8)
        bad_layout = copy.deepcopy(tensor_layout(self.state))
        bad_layout["layer.lora_A.weight"]["shape"] = [2**30, 2**30]
        with self.assertRaises(ValueError):
            decode_tensors(packed, expected_layout=bad_layout)
        with self.assertRaises(ValueError):
            decode_tensors(
                packed, expected_layout=tensor_layout(self.state), expected_bits=4
            )

    def test_resealed_manifest_cannot_underreport_decoded_bytes(self):
        self.encode()
        path = self.directory / "packed" / "codec.json"
        forged = json.loads(path.read_bytes())
        forged["metrics"]["decoded_tensor_bytes"] = 1
        payload = canonical_bytes(forged)
        path.write_bytes(payload)
        with self.assertRaises(ValueError):
            decode_checkpoint(
                self.directory / "packed",
                self.directory / "decoded",
                expected_codec_sha256=sha256(payload),
                allowed_roots={"a" * 64},
                revoked_roots=set(),
            )
        self.assertFalse((self.directory / "decoded").exists())

    def test_symlink_and_special_file_admission(self):
        if hasattr(os, "symlink"):
            real = self.parent / "adapter_model.safetensors"
            moved = self.parent / "original.safetensors"
            real.rename(moved)
            try:
                real.symlink_to(moved)
            except OSError:
                moved.rename(real)
            else:
                with self.assertRaises(ValueError):
                    self.encode()
                real.unlink()
                moved.rename(real)
        if hasattr(os, "mkfifo"):
            target = self.parent / "adapter_model.safetensors"
            target.unlink()
            os.mkfifo(target)
            with self.assertRaises(ValueError):
                self.encode()

    def test_exact_baselines_round_trip_complete_sources_and_account_bytes(self):
        records = [
            dict(
                scope="codec-test",
                entity=str(i),
                relation="color",
                value="red",
                source_digest="a" * 64,
            )
            for i in range(12)
        ]
        destination = self.directory / "baselines"
        receipt = measure_baselines(records, destination)
        self.assertEqual(
            json.loads((destination / "complete_records.json").read_bytes()), records
        )
        self.assertTrue(receipt["source_metadata_retained"])
        self.assertTrue(receipt["semantic_projection_omits_source_metadata"])
        for name, row in receipt["measurements"].items():
            self.assertEqual(
                row,
                dict(
                    bytes=(destination / name).stat().st_size,
                    sha256=sha256((destination / name).read_bytes()),
                    lossless=True,
                ),
            )
        self.assertFalse(receipt["compression_advantage_proven"])

    def test_heterogeneous_baseline_retains_original_records_without_projection(self):
        records = [
            dict(
                kind="semantic",
                entity="A",
                relation="color",
                value="red",
                source_digest="a" * 64,
            ),
            dict(
                kind="episode",
                entity="B",
                day=1,
                location="harbor",
                source_digest="b" * 64,
            ),
            dict(
                kind="procedure",
                rule="R",
                multiplier=2,
                offset=3,
                modulus=11,
                source_digest="c" * 64,
            ),
        ]
        destination = self.directory / "heterogeneous"
        receipt = measure_baselines(records, destination)
        self.assertEqual(
            json.loads((destination / "complete_records.json").read_bytes()), records
        )
        self.assertEqual(
            set(receipt["measurements"]),
            {
                "complete_records.json",
                "complete_records.zlib9",
                "complete_records.lzma6",
                "complete_records.sqlite3",
            },
        )
        self.assertFalse(receipt["semantic_projection_available"])
        self.assertFalse(receipt["semantic_projection_omits_source_metadata"])
        self.assertTrue(receipt["semantic_projection_unavailable_reason"])
        self.assertFalse(list(destination.glob("semantic_only.*")))
        self.assertTrue(receipt["source_metadata_retained"])


if __name__ == "__main__":
    unittest.main()

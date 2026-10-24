"""Strict JSON numeric admission with real, local CPU tensor bytes; no model."""

import json
import math
from pathlib import Path
import tempfile
import unittest

import torch
from safetensors.torch import save

from tensor_contract import read_candidate, sha256, strict_json, tensor_layout


class StrictJsonTests(unittest.TestCase):
    def test_float_overflow_is_rejected_at_every_nesting_depth(self):
        for token in ("1e999", "-1e999", "1E+999", "-1E+999", "1.8e308", "-1.8e308"):
            for template in (
                '{"value":%s}',
                '{"nested":{"value":%s}}',
                '{"array":[%s]}',
            ):
                payload = (template % token).encode()
                with (
                    self.subTest(payload=payload),
                    self.assertRaisesRegex(ValueError, "Out of range float"),
                ):
                    strict_json(payload)

    def test_finite_numbers_and_other_json_values_are_unchanged(self):
        payload = (
            b'{"numbers":[0,-0,1,-1,123456789012345678901234567890,'
            b"0.0,-0.0,1.5,-2.75,1e2,1.7976931348623157e308,"
            b"-1.7976931348623157e308,5e-324,-5e-324,1e-999,-1e-999],"
            b'"nested":{"null":null,"bools":[true,false],'
            b'"strings":["1e999","-1e999","NaN","Infinity"]}}'
        )
        actual = strict_json(payload)
        expected = json.loads(payload)
        self.assertEqual(actual, expected)
        self.assertEqual(
            [type(value) for value in actual["numbers"]],
            [type(value) for value in expected["numbers"]],
        )
        for value, original in zip(actual["numbers"], expected["numbers"]):
            if isinstance(value, float):
                self.assertTrue(math.isfinite(value))
                self.assertEqual(math.copysign(1, value), math.copysign(1, original))

    def test_existing_invalid_constants_duplicates_and_nonobjects_stay_rejected(self):
        for payload in (
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":-Infinity}',
            b'{"nested":[{"value":NaN}]}',
            b'{"value":1,"value":2}',
            b'{"nested":{"value":1,"value":2}}',
            b"[]",
            b"null",
            b"1.0",
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                strict_json(payload)


class CandidateJsonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.state = {"layer.lora_A.weight": torch.zeros((2, 2))}
        self.config = {"r": 2, "target_modules": ["q_proj"], "unknown": {"scale": 1.5}}
        config_bytes = json.dumps(self.config).encode()
        weights = save(self.state)
        self.manifest = {
            "schema": "hepta.memory-lora-candidate.v2",
            "base_identity": "a" * 64,
            "scope": "scope-a",
            "roots": ["1" * 64],
            "tensor_layout": tensor_layout(self.state),
            "adapter_sha256": sha256(weights),
            "config_sha256": sha256(config_bytes),
            # Unauthenticated caller metadata, not proof of training or authority.
            "training": {"loss": [0.0], "unverified_label": "1e999"},
            "model_install_authority": False,
            "production_accepted": False,
        }
        (self.directory / "adapter_config.json").write_bytes(config_bytes)
        (self.directory / "adapter_model.safetensors").write_bytes(weights)

    def read_manifest(self, payload):
        (self.directory / "lineage.json").write_bytes(payload)
        return read_candidate(
            self.directory,
            expected_manifest_sha256=sha256(payload),
            base_identity="a" * 64,
            scope="scope-a",
            expected_layout=tensor_layout(self.state),
            expected_config=self.config,
            allowed_roots={"1" * 64},
            revoked_roots=set(),
        )

    def test_manifest_overflow_is_rejected_before_returning_training_metadata(self):
        original = json.dumps(self.manifest).encode()
        for token in (b"1e999", b"-1e999"):
            payload = original.replace(b'"loss": [0.0]', b'"loss": [' + token + b"]")
            self.assertNotEqual(payload, original)
            with (
                self.subTest(token=token),
                self.assertRaisesRegex(ValueError, "Out of range float"),
            ):
                self.read_manifest(payload)

    def test_config_overflow_is_rejected(self):
        for token in (b"1e999", b"-1e999"):
            config = json.dumps(self.config).encode().replace(b"1.5", token)
            (self.directory / "adapter_config.json").write_bytes(config)
            self.manifest["config_sha256"] = sha256(config)
            with (
                self.subTest(token=token),
                self.assertRaisesRegex(ValueError, "Out of range float"),
            ):
                self.read_manifest(json.dumps(self.manifest).encode())

    def test_finite_candidate_preserves_manifest_roots_and_tensor_bytes(self):
        tensors, roots, manifest = self.read_manifest(
            json.dumps(self.manifest).encode()
        )
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(roots, frozenset(self.manifest["roots"]))
        self.assertEqual(save(tensors), save(self.state))


if __name__ == "__main__":
    unittest.main()

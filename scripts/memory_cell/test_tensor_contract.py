import json
import tempfile
import unittest
from pathlib import Path

import torch
from safetensors.torch import save

from tensor_contract import (
    canonical_config,
    read_candidate,
    sha256,
    tensor_layout,
    validate_tensor_bytes,
)


class TensorContractTests(unittest.TestCase):
    def test_exact_inventory_dtype_content_and_finiteness(self):
        tensors = {
            "layer.q_proj.lora_A.weight": torch.ones((2, 8)),
            "layer.q_proj.lora_B.weight": torch.zeros((8, 2)),
        }
        payload = save(tensors)
        layout = tensor_layout(tensors)
        restored = validate_tensor_bytes(
            payload, expected_sha256=sha256(payload), expected_layout=layout
        )
        self.assertEqual(set(restored), set(tensors))
        for key in restored:
            torch.testing.assert_close(restored[key], tensors[key])
        malformed = [
            payload[:-1],
            save({next(iter(tensors)): tensors[next(iter(tensors))]}),
            save({key: value.half() for key, value in tensors.items()}),
            save(
                {
                    key: torch.full_like(value, float("nan"))
                    for key, value in tensors.items()
                }
            ),
        ]
        for content in malformed:
            with self.assertRaises(Exception):
                validate_tensor_bytes(
                    content, expected_sha256=sha256(content), expected_layout=layout
                )
        with self.assertRaises(ValueError):
            validate_tensor_bytes(
                payload, expected_sha256="0" * 64, expected_layout=layout
            )

    def test_clean_reload_requires_external_binding_current_lineage_and_config(self):
        tensors = {"q.lora_A": torch.randn(4, 8), "q.lora_B": torch.randn(8, 4)}
        payload = save(tensors)
        config = {"r": 4, "lora_alpha": 8, "target_modules": ["q_proj"]}
        config_bytes = json.dumps(config).encode()
        layout = tensor_layout(tensors)
        manifest = {
            "schema": "hepta.memory-lora-candidate.v2",
            "base_identity": "base-A",
            "scope": "workspace-A",
            "roots": ["source-root"],
            "tensor_layout": layout,
            "adapter_sha256": sha256(payload),
            "config_sha256": sha256(config_bytes),
            "training": {},
            "model_install_authority": False,
            "production_accepted": False,
        }
        manifest_bytes = json.dumps(manifest).encode()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "lineage.json").write_bytes(manifest_bytes)
            (root / "adapter_config.json").write_bytes(config_bytes)
            (root / "adapter_model.safetensors").write_bytes(payload)
            kwargs = dict(
                expected_manifest_sha256=sha256(manifest_bytes),
                base_identity="base-A",
                scope="workspace-A",
                expected_layout=layout,
                expected_config=config,
                allowed_roots={"source-root"},
                revoked_roots=set(),
            )
            _, roots, _ = read_candidate(root, **kwargs)
            self.assertEqual(roots, {"source-root"})
            for change in [
                dict(scope="workspace-B"),
                dict(base_identity="base-B"),
                dict(allowed_roots=set()),
                dict(revoked_roots={"source-root"}),
                dict(expected_config={**config, "lora_alpha": 16}),
                dict(expected_manifest_sha256="0" * 64),
            ]:
                with self.assertRaises(ValueError):
                    read_candidate(root, **{**kwargs, **change})
            (root / "adapter_config.json").write_text('{"r":4,"r":8}')
            with self.assertRaises(ValueError):
                read_candidate(root, **kwargs)

    def test_only_declared_unordered_module_fields_and_locator_normalize(self):
        a = {
            "base_model_name_or_path": "/machine-A/base",
            "target_modules": {"q_proj", "v_proj"},
            "layers_to_transform": [1, 2],
        }
        b = {
            "base_model_name_or_path": "/machine-B/base",
            "target_modules": ["v_proj", "q_proj"],
            "layers_to_transform": [1, 2],
        }
        self.assertEqual(canonical_config(a), canonical_config(b))
        self.assertNotEqual(
            canonical_config(a), canonical_config({**b, "layers_to_transform": [2, 1]})
        )

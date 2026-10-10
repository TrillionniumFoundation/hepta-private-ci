"""Metadata + local byte checks: synthetic negative paths are not H2 evidence."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from hepta_neuron_model_trials import InvalidTrial, sha_file
from hepta_neuron_artifact_preflight import (
    _tensor_inventory,
    PUBLISHED_WEIGHTS,
    REPORT,
    REQUIRED,
    REVISION,
    inspect_local,
    match_manifest_catalog,
    verify_catalog,
)

LOCK = ROOT / "qualification/neuron-model-trials/upstream-weights.lock.json"


class ArtifactPreflightTests(unittest.TestCase):
    def test_publisher_catalog_is_commit_pinned_and_not_a_download_claim(self):
        obj = verify_catalog(json.loads(LOCK.read_text()))
        self.assertEqual(obj["revision"], REVISION)
        self.assertEqual(len(obj["variants"]), 3)
        self.assertTrue(len(sha_file(LOCK)) == 64)
        self.assertTrue(all(len(sha) == 64 for _, sha in PUBLISHED_WEIGHTS.values()))

    def test_rejects_mutated_upstream_sha_or_aliased_subfolder(self):
        original = json.loads(LOCK.read_text())
        bad = copy.deepcopy(original)
        bad["revision"] = "f" * 40
        with self.assertRaisesRegex(InvalidTrial, "frozen Laya family"):
            verify_catalog(bad)
        bad = copy.deepcopy(original)
        bad["variants"]["typed"]["subfolder"] = "multilingual"
        with self.assertRaisesRegex(InvalidTrial, "upstream bytes/path"):
            verify_catalog(bad)
        bad = copy.deepcopy(original)
        bad["variants"]["multilingual"]["weights_sha256"] = "f" * 64
        with self.assertRaisesRegex(InvalidTrial, "upstream bytes/path"):
            verify_catalog(bad)

    def test_manifest_requires_frozen_lock_hash_all_arms_and_real_tree_digest(self):
        catalog = json.loads(LOCK.read_text())
        manifest = {
            "family": "decisions",
            "upstream_lock_sha256": sha_file(LOCK),
            "models": {
                arm: {
                    "model_id": catalog["variants"][arm]["model_id"],
                    "revision": catalog["revision"],
                    "weights_sha256": catalog["variants"][arm]["weights_sha256"],
                    "artifact_tree_sha256": "b" * 64,
                }
                for arm in ("laya", "typed")
            },
        }
        self.assertTrue(match_manifest_catalog(manifest, catalog, sha_file(LOCK)))
        wrong = copy.deepcopy(manifest)
        wrong["models"]["typed"]["revision"] = "a" * 40
        with self.assertRaisesRegex(InvalidTrial, "publisher-locked"):
            match_manifest_catalog(wrong, catalog, sha_file(LOCK))
        wrong = copy.deepcopy(manifest)
        wrong["upstream_lock_sha256"] = "f" * 64
        with self.assertRaisesRegex(InvalidTrial, "upstream artifact lock"):
            match_manifest_catalog(wrong, catalog, sha_file(LOCK))
        wrong = copy.deepcopy(manifest)
        wrong["models"].pop("typed")
        with self.assertRaisesRegex(InvalidTrial, "arm set"):
            match_manifest_catalog(wrong, catalog, sha_file(LOCK))

    def test_missing_weight_configs_and_directory_symlinks_fail_closed(self):
        catalog = json.loads(LOCK.read_text())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(InvalidTrial, "incomplete"):
                inspect_local(catalog, "typed", root)
            (root / "model.safetensors").write_bytes(
                b"git-lfs pointer, NOT model weights"
            )
            for item in REQUIRED[1:]:
                path = root / item
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    '{"encoder":"answerdotai/ModernBERT-large","head_layers":2,"max_len":1024}',
                    encoding="utf-8",
                )
            (root / "tokenizer" / "alias").symlink_to(root / "model.safetensors")
            with self.assertRaisesRegex(InvalidTrial, "symlink"):
                inspect_local(catalog, "typed", root)
            (root / "tokenizer" / "alias").unlink()
            with self.assertRaisesRegex(InvalidTrial, "local model weights"):
                inspect_local(catalog, "typed", root)

    def test_safetensors_header_is_parsed_without_loading_model(self):
        try:
            from safetensors.torch import save_file
            import torch
        except ImportError:
            self.skipTest(
                "optional local safetensors/torch smoke dependencies unavailable"
            )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "small.safetensors"
            save_file({"matrix": torch.zeros(3, 7), "bias": torch.ones(7)}, str(path))
            count, keys = _tensor_inventory(path)
            self.assertEqual((count, keys), (28, 2))


if __name__ == "__main__":
    unittest.main()

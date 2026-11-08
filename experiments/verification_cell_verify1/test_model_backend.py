import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .model_backend import normalized_yes, pinned_assets
from .model_protocol import file_sha


class BackendBoundaryTests(unittest.TestCase):
    def test_candidate_probability_extremes_and_nonfinite(self):
        self.assertEqual(normalized_yes(-4, -4), 0.5)
        self.assertGreater(normalized_yes(-1, -1001), 0.999)
        self.assertLess(normalized_yes(-1001, -1), 0.001)
        for value in (True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                normalized_yes(value, -1)

    def test_missing_optional_asset_never_excuses_missing_required_or_unlisted_bytes(self):
        # Synthetic bytes exercise validation only; no MLX load or inference.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected, models = {}, []
            for key in ("qwen", "smol"):
                directory = root / key
                directory.mkdir()
                files = []
                for name in ("model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json"):
                    target = directory / name
                    target.write_bytes(b"validation fixture")
                    files.append({"filename": name, "status": "VERIFIED", "bytes": target.stat().st_size, "sha256": file_sha(target), "expected_lfs_sha256": None})
                files.append({"filename": "special_tokens_map.json", "status": "OPTIONAL_404", "http_status": 404})
                expected[key] = {"repo": key, "revision": "unit-only", "config_sha256": file_sha(directory / "config.json")}
                models.append({"repo_id": key, "revision": "unit-only", "directory": str(directory), "files": files})
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema": "hepta.verify1.model-preparation.v1", "status": "READY", "models": models}))
            with patch("experiments.verification_cell_verify1.model_backend.MODELS", expected):
                self.assertEqual(set(pinned_assets(manifest, file_sha(manifest))), {"qwen", "smol"})
                unlisted = root / "qwen" / "unregistered.py"
                unlisted.write_text("do not load")
                with self.assertRaises(ValueError):
                    pinned_assets(manifest, file_sha(manifest))
                unlisted.unlink()
                models[0]["files"][0].update(status="OPTIONAL_404", http_status=404)
                manifest.write_text(json.dumps({"schema": "hepta.verify1.model-preparation.v1", "status": "READY", "models": models}))
                with self.assertRaises(ValueError):
                    pinned_assets(manifest, file_sha(manifest))


if __name__ == "__main__":
    unittest.main()

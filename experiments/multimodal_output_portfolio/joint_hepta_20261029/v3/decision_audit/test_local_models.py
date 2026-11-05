"""Small file/metadata fixtures only; none is model execution evidence."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import acquire_models as acquisition
from .local_models import LocalModels


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.write_bytes(b"streamed fixture, not model weights\n")
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def test_streamed_download_and_verified_reuse(self):
        target = self.root / "copy"
        first = acquisition.download(self.source.as_uri(), target, self.source.stat().st_size, self.sha)
        with patch.object(acquisition.urllib.request, "urlopen", side_effect=AssertionError("unexpected download")):
            second = acquisition.download(self.source.as_uri(), target, first["size"], self.sha)
        self.assertEqual(first, second)
        self.assertEqual(target.read_bytes(), self.source.read_bytes())

    def test_wrong_hash_never_commits_target(self):
        target = self.root / "bad"
        with self.assertRaises(ValueError):
            acquisition.download(self.source.as_uri(), target, self.source.stat().st_size, "0" * 64)
        self.assertFalse(target.exists())

    def test_invalid_requests_do_not_load_models(self):
        backend = LocalModels(self.root, self.root)
        with patch.object(backend, "_activate", side_effect=AssertionError("model load")):
            for call in (lambda: LocalModels(self.root, self.root, threads=True),
                         lambda: backend.describe("absent", "", 80),
                         lambda: backend.draw("prompt", "absent", -1)):
                with self.assertRaises(ValueError):
                    call()

    def test_unloaded_identity_keeps_pins_without_verified_claims(self):
        with patch("importlib.metadata.version", return_value="unit-fixture"):
            result = LocalModels(self.root, self.root).identity()
        self.assertEqual(set(result["reviewed_model_pins"]), {"vlm", "sd"})
        self.assertEqual(result["models"], {})
        self.assertEqual(result["loads"], [])
        self.assertFalse(result["independent_semantic_scorer"])

    def test_incomplete_or_missing_weight_manifest_rejected(self):
        backend = LocalModels(self.root, self.root)
        for manifest in ({"complete": False}, {"complete": True, "model": acquisition.MODELS["vlm"][0],
                         "revision": acquisition.MODELS["vlm"][1], "files": []}):
            (self.root / "MANIFEST.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                backend._verify("vlm")

    def test_history_preserves_failed_cancelled_and_snapshot_attempts(self):
        with patch.object(acquisition, "resource_snapshot", return_value={"filesystem_free_bytes": 0}):
            with self.assertRaises(RuntimeError):
                acquisition.acquire(self.root)
        with patch.object(acquisition, "resource_snapshot", return_value={"filesystem_free_bytes": 10**12}):
            with patch.object(acquisition, "_json", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    acquisition.acquire(self.root)
            result = acquisition.acquire(self.root, preflight_only=True)
        rows = [json.loads(line) for line in (self.root / "ACQUISITION_ATTEMPTS.jsonl").read_text().splitlines()]
        finished = [row for row in rows if row["event"] == "finished"]
        self.assertEqual([row["status"] for row in finished], ["failed", "cancelled", "preflight_snapshot_passed"])
        self.assertEqual(len({row["attempt_id"] for row in finished}), 3)
        self.assertFalse(result["complete"])


if __name__ == "__main__":
    unittest.main()

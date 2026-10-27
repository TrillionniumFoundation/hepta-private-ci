"""Tiny hostile-download controls; these bytes are not model execution evidence."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_public_initial_v2 as material


class PublicInitialDownloadTests(unittest.TestCase):
    def test_unverified_content_never_publishes_a_material_manifest(self):
        expected = b"explicit controlled nonmodel input"
        runtime = SimpleNamespace(
            PUBLIC_FILES={
                "controlled.bin": (len(expected), hashlib.sha256(expected).hexdigest())
            },
            MODEL="controlled/unit-test",
            REVISION="fixed-unit-revision",
            save=lambda path, value: path.write_text(json.dumps(value)),
        )
        for returned in (expected[:-1], expected + b"!", b"x" * len(expected)):
            with self.subTest(returned=returned), tempfile.TemporaryDirectory() as root:
                target = Path(root) / "fresh"
                with patch.object(
                    material.urllib.request,
                    "urlopen",
                    return_value=io.BytesIO(returned),
                ):
                    with self.assertRaises(ValueError):
                        material.fetch_materials(runtime, target)
                self.assertFalse((target / "material-manifest.json").exists())

    def test_exact_pinned_bytes_publish_and_existing_directory_is_rejected(self):
        expected = b"explicit controlled nonmodel input"
        pin = hashlib.sha256(expected).hexdigest()
        runtime = SimpleNamespace(
            PUBLIC_FILES={"controlled.bin": (len(expected), pin)},
            MODEL="controlled/unit-test",
            REVISION="fixed-unit-revision",
            save=lambda path, value: path.write_text(json.dumps(value)),
        )
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "fresh"
            with patch.object(
                material.urllib.request, "urlopen", return_value=io.BytesIO(expected)
            ) as download:
                material.fetch_materials(runtime, target)
                self.assertEqual((target / "controlled.bin").read_bytes(), expected)
                self.assertEqual(
                    json.loads((target / "material-manifest.json").read_text()),
                    {
                        "files": {
                            "controlled.bin": {
                                "revision": "fixed-unit-revision",
                                "sha256": pin,
                                "size": len(expected),
                            }
                        },
                        "model": "controlled/unit-test",
                        "revision": "fixed-unit-revision",
                    },
                )
                with self.assertRaises(FileExistsError):
                    material.fetch_materials(runtime, target)
                self.assertEqual(download.call_count, 1)


if __name__ == "__main__":
    unittest.main()

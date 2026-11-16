"""Local container mechanics only; never reads an experiment or C panel."""

import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import export_run_v2 as exporter
import restore_run_v2 as restorer


class ArchiveToolTests(unittest.TestCase):
    def test_valid_small_zip_parts_reconstruct_exact_original_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "receipts.zip"
            payload = bytes(range(256)) * 4300
            with zipfile.ZipFile(
                original, "x", compression=zipfile.ZIP_STORED
            ) as archive:
                archive.writestr("run/example.dat", payload)
            parts = root / "parts"
            parts.mkdir()
            manifest = exporter.split_stream(original, parts)
            self.assertEqual(len(manifest["parts"]), 3)
            self.assertEqual(manifest["parts"][0]["bytes"], 491640)
            self.assertTrue(all(p["bytes"] < 512000 for p in manifest["parts"]))
            for part in manifest["parts"]:
                with zipfile.ZipFile(parts / part["file"]) as archive:
                    self.assertEqual(archive.namelist(), ["payload.bin"])
                    self.assertEqual(
                        archive.getinfo("payload.bin").compress_type, zipfile.ZIP_STORED
                    )
            restored = restorer.reconstruct_stream(
                parts, manifest, root / "rebuilt.zip"
            )
            self.assertEqual(restored.read_bytes(), original.read_bytes())
            inventory = [
                {
                    "path": "run/example.dat",
                    "archive": "receipts.zip",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "git_blob": hashlib.sha1(
                        b"blob " + str(len(payload)).encode() + b"\0" + payload
                    ).hexdigest(),
                }
            ]
            manifest["members"] = ["run/example.dat"]
            restorer.extract_stream(restored, manifest, inventory, root / "restored")
            self.assertEqual((root / "restored/run/example.dat").read_bytes(), payload)

    def test_changed_container_is_rejected_before_payload_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "checkpoints.zip"
            source.write_bytes(b"a bounded mechanical stream")
            parts = root / "parts"
            parts.mkdir()
            manifest = exporter.split_stream(source, parts)
            part = parts / manifest["parts"][0]["file"]
            with part.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "identity"):
                restorer.reconstruct_stream(parts, manifest, root / "restored.zip")

    def test_only_canonical_original_roots_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                restorer.bounded_path(root, "source/scripts/module.py"),
                root / "source/scripts/module.py",
            )
            for name in (
                "../outside",
                "run/../outside",
                "/run/file",
                "run/./file",
                "unknown/file",
                "run\\file",
            ):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    restorer.bounded_path(root, name)


if __name__ == "__main__":
    unittest.main()

"""Synthetic inventory admission; no tensor decoding or native execution."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from native_learned_probe import verify_export


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()+b"\n"


def member(root, name, data):
    (root/name).write_bytes(data)
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def seal(root, manifest):
    raw = encoded(manifest)
    (root/"manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fixture(root):
    # Small sentinels exercise inventory binding. Native tensor parsing has its
    # own focused tests; no learned parameters or real feature rows enter here.
    files = {"features.f770": member(root, "features.f770", b"synthetic feature payload")}
    heads, reference = [], {}
    for mode in ("linear", "gated", "residual"):
        for index in range(9):
            key = f"{mode}-{index}"
            name = key+".h770"
            record = member(root, name, ("synthetic "+key).encode())
            files[name] = record
            heads.append({"id": key, "path": name, "artifact_digest": record["sha256"]})
            reference[key] = {"synthetic": True}
    request = {"features": {"path": "features.f770",
        "artifact_digest": files["features.f770"]["sha256"]}, "heads": heads}
    files["request.json"] = member(root, "request.json", encoded(request))
    files["reference.json"] = member(root, "reference.json", encoded(reference))
    manifest = {"schema": "hepta.native-learned-export.v1", "heads": 27, "rows": 64,
        "files": files, "request_sha256": files["request.json"]["sha256"]}
    return manifest, request, reference, seal(root, manifest)


class NativeLearnedProbeTests(unittest.TestCase):
    def test_complete_synthetic_inventory_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            manifest, request, reference, expected = fixture(root)
            self.assertEqual(verify_export(root, expected), (manifest, request, reference))

    def test_oversized_manifest_is_rejected_before_any_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root/"manifest.json").write_bytes(b"x"*65537)
            with mock.patch("native_learned_probe.sha_file") as hashed:
                with self.assertRaisesRegex(ValueError, "bounded export manifest"):
                    verify_export(root, "1"*64)
                hashed.assert_not_called()

    def test_symlink_manifest_is_rejected_before_any_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root/"target.json"
            target.write_bytes(b"{}\n")
            try:
                (root/"manifest.json").symlink_to(target)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlink unavailable: {error}")
            with mock.patch("native_learned_probe.sha_file") as hashed:
                with self.assertRaisesRegex(ValueError, "bounded export manifest"):
                    verify_export(root, "1"*64)
                hashed.assert_not_called()

    def test_thirty_entries_cannot_substitute_an_unrelated_member(self):
        for removed in ("reference.json", "residual-8.h770"):
            with self.subTest(removed=removed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                manifest, _, _, _ = fixture(root)
                del manifest["files"][removed]
                (root/removed).unlink()
                manifest["files"]["unrelated.bin"] = member(root, "unrelated.bin", b"unrelated")
                expected = seal(root, manifest)
                self.assertEqual(len(manifest["files"]), 30)
                with self.assertRaisesRegex(ValueError, "inventory|coverage"):
                    verify_export(root, expected)


if __name__ == "__main__":
    unittest.main()

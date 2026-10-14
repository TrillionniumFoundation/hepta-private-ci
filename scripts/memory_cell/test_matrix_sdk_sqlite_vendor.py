"""Synthetic safe-crate tests; does not establish API compatibility."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from matrix_sdk_sqlite_vendor import candidate


MANIFEST = b'''[package]
name = "matrix-sdk-sqlite"
version = "0.19.0"
[dependencies.rusqlite]
version = "0.40.2"
features = ["modern_sqlite"]
[dependencies.matrix-sdk-crypto]
version = "0.19.0"
'''


def fixtures(manifest=MANIFEST, *, payload_path="matrix-sdk-sqlite-0.19.0/Cargo.toml"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        obj = tarfile.TarInfo(payload_path)
        obj.size = len(manifest)
        tar.addfile(obj, io.BytesIO(manifest))
    archive = buf.getvalue()
    registry = json.dumps({"version": {"num": "0.19.0",
                                      "checksum": hashlib.sha256(archive).hexdigest()}}).encode()
    return archive, registry


class VendorResearchTests(unittest.TestCase):
    def test_valid_published_candidate_changes_only_the_rusqlite_dependency(self):
        tar, meta = fixtures()
        with tempfile.TemporaryDirectory() as d:
            receipt = candidate(tar, meta, Path(d) / "candidate")
            text = (Path(d) / "candidate" / "Cargo.toml").read_text()
            self.assertIn('version = "0.39.0"', text)
            self.assertIn('version = "0.19.0"', text)
            self.assertTrue(receipt["upstream_crate_modified_for_research_only"])
            self.assertFalse(receipt["production_compatible"])
            self.assertNotEqual(receipt["original_manifest_sha256"],
                                receipt["experimental_manifest_sha256"])

    def test_different_registry_hash_does_not_write_candidate(self):
        raw, meta = fixtures()
        corrupted = json.loads(meta)
        corrupted["version"]["checksum"] = "f" * 64
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "target"
            with self.assertRaisesRegex(ValueError, "checksum"):
                candidate(raw, json.dumps(corrupted).encode(), root)
            self.assertFalse(root.exists())

    def test_unsafe_paths_are_rejected_before_extraction(self):
        for unsafe in ("matrix-sdk-sqlite-0.19.0/../../outside", "/etc/secret"):
            tar, meta = fixtures(payload_path=unsafe)
            with tempfile.TemporaryDirectory() as d:
                with self.subTest(path=unsafe), self.assertRaises(ValueError):
                    candidate(tar, meta, Path(d) / "unused")

    def test_wrong_package_version_or_dependency_fails_closed(self):
        for contents in (MANIFEST.replace(b"0.40.2", b"0.39.0"),
                         MANIFEST.replace(b"0.19.0", b"0.20.0")):
            raw, meta = fixtures(contents)
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    candidate(raw, meta, Path(d) / "target")

    def test_symlink_and_hardlink_crate_members_not_admitted(self):
        for type_ in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                link = tarfile.TarInfo("matrix-sdk-sqlite-0.19.0/Cargo.toml")
                link.type = type_
                link.linkname = "../unsafe"
                tar.addfile(link)
            raw = buf.getvalue()
            meta = json.dumps({"version": {"num": "0.19.0",
                         "checksum": hashlib.sha256(raw).hexdigest()}}).encode()
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    candidate(raw, meta, Path(d) / "target")

    def test_cannot_overwrite_preexisting_destination(self):
        raw, meta = fixtures()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "cannot be overwritten"):
                candidate(raw, meta, Path(d))


if __name__ == "__main__":
    unittest.main()

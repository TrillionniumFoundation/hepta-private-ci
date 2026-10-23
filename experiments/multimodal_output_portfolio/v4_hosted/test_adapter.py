"""Transport-only adversarial fixtures; no model or scientific run is executed."""

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from adapter import relative, restore


class InputTransportTests(unittest.TestCase):
    def fixture(self, root, name="native/tool", kind=stat.S_IFREG):
        payload = b"fixture bytes; never executed\n"
        archive = root / "fixture.zip"
        info = zipfile.ZipInfo(name)
        info.create_system, info.external_attr = 3, (kind | 0o755) << 16
        with zipfile.ZipFile(archive, "x") as stream:
            stream.writestr(info, payload)
        data = archive.read_bytes()
        (root / "part.bin").write_bytes(data)
        manifest = {"schema": "hepta.v4.hosted-inputs.v1", "zip": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "member_count": 1},
                    "total_uncompressed_bytes": len(payload), "files": [{"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "unix_mode": 0o755}],
                    "chunks": [{"path": "part.bin", "index": 0, "offset": 0, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}]}
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest))
        return path, payload

    def test_real_roundtrip_and_exclusive_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, payload = self.fixture(root)
            _, restored = restore(manifest, root / "restored")
            self.assertEqual((restored / "native/tool").read_bytes(), payload)
            self.assertEqual(stat.S_IMODE((restored / "native/tool").stat().st_mode), 0o755)
            with self.assertRaises(FileExistsError):
                restore(manifest, root / "restored")

    def test_hash_corruption_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = self.fixture(root)
            data = bytearray((root / "part.bin").read_bytes()); data[-1] ^= 1
            (root / "part.bin").write_bytes(data)
            with self.assertRaisesRegex(RuntimeError, "chunk byte"):
                restore(manifest, root / "restored")
            self.assertFalse((root / "restored/extracted").exists())

    def test_traversal_and_symlink_members_rejected(self):
        for name, kind in (("../escaped", stat.S_IFREG), ("native/link", stat.S_IFLNK)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest, _ = self.fixture(root, name, kind)
                with self.assertRaises(RuntimeError):
                    restore(manifest, root / "restored")
                self.assertFalse((root.parent / "escaped").exists())
        for name in ("/absolute", "C:/drive", "a\\b", "a//b"):
            with self.assertRaises(RuntimeError):
                relative(name)


if __name__ == "__main__":
    unittest.main()

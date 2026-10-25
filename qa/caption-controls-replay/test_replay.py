"""Synthetic negative tests; never reconstruct or substitute real inputs."""

import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import replay


class ArchiveBoundary(unittest.TestCase):
    def fixture(
        self,
        names=("safe.txt",),
        payload=b"fixed",
        mode=0,
        compression=zipfile.ZIP_STORED,
    ):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            for name in names:
                info = zipfile.ZipInfo(name)
                info.external_attr = mode << 16
                info.compress_type = compression
                z.writestr(info, payload)
        raw = stream.getvalue()
        spec = {
            "zip_bytes": len(raw),
            "zip_sha256": replay.digest(raw),
            "zip_members": {
                name: {"bytes": len(payload), "sha256": replay.digest(payload)}
                for name in names
            },
            "inputs_sha256": {names[0]: replay.digest(payload)},
        }
        return raw, spec

    def attempt(self, raw, spec):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "input.zip"
            archive.write_bytes(raw)
            replay.unpack(archive, root / "output", spec)
            return (root / "output/safe.txt").read_bytes()

    def test_positive(self):
        self.assertEqual(self.attempt(*self.fixture()), b"fixed")

    def test_wrong_size_before_parser(self):
        raw, spec = self.fixture()
        spec["zip_bytes"] += 1
        with patch.object(
            replay.zipfile, "ZipFile", side_effect=AssertionError("parser reached")
        ):
            with self.assertRaisesRegex(ValueError, "byte count"):
                self.attempt(raw, spec)

    def test_wrong_digest_before_parser(self):
        raw, spec = self.fixture()
        with patch.object(
            replay.zipfile, "ZipFile", side_effect=AssertionError("parser reached")
        ):
            with self.assertRaisesRegex(ValueError, "ZIP digest"):
                self.attempt(raw[:-1] + bytes([raw[-1] ^ 1]), spec)

    def test_paths(self):
        for name in ("../escape", "/absolute", "a/../b", "C:/escape", "a\\b", "./safe"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "unsafe path"),
            ):
                self.attempt(*self.fixture((name,)))

    def test_link(self):
        with self.assertRaisesRegex(ValueError, "nonregular"):
            self.attempt(*self.fixture(mode=stat.S_IFLNK | 0o777))

    def test_duplicate(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.attempt(*self.fixture(("safe.txt", "safe.txt")))

    def test_unexpected_member(self):
        raw, spec = self.fixture()
        spec["zip_members"] = {}
        with self.assertRaisesRegex(ValueError, "member set"):
            self.attempt(raw, spec)

    def test_wrong_member_hash(self):
        raw, spec = self.fixture()
        spec["zip_members"]["safe.txt"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "member digest"):
            self.attempt(raw, spec)

    def test_wrong_consumed_hash(self):
        raw, spec = self.fixture()
        spec["inputs_sha256"]["safe.txt"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "consumed input"):
            self.attempt(raw, spec)

    def test_oversize(self):
        with self.assertRaisesRegex(ValueError, "member size"):
            self.attempt(
                *self.fixture(
                    payload=b"x" * 8_000_001, compression=zipfile.ZIP_DEFLATED
                )
            )

    def test_crc(self):
        raw, spec = self.fixture()
        raw = raw.replace(b"fixed", b"badxx", 1)
        spec["zip_sha256"] = replay.digest(raw)
        with self.assertRaises(zipfile.BadZipFile):
            self.attempt(raw, spec)

    def test_method(self):
        with self.assertRaisesRegex(ValueError, "ZIP method"):
            self.attempt(*self.fixture(compression=zipfile.ZIP_BZIP2))

    def test_optimized_require_still_fails(self):
        with self.assertRaisesRegex(ValueError, "guard"):
            replay.require(False, "guard")


if __name__ == "__main__":
    unittest.main()

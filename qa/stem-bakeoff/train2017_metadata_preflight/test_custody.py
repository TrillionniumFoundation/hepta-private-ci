import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile
from bounded_json import PreflightError
import custody as p


class CustodyTests(unittest.TestCase):
    def test_bounded_pinned_file_rejects_hash_alias_and_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "source"
            file.write_bytes(b"original")
            digest = hashlib.sha256(b"original").hexdigest()
            with p.pinned_file(file, 8, digest) as stream:
                self.assertEqual(stream.read(), b"original")
            with self.assertRaises(PreflightError), p.pinned_file(file, 8, "0" * 64):
                pass
            alias = Path(tmp) / "alias"
            alias.symlink_to(file)
            with self.assertRaises(PreflightError), p.pinned_file(alias, 8, digest):
                pass
            alias.unlink()
            os.link(file, alias)
            with self.assertRaises(PreflightError), p.pinned_file(file, 8, digest):
                pass
            alias.unlink()
            with self.assertRaises(PreflightError), p.pinned_file(file, 8, digest):
                file.write_bytes(b"modified")
            for consumed in (0, 1, 8):
                file.write_bytes(b"original")
                unchanged_signature = p.signature(file.stat())
                with patch.object(p, "signature", return_value=unchanged_signature):
                    with self.assertRaisesRegex(PreflightError, "byte/hash pin"):
                        with p.pinned_file(file, 8, digest) as stream:
                            self.assertEqual(
                                stream.read(consumed), b"original"[:consumed]
                            )
                            file.write_bytes(b"modified")

            for changed in (b"short", b"expanded!"):
                file.write_bytes(b"original")
                unchanged_signature = p.signature(file.stat())
                with patch.object(p, "signature", return_value=unchanged_signature):
                    with (
                        self.assertRaises(PreflightError),
                        p.pinned_file(file, 8, digest),
                    ):
                        file.write_bytes(changed)

    def test_zip_member_sizes_hashes_duplicates_and_type(self):
        raw = b'{"info":{},"images":[]}'
        profile = (len(raw), len(raw), hashlib.sha256(raw).hexdigest(), len(raw))
        for failure in (None, "hash", "size", "duplicate", "symlink"):
            buffer = io.BytesIO()
            with warnings.catch_warnings(), zipfile.ZipFile(buffer, "w") as archive:
                warnings.simplefilter("ignore", UserWarning)
                entry = zipfile.ZipInfo("annotations/fixture.json")
                if failure == "symlink":
                    entry.external_attr = 0o120777 << 16
                archive.writestr(
                    entry, raw if failure != "hash" else raw.replace(b"info", b"inFo")
                )
                if failure == "duplicate":
                    archive.writestr(entry, raw)
            selected = profile if failure != "size" else (len(raw) + 1, *profile[1:])
            buffer.seek(0)
            with (
                patch.dict(p.MEMBERS, fixture=selected),
                zipfile.ZipFile(buffer) as archive,
            ):
                if failure:
                    with self.assertRaises(PreflightError):
                        list(p.member_records(archive, "fixture", {"images"}, {}))
                else:
                    receipts = {}
                    self.assertEqual(
                        list(
                            p.member_records(archive, "fixture", {"images"}, receipts)
                        ),
                        [],
                    )
                    self.assertEqual(receipts["fixture"]["sha256"], profile[2])


if __name__ == "__main__":
    unittest.main()

"""Byte-preservation and refusal tests; no research models or holdouts are run."""

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from create_chunks import INDEX_PATH, json_bytes, pack
from reassemble import digest, git_blob_digest, verify_or_restore


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source, self.parts, self.output = (self.root / p for p in ("source", "parts", "restored"))
        self.raw = {"evidence/a.tar.gz": bytes(range(256)) * 4001,
                    "evidence/SUMMARY.json": b'{"unchanged": true, "negative": -0.0}\n\n'}
        objects = []
        for name, raw in self.raw.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            objects.append({"logical_path": name, "bytes": len(raw), "sha256": digest(raw),
                            "source_git_blob_sha1": git_blob_digest(raw)})
        self.inventory = {"repository": "example/repo", "source_commit": "0" * 40, "objects": objects}
        self.index = pack(self.inventory, self.source, self.parts)
        self.index_path = self.parts / INDEX_PATH

    def tearDown(self):
        self.temporary.cleanup()

    def change_manifest(self, mutate):
        entry = self.index["objects"][0]
        path = self.parts / entry["manifest"]
        obj = json.loads(path.read_text())
        mutate(obj)
        raw = json_bytes(obj)
        path.write_bytes(raw)
        entry.update(manifest_bytes=len(raw), manifest_sha256=digest(raw))
        self.index_path.write_bytes(json_bytes(self.index))

    def test_roundtrip_preserves_binary_and_json_trailing_bytes(self):
        receipt = verify_or_restore(self.parts, self.index_path, self.output)
        self.assertEqual({p: (self.output / p).read_bytes() for p in self.raw}, self.raw)
        self.assertEqual(receipt["original_bytes"], sum(map(len, self.raw.values())))
        self.assertLessEqual(receipt["maximum_part_bytes"], 480000)
        self.assertEqual(receipt["maximum_decoded_part_bytes"], 479000)

    def test_corrupt_part_rejects_before_any_output(self):
        path = self.parts / "evidence/a.tar.gz.parts/00001.bin.gz"
        path.write_bytes(b"x" + path.read_bytes()[1:])
        with self.assertRaises(ValueError):
            verify_or_restore(self.parts, self.index_path, self.output)
        self.assertFalse(self.output.exists())

    def test_reordered_parts_are_rejected_even_with_updated_manifest_digest(self):
        self.change_manifest(lambda obj: obj["parts"].reverse())
        with self.assertRaises(ValueError):
            verify_or_restore(self.parts, self.index_path, self.output)
        self.assertFalse(self.output.exists())

    def test_escape_path_is_rejected_before_restore(self):
        self.change_manifest(lambda obj: obj["parts"][0].update(path="../outside.bin"))
        with self.assertRaises(ValueError):
            verify_or_restore(self.parts, self.index_path, self.output)
        self.assertFalse(self.output.exists())

    def test_original_sha_mismatch_is_rejected_before_restore(self):
        self.change_manifest(lambda obj: obj.update(sha256="0" * 64))
        with self.assertRaises(ValueError):
            verify_or_restore(self.parts, self.index_path, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            verify_or_restore(self.parts, self.index_path, self.output)
        self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_decoded_hash_mismatch_rejects_before_output(self):
        self.change_manifest(lambda obj: obj["parts"][0].update(decoded_sha256="0" * 64))
        with self.assertRaises(ValueError):
            verify_or_restore(self.parts, self.index_path, self.output)
        self.assertFalse(self.output.exists())

    def test_second_gzip_member_is_not_silently_accepted(self):
        def append_member(obj):
            part = obj["parts"][0]
            path = self.parts / part["path"]
            encoded = path.read_bytes() + gzip.compress(b"", mtime=0)
            path.write_bytes(encoded)
            part.update(encoded_bytes=len(encoded), encoded_sha256=digest(encoded),
                        git_blob_sha1=git_blob_digest(encoded))
        self.change_manifest(append_member)
        with self.assertRaises(ValueError):
            verify_or_restore(self.parts, self.index_path, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_pack_namespace_is_rejected(self):
        with self.assertRaises(FileExistsError):
            pack(self.inventory, self.source, self.parts)


if __name__ == "__main__":
    unittest.main()

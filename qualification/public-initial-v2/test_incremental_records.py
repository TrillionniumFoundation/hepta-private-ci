"""Small integrity/ownership controls for the offline records reader."""

from contextlib import ExitStack
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("incremental", HERE / "restore_incremental_records.py")
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class ReaderControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.payload = b"immutable evidence bytes"
        self.pack = self.directory / "records-000.pack"
        self.pack.write_bytes(self.payload)
        self.chunk = dict(pack=0, offset=0, bytes=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest())

    def bundle(self, chunk=None, expanded_adjustment=0):
        recipe = dict(chunks=[chunk or self.chunk], segments=[["new", 0]])
        raw = json.dumps(recipe).encode()
        compressed = gzip.compress(raw, mtime=0)
        (self.directory / "records.recipe.json.gz").write_bytes(compressed)
        return dict(
            unique_chunks=1, segments=1,
            packs=[dict(file=self.pack.name, bytes=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest())],
            recipe=dict(file="records.recipe.json.gz", bytes=len(compressed), expanded_bytes=len(raw) + expanded_adjustment, sha256=hashlib.sha256(compressed).hexdigest()),
        )

    def test_changed_pack_rejected_before_a_view_is_returned(self):
        manifest = self.bundle()
        self.pack.write_bytes(b"I" + self.payload[1:])
        with ExitStack() as stack, self.assertRaisesRegex(ValueError, "pack checksum"):
            READER.load_bundle(self.directory, manifest, stack)

    def test_chunk_cannot_read_past_verified_pack(self):
        manifest = self.bundle({**self.chunk, "offset": 1})
        with ExitStack() as stack, self.assertRaisesRegex(ValueError, "chunk extent"):
            READER.load_bundle(self.directory, manifest, stack)

    def test_recipe_expansion_is_read_with_its_declared_bound(self):
        manifest = self.bundle(expanded_adjustment=-2)
        with ExitStack() as stack, self.assertRaisesRegex(ValueError, "exact recipe expansion"):
            READER.load_bundle(self.directory, manifest, stack)

    def test_unknown_namespace_and_negative_chunk_are_rejected(self):
        bundles = {"new": (dict(chunks=[self.chunk]), [io.BytesIO(self.payload)])}
        for reference in (["other", 0], ["new", -1]):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                READER.OriginalZipView([reference], bundles, len(self.payload))

    def test_repeated_valid_chunks_cannot_expand_beyond_archive_pin(self):
        bundles = {"new": (dict(chunks=[self.chunk]), [io.BytesIO(self.payload)])}
        with self.assertRaisesRegex(ValueError, "stream expansion"):
            READER.OriginalZipView([["new", 0], ["new", 0]], bundles, len(self.payload))

    def test_changed_whole_archive_digest_cannot_return_success(self):
        directory = HERE / "controls-ci-001-60df5f93"
        real_read = READER.bounded_bytes

        def substituted_manifest(path, limit):
            raw = real_read(path, limit)
            if path == directory / "manifest.json":
                value = json.loads(raw)
                value["original_records_zip"]["sha256"] = "0" * 64
                return json.dumps(value).encode()
            return raw

        with mock.patch.object(READER, "bounded_bytes", side_effect=substituted_manifest):
            with self.assertRaisesRegex(ValueError, "bit-exact original ZIP"):
                READER.restore(directory, HERE / "ci-008-f75bf1ac")

    def test_existing_output_is_never_overwritten(self):
        destination = self.directory / "existing.zip"
        destination.write_bytes(self.payload)
        with self.assertRaises(FileExistsError):
            READER.restore(HERE / "controls-ci-001-60df5f93", HERE / "ci-008-f75bf1ac", destination)
        self.assertEqual(destination.read_bytes(), self.payload)


if __name__ == "__main__":
    unittest.main()

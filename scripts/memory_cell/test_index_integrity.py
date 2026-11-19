import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from index import PersistentIndex, index_digest
from native import Document


class IndexIntegrityTests(unittest.TestCase):
    def test_physical_fts_and_encoder_are_bound_on_reopen(self):
        docs = (Document("d", "root", "scope", "session", "2024", "real evidence"),)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite"
            blob = PersistentIndex.build(
                path, docs, np.ones((1, 4)), "encoder-A", "cut"
            )
            for digest, encoder in [("0" * 64, "encoder-A"), (blob, "encoder-B")]:
                with self.assertRaises(ValueError):
                    PersistentIndex(
                        path,
                        "cut",
                        set(),
                        expected_file_digest=digest,
                        expected_encoder=encoder,
                    )
            db = sqlite3.connect(path)
            db.execute("UPDATE lexical SET content='injected unrelated content'")
            db.commit()
            db.close()
            with self.assertRaises(ValueError):
                PersistentIndex(
                    path,
                    "cut",
                    set(),
                    expected_file_digest=blob,
                    expected_encoder="encoder-A",
                )
            # Even an independently admitted blob cannot relabel lexical content
            # as a projection of different source rows.
            with self.assertRaises(ValueError):
                PersistentIndex(
                    path,
                    "cut",
                    set(),
                    expected_file_digest=index_digest(path),
                    expected_encoder="encoder-A",
                )

    def test_duplicate_id_and_oversize_shape_cannot_create_a_valid_index(self):
        d = Document("d", "root", "scope", "session", "2024", "evidence")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite"
            with self.assertRaises(ValueError):
                PersistentIndex.build(path, (d, d), np.ones((2, 4)), "e", "c")
            self.assertFalse(path.exists())

    def test_digest_enforces_actual_read_bound_after_file_growth(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projection"
            path.write_bytes(b"x" * 64)
            with patch("index.MAX_INDEX_BYTES", 64):
                self.assertEqual(
                    index_digest(path), hashlib.sha256(b"x" * 64).hexdigest()
                )
            path.write_bytes(b"x" * 32)
            initial = path.stat()
            original_stat = Path.stat
            original_fstat = os.fstat
            grown = False

            def grow_after_metadata(info):
                nonlocal grown
                if not grown and (info.st_dev, info.st_ino) == (
                    initial.st_dev,
                    initial.st_ino,
                ):
                    grown = True
                    with path.open("ab") as stream:
                        stream.write(b"y" * 64)
                return info

            def path_metadata(candidate, *args, **kwargs):
                return grow_after_metadata(original_stat(candidate, *args, **kwargs))

            def descriptor_metadata(fd):
                return grow_after_metadata(original_fstat(fd))

            with (
                patch("index.MAX_INDEX_BYTES", 64),
                patch.object(Path, "stat", path_metadata),
                patch("os.fstat", descriptor_metadata),
            ):
                with self.assertRaisesRegex(ValueError, "index file byte limit"):
                    index_digest(path)
            self.assertTrue(grown)

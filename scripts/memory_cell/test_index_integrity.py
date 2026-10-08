import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from index import PersistentIndex, index_digest
from native import Document


class IndexIntegrityTests(unittest.TestCase):
    def test_physical_fts_and_encoder_are_bound_on_reopen(self):
        docs = (Document("d", "root", "scope", "session", "2024", "real evidence"),)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite"
            blob = PersistentIndex.build(path, docs, np.ones((1, 4)), "encoder-A", "cut")
            for digest, encoder in [("0" * 64, "encoder-A"), (blob, "encoder-B")]:
                with self.assertRaises(ValueError):
                    PersistentIndex(path, "cut", set(), expected_file_digest=digest, expected_encoder=encoder)
            db = sqlite3.connect(path)
            db.execute("UPDATE lexical SET content='injected unrelated content'")
            db.commit()
            db.close()
            with self.assertRaises(ValueError):
                PersistentIndex(path, "cut", set(), expected_file_digest=blob, expected_encoder="encoder-A")
            # Even an independently admitted blob cannot relabel lexical content
            # as a projection of different source rows.
            with self.assertRaises(ValueError):
                PersistentIndex(path, "cut", set(), expected_file_digest=index_digest(path), expected_encoder="encoder-A")

    def test_duplicate_id_and_oversize_shape_cannot_create_a_valid_index(self):
        d = Document("d", "root", "scope", "session", "2024", "evidence")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite"
            with self.assertRaises(ValueError):
                PersistentIndex.build(path, (d, d), np.ones((2, 4)), "e", "c")
            self.assertFalse(path.exists())

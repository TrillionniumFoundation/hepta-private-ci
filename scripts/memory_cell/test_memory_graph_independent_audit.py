"""Independent original-source reviewer negative contracts; no model inference."""
import os
import tempfile
import unittest
from pathlib import Path

from memory_graph_independent_audit import audit, strict, read
from memory_graph_source_trial import run, save_new, canonical
from test_memory_graph_source_trial import fixture


class IndependentAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prepared, self.public = fixture(self.root)
        self.run_dir = self.root / 'run'
        seal = run(self.public, self.run_dir)
        save_new(self.run_dir / 'seal.json', seal)

    def test_original_digest_rejects_authored_replacement(self):
        wrong = self.root / 'fake.json'
        wrong.write_bytes(canonical([]))
        with self.assertRaisesRegex(ValueError, 'original source hash mismatch'):
            audit(wrong, self.public, self.run_dir)

    def test_unknown_or_duplicate_json_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate original'):
            strict(b'{"x": 1, "x": 2}')
        with self.assertRaises(ValueError):
            strict(b'{"x": NaN}')

    def test_original_symlink_and_missing_source_denied(self):
        link = self.root / 'original-link.json'
        link.symlink_to(self.prepared / 'public.json')
        with self.assertRaisesRegex(ValueError, 'regular source-only file'):
            read(link)
        with self.assertRaisesRegex(ValueError, 'regular source-only file'):
            read(self.root / 'missing')

    def test_original_corpus_does_not_accept_authored_source_records(self):
        original = os.getenv('HEPTA_MEMORY_ORIGINAL')
        if not original:
            self.skipTest('optional exact original source not provided')
        with self.assertRaisesRegex(ValueError, 'unknown or duplicate original family'):
            audit(original, self.public, self.run_dir)

    def test_private_label_file_in_public_denied(self):
        original = os.getenv('HEPTA_MEMORY_ORIGINAL')
        if not original:
            self.skipTest('optional exact original source not provided')
        (self.public / 'private.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'public input includes private labels'):
            audit(original, self.public, self.run_dir)


if __name__ == '__main__':
    unittest.main()

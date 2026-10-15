"""Minimal filetree-level proof. This does not import the full Hepta ledger."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from e3_model_entry_resnapshot import ChangedDuringAudit,stable_again

class Replay(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.root=Path(self.t.name)
        (self.root/'inputs').mkdir(); (self.root/'images').mkdir()
        for name in ('source-seals.json','inputs/sources.jsonl','inputs/fit_labels.jsonl','inputs/cohort-before-labels.json'):
            p=self.root/name; p.write_bytes(b'{}\n')
        for i in range(192):
            (self.root/'images'/f'{i:064x}').write_bytes(f'pngbytes-{i}'.encode())
        self.first=[(p.relative_to(self.root).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest())
                    for p in self.root.rglob('*') if p.is_file()]
    def tearDown(self): self.t.cleanup()
    def test_unchanged(self): self.assertTrue(stable_again(self.root,self.first))
    def test_changed_receipt(self):
        (self.root/'source-seals.json').write_bytes(b'{"same":"semantics"}\n')
        with self.assertRaises(ChangedDuringAudit): stable_again(self.root,self.first)
    def test_late_added_test_labels(self):
        (self.root/'inputs/test_labels.jsonl').write_bytes(b'secret')
        with self.assertRaises(ChangedDuringAudit): stable_again(self.root,self.first)
    def test_removed_image(self):
        next((self.root/'images').iterdir()).unlink()
        with self.assertRaises(ChangedDuringAudit): stable_again(self.root,self.first)
    def test_symlink_substitution(self):
        p=self.root/'source-seals.json';p.unlink();p.symlink_to(self.root/'inputs/sources.jsonl')
        with self.assertRaises(ChangedDuringAudit): stable_again(self.root,self.first)
    def test_late_unregistered_folder(self):
        (self.root/'private_labels').mkdir()
        with self.assertRaises(ChangedDuringAudit): stable_again(self.root,self.first)

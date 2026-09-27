import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zlib

from scripts import hepta_memory_retrieval_apply_increment as guard

class IncrementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = 'codex-rs/hepta-memory-retrieval/src/reviewed.rs'
        self.source = self.root / self.path
        self.source.parent.mkdir(parents=True)
        self.source.write_text('pub const VALUE: u8 = 1;\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.head = self.git('rev-parse', 'HEAD').strip()
        before = self.git('hash-object', self.path).strip()
        self.source.write_text('pub const VALUE: u8 = 2;\n')
        after = self.git('hash-object', self.path).strip()
        self.patch = self.git('diff', '--full-index').encode()
        self.pin = hashlib.sha256(self.patch).hexdigest()
        self.data = {'schema': 'hepta.retrieval.authorized-patch.v1', 'ancestor': self.head,
            'sha256': self.pin, 'bytes': len(self.patch), 'files': [{'path': self.path, 'before': before, 'after': after}],
            'patch_zlib_base64': base64.b64encode(zlib.compress(self.patch)).decode()}
        self.git('restore', self.path)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True, stderr=subprocess.DEVNULL)

    def apply(self, data=None, head=None):
        return guard.apply(self.root, head or self.head, json.dumps(data or self.data).encode(), self.pin)

    def test_real_index_application_matches_expected_source(self):
        result = self.apply()
        self.assertEqual(self.source.read_text(), 'pub const VALUE: u8 = 2;\n')
        self.assertFalse(result['native_execution_proved'])
        self.assertEqual(result['result_tree'], self.git('write-tree').strip())

    def test_dirty_source_rejected(self):
        self.source.write_text('unreviewed\n')
        with self.assertRaises(guard.PatchError): self.apply()

    def test_untracked_source_rejected(self):
        (self.root / 'untracked').write_text('x')
        with self.assertRaises(guard.PatchError): self.apply()

    def test_wrong_head_rejected(self):
        with self.assertRaises(guard.PatchError): self.apply(head='a' * 40)

    def test_preimage_drift_rejected_without_modification(self):
        data = copy.deepcopy(self.data); data['files'][0]['before'] = 'a' * 40
        with self.assertRaises(guard.PatchError): self.apply(data)
        self.assertIn('= 1', self.source.read_text())

    def test_wrong_postimage_cannot_be_published(self):
        data = copy.deepcopy(self.data); data['files'][0]['after'] = 'a' * 40
        with self.assertRaises(guard.PatchError): self.apply(data)

    def test_inventory_substitution_rejected(self):
        data = copy.deepcopy(self.data); data['files'][0]['path'] = self.path.replace('reviewed', 'different')
        with self.assertRaises(guard.PatchError): self.apply(data)

    def test_paths_are_closed_to_owner_roots(self):
        for path in ['.github/workflows/unsafe.rs', '../unsafe.rs', self.path + '/../../x.rs', 'codex-rs/hepta-agentd/src/../x.rs', '/absolute.rs', 'codex-rs/hepta-agentd/src/x\\y.rs']:
            with self.subTest(path=path): self.assertFalse(guard.safe_path(path))

    def test_duplicate_path_and_unknown_field_rejected(self):
        data = copy.deepcopy(self.data); data['files'].append(data['files'][0])
        with self.assertRaises(guard.PatchError): self.apply(data)
        data = copy.deepcopy(self.data); data['force'] = True
        with self.assertRaises(guard.PatchError): self.apply(data)

    def test_duplicate_json_fields_rejected(self):
        with self.assertRaises(guard.PatchError): guard.decode(b'{"schema":1,"schema":2}', self.pin)

    def test_hash_size_boolean_and_trailing_compression_rejected(self):
        for field, value in [('sha256', '0' * 64), ('bytes', True), ('bytes', len(self.patch)+1), ('patch_zlib_base64', base64.b64encode(zlib.compress(self.patch)+b'trailing').decode())]:
            data=copy.deepcopy(self.data); data[field]=value
            with self.subTest(field=field), self.assertRaises(guard.PatchError): self.apply(data)

    def test_new_file_cannot_replace_an_existing_file(self):
        data=copy.deepcopy(self.data); data['files'][0]['before']=None
        with self.assertRaises(guard.PatchError): self.apply(data)

    def test_exact_patch_is_extractable_without_mutation(self):
        _, patch = guard.decode(json.dumps(self.data).encode(), self.pin)
        self.assertEqual(patch, self.patch)
        self.assertEqual(self.git('status', '--porcelain'), '')

if __name__ == '__main__': unittest.main()

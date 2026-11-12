"""Labelled synthetic archive/path controls; no model or training qualification."""
import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from checkpoint_replay import digest
from cpu_migration import SOURCE_COMMIT, assemble_parts, derive_cpu_plan, extract_verified, object_json, safe_member


class ArchiveAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = {'/study/source.py': b'original source\n', '/data/episode.json': b'{"y":[1,2]}\n'}

    def archive(self, change_index=None, extra=None, attributes=None):
        path = self.root / ('archive-' + str(len(list(self.root.glob('*.zip')))) + '.zip')
        index = {'schema': 'hcsn-six-real-checkpoint-export-v1', 'source_commit': SOURCE_COMMIT,
            'model_executions': 0, 'files': [{'original_path': name, 'member': 'root/' + name.lstrip('/'),
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in self.files.items()]}
        if change_index:
            change_index(index)
        with zipfile.ZipFile(path, 'w') as archive:
            for name, raw in self.files.items():
                member = 'root/' + name.lstrip('/')
                if attributes and member in attributes:
                    info = zipfile.ZipInfo(member)
                    info.external_attr = attributes[member] << 16
                    archive.writestr(info, raw)
                else:
                    archive.writestr(member, raw)
            archive.writestr('INDEX.json', json.dumps(index))
            if extra:
                archive.writestr(*extra)
        return path

    def extract(self, archive):
        return extract_verified(archive, self.root / 'extracted', digest(archive))

    def test_exact_synthetic_bytes_survive_relocation(self):
        index = self.extract(self.archive())
        self.assertEqual(len(index['files']), 2)
        for name, raw in self.files.items():
            self.assertEqual((self.root / 'extracted/root' / name.lstrip('/')).read_bytes(), raw)

    def test_wrong_archive_identity_fails_before_extraction(self):
        path = self.archive()
        with self.assertRaises(ValueError):
            extract_verified(path, self.root / 'extracted', {'bytes': path.stat().st_size, 'sha256': '0' * 64})
        self.assertFalse((self.root / 'extracted').exists())

    def test_traversal_and_alias_paths_are_rejected(self):
        for name in ('../escape', '/absolute', 'root/../escape', 'root//same', 'root/./same', 'root\\same'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_member(name)

    def test_unindexed_member_is_rejected(self):
        with self.assertRaises(ValueError):
            self.extract(self.archive(extra=('extra.bin', b'unindexed')))

    def test_duplicate_archive_member_is_rejected(self):
        with self.assertWarns(UserWarning):
            path = self.archive(extra=('root/study/source.py', b'other'))
        with self.assertRaises(ValueError):
            self.extract(path)

    def test_symlink_archive_member_is_rejected(self):
        path = self.archive(attributes={'root/study/source.py': stat.S_IFLNK | 0o777})
        with self.assertRaises(ValueError):
            self.extract(path)

    def test_index_hash_disagreement_is_rejected(self):
        path = self.archive(lambda index: index['files'][0].update(sha256='0' * 64))
        with self.assertRaises(ValueError):
            self.extract(path)

    def test_index_path_redirection_is_rejected(self):
        path = self.archive(lambda index: index['files'][0].update(member='root/data/episode.json'))
        with self.assertRaises(ValueError):
            self.extract(path)

    def test_duplicate_index_original_is_rejected(self):
        path = self.archive(lambda index: index['files'].append(copy.deepcopy(index['files'][0])))
        with self.assertRaises(ValueError):
            self.extract(path)

    def test_json_ambiguity_and_nonfinite_values_are_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"nested":{"a":1,"a":2}}', b'{"x":NaN}', b'{"x":1e999999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                object_json(raw)

    def test_ordered_parts_reconstruct_exact_archive_bytes(self):
        archive = self.archive()
        raw = archive.read_bytes()
        (self.root / 'part-0').write_bytes(raw[:37])
        (self.root / 'part-1').write_bytes(raw[37:])
        manifest = {'schema': 'hcsn-real-replay-export-parts-v1', 'archive': digest(archive),
            'parts': [{'path': 'part-0', **digest(self.root / 'part-0')},
                      {'path': 'part-1', **digest(self.root / 'part-1')}]}
        path = self.root / 'EXPORT.json'
        path.write_text(json.dumps(manifest))
        result = assemble_parts(path, self.root / 'assembled.zip', digest(archive))
        self.assertEqual(result.read_bytes(), raw)

    def test_part_traversal_is_rejected(self):
        expected = {'bytes': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}
        manifest = {'schema': 'hcsn-real-replay-export-parts-v1', 'archive': expected,
                    'parts': [{'path': '../outside', **expected}]}
        path = self.root / 'EXPORT.json'
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            assemble_parts(path, self.root / 'assembled.zip', expected)

    def test_part_hash_mutation_is_rejected(self):
        part = self.root / 'part-0'
        part.write_bytes(b'first')
        expected = digest(part)
        manifest = {'schema': 'hcsn-real-replay-export-parts-v1', 'archive': expected,
                    'parts': [{'path': 'part-0', **expected}]}
        path = self.root / 'EXPORT.json'
        path.write_text(json.dumps(manifest))
        part.write_bytes(b'other')
        with self.assertRaises(ValueError):
            assemble_parts(path, self.root / 'assembled.zip', expected)


class DerivedPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.extracted, self.torch_root = self.root / 'extracted', self.root / 'active-torch'
        self.entries = []
        def original(name, raw):
            member = 'root/' + name.lstrip('/')
            path = self.extracted / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.entries.append({'original_path': name, 'member': member, **digest(path)})
            return digest(path)
        self.source_hashes = {}
        for index in range(34):
            name = '/study/source-' + str(index) + '.py'
            self.source_hashes[name] = original(name, b'# synthetic source\n')['sha256']
        for relative in ('activation.py', 'container.py', 'linear.py'):
            name = '/old/lib/site-packages/torch/nn/modules/' + relative
            expected = original(name, b'# same synthetic Torch source\n')
            active = self.torch_root / 'nn/modules' / relative
            active.parent.mkdir(parents=True, exist_ok=True)
            active.write_bytes(b'# same synthetic Torch source\n')
            self.source_hashes[name] = expected['sha256']
        original('/prepared/data-manifest.json', b'{"confirmation_access":false}')
        self.native = {'schema': 'hcsn-real-checkpoint-replay-plan-v1', 'steps': 2,
            'confirmation_access': False, 'study_source': '/study', 'torch_version': '2.8.0+cu128',
            'torch_build': 'old', 'fits': []}
        self.selection = {'fits': []}
        for index in range(6):
            fit = 'fit-' + str(index)
            checkpoint = '/checkpoints/' + fit + '.pt'
            expected = original(checkpoint, b'opaque synthetic admission fixture')
            plan = '/plans/' + fit + '.json'
            original(plan, json.dumps({'prepared': '/prepared', 'manifest_sha256': 'unchanged', 'learning_rate': .001}).encode())
            self.native['fits'].append({'fit': fit, 'checkpoint': checkpoint, 'checkpoint_identity': expected,
                'expected_epoch': 10, 'expected_main_updates': 120, 'training_plan': plan,
                'inputs': {checkpoint: expected}, 'model_sources': self.source_hashes.copy()})
            self.selection['fits'].append({'fit': fit, 'identity': expected, 'epoch': 10, 'logical_main_updates': 120})
        self.runtime = {'torch_version': '2.8.0+cpu', 'torch_build': 'new', 'cuda_build': None,
                        'executable': '/new/python'}

    def derive(self):
        return derive_cpu_plan(self.native, {'files': self.entries}, self.extracted,
            self.root / 'derived', [], self.torch_root, self.runtime, self.selection)

    def test_only_prepared_location_changes_and_source_bytes_are_retained(self):
        plan = self.derive()
        self.assertEqual(plan['torch_version'], '2.8.0+cpu')
        self.assertEqual(plan['profile_amendment']['original_native_optimizer_steps'], 'UNKNOWN')
        self.assertFalse(plan['profile_amendment']['inherits_original_cuda_qualification'])
        for entry in plan['fits']:
            training = object_json(Path(entry['training_plan']).read_bytes())
            self.assertEqual(training, {'prepared': str(self.extracted / 'root/prepared'),
                'manifest_sha256': 'unchanged', 'learning_rate': .001})
            self.assertEqual(len(entry['model_sources']), 37)
            self.assertEqual(digest(entry['checkpoint']), entry['checkpoint_identity'])

    def test_changed_cpu_torch_source_is_rejected(self):
        (self.torch_root / 'nn/modules/linear.py').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.derive()

    def test_wrong_checkpoint_selection_is_rejected(self):
        self.selection['fits'][0]['epoch'] = 11
        with self.assertRaises(ValueError):
            self.derive()

    def test_unbound_prepared_path_is_rejected(self):
        path = self.extracted / 'root/plans/fit-0.json'
        path.write_text(json.dumps({'prepared': '/other', 'manifest_sha256': 'unchanged'}))
        next(item for item in self.entries if item['original_path'] == '/plans/fit-0.json').update(digest(path))
        with self.assertRaises(ValueError):
            self.derive()

    def test_cuda_profile_cannot_be_silently_reused(self):
        self.runtime['torch_version'] = '2.8.0+cu128'
        with self.assertRaises(ValueError):
            self.derive()


if __name__ == '__main__':
    unittest.main()

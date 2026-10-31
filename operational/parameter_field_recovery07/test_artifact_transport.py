"""Small synthetic corruption tests; no credentials, SDK calls or scientific files."""

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from artifact_transport import descriptor, logical_path, measured_client, readback, snapshot, validate_binding, write_json


class ArchiveBoundaryTests(unittest.TestCase):
    def fixture(self, directory):
        source, staged, returned = [directory / x for x in ('source', 'upload', 'readback')]
        source.mkdir(); staged.mkdir(); returned.mkdir()
        original = source / 'packet.bin'
        original.write_bytes(b'closed synthetic bytes\x00' * 20)
        item = {'path': 'nested/packet.bin', **snapshot(original, staged / 'payload/nested/packet.bin')}
        manifest = {'files': [item]}
        write_json(staged / 'MANIFEST.json', manifest)
        return original, staged, returned, manifest

    def zip_fixture(self, path, staged, corrupt=False, duplicate=False):
        with zipfile.ZipFile(path, 'w') as archive:
            archive.write(staged / 'MANIFEST.json', 'MANIFEST.json')
            archive.writestr('payload/nested/packet.bin', b'corrupted' if corrupt else (staged / 'payload/nested/packet.bin').read_bytes())
            if duplicate:
                archive.writestr('MANIFEST.json', (staged / 'MANIFEST.json').read_bytes())

    def test_literal_bytes_and_three_distinct_inodes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original, staged, returned, manifest = self.fixture(root)
            archive = root / 'packet.zip'
            self.zip_fixture(archive, staged)
            proof = readback(archive, staged, returned, manifest, {'nested/packet.bin': original})
            self.assertEqual(proof[0]['path'], 'nested/packet.bin')
            self.assertEqual(len({tuple(proof[0][x]) for x in ['source_device_inode', 'staged_device_inode', 'readback_device_inode']}), 3)
            self.assertEqual(descriptor(original)['sha256'], descriptor(returned / 'payload/nested/packet.bin')['sha256'])

    def test_corruption_and_duplicate_members_rejected(self):
        for corrupt, duplicate in ((True, False), (False, True)):
            with self.subTest(corrupt=corrupt, duplicate=duplicate), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                original, staged, returned, manifest = self.fixture(root)
                archive = root / 'packet.zip'
                self.zip_fixture(archive, staged, corrupt, duplicate)
                with self.assertRaises(ValueError):
                    readback(archive, staged, returned, manifest, {'nested/packet.bin': original})

    def test_unsafe_paths_and_symlink_source_rejected(self):
        for value in ('../escape', '/absolute', 'a/../b', '.env', 'a/.git/config', 'x\\y', 'a//b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                logical_path(value)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / 'data'
            original.write_text('synthetic')
            link = root / 'link'
            link.symlink_to(original)
            with self.assertRaises(ValueError):
                snapshot(link, root / 'copy')

    def test_changed_original_and_zip_links_rejected(self):
        for changed, symlink in ((True, False), (False, True)):
            with self.subTest(changed=changed, symlink=symlink), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                original, staged, returned, manifest = self.fixture(root)
                archive = root / 'packet.zip'
                if symlink:
                    with zipfile.ZipFile(archive, 'w') as stream:
                        stream.write(staged / 'MANIFEST.json', 'MANIFEST.json')
                        member = zipfile.ZipInfo('payload/nested/packet.bin')
                        member.external_attr = 0o120777 << 16
                        stream.writestr(member, str(original))
                else:
                    self.zip_fixture(archive, staged)
                    original.write_bytes(b'changed after archive')
                with self.assertRaises(ValueError):
                    readback(archive, staged, returned, manifest, {'nested/packet.bin': original})

    def test_binding_requires_literal_config_and_previous_sequence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / 'config.json', {'synthetic': True})
            binding = {'execution_episode': 'execution07_actions_20261031', 'sequence': 1,
                       'label': 'A-17', 'pipeline_config': descriptor(root / 'config.json'),
                       'completed_jobs': ['A-17'], 'previous_ack': None}
            identity = {'repository': 'synthetic/repository', 'run_id': '123', 'run_attempt': '1',
                        'head_sha': '0' * 40, 'job': 'synthetic'}
            validate_binding('A-17', binding)
            write_json(root / 'ack.json', {'schema': 'hepta.github-actions-archive-ack.v1', 'binding': binding, 'identity': identity})
            second = {**binding, 'sequence': 2, 'label': 'A-29', 'completed_jobs': ['A-17', 'A-29'],
                      'previous_ack': descriptor(root / 'ack.json')}
            validate_binding('A-29', second, identity=identity)
            with self.assertRaises(ValueError):
                validate_binding('A-29', second, identity={**identity, 'run_id': '456'})
            with self.assertRaises(ValueError):
                validate_binding('A-17', {**binding, 'completed_jobs': []})
            with self.assertRaises(ValueError):
                validate_binding('A-43', {**second, 'sequence': 3, 'label': 'A-43',
                                        'completed_jobs': ['A-17', 'A-29', 'A-43']}, identity=identity)
            (root / 'config.json').write_text('changed')
            with self.assertRaises(ValueError):
                validate_binding('A-17', binding)

    def test_health_abort_reaps_and_measures_the_actual_owned_child(self):
        calls = 0

        def health():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise InterruptedError('synthetic health stop')

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(InterruptedError):
                measured_client('upload', {'operation': 'upload'}, root, health)
            receipt = json.loads((root / 'upload.wait4.json').read_text())
            self.assertEqual(receipt['pid'], receipt['waited_pid'])
            self.assertEqual(receipt['interruption_type'], 'InterruptedError')
            self.assertNotEqual(receipt['exit_code'], 0)
            self.assertGreaterEqual(receipt['user_cpu_seconds'] + receipt['system_cpu_seconds'], 0)


if __name__ == '__main__':
    unittest.main()

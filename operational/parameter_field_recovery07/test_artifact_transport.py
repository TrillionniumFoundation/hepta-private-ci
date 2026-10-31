"""Small synthetic corruption tests; no credentials, SDK calls or scientific files."""

import json
import fcntl
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import artifact_transport
from artifact_transport import RAW_LOCKS, descriptor, logical_path, measured_client, readback, snapshot, validate_binding, write_json


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
        for value in ('../escape', '/absolute', 'a/../b', '.env', 'a/.git/config', 'x\\y', 'a//b',
                      'raw/.hidden', 'raw/.ops-custom.lock', 'raw/sub/.ops-controller.lock',
                      'synthetic/raw/sub/.ops-phase.lock', 'payload/raw/.ops-controller.lock',
                      'raw/.git/.ops-controller.lock', 'raw/.env'):
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

    def test_original_closed_raw_locks_preserved_with_independent_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw, staged, returned = [root / name for name in ('raw', 'upload', 'readback')]
            raw.mkdir(); staged.mkdir(); returned.mkdir()
            files, sources = [], {}
            for name in sorted(RAW_LOCKS):
                source = raw / name
                source.write_bytes(b'')
                relative = 'raw/' + name
                logical_path(relative)
                logical_path('synthetic/' + relative)
                item = {'path': relative, **snapshot(source, staged / 'payload' / relative, raw_root=raw)}
                files.append(item); sources[relative] = source
            manifest = {'files': files}
            write_json(staged / 'MANIFEST.json', manifest)
            archive = root / 'packet.zip'
            with zipfile.ZipFile(archive, 'w') as stream:
                stream.write(staged / 'MANIFEST.json', 'MANIFEST.json')
                for item in files:
                    stream.write(staged / 'payload' / item['path'], 'payload/' + item['path'])
            proof = readback(archive, staged, returned, manifest, sources)
            self.assertEqual(len(proof), 5)
            self.assertTrue(all(item['bytes'] == 0 for item in files))
            source = raw / '.ops-controller.lock'
            with self.assertRaises(ValueError):
                snapshot(source, root / 'unbound')
            with self.assertRaises(ValueError):
                snapshot(source, root / 'wrong-root', raw_root=staged)
            with source.open('rb') as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    snapshot(source, root / 'held-copy', raw_root=raw)

    def test_full_archive_keeps_raw_inputs_and_download_destination_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw, output, server = root / 'raw', root / 'attempt', root / 'synthetic-server.zip'
            raw.mkdir()
            paths = {}
            for name in sorted(RAW_LOCKS) + ['last-payload.bin']:
                source = raw / name
                source.write_bytes(b'' if name in RAW_LOCKS else b'synthetic payload')
                paths['raw/' + name] = source
            config = root / 'SYNTHETIC_CONFIG.json'
            write_json(config, {'synthetic_only': True, 'raw_root': str(raw)})
            binding = {'execution_episode': 'execution07_actions_20261031', 'sequence': 1,
                       'label': 'A-17', 'pipeline_config': descriptor(config),
                       'completed_jobs': ['A-17'], 'previous_ack': None}

            def sdk_fixture(operation, request, directory, health_check=None):
                cost = {'operation': operation, 'user_cpu_seconds': 0.0, 'system_cpu_seconds': 0.0,
                        'peak_rss_bytes': 0, 'measurement': 'OFFLINE UNIT STUB, not a measured provider process'}
                if operation == 'upload':
                    with zipfile.ZipFile(server, 'w') as archive:
                        for source in request['files']:
                            archive.write(source, Path(source).relative_to(request['root']).as_posix())
                    item = descriptor(server)
                    return {'id': 1, 'name': request['name'], 'bytes': item['bytes'],
                            'sha256': item['sha256'], 'sdk': 'OFFLINE UNIT STUB'}, cost
                self.assertEqual(Path(request['destination']), output / 'download_raw')
                shutil.copyfile(server, Path(request['destination']) / 'returned.zip')
                return {'id': request['id'], 'expected_sha256': request['sha256'],
                        'digest_mismatch': False, 'raw_archive': True, 'sdk': 'OFFLINE UNIT STUB'}, cost

            identity = {'GITHUB_REPOSITORY': 'synthetic/fixture', 'GITHUB_RUN_ID': '1',
                        'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': '0' * 40, 'GITHUB_JOB': 'fixture',
                        'ACTIONS_RUNTIME_TOKEN': 'not-a-credential-synthetic-only',
                        'ACTIONS_RESULTS_URL': 'https://example.invalid'}
            with patch.dict(os.environ, identity), patch.object(artifact_transport, 'measured_client', sdk_fixture):
                result = artifact_transport.archive_barrier('A-17', paths, binding, output)
            self.assertEqual(result['items_verified'], 6)
            self.assertEqual(set(p.name for p in raw.iterdir()), set(RAW_LOCKS) | {'last-payload.bin'})
            self.assertTrue((output / 'download_raw/returned.zip').is_file())
            self.assertTrue((output / 'readback/payload/raw/.ops-controller.lock').is_file())

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

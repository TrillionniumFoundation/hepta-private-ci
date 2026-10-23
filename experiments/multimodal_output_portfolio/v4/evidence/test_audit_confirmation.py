"""Actual Git-blob and artifact corruption tests for the independent auditor."""

import hashlib
import json
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

from audit_confirmation import digest, relative_path, verify_artifacts, verify_source_bytes, verify_storage


class ConfirmationAuditTests(unittest.TestCase):
    def test_artifact_inventory_bytes_and_hash_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / 'payload.bin').write_bytes(b'actual retained evidence')
            manifest = {'payload.bin': {'bytes': 24, 'sha256': digest(path / 'payload.bin')}}
            (path / 'artifacts.json').write_text(json.dumps(manifest))
            receipt = {'artifact_manifest_sha256': digest(path / 'artifacts.json'), 'artifact_payload_bytes': 24}
            self.assertEqual(verify_artifacts(path, receipt)['files_verified'], 1)
            (path / 'payload.bin').write_bytes(b'changed retained evidence')
            with self.assertRaises(AssertionError):
                verify_artifacts(path, receipt)
            (path / 'payload.bin').write_bytes(b'actual retained evidence')
            (path / 'omitted.bin').write_bytes(b'not in declared inventory')
            with self.assertRaises(AssertionError):
                verify_artifacts(path, receipt)

    def test_committed_blob_and_sha256_both_bind_source(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)

            def git(*arguments):
                return subprocess.check_output(['git', *arguments], cwd=path, stderr=subprocess.PIPE).decode().strip()

            git('init', '--quiet')
            source = path / 'model.py'
            original = b'print("frozen implementation")\n'
            source.write_bytes(original)
            git('add', 'model.py')
            git('-c', 'user.name=Audit fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '--quiet', '-m', 'local provenance fixture')
            commit, blob = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD:model.py')
            manifest = {'implementation_commit': commit, 'git_object_format': 'sha1',
                'source_sha256': {'model.py': hashlib.sha256(original).hexdigest()},
                'committed_blob_sha1': {'model.py': blob}, 'local_blob_sha1': {'model.py': blob},
                'all_source_bytes_committed': True, 'development_dirty_files': []}
            report, bound = verify_source_bytes(path, path / 'run', manifest, False)
            self.assertEqual(bound['model.py'], original)
            self.assertEqual(report['current_development_source_drift'], [])
            source.write_bytes(b'print("changed after execution")\n')
            with self.assertRaises(AssertionError):
                verify_source_bytes(path, path / 'run', manifest, False)
            report, bound = verify_source_bytes(path, path / 'run', manifest, True)
            self.assertEqual(report['current_development_source_drift'], ['model.py'])
            self.assertEqual(bound['model.py'], original)
            manifest['local_blob_sha1']['model.py'] = '1' * 40
            with self.assertRaises(AssertionError):
                verify_source_bytes(path, path / 'run', manifest, True)

    def test_relative_evidence_paths_cannot_escape_or_normalize_away(self):
        for value in ('../escape', '/absolute', 'safe/../escape', 'safe//file', './file', ''):
            with self.subTest(path=value), self.assertRaises(AssertionError):
                relative_path(value)
        self.assertEqual(str(relative_path('seed-17/dynamic/scores.npz')), 'seed-17/dynamic/scores.npz')

    def test_storage_cannot_double_count_one_filesystem_or_drop_archive_reservation(self):
        protocol = json.loads((Path(__file__).parents[1] / 'protocol.json').read_text())
        payload, total = 803785728, 1741789184
        required = total // 2
        split = {'uncompressed_payload_estimate_bytes': payload,
                 'required_free_bytes_with_archive_headroom': total,
                 'total_required_unique_filesystem_bytes': total, 'free_bytes_at_start': required,
                 'strategy': 'split-filesystems', 'distinct_filesystems': True,
                 'archive_headroom_requested': True, 'passed': True,
                 'output': {'directory': '/memory/run', 'st_dev': 11, 'free_bytes': required, 'required_free_bytes': required},
                 'archive': {'directory': '/disk', 'st_dev': 22, 'free_bytes': required,
                             'required_free_bytes': required, 'required_is_shared_with_output': False}}
        self.assertEqual(verify_storage(split, protocol, False)['payload_estimate_bytes'], payload)
        for tamper in ('same_device', 'archive_short', 'lower_total'):
            changed = copy.deepcopy(split)
            if tamper == 'same_device':
                changed['archive']['st_dev'] = 11
            elif tamper == 'archive_short':
                changed['archive']['free_bytes'] -= 1
            else:
                changed['total_required_unique_filesystem_bytes'] -= 1
            with self.subTest(tamper=tamper), self.assertRaises(AssertionError):
                verify_storage(changed, protocol, False)
        shared = copy.deepcopy(split)
        shared.update(strategy='shared-filesystem', distinct_filesystems=False, free_bytes_at_start=total)
        for item in (shared['output'], shared['archive']):
            item.update(st_dev=11, free_bytes=total, required_free_bytes=total)
        shared['archive']['required_is_shared_with_output'] = True
        self.assertTrue(verify_storage(shared, protocol, False)['passed_at_recorded_start'])
        shared['archive']['free_bytes'] = total - 1
        with self.assertRaises(AssertionError):
            verify_storage(shared, protocol, False)


if __name__ == '__main__':
    unittest.main()

"""Synthetic CAS manifest/literal tests; no scientific artifact is accessed."""

import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import finalize_v2 as finalizer
from . import resource_v2 as resource
from .test_resource_v2 import registration


class FinalizeTests(unittest.TestCase):
    def setUp(self):
        directory = Path('/dev/shm/hepta-field-fullstudy-20261029/temporary')
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.root = Path(self.temp.name) / 'raw'
        self.storage = resource.StorageBudget(self.root, registration(self.root))
        self.patches = [patch.object(module, 'memory_admission', return_value={'allowed': True})
                        for module in (resource, finalizer)]
        for context in self.patches:
            context.start()

    def tearDown(self):
        for context in reversed(self.patches):
            context.stop()
        self.temp.cleanup()

    def test_all_logical_paths_failures_and_duplicate_bytes_are_restored(self):
        first = self.root / 'negative-looking-name.bin'
        second = self.root / 'positive-looking-name.bin'
        first.write_bytes(b'opaque-synthetic-bytes' * 4000)
        second.write_bytes(first.read_bytes())
        (self.root / 'FAILED.json').write_text('{"complete":false,"synthetic":true}')
        record = finalizer.finalize(self.storage, {'synthetic': True})
        self.assertTrue(record['archive_verification_complete'])
        self.assertFalse(record['scientific_completion_inferred'])
        self.assertEqual(first.stat().st_ino, second.stat().st_ino)
        manifest = json.loads((self.root / record['manifest']['path']).read_text())
        names = set(manifest['logical_paths'])
        self.assertTrue({'negative-looking-name.bin', 'positive-looking-name.bin', 'FAILED.json'} <= names)
        self.assertEqual(set(record['logical_paths_verified']), names)
        self.assertEqual(record['logical_bytes_restored'], sum(x['bytes'] for x in manifest['logical_paths'].values()))
        self.assertFalse(any(self.storage.cas_root.glob('literal-verify-*')))
        self.assertTrue((self.root / 'FAILED.json').exists())

    def test_corruption_is_not_silently_accepted_and_originals_remain(self):
        artifact = self.root / 'artifact.bin'
        artifact.write_bytes(b'abc' * 1000)
        self.storage.deduplicate_closed(artifact)
        entries = finalizer.snapshot(self.storage, self.root / 'unused')
        artifact.write_bytes(b'corrupted')
        with self.assertRaises(ValueError) as caught:
            finalizer.verify_logical_paths(self.storage, entries)
        progress = caught.exception.verification_progress
        self.assertEqual(progress["current_logical_path"], "artifact.bin")
        self.assertEqual(progress["current_partial_bytes"], len(b"corrupted"))
        self.assertGreaterEqual(progress["physical_verification_bytes_written"], len(b"corrupted"))
        self.assertTrue(Path(progress["temporary_failure_directory"]).is_dir())
        self.assertTrue(artifact.exists())
        self.assertTrue(any(self.storage.cas_root.glob('literal-verify-*')))

    def test_symlinks_and_concurrent_worker_claim_are_rejected(self):
        (self.root / 'artifact').write_bytes(b'synthetic')
        (self.root / 'alias').symlink_to(self.root / 'artifact')
        with self.assertRaises(ValueError):
            finalizer.snapshot(self.storage, self.root / 'unused')
        (self.root / 'alias').unlink()
        import os
        (self.root / 'ACTIVE_WORKERS.json').write_text(json.dumps({'workers': [{'pid': os.getpid()}]}))
        with self.assertRaises(ValueError):
            finalizer.finalize(self.storage, {'synthetic': True})


    def test_controller_lock_rejects_before_creating_verification_artifacts(self):
        with resource.RAW_OPEN(self.root / '.ops-controller.lock', 'a+b') as active:
            fcntl.flock(active.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'stopped controller'):
                finalizer.finalize(self.storage, {'synthetic': True})
        self.assertFalse((self.root / 'evidence_v2').exists())

    def test_partial_copy_failure_records_exact_progress_and_retains_residue(self):
        (self.root / 'a_good.bin').write_bytes(b'12345')
        (self.root / 'z_large.bin').write_bytes(b'x' * (2 * resource.MiB + 7))
        original_check = finalizer._temporary_check
        calls = [0]
        def fail_second_large_chunk(storage, additional):
            if additional == resource.MiB:
                calls[0] += 1
                if calls[0] == 2:
                    raise ValueError('synthetic physical-write gate')
            return original_check(storage, additional)
        with patch.object(finalizer, '_temporary_check', side_effect=fail_second_large_chunk):
            with self.assertRaisesRegex(ValueError, 'synthetic physical-write gate'):
                finalizer.finalize(self.storage, {'synthetic': True})
        failure = json.loads((self.root / 'evidence_v2/verification01/FAILED.json').read_text())
        progress = failure['verification_progress']
        self.assertEqual(progress['current_logical_path'], 'z_large.bin')
        self.assertEqual(progress['current_partial_bytes'], resource.MiB)
        self.assertEqual(progress['physical_verification_bytes_written'], resource.MiB + 5)
        self.assertIn('a_good.bin', progress['logical_paths_verified'])
        self.assertEqual(progress['logical_files_verified'], len(progress['logical_paths_verified']))
        self.assertEqual(progress['verified_manifest_prefix']['count'], progress['logical_files_verified'])
        self.assertEqual(Path(progress['current_partial_path']).stat().st_size, resource.MiB)
        self.assertTrue(Path(progress['temporary_failure_directory']).is_dir())
        self.assertTrue(failure['manifest']['sha256'])
        second = finalizer.finalize(self.storage, {'synthetic': True}, 'verification02')
        manifest = json.loads((self.root / second['manifest']['path']).read_text())
        residues = manifest['verification_residue_outside_logical_raw']
        self.assertEqual(len(residues), 1)
        self.assertEqual(residues[0]['files'][0]['bytes'], resource.MiB)
        self.assertGreater(residues[0]['physical_allocated_bytes'], 0)

    def test_freeze_requires_resource_closure_commit_and_scientific_seals(self):
        seal = self.root / 'SYNTHETIC_COMPLETE.json'
        seal.write_bytes(b'{"synthetic":true}')
        reg = {'attempt_id': 'attempt02', '_sha256': 'a' * 64}
        sources = [Path(finalizer.__file__), Path(resource.__file__)]
        record = {'execution_kind': 'evidence_finalization', 'attempt_id': 'attempt02',
                  'operational_amendment_sha256': reg['_sha256'], 'registered_commit': 'b' * 40,
                  'source_files': {str(p.relative_to(finalizer.ROOT)): resource.file_hash(p) for p in sources},
                  'artifacts': {str(seal): resource.file_hash(seal)},
                  'required_scientific_seals': {str(seal): resource.file_hash(seal)}}
        freeze = Path(self.temp.name) / 'freeze.json'
        freeze.write_text(json.dumps(record))
        self.assertEqual(finalizer.verify_source_freeze(freeze, reg)['registered_commit'], 'b' * 40)
        for mutation in ('missing_resource', 'short_commit', 'empty_seals', 'unbound_seal'):
            bad = json.loads(json.dumps(record))
            if mutation == 'missing_resource':
                del bad['source_files'][str(Path(resource.__file__).relative_to(finalizer.ROOT))]
            elif mutation == 'short_commit':
                bad['registered_commit'] = 'b' * 39
            elif mutation == 'empty_seals':
                bad['required_scientific_seals'] = {}
            else:
                bad['required_scientific_seals'][str(seal)] = '0' * 64
            freeze.write_text(json.dumps(bad))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                finalizer.verify_source_freeze(freeze, reg)

    def test_large_failure_prefix_is_exact_and_bounded(self):
        names = [str(i).zfill(5) + '/' + 'x' * 100 for i in range(2000)]
        error = ValueError('synthetic')
        error.verification_progress = {'logical_paths_verified': names, 'logical_files_verified': len(names)}
        compact = finalizer.failure_progress(error)
        self.assertEqual(compact['verified_manifest_prefix']['count'], len(names))
        self.assertTrue(compact['logical_paths_reconstructable_from_manifest_prefix'])
        self.assertLess(len(json.dumps(compact).encode()), 16384)


if __name__ == '__main__':
    unittest.main()

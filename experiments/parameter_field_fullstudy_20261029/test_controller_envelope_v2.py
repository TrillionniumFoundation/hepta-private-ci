"""Synthetic exact failure observation and historical recovery; no science runs."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import controller_envelope_v2 as envelope
from . import resource_v2 as resource


def profile(*args, **kwargs):
    return {'allowed': True, 'oom': 8, 'oom_kill': 4, 'effective_current': 0,
            'limit': 8 * resource.GiB, 'required_headroom': 0}


class ControllerEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='controller-envelope-test-', dir='/workspace/scratch/178ced6a501f')
        self.base, self.root = Path(self.temp.name), Path(self.temp.name) / 'raw'
        self.root.mkdir()
        self.patches = [patch.object(resource, 'memory_admission', side_effect=profile),
                        patch.object(envelope, 'memory_admission', side_effect=profile),
                        patch.object(envelope, 'live_task_pids', return_value=[])]
        for item in self.patches:
            item.start()
        protocol = self.save(self.base / 'PROTOCOL.json', {'synthetic': True})
        self.ops = self.save(self.base / 'OPS.json', {
            'status': 'REGISTERED_PRE_ENDPOINT', 'execution_ready': True, 'attempt_id': 'attempt02',
            'raw_root': str(self.root), 'original_protocol': protocol,
            'proposed_resource_contract': {'global_raw_logical_bytes': 2 * resource.GiB,
                'minimum_private_allocatable_bytes': 256 * resource.MiB, 'C_training_evidence_bytes': 350 * resource.MiB},
            'concurrency': {'max_workers': 2, 'worker_reservation_bytes': 768 * resource.MiB,
                            'memory_margin_bytes': resource.GiB}})
        prefix = Path(envelope.__file__).parent.relative_to(envelope.ROOT)
        files = {str(prefix / name): envelope.core.digest(envelope.ROOT / prefix / name)
                 for name in ('launch_v2.py', 'resource_v2.py', 'run_v2.py')}
        self.original = {'registered_commit': 'a' * 40, 'allowed_phases': ['OPS'], 'attempt_id': 'attempt02',
                         'execution_kind': 'controller', 'operational_amendment_sha256': self.ops['sha256'],
                         'protocol_sha256': protocol['sha256'], 'source_files': files, 'artifacts': {}}
        parent = self.save(self.base / 'PARENT.json', self.original)
        self.freeze = {**self.original, 'registered_commit': 'b' * 40,
                       'source_files': {**files, str(prefix / 'controller_envelope_v2.py'): envelope.core.digest(envelope.__file__)},
                       'artifacts': {parent['path']: parent['sha256']}, 'controller_parent': parent,
                       'controller_envelope_schema': envelope.SCHEMA}
        frozen = self.save(self.base / 'FREEZE.json', self.freeze)
        queue = self.save(self.base / 'QUEUE.json', {'jobs': [{'id': 'A-17', 'phase': 'A', 'seed': 17,
            'group': 'training', 'requires': [], 'freeze_sha256': 'c' * 64,
            'completion': 'operations/A-seed-17.COMPLETE.json', 'argv': ['-B', '-m',
            'experiments.parameter_field_fullstudy_20261029.run_v2', '--phase', 'A', '--seed', '17',
            '--root', str(self.root), '--freeze', frozen['path'], '--execute']}], 'finalize': False})
        self.args = SimpleNamespace(root=str(self.root), queue=queue['path'], freeze=frozen['path'],
                                    freeze_sha256=frozen['sha256'], amendment=self.ops['path'],
                                    amendment_sha256=self.ops['sha256'], resume_admission=False, recover_zero_work=False)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True))
        return envelope.descriptor(path)

    def frozen_again(self):
        self.args.freeze_sha256 = self.save(Path(self.args.freeze), self.freeze)['sha256']

    def zero_progress_failure(self, unused):
        (self.root / 'controller').mkdir()
        self.save(self.root / 'controller/START.json', {'synthetic': True})
        self.save(self.root / 'ACTIVE_WORKERS.json', {'workers': []})
        raise MemoryError('synthetic PROGRESS memory spike')

    def test_zero_spawn_memory_failure_emits_compatible_receipt_and_restores_proxy(self):
        original = envelope.core.subprocess
        with patch.object(envelope.core, 'run', side_effect=self.zero_progress_failure):
            with self.assertRaisesRegex(MemoryError, 'PROGRESS memory spike'):
                envelope.execute(self.args)
        self.assertIs(envelope.core.subprocess, original)
        failed = envelope.read(self.root / 'controller/ENVELOPE_FAILED.json')
        self.assertEqual(failed['Popen_attempt_count'], 0)
        self.assertEqual(failed['scheduled_gradient_microsteps'], 0)
        self.assertIn('MemoryError', failed['traceback'])
        self.assertGreaterEqual(failed['wall_seconds'], 0)
        self.assertGreaterEqual(failed['cpu_seconds'], 0)
        self.assertGreaterEqual(failed['process_cpu_seconds_total'], failed['cpu_seconds'])
        admission = envelope.read(self.root / 'controller/ADMISSION_FAILED.json')
        self.assertEqual(admission['source_freeze_sha256'], self.args.freeze_sha256)
        self.assertTrue(admission['Popen_observer_confirmed_zero_attempts'])
        self.assertLess((self.root / 'controller/ENVELOPE_FAILED.json').stat().st_size, 64 * 1024)

    def test_unchanged_real_controller_accepts_observed_pure_admission_resume(self):
        with patch.object(envelope.core, 'run', side_effect=self.zero_progress_failure):
            with self.assertRaises(MemoryError):
                envelope.execute(self.args)
        self.args.resume_admission = True
        clock = [0.]
        def advance():
            clock[0] += 100.
            return clock[0]
        with patch.object(envelope.core, 'memory_profile', side_effect=profile), \
             patch.object(envelope.core, 'memory_admission', return_value={**profile(), 'allowed': False}), \
             patch.object(envelope.core.time, 'monotonic', side_effect=advance), \
             patch.object(envelope.core.time, 'sleep'), \
             patch.object(envelope.core.subprocess, 'Popen') as popen:
            self.assertEqual(envelope.execute(self.args), 75)
            popen.assert_not_called()
        self.assertTrue((self.root / 'controller_admission_001/ENVELOPE_FAILED.json').is_file())
        self.assertEqual(envelope.read(self.root / 'controller/ADMISSION_FAILED.json')['scientific_workers_started'], 0)

    def test_successful_Popen_then_failure_never_becomes_admission_blocked(self):
        def fail(unused):
            (self.root / 'controller').mkdir()
            envelope.core.subprocess.Popen(['synthetic', 'worker'])
            raise MemoryError('after spawn')
        with patch.object(envelope.core.subprocess, 'Popen', return_value=SimpleNamespace(pid=987654321)), \
             patch.object(envelope.core, 'run', side_effect=fail):
            with self.assertRaises(MemoryError):
                envelope.execute(self.args)
        record = envelope.read(self.root / 'controller/ENVELOPE_FAILED.json')
        self.assertEqual(record['Popen_returned_count'], 1)
        self.assertEqual(record['returned_processes'][0]['pid'], 987654321)
        self.assertIsNone(record['scheduled_gradient_microsteps'])
        self.assertFalse((self.root / 'controller/ADMISSION_FAILED.json').exists())

    def test_Popen_call_that_raises_is_uncertain_not_zero_spawn(self):
        def fail(unused):
            (self.root / 'controller').mkdir()
            envelope.core.subprocess.Popen(['synthetic'])
        with patch.object(envelope.core.subprocess, 'Popen', side_effect=OSError('exec failure')), \
             patch.object(envelope.core, 'run', side_effect=fail):
            with self.assertRaises(OSError):
                envelope.execute(self.args)
        record = envelope.read(self.root / 'controller/ENVELOPE_FAILED.json')
        self.assertEqual((record['Popen_attempt_count'], record['Popen_returned_count']), (1, 0))
        self.assertFalse((self.root / 'controller/ADMISSION_FAILED.json').exists())

    def test_scientific_START_prevents_zero_work_classification_even_without_new_spawn(self):
        def fail(unused):
            (self.root / 'controller').mkdir()
            self.save(self.root / 'operations/A-seed-17.START.json', {'synthetic': True})
            raise MemoryError('resource failure')
        with patch.object(envelope.core, 'run', side_effect=fail):
            with self.assertRaises(MemoryError):
                envelope.execute(self.args)
        self.assertFalse((self.root / 'controller/ADMISSION_FAILED.json').exists())

    def test_own_source_and_original_closure_are_required(self):
        self.freeze['source_files'].pop(next(k for k in self.freeze['source_files'] if k.endswith('controller_envelope_v2.py')))
        self.frozen_again()
        with self.assertRaisesRegex(ValueError, 'not explicitly frozen'):
            envelope.validate(self.args)

    def test_pending_raw_write_blocks_automatic_resume_without_erasing_partial_bytes(self):
        def fail(unused):
            (self.root / 'controller').mkdir()
            (self.root / 'PROGRESS.json.ops-pending').write_bytes(b'partial metadata')
            raise MemoryError('write interrupted')
        with patch.object(envelope.core, 'run', side_effect=fail):
            with self.assertRaises(MemoryError):
                envelope.execute(self.args)
        record = envelope.read(self.root / 'controller/ENVELOPE_FAILED.json')
        self.assertEqual(record['scheduled_gradient_microsteps'], 0)
        self.assertFalse(record['automatic_admission_resume_safe'])
        self.assertFalse((self.root / 'controller/ADMISSION_FAILED.json').exists())
        self.assertEqual((self.root / 'PROGRESS.json.ops-pending').read_bytes(), b'partial metadata')

    def test_large_unicode_trace_is_bounded_with_full_payload_hash(self):
        registration, unused = envelope.validate(self.args)
        storage = resource.StorageBudget(self.root, registration)
        path = self.root / 'LONG_FAILED.json'
        envelope.write_failure(storage, path, {'message': '🌍' * 50000, 'traceback': '🌍' * 50000})
        record = envelope.read(path)
        self.assertTrue(record['failure_receipt_truncated'])
        self.assertEqual(len(record['full_serialized_failure_sha256']), 64)
        self.assertLess(path.stat().st_size, 64 * 1024)

    def test_outer_exit_requires_full_bound_success_and_rejects_failure_seal(self):
        directory = self.root / 'controller'
        failure = self.save(directory / 'EXECUTION_FAILED.json', {'complete': False})
        self.assertEqual(envelope.terminal_exit(self.args, None), 1)
        Path(failure['path']).unlink()
        self.assertEqual(envelope.terminal_exit(self.args, None), 1)
        jobs, results = [], {}
        for name in sorted(envelope.core.EXPECTED_IDS):
            relative = 'synthetic_seals/' + name + '.json'
            item = self.save(self.root / relative, {'synthetic': True, 'id': name})
            jobs.append({'id': name, 'completion': relative})
            results[name] = {'complete': True, 'exit_code': 0, 'completion': {**item, 'path': relative}}
        self.save(Path(self.args.queue), {'finalize': True, 'jobs': jobs})
        value = {'complete': True, 'source_freeze_sha256': self.args.freeze_sha256, 'jobs': results}
        self.save(directory / 'EXECUTION.json', value)
        with patch.object(envelope.core, 'validate_queue', return_value=jobs):
            self.assertEqual(envelope.terminal_exit(self.args, None), 0)
            value['jobs']['A-17']['completion']['sha256'] = '0' * 64
            self.save(directory / 'EXECUTION.json', value)
            self.assertEqual(envelope.terminal_exit(self.args, None), 1)

    def historical_fixture(self):
        old = {'controller/START.json': {'source_freeze_sha256': self.freeze['controller_parent']['sha256'],
                                        'amendment_sha256': self.ops['sha256']},
               'ACTIVE_WORKERS.json': {'workers': []},
               'PROGRESS.json': {'running': {}, 'results': {}, 'pending': ['A-17']}}
        evidence = {}
        for name, content in old.items():
            evidence[name] = {**self.save(self.root / name, content), 'content': content}
        for name in ('.ops-controller.lock', '.ops-write.lock'):
            (self.root / name).touch()
        incident = self.save(self.base / 'INCIDENT.json', {
            'schema': 'hepta.fullstudy.controller-infrastructure-failure.1', 'attempt_id': 'attempt02',
            'raw_root': str(self.root), 'scientific_workers_started': 0, 'scheduled_gradient_microsteps': 0,
            'error_type': 'MemoryError', 'standard_admission_failure_receipt_written': False,
            'basis_for_zero_worker_count': 'Synthetic source-and-artifact postmortem, not a Popen observer.',
            'raw_evidence': evidence})
        self.freeze['artifacts'][incident['path']] = incident['sha256']
        self.freeze['zero_work_recovery'] = {'incident': incident, 'queue': envelope.descriptor(self.args.queue),
            'prior_raw_files': envelope.raw_inventory(self.root), 'archive_relative': 'controller_recoveries/incident01'}
        self.args.recover_zero_work = True
        self.frozen_again()
        return envelope.raw_inventory(self.root)

    def test_historical_recovery_denied_before_any_archival_mutation(self):
        inventory = self.historical_fixture()
        with patch.object(envelope, 'memory_admission', return_value={'allowed': False}), \
             patch.object(envelope.core, 'run') as run:
            self.assertEqual(envelope.execute(self.args), 75)
            run.assert_not_called()
        self.assertEqual(envelope.raw_inventory(self.root), inventory)

    def test_registered_historical_recovery_preserves_every_original_byte(self):
        inventory = self.historical_fixture()
        with patch.object(envelope.core, 'run', return_value=75):
            self.assertEqual(envelope.execute(self.args), 75)
        archive = self.root / 'controller_recoveries/incident01'
        for name in ('controller/START.json', 'ACTIVE_WORKERS.json', 'PROGRESS.json'):
            self.assertEqual(envelope.core.digest(archive / name), inventory[name]['sha256'])
            self.assertFalse((self.root / name).exists())
        receipt = envelope.read(archive / 'RECOVERY_COMPLETE.json')
        self.assertFalse(receipt['historical_Popen_observation_available'])
        self.assertFalse((archive / 'controller/ADMISSION_FAILED.json').exists())

    def test_historical_recovery_rejects_changed_inventory_and_live_process(self):
        self.historical_fixture()
        self.save(self.root / 'unexpected.json', {'synthetic': True})
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            envelope.execute(self.args)
        (self.root / 'unexpected.json').unlink()
        with patch.object(envelope, 'live_task_pids', return_value=[12345]):
            with self.assertRaisesRegex(ValueError, 'live task'):
                envelope.execute(self.args)
        self.assertFalse((self.root / 'controller_recoveries').exists())


if __name__ == '__main__':
    unittest.main()

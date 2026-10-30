"""Execution05 supervisor tests use synthetic import metadata only; no science."""

import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from . import controller, supervisor
from .test_controller_import import ImportFixture, desc, write


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        target = os.environ.get('HEPTA_SUPERVISOR_TEST_OUTPUT')
        if target:
            self.base = Path(target)/self._testMethodName; self.base.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='hepta-supervisor-fixture-'); self.addCleanup(temporary.cleanup); self.base = Path(temporary.name)
        write(self.base/'SYNTHETIC_TEST_FIXTURE.json', {'scope': 'All import/seal/supervisor files in this test case are synthetic; no science or remote ACK.', 'scientific_tasks_executed': 0})
        self.fixture = ImportFixture(self.base)
        f = self.fixture
        f.receipt_value['method'] = 'copy'; f.receipt = write(f.receipt_path, f.receipt_value)
        write(f.fresh/'imports/execution04/A-17/IMPORT_STARTED.json', {
            'source_episode': controller.SOURCE_EPISODE, 'target_episode': controller.TARGET_EPISODE,
            'pins': f.receipt_value['pins'], 'method': 'copy', 'scientific_workers_started': 0})
        self.ops = self.base/'ops'; self.ops.mkdir()
        for obj, key, value in ((controller.legacy, 'ROOT', f.source),
                                (controller.legacy, '__file__', str(f.source/'experiments/parameter_field_fullstudy_20261029/launch_v2.py')),
                                (supervisor, 'SOURCE', f.source), (supervisor, 'OPS', self.ops), (supervisor, 'RAW', f.fresh)):
            patch = mock.patch.object(obj, key, value); patch.start(); self.addCleanup(patch.stop)
        sample = {'oom': 4, 'oom_kill': 4, 'effective_available': 16*1024**3, 'disk_available': 16*1024**3,
                  'available_inodes': 100000, 'synthetic_capacity_fixture': True}
        patch = mock.patch.object(supervisor, 'capacity', side_effect=lambda path: dict(sample)); patch.start(); self.addCleanup(patch.stop)
        self.core = controller.ControllerCore(f.receipt)
        self.full_queue = f.queue(self.core, finalize=False)
        self.initial = {**self.full_queue, 'jobs': self.full_queue['jobs'][:4]}
        self.policy = write(self.base/'CWD_POLICY.json', {'synthetic_policy': True})
        self.config = {'execution_episode': supervisor.EPISODE, 'active_queue': str(self.ops/'ACTIVE_QUEUE.json'),
                       'python': os.sys.executable, 'empty_cwd': str(self.base), 'ops_root': str(self.ops),
                       'descriptors': {'import_receipt': f.receipt, 'amendment': f.new_profile,
                                       'controller_freeze': f.new_freeze, 'cwd_policy': self.policy,
                                       'cwd_runner': {'path': str(self.base/'dummy_cwd.py')}, 'producer_map': {'synthetic': True}}}
        self.config_desc = write(self.base/'CONFIG.json', self.config)
        self.subject = supervisor.Supervisor(self.config, self.config_desc, self.initial)

    def imported_records(self):
        raw = self.fixture.fresh
        write(raw/'controller/A-17.IMPORT.json', self.core.import_record)
        write(raw/'controller/A-17.RESULT.json', self.core.imported_result)
        write(raw/'ACTIVE_WORKERS.json', {'workers': []})

    def test_exact_materialized_import_allowed_and_extra_file_rejected(self):
        self.subject.prepare_imported_layout()
        self.assertEqual(self.subject.import_core.imported_job, self.core.imported_job)
        (self.fixture.fresh/'unexpected.bin').write_bytes(b'not admitted')
        with self.assertRaisesRegex(ValueError, 'exact materialized A17 files'):
            self.subject.prepare_imported_layout()

    def test_extra_empty_directory_and_nonempty_cas_rejected(self):
        extra = self.fixture.fresh/'unregistered_empty'; extra.mkdir()
        with self.assertRaisesRegex(ValueError, 'Unregistered initial RAW directory'):
            self.subject.prepare_imported_layout()
        extra.rmdir()
        cas = self.fixture.fresh.with_name(self.fixture.fresh.name+'_cas'); cas.mkdir()
        (cas/'foreign').write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError, 'CAS must start empty'):
            self.subject.prepare_imported_layout()

    def test_import_receipt_changed_materialization_start_rejected(self):
        p = self.fixture.fresh/'imports/execution04/A-17/IMPORT_STARTED.json'
        value = json.loads(p.read_text()); value['scientific_workers_started'] = 1; write(p, value)
        with self.assertRaisesRegex(ValueError, 'materialization start receipt'):
            self.subject.prepare_imported_layout()

    def test_start_policy_uses_one_original_deadline_and_cannot_overwrite(self):
        self.subject.run_dir.mkdir()
        item = self.subject.write_start_policy(); value = json.loads(Path(item['path']).read_text())
        expected = {'schema': 'hepta.execution05.supervisor-start-policy.1', 'execution_episode': supervisor.EPISODE,
                    'source_root': str(self.fixture.source), 'raw_root': str(self.fixture.fresh), 'ops_root': str(self.ops),
                    'cwd_policy': self.policy, 'supervisor_identity': supervisor.proc_identity(os.getpid()),
                    'started_monotonic': self.subject.started, 'deadline_monotonic': self.subject.started+43200,
                    'oom_baseline': {'oom': 4, 'oom_kill': 4}}
        self.assertEqual(value, expected)
        self.assertEqual(item, desc(Path(item['path'])))
        with self.assertRaisesRegex(ValueError, 'Refusing to replace'):
            self.subject.write_start_policy()
        self.assertEqual(json.loads(Path(item['path']).read_text()), expected)

    def test_A17_uses_original_profile_and_exact_import_result_without_fake_start(self):
        self.subject.prepare_imported_layout(); self.imported_records()
        self.subject.wait_job(self.core.imported_job)
        self.assertEqual(self.subject.done, ['A-17'])
        paths = self.subject.closed_job_paths(self.core.imported_job)
        self.assertIn('raw/controller/A-17.IMPORT.json', paths)
        self.assertIn('raw/controller/A-17.RESULT.json', paths)
        self.assertIn('raw/operations/A-seed-17.COMPLETE.json', paths)
        self.assertIn('raw/imports/execution04/A-17/ORIGINAL_CONTROLLER_RESULT.json', paths)
        self.assertFalse(any(name.endswith('A-17.START.json') or name.endswith('A-17.log') or name.endswith('A-seed-17.START.json') for name in paths))
        changed = copy.deepcopy(self.core.imported_result); changed['executed_here'] = True
        with self.assertRaisesRegex(ValueError, 'imported job/result differs'):
            self.subject.require_imported_result(self.core.imported_job, changed)
        write(self.fixture.fresh/'controller/A-17.START.json', {'synthetic_forgery': True})
        with self.assertRaisesRegex(ValueError, 'no fabricated'):
            self.subject.require_imported_result(self.core.imported_job, self.core.imported_result)

    def test_next_activation_requires_new_episode_ACK_not_old_A17_ACK(self):
        self.subject.run_dir.mkdir(); self.subject.activate(1)
        self.subject.done = ['A-17']
        with self.assertRaisesRegex(ValueError, 'verified durable ACK'):
            self.subject.activate(2)
        binding = {'label': 'A-17', 'completed_jobs': ['A-17'], 'sequence': 1, 'execution_episode': controller.SOURCE_EPISODE}
        self.subject.acks = [{'binding': binding}]
        with self.assertRaisesRegex(ValueError, 'historical ACK cannot be reused'):
            self.subject.activate(2)
        self.subject.acks[0]['binding']['execution_episode'] = supervisor.EPISODE
        self.subject.activate(2)
        active = json.loads(Path(self.config['active_queue']).read_text())
        self.assertEqual([row['id'] for row in active['jobs']], ['A-17', 'A-29'])
        self.assertFalse(active['finalize'])

    def test_nonimported_job_still_requires_original_START_and_log(self):
        job = self.full_queue['jobs'][1]
        directory = self.fixture.fresh/'stage_A/seed-29'; directory.mkdir()
        (directory/'dummy').write_bytes(b'synthetic only')
        with self.assertRaisesRegex(ValueError, 'Missing stable controller job artifact'):
            self.subject.closed_job_paths(job)

    def test_finalizer_calls_registered_wrapper_with_verification05(self):
        captured = {}
        self.subject.register = lambda stage, count: {'synthetic': True}
        self.subject.sealed_sources = lambda result, name, count: ({'path': '/synthetic/freeze', 'sha256': 'a'*64}, {})
        self.subject.gate = lambda: None
        def child(name, argv):
            captured.update({'name': name, 'argv': argv}); return object()
        self.subject.child = child
        stop = RuntimeError('stop test before finalizer output parsing')
        self.subject.wait_child = lambda child: (_ for _ in ()).throw(stop)
        with self.assertRaises(RuntimeError) as caught:
            self.subject.finalize(self.fixture.fresh/'analysis')
        self.assertIs(caught.exception, stop)
        expected_flags = ['--root', str(self.fixture.fresh), '--amendment', self.fixture.new_profile['path'],
                          '--amendment-sha256', self.fixture.new_profile['sha256'], '--freeze', '/synthetic/freeze',
                          '--evidence-id', 'verification05', '--execute']
        self.assertEqual(captured, {'name': 'finalizer', 'argv': self.subject.cwd_command('finalizer', expected_flags)})

    def closed_wrappers(self):
        expected = {'CONTROLLER', 'ANALYSIS_PARENT', 'ANALYSIS', 'FINALIZER-verification05', *supervisor.ORDER[1:]}
        for token in expected:
            run = self.ops/'wrapper_runs'/token/'999999-1'
            write(run/'START.json', {'synthetic_test_fixture': True})
            write(run/'COMPLETE.json', {'synthetic_test_fixture': True, 'scientific_completion_claim': False})
            if token in ('CONTROLLER', 'ANALYSIS_PARENT'):
                count = 13 if token == 'CONTROLLER' else 1
                write(run/'owned_children/CLOSURE.json', {'synthetic_test_fixture': True,
                    'all_returned_direct_children_reaped': True, 'accounting_complete_for_attempted_direct_workers': True,
                    'attempt_count': count, 'returned_children': count, 'children': [{'wait4': {'exit_code': 0}} for unused in range(count)]})
            journal = self.ops/'resource_backpressure'/token/'999999-1'; journal.mkdir(parents=True)
            (journal/'CAPACITY_EVENTS.jsonl').write_text('{"synthetic_test_fixture":true}\n')

    def test_final_operational_closure_includes_all_journals_and_rejects_fake_A17(self):
        self.closed_wrappers(); paths = self.subject.closed_wrapper_paths()
        self.assertIn('ops/wrapper_runs/CONTROLLER/999999-1/owned_children/CLOSURE.json', paths)
        self.assertIn('ops/resource_backpressure/ANALYSIS/999999-1/CAPACITY_EVENTS.jsonl', paths)
        (self.ops/'wrapper_runs/A-17').mkdir()
        with self.assertRaisesRegex(ValueError, 'wrapper population differs'):
            self.subject.closed_wrapper_paths()

    def test_operational_closure_rejects_missing_worker_accounting(self):
        self.closed_wrappers(); path = self.ops/'wrapper_runs/CONTROLLER/999999-1/owned_children/CLOSURE.json'
        value = json.loads(path.read_text()); value['returned_children'] = 12; write(path, value)
        with self.assertRaisesRegex(ValueError, 'exact new-worker population'):
            self.subject.closed_wrapper_paths()

    def test_full_pipeline_schedule_keeps_fourteen_jobs_and_seventeen_barriers(self):
        subject = self.subject; events = []
        subject.gate = lambda: events.append(('gate', subject.phase))
        subject.status = lambda **extra: None
        def child(name, argv):
            class SyntheticChild:
                result = None
                def poll(inner):
                    if subject.active and subject.active.get('finalize'):
                        inner.result = {'exit_code': 0, 'total_cpu_seconds': 0.0}; return 0
                    return None
            value = SyntheticChild(); subject.children.append(value); return value
        subject.child = child
        subject.wait_job = lambda job: subject.done.append(job['id'])
        subject.closed_job_paths = lambda job: {}
        def durable(label, paths, controller_closed=False):
            events.append(('barrier', label))
            subject.acks.append({'binding': {'execution_episode': supervisor.EPISODE, 'sequence': len(subject.acks)+1,
                'label': label, 'completed_jobs': list(subject.done)}, 'items_verified': 0})
        subject.durable = durable
        def register(stage, count):
            events.append(('register', stage)); subject.canonical = {**self.full_queue, 'jobs': self.full_queue['jobs'][:count]}
        subject.register = register
        def verify():
            events.append(('verify_grid', len(subject.done)))
            (self.fixture.fresh/'controller').mkdir(exist_ok=True)
        subject.verify_grid = verify
        def analysis():
            durable('analysis', {}, True); return self.fixture.fresh/'analysis'
        subject.run_analysis = analysis
        def finalize(output):
            durable('final_closure', {}, True)
            return {'synthetic_test_fixture': True}, {'logical_files_restored': 0, 'logical_bytes_restored': 0}
        subject.finalize = finalize
        result = subject.execute()
        labels = [value for kind, value in events if kind == 'barrier']
        self.assertEqual(labels, supervisor.ORDER+['controller', 'analysis', 'final_closure'])
        self.assertEqual(result['jobs'], supervisor.ORDER)
        self.assertEqual((result['jobs_verified'], result['jobs_imported'], result['jobs_executed_here']), (14, 1, 13))
        self.assertEqual(result['scientific_jobs_executed_here'], supervisor.ORDER[1:])
        self.assertEqual([value for kind, value in events if kind == 'register'], ['followups', 'endpoints'])
        self.assertEqual(len(result['durable_stages']), 17)


if __name__ == '__main__':
    unittest.main()

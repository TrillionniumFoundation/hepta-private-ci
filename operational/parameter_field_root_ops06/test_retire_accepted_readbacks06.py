"""Local marked fixtures only: no production retirement or remote calls.

The original frozen ACK byte verifier is real. Service identities and helper
WAIT4 objects inside cases are explicitly synthetic, not actual measurements.
Actual filesystem/xattr/dirfd/unlink/fadvise and a tiny child FD/maps are exercised.
"""
import argparse
import contextlib
import copy
import errno
import hashlib
import importlib.util
import io
import json
import mmap
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.dont_write_bytecode = True
DEV = Path('/workspace/scratch/178ced6a501f/execution06_retirement_development')
SCRIPT = Path(__file__).resolve().with_name('retire_accepted_readbacks06.py')
spec = importlib.util.spec_from_file_location('accepted_retirement06_test_api', SCRIPT)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
TEST_ROOT = None


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.base = TEST_ROOT / self._testMethodName
        self.base.mkdir(parents=True, exist_ok=False)
        self.ops = self.base / 'synthetic_ops'
        self.ops.mkdir()
        self.raw = self.base / 'synthetic_raw'
        self.raw.mkdir()
        self.output = self.base / 'retirement'
        for name, value in [('OPS', self.ops), ('RAW', self.raw), ('RETIREMENT_ROOT', self.output)]:
            patch = mock.patch.object(api, name, value)
            patch.start(); self.addCleanup(patch.stop)
        api.write_new(self.base / 'SYNTHETIC_ONLY.json', {
            'synthetic_test_fixture': True, 'actual_library_calls': 0, 'production_mutations': 0,
            'scientific_execution': 0, 'all_remote_identities_and_inner_WAIT4_are_synthetic': True,
            'actual_local_filesystem_operations': True, 'actual_frozen_ACK_verifier': True})
        (self.ops / 'empty_cwd').mkdir()
        initial = self.ops / 'registrations/initial'
        initial.mkdir(parents=True)
        policy = api.write_new(initial / 'CWD_POLICY.json', {
            'schema': 'hepta.fullstudy.cwd-policy.5', 'execution_episode': api.EPISODE,
            'source_root': str(api.SOURCE), 'raw_root': str(self.raw), 'ops_root': str(self.ops),
            'capacity_wait_seconds': 300, 'source_files': api.CODE})
        self.config = api.write_new(initial / 'PIPELINE_CONFIG.json', {
            'schema': 'hepta.fullstudy.execution06.configuration.1', 'execution_episode': api.EPISODE,
            'source_root': str(api.SOURCE), 'raw_root': str(self.raw), 'ops_root': str(self.ops),
            'source_commit': api.COMMIT, 'descriptors': {'cwd_policy': policy,
                'daemon_bootstrap': api.descriptor(api.SOURCE / 'operational/parameter_field_recovery06/daemon_bootstrap.py'),
                'wait4_launcher': api.descriptor(api.SOURCE / 'operational/parameter_field_recovery06/wait4_launcher.py')}})
        patch = mock.patch.object(api, 'CONFIG_SHA', self.config['sha256'])
        patch.start(); self.addCleanup(patch.stop)
        self.cfg = api.bound(self.config)
        startup = self.ops / 'supervisor_run'
        startup.mkdir()
        self.owner = api.proc_identity(os.getpid())
        started = time.monotonic() - 1
        self.start = api.write_new(startup / 'START_POLICY.json', {
            'schema': 'hepta.execution06.supervisor-start-policy.1', 'execution_episode': api.EPISODE,
            'source_root': str(api.SOURCE), 'raw_root': str(self.raw), 'ops_root': str(self.ops),
            'cwd_policy': policy, 'supervisor_identity': self.owner,
            'started_monotonic': started, 'deadline_monotonic': started + 43200,
            'oom_baseline': api.oom_counts()})
        self.stage = self.ops / 'durable/01_A-17'
        self.stage.mkdir(parents=True)
        self.work = self.ops / 'root_archive_io/01_A-17'
        (self.work / 'readback').mkdir(parents=True)
        eng = self.ops / 'root_archive_io/_engineering/01_A-17_upload'
        eng.mkdir(parents=True)
        self.binding = {'execution_episode': api.EPISODE, 'sequence': 1, 'label': 'A-17',
                        'completed_jobs': ['A-17'], 'pipeline_config': self.config, 'previous_ack': None}
        self.items = []
        for index in range(2):
            part = self.stage / ('part-%04d.tar.gz' % index)
            part.write_bytes((('synthetic archive only %d\n' % index) * 1500).encode())
            self.items.append(api.descriptor(part))
        manifest = api.write_new(self.stage / 'MANIFEST.json', {'schema': 'synthetic-manifest',
            'binding': self.binding, 'files': [], 'parts': [{'artifact': x} for x in self.items]})
        verification = api.write_new(self.stage / 'VERIFIED.json', {'binding': self.binding,
            'verification_complete': True, 'manifest': manifest})
        cost = api.write_new(self.stage / 'ARCHIVE_COST.json', {'binding': self.binding, 'synthetic_cost_not_measurement': True})
        self.items += [manifest, verification, cost]
        self.request = api.write_new(self.stage / 'REQUEST.json', {
            'schema': 'hepta.fullstudy.library-archive-request.1',
            'state': 'AWAITING_EXTERNAL_UPLOAD_AND_REMOTE_READBACK',
            'required_ack_schema': 'hepta.fullstudy.library-archive-ack.1',
            'binding': self.binding, 'manifest': manifest, 'archive_verification': verification, 'items': self.items})
        legacy = {'pid': self.owner['pid'], 'process_group': self.owner['pgid'],
                  'session': self.owner['sid'], 'start_ticks': str(self.owner['start_ticks'])}
        root_binding = api.write_new(self.work / 'BOUND_REQUEST.json', {
            'schema': 'hepta.execution06.root-archive-binding.1', 'request': self.request,
            'work_directory': str(self.work), 'supervisor_identity': legacy,
            'execution_code': api.bound_archive_code(), 'directory_id': 'synthetic-folder-id',
            'synthetic_test_fixture': True})
        upload_request = api.write_new(self.work / 'UPLOAD_REQUEST.json', {'uploads': [
            {'local_path': x['path'], 'purpose': 'create_library_file', 'library_artifact_type': 'other',
             'directory_id': 'synthetic-folder-id'} for x in self.items]})
        upload_rows = [{'local_path': x['path'], 'purpose': 'create_library_file', 'status': 'succeeded',
                        'local_metadata_applied': True, 'file_id': 'synthetic-file-%d' % i,
                        'library_file_id': 'synthetic-library-%d' % i, 'file_name': Path(x['path']).name,
                        'current_version_number': 0} for i, x in enumerate(self.items)]
        upload = api.write_new(eng / 'helper.stdout.log', {'results': upload_rows, 'synthetic_upload_result': True})
        upload_err = api.write_new(eng / 'helper.stderr.log', {'synthetic': True})
        intent = api.write_new(eng / 'INTENT.json', {'schema': 'hepta.execution04.root-engineering-intent.1',
            'synthetic_test_fixture_not_actual_measurement': True,
            'argv': [api.HELPER_PYTHON, '-B', str(api.HELPERS / 'library_upload.py')], 'stdin': upload_request,
            'cwd': str(self.ops / 'empty_cwd'), 'automatic_retry': False})
        upload_wait = api.write_new(eng / 'WAIT4.json', {
            'schema': 'hepta.execution04.root-engineering-wait4.1', 'complete': True, 'command_success': True,
            'child': {'exit_code': 0, 'wait_status': 0}, 'intent': intent, 'stdout': upload, 'stderr': upload_err,
            'synthetic_test_fixture_not_actual_measurement': True})
        transfers = [{'file_id': 'synthetic-file-%d' % i, 'library_file_id': 'synthetic-library-%d' % i,
                      'file_name': Path(x['path']).name, 'current_version_number': 0,
                      'download_url': 'https://synthetic.invalid/never-used'} for i, x in enumerate(self.items)]
        materialize = api.write_new(self.work / 'MATERIALIZE.json', {
            'isError': False, 'structuredContent': {'transfers': transfers, 'warnings': [], 'unavailable_items': []},
            'synthetic_materialize_response': True})
        ack_items, jobs = [], []
        for index, item in enumerate(self.items):
            source = Path(item['path'])
            duplicate = self.work / 'readback' / source.name
            duplicate.write_bytes(source.read_bytes())
            remote = {'file_id': 'synthetic-file-%d' % index, 'library_file_id': 'synthetic-library-%d' % index,
                      'file_name': source.name, 'version': 0}
            for path in (source, duplicate):
                os.setxattr(path, 'user.library-file-id', remote['library_file_id'].encode())
                os.setxattr(path, 'user.library-file-version', b'0')
            directory = self.work / 'readback_steps' / ('%03d' % index)
            directory.mkdir(parents=True)
            transfer = api.write_new(directory / 'TRANSFER.json', transfers[index])
            helper_argv = [api.HELPER_PYTHON, '-B', str(api.HELPERS / 'library_file_transfer.py'), 'materialize', str(duplicate)]
            helper_intent = api.write_new(directory / 'INTENT.json', {
                'schema': 'hepta.execution04.root-engineering-intent.1', 'argv': helper_argv,
                'stdin': transfer, 'cwd': str(self.ops / 'empty_cwd'), 'automatic_retry': False,
                'synthetic_test_fixture_not_actual_measurement': True})
            stdout = directory / 'helper.stdout.log'; stdout.write_text(str(duplicate) + '\n')
            stderr = directory / 'helper.stderr.log'; stderr.write_text('')
            wait = api.write_new(directory / 'WAIT4.json', {
                'schema': 'hepta.execution04.root-engineering-wait4.1', 'complete': True, 'command_success': True,
                'child': {'exit_code': 0, 'wait_status': 0}, 'intent': helper_intent, 'stdout': api.descriptor(stdout), 'stderr': api.descriptor(stderr),
                'synthetic_test_fixture_not_actual_measurement': True})
            ack_items.append({'local': item, 'upload_item_success': True, 'remote_readback_performed': True,
                'remote_identity': remote, 'readback_remote_identity': remote, 'readback': api.descriptor(duplicate),
                'upload_receipt': upload, 'readback_receipt': materialize, 'upload_wait4': upload_wait,
                'readback_helper_wait4': wait, 'readback_helper_stdout': api.descriptor(stdout),
                'complete_transfer_receipt': transfer})
            jobs.append({'local': item, 'remote_identity': remote, 'transfer': transfer,
                         'helper_argv': helper_argv, 'expected_output_path': str(duplicate), 'wait4_path': wait['path']})
        upload_verified = api.write_new(self.work / 'UPLOAD_VERIFIED.json', {
            'schema': 'hepta.execution06.root-upload-verified.1', 'request': self.request,
            'upload_request': upload_request, 'upload_wait4': upload_wait, 'upload_stdout': upload,
            'items': [{'local': x['local'], 'remote_identity': x['remote_identity']} for x in ack_items],
            'materialize_destination': str(self.work / 'readback')})
        materialize_args = api.write_new(self.work / 'MATERIALIZE_ARGS.json', {'synthetic_only': True})
        api.write_new(self.work / 'READBACK_PLAN.json', {
            'schema': 'hepta.execution06.root-readback-helper-plan.1', 'request': self.request,
            'upload_verified': upload_verified, 'materialize_arguments': materialize_args,
            'materialize_receipt': materialize, 'items': jobs})
        self.ack = api.write_new(self.stage / 'ACK.json', {
            'schema': 'hepta.fullstudy.library-archive-ack.1', 'status': 'VERIFIED_REMOTE_READBACK',
            'unknown_upload_outcome': False, 'request': self.request, 'binding': self.binding,
            'items': ack_items, 'root_operational_binding': root_binding})
        frozen_path = api.SOURCE / 'operational/parameter_field_recovery04/durable_archive.py'
        spec = importlib.util.spec_from_file_location('actual_frozen_verifier_for_fixture', frozen_path)
        frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
        self.verified = api.write_new(self.stage / 'ACK_VERIFIED.json', frozen.verify_ack(self.ack['path'], self.request))
        api.write_new(self.ops / 'STATUS.json', {'schema': 'hepta.fullstudy.execution06-status.1',
            'execution_episode': api.EPISODE, 'phase': 'science_A-29', 'pid': self.owner['pid'],
            'identity': {**legacy, 'state': 'S'}, 'durable_acks': 1, 'completed_jobs': ['A-17'], 'awaiting_durable': None})
        self.args = SimpleNamespace(stage='01_A-17', expected_request_sha256=self.request['sha256'], reason='Tiny synthetic disk test')

    def health(self):
        return api.Health(self.config, self.cfg, self.cfg['descriptors']['cwd_policy'])

    def state(self):
        return api.accepted('01_A-17', self.config, self.health())

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return api.prepare(self.args)

    def execute(self, plan):
        args = SimpleNamespace(plan=plan['path'], expected_plan_sha256=plan['sha256'], execute=True)
        with contextlib.redirect_stdout(io.StringIO()):
            return api.execute(args)

    def rewrite(self, path, value):
        Path(path).write_text(json.dumps(value, sort_keys=True) + '\n')

    def test_real_file_full_prepare_execute_and_no_second_unlink(self):
        plan_desc = self.prepare()
        plan = api.bound(plan_desc)
        self.assertEqual(len(plan['rows']), 2)
        self.assertFalse(plan['deletion_executed'])
        result = api.bound(self.execute(plan_desc))
        self.assertEqual(result['count'], 2)
        self.assertTrue(result['retained_source_parts_full_sha_and_xattrs_verified_after'])
        for row in plan['rows']:
            self.assertFalse(Path(row['duplicate']['path']).exists())
            self.assertEqual(api.descriptor(row['retained_original']['path']), row['retained_original'])
        self.assertTrue((self.work / 'readback/MANIFEST.json').exists())
        self.assertTrue((self.stage / 'ACK_VERIFIED.json').exists())
        with self.assertRaises(FileExistsError):
            self.execute(plan_desc)
        events = [json.loads(x) for x in (Path(plan_desc['path']).parent / 'execution/JOURNAL.jsonl').read_text().splitlines()]
        self.assertEqual(sum(e['event'] == 'UNLINK_INTENT' for e in events), 2)
        self.assertEqual(sum(e['event'] == 'UNLINK_DURABLE_AND_ABSENT' for e in events), 2)

    def test_current_unaccepted_status_and_wrong_request_are_rejected_without_plan(self):
        status = api.read(self.ops / 'STATUS.json')
        status.update(phase='await_durable_ack_A-17', awaiting_durable={'request': self.request, 'ack_path': self.ack['path']})
        self.rewrite(self.ops / 'STATUS.json', status)
        with self.assertRaisesRegex(RuntimeError, 'has not advanced'):
            self.prepare()
        self.assertFalse(self.output.exists())
        status.update(phase='science_A-29', awaiting_durable=None)
        self.rewrite(self.ops / 'STATUS.json', status)
        self.args.expected_request_sha256 = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'REQUEST SHA differs'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_parent_deadline_oom_and_startup_change_fail_closed(self):
        health = self.health()
        identity = {**self.owner, 'parent_pid': self.owner['parent_pid'] + 1}
        with mock.patch.object(api, 'proc_identity', return_value=identity):
            with self.assertRaisesRegex(RuntimeError, 'including parent changed'):
                health(force=True)
        with mock.patch.object(api.time, 'monotonic', return_value=health.start['deadline_monotonic'] + 1):
            with self.assertRaisesRegex(RuntimeError, 'deadline exhausted'):
                health(force=True)
        increased = {**health.start['oom_baseline'], 'oom': health.start['oom_baseline']['oom'] + 1}
        with mock.patch.object(api, 'oom_counts', return_value=increased):
            with self.assertRaisesRegex(RuntimeError, 'OOM baseline exceeded'):
                health(force=True)
        self.rewrite(self.start['path'], {**api.bound(self.start), 'tampered': True})
        with self.assertRaisesRegex(RuntimeError, 'startup record changed'):
            health(force=True)
        self.assertFalse(self.output.exists())

    def test_actual_child_fd_and_mmap_prevent_retirement(self):
        row = api.row_scope(self.state())[0]
        path = row['duplicate']['path']
        child_code = 'import mmap,os,sys;f=open(sys.argv[1],"rb");m=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ);print("READY",flush=True);sys.stdin.readline();m.close();f.close()'
        child = subprocess.Popen([sys.executable, '-B', '-c', child_code, path],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'READY')
            with self.assertRaises(RuntimeError) as raised:
                api.no_open_references(api.scan_rows([row]))
            message = str(raised.exception)
            self.assertIn('target_references', message)
            self.assertIn(str(child.pid), message)
            self.assertIn('mmap', message)
            self.assertIn('"kind": "fd"', message)
        finally:
            child.communicate('\n', timeout=5)
            self.assertEqual(child.returncode, 0)
        self.assertTrue(Path(path).exists())

    def test_source_or_duplicate_identity_change_blocks_all_unlinks(self):
        plan = self.prepare()
        row = api.bound(plan)['rows'][0]
        duplicate = Path(row['duplicate']['path'])
        original = duplicate.read_bytes()
        duplicate.unlink()
        duplicate.write_bytes(original)
        for name, value in [('user.library-file-id', row['remote_identity']['library_file_id']), ('user.library-file-version', '0')]:
            os.setxattr(duplicate, name, value.encode())
        with self.assertRaisesRegex(RuntimeError, 'identity changed since plan'):
            self.execute(plan)
        self.assertTrue(duplicate.exists())
        failure = api.read(Path(plan['path']).parent / 'execution/FAILED.json')
        self.assertEqual(failure['known_unlinks_returned'], [])
        with self.assertRaises(FileExistsError):
            self.execute(plan)

    def test_wrong_remote_version_and_hardlinks_are_rejected(self):
        state = self.state()
        rows = api.row_scope(state)
        duplicate = Path(rows[0]['duplicate']['path'])
        os.setxattr(duplicate, 'user.library-file-version', b'999')
        with self.assertRaisesRegex(RuntimeError, 'version xattrs differ'):
            self.prepare()
        self.assertTrue(duplicate.exists())
        duplicate.unlink()
        os.link(rows[0]['retained_original']['path'], duplicate)
        with self.assertRaisesRegex(RuntimeError, 'single-link'):
            api.row_scope(self.state())

    def test_partial_unlink_error_is_journaled_and_never_retried(self):
        plan = self.prepare()
        rows = api.bound(plan)['rows']
        actual = api.os.unlink
        calls = []
        def fail_second(path, *args, **kwargs):
            if kwargs.get('dir_fd') is not None:
                calls.append(str(path))
                if len(calls) == 2:
                    raise OSError(errno.EIO, 'synthetic second unlink failure')
            return actual(path, *args, **kwargs)
        with mock.patch.object(api.os, 'unlink', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'synthetic second'):
                self.execute(plan)
        self.assertFalse(Path(rows[0]['duplicate']['path']).exists())
        self.assertTrue(Path(rows[1]['duplicate']['path']).exists())
        failure = api.read(Path(plan['path']).parent / 'execution/FAILED.json')
        self.assertEqual(failure['known_unlinks_returned'], [rows[0]['duplicate']])
        self.assertTrue(failure['manual_reconciliation_required'])
        with self.assertRaises(FileExistsError):
            self.execute(plan)
        self.assertEqual(len(calls), 2)

    def test_unlink_return_then_journal_failure_keeps_ambiguity_and_no_retry(self):
        plan = self.prepare()
        rows = api.bound(plan)['rows']
        actual = api.Journal.log
        def fail_after_return(journal, event, **value):
            if event == 'UNLINK_RETURNED':
                raise OSError(errno.EIO, 'synthetic post-unlink journal failure')
            return actual(journal, event, **value)
        with mock.patch.object(api.Journal, 'log', fail_after_return):
            with self.assertRaisesRegex(OSError, 'post-unlink journal'):
                self.execute(plan)
        self.assertFalse(Path(rows[0]['duplicate']['path']).exists())
        self.assertTrue(Path(rows[1]['duplicate']['path']).exists())
        failure = api.read(Path(plan['path']).parent / 'execution/FAILED.json')
        self.assertEqual(failure['known_unlinks_returned'], [])
        self.assertTrue(failure['journal_last_intent_may_have_committed_before_completion_record'])
        events = [json.loads(x) for x in (Path(plan['path']).parent / 'execution/JOURNAL.jsonl').read_text().splitlines()]
        self.assertEqual(events[-1]['event'], 'UNLINK_INTENT')
        with self.assertRaises(FileExistsError):
            self.execute(plan)

    def test_verified_hash_last_payload_operation_is_real_advice(self):
        state = self.state(); row = api.row_scope(state)[0]
        target = row['retained_original_stat']
        key = (target['st_dev'], target['st_ino'])
        actual_read, actual_advise = os.read, os.posix_fadvise
        operations = []
        def observed_read(fd, count):
            value = actual_read(fd, count)
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == key:
                operations.append('read' if value else 'read_eof')
            return value
        def observed_advice(fd, offset, length, advice):
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == key:
                self.assertEqual(operations[-1], 'read_eof')
                operations.append('final_DONTNEED')
            return actual_advise(fd, offset, length, advice)
        journal = api.Journal(self.base / 'ADVICE_TEST.jsonl')
        try:
            with mock.patch.object(api.os, 'read', side_effect=observed_read), mock.patch.object(api.os, 'posix_fadvise', side_effect=observed_advice):
                api.verified_part(row['retained_original'], target, row['remote_identity'], self.health(), journal)
        finally:
            journal.close()
        self.assertEqual(operations[-1], 'final_DONTNEED')
        self.assertEqual(api.file_stat(row['retained_original']['path']), target)

    def test_protected_metadata_mutation_blocks_before_delete(self):
        plan = self.prepare()
        path = self.work / 'readback/MANIFEST.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(RuntimeError, 'metadata bytes/identity changed'):
            self.execute(plan)
        for row in api.bound(plan)['rows']:
            self.assertTrue(Path(row['duplicate']['path']).exists())

    def test_existing_prepare_and_plan_sha_cannot_restart(self):
        plan = self.prepare()
        with self.assertRaises(FileExistsError):
            self.prepare()
        bad = SimpleNamespace(plan=plan['path'], expected_plan_sha256='0' * 64, execute=True)
        with self.assertRaisesRegex(RuntimeError, 'plan SHA differs'):
            api.execute(bad)
        self.assertFalse((Path(plan['path']).parent / 'execution').exists())

    def test_symlink_and_out_of_stage_targets_fail_closed(self):
        rows = api.row_scope(self.state())
        duplicate = Path(rows[0]['duplicate']['path'])
        duplicate.unlink()
        duplicate.symlink_to(rows[0]['retained_original']['path'])
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            api.row_scope(self.state())
        self.assertTrue(Path(rows[0]['retained_original']['path']).is_file())

    def test_helper_intent_changed_after_ack_blocks_before_any_deletion(self):
        state = self.state()
        helper_wait = api.bound(state['ack']['items'][0]['readback_helper_wait4'])
        intent = api.bound(helper_wait['intent'])
        self.rewrite(helper_wait['intent']['path'], {**intent, 'argv': ['wrong-helper']})
        with self.assertRaisesRegex(RuntimeError, 'Exact metadata descriptor changed'):
            self.prepare()
        self.assertTrue((self.work / 'readback/part-0000.tar.gz').exists())

    def test_read_only_unknown_coverage_can_settle_but_requires_original_full_pass(self):
        incomplete = {'target_references': [], 'full_visible_proc_namespace_checked': False,
                      'new_unscanned_pids': [999999], 'access_errors': []}
        passed = {'target_references': [], 'new_unscanned_pids': [], 'access_errors': [],
                  'full_visible_proc_namespace_checked': True}
        clock = [0.0]
        records = []
        journal = SimpleNamespace(log=lambda event, **v: records.append({'event': event, **v}))
        sleeper = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        with mock.patch.object(api, 'no_open_references', side_effect=[api.IncompleteProcObservation(incomplete), passed]) as observe:
            value = api.settled_no_use([], lambda **kw: None, journal, clock=lambda: clock[0], sleeper=sleeper)
        self.assertEqual(observe.call_count, 2)
        self.assertEqual(value['read_only_observation_attempts'], 2)
        self.assertAlmostEqual(clock[0], 0.2)
        self.assertFalse(records[0]['mutation_performed_in_response'])
        malformed_pass = {**passed, 'full_visible_proc_namespace_checked': False}
        with mock.patch.object(api, 'no_open_references', return_value=malformed_pass):
            with self.assertRaisesRegex(RuntimeError, 'Original full no-reference PASS'):
                api.settled_no_use([], lambda **kw: None, journal, clock=lambda: 0.0, sleeper=sleeper)

    def test_known_user_and_unrelated_errors_never_enter_observation_wait(self):
        journal = SimpleNamespace(log=mock.Mock())
        sleeper = mock.Mock()
        for error in (RuntimeError('Known target user'), OSError(errno.EIO, 'unrelated IO failure')):
            with mock.patch.object(api, 'no_open_references', side_effect=error) as observe:
                with self.assertRaises(type(error)):
                    api.settled_no_use([], lambda **kw: None, journal, sleeper=sleeper)
                self.assertEqual(observe.call_count, 1)
        journal.log.assert_not_called()
        sleeper.assert_not_called()

    def test_unknown_coverage_has_ten_second_bound_and_preserves_health_failure(self):
        incomplete = {'target_references': [], 'full_visible_proc_namespace_checked': False,
                      'new_unscanned_pids': [], 'access_errors': [{'pid': 999999, 'errno': 13, 'error_type': 'PermissionError'}]}
        clock = [0.0]
        journal = SimpleNamespace(log=lambda event, **value: None)
        sleeper = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        with mock.patch.object(api, 'no_open_references', side_effect=api.IncompleteProcObservation(incomplete)):
            with self.assertRaisesRegex(TimeoutError, '10 seconds'):
                api.settled_no_use([], lambda **kw: None, journal, clock=lambda: clock[0], sleeper=sleeper)
        self.assertAlmostEqual(clock[0], 10.0)
        health = mock.Mock(side_effect=[None, RuntimeError('Original deadline exhausted')])
        with mock.patch.object(api, 'no_open_references', side_effect=api.IncompleteProcObservation(incomplete)) as observe:
            with self.assertRaisesRegex(RuntimeError, 'Original deadline exhausted'):
                api.settled_no_use([], health, journal, sleeper=lambda s: None)
            self.assertEqual(observe.call_count, 1)

    def test_terminal_uses_frozen_detached_chain_without_requiring_departed_proc(self):
        directory = self.ops / 'daemon_bootstrap'
        directory.mkdir()
        binding = {'execution_episode': api.EPISODE, 'pipeline_config': self.config,
                   'daemon_bootstrap': self.cfg['descriptors']['daemon_bootstrap'],
                   'wait4_launcher': self.cfg['descriptors']['wait4_launcher']}
        measuring = {'pid': self.owner['parent_pid'], 'parent_pid': 1, 'pgid': 77777, 'sid': 77777, 'start_ticks': 12345}
        bootstrap = {'pid': 99999, 'parent_pid': 88888, 'pgid': 99999, 'sid': 99999, 'start_ticks': 54321}
        intent = api.write_new(directory / 'INTENT.json', {
            'schema': 'hepta.execution06.detached-launch-intent.1', 'binding': binding,
            'bootstrap_identity': bootstrap, 'final_wait4_complete': False, 'automatic_retry': False,
            'synthetic_terminal_fixture': True})
        api.write_new(directory / 'FORKED.json', {'binding': binding, 'intent': intent,
            'daemon_pid': measuring['pid'], 'bridge_identity': {'pid': measuring['pgid']}})
        ready = api.write_new(directory / 'READY.json', {
            'schema': 'hepta.execution06.detached-parent-ready.1', 'binding': binding,
            'measuring_parent_identity': measuring, 'final_wait4_complete': False,
            'scientific_completion_claim': False, 'inherited_fds_closed': True, 'stdin_is_devnull': True,
            'stdout_stderr_are_regular_files': True, 'automatic_retry': False,
            'stdout': str(directory / 'daemon.stdout.log'), 'stderr': str(directory / 'daemon.stderr.log')})
        bridge = api.write_new(directory / 'BRIDGE_WAIT4.json', {
            'schema': 'hepta.execution06.bootstrap-bridge-wait4.1', 'pid': measuring['pgid'],
            'exit_code': 0, 'wait_status': 0, 'excludes_detached_measuring_parent_and_science': True,
            'synthetic_test_fixture_not_actual_measurement': True})
        api.write_new(directory / 'ACCEPTED.json', {
            'schema': 'hepta.execution06.detached-parent-accepted.1', 'binding': binding,
            'ready': ready, 'bridge_wait4': bridge, 'bootstrap_identity': bootstrap,
            'final_wait4_complete': False, 'automatic_retry': False})
        api.write_new(directory / 'TARGET_STARTED.json', {
            'binding': binding, 'ready': ready, 'measuring_parent_identity': measuring, 'automatic_retry': False})
        returned = api.write_new(directory / 'DAEMON_RETURNED.json', {
            'schema': 'hepta.execution06.detached-parent-returned.1', 'binding': binding,
            'ready': ready, 'measuring_parent_identity': measuring, 'target_exit_code': 0,
            'this_is_not_the_daemons_own_kernel_wait4': True, 'final_supervisor_wait4_must_be_verified_separately': True})
        verified = api.bound(self.verified)
        complete = api.write_new(self.ops / 'COMPLETE.json', {
            'schema': 'hepta.fullstudy.pipeline-completion.4', 'complete': True,
            'execution_episode': api.EPISODE, 'pipeline_config': self.config,
            'jobs_verified': 14, 'required_finalizer_seals_verified': 30,
            'durable_stages': [verified] + [{'synthetic_unused_terminal_header_slot': i} for i in range(16)],
            'synthetic_terminal_header_not_actual_grid_execution': True})
        outer_dir = self.ops / 'wait4_launcher'; outer_dir.mkdir()
        api.write_new(outer_dir / 'WAIT4_COMPLETE.json', {
            'schema': 'hepta.fullstudy.execution06-outer-wait4.1', 'config': self.config,
            'exit_code': 0, 'wait_status': 0, 'primary_complete': complete,
            'child_identity': self.owner, 'waited_pid': self.owner['pid'],
            'measuring_parent_identity': measuring, 'detached_start': ready,
            'synthetic_test_fixture_not_actual_measurement': True})
        with mock.patch.object(api, 'proc_identity', side_effect=RuntimeError('Departed process must not be required')):
            health = self.health()
            state = api.accepted('01_A-17', self.config, health)
        self.assertEqual(state['health']['basis'], 'PRIMARY_OUTER_AND_DETACHED_COMPLETE')
        self.rewrite(returned['path'], {**api.bound(returned), 'target_exit_code': 7})
        with self.assertRaisesRegex(RuntimeError, 'successful target return'):
            self.health()
        self.assertFalse(self.output.exists())

    def test_atomic_evidence_is_exclusive_and_not_overwritten(self):
        path = self.base / 'ATOMIC.json'
        first = api.write_new(path, {'version': 1})
        with self.assertRaisesRegex(RuntimeError, 'Existing evidence'):
            api.write_new(path, {'version': 2})
        self.assertEqual(api.descriptor(path), first)
        self.assertFalse(path.with_name('ATOMIC.json.writing').exists())


def main():
    global TEST_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    TEST_ROOT = Path(args.output).absolute()
    if not TEST_ROOT.is_relative_to(DEV) or TEST_ROOT == DEV:
        raise RuntimeError('Tests must remain inside the separate DEV directory')
    TEST_ROOT.mkdir(parents=True, exist_ok=False)
    api.write_new(TEST_ROOT / 'SYNTHETIC_TEST_SUITE.json', {
        'schema': 'hepta.execution06.retirement-test-scope.1', 'production_mutations': 0,
        'actual_scientific_execution': 0, 'actual_library_calls': 0,
        'all_fixture_remote_and_inner_WAIT4_records_are_synthetic': True,
        'actual_external_step_suite_WAIT4_is_separate': True})
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RetirementTests))
    receipt = {'schema': 'hepta.execution06.retirement-test-result.1', 'tests': result.testsRun,
               'failures': len(result.failures), 'errors': len(result.errors), 'success': result.wasSuccessful(),
               'test_code': api.descriptor(__file__), 'retirement_code': api.descriptor(SCRIPT),
               'production_mutations': 0, 'science_or_Library_operations': 0}
    api.write_new(TEST_ROOT / 'TEST_RESULT.json', receipt)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()

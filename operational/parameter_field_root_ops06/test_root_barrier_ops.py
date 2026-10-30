"""Local/synthetic glue tests. No actual Library operation or production ACK.

All simulated service/WAIT4/ACK fixtures are beneath explicitly marked test
case directories. The one real inner external_step measures a local print-only
Python process. The outer test-suite WAIT4 is separately real engineering cost.
"""
import argparse
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.dont_write_bytecode = True
RECOVERY = Path('/workspace/scratch/178ced6a501f/execution06_recovery_20261030')
GLUE = RECOVERY / 'root_barrier_ops.py'
spec = importlib.util.spec_from_file_location('external_root_barrier_ops06', GLUE)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
sys.path.insert(0, str(api.SOURCE))
from operational.parameter_field_recovery06 import archive_io as frozen

TEST_ROOT = None


class BarrierTests(unittest.TestCase):
    def setUp(self):
        need_root = TEST_ROOT
        if need_root is None:
            raise RuntimeError('Pass an explicit --output directory under execution06 recovery')
        self.base = need_root / self._testMethodName
        self.base.mkdir(parents=True, exist_ok=False)
        self.ops = self.base / 'synthetic_ops'
        self.ops.mkdir()
        self.root = self.ops / 'root_archive_io'
        self.empty = self.ops / 'empty_cwd'
        self.empty.mkdir()
        for mod, key, value in ((api, 'OPS', self.ops), (api, 'ROOT', self.root),
                                (api, 'ENGINEERING', self.root / '_engineering'),
                                (api, 'EMPTY_CWD', self.empty),
                                (frozen, 'OPS', self.ops), (frozen, 'ROOT', self.root)):
            patch = mock.patch.object(mod, key, value)
            patch.start()
            self.addCleanup(patch.stop)
        api.write(self.base / 'SYNTHETIC_TEST_FIXTURE.json', {
            'scope': 'Only local synthetic metadata/remote identities/receipts; not execution06 production evidence',
            'actual_library_calls': 0, 'actual_scientific_execution': 0,
            'simulated_wait4_records_are_not_measurements': True,
            'real_inner_measurement_only_in_named_print_process_case': True})
        self.stage_name = '01_A-17'
        self.stage = self.ops / 'durable' / self.stage_name
        self.stage.mkdir(parents=True)
        self.items = []
        for name in ('part-0000.tar.gz', 'MANIFEST.json'):
            path = self.stage / name
            path.write_text('synthetic-test-bytes-' + name + '\n')
            self.items.append(api.descriptor(path))
        request_value = {'schema': 'hepta.fullstudy.library-archive-request.1',
            'state': 'AWAITING_EXTERNAL_UPLOAD_AND_REMOTE_READBACK',
            'required_ack_schema': 'hepta.fullstudy.library-archive-ack.1',
            'binding': {'execution_episode': api.EPISODE, 'sequence': 1, 'label': 'A-17', 'completed_jobs': ['A-17']},
            'items': self.items}
        self.request = api.write(self.stage / 'REQUEST.json', request_value)
        self.request_input = self.base / 'REQUEST_DESCRIPTOR.json'
        api.write(self.request_input, self.request)
        live = api.proc_identity(os.getpid())
        legacy = {'pid': live['pid'], 'start_ticks': str(live['start_ticks']),
                  'process_group': live['pgid'], 'session': live['sid'], 'state': 'S'}
        api.write(self.ops / 'STATUS.json', {'schema': 'hepta.fullstudy.execution06-status.1',
            'execution_episode': api.EPISODE, 'phase': 'await_durable_ack_A-17',
            'pid': os.getpid(), 'identity': legacy,
            'awaiting_durable': {'request': self.request, 'ack_path': str(self.stage / 'ACK.json')}})
        startup = self.ops / 'supervisor_run'
        startup.mkdir()
        started = time.monotonic() - 1
        api.write(startup / 'START_POLICY.json', {'schema': 'hepta.execution06.supervisor-start-policy.1',
            'execution_episode': api.EPISODE, 'source_root': str(api.SOURCE), 'ops_root': str(self.ops),
            'supervisor_identity': live, 'started_monotonic': started,
            'deadline_monotonic': started + 43200.0, 'oom_baseline': {'oom': 0, 'oom_kill': 0}})
        self.folder_path = self.base / 'FOLDER_TOOLRESPONSE.json'
        self.folder_payload = {'results': [{'operation': 'create_folder', 'status': 'succeeded',
            'error_code': None, 'directory_id': 'synthetic-actual-returned-directory',
            'path': '/SYNTHETIC-ONLY/' + self.stage_name}], 'warnings': []}
        api.write(self.folder_path, self.envelope(self.folder_payload))
        self.work = self.root / self.stage_name
        self.upload_args = SimpleNamespace(stage=self.stage_name, request_descriptor=str(self.request_input),
            folder_response=str(self.folder_path), directory_id='synthetic-actual-returned-directory',
            upload_stdout=str(api.ENGINEERING / (self.stage_name + '_upload') / 'helper.stdout.log'))
        self.calls = []
        self.partial_upload = False
        self.transfer_nonzero = False
        self.transfer_wrong_stdout = False
        self.transfer_no_wait4 = False
        self.change_plan = False
        self.actual_subprocess_run = api.subprocess.run

    @staticmethod
    def envelope(payload):
        return {'content': [{'type': 'text', 'text': 'Synthetic test only.'}],
                'structuredContent': payload, 'isError': False}

    def measured_fixture(self, command, **kwargs):
        """Simulate execution only inside a marked fixture; never call a helper."""
        self.calls.append(list(command))
        self.assertEqual(command[:3], [api.VENV, '-B', str(api.EXTERNAL_STEP)])
        end = command.index('--')
        fields = dict(zip(command[3:end:2], command[4:end:2]))
        directory = Path(fields['--directory'])
        self.assertTrue(directory.is_relative_to(self.base))
        self.assertEqual(fields['--cwd'], str(self.empty))
        directory.mkdir(parents=True, exist_ok=False)
        argv = command[end + 1:]
        stdin = api.descriptor(fields['--stdin-file']) if '--stdin-file' in fields else None
        intent = api.write(directory / 'INTENT.json', {
            'schema': 'hepta.execution04.root-engineering-intent.1', 'argv': argv,
            'cwd': str(self.empty), 'stdin': stdin, 'automatic_retry': False,
            'synthetic_test_fixture_not_actual_measurement': True})
        stream = io.StringIO()
        code = 0
        transfer = argv[2] == str(api.HELPERS / 'library_file_transfer.py')
        with contextlib.redirect_stdout(stream):
            if argv[2] == str(api.ARCHIVE_IO):
                with mock.patch.object(sys, 'argv', [str(api.ARCHIVE_IO), *argv[3:]]):
                    if argv[3] == 'ack':
                        with mock.patch.object(frozen, 'verify_ack', return_value={
                                'synthetic_frozen_verifier_fixture': True,
                                'scope': 'ACK byte/identity walk is real; aggregate archive gate is simulated'}):
                            frozen.main()
                    else:
                        frozen.main()
            elif argv[2] == str(api.HELPERS / 'library_upload.py'):
                expected = api.read(stdin['path'])
                self.assertEqual([r['local_path'] for r in expected['uploads']], [x['path'] for x in self.items])
                rows = []
                for index, row in enumerate(expected['uploads']):
                    identity = 'synthetic-library-' + str(index)
                    os.setxattr(row['local_path'], 'user.library-file-id', identity.encode())
                    rows.append({'local_path': row['local_path'], 'purpose': 'create_library_file',
                        'status': 'unknown' if self.partial_upload and index == 0 else 'succeeded',
                        'local_metadata_applied': True, 'file_id': 'synthetic-file-' + str(index),
                        'file_name': Path(row['local_path']).name, 'library_file_id': identity,
                        'current_version_number': 0})
                print(json.dumps({'results': rows}))
            elif transfer:
                transfer_value = api.read(stdin['path'])
                output = Path(argv[4])
                self.assertTrue(output.is_relative_to(self.work / 'readback'))
                if self.transfer_nonzero:
                    code = 7
                else:
                    if argv[3] == 'materialize':
                        output.parent.mkdir(parents=True, exist_ok=True)
                        source = next(item for item in self.items if Path(item['path']).name == output.name)
                        output.write_bytes(Path(source['path']).read_bytes())
                    os.setxattr(output, 'user.library-file-id', transfer_value['library_file_id'].encode())
                    print(str(output) + ('.wrong' if self.transfer_wrong_stdout else ''))
            else:
                self.fail('Unexpected simulated command: ' + repr(argv))
        if self.change_plan and len(argv) > 3 and argv[3] == 'prepare-transfers':
            plan_path = self.work / 'READBACK_PLAN.json'
            value = api.read(plan_path)
            value['items'][0]['external_step_argv'][-1] += '.changed'
            plan_path.write_text(json.dumps(value))
            result = {'readback_plan': api.descriptor(plan_path), 'item_count': len(self.items), 'remote_calls_performed': 0}
            stream = io.StringIO(json.dumps(result) + '\n')
        out = directory / 'helper.stdout.log'
        err = directory / 'helper.stderr.log'
        out.write_text(stream.getvalue())
        err.write_text('synthetic failure\n' if code else '')
        if not (transfer and self.transfer_no_wait4):
            api.write(directory / 'WAIT4.json', {
                'schema': 'hepta.execution04.root-engineering-wait4.1', 'complete': True,
                'command_success': code == 0, 'child': {'exit_code': code}, 'intent': intent,
                'stdout': api.descriptor(out), 'stderr': api.descriptor(err),
                'synthetic_test_fixture_not_actual_measurement': True})
        kwargs['stdout'].write(b'SYNTHETIC external_step fixture; not a measurement\n')
        return SimpleNamespace(returncode=code)

    def simulate_upload(self):
        with mock.patch.object(api.subprocess, 'run', side_effect=self.measured_fixture):
            return api.upload(self.upload_args)

    def materialize_input(self, workspace=False):
        saved = api.read(self.work / 'UPLOAD_VERIFIED.json')
        transfers = []
        for item in saved['items']:
            remote = item['remote_identity']
            row = {key: remote[key] for key in ('file_id', 'file_name', 'library_file_id')}
            row.update({'current_version_number': remote['version'], 'size_bytes': item['local']['bytes']})
            if workspace:
                output = self.work / 'readback' / row['file_name']
                output.parent.mkdir(exist_ok=True, parents=True)
                output.write_bytes(Path(item['local']['path']).read_bytes())
                row['workspace_path'] = str(output)
            else:
                row['download_url'] = 'https://synthetic.invalid/never-requested'
            transfers.append(row)
        self.materialize = self.base / 'MATERIALIZE_TOOLRESPONSE.json'
        api.write(self.materialize, self.envelope({'transfers': transfers, 'unavailable_items': [],
                  'partial_bindings': [], 'warnings': [],
                  'destination': {'directory': str(self.work / 'readback')}}))
        return SimpleNamespace(stage=self.stage_name, materialize_response=str(self.materialize))

    def simulate_readback(self, workspace=False):
        self.simulate_upload()
        args = self.materialize_input(workspace)
        with mock.patch.object(api.subprocess, 'run', side_effect=self.measured_fixture):
            return api.readback(args)

    def test_actual_frozen_dependency_pins_and_ast_are_readable(self):
        value = api.code_identity()
        self.assertEqual(len(value['frozen_dependencies']), 9)
        self.assertEqual(api.archive_code(value), frozen.code_identity())
        import ast
        ast.parse(GLUE.read_text())

    def test_status_without_ops_is_read_only(self):
        absent = self.base / 'never-created-ops'
        before = sorted(str(p) for p in self.base.rglob('*'))
        with mock.patch.object(api, 'OPS', absent):
            value = api.status()
        self.assertFalse(value['ops_exists'])
        self.assertEqual(before, sorted(str(p) for p in self.base.rglob('*')))

    def test_status_current_await_is_read_only_and_bound(self):
        before = sorted(str(p) for p in self.base.rglob('*'))
        result = api.status()
        self.assertEqual(result['actual_request'], self.request)
        self.assertEqual(result['awaiting_stage'], self.stage_name)
        self.assertEqual(before, sorted(str(p) for p in self.base.rglob('*')))
        self.assertFalse(self.root.exists())

    def test_folder_requires_full_response_exact_actual_id_and_no_partial(self):
        expected = {'directory_id': self.upload_args.directory_id, 'folder_path': '/SYNTHETIC-ONLY/01_A-17'}
        self.assertEqual(api.folder_identity(self.folder_path, self.stage_name, self.upload_args.directory_id), expected)
        cases = []
        for field, value in (('warnings', ['uncertain']), ('partial_bindings', ['uncertain'])):
            payload = copy.deepcopy(self.folder_payload)
            payload[field] = value
            cases.append(self.envelope(payload))
        cases += [self.folder_payload, {**self.envelope(self.folder_payload), 'isError': True}]
        for index, value in enumerate(cases):
            path = self.base / f'BAD_FOLDER_{index}.json'
            api.write(path, value)
            with self.assertRaises(RuntimeError):
                api.folder_identity(path, self.stage_name, self.upload_args.directory_id)
        with self.assertRaises(RuntimeError):
            api.folder_identity(self.folder_path, self.stage_name, 'synthetic-wrong-id')
        self.assertFalse(self.root.exists())

    def test_upload_is_one_whole_ordered_call_and_requires_exact_stdout(self):
        result = self.simulate_upload()
        self.assertEqual(len(self.calls), 3)
        upload_calls = [x for x in self.calls if x[x.index('--') + 3] == str(api.HELPERS / 'library_upload.py')]
        self.assertEqual(len(upload_calls), 1)
        final = self.calls[-1]
        self.assertEqual(final[final.index('--upload-stdout') + 1], self.upload_args.upload_stdout)
        self.assertEqual(result['materialize_arguments_value']['destination'], {'directory': str(self.work / 'readback')})
        self.assertFalse((self.stage / 'ACK.json').exists())
        with self.assertRaises(RuntimeError):
            self.simulate_upload()
        self.assertEqual(len(self.calls), 3)

    def test_wrong_upload_stdout_fails_before_work_or_helper(self):
        self.upload_args.upload_stdout = str(self.base / 'guessed-output.json')
        with self.assertRaisesRegex(RuntimeError, 'exact forthcoming'):
            self.simulate_upload()
        self.assertFalse(self.work.exists())
        self.assertEqual(self.calls, [])

    def test_existing_work_stops_before_prepare_upload(self):
        self.work.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'Existing path'):
            self.simulate_upload()
        self.assertEqual(self.calls, [])

    def test_partial_upload_even_exit_zero_has_no_readback_or_retry(self):
        self.partial_upload = True
        with self.assertRaisesRegex(RuntimeError, 'failed, partial, unknown'):
            self.simulate_upload()
        self.assertEqual(len(self.calls), 2)
        self.assertTrue((api.ENGINEERING / (self.stage_name + '_upload_phase') / 'FAILED.json').exists())
        self.assertFalse((self.work / 'MATERIALIZE_ARGS.json').exists())
        self.assertFalse((self.stage / 'ACK.json').exists())
        with self.assertRaises(RuntimeError):
            self.simulate_upload()
        self.assertEqual(len(self.calls), 2)

    def test_changed_awaiting_request_stops_before_any_action(self):
        value = api.read(self.ops / 'STATUS.json')
        value['awaiting_durable']['request']['sha256'] = '0' * 64
        (self.ops / 'STATUS.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'descriptor differs'):
            self.simulate_upload()
        self.assertEqual(self.calls, [])

    def test_materialize_partial_result_is_rejected_without_transfer(self):
        self.simulate_upload()
        args = self.materialize_input()
        value = api.read(self.materialize)
        value['structuredContent']['partial_bindings'] = [{'synthetic': 'unknown'}]
        self.materialize.write_text(json.dumps(value))
        with mock.patch.object(api.subprocess, 'run', side_effect=self.measured_fixture):
            with self.assertRaisesRegex(RuntimeError, 'Partial'):
                api.readback(args)
        self.assertEqual(len(self.calls), 3)
        self.assertFalse((self.work / 'READBACK_PLAN.json').exists())

    def test_readback_uses_each_exact_plan_argv_and_plain_text_then_candidate_only(self):
        result = self.simulate_readback()
        plan = api.read(self.work / 'READBACK_PLAN.json')
        self.assertEqual(self.calls[4:6], [job['external_step_argv'] for job in plan['items']])
        for job in plan['items']:
            value = api.read(job['wait4_path'])
            self.assertEqual(Path(value['stdout']['path']).read_text().strip(), job['expected_output_path'])
        self.assertEqual(len(self.calls), 7)
        self.assertFalse(result['actual_ack_published'])
        self.assertTrue(Path(result['candidate']['path']).is_file())
        self.assertFalse((self.stage / 'ACK.json').exists())
        self.assertNotIn('--publish-ack', self.calls[-1])

    def test_workspace_materialization_uses_exact_apply_xattrs(self):
        result = self.simulate_readback(workspace=True)
        self.assertFalse(result['actual_ack_published'])
        plan = api.read(self.work / 'READBACK_PLAN.json')
        self.assertEqual([row['helper_argv'][3] for row in plan['items']], ['apply-xattrs', 'apply-xattrs'])

    def test_modified_plan_argv_is_rejected_before_transfer(self):
        self.simulate_upload()
        args = self.materialize_input()
        self.change_plan = True
        with mock.patch.object(api.subprocess, 'run', side_effect=self.measured_fixture):
            with self.assertRaisesRegex(RuntimeError, 'exact READBACK_PLAN argv'):
                api.readback(args)
        self.assertEqual(len(self.calls), 4)
        self.assertFalse((self.work / 'ACK_CANDIDATE.json').exists())

    def test_nonzero_transfer_is_not_retried_and_cannot_create_candidate(self):
        self.transfer_nonzero = True
        with self.assertRaisesRegex(RuntimeError, 'External step failed'):
            self.simulate_readback()
        self.assertEqual(len(self.calls), 5)
        self.assertFalse((self.work / 'ACK_CANDIDATE.json').exists())
        self.assertTrue((api.ENGINEERING / (self.stage_name + '_readback_phase') / 'FAILED.json').exists())

    def test_missing_wait4_is_unknown_and_stops_without_candidate(self):
        self.transfer_no_wait4 = True
        with self.assertRaises(FileNotFoundError):
            self.simulate_readback()
        self.assertEqual(len(self.calls), 5)
        self.assertFalse((self.work / 'ACK_CANDIDATE.json').exists())

    def test_plain_stdout_wrong_path_is_rejected_without_next_transfer(self):
        self.transfer_wrong_stdout = True
        with self.assertRaisesRegex(RuntimeError, 'plain-text'):
            self.simulate_readback()
        self.assertEqual(len(self.calls), 5)
        self.assertFalse((self.work / 'ACK_CANDIDATE.json').exists())

    def test_publish_requires_explicit_flag_and_reviewed_sha_and_never_claims_acceptance(self):
        result = self.simulate_readback()
        args = SimpleNamespace(stage=self.stage_name, publish_ack=False,
                               expected_candidate_sha256=result['candidate']['sha256'])
        with self.assertRaisesRegex(RuntimeError, 'explicit'):
            api.publish(args)
        args.publish_ack = True
        args.expected_candidate_sha256 = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'reviewed candidate'):
            api.publish(args)
        self.assertEqual(len(self.calls), 7)
        args.expected_candidate_sha256 = result['candidate']['sha256']
        with mock.patch.object(api.subprocess, 'run', side_effect=self.measured_fixture):
            published = api.publish(args)
        self.assertEqual(len(self.calls), 8)
        self.assertIn('--publish-ack', self.calls[-1])
        self.assertFalse(published['supervisor_acceptance_claimed'])
        self.assertEqual(api.descriptor(self.stage / 'ACK.json'), published['actual_ack'])
        self.assertFalse((self.stage / 'ACK_VERIFIED.json').exists())
        with self.assertRaises(RuntimeError):
            api.publish(args)
        self.assertEqual(len(self.calls), 8)

    def test_original_supervisor_parent_change_rejected_before_helper(self):
        path = self.ops / 'supervisor_run/START_POLICY.json'
        value = api.read(path)
        value['supervisor_identity']['parent_pid'] += 1
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'including original parent'):
            self.simulate_upload()
        self.assertEqual(self.calls, [])

    def test_deadline_exhaustion_rejected_before_helper(self):
        path = self.ops / 'supervisor_run/START_POLICY.json'
        value = api.read(path)
        value['deadline_monotonic'] = time.monotonic() - 1
        value['started_monotonic'] = value['deadline_monotonic'] - 43200
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'deadline'):
            self.simulate_upload()
        self.assertEqual(self.calls, [])

    def test_real_external_step_print_process_yields_actual_wait4_plain_stdout(self):
        directory = self.base / 'REAL_PRINT_ONLY_WAIT4'
        expected_output = str(self.base / 'plain_path_no_file_created')
        argv = [api.VENV, '-B', '-c', 'import sys; print(sys.argv[1])', expected_output]
        command = api.step_argv(directory, argv)
        with (self.base / 'actual.wrapper.stdout.log').open('xb') as out, (self.base / 'actual.wrapper.stderr.log').open('xb') as err:
            completed = self.actual_subprocess_run(command, cwd=self.empty, stdin=api.subprocess.DEVNULL,
                                                   stdout=out, stderr=err, check=False)
        self.assertEqual(completed.returncode, 0)
        measured = api.validate_wait4(directory / 'WAIT4.json', argv, None, directory)
        self.assertEqual(Path(measured['stdout']['path']).read_text().strip(), expected_output)
        self.assertFalse(Path(expected_output).exists())
        value = api.read(measured['wait4']['path'])
        self.assertNotIn('synthetic_test_fixture_not_actual_measurement', value)
        self.assertEqual(value['child']['exit_code'], 0)

    def test_atomic_exclusive_metadata_and_symlink_refusal(self):
        path = self.base / 'EXCLUSIVE.json'
        original = api.write(path, {'actual_local_test': True})
        with self.assertRaisesRegex(RuntimeError, 'Existing path'):
            api.write(path, {'overwrite': True})
        self.assertEqual(api.descriptor(path), original)
        alias = self.base / 'ALIAS.json'
        alias.symlink_to(path)
        with self.assertRaisesRegex(RuntimeError, 'aliases'):
            api.read(alias)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args, rest = parser.parse_known_args()
    TEST_ROOT = Path(args.output).absolute()
    if not TEST_ROOT.is_relative_to(RECOVERY) or TEST_ROOT != TEST_ROOT.resolve():
        raise SystemExit('Test output must remain under execution06 recovery')
    TEST_ROOT.mkdir(parents=True, exist_ok=False)
    unittest.main(argv=[sys.argv[0], *rest])

"""Synthetic file/runner controls only; these tests execute no native study."""
import copy
import hashlib
import io
import json
from contextlib import nullcontext
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ordinary_start_observation as reader
import run_study

EPOCH = '00000000-0000-4000-8000-000000000120'
RELEASE = 'ordinary-source'


def status(lifecycle):
    active = lifecycle != 'stopped'
    generation = {'stopped': 4, 'starting': 5, 'running': 6}[lifecycle]
    row = dict(agent_id=reader.OWNER, control_revision=int(active), lifecycle=lifecycle,
               lifecycle_generation=generation, active=active, healthy=lifecycle == 'running',
               process_id=321 if active else None, spawn_generation=5 if active else None,
               runtime_generation=generation if active else None,
               current_release=RELEASE if active else None, previous_release=None,
               release_change_pending=False, matrix=dict(active=False))
    row['control_fence'] = {k: row[k] for k in ('agent_id', 'lifecycle', 'lifecycle_generation',
        'spawn_generation', 'runtime_generation', 'current_release', 'previous_release', 'release_change_pending')}
    row['control_fence'].update(supervisor_epoch=EPOCH, state_digest=str(generation) * 64)
    return row


def evidence(unknown=False):
    before, starting, running = (status(value) for value in ('stopped', 'starting', 'running'))
    request = dict(schema=reader.SCHEMA, started_at_unix_micros=1000, supervisor_epoch=EPOCH,
                   release=RELEASE, spawn_generation=5, start_calls=1, readbacks=[], before=before,
                   request=dict(fence=copy.deepcopy(before['control_fence']), release_id=RELEASE))
    result = dict(state='unknown', error=reader.READ_TIMEOUT) if unknown else dict(state='accepted',
        response=dict(operation='start', accepted_state_digest=before['control_fence']['state_digest'],
                      agent=starting, production_receipt=None))
    response = copy.deepcopy(request)
    response['start_result'] = result
    final = copy.deepcopy(response)
    readbacks = []
    if unknown:
        readbacks += [dict(monotonic_elapsed_micros=1, status=copy.deepcopy(before)),
                      dict(monotonic_elapsed_micros=2, error=reader.READ_TIMEOUT)]
    readbacks += [dict(monotonic_elapsed_micros=100, status=starting),
                  dict(monotonic_elapsed_micros=200, status=running)]
    final.update(readbacks=readbacks, result=dict(state='ready', status=copy.deepcopy(running)),
                 monotonic_elapsed_micros=210)
    return dict(zip(reader.FILES, [request, response, final, copy.deepcopy(running),
        dict(process_id=123, health=dict(ready=True, supervisor_epoch=EPOCH, process_id=123),
             binary_sha256='a' * 64, production_authority_build_required=True),
        dict(source_release=RELEASE, binary_sha256='b' * 64),
        dict(schema='hepta.ordinary-native-upgrade-study.v1', source_spawn_generation=5)]))


def write_evidence(root, rows):
    root.mkdir(exist_ok=True)
    for name, value in rows.items():
        (root / name).write_text(json.dumps(value) + '\n', encoding='utf-8')


class StartObservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def rejected(self, rows, message=None):
        write_evidence(self.root, rows)
        with self.assertRaises(reader.StartObservationError) as caught:
            reader.verify_start_observation(self.root)
        if message:
            self.assertIn(message, str(caught.exception))
        return caught.exception

    def test_accepted_and_exact_timeout_readbacks_bind_all_actual_bytes(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown):
                write_evidence(self.root, evidence(unknown))
                result = reader.verify_start_observation(self.root)
                self.assertEqual(result['state'], 'verified')
                self.assertEqual(result['artifact_sha256'], {
                    name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in reader.FILES})

    def test_missing_every_required_file_is_rejected(self):
        for name in reader.FILES:
            with self.subTest(name=name):
                write_evidence(self.root, evidence())
                (self.root / name).unlink()
                with self.assertRaises(reader.StartObservationError) as caught:
                    reader.verify_start_observation(self.root)
                self.assertIn(name, str(caught.exception))

    def test_twice_start_and_boolean_one_cannot_pass_any_phase(self):
        for name in reader.FILES[:3]:
            for value in (2, True):
                rows = evidence()
                rows[name]['start_calls'] = value
                with self.subTest(name=name, value=value):
                    self.rejected(rows)

    def test_wrong_supervisor_epoch_or_health_pid_rejected(self):
        for target in ('trace', 'health_epoch', 'health_pid', 'boolean_pid', 'nil_epoch'):
            rows = evidence()
            if target == 'trace':
                rows[reader.FILES[2]]['readbacks'][-1]['status']['control_fence']['supervisor_epoch'] = reader.OWNER
            elif target == 'health_epoch':
                rows['supervisor-process.json']['health']['supervisor_epoch'] = reader.OWNER
            elif target == 'nil_epoch':
                rows = json.loads(json.dumps(rows).replace(EPOCH, str(reader.uuid.UUID(int=0))))
            else:
                rows['supervisor-process.json']['health']['process_id'] = True if target == 'boolean_pid' else 124
            with self.subTest(target=target):
                self.rejected(rows)

    def test_revision_not_exactly_one_or_boolean_revision_rejected(self):
        for value in (0, 2, True, None):
            rows = evidence()
            rows[reader.FILES[2]]['readbacks'][-1]['status']['control_revision'] = value
            with self.subTest(value=value):
                self.rejected(rows)

    def test_final_identity_and_source_service_cannot_diverge(self):
        for name in ('agent_id', 'process_id', 'current_release', 'spawn_generation', 'healthy'):
            rows = evidence()
            rows['source-service-status.json'][name] = {
                'agent_id': EPOCH, 'process_id': 999, 'current_release': 'other',
                'spawn_generation': 9, 'healthy': False}[name]
            with self.subTest(field=name):
                self.rejected(rows, 'final/source-service status identity')

    def test_final_result_boolean_revision_is_not_equal_to_numeric_one(self):
        rows = evidence()
        rows[reader.FILES[2]]['result']['status']['control_revision'] = True
        self.rejected(rows, 'final/source-service status identity')

    def test_rejected_and_indeterminate_cannot_be_disguised_as_unknown(self):
        for message in (reader.READ_TIMEOUT + ' ', 'supervisord read timed out',
                        'invalid supervisor value: supervisord rejected request (stale_control_fence): selected Agent changed; refresh before retry',
                        'invalid supervisor value: supervisord rejected request (operation_indeterminate): operation outcome is indeterminate; refresh before retry'):
            rows = evidence(unknown=True)
            for name in reader.FILES[1:3]:
                rows[name]['start_result']['error'] = message
            with self.subTest(message=message):
                self.rejected(rows, 'only original exact read timeout')

    def test_failed_start_label_cannot_pass_even_with_ready_status(self):
        rows = evidence(unknown=True)
        for name in reader.FILES[1:3]:
            rows[name]['start_result']['state'] = 'failed'
        self.rejected(rows, 'only original exact read timeout')

    def test_accepted_receipt_must_bind_original_operation_and_fence(self):
        for field, value in [('operation', 'kill'), ('accepted_state_digest', 'f' * 64),
                             ('production_receipt', {'fake': True})]:
            rows = evidence()
            for name in reader.FILES[1:3]:
                rows[name]['start_result']['response'][field] = value
            with self.subTest(field=field):
                self.rejected(rows, 'original Start accepted receipt')

    def test_timeout_readback_then_revision_regression_is_rejected(self):
        rows = evidence(unknown=True)
        final = rows[reader.FILES[2]]
        final['readbacks'].insert(-1, dict(monotonic_elapsed_micros=150, status=status('stopped')))
        self.rejected(rows, 'regressed')

    def test_wrong_running_generation_pid_and_readback_deadline_rejected(self):
        for field, value in [('runtime_generation', 5), ('process_id', 999), ('time', 60_000_000)]:
            rows = evidence()
            observed = rows[reader.FILES[2]]['readbacks'][-1]
            if field == 'time':
                observed['monotonic_elapsed_micros'] = value
                rows[reader.FILES[2]]['monotonic_elapsed_micros'] = value + 1
            else:
                observed['status'][field] = value
                if field == 'runtime_generation':
                    observed['status']['control_fence'][field] = value
            with self.subTest(field=field):
                self.rejected(rows)

    def test_duplicate_oversized_nonfinite_and_symlink_material_rejected(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"value":NaN}', b'x' * (reader.JSON_LIMIT + 1)):
            write_evidence(self.root, evidence())
            (self.root / reader.FILES[0]).write_bytes(raw)
            with self.subTest(raw_size=len(raw)), self.assertRaises(reader.StartObservationError):
                reader.verify_start_observation(self.root)
        write_evidence(self.root, evidence())
        (self.root / reader.FILES[0]).unlink()
        (self.root / reader.FILES[0]).symlink_to(self.root / reader.FILES[1])
        with self.assertRaises(reader.StartObservationError):
            reader.verify_start_observation(self.root)

    def test_runner_keeps_receipt_and_log_when_reader_or_native_fails(self):
        # Popen is mocked: synthetic files exercise wiring, never native counts.
        binary = self.root / 'synthetic-nonexecutable-binary'
        binary.write_bytes(b'not a native executable')
        cases = [(0, True, False, 'source Start evidence failed'),
                 (7, False, False, 'native study failed'),
                 (0, False, True, 'source Start evidence failed')]
        for index, (code, missing, defective_reader, expected) in enumerate(cases):
            output = self.root / f'run-{index}'
            def launch(command, **kwargs):
                rows = evidence()
                if missing:
                    del rows[reader.FILES[0]]
                write_evidence(output, rows)
                kwargs['stdout'].write(b'synthetic runner I/O only; no native execution\n')
                class Child:
                    def poll(self):
                        return code
                    def wait(self):
                        return code
                return Child()
            argv = ['run_study.py', '--scenario', 'ordinary-upgrade', '--binary', str(binary), '--output', str(output)]
            defect = patch.object(run_study, 'verify_start_observation', side_effect=RuntimeError('synthetic reader failure')) if defective_reader else nullcontext()
            with self.subTest(code=code, defective_reader=defective_reader), patch.object(run_study.sys, 'argv', argv), defect, \
                    patch.object(run_study.subprocess, 'Popen', side_effect=launch), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, expected):
                    run_study.main()
            receipt = json.loads(output.with_suffix('.execution.json').read_text())
            self.assertEqual(receipt['native_exit_code'], code)
            self.assertTrue(receipt['binary_unchanged'])
            self.assertEqual(receipt['log_sha256'], hashlib.sha256(output.with_suffix('.native.log').read_bytes()).hexdigest())
            self.assertIn('wall_ns', receipt)
            self.assertEqual(receipt['source_start_observation']['state'], 'failed' if missing or defective_reader else 'verified')


if __name__ == '__main__':
    unittest.main()

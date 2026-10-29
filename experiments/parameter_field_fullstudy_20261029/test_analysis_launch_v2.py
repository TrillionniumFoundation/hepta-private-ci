"""Synthetic admission, provenance, process ownership and guarded report tests."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import analysis_launch_v2 as launch
from . import resource_v2 as resource


def memory_ok(*args, **kwargs):
    return {"allowed": True, "oom": 8, "oom_kill": 4, "effective_current": 0, "limit": 8 * resource.GiB}


class AnalysisLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='analysis-launch-test-', dir='/workspace/scratch/178ced6a501f')
        self.base, self.root = Path(self.temp.name), Path(self.temp.name) / 'raw'
        self.root.mkdir()
        self.patches = [patch.object(resource, 'memory_admission', side_effect=memory_ok),
                        patch.object(launch, 'memory_admission', side_effect=memory_ok),
                        patch.object(launch, 'memory_profile', side_effect=memory_ok)]
        for item in self.patches:
            item.start()
        self.artifacts = {}
        def save(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, sort_keys=True))
            d = launch.descriptor(path)
            self.artifacts[d['path']] = d['sha256']
            return d
        self.save = save
        protocol = launch.descriptor(Path(launch.__file__).with_name('PROTOCOL.json'))
        self.artifacts[protocol['path']] = protocol['sha256']
        amendment = save(self.base / 'OPS.json', {
            'status': 'REGISTERED_PRE_ENDPOINT', 'execution_ready': True, 'attempt_id': 'attempt02',
            'raw_root': str(self.root), 'original_protocol': protocol,
            'proposed_resource_contract': {'global_raw_logical_bytes': 2 * resource.GiB,
                'minimum_private_allocatable_bytes': 256 * resource.MiB, 'C_training_evidence_bytes': 350 * resource.MiB},
            'concurrency': {'max_workers': 2, 'worker_reservation_bytes': 768 * resource.MiB,
                            'memory_margin_bytes': resource.GiB}})
        stages, seals, job_completions = {}, {}, {}
        for phase in launch.PHASES:
            stages[phase] = {'status': 'COMPLETE', 'runs': []}
            for seed in launch.SEEDS if phase in ('A', 'B', 'R') else (None,):
                token = f'{phase}-seed-{seed}' if seed is not None else f'{phase}-all'
                complete = f'stage_{phase}/seed-{seed}/COMPLETE.json' if seed is not None else f'stage_{phase}/COMPLETE.json'
                run = {'seed': seed}
                for key, rel in [('operation', f'operations/{token}.COMPLETE.json'), ('complete', complete)]:
                    run[key] = save(self.root / rel, {'complete': True, 'synthetic': True})
                    seals[run[key]['path']] = run[key]['sha256']
                stages[phase]['runs'].append(run)
                op = run['operation']
                name = f'{phase}-{seed}' if seed is not None else phase
                job_completions[name] = {**op, 'path': str(Path(op['path']).relative_to(self.root))}
            if phase in ('A', 'B', 'C'):
                folder = 'endpoint_evaluation' if phase == 'C' else 'endpoints'
                ep = save(self.root / f'stage_{phase}/{folder}/ENDPOINTS.json', {'synthetic': True})
                stages[phase]['endpoint'] = ep
                seals[ep['path']] = ep['sha256']
                job_completions[phase + '_endpoint'] = {**ep, 'path': str(Path(ep['path']).relative_to(self.root))}
        control = save(self.root / 'controller/EXECUTION.json', {'complete': True,
            'jobs': {key: {'complete': True, 'completion': job_completions[key]} for key in launch.JOB_IDS}})
        seals[control['path']] = control['sha256']
        inputs = save(self.base / 'INPUTS.json', {'schema': 'hepta.fullstudy.report-inputs.1',
            'attempt_id': 'attempt02', 'raw_root': str(self.root), 'protocol': protocol,
            'amendment': amendment, 'stages': stages})
        prefix = Path(launch.__file__).parent.relative_to(launch.ROOT)
        source_files = {str(prefix / (name + '.py')): launch.file_hash(launch.ROOT / prefix / (name + '.py'))
            for name in ('analysis_launch_v2', 'report_results', 'resource_v2', 'resource_io_v2', 'run_v2')}
        self.freeze = {'execution_kind': 'aggregate_analysis', 'allowed_phases': ['ANALYSIS'],
            'attempt_id': 'attempt02', 'operational_amendment_sha256': amendment['sha256'],
            'registered_commit': 'a' * 40, 'protocol_sha256': protocol['sha256'], 'source_files': source_files, 'report_module': launch.__package__ + '.report_results',
            'report_inputs': inputs, 'output_relative': 'aggregate_results', 'analysis_id': 'analysis01',
            'required_scientific_seals': seals, 'artifacts': dict(self.artifacts)}
        frozen = save(self.base / 'FREEZE.json', self.freeze)
        self.args = SimpleNamespace(root=str(self.root), inputs=inputs['path'], expected_sha256=inputs['sha256'],
            output=str(self.root / 'aggregate_results'), freeze=frozen['path'], freeze_sha256=frozen['sha256'],
            amendment=amendment['path'], amendment_sha256=amendment['sha256'], parent_pid=os.getppid())

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_exact_freeze_and_full_seal_population(self):
        launch.validate(self.args)
        self.assertEqual(len(self.freeze['required_scientific_seals']), 26)
        broken = dict(self.freeze)
        broken['source_files'] = dict(broken['source_files'])
        broken['source_files'].pop(next(k for k in broken['source_files'] if k.endswith('report_results.py')))
        self.args.freeze_sha256 = self.save(Path(self.args.freeze), broken)['sha256']
        with self.assertRaisesRegex(ValueError, 'closure incomplete'):
            launch.validate(self.args)

    def test_input_tamper_is_rejected(self):
        Path(self.args.inputs).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Frozen artifact differs'):
            launch.validate(self.args)

    def test_denied_admission_never_starts_worker_or_creates_report(self):
        with patch.object(launch, 'memory_admission', return_value={'allowed': False}), patch.object(launch.subprocess, 'Popen') as popen:
            self.assertEqual(launch.parent(self.args), 75)
            popen.assert_not_called()
        failure = launch.json_read(self.root / 'analysis_operations/analysis01/ADMISSION_FAILED.json')
        self.assertEqual(failure['workers_started'], 0)
        self.assertEqual(failure['scheduled_gradient_microsteps'], 0)
        self.assertFalse(Path(self.args.output).exists())

    def test_existing_worker_prevents_parent_admission(self):
        (self.root / 'ACTIVE_WORKERS.json').write_text(json.dumps({'workers': [{'pid': os.getpid()}]}))
        with patch.object(launch.subprocess, 'Popen') as popen, self.assertRaisesRegex(ValueError, 'empty worker registry'):
            launch.parent(self.args)
        popen.assert_not_called()

    def test_child_cannot_import_report_before_pid_registration(self):
        with patch.object(launch.time, 'monotonic', side_effect=[0., 6.]), patch.object(launch.importlib, 'import_module') as importer:
            with self.assertRaisesRegex(ValueError, 'not registered'):
                launch.child(self.args)
            importer.assert_not_called()

    def test_registered_child_uses_real_slot_and_guarded_output(self):
        control = self.root / 'analysis_operations/analysis01'
        control.mkdir(parents=True)
        (self.root / 'ACTIVE_WORKERS.json').write_text(json.dumps({'workers': [{'id': 'ANALYSIS', 'pid': os.getpid(),
            'reservation_bytes': 768 * resource.MiB, 'source_freeze_sha256': self.args.freeze_sha256,
            'report_inputs_sha256': self.args.expected_sha256}]}))
        registration, unused = launch.validate(self.args)
        def synthetic_report():
            with resource.training_slot(self.root, registration):
                Path(self.args.output).mkdir()
                (Path(self.args.output) / 'REPORT.md').write_text('synthetic report only')
                (Path(self.args.output) / 'RESULTS.json').write_text('{}')
        with patch.object(launch.importlib, 'import_module', return_value=SimpleNamespace(__name__='synthetic_report', main=synthetic_report)), patch.object(launch, 'ensure_loaded_closure'):
            self.assertEqual(launch.child(self.args), 0)
        receipt = launch.json_read(control / 'WORKER_COMPLETE.json')
        self.assertTrue(receipt['post_execution_storage_check'])
        self.assertGreater(receipt['process_peak_rss_bytes'], 0)
        output = Path(self.args.output) / 'RESULTS.json'
        self.assertGreater(output.stat().st_nlink, 1)

    def test_parent_registers_owned_pid_and_seals_outputs_and_clears_registry(self):
        def fake_process(*args, **kwargs):
            self.assertEqual(launch.active_workers(self.root), [])
            output = Path(self.args.output)
            output.mkdir()
            (output / 'REPORT.md').write_text('synthetic')
            (output / 'RESULTS.json').write_text(json.dumps({'status': 'COMPLETE', 'efficacy_artifacts_opened': True,
                'input_sha256': self.args.expected_sha256}))
            control = self.root / 'analysis_operations/analysis01'
            (control / 'WORKER_COMPLETE.json').write_text(json.dumps({**launch.binding(self.args, self.freeze),
                'complete': True, 'post_execution_storage_check': True, 'process_peak_rss_bytes': 1024, 'process_cpu_seconds_total': .01}))
            read, write = os.pipe()
            os.write(write, b'synthetic worker finished\n')
            os.close(write)
            return SimpleNamespace(pid=99999999, stdout=os.fdopen(read, 'rb'), returncode=0, poll=lambda: 0)
        with patch.object(launch.subprocess, 'Popen', side_effect=fake_process):
            self.assertEqual(launch.parent(self.args), 0)
        self.assertEqual(launch.active_workers(self.root), [])
        receipt = launch.json_read(self.root / 'analysis_operations/analysis01/COMPLETE.json')
        self.assertEqual(len(receipt['outputs']), 2)
        self.assertTrue(receipt['complete'])
        self.assertEqual(receipt['scheduled_gradient_microsteps'], 0)


    def test_child_failure_is_preserved_and_cannot_publish_complete(self):
        read, write = os.pipe()
        os.write(write, b'synthetic failure\n')
        os.close(write)
        process = SimpleNamespace(pid=99999999, stdout=os.fdopen(read, 'rb'), returncode=3, poll=lambda: 3)
        with patch.object(launch.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, 'exit code 3'):
                launch.parent(self.args)
        control = self.root / 'analysis_operations/analysis01'
        self.assertFalse((control / 'COMPLETE.json').exists())
        self.assertTrue((control / 'FAILED.json').is_file())
        self.assertEqual((control / 'worker.log').read_bytes(), b'synthetic failure\n')
        self.assertEqual(launch.active_workers(self.root), [])


    def test_only_pure_admission_retry_preserves_previous_receipt(self):
        with patch.object(launch, 'memory_admission', return_value={'allowed': False}), patch.object(launch.subprocess, 'Popen') as popen:
            self.assertEqual(launch.parent(self.args), 75)
            self.args.resume_admission = True
            self.assertEqual(launch.parent(self.args), 75)
            popen.assert_not_called()
        parent = self.root / 'analysis_operations'
        self.assertTrue((parent / 'analysis01_admission_001/ADMISSION_FAILED.json').is_file())
        self.assertTrue((parent / 'analysis01/ADMISSION_FAILED.json').is_file())
        (parent / 'analysis01/START.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'zero-worker admission'):
            launch.parent(self.args)

    def test_stale_controller_boolean_completion_does_not_authorize_analysis(self):
        path = self.root / 'controller/EXECUTION.json'
        value = launch.json_read(path)
        value['jobs']['A-17']['completion']['sha256'] = '0' * 64
        info = self.save(path, value)
        self.freeze['artifacts'][info['path']] = info['sha256']
        self.freeze['required_scientific_seals'][info['path']] = info['sha256']
        self.args.freeze_sha256 = self.save(Path(self.args.freeze), self.freeze)['sha256']
        with self.assertRaisesRegex(ValueError, 'completion identities differ'):
            launch.validate(self.args)


if __name__ == '__main__':
    unittest.main()

"""Synthetic opaque-payload populations, provenance and registration failure gates."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import register_summary_v2 as reg
from . import resource_v2 as resource

OPAQUE = b'opaque fixture: this is deliberately not scientific JSON, NPZ, or a checkpoint\n'


class SummaryRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='summary-registration-test-', dir='/workspace/scratch/178ced6a501f')
        self.base, self.root = Path(self.temp.name), Path(self.temp.name) / 'raw'
        self.root.mkdir()
        self.stages = {phase: {'status': 'COMPLETE', 'runs': []} for phase in reg.launcher.PHASES}
        self.artifacts = {}

    def tearDown(self):
        self.temp.cleanup()

    def save(self, path, value=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(OPAQUE if value is None else reg.encode(value))
        return reg.descriptor(path)

    def payloads(self):
        for phase in ('A', 'B', 'R'):
            for seed in reg.SEEDS:
                directory = self.root / f'stage_{phase}/seed-{seed}'
                self.stages[phase]['runs'].append({'seed': seed, 'complete': self.save(directory / 'COMPLETE.json')})
                if phase in ('A', 'B'):
                    for name in reg.ab_ids(phase):
                        if name.startswith(f'seed-{seed}-'):
                            for ext in ('.state', '.json'):
                                self.save(directory / 'paths' / (name + ext))
                    self.save(directory / 'paths/PATHS.json')
                if phase == 'A':
                    bank = directory / 'bank'
                    for name in ('BANK.json', 'trace.jsonl.gz'):
                        self.save(bank / name)
                    for stem in reg.stems():
                        self.save(bank / (stem + '.state'))
                        for action in range(4):
                            self.save(bank / f'{stem}-action-{action}.npz')
                    for mode in reg.METHODS[1:]:
                        for kind in ('head', 'bank'):
                            self.save(bank / f'{mode}-{kind}.npz')
                if phase == 'R':
                    for stem in reg.stems():
                        for action in range(4):
                            for ext in ('.bin.gz', '.trace.json.gz'):
                                self.save(directory / (f'{stem}-action-{action}' + ext))
        for phase in ('C', 'W'):
            self.stages[phase]['runs'].append({'seed': None, 'complete': self.save(self.root / f'stage_{phase}/COMPLETE.json')})
        for seed in [701, 702, *range(801, 809)]:
            for mode in ('ordinary', 'dual'):
                self.save(self.root / f'stage_C/warmstarts/{mode}-seed-{seed}.pt.gz')
                if seed >= 801:
                    for policy in ('baseline', 'field'):
                        for ext in ('.pt.gz', '.trace.json.gz'):
                            self.save(self.root / f'stage_C/endpoints/{mode}-seed-{seed}-{policy}{ext}')
        for mode in ('ordinary', 'dual'):
            self.save(self.root / f'stage_C/heads/{mode}/HEAD.json')
        for seed in reg.SEEDS:
            witness = self.root / f'stage_W/seed-{seed}'
            for name in ('original-parent.state', 'reflected-parent.state', 'projection.npz'):
                self.save(witness / name)
            for action in range(4):
                for name in ('first.state', 'terminal.state', 'outputs.npz'):
                    self.save(witness / f'action-{action}-{name}')
        for phase in ('A', 'B', 'C'):
            ids = reg.c_ids() if phase == 'C' else reg.ab_ids(phase) + [f'seed-{seed}-frozen' for seed in reg.SEEDS]
            folder = 'endpoint_evaluation' if phase == 'C' else 'endpoints'
            endpoint = self.root / f'stage_{phase}/{folder}'
            self.stages[phase]['endpoint'] = self.save(endpoint / 'ENDPOINTS.json')
            for name in ids:
                for role in ('task', 'clean'):
                    self.save(endpoint / 'scores' / f'{name}-{role}.npz')

    def test_full_fixed_population_is_hashed_without_decoding_payloads(self):
        self.payloads()
        with patch.object(reg, 'read', side_effect=AssertionError('scientific payload decoded')):
            reg.payload_population(self.root, self.stages, self.artifacts)
        self.assertEqual(sum(len(run['bank_outputs']) for run in self.stages['A']['runs']), 144)
        self.assertEqual(sum(len(group) for run in self.stages['A']['runs'] for group in run['bank_outputs'].values()), 576)
        self.assertEqual(len(reg.ab_ids('B')), 240)
        self.assertEqual(len(reg.c_ids()), 48)

    def test_missing_terminal_and_extra_endpoint_refuse_registration(self):
        self.payloads()
        missing = self.root / 'stage_R/seed-17/schedule-6000-baseline-step-0-action-0.bin.gz'
        missing.unlink()
        with self.assertRaisesRegex(ValueError, 'population differs'):
            reg.payload_population(self.root, self.stages, self.artifacts)
        self.save(missing)
        self.save(self.root / 'stage_B/endpoints/scores/unregistered-extra.npz')
        with self.assertRaisesRegex(ValueError, 'population differs'):
            reg.payload_population(self.root, self.stages, self.artifacts)

    def access(self, phase, scorer=None):
        stage = self.root / ('stage_' + phase)
        kind = 'qualification' if phase == 'B' else 'final'
        source = self.save(self.base / 'SOURCE.json', {'identities_only': True})
        freeze = scorer or self.save(self.base / f'{phase}_SCORER.json', {'registered_commit': 'abcdef0123' * 4})
        identities = reg.ab_ids('B') if phase == 'B' else reg.c_ids()
        entries = []
        for name in identities:
            if phase == 'B':
                path = stage / f"seed-{name.split('-')[1]}/paths/{name}.state"
            else:
                mode, unused, seed, method = name.split('-')
                suffix = 'baseline' if method == 'ordinary' else 'field'
                path = stage / (f'warmstarts/{mode}-seed-{seed}.pt.gz' if method == 'frozen' else f'endpoints/{mode}-seed-{seed}-{suffix}.pt.gz')
            entry = reg.descriptor(path)
            entries.append({**entry, 'path': str(path.relative_to(stage)), 'id': name})
        manifest = self.save(stage / 'ENDPOINT_CHECKPOINTS.json', {'phase': kind, 'training_complete': True, 'checkpoints': entries})
        access = {'phase': kind, 'source_manifest_sha256': source['sha256'], 'checkpoint_manifest_sha256': manifest['sha256'],
            'scorer_freeze_sha256': freeze['sha256'], 'scorer_registered_commit': 'abcdef0123' * 4,
            'allowed_roles': [kind + '_task', kind + '_clean'], 'required_checkpoint_ids': sorted(identities)}
        path = stage / ('QUALIFICATION_ACCESS_FREEZE.json' if phase == 'B' else 'FINAL_ACCESS_FREEZE.json')
        self.save(path, access)
        job = {'freeze_sha256': freeze['sha256'], 'argv': ['-B', '-m', 'synthetic', '--freeze', freeze['path'], '--source-manifest', source['path']]}
        return job, path

    def test_complete_access_populations_and_scorer_identity(self):
        self.payloads()
        for phase in ('B', 'C'):
            job, path = self.access(phase)
            reg.access_metadata(self.root, phase, job, self.artifacts)
            altered = reg.read(path)
            altered['scorer_freeze_sha256'] = '0' * 64
            self.save(path, altered)
            with self.assertRaisesRegex(ValueError, 'access provenance differs'):
                reg.access_metadata(self.root, phase, job, self.artifacts)

    def aggregate(self):
        seals = {}
        for index in range(26):
            info = self.save(self.root / 'scientific-seals' / f'{index}.json')
            self.artifacts[info['path']] = info['sha256']
            seals[info['path']] = info['sha256']
        inputs = self.save(self.base / 'REPORT_INPUTS.json', {'schema': 'synthetic-metadata-only'})
        self.artifacts[inputs['path']] = inputs['sha256']
        source_files = {str(reg.PREFIX / (name + '.py')): reg.file_hash(reg.ROOT / reg.PREFIX / (name + '.py'))
            for name in ('analysis_launch_v2', 'report_results', 'resource_v2', 'resource_io_v2', 'run_v2')}
        freeze = {'execution_kind': 'aggregate_analysis', 'allowed_phases': ['ANALYSIS'], 'attempt_id': 'attempt02',
            'operational_amendment_sha256': 'e' * 64, 'protocol_sha256': reg.PROTOCOL_SHA,
            'registered_commit': 'abcdef0123' * 4, 'source_files': source_files, 'artifacts': dict(self.artifacts),
            'required_scientific_seals': dict(seals), 'analysis_id': 'analysis01', 'output_relative': 'aggregate_results',
            'report_module': reg.__package__ + '.report_results', 'report_inputs': inputs}
        frozen = self.save(self.base / 'ANALYSIS_SOURCE_FREEZE.json', freeze)
        args = SimpleNamespace(root=self.root, analysis_freeze=frozen['path'], analysis_freeze_sha256=frozen['sha256'])
        control, output = self.root / 'analysis_operations/analysis01', self.root / 'aggregate_results'
        expected = {'attempt_id': 'attempt02', 'phase': 'ANALYSIS', 'analysis_id': 'analysis01',
            'source_freeze_sha256': frozen['sha256'], 'registered_commit': freeze['registered_commit'],
            'operational_amendment_sha256': 'e' * 64, 'report_inputs_sha256': inputs['sha256'],
            'scheduled_gradient_microsteps': 0, 'endpoint_scoring_performed': False, 'refitting_performed': False,
            'complete': True, 'post_execution_storage_check': True}
        worker = self.save(control / 'WORKER_COMPLETE.json', expected)
        outputs = [self.save(output / name) for name in ('RESULTS.json', 'REPORT.md')]
        self.save(control / 'COMPLETE.json', {**expected, 'worker_receipt': worker, 'outputs': outputs})
        return args, {'_sha256': 'e' * 64}, seals

    def test_finalizer_binds_thirty_seals_without_decoding_aggregate_outputs(self):
        args, registration, seals = self.aggregate()
        reg.aggregate_completion(args, registration, self.artifacts, seals)
        self.assertEqual(len(seals), 30)
        self.assertEqual((self.root / 'aggregate_results/RESULTS.json').read_bytes(), OPAQUE)

    def test_finalizer_rejects_changed_report_output(self):
        args, registration, seals = self.aggregate()
        (self.root / 'aggregate_results/REPORT.md').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'output population or bytes differ'):
            reg.aggregate_completion(args, registration, self.artifacts, seals)

    def test_historical_failure_and_cost_scopes_are_preserved(self):
        args = SimpleNamespace(historical_inputs=str(reg.ROOT / reg.PREFIX / 'evidence/REPORT_INPUTS_BLOCKED.json'),
                               expected_historical_sha256=reg.HISTORY_SHA)
        original, info = reg.historical_inputs(args, self.artifacts)
        self.assertTrue(original['integrity']['historical_exact_regression_gate'].startswith('FAIL'))
        self.assertEqual(original['failed_attempts'][0]['training_microsteps_lower_bound'], 102320)
        self.assertEqual(len(original['engineering_preflights']), 2)
        self.assertEqual(len(self.artifacts), 4)

    def test_partial_or_existing_bundle_cannot_be_overwritten(self):
        directory = self.base / 'bundle'
        payloads = {'REPORT_INPUTS.json': b'opaque'}
        reg.write_bundle(directory, payloads, {'stage': 'synthetic'})
        before = (directory / 'REPORT_INPUTS.json').read_bytes()
        with self.assertRaises(FileExistsError):
            reg.write_bundle(directory, {'REPORT_INPUTS.json': b'replacement'}, {'stage': 'synthetic'})
        self.assertEqual((directory / 'REPORT_INPUTS.json').read_bytes(), before)

    def test_uncommitted_source_fails_before_any_registration_output(self):
        amendment = self.save(self.base / 'OPS.json', {'status': 'REGISTERED_PRE_ENDPOINT', 'execution_ready': True,
            'attempt_id': 'attempt02', 'raw_root': str(self.root),
            'proposed_resource_contract': {'global_raw_logical_bytes': 2 * resource.GiB,
                'minimum_private_allocatable_bytes': 256 * resource.MiB, 'C_training_evidence_bytes': 350 * resource.MiB},
            'concurrency': {'max_workers': 2, 'worker_reservation_bytes': 768 * resource.MiB, 'memory_margin_bytes': resource.GiB}})
        queue = self.save(self.base / 'QUEUE.json', {})
        args = SimpleNamespace(stage='analysis', root=self.root, output=self.base / 'bundle', amendment=amendment['path'],
            amendment_sha256=amendment['sha256'], analysis_id='analysis01', source_git_root=self.base, source_commit='abcdef0123' * 4,
            queue=queue['path'], expected_queue_sha256=queue['sha256'])
        with patch.object(reg, 'collect', return_value=({}, {}, {}, {}, {})), patch.object(reg, 'analysis_inputs', return_value={}), \
                patch.object(reg, 'committed_sources', side_effect=ValueError('real local source commit required')):
            with self.assertRaisesRegex(ValueError, 'real local source commit'):
                reg.register(args)
        self.assertFalse(args.output.exists())


    def cohort(self):
        self.payloads()
        protocol = reg.descriptor(reg.ROOT / reg.PREFIX / 'PROTOCOL.json')
        amendment = self.save(self.base / 'OPS.json', {'status': 'REGISTERED_PRE_ENDPOINT', 'execution_ready': True,
            'attempt_id': 'attempt02', 'raw_root': str(self.root), 'original_protocol': protocol,
            'proposed_resource_contract': {'global_raw_logical_bytes': 2 * resource.GiB,
                'minimum_private_allocatable_bytes': 256 * resource.MiB, 'C_training_evidence_bytes': 350 * resource.MiB},
            'concurrency': {'max_workers': 2, 'worker_reservation_bytes': 768 * resource.MiB, 'memory_margin_bytes': resource.GiB}})
        source_name = str(reg.PREFIX / 'register_summary_v2.py')
        source_files = {source_name: reg.file_hash(reg.ROOT / source_name)}
        freeze_values, frozen = {}, {}
        for phase in (*reg.launcher.PHASES, 'OPS'):
            freeze_values[phase] = {'source_files': source_files, 'artifacts': {}, 'registered_commit': 'abcdef0123' * 4}
            frozen[phase] = self.save(self.base / f'{phase}_SOURCE_FREEZE.json', freeze_values[phase])
        for phase in ('A', 'B', 'C'):
            value = {**freeze_values[phase], 'training_parents': {phase: frozen[phase]}}
            frozen[phase + '_endpoint'] = self.save(self.base / f'{phase}_ENDPOINT_SOURCE_FREEZE.json', value)
        jobs, results = [], {}
        for name in sorted(reg.launcher.JOB_IDS):
            endpoint = name.endswith('_endpoint')
            phase = name.split('_')[0] if endpoint else name.split('-')[0]
            seed = int(name.split('-')[1]) if '-' in name else None
            source = frozen[name if endpoint else phase]
            module = 'endpoint_v2' if endpoint else 'architecture_run_v2' if phase == 'C' else 'run_v2'
            argv = ['-B', '-m', 'experiments.parameter_field_fullstudy_20261029.' + module,
                '--root', str(self.root), '--freeze', source['path'], '--amendment', amendment['path'],
                '--amendment-sha256', amendment['sha256'], '--execute']
            if phase != 'C' or endpoint:
                argv += ['--phase', phase]
            if seed is not None:
                argv += ['--seed', str(seed)]
            if endpoint:
                folder = 'endpoint_evaluation' if phase == 'C' else 'endpoints'
                complete = f'stage_{phase}/{folder}/ENDPOINTS.json'
                group = 'singleton'
                if phase in ('B', 'C'):
                    access_job, unused = self.access(phase, source)
                    flags = reg.arguments(access_job['argv'])
                    argv += ['--source-manifest', flags['--source-manifest']]
            else:
                token = f'{phase}-seed-{seed}' if seed is not None else f'{phase}-all'
                complete = f'operations/{token}.COMPLETE.json'
                group = 'singleton' if phase == 'W' else 'reconstruction' if phase == 'R' else 'training'
                relative = f'stage_{phase}/COMPLETE.json' if seed is None else f'stage_{phase}/seed-{seed}/COMPLETE.json'
                science = reg.descriptor(self.root / relative)
                self.save(self.root / complete, {'complete': True, 'post_execution_storage_check': True,
                    'attempt_id': 'attempt02', 'phase': phase, 'seed': seed, 'registered_commit': 'abcdef0123' * 4,
                    'source_freeze_sha256': source['sha256'], 'operational_amendment_sha256': amendment['sha256'],
                    'scientific_protocol_sha256': reg.PROTOCOL_SHA, 'scientific_source_bytes_unchanged': True,
                    'scientific_complete': {**science, 'path': relative}})
            job = {'id': name, 'phase': phase, 'seed': seed, 'group': group, 'argv': argv,
                'freeze_sha256': source['sha256'], 'completion': complete, 'requires': []}
            jobs.append(job)
            item = reg.descriptor(self.root / complete)
            results[name] = {'complete': True, 'exit_code': 0, 'completion': {**item, 'path': complete}, 'wall_seconds': 1.}
            self.save(self.root / 'controller' / (name + '.RESULT.json'), results[name])
            self.save(self.root / 'controller' / (name + '.START.json'), {'job': job})
        self.save(self.root / 'controller/START.json', {'source_freeze_sha256': frozen['OPS']['sha256'],
            'amendment_sha256': amendment['sha256']})
        self.save(self.root / 'controller/EXECUTION.json', {'complete': True, 'source_freeze_sha256': frozen['OPS']['sha256'],
            'oom_admission_paused': False, 'jobs': results})
        queue = self.save(self.base / 'QUEUE.json', {'schema': 'hepta.fullstudy.queue.2', 'attempt_id': 'attempt02', 'finalize': True, 'jobs': jobs})
        args = SimpleNamespace(stage='analysis', root=self.root, output=self.base / 'bundle', amendment=amendment['path'],
            amendment_sha256=amendment['sha256'], analysis_id='analysis01', source_git_root=self.base, source_commit='abcdef0123' * 4,
            queue=queue['path'], expected_queue_sha256=queue['sha256'], controller_freeze=frozen['OPS']['path'],
            controller_freeze_sha256=frozen['OPS']['sha256'], historical_inputs=str(reg.ROOT / reg.PREFIX / 'evidence/REPORT_INPUTS_BLOCKED.json'),
            expected_historical_sha256=reg.HISTORY_SHA)
        return args

    def test_generated_report_inputs_match_unchanged_analysis_launcher(self):
        args = self.cohort()
        # Only synthetic producer source ancestors and Git availability are stubbed.
        # All actual queue, operation, population, hash, output and launcher checks run.
        real_getrusage = reg.resource.getrusage
        def fixed_child_counters(kind):
            return SimpleNamespace(ru_utime=.01, ru_stime=.02) if kind == reg.resource.RUSAGE_CHILDREN else real_getrusage(kind)
        with patch.object(reg, 'verify_job'), patch.object(reg, 'verify_controller'), patch.object(reg, 'committed_sources'), \
                patch.object(reg.resource, 'getrusage', side_effect=fixed_child_counters):
            result = reg.register(args)
        self.assertTrue(Path(result['registration_cost']['path']).is_file())
        cost = reg.read(result['registration_cost']['path'])
        self.assertGreater(cost['wall_seconds'], 0)
        self.assertEqual(cost['scheduled_gradient_microsteps'], 0)
        self.assertGreaterEqual(cost['child_process_cpu_seconds'], 0)
        self.assertEqual(cost['child_process_cpu_seconds'], 0.)
        inputs = reg.descriptor(args.output / 'REPORT_INPUTS.json')
        frozen = reg.descriptor(args.output / 'ANALYSIS_SOURCE_FREEZE.json')
        launch_args = SimpleNamespace(root=str(self.root), inputs=inputs['path'], expected_sha256=inputs['sha256'],
            output=str(self.root / 'aggregate_results'), freeze=frozen['path'], freeze_sha256=frozen['sha256'],
            amendment=args.amendment, amendment_sha256=args.amendment_sha256)
        reg.launcher.validate(launch_args)
        self.assertEqual(reg.read(frozen['path'])['required_scientific_seals'].__len__(), 26)

    def test_full_collector_rejects_swapped_controller_completion(self):
        args = self.cohort()
        path = self.root / 'controller/EXECUTION.json'
        value = reg.read(path)
        value['jobs']['A-17']['completion']['sha256'] = '0' * 64
        self.save(path, value)
        registration = resource.load_registration(args.amendment, args.amendment_sha256)
        with patch.object(reg, 'verify_job'), patch.object(reg, 'verify_controller'):
            with self.assertRaisesRegex(ValueError, 'Controller job completion'):
                reg.collect(args, registration)


    def test_generated_finalizer_freeze_passes_original_finalizer_verifier(self):
        args = self.cohort()
        with patch.object(reg, 'verify_job'), patch.object(reg, 'verify_controller'), patch.object(reg, 'committed_sources'):
            reg.register(args)
        frozen = reg.descriptor(args.output / 'ANALYSIS_SOURCE_FREEZE.json')
        freeze = reg.read(frozen['path'])
        inputs = freeze['report_inputs']
        control, output = self.root / 'analysis_operations/analysis01', self.root / 'aggregate_results'
        expected = {'attempt_id': 'attempt02', 'phase': 'ANALYSIS', 'analysis_id': 'analysis01',
            'source_freeze_sha256': frozen['sha256'], 'registered_commit': freeze['registered_commit'],
            'operational_amendment_sha256': args.amendment_sha256, 'report_inputs_sha256': inputs['sha256'],
            'scheduled_gradient_microsteps': 0, 'endpoint_scoring_performed': False, 'refitting_performed': False,
            'complete': True, 'post_execution_storage_check': True}
        worker = self.save(control / 'WORKER_COMPLETE.json', expected)
        outputs = [self.save(output / name) for name in ('RESULTS.json', 'REPORT.md')]
        self.save(control / 'COMPLETE.json', {**expected, 'worker_receipt': worker, 'outputs': outputs})
        args.stage, args.output = 'finalizer', self.base / 'finalizer_bundle'
        args.analysis_freeze, args.analysis_freeze_sha256 = frozen['path'], frozen['sha256']
        with patch.object(reg, 'verify_job'), patch.object(reg, 'verify_controller'), patch.object(reg, 'committed_sources'):
            reg.register(args)
        from .finalize_v2 import verify_source_freeze
        registration = resource.load_registration(args.amendment, args.amendment_sha256)
        final = verify_source_freeze(args.output / 'FINALIZER_SOURCE_FREEZE.json', registration)
        self.assertEqual(len(final['required_scientific_seals']), 30)
        self.assertIn(str(Path(frozen['path']).parent / 'REGISTRATION_COST.json'), final['artifacts'])


if __name__ == '__main__':
    unittest.main()

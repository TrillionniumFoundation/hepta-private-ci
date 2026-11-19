"""Synthetic raw metadata only; never renders or reads production C2/model/E."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import input_contract as contract
import native_analysis_envelope as gate

HERE = Path(__file__).resolve().parent


def saved(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = obj if isinstance(obj, bytes) else (json.dumps(obj, indent=2) + '\n').encode()
    path.write_bytes(raw)
    return {'path': str(path), 'identity': contract.identity(raw)}


def fixture(root):
    out, program = root / 'out', root / 'core'
    sources = {name: saved(root / 'source' / name, (HERE / 'supervisor-source' / name).read_bytes()) for name in gate.SOURCES}
    binding = saved(root / 'binding.json', {'schema': 'c2-resource-input-binding-v1', 'all_six_terminal': True, 'confirmation_E_access': False})
    analysis = {'execution_authorized': True, 'scope': 'c2-terminal-resource-metadata-only', 'confirmation_E_access': False,
                'program_manifest_sha256': contract.PROGRAM, 'plan_sha256': contract.PLAN,
                'binding_sha256': binding['identity']['sha256'], 'synthetic_metadata_only': True,
                'resources': {'whole_hard_wall_seconds': 120, 'peak_RSS_bytes': gate.RSS, 'workers': 1, 'threads': 1, 'automatic_retry': False},
                'complete_os_supervisor': {'schema': 'c2-resource-complete-os-authorization-v1', 'execution_authorized': True,
                    'limits': gate.LIMITS, 'metadata_finalization_seconds': 30, 'native_whole_seconds': 155, 'startup_allowance_seconds': 5,
                    'source_sha256': gate.SOURCES['complete_os_envelope.py']['sha256'], 'runtime_sources': gate.SOURCES,
                    'output_directory': str(out), 'core_program_directory': str(program)}}
    authorization = saved(root / 'authorization.json', analysis)
    args = ['-v', '-o', str(root / 'time.txt'), '/synthetic/python', '-B', sources['complete_os_envelope.py']['path'],
            '--authorization', authorization['path'], '--authorization-sha', authorization['identity']['sha256'],
            '--binding', binding['path'], '--binding-sha', binding['identity']['sha256'], '--program', str(program), '--output', str(out)]
    env = {k: '1' for k in gate.THREADS}; env.update(CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1', LC_ALL='C')
    request = {'executable': '/usr/bin/time', 'timeout_seconds': 155, 'cpu_quota_percent': 100, 'memory_max_bytes': gate.RSS,
               'nice': 10, 'stdin': None, 'env': env, 'args': args, 'cwd': str(root), 'host': 'desktop', 'idempotency_key': 'synthetic-only'}
    job = {k: request[k] for k in ('executable', 'args', 'cwd', 'host', 'idempotency_key')}
    job.update(id='synthetic-job', request_digest='a' * 64, env_keys=list(env), launch_state='launched', launch_error=None)
    ack = {'reused': False, 'launch': {'ok': True}, 'job': job}
    terminal = {'job_id': job['id'], 'state': 'succeeded', 'exit_code': 0, 'timed_out': False, 'cancelled': False, 'automatic_retry': False,
                'output_complete': True, 'output_durable': True, 'terminal_publication_confirmed': True,
                'log_bytes': {n: {'seen': 0, 'stored': 0} for n in ('stdout', 'stderr')},
                'log_synced': {'stdout': True, 'stderr': True}, 'log_errors': {'stdout': None, 'stderr': None},
                'log_truncated': {'stdout': False, 'stderr': False}}
    page = {'job_id': job['id'], **{n: {'offset': 0, 'next_offset': 0, 'size': 0, 'eof': True, 'bytes_hex': ''} for n in ('stdout', 'stderr')}}
    gnu = ('Command being timed: "' + ' '.join(args[3:]) + '"\nUser time (seconds): 0.30\nSystem time (seconds): 0.10\n'
           'Elapsed (wall clock) time (h:mm:ss or m:ss): 0:04.00\nMaximum resident set size (kbytes): 1000\nExit status: 0\n').encode()
    manifest_raw = (HERE / 'ANALYSIS-PROGRAM-MANIFEST.json').read_bytes(); manifest = json.loads(manifest_raw)
    source_map = {str(program / n): item for n, item in manifest['files'].items()}
    source_map[str(program / 'MANIFEST.json')] = contract.identity(manifest_raw)
    source_map.update({s['path']: s['identity'] for s in (*sources.values(), authorization, binding)})
    core = {'whole_wall_seconds': .5, 'authorization': authorization['identity'], 'binding': binding['identity'],
            'own_process_CPU_sample_seconds': .02, 'exact_waited_child_CPU_seconds': .05}
    result = {'authorization_identity': authorization['identity'], 'binding_identity': binding['identity']}
    core_argv = [args[3], '-B', str(program / 'launch_analysis.py'), '--authorization', authorization['path'],
                 '--authorization-sha', authorization['identity']['sha256'], '--binding', binding['path'],
                 '--binding-sha', binding['identity']['sha256'], '--output', str(out / 'core-output'), '--launch-directory', str(out / 'core-launch')]
    outer = {'source_and_input_identities': source_map, 'authorization': authorization['identity'], 'binding': binding['identity'], 'argv': core_argv,
             'popen_started_monotonic': 100., 'wait4_completed_monotonic': 101., 'whole_child_wall_seconds': 1.,
             'process_gate_passed': True, 'cleanup_errors': [], 'supervisor_main_wall_prefix_seconds': 3.,
             'metadata_finalization_wall_prefix_seconds': .5, 'supervisor_peak_RSS_bytes': 1000,
             'supervisor_CPU_prefix_seconds': .1, 'wait4_child_CPU_seconds': .2,
             'process_observations': {k: {'observed_monotonic': t} for k, t in
                                      [('before_start', 99.9), ('after_direct_wait4', 101.01), ('after_cleanup', 101.1)]},
             'artifact_paths': {'core_receipt': str(out / 'core-launch/RECEIPT.json'),
                               'RESULT': str(out / 'core-output/RESULT.json'), 'ZIP': str(out / 'core-output.zip')}}
    inputs = {'os_receipt': saved(out / 'OS-RECEIPT.json', outer), 'core_receipt': saved(Path(outer['artifact_paths']['core_receipt']), core),
              'RESULT': saved(Path(outer['artifact_paths']['RESULT']), result), 'ZIP': saved(Path(outer['artifact_paths']['ZIP']), b'synthetic-placeholder-not-consumed-by-this-native-only-fixture')}
    envelope = {'schema': 'hcsn-c2-resource-analysis-native-envelope-inputs-v1', 'whole_native_limit_seconds': 155,
                'peak_RSS_limit_bytes': gate.RSS, 'native_job_id': job['id'], 'idempotency_key': job['idempotency_key'],
                'native_request_digest': job['request_digest'], 'expected_output_directory': str(out), 'dispatch_records': [],
                'launch_request': saved(root / 'request.json', request), 'launch_ack': saved(root / 'ACK.json', ack),
                'terminal_status': saved(root / 'terminal.json', {'raw': terminal}), 'read_pages': [saved(root / 'page.json', page)],
                'gnu_time': saved(root / 'time.txt', gnu), 'supervisor_sources': sources,
                'analysis_authorization': authorization, 'analysis_binding': binding}
    inputs['native_envelope'] = saved(root / 'native-envelope.json', envelope)
    auth = {'analysis_supervisor_source_sha256': gate.SOURCES['complete_os_envelope.py']['sha256'],
            'renderer_sources': {'ANALYSIS-PROGRAM-MANIFEST.json': contract.identity(manifest_raw)}, 'inputs': inputs}
    return envelope, auth, outer, core, result


class Native155Tests(unittest.TestCase):
    def evaluate(self, fault=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); envelope, auth, outer, core, result = fixture(root)
            if fault: fault(root, envelope, outer)
            ids = {k: spec['identity'] for k, spec in auth['inputs'].items()}
            return gate.verify_native(json.dumps(envelope).encode(), auth, {}, outer, core, result, ids)

    def test_positive_complete_native_metadata(self):
        row = self.evaluate()
        self.assertEqual(row['GNU_complete_native_cost']['conservative_wall_upper_seconds'], 4.01)
        self.assertEqual(row['nested_accounts']['complete_analysis_child_seconds'], 1.)

    def test_wrong_native_limits_or_terminal_refused(self):
        for fault in ('wall', 'rss', 'terminal'):
            def change(root, envelope, outer):
                key = 'terminal_status' if fault == 'terminal' else 'launch_request'
                spec = envelope[key]; data = json.loads(Path(spec['path']).read_bytes())
                if fault == 'wall': data['timeout_seconds'] = 1950
                elif fault == 'rss': data['memory_max_bytes'] = 2 * 1024**3
                else: data['raw']['output_durable'] = False
                envelope[key] = saved(Path(spec['path']), data)
            with self.subTest(fault=fault), self.assertRaises(ValueError): self.evaluate(change)

    def test_impossible_CPU_and_prefix_rejected(self):
        for fault in ('CPU', 'prefix'):
            def change(root, envelope, outer):
                if fault == 'CPU': outer['supervisor_CPU_prefix_seconds'] = 5.
                else: outer['supervisor_main_wall_prefix_seconds'] = 156.
            with self.subTest(fault=fault), self.assertRaises(ValueError): self.evaluate(change)

    def test_native_whole_must_cover_child_plus_finalization(self):
        def change(root, envelope, outer): outer['metadata_finalization_wall_prefix_seconds'] = 29.
        with self.assertRaisesRegex(ValueError, 'native whole cannot cover'): self.evaluate(change)

    def test_core_CPU_and_actual_command_cannot_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            envelope, auth, outer, core, result = fixture(Path(tmp))
            ids = {k: spec['identity'] for k, spec in auth['inputs'].items()}
            core['own_process_CPU_sample_seconds'] = 500.
            with self.assertRaisesRegex(ValueError, 'core disjoint CPU'):
                gate.verify_native(json.dumps(envelope).encode(), auth, {}, outer, core, result, ids)
        def change(root, envelope, outer): outer['argv'][1] = '-O'
        with self.assertRaisesRegex(ValueError, 'actual complete OS child command differs'): self.evaluate(change)

    def test_incomplete_raw_log_and_source_mutation_refused(self):
        for fault in ('log', 'source'):
            def change(root, envelope, outer):
                if fault == 'source': (root / 'source/os_processes.py').write_bytes(b'changed')
                else:
                    spec = envelope['read_pages'][0]; data = json.loads(Path(spec['path']).read_bytes())
                    data['stderr']['eof'] = False; envelope['read_pages'][0] = saved(Path(spec['path']), data)
            with self.subTest(fault=fault), self.assertRaises(ValueError): self.evaluate(change)

    def test_same_key_reconciliation_accepts_only_preserved_dispatch(self):
        def reconciled(root, envelope, outer):
            spec = envelope['launch_ack']; ack = json.loads(Path(spec['path']).read_bytes()); ack['reused'] = True
            envelope['launch_ack'] = saved(Path(spec['path']), ack)
            error = saved(root / 'original-error.json', {'isError': True, 'error': 'synthetic lost response'})
            envelope['dispatch_records'] = [{'request': envelope['launch_request'], 'response': error},
                                            {'request': envelope['launch_request'], 'response': envelope['launch_ack']}]
        self.assertTrue(self.evaluate(reconciled)['reconciled_same_key'])
        def missing(root, envelope, outer):
            reconciled(root, envelope, outer); envelope['dispatch_records'] = []
        with self.assertRaises(ValueError): self.evaluate(missing)

    def test_loader_requires_native_input_before_reading_science(self):
        with self.assertRaisesRegex(ValueError, 'input roster differs'):
            contract.load({'inputs': {k: {} for k in ('os_receipt', 'core_receipt', 'RESULT', 'ZIP')}}, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)

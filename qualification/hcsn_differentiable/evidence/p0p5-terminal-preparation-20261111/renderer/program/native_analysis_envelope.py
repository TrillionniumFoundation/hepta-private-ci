"""Admit only original native155 analysis records; no process or model execution."""
from pathlib import PurePosixPath
import re

from input_contract import PROGRAM, PLAN, RSS, WALL, read_exact, require, number, strict_json
from native_observation_parsers import payload, complete_logs, gnu_time

NATIVE_WALL = 155
SOURCES = {
    'complete_os_envelope.py': {'bytes': 16554, 'sha256': '6e6be1db16c1a05f49806b63f8024111ed25c02bda61510dcde4a9e4e3a39be0'},
    'os_processes.py': {'bytes': 15037, 'sha256': 'f58ca60428d3abafea377ca64e1d71040df98c4f149adce88436951187c990d6'}}
LIMITS = {'whole_wall_seconds': WALL, 'peak_RSS_bytes': RSS, 'workers': 1, 'threads': 1, 'automatic_retry': False}
THREADS = ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


def original_path(spec):
    return spec.get('source_path', spec['path'])


def acknowledgement(request, ack, envelope):
    require(type(ack.get('reused')) is bool and ack.get('launch', {}).get('ok') is True,
            'original or same-key reconciled ACK required')
    job = ack['job']
    require(job.get('launch_state') == 'launched' and job.get('launch_error') is None, 'native launch unacknowledged')
    for key in ('executable', 'args', 'cwd', 'host', 'idempotency_key'):
        require(job[key] == request[key], 'native request/ACK mismatch: ' + key)
    require(sorted(job['env_keys']) == sorted(request['env']), 'native environment key mismatch')
    require(job['id'] == envelope['native_job_id'] and job['idempotency_key'] == envelope['idempotency_key']
            and job['request_digest'] == envelope['native_request_digest']
            and all(isinstance(envelope[k], str) and envelope[k] for k in
                    ('native_job_id', 'idempotency_key', 'native_request_digest')), 'native execution identity differs')


def launch(request, ack, envelope):
    require(request.get('executable') == '/usr/bin/time' and request.get('timeout_seconds') == NATIVE_WALL
            and request.get('cpu_quota_percent') == 100 and request.get('memory_max_bytes') == RSS
            and request.get('nice') == 10 and request.get('stdin') in (None, ''), 'native155 launch limits differ')
    env = request['env']
    require(all(env.get(k) == '1' for k in THREADS) and env.get('CUDA_VISIBLE_DEVICES') == ''
            and env.get('PYTHONDONTWRITEBYTECODE') == '1' and env.get('LC_ALL') == 'C', 'native runtime environment differs')
    acknowledgement(request, ack, envelope)
    args = request['args']
    require(isinstance(args, list) and len(args) == 18 and args[:2] == ['-v', '-o'] and args[4] == '-B'
            and args[3].startswith('/') and args[5].startswith('/') and args[5].endswith('/complete_os_envelope.py')
            and all(isinstance(a, str) and a and not re.search(r'''[\s'"]''', a) for a in args),
            'direct pre-staged supervisor command required')
    flags = dict(zip(args[6::2], args[7::2]))
    require(set(flags) == {'--authorization', '--authorization-sha', '--binding', '--binding-sha', '--program', '--output'}
            and flags['--output'] == envelope['expected_output_directory']
            and all(flags[k].startswith('/') for k in ('--authorization', '--binding', '--program', '--output')),
            'native supervisor argument roster differs')
    return flags, args


def accounting(outer, core, gnu):
    started = number(outer['popen_started_monotonic'])
    waited = number(outer['wait4_completed_monotonic'])
    require(waited - started == outer['whole_child_wall_seconds'], 'complete analysis-child clocks differ')
    require(outer['process_gate_passed'] is True and outer['cleanup_errors'] == [] and 'error' not in outer,
            'OS cleanup or process admission failed')
    obs = outer['process_observations']
    clocks = [number(obs[k]['observed_monotonic']) for k in ('before_start', 'after_direct_wait4', 'after_cleanup')]
    require(clocks[0] <= started <= waited <= clocks[1] <= clocks[2], 'OS observations reverse time')
    prefix = number(outer['supervisor_main_wall_prefix_seconds'], NATIVE_WALL)
    final = number(outer['metadata_finalization_wall_prefix_seconds'], 30)
    number(outer['supervisor_peak_RSS_bytes'], RSS)
    require(core['whole_wall_seconds'] <= outer['whole_child_wall_seconds'] <= prefix <= gnu['conservative_wall_upper_seconds']
            and outer['whole_child_wall_seconds'] + final <= gnu['conservative_wall_upper_seconds']
            and clocks[2] <= waited + final, 'native whole cannot cover recorded child/finalization prefixes')
    core_cpu_lower = number(core['own_process_CPU_sample_seconds']) + number(core['exact_waited_child_CPU_seconds'])
    require(core_cpu_lower <= outer['wait4_child_CPU_seconds'], 'core disjoint CPU exceeds complete OS child CPU')
    cpu_lower = number(outer['supervisor_CPU_prefix_seconds']) + number(outer['wait4_child_CPU_seconds'])
    require(cpu_lower <= gnu['printed_CPU_sum_seconds'] + .02, 'disjoint observed CPU exceeds GNU whole CPU')
    return {'complete_analysis_child_seconds': outer['whole_child_wall_seconds'],
            'supervisor_wall_prefix_seconds': prefix, 'metadata_finalization_prefix_seconds': final,
            'disjoint_CPU_lower_bound_seconds': cpu_lower, 'core_disjoint_CPU_lower_bound_seconds': core_cpu_lower,
            'GNU_CPU_print_comparison_slack_seconds': .02,
            'scope': 'GNU is the complete native155 command; supervisor prefix excludes its final receipt and exit. Nested costs are not added again.'}


def verify_native(raw, auth, tracked, outer, core, result, ids):
    envelope = strict_json(raw)
    require(envelope['schema'] == 'hcsn-c2-resource-analysis-native-envelope-inputs-v1'
            and envelope['whole_native_limit_seconds'] == NATIVE_WALL and envelope['peak_RSS_limit_bytes'] == RSS,
            'complete native155 original-input envelope required')
    def read(spec):
        return read_exact(spec, tracked)
    request = payload(read(envelope['launch_request']))
    ack = payload(read(envelope['launch_ack']))
    flags, args = launch(request, ack, envelope)
    dispatches = envelope.get('dispatch_records', [])
    if ack['reused']:
        require(len(dispatches) >= 2 and dispatches[0]['response']['identity'] != envelope['launch_ack']['identity']
                and dispatches[-1]['response']['identity'] == envelope['launch_ack']['identity'],
                'same-key reconciliation lacks original response/error and final ACK')
    for record in dispatches:
        require(record['request']['identity'] == envelope['launch_request']['identity']
                and payload(read(record['request'])) == request, 'same-key reconciliation changed request')
        previous = read(record['response'])
        require(previous, 'empty raw dispatch response')
        try:
            previous = payload(previous)
        except ValueError:
            continue  # Preserved original unknown response is not launch proof.
        if 'job' in previous:
            acknowledgement(request, previous, envelope)
    logs = complete_logs(payload(read(envelope['terminal_status'])),
                         [payload(read(s)) for s in envelope['read_pages']], envelope['native_job_id'])
    require(original_path(envelope['gnu_time']) == args[2], 'GNU artifact path differs from original request')
    gnu = gnu_time(read(envelope['gnu_time']), args[3:])  # This new adapter has fixed155/512MiB constants.
    require(set(envelope['supervisor_sources']) == set(SOURCES), 'supervisor runtime source roster differs')
    source_inputs = outer['source_and_input_identities']
    for name, spec in envelope['supervisor_sources'].items():
        path = str(PurePosixPath(args[5]).parent / name)
        require(spec['identity'] == SOURCES[name] and original_path(spec) == path
                and source_inputs[path] == spec['identity'], 'qualified supervisor runtime source differs')
        read(spec)
    require(auth['analysis_supervisor_source_sha256'] == SOURCES['complete_os_envelope.py']['sha256'], 'renderer supervisor pin differs')
    authorization_spec, binding_spec = envelope['analysis_authorization'], envelope['analysis_binding']
    analysis = strict_json(read(authorization_spec))
    binding = strict_json(read(binding_spec))
    for spec, flag in ((authorization_spec, '--authorization'), (binding_spec, '--binding')):
        require(original_path(spec) == flags[flag] and spec['identity']['sha256'] == flags[flag + '-sha']
                and source_inputs[flags[flag]] == spec['identity'], 'analysis original input identity differs')
    require(analysis['execution_authorized'] is True and analysis['scope'] == 'c2-terminal-resource-metadata-only'
            and analysis['confirmation_E_access'] is False and analysis['program_manifest_sha256'] == PROGRAM
            and analysis['plan_sha256'] == PLAN and analysis['binding_sha256'] == binding_spec['identity']['sha256']
            and analysis['resources'] == {'whole_hard_wall_seconds': WALL, 'peak_RSS_bytes': RSS,
                                         'workers': 1, 'threads': 1, 'automatic_retry': False}, 'analysis authorization differs')
    require(binding['schema'] == 'c2-resource-input-binding-v1' and binding['all_six_terminal'] is True
            and binding['confirmation_E_access'] is False, 'analysis terminal binding absent')
    extra = analysis['complete_os_supervisor']
    require(extra['schema'] == 'c2-resource-complete-os-authorization-v1' and extra['execution_authorized'] is True
            and extra['limits'] == LIMITS and extra['metadata_finalization_seconds'] == 30
            and extra['native_whole_seconds'] == 155 and extra['startup_allowance_seconds'] == 5
            and extra['source_sha256'] == auth['analysis_supervisor_source_sha256'] and extra['runtime_sources'] == SOURCES
            and extra['output_directory'] == flags['--output'] and extra['core_program_directory'] == flags['--program'],
            'complete OS authorization path/source/caps differ')
    require(outer['authorization'] == core['authorization'] == result['authorization_identity'] == authorization_spec['identity']
            and outer['binding'] == core['binding'] == result['binding_identity'] == binding_spec['identity'], 'cross-layer input identity differs')
    program = flags['--program']
    manifest_spec = auth['renderer_sources']['ANALYSIS-PROGRAM-MANIFEST.json']
    require(source_inputs[program + '/MANIFEST.json'] == manifest_spec and manifest_spec['sha256'] == PROGRAM,
            'completed OS program manifest differs')
    from pathlib import Path
    manifest = strict_json(read({'path': str(Path(__file__).parent / 'ANALYSIS-PROGRAM-MANIFEST.json'), 'identity': manifest_spec}))
    require(all(source_inputs[program + '/' + name] == item for name, item in manifest['files'].items()), 'completed source map differs')
    output = flags['--output']
    expected_argv = [args[3], '-B', program + '/launch_analysis.py', '--authorization', flags['--authorization'],
                     '--authorization-sha', flags['--authorization-sha'], '--binding', flags['--binding'],
                     '--binding-sha', flags['--binding-sha'], '--output', output + '/core-output',
                     '--launch-directory', output + '/core-launch']
    require(outer['argv'] == expected_argv, 'actual complete OS child command differs from native request')
    expected = {'os_receipt': output + '/OS-RECEIPT.json', 'core_receipt': output + '/core-launch/RECEIPT.json',
                'RESULT': output + '/core-output/RESULT.json', 'ZIP': output + '/core-output.zip'}
    for key, path in expected.items():
        require(original_path(auth['inputs'][key]) == path, 'presentation artifact original path differs: ' + key)
    require(outer['artifact_paths'] == {k: expected[k] for k in ('core_receipt', 'RESULT', 'ZIP')}, 'completed artifact paths differ')
    summary = accounting(outer, core, gnu)
    return {'schema': 'renderer-native155-admission-v1', 'native_job_id': envelope['native_job_id'],
            'native_idempotency_key': envelope['idempotency_key'], 'request_digest': envelope['native_request_digest'],
            'reconciled_same_key': ack['reused'], 'raw_log_identities': logs,
            'qualified_supervisor_sources': SOURCES, 'program_manifest_sha256': PROGRAM,
            'GNU_complete_native_cost': gnu, 'nested_accounts': summary,
            'analysis_artifacts': {k: ids[k] for k in ('os_receipt', 'core_receipt', 'RESULT', 'ZIP')},
            'scope': 'Metadata/source admission only; no new process, statistics, LR selection, model or E access.'}

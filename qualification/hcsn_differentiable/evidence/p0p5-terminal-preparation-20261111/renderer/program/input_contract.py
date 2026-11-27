"""Read only SHA-bound, finalized resource metadata; no statistical recomputation."""
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import zipfile

ARMS = ('gru', 'cfc', 'snn_plif', 'event_time_lif', 'ssm_s4d', 'attention', 'hcsn')
SEEDS, LRS = (101, 211, 307), (.001, .003)
PROGRAM = 'f2d1ce683591a9b8575aab2d0981bf67b9e465bf9686a8da2e87a2246a0ea70e'
PLAN = '4ccfa7cc21ec37312e48d095e8f4b7373c765dd6d33fa9314ce724d161e8b06b'
OLD = {'RESULT.json': {'bytes': 402835, 'sha256': '9a5ca0f21e3a881862eafd9e67e35793a9eaeb5a1d4dbcaebcaf6d3720e01367'},
       'POINTS.json': {'bytes': 257663, 'sha256': '90e9f27b5ce07243621cf6b234c9ef0a406ff328ee42ed106e127f8193a1cf8f'}}
RSS, WALL, MAX_BYTES = 512 * 2**20, 120, 64 * 2**20
RUNTIME = ('input_contract.py', 'render_c2_resources.py', 'native_analysis_envelope.py',
           'native_observation_parsers.py', 'ANALYSIS-PLAN.json', 'ANALYSIS-PROGRAM-MANIFEST.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, ceiling=math.inf):
    require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= ceiling,
            'nonnegative finite scalar outside declared envelope')
    return value


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def real(value):
        result = float(value)
        require(math.isfinite(result), 'nonfinite JSON scalar')
        return result
    def invalid(value):
        raise ValueError('nonfinite JSON constant: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_float=real, parse_constant=invalid)


def read_exact(spec, tracked):
    path = Path(spec['path'])
    require(stat.S_ISREG(path.lstat().st_mode), 'regular nonsymlink input required')
    require(path.stat().st_size <= MAX_BYTES, 'input exceeds metadata size limit')
    raw = path.read_bytes()
    require(identity(raw) == spec['identity'], 'input identity mismatch: ' + str(path))
    resolved = str(path.resolve())
    require(resolved not in tracked or tracked[resolved] == spec['identity'], 'cross-record input identity changed')
    tracked[resolved] = spec['identity']
    return raw


def verify_unchanged(tracked):
    for path, expected in tracked.items():
        read_exact({'path': path, 'identity': expected}, {})


def authorize(path, expected_sha, output):
    require(stat.S_ISREG(Path(path).lstat().st_mode) and Path(path).stat().st_size <= 2**20,
            'small regular root decision required')
    raw = Path(path).read_bytes()
    require(len(raw) <= 2**20 and identity(raw)['sha256'] == expected_sha, 'root decision SHA mismatch')
    auth = strict_json(raw)
    require(auth['schema'] == 'c2-resource-render-authorization-v3' and auth['execution_authorized'] is True
            and auth['scope'] == 'render_only_after_complete_resource_analysis'
            and auth['confirmation_E_access'] is False and auth['automatic_retry'] is False,
            'future exact render authorization required')
    require(Path(auth['output_directory']).resolve() == output.resolve(), 'exclusive output differs from decision')
    require(re.fullmatch('[0-9a-f]{64}', auth['analysis_supervisor_source_sha256']) is not None,
            'supervisor source must be pinned')
    tracked = {str(Path(path).resolve()): identity(raw)}
    require(set(auth['renderer_sources']) == set(RUNTIME), 'renderer source roster differs')
    for name in RUNTIME:
        read_exact({'path': str(Path(__file__).parent / name), 'identity': auth['renderer_sources'][name]}, tracked)
    return auth, tracked


def envelopes(outer, core, result, auth, ids, members):
    require(outer['schema'] == 'c2-resource-analysis-complete-os-envelope-v1'
            and outer['status'] == 'completed' and outer['process_started'] is True
            and outer['returncode'] == 0 and outer['timed_out'] is False
            and outer['child_terminal_unknown'] is False and outer['unreaped_descendants'] is False
            and outer['direct_child_CPU_complete'] is True
            and outer['total_attempt_CPU_unknown_or_lower_bound'] is False
            and outer['adopted_child_wait4'] == [],
            'complete OS analysis-child terminal not admitted')
    require(outer['limits'] == {'whole_wall_seconds': WALL, 'peak_RSS_bytes': RSS,
            'workers': 1, 'threads': 1, 'automatic_retry': False}, 'OS analysis envelope changed')
    number(outer['whole_child_wall_seconds'], WALL)
    number(outer['wait4_child_CPU_seconds'])
    for key in ('wait4_peak_RSS_bytes', 'sampled_peak_RSS_bytes'):
        number(outer[key], RSS)
    require(outer['program_manifest_sha256'] == PROGRAM and outer['source_inputs_unchanged'] is True
            and outer['supervisor_source_sha256'] == outer['supervisor_source_sha256_before'] ==
            outer['supervisor_source_sha256_after'] == auth['analysis_supervisor_source_sha256'],
            'OS source identity differs')
    require(outer['artifacts'] == {k: ids[k] for k in ('core_receipt', 'RESULT', 'ZIP')}, 'OS artifact identities differ')
    observation = outer['process_observations']
    require(observation['subreaper_enabled'] is True and observation['unreadable'] == []
            and observation['before_start'] and observation['tracked_identities'], 'process observation incomplete')
    for key in ('after_direct_wait4', 'after_cleanup'):
        scan = observation[key]
        for field in ('observer_pid', 'core_pid', 'core_pgid'):
            require(type(scan[field]) is int and scan[field] > 0, 'process identity missing')
        require(isinstance(scan['records'], (list, dict)) and bool(scan['records']), 'raw process evidence missing')
        require(all(scan[k] == [] for k in ('same_group_pids', 'tracked_live_descendants', 'adopted_children', 'scan_errors')),
                'unreadable process scan or remaining descendants')
    require(core['schema'] == 'c2-resource-analysis-launch-v1' and core['status'] == 'completed'
            and core['process_started'] is True and core['spawn_attempted'] is True and core['returncode'] == 0
            and core['archive_finalized'] is True and core['child_CPU_complete'] is True
            and core['CPU_unknown_or_lower_bound'] is False and core.get('child_terminal_unknown', False) is False,
            'core receipt incomplete; exit zero is insufficient')
    require(core['whole_hard_wall_seconds'] == WALL and core['peak_RSS_limit_bytes'] == RSS
            and core['workers'] == core['threads'] == 1, 'core caps changed')
    number(core['whole_wall_seconds'], WALL)
    number(core['exact_waited_child_CPU_seconds'])
    number(core['own_process_CPU_sample_seconds'])
    for key in ('sampled_child_peak_RSS_bytes', 'exact_waited_child_peak_RSS_bytes', 'own_peak_RSS_bytes'):
        number(core[key], RSS)
    require(core['archive'] == ids['ZIP'] and core['RESULT'] == ids['RESULT'] and core['members'] == len(members)
            and core['CRC_all_members_manifest_verified'] is True, 'core archive binding differs')
    require(core['authorization'] == result['authorization_identity'] and core['binding'] == result['binding_identity']
            and core['result_status'] == result['execution_status'], 'analysis input/terminal binding differs')


def table_contract(result):
    expected = {f'{arm}-s{seed}-lr{lr:g}' for arm in ARMS for seed in SEEDS for lr in LRS}
    candidates, tables = result['candidates'], result['longer_resource_core_table']
    require(len(candidates) == 42 and {c['name'] for c in candidates} == expected, 'all 42 opportunities required')
    require(len(tables) == 7 and {r['arm'] for r in tables} == set(ARMS), 'seven core rows required')
    for row in tables:
        arm, lr, stats = row['arm'], row['selected_common_learning_rate'], row['selected_statistics']
        group = [c for c in candidates if c['arm'] == arm]
        require(len(group) == 6 and {c['name'] for c in group} == {f'{arm}-s{s}-lr{v:g}' for s in SEEDS for v in LRS}, 'core roster differs')
        choices = row['learning_rate_candidates']
        require(len(choices) == 2 and {c['learning_rate'] for c in choices} == set(LRS), 'both LR rosters required')
        if stats is not None:
            selected = next(c for c in choices if c['learning_rate'] == lr)
            require(selected['verified_quality_count'] == 3 and stats == selected['verified_three_seed_statistics'], 'unverified selected statistics')
            require(all(c['quality_verified'] is True for c in group if c['learning_rate'] == lr), 'selected quality gate false')
            require(arm != 'hcsn' or result['independent_auditor_admitted'] is True
                    and all(c['quality_verified'] is True for c in group), 'HCSN requires all six verified candidates')
            number(stats['mean'], 1)
            number(stats['sample_standard_deviation'], 1)
        else:
            require(row['selected_trained_comparison_supported'] is False, 'missing quality cannot be adequate')
        if row['selected_trained_comparison_supported']:
            require(stats is not None and row['selected_independently_adequate_count'] == 3, 'selected adequacy differs')
        crossings = row['selected_target_crossings']
        count, median = row['selected_observed_crossing_count'], row['median_first_observed_target_seconds']
        require(count == sum(c['crossing'] is not None for c in crossings), 'crossing count differs')
        if median is not None:
            require(stats is not None and count == 3 and len(crossings) == 3, 'median requires all three observed crossings')
            number(median)
        cost = row['all_six_opportunity_cost']
        require(cost['opportunity_count'] == 6, 'opportunity cost lost candidates')
        number(cost['known_wall_lower_bound_seconds'])
        if cost['all_opportunity_wall_seconds'] is not None:
            number(cost['all_opportunity_wall_seconds'])
            require(cost['missing_full_cost_names'] == [] and cost['known_sum_is_lower_bound'] is False, 'incomplete full bill')
        require(row['memory_at_quality_crossing_known'] is False
                and all(row[k] is None for k in ('energy_joules', 'GPU_VRAM_bytes', 'billed_currency')), 'measurement scope changed')


def load(auth, tracked):
    require(set(auth['inputs']) == {'os_receipt', 'core_receipt', 'RESULT', 'ZIP', 'native_envelope'}, 'input roster differs')
    raw = {k: read_exact(v, tracked) for k, v in auth['inputs'].items()}
    ids = {k: identity(v) for k, v in raw.items()}
    import io
    with zipfile.ZipFile(io.BytesIO(raw['ZIP'])) as archive:
        names = archive.namelist()
        required = {'MANIFEST.json', 'RESULT.json', 'LONGER-CURVES.json', 'frozen-original-budget/RESULT.json', 'frozen-original-budget/POINTS.json'}
        require(len(names) == len(set(names)) and set(names) == required, 'archive member roster differs')
        require(sum(i.file_size for i in archive.infolist()) <= MAX_BYTES, 'uncompressed metadata exceeds limit')
        require(all(not i.is_dir() and stat.S_IFMT(i.external_attr >> 16) in (0, stat.S_IFREG) for i in archive.infolist()), 'nonregular archive member')
        contents = {name: archive.read(name) for name in names}  # read verifies each CRC
    members = {name: identity(value) for name, value in contents.items()}
    manifest = strict_json(contents['MANIFEST.json'])['files']
    require(manifest == {k: v for k, v in members.items() if k != 'MANIFEST.json'}, 'archive manifest differs')
    require(contents['RESULT.json'] == raw['RESULT'], 'standalone result/archive bytes differ')
    for name, expected in OLD.items():
        require(members['frozen-original-budget/' + name] == expected, 'old resource view changed')
    result, core, outer = (strict_json(raw[k]) for k in ('RESULT', 'core_receipt', 'os_receipt'))
    require(result['schema'] == 'c2-longer-resource-metadata-analysis-v1' and result['execution_status'] in
            ('completed_metadata', 'completed_metadata_with_explicit_holds') and result['inputs_unchanged'] is True
            and result['program_manifest_before'] == result['program_manifest_after'] == PROGRAM, 'analysis source/finality failed')
    require(result['confirmation_E_access'] is False and result['CPU_axis_used_for_quality_selection'] is False
            and result['old_budget_300_900_1800_modified'] is False and result['scientific_admission'] ==
            result['whole_training_numerical_admission'] == 'HOLD', 'analysis scope changed')
    require(all(type(result[k]) is int and result[k] == 0 for k in ('training_steps', 'forward_calls', 'backward_calls', 'numerical_oracle_calls')), 'forbidden analysis execution')
    require(result['original_budget_exact_copies'] == OLD and result['archive_status'] ==
            'provisional_until_external_terminal_receipt_and_archive_identity', 'inner archive scope changed')
    plan_raw = (Path(__file__).parent / 'ANALYSIS-PLAN.json').read_bytes()
    require(identity(plan_raw)['sha256'] == PLAN and result['plan'] == strict_json(plan_raw), 'frozen analysis plan differs')
    number(result['metadata_worker_wall_seconds'], WALL)
    number(result['worker_self_peak_RSS_bytes'], RSS)
    envelopes(outer, core, result, auth, ids, members)
    from native_analysis_envelope import verify_native
    verify_native(raw['native_envelope'], auth, tracked, outer, core, result, ids)
    table_contract(result)
    return result, strict_json(contents['frozen-original-budget/RESULT.json']), raw, contents

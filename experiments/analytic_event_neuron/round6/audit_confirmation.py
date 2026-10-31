"""Independent reconstruction of completed paid-feedback execution and scoring.

This verifier reads private labels only after all policy/scoring completion
receipts exist. It never generates data, retrains models or changes run files.
Fresh Owner/native calls are recorded under the separate review output.
"""

import gzip
import json
from pathlib import Path

import numpy as np

from .audit_training import load_npz
from .audit_transport import Archive, acquired_public, broker_records, digest, file_sha, transport_records
from .audit_replay import LEARNED


ARMS = ('event', 'direct', 'float', 'gaussian', 'probit', 'analytic', 'numeric', 'history', 'uncalibrated')
SCORE_FIELDS = {'target', 'squared_error', 'utility', 'score_started_ns'}
PUBLIC_FIELDS = {'initial', 'residuals', 'variances', 'repair_cost', 'wait_cost', 'wait_variance'}
STATE_FIELDS = {'index', 'arm', 'case_id', 'case_dir', 'phase', 'public', 'cost', 'durable_readback_ns'}
SCOPE = 'runtime6_confirmation'


def document(path):
    return json.loads(Path(path).read_text())


def compressed_rows(path):
    with gzip.open(path, 'rt') as stream:
        return json.load(stream)


def completed_scope(directory, model_path, seed, domain, checks):
    """Bind all original file bytes before opening private scoring data."""
    job = document(directory / 'JOB.json')
    worker = document(directory / 'WORKER.json')
    summary = document(directory / 'SUMMARY.json')
    complete = document(directory / 'RUN_COMPLETED.json')
    checks.require(complete['summary_sha256'] == file_sha(directory / 'SUMMARY.json'), 'completed scoring summary bytes')
    for role in ('worker', 'score'):
        receipt = document(directory / (role.upper() + '_COMPLETED.json'))
        checks.require(receipt == complete['execution'][role] and receipt['returncode'] == 0,
                       'successful separate process completion:' + role)
        checks.require(receipt['wall_ns'] > 0 and receipt['children_user_seconds'] >= 0
                       and receipt['children_system_seconds'] >= 0, 'actual whole-process costs:' + role)
        checks.require(receipt['native_energy'] is None and receipt['financial_cost'] is None,
                       'unmeasured energy and financial cost remain absent')
    worker_start = document(directory / 'WORKER_STARTED.json')['started_ns']
    score_start = document(directory / 'SCORE_STARTED.json')['started_ns']
    checks.require(worker_start + complete['execution']['worker']['wall_ns'] <= score_start
                   <= summary['target_read_started_ns'], 'scorer starts after worker process completion')
    checks.require(worker['model_sha256'] == job['model_sha256'] == file_sha(model_path), 'immutable actual model bytes')
    checks.require(worker['job_sha256'] == file_sha(directory / 'JOB.json'), 'completed worker job binding')
    checks.require(worker['public_rows_sha256'] == file_sha(directory / 'PUBLIC_ROWS.json.gz'), 'completed public rows bytes')
    checks.require(summary['rows_sha256'] == file_sha(directory / 'ROWS.json.gz'), 'completed scored rows bytes')
    checks.require(summary['data_sha256'] == job['data_sha256'] == file_sha(directory / 'DATA.npz'), 'private actual scoring data bytes')
    checks.require(summary['worker'] == worker, 'scorer binds original completed worker')
    checks.require(worker['private_array_loads_denied_in_policy_process']
                   and worker['future_observation_only_returned_after_wait']
                   and not worker['same_uid_hostile_isolation_claimed'], 'documented cooperative information boundary')
    checks.require(len({worker['pid'], worker['broker_pid'], summary['scorer_pid']}) == 3, 'three distinct actual process identities')
    for item in (job, summary, complete):
        checks.require(item['seed'] == seed and item['domain'] == domain
                       and item['namespace'] == job['namespace'], 'completed execution scope')
    for item in (worker, summary, complete):
        checks.require(item['production_promotion'] is False, 'research-only execution receipt')
    n = job['rows']
    checks.require(0 < n <= 8 if job['namespace'] == 'smoke' else n == 128, 'declared confirmation row count')
    checks.require(summary['independent_trajectories'] == n and summary['executions'] == worker['executions'] == n * len(ARMS),
                   'trajectories versus arm executions counted separately')
    return job, worker, summary, complete


def transitions(row, group, values, records, receipt_sha, archive, prefix, checks, *, legacy_terminal_timestamp=False):
    """Rebuild exactly the acquired public history and actual cost transitions."""
    i, arm, stages = row['index'], row['arm'], row['stages']
    actions = [stage['action'] for stage in stages]
    waited = len(stages) == 2
    checks.require(len(stages) in (1, 2) and row['actions'] == actions, 'one or two acquired decision stages')
    checks.require(actions[-1] in ('stop', 'repair') and (not waited or actions[0] == 'wait'),
                   'only paid wait can produce a second observation')
    operations = ['start', 'wait', 'finish'] if waited else ['start', 'finish']
    checks.require([r['operation'] for r in group] == operations, 'exact acquired broker operation sequence')
    archived = [json.loads(line) for line in archive.read(prefix + '/PUBLIC_TRANSITIONS.jsonl').splitlines()]
    checks.require(archived == group, 'case transitions equal persistent global broker transcript')
    checks.require([r for transition in group for r in transition['transport_records']] == records,
                   'each actual transport operation belongs to exactly one transition')
    expected_stages = ['initial', 'sensor', 'sensor_variance', 'repair_cost', 'wait_cost', 'wait_variance', 'residual']
    if waited:
        expected_stages += ['wait_sensor', 'wait_residual']
    expected_stages += ['final']
    checks.require([r['stage'] for r in records] == expected_stages, 'complete actual delivery and observation order')
    case_id = 'broker6:' + digest([SCOPE, i])[:24]
    checks.require(row['case'] == case_id, 'opaque acquired case identity')
    case_folder = digest([SCOPE, i, arm])[:32]
    initial = acquired_public(values, False, checks)
    public_history = [initial] + ([acquired_public(values, True, checks)] if waited else [])
    amount = stages[-1]['values']['repair_amount'] if actions[-1] == 'repair' else 0.0
    cost = (initial['wait_cost'] if waited else 0.0) + (initial['repair_cost'] if actions[-1] == 'repair' else 0.0)
    for index, (stage, public) in enumerate(zip(stages, public_history)):
        transition = group[index]
        checks.require(set(public) == PUBLIC_FIELDS and public == stage['public']
                       == transition['state']['public'] == transition['response']['result']['public'],
                       'exact six-field acquired model information')
        checks.require(stage['decision_ns'] >= transition['recorded_ns'], 'decision follows acquired durable response')
        if index:
            checks.require(transition['transport_records'][0]['began_ns'] >= stages[index - 1]['decision_ns'],
                           'paid wait acquisition begins after wait choice')
    for index, transition in enumerate(group):
        terminal = index == len(group) - 1
        state, request = transition['state'], transition['request']
        checks.require(set(state) == STATE_FIELDS | ({'choice', 'repair_amount', 'result'} if terminal else set()),
                       'broker state has no private future or target fields')
        checks.require(state['index'] == i and state['arm'] == arm and state['case_id'] == case_id
                       and Path(state['case_dir']).name == case_folder, 'transition case identity')
        checks.require(state['public'] == public_history[-1 if terminal else index], 'state retains only acquired history')
        expected_phase = 'terminal' if terminal else ('observed' if index == 0 else 'waited')
        checks.require(state['phase'] == expected_phase, 'broker action phase')
        expected_cost = cost if terminal else (initial['wait_cost'] if index else 0.0)
        checks.close(state['cost'], expected_cost, 'independent accrued broker cost', 0)
        checks.require(request['op'] == transition['operation'], 'request operation identity')
        if index == 0:
            checks.require(request == {'id': request['id'], 'op': 'start', 'index': i, 'arm': arm},
                           'start request cannot carry latent fields')
            checks.require(set(transition['response']['result']) == {'public', 'case_id', 'case_dir'},
                           'start response exposes acquired fields only')
        elif not terminal:
            checks.require(request == {'id': request['id'], 'op': 'wait'}
                           and set(transition['response']['result']) == {'public'}, 'wait request and response schema')
    final = group[-1]
    checks.require(final['request'] == {'id': final['request']['id'], 'op': 'finish',
                   'choice': actions[-1], 'repair_amount': amount}, 'actual terminal request equals chosen action')
    result = final['response']['result']
    checks.require(set(result) == {'delivered', 'cost', 'transport', 'final_readback_ns'}, 'terminal response remains label-free')
    checks.require(final['state']['result'] == result
                   and final['state']['choice'] == actions[-1] and final['state']['repair_amount'] == amount,
                   'terminal state and response agree')
    if legacy_terminal_timestamp:
        checks.require(final['state']['durable_readback_ns'] == group[-2]['state']['durable_readback_ns']
                       < result['final_readback_ns'], 'known old development metadata defect reproduced explicitly')
    else:
        checks.require(final['state']['durable_readback_ns'] == result['final_readback_ns'],
                       'terminal state advances to actual final durable readback')
    checks.require(records[-1]['began_ns'] >= stages[-1]['decision_ns'], 'final delivery follows terminal choice')
    checks.require(values['final'] == initial['initial'] + amount == result['delivered'] == row['delivered'],
                   'actual PNG/text final delivery equals chosen amount')
    checks.close(row['cost'], cost, 'actual paid total cost', 0)
    checks.require(all(row[key] == value for key, value in result.items()), 'public row preserves exact final broker receipt')
    receipt = row['transport']
    checks.require(receipt['receipt_sha256'] == receipt_sha, 'actual final transport receipt bytes')
    deliveries = sum(record['kind'] == 'delivery' for record in records)
    checks.require(receipt['deliveries'] == deliveries and receipt['observations'] == len(records) - deliveries
                   and receipt['files'] == 2 * deliveries + len(records) - deliveries, 'actual transport cost inventory')
    for record in records:
        checks.require(record['scope'] == SCOPE and record['case'] == case_id and record['arm'] == arm,
                       'every actual artifact has its own case binding')
    return public_history


def replay_policy(row, model, replay, checks):
    """Check all independent probabilities, action scores and original sparse ticks."""
    arm, stages = row['arm'], row['stages']
    mode = arm if arm in ('event', 'direct', 'float') else ('float' if arm in ('gaussian', 'probit', 'uncalibrated') else 'event')
    owner = replay.owner([row['case'], arm], digest(model), mode)
    before_requests, before_ticks = replay.native.calls, replay.native.original_sparse_ticks
    checkpoint, near_boundary = '0' * 64, 0
    for index, stage in enumerate(stages):
        public = stage['public']
        checkpoint, independent = replay.stage(owner, stage['runtime'], model, arm, public, index + 1, checkpoint)
        replay.values(stage['values'], independent)
        if arm in LEARNED:
            feature = replay.features(public, stage['runtime']['law'], model, arm,
                                      row['case'] + f'/stage{index}/{arm}', stage['native'])
            checks.close(stage['feature'], feature, 'confirmation independent ' + arm + ' features', 2e-12)
            repair = float(feature @ model['heads'][arm]['weights']) + model['heads'][arm]['offset']
        else:
            checks.require(stage['feature'] is None and stage['native'] == [], 'declared non-readout comparator')
            repair = independent['repair_gain']
        scores = {'stop': 0.0, 'repair': repair}
        if index == 0:
            scores['wait'] = independent['wait_gain']
        checks.require(set(stage['scores']) == set(scores), 'available action set follows acquired stage')
        for key, value in scores.items():
            checks.close(stage['scores'][key], value, 'independent action score:' + key, 3e-9)
        # JSON sort order is not the policy's declared tie order.
        original = {key: stage['scores'][key] for key in ('stop', 'repair', 'wait') if key in scores}
        checks.require(max(original, key=original.get) == stage['action'], 'actual deterministic action and tie rule')
        ranked = sorted(scores.values(), reverse=True)
        if ranked[0] - ranked[1] > 6e-9:
            checks.require(max(scores, key=scores.get) == stage['action'], 'independent numerical action away from tolerance boundary')
        else:
            near_boundary += 1
    checks.require(replay.native.calls - before_requests == row['native_requests']
                   and replay.native.original_sparse_ticks - before_ticks == row['native_ticks'],
                   'every recorded actual native request and original tick replayed')
    checks.require(row['packet_bytes'] == sum(s['runtime']['packet_bytes'] for s in stages), 'actual packet byte accounting')
    return owner, near_boundary


def audit_scope(run_dir, seed, domain, replay, checks):
    root = Path(run_dir)
    directory = root / 'confirmation' / f'seed_{seed}' / domain
    model_path = root / 'prepared' / f'seed_{seed}' / 'MODELS.json'
    job, worker, summary, completed = completed_scope(directory, model_path, seed, domain, checks)
    # A historical development fixture predates the independent review that
    # found stale terminal-state metadata. Only its exact archived old source
    # can activate this transparent compatibility check; formal runs cannot.
    broker_path = 'experiments/analytic_event_neuron/round6/broker.py'
    old_broker = 'b0029de73f2ea21fbe7042616aed8b27302760e593fde610a7aad54044b0803d'
    snapshot = root / 'SOURCE_SNAPSHOT' / broker_path
    legacy = (job['namespace'] == 'smoke' and snapshot.exists()
              and file_sha(snapshot) == old_broker)
    if legacy:
        checks.require(document(root / 'SOURCE_BEFORE.json')['sources_sha256'][broker_path] == old_broker,
                       'exact historical development source binding for disclosed metadata defect')
    model = document(model_path)
    expected_freeze = None if job['namespace'] == 'smoke' else file_sha(root / 'FREEZE.json')
    checks.require(job['expected_freeze_sha256'] == expected_freeze and model['namespace'] == job['namespace'],
                   'actual confirmation uses expected frozen model scope')
    checks.require(model['native_binary_sha256'] == replay.native.receipt['binary_sha256'], 'exact original native executable')
    # All completion/hash checks above precede this independent private-label read.
    data = load_npz(directory / 'DATA.npz')
    n = job['rows']
    checks.require(len(data['target']) == n and data['seed'] == seed and data['domain'] == domain
                   and data['split'] == 'confirmation', 'independent scorer data identity')
    public_rows, rows = compressed_rows(directory / 'PUBLIC_ROWS.json.gz'), compressed_rows(directory / 'ROWS.json.gz')
    pairs = {(i, arm) for i in range(n) for arm in ARMS}
    checks.require(len(public_rows) == len(rows) == len(pairs)
                   and {(r['index'], r['arm']) for r in rows} == pairs, 'complete paired execution inventory')
    groups, broker = broker_records(directory, len(pairs), checks, legacy_terminal_timestamp=legacy)
    checks.require(broker['pid'] == worker['broker_pid'] and broker['rows'] == n
                   and not broker['private_targets_returned'] and not broker['same_uid_hostile_isolation_claimed'],
                   'actual separate private broker receipt')
    archive = Archive(directory, worker['archive'], checks)
    near_boundary, stages_total = 0, 0
    try:
        prefixes = {'/'.join(name.split('/')[:2]) for name in archive.files}
        checks.require(prefixes == {f'case-{i}/{arm}' for i, arm in pairs}, 'archive has every and only declared execution')
        for public_row, row in zip(public_rows, rows):
            checks.require(not SCORE_FIELDS.intersection(public_row)
                           and set(row) == set(public_row) | SCORE_FIELDS
                           and {key: row[key] for key in public_row} == public_row, 'scorer only appends labels and score after policy')
            i, arm = row['index'], row['arm']
            prefix = f'case-{i}/{arm}'
            values, records, receipt_sha = transport_records(archive, prefix, checks)
            for name, column in [('initial', 'initial_output'), ('sensor', 'self_evaluation'),
                                 ('sensor_variance', 'sensor_variance'), ('wait_variance', 'wait_variance'),
                                 ('repair_cost', 'repair_cost'), ('wait_cost', 'wait_cost')]:
                checks.require(values[name] == float(data[column][i]), 'original actual environment readback')
            if len(row['stages']) == 2:
                checks.require(values['wait_sensor'] == float(data['wait_evaluation'][i]), 'actual paid future observation')
            transitions(row, groups[i, arm], values, records, receipt_sha, archive, prefix, checks,
                        legacy_terminal_timestamp=legacy)
            owner, boundary = replay_policy(row, model, replay, checks)
            replay.archived_owner(archive, prefix, owner, row['stages'])
            near_boundary += boundary
            stages_total += len(row['stages'])
            target = float(data['target'][i])
            checks.require(row['target'] == target, 'scored private target identity')
            checks.close(row['squared_error'], (values['final'] - target) ** 2, 'independent actual squared error', 0)
            checks.close(row['utility'], 1 - (values['final'] - target) ** 2 - row['cost'], 'independent actual final utility', 0)
            checks.require(row['final_readback_ns'] < summary['target_read_started_ns'] <= row['score_started_ns'],
                           'private scoring follows all completed final readbacks')
            for key in ('wall_ns', 'cpu_ns', 'native_roundtrip_ns', 'evidence_archive_wall_ns'):
                checks.require(row[key] > 0, 'measured execution cost:' + key)
        for arm, metrics in summary['summary'].items():
            checks.require(arm in ARMS, 'declared scoring arm')
            selected = [r for r in rows if r['arm'] == arm]
            for key, value in metrics.items():
                checks.close(value, np.mean([r[key] for r in selected]), 'independent scope aggregate:' + key, 3e-12)
        checks.require(set(summary['summary']) == set(ARMS), 'all declared aggregate arms')
        for aggregate, field in [('requests', 'native_requests'), ('ticks', 'native_ticks'), ('roundtrip_ns', 'native_roundtrip_ns')]:
            checks.require(worker['native'][aggregate] == sum(r[field] for r in rows), 'complete original native cost ledger')
        checks.require(worker['broker'] == {'complete': True, 'finished_cases': len(pairs)}, 'original private broker termination')
        return {'seed': seed, 'domain': domain, 'namespace': job['namespace'], 'independent_trajectories': n,
                'arm_executions': len(rows), 'owner_stages': stages_total, 'archive_members_verified': len(archive.files),
                'acquired_action_stages_near_numerical_tolerance': near_boundary,
                'every_original_sparse_tick_replayed': True,
                'legacy_development_terminal_state_timestamp_defect_cases': len(rows) if legacy else 0,
                'terminal_state_durable_timestamp_strictly_correct': not legacy,
                'rows_sha256': file_sha(directory / 'ROWS.json.gz'),
                'broker_transcript_sha256': file_sha(directory / 'broker/BROKER_TRANSCRIPT.jsonl')}
    finally:
        archive.close()


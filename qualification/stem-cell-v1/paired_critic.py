"""Frozen one-step tabular critic fitted to complete paired outcome groups.

Fit and calibration groups are disjoint; the bins and attempt inventory precede
outcomes. Confidence is conditional on independent, stationary groups WITHIN a
bin and the declared resource envelope. Length bins do not prove sufficient state,
pointwise calibration, truthful records or transport to a new task distribution.
No fitted maximum is promoted to a hard resource bound. No outcomes are loaded at
runtime. This module fits group-mean net gains, not a neural generator or FBSDE.
"""
from __future__ import annotations

import copy
import math
import time
from collections import defaultdict

from next_round_matrix import _digest
from paired_execution import _integer, _sha

PROTOCOL = 'hepta.ndu.paired-critic-protocol.v1'
ARTIFACT = 'hepta.ndu.frozen-paired-critic.v1'
CAPTURED_ARTIFACT = 'hepta.ndu.frozen-paired-critic.v2'
MAX_PAIRS = 8192
COEFFICIENTS = ('discount_rate_per_second', 'cost_per_formula_flop', 'cost_per_latency_ns')


def _number(x, name, lo, hi):
    if type(x) not in (int, float) or not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError('invalid ' + name)
    return x


def freeze_protocol(*, objective_sha256, subject_id, callback_profile_sha256,
                    observer_sha256, registered_at_ns, cutoff_ns, expires_at_ns,
                    fit_groups, calibration_groups, pairs, candidate_edges,
                    feedback_edges, alpha, minimum_groups, max_calibration_gap,
                    duration_upper_ns, formula_work_upper, coefficients):
    for value in (objective_sha256, callback_profile_sha256, observer_sha256):
        _sha(value, 'critic owner/profile reference')
    if not isinstance(subject_id, str) or not 1 <= len(subject_id.encode()) <= 256:
        raise ValueError('bounded subject required')
    for t in (registered_at_ns, cutoff_ns, expires_at_ns):
        _integer(t, 'critic protocol time', 1)
    if not registered_at_ns < cutoff_ns < expires_at_ns:
        raise ValueError('registration, cutoff and expiry must be ordered')
    for groups in (fit_groups, calibration_groups):
        if (not isinstance(groups, list) or not 1 <= len(groups) <= 4096
                or any(not isinstance(g, str) or not 1 <= len(g.encode()) <= 256 for g in groups)
                or groups != sorted(set(groups))):
            raise ValueError('canonical nonempty source groups required')
    if set(fit_groups) & set(calibration_groups):
        raise ValueError('fit and calibration groups overlap')
    for edges in (candidate_edges, feedback_edges):
        if (not isinstance(edges, list) or len(edges) > 3 or edges != sorted(set(edges))
                or any(type(e) is not int or not 1 <= e < 65536 for e in edges)):
            raise ValueError('predeclared bounded length bins required')
    _number(alpha, 'family alpha', 1e-12, .5)
    _integer(minimum_groups, 'minimum independent groups', 2)
    if minimum_groups > 4096:
        raise ValueError('too many groups')
    _number(max_calibration_gap, 'calibration gap', 0., 1.)
    _integer(duration_upper_ns, 'segment duration envelope', 1)
    _integer(formula_work_upper, 'segment arithmetic envelope')
    if duration_upper_ns > 3_600_000_000_000 or formula_work_upper > 10**18:
        raise ValueError('segment resource envelope too large')
    if not isinstance(coefficients, dict) or set(coefficients) != set(COEFFICIENTS):
        raise ValueError('all linear utility coefficients required')
    for v in coefficients.values():
        _number(v, 'utility coefficient', 0., 1e6)
    cost = coefficients['cost_per_formula_flop'] * formula_work_upper + coefficients['cost_per_latency_ns'] * duration_upper_ns
    if not math.isfinite(cost) or cost > 1e6:
        raise ValueError('net-gain range exceeds numeric envelope')
    all_groups = set(fit_groups) | set(calibration_groups)
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= MAX_PAIRS:
        raise ValueError('bounded preregistered paired attempt inventory required')
    ids, cases, observed_groups = set(), {}, set()
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {'pair_id', 'group_id', 'case_sha256', 'candidate_bytes', 'feedback_bytes'}:
            raise ValueError('complete public paired-case descriptor required')
        pid, group = pair['pair_id'], pair['group_id']
        if not isinstance(pid, str) or not 1 <= len(pid.encode()) <= 256 or pid in ids or not isinstance(group, str) or group not in all_groups:
            raise ValueError('duplicate pair or unregistered group')
        _sha(pair['case_sha256'], 'pre-outcome case fingerprint')
        for key in ('candidate_bytes', 'feedback_bytes'):
            _integer(pair[key], key, 1)
            if pair[key] > 65536:
                raise ValueError('oversized case descriptor')
        old = cases.setdefault(pair['case_sha256'], group)
        if old != group:
            raise ValueError('same case cannot inflate independent groups')
        ids.add(pid); observed_groups.add(group)
    if observed_groups != all_groups:
        raise ValueError('all preregistered groups need cases')
    body = dict(schema=PROTOCOL, objective_sha256=objective_sha256, subject_id=subject_id,
                callback_profile_sha256=callback_profile_sha256, observer_sha256=observer_sha256,
                registered_at_ns=registered_at_ns, cutoff_ns=cutoff_ns, expires_at_ns=expires_at_ns,
                fit_groups=fit_groups, calibration_groups=calibration_groups, pairs=pairs,
                candidate_edges=candidate_edges, feedback_edges=feedback_edges, alpha=alpha,
                minimum_groups=minimum_groups, max_calibration_gap=max_calibration_gap,
                duration_upper_ns=duration_upper_ns, formula_work_upper=formula_work_upper,
                coefficients=coefficients)
    return copy.deepcopy({**body, 'protocol_id': _digest(body)})


def validate_protocol(protocol, expected_id):
    _sha(expected_id, 'externally retained critic protocol')
    if not isinstance(protocol, dict):
        raise ValueError('critic protocol required')
    try:
        expected = freeze_protocol(**{k: v for k, v in protocol.items() if k not in ('schema', 'protocol_id')})
    except TypeError as exc:
        raise ValueError('unknown/incomplete critic protocol') from exc
    if expected['protocol_id'] != expected_id or _digest(protocol) != _digest(expected):
        raise ValueError('critic protocol differs from pre-outcome registration')


def bucket(protocol, candidate_bytes, feedback_bytes):
    return f"{sum(candidate_bytes > e for e in protocol['candidate_edges'])}:{sum(feedback_bytes > e for e in protocol['feedback_edges'])}"


def fit_critic(protocol, rows, *, expected_protocol_id, expected_dataset_sha256):
    """Fit a table, calibrate on held-out GROUP means, seal a label-free artifact.

    Rows are owner-supplied paired stop/one-more-segment observations, not inferred
    from verifier acceptance. Every registered attempt, including failed ones,
    must be present. Missing costs block release; bound violations block the whole
    dataset rather than filtering expensive failures. Digests are not attestation.
    """
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    validate_protocol(protocol, expected_protocol_id)
    _sha(expected_dataset_sha256, 'pinned paired dataset')
    if not isinstance(rows, list) or len(rows) != len(protocol['pairs']) or _digest(rows) != expected_dataset_sha256:
        raise ValueError('complete unchanged paired dataset required')
    grouped, failures = defaultdict(list), 0
    c = protocol['coefficients']
    for pair, row in zip(protocol['pairs'], rows, strict=True):
        fields = {'pair_id', 'protocol_id', 'decision_at_ns', 'observed_at_ns', 'stop_utility',
                  'continue_utility', 'status', 'duration_ns', 'formula_work', 'outcome_receipt_sha256'}
        if not isinstance(row, dict) or set(row) != fields or row['pair_id'] != pair['pair_id'] or row['protocol_id'] != expected_protocol_id:
            raise ValueError('missing, reordered or substituted paired outcome')
        _sha(row['outcome_receipt_sha256'], 'external paired outcome receipt')
        for k in ('decision_at_ns', 'observed_at_ns', 'duration_ns'):
            _integer(row[k], k, 1)
        if not protocol['registered_at_ns'] <= row['decision_at_ns'] < row['decision_at_ns'] + row['duration_ns'] <= row['observed_at_ns'] <= protocol['cutoff_ns']:
            raise ValueError('future, pre-registration or invalid paired chronology')
        _integer(row['formula_work'], 'complete paired segment work')
        if row['duration_ns'] > protocol['duration_upper_ns'] or row['formula_work'] > protocol['formula_work_upper']:
            raise ValueError('observed envelope violation; do not filter the expensive row')
        for k in ('stop_utility', 'continue_utility'):
            _number(row[k], k, 0., 1.)
        if row['status'] not in ('completed', 'failed', 'timed_out') or (row['status'] != 'completed' and row['continue_utility'] != 0):
            raise ValueError('fail-closed continuation outcomes required')
        failures += row['status'] != 'completed'
        gain = (math.exp(-c['discount_rate_per_second'] * row['duration_ns'] / 1e9) * row['continue_utility']
                - row['stop_utility'] - c['cost_per_formula_flop'] * row['formula_work']
                - c['cost_per_latency_ns'] * row['duration_ns'])
        grouped[bucket(protocol, pair['candidate_bytes'], pair['feedback_bytes']), pair['group_id']].append(gain)
    # Runtime keeps summaries and hashes, never the observation labels or text.
    aggregates = [dict(bucket_id=b, group_id=g, attempts=len(values), mean_gain=math.fsum(values) / len(values))
                  for (b, g), values in sorted(grouped.items())]
    body = dict(schema=ARTIFACT, protocol=copy.deepcopy(protocol), dataset_sha256=expected_dataset_sha256,
                failed_attempts=failures, groups=aggregates, table=_table(protocol, aggregates),
                observer_authenticity_verified=False, conditional_exchangeability_verified=False,
                final_efficacy_established=False)
    artifact = {**body, 'artifact_id': _digest(body)}
    return artifact, dict(schema='hepta.ndu.critic-fit-work.v1', elapsed_ns=time.perf_counter_ns()-began,
                          cpu_ns=time.process_time_ns()-cpu, pairs=len(rows), failed_attempts=failures,
                          arithmetic_work=None, energy_joules=None, scope='python_fit_call_not_full_system')


def _table(p, groups):
    """min(fit mean, calibration lower bound); calibration cannot tune the bins.

    For each predeclared bin Z in [-1-C,1], Hoeffding + union over K bins gives
    radius=(2+C)*sqrt(log(K/alpha)/(2*n)) for independent group means. No assumption
    is checked by the arithmetic; this is not pointwise task confidence.
    Primary result: doi:10.1080/01621459.1963.10500830 (Hoeffding, 1963).
    """
    c = p['coefficients']
    width = 2 + c['cost_per_formula_flop']*p['formula_work_upper'] + c['cost_per_latency_ns']*p['duration_upper_ns']
    bins = [f'{i}:{j}' for i in range(len(p['candidate_edges'])+1) for j in range(len(p['feedback_edges'])+1)]
    result = {}
    for b in bins:
        fit = [g['mean_gain'] for g in groups if g['bucket_id'] == b and g['group_id'] in p['fit_groups']]
        cal = [g['mean_gain'] for g in groups if g['bucket_id'] == b and g['group_id'] in p['calibration_groups']]
        entry = dict(fit_groups=len(fit), calibration_groups=len(cal), supported=False,
                     fit_mean=None, calibration_mean=None, radius=None, net_gain_lower=None)
        if fit and cal:
            f, m = math.fsum(fit)/len(fit), math.fsum(cal)/len(cal)
            radius = width * math.sqrt((math.log(len(bins))-math.log(p['alpha']))/(2*len(cal)))
            entry.update(fit_mean=f, calibration_mean=m, radius=radius,
                         net_gain_lower=max(1-width, min(f, m-radius)),
                         supported=min(len(fit),len(cal)) >= p['minimum_groups'] and abs(f-m) <= p['max_calibration_gap'])
        result[b] = entry
    return result


def bind_capture(artifact, binding):
    """Attach checked capture linkage; never certify the external observer."""
    validate_artifact(artifact, artifact['artifact_id'])
    result = {k: copy.deepcopy(v) for k, v in artifact.items() if k != 'artifact_id'}
    result.update(schema=CAPTURED_ARTIFACT, capture_binding=copy.deepcopy(binding))
    result['artifact_id'] = _digest(result)
    validate_artifact(result, result['artifact_id'])
    return result


def validate_artifact(artifact, expected_id):
    _sha(expected_id, 'externally retained frozen critic')
    expected_fields = {'schema','protocol','dataset_sha256','failed_attempts','groups','table','observer_authenticity_verified',
                       'conditional_exchangeability_verified','final_efficacy_established','artifact_id'}
    if isinstance(artifact, dict) and artifact.get('schema') == CAPTURED_ARTIFACT:
        expected_fields.add('capture_binding')
    if not isinstance(artifact, dict) or set(artifact) != expected_fields or artifact.get('schema') not in (ARTIFACT, CAPTURED_ARTIFACT):
        raise ValueError('frozen critic artifact required')
    body = {k:v for k,v in artifact.items() if k != 'artifact_id'}
    if artifact.get('artifact_id') != expected_id or _digest(body) != expected_id:
        raise ValueError('frozen critic bytes changed')
    p = artifact['protocol']; validate_protocol(p, p['protocol_id'])
    _sha(artifact['dataset_sha256'], 'dataset identity')
    if artifact['schema'] == CAPTURED_ARTIFACT:
        binding = artifact['capture_binding']
        keys = {'capture_id', 'protocol_id', 'dataset_sha256', 'observer_receipt_sha256',
                'terminal_inventory_sha256', 'source_inventory_sha256', 'arithmetic_profile'}
        if not isinstance(binding, dict) or set(binding) != keys:
            raise ValueError('complete paired capture lineage required')
        for key in keys - {'arithmetic_profile'}:
            _sha(binding[key], 'capture linkage ' + key)
        from aten_work import PROFILE as base_profile
        from transformer_work import PROFILE as transformer_profile
        if (binding['protocol_id'] != p['protocol_id'] or binding['dataset_sha256'] != artifact['dataset_sha256']
                or binding['arithmetic_profile'] not in (base_profile, transformer_profile)):
            raise ValueError('capture linkage or arithmetic units do not match fitted data')
    expected = defaultdict(int)
    for pair in p['pairs']:
        expected[bucket(p, pair['candidate_bytes'], pair['feedback_bytes']), pair['group_id']] += 1
    groups = artifact['groups']
    if not isinstance(groups, list) or len(groups) != len(expected):
        raise ValueError('group denominator missing')
    seen = set()
    cost = p['coefficients']['cost_per_formula_flop']*p['formula_work_upper'] + p['coefficients']['cost_per_latency_ns']*p['duration_upper_ns']
    for row in groups:
        if not isinstance(row, dict) or set(row) != {'bucket_id','group_id','attempts','mean_gain'}:
            raise ValueError('invalid aggregate')
        key = row['bucket_id'],row['group_id']
        _integer(row['attempts'], 'aggregate attempts', 1)
        if key in seen or row['attempts'] != expected.get(key):
            raise ValueError('duplicate or altered aggregate denominator')
        seen.add(key); _number(row['mean_gain'], 'group net gain', -1-cost, 1.)
    if _digest(artifact['table']) != _digest(_table(p, groups)):
        raise ValueError('calibration table inconsistent with group observations')
    _integer(artifact['failed_attempts'], 'failed paired attempts')
    if artifact['failed_attempts'] > len(p['pairs']):
        raise ValueError('failed count exceeds paired inventory')
    if any(artifact.get(k) is not False for k in ('observer_authenticity_verified','conditional_exchangeability_verified','final_efficacy_established')):
        raise ValueError('artifact cannot self-certify efficacy or independence')


def main():
    """Explicit offline fitting; no acquisition or model execution in this CLI."""
    import argparse
    from pathlib import Path
    from matrix_materials import strict_json, file_sha256
    from matrix_runtime import write_json_exclusive
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('protocol','protocol-id','rows','dataset-id','output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(exist_ok=False)
    try:
        artifact, observation = fit_critic(strict_json(args.protocol),strict_json(args.rows),
                                          expected_protocol_id=args.protocol_id,expected_dataset_sha256=args.dataset_id)
        write_json_exclusive(root/'critic.json',artifact)
        write_json_exclusive(root/'fit-work.json',observation)
        write_json_exclusive(root/'COMMITTED.json',dict(artifact_id=artifact['artifact_id'],
                             files={n:file_sha256(root/n) for n in ('critic.json','fit-work.json')}))
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json',dict(error_type=type(exc).__name__,production_authorized=False))
        raise


if __name__ == '__main__':
    main()

"""Independently audit fixed V3 score arithmetic; no model, evaluator or labels."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


COMMIT = 'a062749d768ea09838921c7f3bfd8b644541b873'
PAIRS = {
    'loss2_h8_minus_h1': ('loss2_h8_direct_soft', 'loss2_h1_direct_soft'),
    'full_h8_minus_h1': ('full_h8_direct_soft', 'full_h1_direct_soft'),
    'full_h8_minus_loss2_h8': ('full_h8_direct_soft', 'loss2_h8_direct_soft'),
}


def audit(inputs, binding, analysis=None):
    root = Path(inputs)
    bound = json.loads(Path(binding).read_bytes())
    if bound['commit'] != COMMIT or len(bound['anchors']) != 18:
        raise ValueError('unexpected published input binding')
    raw = (root / 'protocol.json').read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if (hashlib.sha256(raw).hexdigest() != bound['protocol_sha256']
            or blob != bound['protocol_git_blob_sha1']):
        raise ValueError('frozen protocol bytes differ')
    plan = json.loads(raw)
    h, rho = plan['h'], plan['effort_price']
    if (h, rho, plan['direct_coefficient']) != (0.02, 0.1, 0.03):
        raise ValueError('unexpected score units')
    errors, rows, checks, verified, critic_rows = [], [], 0, [], []

    def equal(left, right):
        nonlocal checks
        if not math.isfinite(left) or not math.isfinite(right):
            raise ValueError('nonfinite score arithmetic')
        error = abs(left - right)
        if error > 5e-17 + 5e-12 * max(abs(left), abs(right)):
            raise ValueError('score arithmetic mismatch')
        errors.append(error)
        checks += 1

    expected_methods = {'zero'} | {
        f'{obs}_h{horizon}_{obj}' for obs in plan['observations']
        for horizon in plan['lookaheads'] for obj in plan['objectives']}
    for i, entry in enumerate(bound['anchors']):
        if entry['path'] != f'runs/anchor-{i:02d}.json':
            raise ValueError('published anchor order differs')
        raw = (root / entry['path']).read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('published anchor bytes differ: ' + entry['path'])
        chunk = json.loads(raw)
        initial = chunk['initial']
        records = {r['method_id']: r for r in chunk['records']}
        if (len(chunk['records']) != 19 or set(records) != expected_methods
                or initial['initial_index'] != i):
            raise ValueError('fixed candidate census differs')
        for r in records.values():
            if (r['status'] != 'completed' or r['initial_index'] != i
                    or any(r[k] != initial[k] for k in ('seed', 'head', 'anchor_offset'))):
                raise ValueError('candidate identity or completion differs')
            s = r['actual_scores']
            equal(s['direct_soft_total'], math.fsum([s['direct_current'], s['forgetting'], s['effort']]))
            equal(s['tracking_soft_total'], math.fsum([s['tracking_current'], s['forgetting'], s['effort']]))
            equal(s['effort'], rho / (2 * h) * r['physical_intervention_squared_norm'])
            equal(s['forgetting'], 0.0)
        one, other = records['loss2_h1_direct_soft'], records['full_h1_direct_soft']
        if one['actual_scores'] != other['actual_scores'] or one['final_state_sha256'] != other['final_state_sha256']:
            raise ValueError('H1 common action results differ')
        longer = records['loss2_h8_direct_soft']
        for critic in ('loss2', 'full'):
            a, b = longer['predicted_scores'][critic], one['predicted_scores'][critic]
            delta = {k: a[k] - b[k] for k in ('direct_soft_total', 'direct_current',
                                             'forgetting', 'effort', 'terminal_current_nll')}
            equal(delta['direct_soft_total'], math.fsum(delta[k] for k in ('direct_current', 'forgetting', 'effort')))
            critic_rows.append({'anchor': i, 'critic': critic, 'difference': delta,
                'predicted_J_improves': delta['direct_soft_total'] < 0,
                'predicted_current_risk_worsens': delta['direct_current'] > 0,
                'predicted_effort_reduces': delta['effort'] < 0,
                'predicted_terminal_current_nll_worsens': delta['terminal_current_nll'] > 0})
        for pair, (left, right) in PAIRS.items():
            a, b = records[left], records[right]
            x, y = a['actual_scores'], b['actual_scores']
            components = {k: x[k] - y[k] for k in ('direct_current', 'forgetting', 'effort')}
            delta_j = x['direct_soft_total'] - y['direct_soft_total']
            equal(delta_j, math.fsum(components.values()))
            ratio = math.sqrt(a['physical_intervention_squared_norm'] / b['physical_intervention_squared_norm'])
            equal(ratio, math.sqrt(x['effort'] / y['effort']))
            risk = math.fsum([components['direct_current'], components['forgetting']])
            threshold = -rho * risk / components['effort'] if components['effort'] != 0 else None
            if threshold is not None:
                equal(risk + (threshold / rho) * components['effort'], 0.0)
            rows.append({'pair': pair, 'anchor': i, 'head': initial['head'],
                'anchor_offset': initial['anchor_offset'], 'seed': initial['seed'],
                'delta_J': delta_j, **{'delta_' + k: v for k, v in components.items()},
                'delta_terminal_current_nll': x['terminal_current_nll'] - y['terminal_current_nll'],
                'physical_norm_ratio': ratio, 'fixed_action_rho_crossing': threshold})
        verified.append({'path': entry['path'], 'sha256': entry['sha256'],
            'git_blob_sha1': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()})
    summaries = {}
    for pair in PAIRS:
        selected = [r for r in rows if r['pair'] == pair]
        names = ['delta_J', 'delta_direct_current', 'delta_forgetting', 'delta_effort',
                 'delta_terminal_current_nll', 'physical_norm_ratio', 'fixed_action_rho_crossing']
        summaries[pair] = {'count': len(selected), 'statistics': {name: {
            'mean': statistics.fmean(r[name] for r in selected),
            'min': min(r[name] for r in selected), 'max': max(r[name] for r in selected)} for name in names},
            'joint_J_improves_risk_worsens_effort_reduces': sum(
                r['delta_J'] < 0 and r['delta_direct_current'] > 0 and r['delta_effort'] < 0 for r in selected),
            'current_risk_and_effort_both_improve': sum(
                r['delta_direct_current'] < 0 and r['delta_effort'] < 0 for r in selected),
            'terminal_current_nll_worsens': sum(r['delta_terminal_current_nll'] > 0 for r in selected)}
    implementation_comparison = None
    if analysis:
        published_analysis = json.loads(Path(analysis).read_bytes())
        pairs = {'loss2_h8_vs_myopic': 'loss2_h8_minus_h1',
                 'full_h8_vs_myopic': 'full_h8_minus_h1',
                 'full_h8_vs_loss2_h8': 'full_h8_minus_loss2_h8'}
        indexed = {(r['pair'], r['head'], r['seed'], r['anchor_offset']): r for r in rows}
        for actual in published_analysis['comparisons']:
            wanted = indexed[(pairs[actual['contrast']], actual['head'], actual['seed'], actual['anchor_offset'])]
            for name, field in [('direct_soft_total', 'J'), ('direct_current', 'direct_current'),
                                ('forgetting', 'forgetting'), ('effort', 'effort'),
                                ('terminal_current_nll', 'terminal_current_nll')]:
                equal(actual['difference'][name], wanted['delta_' + field])
            equal(actual['action_norm_ratio'], wanted['physical_norm_ratio'])
            threshold = actual['fixed_action_rho']['rho_star']
            if threshold is not None:
                equal(threshold, wanted['fixed_action_rho_crossing'])
        if len(published_analysis['comparisons']) != 54 or published_analysis['source_commit'] != COMMIT:
            raise ValueError('primary decomposition census or source differs')
        implementation_comparison = {'report_sha256': hashlib.sha256(Path(analysis).read_bytes()).hexdigest(),
                                     'per_anchor_comparisons_checked': 54}
    critic_summaries = {}
    for critic in ('loss2', 'full'):
        chosen = [r for r in critic_rows if r['critic'] == critic]
        critic_summaries[critic] = {'anchors': len(chosen),
            'means': {k: statistics.fmean(r['difference'][k] for r in chosen) for k in chosen[0]['difference']},
            'all_predict_J_improvement_with_worse_risk_lower_effort_and_worse_terminal_current_nll': all(
                r['predicted_J_improves'] and r['predicted_current_risk_worsens']
                and r['predicted_effort_reduces'] and r['predicted_terminal_current_nll_worsens'] for r in chosen)}
    return {'schema': 'hepta.v3-independent-objective-decomposition-audit.v1',
        'input_commit': COMMIT, 'protocol_sha256': bound['protocol_sha256'],
        'verified_anchors': verified, 'candidate_score_records_checked': 342,
        'scalar_equalities_checked': checks, 'maximum_absolute_arithmetic_discrepancy': max(errors),
        'summaries': summaries, 'pair_rows': rows,
        'critic_pair_rows': critic_rows, 'critic_pair_summaries': critic_summaries,
        'primary_analysis_comparison': implementation_comparison,
        'analysis_implementation_imported': False, 'training_or_evaluator_imported': False,
        'label_payloads_read': False, 'new_actions_or_policies_executed': False,
        'scope': 'Independent published-source score arithmetic; no new statistical inference. '
                 'Effort is a quadratic action penalty, not measured compute or elapsed time. '
                 'Rho crossings hold only for fixed actions; no re-optimization or policy selection.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs', 'binding', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--analysis')
    args = parser.parse_args()
    result = audit(args.inputs, args.binding, args.analysis)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('candidate_score_records_checked', 'scalar_equalities_checked',
        'maximum_absolute_arithmetic_discrepancy', 'summaries')}, ensure_ascii=False, indent=2))

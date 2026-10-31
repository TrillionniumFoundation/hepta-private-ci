"""Census, paired inference, measured costs and selected-action diagnostics."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time

import numpy as np

from ...abc_recovery.base_recovery import file_sha, write_json
from .rollout import POLICIES


def key(row):
    return tuple(row[k] for k in ('seed', 'case', 'view', 'draw', 'policy'))


def read_rows(directory):
    with gzip.open(directory / 'requests.jsonl.gz', 'rt') as stream:
        all_rows = list(map(json.loads, stream))
        rows = {key(r): r for r in all_rows}
    if len(rows) != len(all_rows):
        raise ValueError('Duplicate request identity')
    with gzip.open(directory / 'scored.jsonl.gz', 'rt') as stream:
        scored = list(map(json.loads, stream))
    if len(rows) != len(scored) or len({key(r) for r in scored}) != len(rows):
        raise ValueError('Missing/duplicate request or score identity')
    for score in scored:
        rows[key(score)].update(score)
    return rows


def ce(values):
    scaled = -2. * np.asarray(values, dtype=np.float64)
    shift = scaled.max()
    return float(-(shift + np.log(np.exp(scaled - shift).mean())) / 2.)


def interval(point, draws, level=.975):
    tail = (1. - level) / 2.
    return {'estimate': float(point), 'lower': float(np.quantile(draws, tail)),
            'upper': float(np.quantile(draws, 1. - tail)), 'nominal_level': level}


def run(directory, development):
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    registration = json.loads((directory / 'registration.json').read_text())
    completion = json.loads((directory / 'completion.json').read_text())
    spec = registration['evaluation']
    for file, field in (('requests.jsonl.gz', 'requests_sha256'), ('scored.jsonl.gz', 'scored_sha256'),
                        ('actual-media.bin', 'media_sha256'), ('commitments.jsonl.gz', 'commitments_sha256'),
                        ('calibration-media.bin.gz', 'calibration_media_sha256')):
        if file_sha(directory / file) != completion[field]:
            raise ValueError('Closed evidence changed: ' + file)
    rows = read_rows(directory)
    seeds, cases, views = completion['seeds'], range(spec['pair_start'], spec['pair_start'] + spec['pair_count']), spec['views']
    expected = {(s, c, v, d, p) for s in seeds for c in cases for v in views for d in range(2) for p in POLICIES}
    if set(rows) != expected or len(rows) != spec['requests']:
        raise ValueError('Frozen source/view/seed/future/policy census differs')
    failures = [r for r in rows.values() if r['status'] != 'completed']
    if failures:
        write_json(directory / 'analysis.json', {'status': 'blocked_by_actual_failures', 'failures': failures,
                   'attempts': len(rows), 'quality_inference_permitted': False})
        return
    with gzip.open(directory / 'commitments.jsonl.gz', 'rt') as stream:
        commits = Counter()
        for row in map(json.loads, stream):
            identity = key(row); decision = row['decision_index']
            if decision != commits[identity] or {k: row[k] for k in rows[identity]['decisions'][decision]} != rows[identity]['decisions'][decision]:
                raise ValueError('Durable commitment order/content differs')
            commits[identity] += 1
    if any(commits[k] != len(r['decisions']) for k, r in rows.items()) or set(commits) != set(rows):
        raise ValueError('Durable action commitment census differs')
    fitted = json.loads((development / 'result.json').read_text())
    disabled = {r['seed'] for r in fitted['records'] if r['threshold'] is None}
    disabled_pairs = 0
    for s in disabled:
        for c in cases:
            for v in views:
                for d in range(2):
                    teacher, gate = rows[s, c, v, d, 'cached_teacher'], rows[s, c, v, d, 'selected_gate']
                    if (teacher['output_sha256'], teacher['path']) != (gate['output_sha256'], gate['path']):
                        raise ValueError('Disabled gate differs from frozen exact fallback')
                    disabled_pairs += 1
    shape = (4, len(seeds), len(cases), len(views), 2)
    utility, success, wall, cpu_cost = (np.empty(shape, dtype=np.float64) for _ in range(4))
    secondary = np.empty_like(utility)
    policy_detail = {}
    for p, policy in enumerate(POLICIES):
        selected, work, actions = [], Counter(), Counter()
        for si, s in enumerate(seeds):
            for ci, c in enumerate(cases):
                for vi, v in enumerate(views):
                    for d in range(2):
                        row = rows[s, c, v, d, policy]; index = p, si, ci, vi, d
                        utility[index] = row['scores']['primary']['utility']
                        success[index] = row['scores']['primary']['joint_fact_correct']
                        secondary[index] = row['scores']['secondary']['utility']
                        wall[index], cpu_cost[index] = row['wall_ns'] / 1e6, row['cpu_ns'] / 1e6
                        work.update(row['work']); actions.update(x['action'] for x in row['decisions'])
                        steps = [x for x in row['decisions'] if 'paired_prediction' in x]
                        if len(steps) != len(row['selected_action_calibration']):
                            raise ValueError('Selected-action calibration pairing differs')
                        for step, before in zip(steps, row['selected_action_calibration']):
                            actual = np.exp(-2 * (utility[index] - .002 * (step['action'] != 'stop'))) - np.exp(-2 * before['primary'])
                            selected.append((step['paired_prediction'], actual, step['confidence'], step['cheap'], step['action'] != 'stop'))
        calibration = np.asarray(selected, dtype=np.float64).reshape(-1, 5)
        nonstop = calibration[:, 4] > 0
        bins = []
        for lo, hi in ((-10., -.1), (-.1, -.025), (-.025, 0.), (0., 10.)):
            mask = (calibration[:, 0] >= lo) & (calibration[:, 0] < hi)
            bins.append({'predicted_interval': [lo, hi], 'n': int(mask.sum()),
                         'predicted_mean': float(calibration[mask, 0].mean()) if mask.any() else None,
                         'realized_mean': float(calibration[mask, 1].mean()) if mask.any() else None})
        policy_detail[policy] = {'CE': ce(utility[p]), 'success': float(success[p].mean()),
            'secondary_CE': ce(secondary[p]), 'mean_wall_ms': float(wall[p].mean()),
            'wall_p50_p95_p99_max_ms': np.quantile(wall[p], [.5, .95, .99, 1.]).tolist(),
            'mean_cpu_ms': float(cpu_cost[p].mean()), 'work': dict(work), 'action_counts': dict(actions),
            'selected_H1_calibration': {'n': len(calibration), 'bins': bins,
                'nonstop_n': int(nonstop.sum()),
                'nonstop_MSE': float(((calibration[nonstop, 0] - calibration[nonstop, 1]) ** 2).mean()) if nonstop.any() else None,
                'prediction_bias': float((calibration[:, 0] - calibration[:, 1]).mean()) if len(calibration) else None,
                'MSE': float(((calibration[:, 0] - calibration[:, 1]) ** 2).mean()) if len(calibration) else None,
                'scope': 'Adaptive selected-action realized paired differences; finite sample, not conditional/uniform certification'},
            'per_seed': {str(s): {'CE': ce(utility[p, i]), 'success': float(success[p, i].mean()),
                                  'mean_wall_ms': float(wall[p, i].mean())} for i, s in enumerate(seeds)}}
    rng = np.random.default_rng(spec['bootstrap_seed'])
    count = spec['bootstrap_replicates']
    sw = rng.multinomial(len(seeds), np.full(len(seeds), 1 / len(seeds)), size=count) / len(seeds)
    cw = rng.multinomial(len(cases), np.full(len(cases), 1 / len(cases)), size=count) / len(cases)
    def means(values):
        return np.einsum('rs,psc,rc->pr', sw, values.mean(axis=(-1, -2)), cw, optimize=True)
    def ces(values):
        shift = (-2 * values).max(axis=(1, 2, 3, 4))
        moments = np.exp(-2 * values - shift[:, None, None, None, None])
        return -(np.log(means(moments)) + shift[:, None]) / 2
    boot_ce, boot_success, boot_wall, boot_cpu, boot_secondary = ces(utility), means(success), means(wall), means(cpu_cost), ces(secondary)
    contrasts = {}
    for p, policy in enumerate(POLICIES[1:], 1):
        detail = {'raw_CE': interval(ce(utility[p]) - ce(utility[0]), boot_ce[p] - boot_ce[0]),
            'success': interval(success[p].mean() - success[0].mean(), boot_success[p] - boot_success[0]),
            'mean_wall_ms': interval(wall[p].mean() - wall[0].mean(), boot_wall[p] - boot_wall[0]),
            'mean_cpu_ms': interval(cpu_cost[p].mean() - cpu_cost[0].mean(), boot_cpu[p] - boot_cpu[0]),
            'secondary_CE': interval(ce(secondary[p]) - ce(secondary[0]), boot_secondary[p] - boot_secondary[0])}
        for name, cost in (('wall', wall), ('cpu', cpu_cost)):
            points, draws = [], []
            for price in spec['prices_utility_per_actual_ms']:
                value = utility - price * cost
                points.append(ce(value[p]) - ce(value[0])); sample = ces(value)
                draws.append(sample[p] - sample[0])
            radius = float(np.quantile(np.max(np.abs(np.stack(draws) - np.asarray(points)[:, None]), axis=0), .95))
            detail[name + '_price_curve'] = [{'price_utility_per_ms': price, 'estimate': point, 'simultaneous_lower': point - radius,
                                              'simultaneous_upper': point + radius} for price, point in zip(spec['prices_utility_per_actual_ms'], points)]
        detail['replacement_family_pass'] = (detail['raw_CE']['lower'] >= -.005 and detail['success']['lower'] >= -.005
                                               and detail['mean_wall_ms']['upper'] < 0)
        detail['quality_superiority_family_pass'] = detail['raw_CE']['lower'] > 0 and detail['success']['lower'] >= 0
        contrasts[policy] = detail
    result = {'schema': 'hepta.closure.control-analysis.v1', 'status': 'completed', 'attempts': len(rows), 'failures': 0,
        'source_pairs': len(cases), 'new_independent_sources': completion['new_independent_sources'],
        'scope': registration['scope'], 'statistical_scope': spec['statistical_scope'],
        'interval_scope': 'Nominal crossed source/seed bootstrap; views/draws kept together, five seeds, no finite-sample coverage guarantee',
        'disabled_gate_identity_pairs': disabled_pairs, 'policies': policy_detail, 'contrasts_vs_cached_teacher': contrasts,
        'empirical_four_policy_hindsight': {'CE': ce(utility.max(0)),
            'CE_gap_from_teacher': ce(utility.max(0)) - ce(utility[0]),
            'scope': 'Private target and realized future choose among four policy outputs; not a feasible online oracle or an action-wise global optimum'},
        'preselected_gate_accepted_decisions': sum(x['cheap'] for r in rows.values() if r['policy'] == 'selected_gate' for x in r['decisions']),
        'preselected_gate_total_decisions': sum(len(r['decisions']) for r in rows.values() if r['policy'] == 'selected_gate'),
        'completion_sha256': file_sha(directory / 'completion.json'), 'analysis_source_sha256': file_sha(Path(__file__)),
        'analysis_wall_ns': time.perf_counter_ns() - start, 'analysis_cpu_ns': time.process_time_ns() - cpu}
    write_json(directory / 'analysis.json', result)
    print(json.dumps({'sources': len(cases), 'new_sources': completion['new_independent_sources'],
                      'selected_gate': contrasts['selected_gate'], 'policies': {p: {k: policy_detail[p][k] for k in ('CE', 'success', 'mean_wall_ms')} for p in POLICIES}}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    args = parser.parse_args(); run(args.directory, args.development)

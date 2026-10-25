"""Independent read-only review of closed primary control observations."""

import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ce(values):
    scaled = [-2 * value for value in values]
    shift = max(scaled)
    return -(shift + math.log(math.fsum(math.exp(v - shift) for v in scaled) / len(scaled))) / 2


def review(directory, development, output):
    began = time.monotonic_ns()
    with gzip.open(directory / 'requests.jsonl.gz', 'rt') as stream:
        requests = list(map(json.loads, stream))
    with gzip.open(directory / 'scored.jsonl.gz', 'rt') as stream:
        scored = list(map(json.loads, stream))
    key = lambda row: tuple(row[k] for k in ('seed', 'case', 'view', 'draw', 'policy'))
    rows = {key(row): row for row in requests}
    assert len(rows) == len(requests) == len(scored)
    assert set(rows) == {key(row) for row in scored}
    for row in scored:
        rows[key(row)].update(row)
    spec = json.loads((directory / 'registration.json').read_text())['evaluation']
    completion = json.loads((directory / 'completion.json').read_text())
    analysis = json.loads((directory / 'analysis.json').read_text())
    fitted = json.loads((development / 'result.json').read_text())
    media = (directory / 'actual-media.bin').read_bytes()
    with gzip.open(directory / 'calibration-media.bin.gz', 'rb') as stream:
        calibration = stream.read()
    assert len(rows) == spec['requests'] and len(media) == 204 * len(rows)
    counts, policies = collections.Counter(), collections.defaultdict(list)
    initial, paths, identities = collections.defaultdict(set), collections.defaultdict(set), {}
    for row in rows.values():
        assert row['status'] == 'completed'
        raw = media[row['offset']:row['offset'] + 204]
        assert hashlib.sha256(raw).hexdigest() == row['payload_sha256']
        identities.setdefault(row['case'], tuple(row['source_ids']))
        assert identities[row['case']] == tuple(row['source_ids'])
        initial[row['seed'], row['case'], row['view']].add(row['decisions'][0]['public_sha256'])
        paths[row['seed'], row['case'], row['view'], row['draw'], tuple(row['path'])].add(row['output_sha256'])
        steps = [d for d in row['decisions'] if 'paired_prediction' in d]
        assert len(steps) == len(row['selected_action_calibration']) == len(row['calibration_records'])
        for step, observed, record in zip(steps, row['selected_action_calibration'], row['calibration_records']):
            assert step['remaining'] == 1 and step is row['decisions'][-1]
            before = calibration[record['offset']:record['offset'] + 204]
            assert hashlib.sha256(before).hexdigest() == record['sha256']
            counts['H1'] += 1
            if step['action'] == 'stop':
                assert before == raw and observed['primary'] == row['scores']['primary']['utility']
                assert step['paired_prediction'] == 0.
                counts['H1_stop_exact_media_utility_and_zero_prediction'] += 1
            else:
                counts['H1_nonstop_final_action'] += 1
        policies[row['policy']].append(row)
    assert all(len(value) == 1 for value in initial.values())
    assert all(len(value) == 1 for value in paths.values())
    assert len(identities) == spec['pair_count']
    assert len(set(value for pair in identities.values() for value in pair)) == 2 * len(identities)
    baseline = policies['cached_teacher']
    for policy, selected in policies.items():
        point = ce([r['scores']['primary']['utility'] for r in selected])
        assert abs(point - analysis['policies'][policy]['CE']) < 1e-12
        if policy == 'cached_teacher':
            continue
        for clock in ('wall', 'cpu'):
            for curve in analysis['contrasts_vs_cached_teacher'][policy][clock + '_price_curve']:
                price = curve['price_utility_per_ms']
                score = lambda q: q['scores']['primary']['utility'] - price * q[clock + '_ns'] / 1e6
                point = ce([score(q) for q in selected]) - ce([score(q) for q in baseline])
                assert abs(point - curve['estimate']) < 1e-12
    seeds, views = completion['seeds'], spec['views']
    cases = range(spec['pair_start'], spec['pair_start'] + spec['pair_count'])
    utility = np.array([[[[[rows[s, c, v, d, policy]['scores']['primary']['utility'] for d in range(2)]
                          for v in views] for c in cases] for s in seeds] for policy in spec['policies']])
    rng = np.random.default_rng(spec['bootstrap_seed'])
    sw = rng.multinomial(len(seeds), np.full(len(seeds), 1 / len(seeds)), size=spec['bootstrap_replicates'])
    cw = rng.multinomial(len(cases), np.full(len(cases), 1 / len(cases)), size=spec['bootstrap_replicates'])
    moments = np.exp(-2 * utility).mean(axis=(3, 4))
    draws = -np.log(np.einsum('rs,psc,rc->pr', sw / len(seeds), moments, cw / len(cases), optimize=True)) / 2
    for replicate in range(10):
        si = np.repeat(np.arange(len(seeds)), sw[replicate])
        ci = np.repeat(np.arange(len(cases)), cw[replicate])
        literal = -np.log(np.exp(-2 * utility[:, si][:, :, ci]).mean(axis=(1, 2, 3, 4))) / 2
        np.testing.assert_allclose(literal, draws[:, replicate], rtol=0, atol=1e-12)
    for index, policy in enumerate(spec['policies'][1:], 1):
        interval = analysis['contrasts_vs_cached_teacher'][policy]['raw_CE']
        values = draws[index] - draws[0]
        assert abs(float(np.quantile(values, .0125)) - interval['lower']) < 1e-12
        assert abs(float(np.quantile(values, .9875)) - interval['upper']) < 1e-12
    thresholds = {str(record['seed']): record['threshold'] for record in fitted['records']}
    disabled_pairs = 0
    for identity, row in rows.items():
        if row['policy'] == 'selected_gate' and thresholds[str(row['seed'])] is None:
            teacher = rows[(*identity[:-1], 'cached_teacher')]
            assert (teacher['path'], teacher['output_sha256']) == (row['path'], row['output_sha256'])
            disabled_pairs += 1
    record = {'schema': 'hepta.closure.control-independent-review.v1', 'status': 'passed',
              'directory': str(directory), 'rows': len(rows), 'source_pairs': len(identities),
              'all_terminal_and_calibration_media_hashes_checked': True,
              'H1_calibration_pairing': dict(counts), 'same_initial_state_groups': len(initial),
              'same_path_same_output_groups': len(paths), 'all_policy_CE_and_cost_CE_points_recomputed': True,
              'crossed_bootstrap_replicates': len(sw), 'literal_resampling_comparisons': 10,
              'all_raw_CE_intervals_reproduced': True, 'frozen_thresholds': thresholds,
              'disabled_gate_exact_fallback_pairs': disabled_pairs,
              'accepted_cheap_decisions': analysis['preselected_gate_accepted_decisions'],
              'total_selected_gate_decisions': analysis['preselected_gate_total_decisions'],
              'interpretation': 'All five gates disabled: same fallback algorithm; timing difference cannot establish actor, gate, or adaptive-information benefit',
              'limitations': ['Nominal crossed bootstrap with five seeds, not finite-sample coverage',
                              'Price bands simultaneous only within each declared contrast and clock',
                              'Historical review does not add independent sources or evaluate still-running fresh data'],
              'analysis_sha256': sha(directory / 'analysis.json'), 'completion_sha256': sha(directory / 'completion.json'),
              'review_source_sha256': sha(__file__), 'review_wall_ns': time.monotonic_ns() - began}
    with output.open('x') as stream:
        json.dump(record, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(record, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('directory', 'development', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    review(args.directory, args.development, args.output)

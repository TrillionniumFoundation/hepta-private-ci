"""A single fixed-seed candidate: paired source-cluster inference, no seed pooling."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time

import numpy as np

from ....abc_recovery.base_recovery import file_sha, write_json
from ..analysis import ce, interval, key, read_rows


def run(directory, protocol):
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    spec = json.loads(protocol.read_text())
    done = json.loads((directory / 'completion.json').read_text())
    for name, digest in done['files_sha256'].items():
        if file_sha(directory / name) != digest:
            raise ValueError('Closed confirmation evidence changed')
    rows = read_rows(directory); views = spec['evaluation']['views']
    expected = {(17, c, v, d, p) for c in range(96) for v in views for d in range(2) for p in spec['policies']}
    if set(rows) != expected or len(rows) != 3072 or done['failed']:
        raise ValueError('Every registered single-seed request must complete before inference')
    with gzip.open(directory / 'commitments.jsonl.gz', 'rt') as stream:
        committed = Counter()
        for entry in map(json.loads, stream):
            identity = key(entry); index = entry['decision_index']
            if index != committed[identity] or {k: entry[k] for k in rows[identity]['decisions'][index]} != rows[identity]['decisions'][index]:
                raise ValueError('Confirmation durable commitment mismatch')
            committed[identity] += 1
    if set(committed) != expected or any(committed[k] != len(r['decisions']) for k, r in rows.items()):
        raise ValueError('Confirmation durable commitment census differs')
    shape = 2, 96, len(views), 2
    utility, success, secondary, wall, cpu = (np.empty(shape) for _ in range(5))
    detail, calibration = {}, []
    for pi, policy in enumerate(spec['policies']):
        work = Counter(); decision_count = accepted = 0
        for c in range(96):
            for vi, v in enumerate(views):
                for d in range(2):
                    row = rows[17, c, v, d, policy]; at = pi, c, vi, d
                    baseline = rows[17, c, v, d, spec['policies'][0]]
                    if row['source_ids'] != baseline['source_ids'] or row['decisions'][0]['public_sha256'] != baseline['decisions'][0]['public_sha256']:
                        raise ValueError('Paired policies do not share public initial state')
                    if row['path'] == baseline['path'] and row['output_sha256'] != baseline['output_sha256']:
                        raise ValueError('Same action path differs under paired RNG')
                    utility[at], success[at] = row['scores']['primary']['utility'], row['scores']['primary']['joint_fact_correct']
                    secondary[at] = row['scores']['secondary']['utility']
                    wall[at], cpu[at] = row['wall_ns'] / 1e6, row['cpu_ns'] / 1e6
                    work.update(row['work']); decision_count += len(row['decisions'])
                    accepted += sum(x['cheap'] for x in row['decisions'])
                    steps = [x for x in row['decisions'] if 'paired_prediction' in x]
                    if len(steps) != len(row['selected_action_calibration']):
                        raise ValueError('Confirmation selected-action calibration unpaired')
                    for step, previous in zip(steps, row['selected_action_calibration']):
                        actual = np.exp(-2 * (utility[at] - .002 * (step['action'] != 'stop'))) - np.exp(-2 * previous['primary'])
                        calibration.append((step['paired_prediction'], actual, step['action'] != 'stop'))
        detail[policy] = {'raw_CE': ce(utility[pi]), 'exact_success': float(success[pi].mean()),
                         'secondary_CE': ce(secondary[pi]), 'mean_wall_ms': float(wall[pi].mean()),
                         'mean_cpu_ms': float(cpu[pi].mean()), 'wall_p50_p95_p99_max_ms': np.quantile(wall[pi], [.5, .95, .99, 1.]).tolist(),
                         'work': dict(work), 'decisions': decision_count, 'cheap_decisions': accepted}
    rng = np.random.default_rng(spec['bootstrap_seed'])
    weights = rng.multinomial(96, np.full(96, 1 / 96), size=spec['bootstrap_replicates']) / 96
    def means(values):
        return values.mean((-1, -2)) @ weights.T
    def ces(values):
        shift = (-2 * values).max((1, 2, 3))
        return -(np.log(means(np.exp(-2 * values - shift[:, None, None, None]))) + shift[:, None]) / 2
    contrasts = {}
    for name, values, moment in (('raw_CE', utility, True), ('exact_success', success, False),
                                 ('mean_wall_ms', wall, False), ('mean_cpu_ms', cpu, False), ('secondary_CE', secondary, True)):
        boot = ces(values) if moment else means(values)
        point = ce(values[1]) - ce(values[0]) if moment else values[1].mean() - values[0].mean()
        contrasts[name] = interval(point, boot[1] - boot[0])
    for name, cost in (('wall', wall), ('cpu', cpu)):
        points, draws = [], []
        for price in spec['evaluation']['prices_utility_per_actual_ms']:
            value = utility - price * cost; boot = ces(value)
            points.append(ce(value[1]) - ce(value[0])); draws.append(boot[1] - boot[0])
        radius = float(np.quantile(np.max(np.abs(np.stack(draws) - np.asarray(points)[:, None]), 0), .95))
        contrasts[name + '_price_curve'] = [{'price_utility_per_ms': price, 'estimate': value,
                                            'simultaneous_lower': value - radius, 'simultaneous_upper': value + radius}
                                           for price, value in zip(spec['evaluation']['prices_utility_per_actual_ms'], points)]
    gates = {'raw_CE_noninferiority': contrasts['raw_CE']['lower'] >= -.005,
             'success_noninferiority': contrasts['exact_success']['lower'] >= -.005,
             'request_wall_saving': contrasts['mean_wall_ms']['upper'] < 0}
    array = np.asarray(calibration).reshape(-1, 3); nonstop = array[:, 2] > 0
    result = {'schema': 'hepta.closure.control-repair-confirmation-analysis.v1', 'status': 'completed',
              'requests': len(rows), 'failures': 0, 'new_source_pairs': 96, 'training_seed': 17,
              'scope': 'Conditional on exactly the frozen seed-17 generator/teacher; no cross-training-seed generalization claim',
              'source_clusters': 96, 'within_source_views_and_futures_are_independent_N': False,
              'policies': detail, 'candidate_minus_cached_teacher': contrasts, 'primary_family': gates,
              'qualified_conditional_replacement': all(gates.values()),
              'zero_margin_quality_superiority': contrasts['raw_CE']['lower'] > 0 and contrasts['exact_success']['lower'] >= 0,
              'selected_H1_calibration': {'n': len(array), 'nonstop_n': int(nonstop.sum()),
                  'prediction_bias': float((array[:, 0] - array[:, 1]).mean()) if len(array) else None,
                  'MSE': float(((array[:, 0] - array[:, 1]) ** 2).mean()) if len(array) else None,
                  'nonstop_MSE': float(((array[nonstop, 0] - array[nonstop, 1]) ** 2).mean()) if nonstop.any() else None},
              'inference': '2000 source-cluster bootstrap replicates, nominal97.5% component intervals; separate nominal95% finite-price bands per clock; no uniform conditional guarantee',
              'completion_sha256': file_sha(directory / 'completion.json'), 'protocol_sha256': file_sha(protocol),
              'analysis_wall_ns': time.perf_counter_ns() - started, 'analysis_cpu_ns': time.process_time_ns() - cpu_started}
    write_json(directory / 'analysis.json', result)
    print(json.dumps({'primary_family': gates, 'qualified': all(gates.values()), 'contrasts': contrasts}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args(); run(args.directory, args.protocol)

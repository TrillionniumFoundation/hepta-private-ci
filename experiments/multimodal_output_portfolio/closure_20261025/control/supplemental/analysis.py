"""Exploratory same-source dynamic/nonfeedback comparison; no batched clock claim."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time

import numpy as np

from ....abc_recovery.base_recovery import file_sha, write_json
from ..analysis import ce, interval, key, read_rows


def run(primary, supplement, protocol):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    spec = json.loads(protocol.read_text())
    base_done, extra_done = (json.loads((p / 'completion.json').read_text()) for p in (primary, supplement))
    if base_done['failed'] or extra_done['failed']:
        raise ValueError('Any primary/supplement failure blocks exploratory quality inference')
    for file, expected in extra_done['files_sha256'].items():
        if file_sha(supplement / file) != expected:
            raise ValueError('Supplement evidence changed')
    for file, field in (('requests.jsonl.gz', 'requests_sha256'), ('scored.jsonl.gz', 'scored_sha256')):
        if file_sha(primary / file) != base_done[field]:
            raise ValueError('Primary evidence changed')
    original, added = read_rows(primary), read_rows(supplement)
    seeds, views = spec['seeds'], spec['evaluation']['views']
    expected = {(s, c, v, d, p) for s in seeds for c in range(256) for v in views for d in range(2) for p in spec['policies']}
    if set(added) != expected:
        raise ValueError('Supplemental source/policy census differs')
    with gzip.open(supplement / 'commitments.jsonl.gz', 'rt') as stream:
        commits = Counter()
        for row in map(json.loads, stream):
            identity = key(row); decision = row['decision_index']
            if decision != commits[identity] or {k: row[k] for k in added[identity]['decisions'][decision]} != added[identity]['decisions'][decision]:
                raise ValueError('Supplemental action ledger differs')
            commits[identity] += 1
    if set(commits) != expected or any(commits[k] != len(r['decisions']) for k, r in added.items()):
        raise ValueError('Supplemental action census differs')
    same_path = 0
    for (s, c, v, d, p), row in added.items():
        teacher = original[s, c, v, d, 'cached_teacher']
        if row['source_ids'] != teacher['source_ids'] or row['decisions'][0]['public_sha256'] != teacher['decisions'][0]['public_sha256']:
            raise ValueError('Supplement and primary do not begin from identical public state')
        if row['path'] == teacher['path']:
            same_path += 1
            if row['output_sha256'] != teacher['output_sha256']:
                raise ValueError('Same actual path has different terminal media')
    rows = original | added
    names = ['cached_teacher', *spec['policies']]
    shape = len(names), len(seeds), 256, len(views), 2
    utility, success, secondary, measured_wall, measured_cpu = (np.empty(shape) for _ in range(5))
    detail = {}
    for pi, p in enumerate(names):
        work = Counter()
        for si, s in enumerate(seeds):
            for c in range(256):
                for vi, v in enumerate(views):
                    for d in range(2):
                        row = rows[s, c, v, d, p]; at = pi, si, c, vi, d
                        utility[at], success[at] = row['scores']['primary']['utility'], row['scores']['primary']['joint_fact_correct']
                        secondary[at] = row['scores']['secondary']['utility']
                        measured_wall[at], measured_cpu[at] = row['wall_ns'] / 1e6, row['cpu_ns'] / 1e6
                        work.update(row['work'])
        detail[p] = {'CE': ce(utility[pi]), 'success': float(success[pi].mean()), 'secondary_CE': ce(secondary[pi]),
                     'mean_wall_ms': float(measured_wall[pi].mean()), 'mean_cpu_ms': float(measured_cpu[pi].mean()),
                     'work': dict(work), 'per_seed': {str(s): {'CE': ce(utility[pi, i]), 'success': float(success[pi, i].mean())} for i, s in enumerate(seeds)}}
    rng = np.random.default_rng(20261025482)
    sw = rng.multinomial(len(seeds), np.full(len(seeds), 1 / len(seeds)), size=2000) / len(seeds)
    cw = rng.multinomial(256, np.full(256, 1 / 256), size=2000) / 256
    def means(values):
        return np.einsum('rs,psc,rc->pr', sw, values.mean((-1, -2)), cw, optimize=True)
    def ces(values):
        shift = (-2 * values).max((1, 2, 3, 4))
        return -(np.log(means(np.exp(-2 * values - shift[:, None, None, None, None]))) + shift[:, None]) / 2
    boot_ce, boot_success, boot_secondary = ces(utility), means(success), ces(secondary)
    contrasts = {}
    for pi, p in enumerate(names[1:], 1):
        contrasts[p] = {'teacher_minus_baseline_raw_CE': interval(ce(utility[0]) - ce(utility[pi]), boot_ce[0] - boot_ce[pi]),
                        'teacher_minus_baseline_success': interval(success[0].mean() - success[pi].mean(), boot_success[0] - boot_success[pi]),
                        'teacher_minus_baseline_secondary_CE': interval(ce(secondary[0]) - ce(secondary[pi]), boot_secondary[0] - boot_secondary[pi]),
                        'descriptive_teacher_minus_baseline_wall_ms': float(measured_wall[0].mean() - measured_wall[pi].mean()),
                        'descriptive_teacher_minus_baseline_cpu_ms': float(measured_cpu[0].mean() - measured_cpu[pi].mean()),
                        'causal_clock_superiority_claim_permitted': False}
    result = {'schema': 'hepta.closure.control-supplement-analysis.v1', 'status': 'completed',
              'scope': spec['status'], 'source_pairs': 256, 'additional_independent_sources': 0,
              'supplement_requests': len(added), 'failures': 0, 'identical_public_root_pairs': len(added),
              'same_path_identical_terminal_pairs': same_path, 'policies': detail, 'teacher_minus_baselines': contrasts,
              'cost_scope': spec['cost_scope'], 'statistical_scope': 'Exploratory 2000 crossed seed/source bootstrap, 97.5% nominal component intervals; no finite-five-seed coverage guarantee',
              'primary_completion_sha256': file_sha(primary / 'completion.json'),
              'supplement_completion_sha256': file_sha(supplement / 'completion.json'),
              'analysis_wall_ns': time.perf_counter_ns() - wall, 'analysis_cpu_ns': time.process_time_ns() - cpu}
    write_json(supplement / 'analysis.json', result)
    print(json.dumps({'scope': result['scope'], 'same_path_pairs': same_path, 'contrasts': contrasts}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary', type=Path, required=True)
    parser.add_argument('--supplement', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args(); run(args.primary, args.supplement, args.protocol)

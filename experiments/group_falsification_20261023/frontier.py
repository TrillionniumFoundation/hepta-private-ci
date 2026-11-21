"""Descriptive engineering frontier only; no equal-work scientific ranking."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / 'results_v2/trajectories.jsonl'
rows = [json.loads(line) for line in INPUT.read_text().splitlines()]
points = []
for scope in ('17', '29', '43', 'pooled'):
    for budget in (8, 16):
        for variant in sorted({r['variant'] for r in rows}):
            group = []
            for policy in sorted({r['policy'] for r in rows}):
                selected = [r for r in rows if r['budget'] == budget and r['variant'] == variant
                            and r['policy'] == policy and (scope == 'pooled' or str(r['seed']) == scope)]
                n = len(selected)
                correct = sum(r['correct'] for r in selected)
                answered = sum(r['answered'] for r in selected)
                point = dict(scope=scope, budget=budget, logical_depth=budget//4,
                             variant=variant, policy=policy, n=n, correct=correct,
                             accuracy=correct/n, coverage=answered/n,
                             selective_risk=(answered-correct)/answered if answered else '',
                             actual_calls=sum(r['calls'] for r in selected),
                             candidate_evaluations=sum(r['candidate_evaluations'] for r in selected),
                             trajectory_cpu_seconds=sum(r['cpu_seconds'] for r in selected),
                             trajectory_wall_seconds=sum(r['wall_seconds'] for r in selected),
                             inference_dense_flops_estimate=sum(r['flops_dense_estimate'] for r in selected))
                group.append(point)
            for point in group:
                def dominates(other):
                    weak = (other['accuracy'] >= point['accuracy'] and
                            other['actual_calls'] <= point['actual_calls'] and
                            other['trajectory_cpu_seconds'] <= point['trajectory_cpu_seconds'])
                    strict = (other['accuracy'] > point['accuracy'] or
                              other['actual_calls'] < point['actual_calls'] or
                              other['trajectory_cpu_seconds'] < point['trajectory_cpu_seconds'])
                    return weak and strict
                point['descriptive_frontier_only'] = not any(dominates(other) for other in group)
                points.append(point)
with (ROOT/'frontier.csv').open('w') as f:
    writer = csv.DictWriter(f, fieldnames=list(points[0]))
    writer.writeheader()
    writer.writerows(points)
assert len(points) == 280
assert sum(r['actual_calls'] for r in points if r['scope'] == 'pooled') == 69513
(ROOT/'frontier_audit.json').write_text(json.dumps({
    'input_sha256': hashlib.sha256(INPUT.read_bytes()).hexdigest(),
    'protocol_sha256': hashlib.sha256((ROOT/'frontier_protocol.json').read_bytes()).hexdigest(),
    'all_points': len(points), 'pooled_actual_calls': 69513,
    'ranking': 'REFUSED: descriptive frontier only; no equal actual-work experiment',
    'first_failed_run_total_cpu_wall': 'unknown', 'new_model_runs': 0}, indent=2)+'\n')
for p in points:
    if p['scope'] == 'pooled' and p['variant'] == 'normal':
        print(p)

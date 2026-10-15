#!/usr/bin/env python3
"""Research-only one-axis Cell scaling evidence audit; no model authority.

Consumes sealed, independently reviewed *candidate* measurement rows from the
existing Stem/Cell experiments. It does not run a pretrained model, authenticate
a model publisher, or certify a 10T/100T teacher equivalence. Never interpret a
SHA string or a producer-supplied 'physical' flag as independent attestation.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = 'hepta.stem-cell-one-axis-scale.v1'
ALLOWED_SCALES = (64, 256, 1024, 4096)
LEVELS = {
    'logical_cells': (64, 256, 1024, 4096),
    'active_cells': (1, 2, 4, 8),
    'reasoning_depth': (1, 2, 4, 8),
    'train_rows': (32, 64, 128, 256),
    'compute_budget_ns': (250000, 500000, 1000000, 2000000),
}
AXES = tuple(LEVELS)
REQUIRED = frozenset({
    'trial_id', 'arm', 'seed', 'source_sha256', 'held_label_sha256',
    'evaluator_sha256', 'stem_sha256', 'logical_cells', 'active_cells',
    'reasoning_depth', 'train_rows', 'compute_budget_ns', 'correct', 'total',
    'training_cpu_ns', 'inference_cpu_ns', 'encoder_forwards', 'peak_rss_bytes',
    'independent_source_groups', 'physical_work_observed', 'independent_score_receipt',
})


class ScalingDenied(ValueError):
    """Malformed, unpaired, cherry-picked, or authority-elevating evidence."""


def need(ok: bool, message: str) -> None:
    if not ok:
        raise ScalingDenied(message)


def digest(value: Any, field: str) -> None:
    need(type(value) is str and len(value) == 64 and value != '0' * 64 and
         all(c in '0123456789abcdef' for c in value), 'invalid ' + field)


def number(value: Any, field: str, *, positive: bool = False) -> None:
    need(type(value) is int and value >= (1 if positive else 0),
         'invalid nonnegative integer ' + field)


def validate_row(row: Any) -> None:
    need(type(row) is dict and set(row) == REQUIRED, 'scale row field mismatch')
    for field in ('source_sha256', 'held_label_sha256',
                  'evaluator_sha256', 'stem_sha256'):
        digest(row[field], field)
    need(type(row['trial_id']) is str and 1 <= len(row['trial_id']) <= 128,
         'invalid trial identity')
    need(row['arm'] in ('shared_sparse', 'shared_unsplit', 'replicated_421m',
                        'fixed_top1', 'adaptive_split', 'distilled_group'),
         'unregistered arm')
    for name in ('seed', 'logical_cells', 'active_cells', 'reasoning_depth',
                 'train_rows', 'compute_budget_ns', 'correct', 'total',
                 'training_cpu_ns', 'inference_cpu_ns', 'encoder_forwards',
                 'peak_rss_bytes', 'independent_source_groups'):
        number(row[name], name, positive=name not in ('correct', 'training_cpu_ns'))
    need(row['logical_cells'] in ALLOWED_SCALES and
         all(row[axis] in values for axis, values in LEVELS.items()) and
         row['active_cells'] <= row['logical_cells'] and
         row['correct'] <= row['total'], 'invalid scale or score')
    need(row['training_cpu_ns'] + row['inference_cpu_ns'] > 0 and
         row['independent_source_groups'] <= row['total'],
         'unphysical cost or source group count')
    need(row['physical_work_observed'] is True and
         row['independent_score_receipt'] is True,
         'original physical and independent numerical replay required')


def validate_series(bundle: Any) -> list[dict[str, Any]]:
    need(type(bundle) is dict and set(bundle) == {
        'schema', 'authority_posture', 'production_accepted',
        'teacher_equivalence_certified', 'rows'}, 'series field mismatch')
    need(bundle['schema'] == SCHEMA and bundle['authority_posture'] == 'DENY_ALL' and
         bundle['production_accepted'] is False and
         bundle['teacher_equivalence_certified'] is False,
         'authority/equivalence not allowed')
    rows = bundle['rows']
    need(type(rows) is list and 3 <= len(rows) <= 4096,
         'missing or unbounded candidate physical rows')
    seen = set()
    for row in rows:
        validate_row(row)
        need(row['trial_id'] not in seen, 'duplicate trial identity')
        seen.add(row['trial_id'])
    return rows


def one_axis_sweeps(bundle: Any) -> dict[str, Any]:
    rows = validate_series(bundle)
    # Exactly one of five resource axes is varied at a time. The registered
    # complete four-level design is mandatory; a subset from a changed source
    # cannot silently become a different experiment. Seeds stay separate.
    sweeps = []
    anchor = ('arm', 'seed', 'source_sha256', 'held_label_sha256',
              'evaluator_sha256', 'stem_sha256', 'independent_source_groups', 'total')
    for axis in AXES:
        other = tuple(x for x in AXES if x != axis)
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in rows:
            key = tuple(row[k] for k in anchor + other)
            groups.setdefault(key, []).append(row)
        for key, items in groups.items():
            series = sorted(items, key=lambda x: x[axis])
            levels = [r[axis] for r in series]
            need(len(levels) == len(set(levels)),
                 'duplicate axis level under identical fixed axes')
            if levels != list(LEVELS[axis]):
                continue
            # Fit on 3 smaller levels; score ONLY the preregistered 4th level.
            # The log-axis slope is descriptive, not a certified scaling law.
            xs = [math.log(float(r[axis])) for r in series[:-1]]
            ys = [r['correct'] / r['total'] for r in series[:-1]]
            mean_x = sum(xs) / len(xs)
            mean_y = sum(ys) / len(ys)
            den = sum((x - mean_x) ** 2 for x in xs)
            need(den > 0, 'underidentified scaling slope')
            slope = sum((x-mean_x)*(y-mean_y) for x,y in zip(xs,ys)) / den
            last = series[-1]
            prediction = mean_y + slope*(math.log(float(last[axis])) - mean_x)
            actual = last['correct']/last['total']
            sweeps.append({
                'swept_axis': axis, 'arm': key[0], 'seed': key[1],
                'source_sha256': key[2], 'levels': levels, 'held_level': levels[-1],
                'lower_scales_log_axis_slope': round(slope, 12),
                'held_level_prediction_unclipped': round(prediction, 12),
                'held_level_quality': round(actual, 12),
                'held_level_absolute_error': round(abs(prediction-actual), 12),
                'inference_cpu_ns': [r['inference_cpu_ns'] for r in series],
                'training_cpu_ns': [r['training_cpu_ns'] for r in series],
                'encoder_forwards': [r['encoder_forwards'] for r in series],
                'peak_rss_bytes': [r['peak_rss_bytes'] for r in series],
                'quality_denominator': last['total'],
                'distinct_source_groups_not_multiplied_by_seeds': key[6],
            })
    sweeps.sort(key=lambda x: (x['swept_axis'], x['arm'], x['seed']))
    return {
        'schema': 'hepta.stem-cell-scale-descriptive-review.v1',
        'observations': len(rows), 'matched_one_axis_sweeps': sweeps,
        'source_outcomes_authenticated_externally': False,
        'task_quality_winner_certified': False,
        'model_or_teacher_equivalence_certified': False,
        'can_extrapolate_to_unmeasured_10t_100t': False,
        'complete_cost_pareto_certified': False,
        'production_accepted': False, 'authority_posture': 'DENY_ALL',
    }


def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = {}
    for k, v in pairs:
        need(k not in out, 'duplicate JSON key')
        out[k] = v
    return out


def load(path: Path) -> Any:
    need(path.is_file() and not path.is_symlink() and
         path.stat().st_size <= 4*1024*1024, 'invalid bounded input file')
    return json.loads(path.read_bytes(), object_pairs_hook=reject_duplicate,
                      parse_constant=lambda x: (_ for _ in ()).throw(
                          ScalingDenied('nonfinite JSON literal: '+x)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink(),
         'create-only report destination required')
    report = one_axis_sweeps(load(args.input))
    args.output.write_text(json.dumps(report, sort_keys=True,
                      allow_nan=False, separators=(',', ':'))+'\n', encoding='utf-8')
    print('P5_RESEARCH_ONLY / DENY_ALL / NO_10T_100T_EQUIVALENCE',
          f"rows={report['observations']} sweeps={len(report['matched_one_axis_sweeps'])}")


if __name__ == '__main__':
    main()

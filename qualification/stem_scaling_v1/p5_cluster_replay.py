#!/usr/bin/env python3
"""P5 exact source-group arithmetic for observed Stem/Cell scaling panels.

Research-only *consumer* of external label-owning original source receipts.
No model executions or publisher signatures are supplied by this script.
Group pairing prevents a changed evaluation cohort from being sold as scale.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import scaling_frontier as base

SCHEMA = 'hepta.stem-scaling-original-group-outcomes.v1'
REQUIRED = {'trial_id', 'source_group_id', 'source_group_sha256',
            'correct', 'total', 'label_owner_scored'}


class ClusterDenied(ValueError):
    """Unpaired, altered, ambiguous, or self-promoting research evidence."""


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise ClusterDenied(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_digest(s: Any) -> bool:
    return type(s) is str and len(s) == 64 and s != '0'*64 and all(c in '0123456789abcdef' for c in s)


def parse(data: bytes) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out = {}
        for k, v in pairs:
            need(k not in out, 'duplicate JSON field')
            out[k] = v
        return out
    try:
        return json.loads(data, object_pairs_hook=unique_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(
                              ClusterDenied('nonfinite JSON: ' + x)))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClusterDenied('malformed JSON') from exc


def read(path: Path) -> tuple[bytes, Any]:
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 12_000_000,
         'missing or unbounded original source material')
    raw = path.read_bytes()
    return raw, parse(raw)


def emit_once(path: Path, report: Any) -> str:
    raw = (json.dumps(report, allow_nan=False, sort_keys=True,
                      separators=(',', ':')) + '\n').encode()
    need(not path.is_symlink(), 'unsafe output path')
    with path.open('xb') as writer:
        writer.write(raw)
    return sha(raw)


def exact_signflip(group_deltas: list[int]) -> float | None:
    """Descriptive randomization enumeration; NOT independence certification."""
    need(type(group_deltas) is list and
         all(type(x) is int for x in group_deltas), 'invalid cluster deltas')
    if not (2 <= len(group_deltas) <= 12):
        return None
    magnitude = abs(sum(group_deltas))
    variants = itertools.product((-1, 1), repeat=len(group_deltas))
    num = sum(abs(sum(s*d for s,d in zip(signs,group_deltas))) >= magnitude
              for signs in variants)
    return num / (2 ** len(group_deltas))


def replay(source: Any, raw_source: bytes, sidecar: Any) -> dict[str, Any]:
    # The 5-axis base is revalidated first; all old source and cost constraints stay.
    observations = base.validate_series(source)
    base_review = base.one_axis_sweeps(source)
    need(type(sidecar) is dict and set(sidecar) == {
         'schema', 'source_manifest_sha256', 'authority_posture',
         'model_or_teacher_equivalence_certified', 'production_accepted', 'rows'},
         'unregistered independent label-owner sidecar')
    need(sidecar['schema'] == SCHEMA and sidecar['source_manifest_sha256'] == sha(raw_source) and
         sidecar['authority_posture'] == 'DENY_ALL' and
         sidecar['model_or_teacher_equivalence_certified'] is False and
         sidecar['production_accepted'] is False,
         'source/authority provenance mismatch')
    group_rows = sidecar['rows']
    need(type(group_rows) is list and 1 <= len(group_rows) <= 250_000,
         'missing or oversized group ledger')
    trials = {r['trial_id']:r for r in observations}
    groups: dict[str, dict[str, dict[str, Any]]] = {trial:{} for trial in trials}
    for r in group_rows:
        need(type(r) is dict and set(r) == REQUIRED and
             type(r['trial_id']) is str and r['trial_id'] in groups and
             type(r['source_group_id']) is str and 1 <= len(r['source_group_id']) <= 200 and
             valid_digest(r['source_group_sha256']) and
             type(r['correct']) is int and type(r['total']) is int and
             r['total'] > 0 and 0 <= r['correct'] <= r['total'] and
             r['label_owner_scored'] is True,
             'invalid group outcome or unknown source trial')
        trial_group = groups[r['trial_id']]
        need(r['source_group_id'] not in trial_group, 'duplicated source group in one trial')
        trial_group[r['source_group_id']] = r
    for trial_id, trial in trials.items():
        rows = groups[trial_id]
        need(len(rows) == trial['independent_source_groups'] and
             len(rows) == len({r['source_group_sha256'] for r in rows.values()}) and
             sum(x['total'] for x in rows.values()) == trial['total'] and
             sum(x['correct'] for x in rows.values()) == trial['correct'],
             'group/candidate counts or source hashes do not reproduce original')
    reviews = []
    axis_groups = {}
    anchor = ('arm', 'seed', 'source_sha256', 'held_label_sha256',
              'evaluator_sha256', 'stem_sha256', 'independent_source_groups', 'total')
    for axis in base.AXES:
        fixed = tuple(x for x in base.AXES if x != axis)
        for trial in observations:
            key = tuple(trial[k] for k in anchor + fixed)
            axis_groups.setdefault((axis, key), []).append(trial)
    for (axis, key), items in sorted(axis_groups.items(), key=lambda kv: str(kv[0])):
        ordered = sorted(items, key=lambda row: row[axis])
        values = [r[axis] for r in ordered]
        need(len(values) == len(set(values)), 'duplicate scale level in a fixed source panel')
        if values != list(base.LEVELS[axis]):
            continue
        same_group_ids = set(groups[ordered[0]['trial_id']])
        original = groups[ordered[0]['trial_id']]
        for row in ordered[1:]:
            counterpart = groups[row['trial_id']]
            need(set(counterpart) == same_group_ids and all(
                 original[group]['source_group_sha256'] == counterpart[group]['source_group_sha256'] and
                 original[group]['total'] == counterpart[group]['total']
                 for group in same_group_ids),
                 'held question/source group or denominator changed between scale levels')
        low = groups[ordered[-2]['trial_id']]
        high = groups[ordered[-1]['trial_id']]
        deltas = [high[k]['correct'] - low[k]['correct'] for k in sorted(same_group_ids)]
        held_improvement = sum(deltas)/ordered[-1]['total']
        reviews.append({
            'axis': axis, 'arm': key[0], 'seed': key[1],
            'scale_levels': values, 'paired_independent_groups_declared': len(deltas),
            'paired_group_correct_deltas': deltas,
            'held_quality_difference': round(held_improvement, 12),
            'exact_group_signflip_p_descriptive_only': exact_signflip(deltas),
            'independent_group_sampling_proven': False,
            'new_held_source_families_proven': False,
            'statistical_gain_claim_admitted': False,
            'equivalence_claim_admitted': False,
        })
    need(len(reviews) == len(base_review['matched_one_axis_sweeps']),
         'not all original scaling comparisons survived independent source matching')
    need(len(reviews) > 0, 'missing complete four-level original-source-paired scaling experiment')
    return {
        'schema': 'hepta.stem-scaling-group-paired-review.v1',
        'original_input_sha256': sha(raw_source),
        'original_trials_accounted': len(trials),
        'registered_complete_sweeps': len(reviews),
        'paired_sweep_reviews': reviews,
        'outcome_receipts_independently_authenticated': False,
        'independent_cluster_sampling_established': False,
        'new_real_pretrained_forward_executed': False,
        'teacher_or_10t_100t_equivalence_established': False,
        'production_accepted': False, 'authority_posture': 'DENY_ALL',
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--held-group-outputs', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    raw, original = read(args.original)
    _, group_outcomes = read(args.held_group_outputs)
    result = replay(original, raw, group_outcomes)
    print(emit_once(args.output, result))


if __name__ == '__main__':
    main()

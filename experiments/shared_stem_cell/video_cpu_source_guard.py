"""Exploratory source-wise conservative gating for the existing video FIFO grid.

Uses ONLY already-recorded calibration CPU proxy runs, before holdout output.
No trained selector, production scheduler, IID/statistical retention guarantee,
or external traffic. Per-source tails share one queue and are NOT independent.
"""
from __future__ import annotations

import math
import statistics

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import video_cpu_queue as queue

MIN_SOURCES = 2
MIN_CELLS_PER_SOURCE = 4
MAX_SOURCE_P95_RATIO = 1.05
MAX_ROUND_FIRST_RATIO = 1.5
MAX_ROUND_WALL_RATIO = 1.1
MAX_ROUND_P95_RATIO = .95


def source_p95(records):
    groups = {}
    if not isinstance(records, list) or not records:
        raise e.InputError('source-labeled calibration records required')
    for r in records:
        if (not isinstance(r, dict) or not isinstance(r.get('source_id'), str)
                or len(r['source_id']) != 64 or type(r.get('response_latency_ns')) is not int
                or r['response_latency_ns'] < 0):
            raise e.InputError('bounded source latency records required')
        groups.setdefault(r['source_id'], []).append(r['response_latency_ns'])
    return {key: queue.percentile(vals, 95) for key, vals in sorted(groups.items())}


def choose(calibrated):
    """Require stability in EVERY paired round and source; else scalar.

    This is a predeclared empirical safety filter. It does not certify an
    unseen population or claim that 2 sources suffice for tail-risk bounds.
    """
    options = [queue.policy_key(p) for p in queue.POLICIES]
    if (not isinstance(calibrated, dict) or set(calibrated) != set(options)
            or not 2 <= len(calibrated[options[0]]) <= 7):
        raise e.InputError('complete fixed-grid calibration runs required')
    rounds = len(calibrated[options[0]])
    first = calibrated[options[0]][0]
    ordered_ids = first['case_ids']
    baseline_source_ids = [r['source_id'] for r in first['records']]
    if (not isinstance(ordered_ids, list) or len(ordered_ids) != len(baseline_source_ids)
            or len(set(ordered_ids)) != len(ordered_ids)
            or not 1 <= len(ordered_ids) <= 16):
        raise e.InputError('bounded complete source/case calibration cohort')
    source_count = len(set(baseline_source_ids))
    per_source_count = {s: baseline_source_ids.count(s) for s in sorted(set(baseline_source_ids))}
    sufficient = source_count >= MIN_SOURCES and all(n >= MIN_CELLS_PER_SOURCE for n in per_source_count.values())
    matrix = {}
    qualified = []
    for name in options:
        runs = calibrated[name]
        if not isinstance(runs, list) or len(runs) != rounds:
            raise e.InputError('all matched calibration rounds required')
        by_round = []
        for index, trial in enumerate(runs):
            baseline = calibrated[options[0]][index]
            if (not isinstance(trial, dict) or not isinstance(baseline, dict)
                    or trial.get('iteration') != baseline.get('iteration')
                    or trial.get('case_ids') != ordered_ids or baseline.get('case_ids') != ordered_ids
                    or trial.get('arrival_offsets_ns') != baseline.get('arrival_offsets_ns')
                    or trial.get('policy_key') != name
                    or trial.get('depth') != baseline.get('depth')
                    or trial.get('gap_ns') != baseline.get('gap_ns')
                    or [r['source_id'] for r in trial['records']] != baseline_source_ids
                    or [r['case_id'] for r in trial['records']] != ordered_ids
                    or [r['case_id'] for r in baseline['records']] != ordered_ids):
                raise e.InputError('unmatched calibration arm, source or arrival order')
            for k in ('latency_p95_ns', 'first_response_ns', 'whole_run_wall_ns'):
                if (type(trial.get(k)) is not int or trial[k] <= 0
                        or type(baseline.get(k)) is not int or baseline[k] <= 0):
                    raise e.InputError('positive exact calibration clocks required')
            per_source = source_p95(trial['records'])
            base_source = source_p95(baseline['records'])
            if set(per_source) != set(base_source):
                raise e.InputError('source stratification mismatch')
            improvement = trial['latency_p95_ns'] / baseline['latency_p95_ns']
            first_ratio = trial['first_response_ns'] / baseline['first_response_ns']
            wall_ratio = trial['whole_run_wall_ns'] / baseline['whole_run_wall_ns']
            source_ratios = {s: per_source[s] / max(base_source[s], 1) for s in per_source}
            by_round.append({'iteration':index, 'p95_ratio':improvement,
                'first_response_ratio':first_ratio, 'whole_wall_ratio':wall_ratio,
                'source_p95_ratios':source_ratios,
                'passes': bool(improvement <= MAX_ROUND_P95_RATIO
                    and first_ratio <= MAX_ROUND_FIRST_RATIO
                    and wall_ratio <= MAX_ROUND_WALL_RATIO
                    and all(math.isfinite(r) and r <= MAX_SOURCE_P95_RATIO for r in source_ratios.values()))})
        median_ns = int(statistics.median([trial['latency_p95_ns'] for trial in runs]))
        valid = name != options[0] and sufficient and all(r['passes'] for r in by_round)
        matrix[name] = {'paired_rounds': by_round, 'median_p95_ns': median_ns,
            'eligible': valid,
            'reason': ('baseline' if name == options[0] else
                'insufficient_source_groups' if not sufficient else
                'some_paired_round_or_source_failed' if not valid else 'all_guards_pass')}
        if valid:
            qualified.append(name)
    chosen = min(qualified, key=lambda k: (matrix[k]['median_p95_ns'],options.index(k))) if qualified else options[0]
    return {'schema':'hepta.video-arrival-source-guard.v1',
        'selected_policy_key':chosen, 'qualified':qualified,
        'source_groups':per_source_count,'calibration_rounds':rounds,
        'comparison':matrix,'minimum_distinct_sources':MIN_SOURCES,
        'minimum_cells_per_source':MIN_CELLS_PER_SOURCE,
        'max_source_p95_ratio':MAX_SOURCE_P95_RATIO,
        'max_round_p95_ratio':MAX_ROUND_P95_RATIO,
        'max_round_first_response_ratio':MAX_ROUND_FIRST_RATIO,
        'max_round_wall_ratio':MAX_ROUND_WALL_RATIO,
        'all_guards_are_calibration_only':True,
        'empirical_guard_not_population_certificate':True,
        'same_queue_sources_not_independent':True,
        'uses_previously_exposed_public_source_family':True,
        'production_accepted':False}

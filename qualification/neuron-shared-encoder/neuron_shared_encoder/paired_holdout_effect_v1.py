"""Case-paired retrospective quality diagnostics for independently replayed Cell Heads.

No training, future-outcome claims, model selection, authority, or raw text is
read or written here. Original source case (NOT case x seed) is the resampling
unit. The original AG News partitions do not establish source independence.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

SCHEMA = 'hepta.neuron.paired-original-case-retrospective.v1'
METRICS = ('accuracy', 'brier', 'nll')
EXPECTED_CELLS = (0, 1)
EXPECTED_CASES_PER_CELL = 16
MAX_ROWS = 32 * 3


def _metrics(logits: list[float], label: int) -> tuple[float, float, float]:
    if (not isinstance(logits, list) or len(logits) != 4
            or any(type(v) not in (float, int) or not math.isfinite(v)
                   for v in logits)):
        raise ValueError('four finite classification logits required')
    z = np.asarray(logits, dtype=np.float64)
    shifted = z - z.max()
    e = np.exp(shifted)
    p = e / e.sum()
    truth = np.zeros(4, dtype=np.float64)
    truth[label] = 1
    return (float(int(z.argmax() == label)),
            float(np.square(p - truth).sum()),
            float(-math.log(max(float(p[label]), 1e-300))))


def paired_original_case_effect_v1(rows: list[dict[str, Any]], *,
                                   repeats: int = 2000,
                                   bootstrap_seed: int = 20261014) -> dict[str, Any]:
    """Descriptive, stratified original-case bootstrap of paired Head scores.

    Each case's complete repeated training-seed trajectory stays intact. No
    seed is ever counted as an independent case, and no classification winner
    is selected, even when an interval excludes zero.
    """
    if (type(repeats) is not int or not 1000 <= repeats <= 5000
            or type(bootstrap_seed) is not int or not 0 <= bootstrap_seed < 2**32
            or not isinstance(rows, list) or not 32 <= len(rows) <= MAX_ROWS):
        raise ValueError('bounded matched original-case observation panel required')
    keys = {'seed', 'cell', 'case_id', 'source_group', 'label',
            'pooled_logits', 'token_logits'}
    observations: dict[tuple[int, str], dict[int, np.ndarray]] = {}
    metadata: dict[tuple[int, str], tuple[str, int]] = {}
    unique_groups: dict[str, tuple[int, str]] = {}
    all_seeds: set[int] = set()
    newly_correct = 0
    newly_incorrect = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError('complete fixed-schema matched case data required')
        cell, seed, label = row['cell'], row['seed'], row['label']
        case_id, group = row['case_id'], row['source_group']
        if (type(cell) is not int or cell not in EXPECTED_CELLS
                or type(seed) is not int or not 0 <= seed < 2**31
                or type(label) is not int or not 0 <= label < 4
                or not isinstance(case_id, str) or not 0 < len(case_id) <= 128
                or not isinstance(group, str) or not 0 < len(group) <= 128):
            raise ValueError('invalid independent case/scope/label identity')
        key = (cell, case_id)
        earlier = unique_groups.setdefault(group, key)
        if earlier != key:
            raise ValueError('reused source group across original cases')
        ident = (group, label)
        if metadata.setdefault(key, ident) != ident:
            raise ValueError('case group or label changed between seeds')
        if seed in observations.setdefault(key, {}):
            raise ValueError('duplicate case x training seed observation')
        left = _metrics(row['pooled_logits'], label)
        right = _metrics(row['token_logits'], label)
        delta = np.asarray([b - a for a, b in zip(left, right)], dtype=np.float64)
        observations[key][seed] = delta
        newly_correct += int(left[0] == 0 and right[0] == 1)
        newly_incorrect += int(left[0] == 1 and right[0] == 0)
        all_seeds.add(seed)

    sorted_seeds = sorted(all_seeds)
    if not 1 <= len(sorted_seeds) <= 3:
        raise ValueError('unsupported seed replication count')
    cases = {cell: sorted((key for key in observations if key[0] == cell),
                          key=lambda key: key[1]) for cell in EXPECTED_CELLS}
    if (any(len(cases[cell]) != EXPECTED_CASES_PER_CELL for cell in EXPECTED_CELLS)
            or len(rows) != 32 * len(sorted_seeds)
            or any(set(observations[key]) != all_seeds for key in observations)):
        raise ValueError('incomplete 32-case matched and seed-complete panel')
    # Crucially, aggregate seed trajectories within each ORIGINAL case before
    # any case-level bootstrap draw. Both Cell partitions remain represented.
    deltas = {
        cell: np.stack([np.stack([observations[key][seed]
                                   for seed in sorted_seeds]).mean(axis=0)
                         for key in cases[cell]])
        for cell in EXPECTED_CELLS
    }
    overall = np.concatenate([deltas[cell] for cell in EXPECTED_CELLS], axis=0)
    rng = np.random.default_rng(bootstrap_seed)
    distributions = np.empty((repeats, len(METRICS)), dtype=np.float64)
    for j in range(repeats):
        # Paired resampling and equal original case weighting, with two Cells
        # held at their fixed original 16/16 composition.
        sampled = [deltas[cell][rng.integers(0, EXPECTED_CASES_PER_CELL,
                                            size=EXPECTED_CASES_PER_CELL)]
                   for cell in EXPECTED_CELLS]
        distributions[j] = np.concatenate(sampled).mean(axis=0)

    per_cell = [
        {'cell': cell, 'original_cases': EXPECTED_CASES_PER_CELL,
         'token_minus_pooled': {metric: float(deltas[cell][:, i].mean())
                                for i, metric in enumerate(METRICS)}}
        for cell in EXPECTED_CELLS
    ]
    return {
        'schema': SCHEMA,
        'evidence_class': 'RETROSPECTIVE_INDEPENDENT_NUMERIC_REPLAY_DESCRIPTIVE_ONLY',
        'original_holdout_cases': len(overall),
        'original_holdout_cases_per_cell': EXPECTED_CASES_PER_CELL,
        'repeated_train_seeds': sorted_seeds,
        'number_of_actual_case_seed_comparisons': len(rows),
        'paired_token_minus_pooled': {
            metric: {
                'point_estimate': float(overall[:, i].mean()),
                'original_case_stratified_bootstrap_95_descriptive': [
                    float(np.quantile(distributions[:, i], .025)),
                    float(np.quantile(distributions[:, i], .975))],
            } for i, metric in enumerate(METRICS)},
        'per_cell': per_cell,
        'repeated_seed_newly_correct_count': newly_correct,
        'repeated_seed_newly_incorrect_count': newly_incorrect,
        'case_bootstrap_repeats': repeats,
        'case_bootstrap_seed': bootstrap_seed,
        'higher_accuracy_better': True,
        'lower_brier_nll_better': True,
        'case_source_independence_verified': False,
        'three_training_seeds_are_not_independent_cases': True,
        'real_deployed_nochange_verified': False,
        'prospective_future_outcome_verified': False,
        'independent_signed_NDU_verified': False,
        'model_winner_selected': False,
        'selection_authorized': False,
        'production_admission': 'BLOCKED',
        'warning': ('Intervals are retrospective, source-family independence is unverified, '
                    'and seeded training replicates do not increase original case n=32. '
                    'No prospective causal or production inference follows.'),
    }

"""Summarise fixed-gallery outcomes after both independently trained panels lock."""
import argparse
import json
from pathlib import Path

import numpy as np


SEEDS = (109, 271, 463)
BUDGETS = (120, 600, 1800, 3600, 7200)
METHODS = ('hybrid', 'literal', 'smooth', 'linear', 'conventional')
CONTRASTS = (
    ('hybrid', 'conventional'), ('hybrid', 'literal'),
    ('hybrid', 'linear'), ('literal', 'conventional'),
)


def mean_hits(rankings, cutoff):
    """One observation per gallery pair, averaged over both directions and seeds."""
    return np.mean([(ranks[:, :, 0] <= cutoff).mean(axis=0) for ranks in rankings], axis=0)


def paired_interval(differences):
    rng = np.random.default_rng(220711)
    count = len(differences)
    replicates = [differences[rng.integers(count, size=(100, count))].mean(axis=1) for _ in range(80)]
    return np.quantile(np.concatenate(replicates), [.025, .975]).tolist()


def main(data):
    long_dir = data / 'long'
    hybrid_dir = data / 'hybrid_long'
    result = {}
    with np.load(long_dir / 'cold_ranks.npz') as conventional:
        for budget in BUDGETS:
            with np.load(hybrid_dir / f'cold-{budget}.npz') as warm:
                ranks = {
                    method: [warm[str(seed)] if method == 'hybrid' else conventional[f'{method}/{seed}/{budget}'] for seed in SEEDS]
                    for method in METHODS
                }
                scores = {method: mean_hits(rows, 1) for method, rows in ranks.items()}
                record = {f'r{cutoff}': {name: float(mean_hits(rows, cutoff).mean()) for name, rows in ranks.items()} for cutoff in (1, 5, 10)}
                record['contrasts'] = {}
                for candidate, baseline in CONTRASTS:
                    difference = scores[candidate] - scores[baseline]
                    record['contrasts'][f'{candidate}-{baseline}'] = {
                        'strict_R1_difference': float(difference.mean()),
                        'paired95': paired_interval(difference),
                    }
                result[str(budget)] = record
    (data/'time_matched_long_comparison.json').write_text(json.dumps(result, indent=1))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('data', type=Path)
    main(parser.parse_args().data)

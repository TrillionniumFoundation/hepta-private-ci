"""Aggregate the frozen 12 x 5 experiment without changing or selecting models.

The primary reference baseline is chosen on mean validation set loss only.
Bootstrap intervals are descriptive crossed seed/episode resampling intervals;
five training seeds and this synthetic task do not establish external validity.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import numpy as np

ROOT = Path(__file__).resolve().parent
SEEDS = (101, 211, 307, 401, 503)
VARIANTS = (
    'lif', 'alif', 'resource_lif', 'fp_no_maturity', 'fp_multi_fixed',
    'rr_full', 'ctrnn', 'ctrnn_budget', 'rr_no_rollover',
    'rr_collapse_maturity', 'rr_shuffle_maturity', 'rr_frozen_resource',
)
BASELINES = ('lif', 'alif', 'resource_lif', 'fp_no_maturity',
             'fp_multi_fixed', 'ctrnn', 'ctrnn_budget')
EVALUATIONS = ('test_expected', 'test_hard', 'future_expected', 'future_hard')


def stats(values):
    a = np.asarray(values, dtype=float)
    return {'mean': float(a.mean()), 'seed_sd': float(a.std(ddof=1)),
            'values': a.tolist()}


def compare(a, b, rng_seed=81001, draws=4000):
    delta = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    seeds, episodes = delta.shape
    rng = np.random.default_rng(rng_seed)
    # Crossing both sampling axes preserves pairing between models. These are
    # not 1920 independent training replications.
    seed_counts = rng.multinomial(seeds, np.ones(seeds)/seeds, size=draws)
    episode_counts = rng.multinomial(episodes, np.ones(episodes)/episodes, size=draws)
    sampled = ((seed_counts @ delta) * episode_counts).sum(axis=1)/(seeds*episodes)
    means = delta.mean(axis=1)
    return {
        'mean_delta': float(delta.mean()),
        'seed_sd_of_mean_delta': float(means.std(ddof=1)),
        'per_seed_mean_delta': means.tolist(),
        'crossed_seed_episode_bootstrap_95_interval': np.quantile(sampled, [.025, .975]).tolist(),
        'negative_transfer_seed_episode_fraction': float((delta < -1e-9).mean()),
        'positive_transfer_seed_episode_fraction': float((delta > 1e-9).mean()),
        'tie_seed_episode_fraction': float((np.abs(delta) <= 1e-9).mean()),
        'negative_transfer_episode_fraction_after_seed_average': float((delta.mean(axis=0) < -1e-9).mean()),
        'bootstrap_draws': draws, 'bootstrap_seed': rng_seed,
        'interpretation': 'Descriptive paired crossed bootstrap; 5 training seeds, same 384 episodes; no multiplicity adjustment.',
    }


def main():
    all_results = {}
    for variant in VARIANTS:
        all_results[variant] = []
        for seed in SEEDS:
            p = ROOT/'results'/variant/f'seed_{seed}'/'result.json'
            d = json.loads(p.read_text())
            assert d['variant'] == variant and d['seed'] == seed
            assert d['training_updates'] == 512
            assert d['source_sha256'] == hashlib.sha256((ROOT/'train_compare.py').read_bytes()).hexdigest()
            assert d['checkpoint_sha256'] == hashlib.sha256(p.with_name('model.pt').read_bytes()).hexdigest()
            all_results[variant].append(d)
    freeze = json.loads((ROOT/'results/source_freeze.json').read_text())
    freeze_checks = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == sha
                     for name, sha in freeze.items()}
    assert all(freeze_checks.values()), 'Frozen source changed'

    rows = []
    for variant, records in all_results.items():
        accounting = records[0]['metadata']['accounting']
        row = {
            'variant': variant,
            'parameters': records[0]['metadata']['total_trainable_parameters'],
            'active_state_bytes_per_sequence': accounting['active_state_bytes_per_sequence'],
            'state_exclusions': accounting['excludes'],
            'validation_nll': stats([d['best_validation_loss'] for d in records]),
            'best_epochs': [d['best_epoch'] for d in records],
            'training_seconds': stats([d['train_seconds'] for d in records]),
            'peak_process_rss_mib_training_and_evaluation': stats([d['process_peak_rss_mib'] for d in records]),
            'process_peak_rss_scope': 'Process high-water mark after imports, training, validation and all closed-loop evaluations; not training-only RSS.',
            'training_updates_per_seed': 512,
            'evaluation': {},
        }
        for name in EVALUATIONS:
            evaluations = [d['evaluation'][name] for d in records]
            reference_oracle = evaluations[0]['episode_oracle']
            assert all(e['episode_oracle'] == reference_oracle for e in evaluations)
            assert all(e['budget_violations'] == 0 and e['ledger_conservation'] for e in evaluations)
            summary = {}
            for metric in ('normalized_utility_mean', 'utility_mean', 'regret_mean',
                           'retained_value_mean', 'budget_spent_mean',
                           'renewal_count_mean', 'emission_count_mean', 'dropped_count_mean',
                           'internal_events_mean', 'policy_optimal_set_accuracy',
                           'policy_optimal_set_nll', 'policy_ece_10_bins'):
                summary[metric] = stats([e[metric] for e in evaluations])
            positive_oracle = np.asarray(reference_oracle) > 1e-12
            summary['normalized_utility_excluding_zero_oracle'] = stats([
                np.asarray(e['episode_normalized_utility'])[positive_oracle].mean()
                for e in evaluations])
            summary['episode_count'] = evaluations[0]['episodes']
            summary['zero_oracle_episodes'] = evaluations[0]['zero_oracle_episodes']
            summary['oracle_mean'] = evaluations[0]['oracle_mean']
            summary['budget_violations'] = 0
            summary['ledger_conservation_all'] = True
            row['evaluation'][name] = summary
        rows.append(row)

    selected = min(BASELINES, key=lambda v: np.mean([d['best_validation_loss'] for d in all_results[v]]))
    comparisons = {}
    rr = all_results['rr_full']
    for variant in VARIANTS:
        if variant == 'rr_full':
            continue
        comparisons[variant] = {}
        for name in EVALUATIONS:
            normalized_a = [d['evaluation'][name]['episode_normalized_utility'] for d in rr]
            normalized_b = [d['evaluation'][name]['episode_normalized_utility'] for d in all_results[variant]]
            raw_a = [d['evaluation'][name]['episode_utility'] for d in rr]
            raw_b = [d['evaluation'][name]['episode_utility'] for d in all_results[variant]]
            comparisons[variant][name] = {
                'normalized_utility_RR_minus_comparator': compare(normalized_a, normalized_b),
                'raw_utility_RR_minus_comparator': compare(raw_a, raw_b),
            }
    report = {
        'schema': 'rrsnn.frozen-matrix-summary.v1',
        'seeds': list(SEEDS), 'models': len(VARIANTS), 'completed_runs': len(VARIANTS)*len(SEEDS),
        'source_freeze_checks': freeze_checks,
        'scope': 'Synthetic planning task with observation-grid neural proxies; expected-mode training, separate hard proxy replay.',
        'selected_reference_baseline': selected,
        'reference_selection': 'Lowest mean validation oracle-set NLL among seven baselines; no held-out utility used.',
        'rows': rows,
        'RR_minus_comparators': comparisons,
        'limits': [
            'Independent synthetic distribution-shift holdout is not a real future window.',
            'All models see the same 22 observations and common feasibility mask.',
            'Identical parameter count for standard models; joint-budget CTRNN has 1984 vs 2001 parameters and 384 state bytes.',
            'A common 388-byte active-state ceiling does not mean equal actual memory usage or equal temporary allocations.',
            '512 Adam updates, identical data and validation selection are matched; FLOPs and wall time are not matched.',
            'Five training seeds; bootstrap intervals are descriptive, no multiple-comparison correction.',
            'Zero-oracle episodes are assigned normalized utility 1 and separately reported.',
            'No overdrafts follows from the shared legal-action mask, not from a learned RR property.',
            'Policy-confidence ECE is not first-passage calibration.',
            'Hard replay is not the exact continuous-time event engine.',
            'Fixed-boundary RR equals fp_multi_fixed and is not an independent trained model.',
        ],
    }
    destination = ROOT/'results/aggregate.json'
    destination.write_text(json.dumps(report, indent=2)+'\n')
    lines = ['RR-SNN frozen matrix: 12 models x 5 seeds', f'Validation-selected reference: {selected}',
             'model | params | state B | val NLL | test expected | shift expected | shift hard | train seconds']
    for row in rows:
        columns = [row['variant'], str(row['parameters']), str(row['active_state_bytes_per_sequence'])]
        for s in (row['validation_nll'],
                  row['evaluation']['test_expected']['normalized_utility_mean'],
                  row['evaluation']['future_expected']['normalized_utility_mean'],
                  row['evaluation']['future_hard']['normalized_utility_mean'],
                  row['training_seconds']):
            columns.append(f"{s['mean']:.5f} +/- {s['seed_sd']:.5f}")
        lines.append(' | '.join(columns))
    for name in EVALUATIONS:
        c = comparisons[selected][name]['normalized_utility_RR_minus_comparator']
        lines.append(f'RR - {selected} {name}: '+json.dumps(c))
    (ROOT/'results/aggregate.txt').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()

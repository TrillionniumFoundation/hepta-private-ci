"""Deterministic fixtures for grouping, pairing and fail-closed analysis behavior."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis import analyze_run, hierarchical_bootstrap, point_metrics, world_metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    config = json.loads((ROOT / 'protocol.json').read_text())
    config.update({'development': True, 'heldout_worlds': {'iid': 20}, 'validation_worlds': 20})
    config['primary']['paired_hierarchical_bootstrap_replicates'] = 100
    draws, n = 4, 20
    primary_name = f"{config['primary']['arm']}__n{config['primary_steps']}"
    baseline_name = 'free_trained__free_joint__n8'
    arrays = {'factual_loss': np.tile([0., 0., 0., 4.], n),
              'lawful_consistent': np.ones(n*draws), 'correct_resolved': np.ones(n*draws),
              'style_positive': np.tile([0., 0., 1., 1.], n),
              'world_index': np.repeat(np.arange(n), draws), 'draw_index': np.tile(np.arange(draws), n)}
    baseline = {k: v.copy() for k, v in arrays.items()}
    baseline['factual_loss'] = np.full(n*draws, 1.2)
    with tempfile.TemporaryDirectory(prefix='ndu-analysis-fixture-') as tmp:
        output = Path(tmp)
        for seed in config['seeds']:
            folder = output / 'seeds' / str(seed)
            folder.mkdir(parents=True)
            selection = {'fairness_gate': True, 'cpu_seconds_cap': .11,
                         'choice': {'name': baseline_name, 'arm': 'free_joint'},
                         'eligible_names': [baseline_name], 'same_actuator_eligible_names': [baseline_name]}
            (folder/'selection.json').write_text(json.dumps(selection))
            reports = []
            facts = np.zeros((n, 6), dtype=np.float32)
            facts_hash = hashlib.sha256(facts.tobytes()).hexdigest()
            np.savez_compressed(folder/'iid__worlds.npz', facts=facts)
            for name, values, seconds in ((primary_name, arrays, .1), (baseline_name, baseline, .08)):
                np.savez_compressed(folder/f'iid__{name}.npz', **values)
                report = {'scenario': 'iid', 'choice': {'name': name, 'arm': 'free_joint' if name == baseline_name else 'ndu'}, 'cpu_seconds_per_world': seconds,
                          'facts_sha256': facts_hash, 'noise_sha256': 'f'*64,
                          'world_seed': config['split_seed_offsets']['test'] + seed,
                          'seconds_per_world': seconds, **point_metrics(world_metrics(values, draws))}
                reports.append(report)
            (folder/'evaluation.json').write_text(json.dumps(reports))
            np.savez_compressed(folder/'validation__primary.npz', **arrays)
            np.savez_compressed(folder/f'validation__{baseline_name}.npz', **baseline)
            (folder/'validation.json').write_text(json.dumps({'primary': reports[0], 'candidates': [reports[1]]}))
            training = {'continuation_updates': {'ndu_trained': config['continued_updates'],
                                                'free_equal_updates': config['continued_updates'], 'free_trained': 200},
                        'continuation_seconds': {'ndu_trained': 2., 'free_equal_updates': .3, 'free_trained': 2.01},
                        'free_to_ndu_training_time_ratio': 1.005}
            (folder/'training.json').write_text(json.dumps(training))
        good = analyze_run(output, config)
        pairs = [(world_metrics(arrays, draws), world_metrics(baseline, draws))] * len(config['seeds'])
        constant = hierarchical_bootstrap(pairs, 100)
        identical = hierarchical_bootstrap([(a, a) for a, _ in pairs], 100)
        zero = copy.deepcopy(arrays)
        zero['lawful_consistent'] *= 0
        zero_entropy = world_metrics(zero, draws)['lawful_entropy']
        # Tamper only the evidence indices; it must invalidate pairing, not improve the result.
        folder = output/'seeds'/str(config['seeds'][0])
        bad = copy.deepcopy(arrays)
        bad['draw_index'] = bad['draw_index'][::-1]
        np.savez_compressed(folder/f'iid__{primary_name}.npz', **bad)
        unpaired = analyze_run(output, config)
        # Restore indices, tamper a reported statistic: raw recomputation must detect it.
        np.savez_compressed(folder/f'iid__{primary_name}.npz', **arrays)
        reports = json.loads((folder/'evaluation.json').read_text())
        reports[0]['world_cvar90'] = 0.
        (folder/'evaluation.json').write_text(json.dumps(reports))
        mismatch = analyze_run(output, config)
    gates = {
        'world_means_not_draw_tails': abs(good['primary']['ndu']['world_cvar90'] - 1.) < 1e-12,
        'paired_CVaR_translation': np.allclose(constant['cvar90_delta_ci'], [-.2, -.2], atol=1e-12),
        'identical_pairs_zero_CI': identical['cvar90_delta_ci'] == [0., 0.],
        'lawful_balanced_styles_entropy_one': abs(good['primary']['ndu']['conditional_lawful_style_entropy']-1.) < 1e-12,
        'invalid_styles_entropy_zero': np.array_equal(zero_entropy, np.zeros(n)),
        'development_cannot_claim_scientific_success': not good['scientific_superiority_gate_passed'],
        'reordered_draw_indices_fail_pairing': not unpaired['gates']['world_draw_pairing_indices_verified'],
        'tampered_report_detected': not mismatch['gates']['heldout_metrics_match_raw_evidence'],
    }
    result = {'schema': 'ndu-analysis-fixture-audit-v1', 'scope': 'deterministic artificial fixtures, never heldout evidence',
              'gates': gates, 'all_passed': all(gates.values()),
              'fixture_primary_delta': good['primary']['cvar90_delta'],
              'fixture_CI': constant['cvar90_delta_ci'],
              'fixture_gates': good['gates'],
              'analysis_sha256': hashlib.sha256((ROOT/'analysis.py').read_bytes()).hexdigest(),
              'audit_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not all(gates.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

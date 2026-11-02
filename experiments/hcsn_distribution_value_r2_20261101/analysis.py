"""Predeclared paired-context summaries; same-law comparison is retained."""
import json
from pathlib import Path

import numpy as np

from . import model

NAMES = ('A_ordinary_light', 'B_ordinary_value', 'C_analytic_light', 'D_analytic_value', 'joint_train_factor_execute', 'factor_train_joint_execute', 'factor_train_factor_execute', 'joint_train_mean_execute')


def contrast(utility, left, right, protocol, cues=None):
    difference = utility[..., left, :] - utility[..., right, :]
    if cues is not None:
        difference = difference[:, :, cues]
    by_context = difference.mean(axis=(0, 2, 3, 4))
    by_fit = difference.mean(axis=(1, 2, 3, 4))
    rng = np.random.default_rng(protocol['bootstrap']['seed'])
    draws = [by_context[rng.integers(len(by_context), size=len(by_context))].mean() for _ in range(protocol['bootstrap']['draws'])]
    interval = np.quantile(draws, [.025, .975]).tolist()
    return dict(mean=float(difference.mean()), per_fit=by_fit.tolist(), per_context=by_context.tolist(), conditional_context_interval=interval,
                strictly_positive_gate=bool((by_fit > 0).all() and interval[0] > 0))


def analyze(out):
    protocol = json.loads((out / 'PROTOCOL.json').read_text())
    candidates = json.loads((out / 'ALL_CANDIDATES.json').read_text())
    shape = (3, protocol['test_contexts'], protocol['cue_count'], 4, 8, protocol['episodes_per_cell'])
    utility, accuracy = np.zeros(shape), np.zeros(shape)
    action_difference = 0; engine_action_differences = 0; action_counts = np.zeros((8, 5), dtype=np.int64)
    for si, fit in enumerate(candidates['fits']):
        for ci in range(protocol['test_contexts']):
            for cue in range(protocol['cue_count']):
                for price in range(4):
                    path = out / 'confirmation' / f"fit{fit['seed']}_context{ci}_cue{cue}_price{price}.npz"
                    with np.load(path, allow_pickle=False) as raw:
                        utility[si, ci, cue, price] = raw['utility']; accuracy[si, ci, cue, price] = raw['correct']
                        assert np.array_equal(raw['target'], np.repeat(raw['target'][:1], 8, axis=0))
                        engine_action_differences += int(np.any(raw['actions'][1] != raw['actions'][3], axis=1).sum())
                        if cue in (2, 3):
                            action_difference += int(np.any(raw['actions'][3] != raw['actions'][4], axis=1).sum())
                        for arm in range(8):
                            actions = raw['actions'][arm]
                            action_counts[arm] += np.bincount(actions[actions != 255], minlength=5)
    result = dict(main_2x2={}, secondary={}, action_counts={name: action_counts[i].tolist() for i, name in enumerate(NAMES)},
        mean_utility={name: float(utility[..., i, :].mean()) for i, name in enumerate(NAMES)},
        mean_accuracy={name: float(accuracy[..., i, :].mean()) for i, name in enumerate(NAMES)},
        ordinary_vs_analytic_value_action_differences=engine_action_differences, association_projection_episode_action_differences=action_difference,
        rollout_records=int(np.prod(shape)), paired_scope='Episode worlds shared across all arms and three fitted model replicates. Bootstrap resamples6 context clusters, not individual rollout count.')
    for name, left, right in [('B-A', 1, 0), ('D-C', 3, 2), ('C-A', 2, 0), ('D-B', 3, 1)]:
        result['main_2x2'][name] = contrast(utility, left, right, protocol)
    interaction = utility.copy(); interaction[..., 0, :] = utility[..., 3, :] - utility[..., 2, :] - utility[..., 1, :] + utility[..., 0, :]
    interaction[..., 1, :] = 0
    result['main_2x2']['(D-C)-(B-A)'] = contrast(interaction, 0, 1, protocol)
    for name, left, right in [('joint_execute_effect_joint_train', 3, 4), ('joint_execute_effect_factor_train', 5, 6), ('joint_train_effect_joint_execute', 3, 5), ('joint_train_effect_factor_execute', 4, 6), ('mean_projection_effect', 3, 7)]:
        result['secondary'][name] = contrast(utility, left, right, protocol)
    result['association_primary'] = contrast(utility, 3, 4, protocol, cues=[2, 3])
    result['distribution_mechanism_gate'] = bool(result['association_primary']['strictly_positive_gate'] and action_difference > 0)
    result['analytic_increment_gate'] = result['main_2x2']['D-B']['strictly_positive_gate']
    contexts = json.loads((out / 'confirmation/CONTEXTS.json').read_text())['context_features']
    witnesses = []
    for fit in candidates['fits']:
        candidate = json.loads((out / fit['candidate']).read_text())
        priors = np.asarray(candidate['full_priors'])
        for ci, context in enumerate(contexts):
            kernels, _ = model.kernels(candidate, context, 'analytic', .9)
            survival = [float((prior @ kernels[0]).sum()) for prior in priors[:4]]
            post_y0 = [float((prior @ kernels[0]).reshape(4, 2)[:, 0].sum() / survival[i]) for i, prior in enumerate(priors[:4])]
            witnesses.append(dict(fit_seed=fit['seed'], context=ci, no_outage_probabilities=survival, conditional_y0_probabilities=post_y0,
                interpretation='Cues0/1 share physical mean1 and bit marginal. Cues2/3 share both physical and bit marginals but opposite association. These are fitted-law diagnostics, not true-law posterior input to any policy.'))
    result['matched_mean_and_association_witnesses'] = witnesses
    result.update(all_blockers_closed=False, original_learned_core_advantage_established=False, production_activation=False, energy_joules=None)
    with (out / 'SUMMARY.json').open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps(dict(main=result['main_2x2'], distribution_mechanism_gate=result['distribution_mechanism_gate'], analytic_increment_gate=result['analytic_increment_gate'])))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, required=True)
    analyze(parser.parse_args().out)

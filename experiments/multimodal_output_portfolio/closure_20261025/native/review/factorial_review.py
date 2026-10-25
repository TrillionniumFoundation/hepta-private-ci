"""Read-only mathematical audit before factorial new-source evaluation."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import torch

from ...factorial.heads import Gate, objective, select, child_columns
from ...factorial.analyze import contrast_weights, signs
from ....v6.forecast import RidgeHead


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def review(args):
    torch.set_num_threads(1)
    protocol = json.loads(args.protocol.read_text())
    assert all(sha(path) == expected for path, expected in protocol['frozen_candidate_sha256'].items())
    logits = np.array([[.3, -.2, .1], [-.4, .5, .2]])
    utility = np.array([[[.4, .4], [1., -.1], [.2, .7]], [[.1, .8], [.6, .6], [-.3, .9]]])
    probability = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    expected_utility = utility.mean(axis=2)
    moments = np.exp(-2 * utility).mean(axis=2)
    row_mean = (probability * expected_utility).sum(axis=1)
    row_moment = (probability * moments).sum(axis=1)
    expected = {'mean': -row_mean.mean(), 'entropic': np.log(row_moment.mean()) / 2}
    gradient = {'mean': -probability * (expected_utility - row_mean[:, None]) / 2,
                'entropic': probability * (moments - row_moment[:, None]) / (2 * row_moment.sum())}
    objective_checks = {}
    for profile in expected:
        x = torch.tensor(logits, requires_grad=True)
        y = torch.tensor(utility, requires_grad=True)
        loss = objective(x, y, profile); loss.backward()
        assert abs(float(loss.detach()) - expected[profile]) < 1e-12 and y.grad is None
        np.testing.assert_allclose(x.grad.numpy(), gradient[profile], rtol=0, atol=1e-12)
        objective_checks[profile] = {'value': float(loss.detach()), 'analytical_gradient_matches': True,
                                     'actual_reward_labels_detached': True}
    gate, critic = Gate(), RidgeHead(673, 5)
    with torch.no_grad():
        for parameter in gate.parameters():
            parameter.zero_()
        gate.net[-1].bias[4] = 10.
        critic.weight.zero_()
        critic.weight[-1] = torch.tensor([.8, .2, .3, .5, .4])
        critic.weight[384, 2] = 5.
    features = torch.zeros(3, 5, 673)
    fixed = select(gate, critic, features, False)
    dynamic = select(gate, critic, features, True)
    assert fixed.tolist() == [4] * 3 and dynamic.tolist() == [child_columns(4)[2]] * 3
    unseen = features.clone(); unseen[:, 1:4] = 1000000.
    assert torch.equal(select(gate, critic, unseen, True), dynamic)
    observed = features.clone(); observed[:, 4, 384] = 1.
    changed = select(gate, critic, observed, True)
    assert changed.tolist() == [child_columns(4)[4]] * 3
    cells = [{'seed': seed, 'base': base, 'gate': profile, 'dynamic': enabled}
             for seed in (17, 29, 43) for base in ('supervised', 'terminal_entropic_ndu')
             for profile in ('mean', 'entropic') for enabled in (False, True)]
    terms = [v for size in (1, 2, 3) for v in itertools.combinations(range(3), size)]
    design = np.array([[np.prod(signs(cell)[list(term)]) for term in terms] for cell in cells])
    weights = contrast_weights(cells)
    np.testing.assert_allclose(weights @ design, 2 * np.eye(7), rtol=0, atol=1e-14)
    np.testing.assert_allclose(weights.sum(1), np.zeros(7), rtol=0, atol=1e-14)
    rng = np.random.default_rng(4701)
    synthetic = rng.uniform(-1, 1, size=(24, 5, 2, 2))
    multiplicity = rng.multinomial(5, np.full(5, .2), size=10)
    moment = np.exp(-2 * synthetic).mean(axis=(2, 3))
    weighted = weights @ (-np.log(moment @ (multiplicity / 5).T) / 2)
    for index, counts in enumerate(multiplicity):
        literal = synthetic[:, np.repeat(np.arange(5), counts)]
        direct = weights @ (-np.log(np.exp(-2 * literal).mean(axis=(1, 2, 3))) / 2)
        np.testing.assert_allclose(weighted[:, index], direct, rtol=0, atol=1e-12)
    base_records = {}
    for seed in (17, 29, 43):
        file = (args.assets / 'abc2-runs/base-recovery-001/training.json' if seed == 17
                else args.runs / f'base-seed-{seed}/RESULTS.json')
        reports = json.loads(file.read_text())
        if seed != 17:
            reports = reports['arms']
        left, right = reports['supervised'], reports['terminal_entropic_ndu']
        for field in ('training_config', 'initial_parameter_sha256', 'schedule_sha256'):
            assert left[field] == right[field]
        base_records[str(seed)] = {'training_config': left['training_config'],
                                  'initial_parameter_sha256': left['initial_parameter_sha256'],
                                  'schedule_sha256': left['schedule_sha256'], 'record_sha256': sha(file)}
    report = {'schema': 'hepta.closure.factorial-independent-review.v1', 'status': 'no_blocking_issue_found',
              'source_review_only_new_data_opened': False, 'protocol_sha256': sha(args.protocol),
              'frozen_files_checked': len(protocol['frozen_candidate_sha256']),
              'objective_and_gradient': objective_checks,
              'synthetic_nonanticipation': {'unselected_child_poisoning_no_effect': True,
                                           'selected_current_draft_changes_second_action': True,
                                           'first_action_unchanged': True},
              'all_seven_factorial_terms_recovered': True,
              'effect_scale': '2*Walsh coefficient; pairwise DID/2 and three-way DDD/4; averaged over three fitted seeds',
              'literal_source_cluster_resampling_comparisons': 10,
              'matched_training': base_records,
              'interpretation_limits': ['Base risk is teacher-forced conditional latent-noise surrogate risk',
                                       'Dynamic factor bundles draft feedback and shared entropic-critic replanning, not pure information value',
                                       'Softmax mixture trained; deterministic argmax deployed, no equality/global-optimum claim',
                                       'Offline complete trees support functionally nonanticipative policy evaluation, not online latency evidence',
                                       'Source-pair bootstrap conditions on three fitted seeds; primary seven nominal Bonferroni intervals only',
                                       'Historical seed17 used two training threads; new seed29/43 used one, paired within each seed'],
              'review_source_sha256': sha(__file__)}
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps({'status': report['status'], 'frozen_files_checked': report['frozen_files_checked'],
                      'objective_and_gradient': objective_checks, 'new_sources_opened': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('protocol', 'assets', 'runs', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    review(parser.parse_args())

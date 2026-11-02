"""Recompute both predeclared GRID candidates and multiplicity-adjusted bounds."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np

from audit_audio_candidate import arrays, probability, read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIMARY = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'
SECONDARY = ROOT / 'experiments/hcsn_grid_temporal_r2_20261101'
ORIGINAL = PRIMARY / 'results/run001'
OUT = SECONDARY / 'results/run001'


def close(a, b):
    assert np.allclose(a, b, atol=1e-12, rtol=0), (a, b)


def basis(p, name):
    return np.column_stack((p[:, 0], p[:, 2], p[:, 0] * p[:, 2])) if name == 'AT' else np.column_stack([p[:, group].prod(1) for size in (1, 2, 3) for group in itertools.combinations(range(3), size)])


def main(role):
    result = read(OUT / f'{role}_FAMILY_RESULT.json')
    recorded, primary = arrays(OUT / f'{role}_OUTPUTS.npz'), arrays(ORIGINAL / f'{role}_OUTPUTS.npz')
    original_result = read(ORIGINAL / f'{role}_RESULT.json')
    assert result['quantiles'] == [.0125, .9875] and result['interval_coverage'] == .975 and result['nominal_two_candidate_family_coverage'] == .95
    assert result['primary_candidate_sha256'] == sha(ORIGINAL / 'CANDIDATE_FREEZE.json')
    assert result['secondary_candidate_sha256'] == sha(OUT / 'CANDIDATE_FREEZE.json')
    source = read(SECONDARY / 'SOURCE_FREEZE.json')
    candidate = read(OUT / 'CANDIDATE_FREEZE.json')
    for name, expected in source['files'].items():
        assert sha(SECONDARY / name) == expected
    for name, expected in source['dependencies'].items():
        assert sha(ROOT / name) == expected
    for name, expected in candidate['files'].items():
        assert sha(OUT / name) == expected
    secondary_features = arrays(SECONDARY / 'features' / role / 'FEATURES.npz')
    primary_features = arrays(PRIMARY / 'features' / role / 'FEATURES.npz')
    for name in ('actor', 'member', 'label'):
        assert np.array_equal(secondary_features[name], primary_features[name])
    assert secondary_features['V'].shape == (len(secondary_features['label']), 3060)
    predicted = np.column_stack([probability(arrays(OUT / f'{name}_classifier.npz'), secondary_features['V'] if name == 'V' else primary_features[name]) for name in ('A', 'V', 'T')])
    close(predicted, recorded['clip_probabilities'])
    assert np.array_equal(recorded['clip_probabilities'][:, [0, 2]], primary['clip_probabilities'][:, [0, 2]])
    assert np.array_equal(recorded['primary_clip_probabilities'], primary['clip_probabilities'])
    assert np.array_equal(recorded['primary_AVT'], primary['AVT'])
    assert np.array_equal(recorded['AT'], primary['AT'])
    for name in ('y', 'weights', 'actor', 'ordinal', 'commands', 'clip_actor', 'clip_label', 'member'):
        assert np.array_equal(recorded[name], primary[name])
    p, y, weights, owners = recorded['episode_probabilities'], recorded['y'], recorded['weights'], recorded['actor']
    assert np.array_equal(p[:, [0, 2]], primary['episode_probabilities'][:, [0, 2]])
    actors = sorted({int(a) for a in owners})
    assert actors == ([8, 9] if role == 'development' else [10, 11, 12, 13])
    # Independently map every declared command/ordinal to its correct modality
    # clip, using the full clip registry instead of the scientific episode code.
    expected = []
    for actor, ordinal, command in zip(owners, recorded['ordinal'], recorded['commands']):
        selected = []
        for column, target in enumerate(command):
            candidates = sorted([i for i, (a, label) in enumerate(zip(secondary_features['actor'], secondary_features['label'])) if a == actor and label == target], key=lambda i: str(secondary_features['member'][i]))
            assert len(candidates) == 16
            selected.append(recorded['clip_probabilities'][candidates[int(ordinal)], column])
        expected.append(selected)
    assert np.array_equal(p, expected)
    assert np.array_equal(y, [int(len(set(c)) == 1) for c in recorded['commands']])
    at = probability(arrays(OUT / 'AT_head.npz'), basis(p, 'AT'))
    secondary_score = probability(arrays(OUT / 'AVT_head.npz'), basis(p, 'AVT'))
    close(at, recorded['AT'])
    close(secondary_score, recorded['secondary_AVT'])
    rng = np.random.default_rng(20261105 if role == 'development' else 20261106)
    indices = rng.integers(len(actors), size=(10000, len(actors)))
    reports = {}
    for name, score, clip_p in (('primary', recorded['primary_AVT'], recorded['primary_clip_probabilities']), ('secondary', recorded['secondary_AVT'], recorded['clip_probabilities'])):
        declared = result['reports'][name]
        sentence = {mod: float(np.mean((clip_p[:, column] >= .5) == secondary_features['label'])) for column, mod in enumerate(('A', 'V', 'T'))}
        for mod in sentence:
            close(sentence[mod], declared['sentence_accuracy'][mod])
        accuracy = float(np.average((score >= .5) == y, weights=weights))
        brier = float(np.average((score - y) ** 2, weights=weights))
        close([accuracy, brier], [declared['accuracy'], declared['brier']])
        differences, rates = [], []
        for actor in actors:
            take = owners == actor
            av, baseline = score[take], recorded['AT'][take]
            rates.append(np.average((av >= .5) == y[take], weights=weights[take]))
            differences.append([np.average(((av >= .5) == y[take]).astype(float) - ((baseline >= .5) == y[take]).astype(float), weights=weights[take]),
                                np.average((av - y[take]) ** 2 - (baseline - y[take]) ** 2, weights=weights[take])])
        differences = np.asarray(differences)
        close(differences, declared['actor_differences'])
        intervals = np.quantile(differences[indices].mean(1), [.0125, .9875], axis=0).T
        full = np.quantile(np.asarray(rates)[indices].mean(1), [.0125, .9875])
        close(intervals, [declared['AVT_minus_AT']['accuracy_actor_bootstrap_975'], declared['AVT_minus_AT']['brier_actor_bootstrap_975']])
        close(full, declared['AVT_actor_bootstrap_975'])
        close(differences.mean(0), [declared['AVT_minus_AT']['accuracy'], declared['AVT_minus_AT']['brier']])
        gate = sentence['A'] >= .9 and sentence['V'] >= .9 and sentence['T'] >= .99 and full[0] > 5/6 and intervals[0, 0] > 0
        assert bool(gate) == declared['family_adjusted_gate']
        reports[name] = dict(sentence_accuracy=sentence, accuracy=accuracy, brier=brier, actor_bootstrap_975=full.tolist(),
                             paired_actor_bootstrap_975=intervals.tolist(), family_adjusted_gate=bool(gate))
    primary_95 = original_result['AVT_actor_bootstrap_95']
    assert reports['primary']['actor_bootstrap_975'][0] <= primary_95[0] and reports['primary']['actor_bootstrap_975'][1] >= primary_95[1]
    report = dict(schema='hcsn.grid-two-candidate-family.independent-output-audit.v1', role=role, actors=actors,
        result_sha256=sha(OUT / f'{role}_FAMILY_RESULT.json'), output_sha256=sha(OUT / f'{role}_OUTPUTS.npz'),
        primary_original_result_sha256=sha(ORIGINAL / f'{role}_RESULT.json'), reports=reports,
        original_primary_outputs_bit_identical=True, clean_AT_scores_bit_identical=True, A_T_clip_and_episode_probabilities_bit_identical=True,
        quantiles=[.0125, .9875], any_candidate_family_gate=any(r['family_adjusted_gate'] for r in reports.values()),
        real_media_opened=False, neural_encoder_inference_performed=False, frozen_head_predictions_recomputed=True, fit_performed=False,
        limitation='Two candidates were registered before shared held media; both are reported. Nominal Bonferroni bounds use a small actor-cluster bootstrap and do not guarantee population coverage or global identity exclusion.', all_blockers_closed=False)
    target = HERE / f'REVIEW_GRID_FAMILY_{role.upper()}.json'
    with target.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), role=role, reports=reports), sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['development', 'confirmation'])
    main(parser.parse_args().role)

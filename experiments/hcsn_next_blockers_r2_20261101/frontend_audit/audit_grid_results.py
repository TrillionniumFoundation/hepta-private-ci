"""Recompute registered GRID held-role predictions, pairings and quality gates."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np

from audit_audio_candidate import arrays, probability, read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GRID = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'
OUT = GRID / 'results/run001'


def close(a, b):
    assert np.allclose(a, b, atol=1e-12, rtol=0), (a, b)


def basis(p, name):
    return np.column_stack((p[:, 0], p[:, 2], p[:, 0] * p[:, 2])) if name == 'AT' else np.column_stack([p[:, group].prod(1) for size in (1, 2, 3) for group in itertools.combinations(range(3), size)])


def main(role):
    result, recorded = read(OUT / f'{role}_RESULT.json'), arrays(OUT / f'{role}_OUTPUTS.npz')
    candidate = read(OUT / 'CANDIDATE_FREEZE.json')
    assert result['candidate_sha256'] == sha(OUT / 'CANDIDATE_FREEZE.json')
    for name, expected in candidate['files'].items():
        assert sha(OUT / name) == expected
    source = read(GRID / 'MODEL_SOURCE_FREEZE.json')
    assert candidate['model_source_freeze_sha256'] == sha(GRID / 'MODEL_SOURCE_FREEZE.json')
    for name, expected in source['files'].items():
        assert sha(GRID / name) == expected
    directory = GRID / 'features' / role
    identity = read(directory / 'IDENTITY.json')
    values = arrays(directory / 'FEATURES.npz')
    assert result['features_sha256'] == identity['features_sha256'] == sha(directory / 'FEATURES.npz')
    assert identity['cohort_sha256'] == sha(GRID / 'COHORT_SELECTION.json')
    assert identity['model_source_freeze_sha256'] == sha(GRID / 'MODEL_SOURCE_FREEZE.json')
    assert identity['acquisition_sha256'] == sha(GRID / 'inputs' / f'{role.upper()}_ACQUISITION.json')
    rows = [row for row in read(GRID / 'COHORT_SELECTION.json')['entries'] if row['role'] == role]
    assert values['member'].tolist() == recorded['member'].tolist() == [r['name'] for r in rows]
    assert values['actor'].tolist() == recorded['clip_actor'].tolist() == [r['speaker'] for r in rows]
    assert values['label'].tolist() == recorded['clip_label'].tolist() == [r['sentence_target'] for r in rows]
    actors = sorted({int(actor) for actor in values['actor']})
    assert actors == ([8, 9] if role == 'development' else [10, 11, 12, 13])
    assert len(rows) == 32 * len(actors)
    predicted = np.column_stack([probability(arrays(OUT / f'{name}_classifier.npz'), values[name]) for name in ('A', 'V', 'T')])
    close(predicted, recorded['clip_probabilities'])
    prediction_error = float(np.max(np.abs(predicted - recorded['clip_probabilities'])))
    clip_p = recorded['clip_probabilities']
    p, targets, weights, owners, ordinals, commands = [], [], [], [], [], []
    for actor in actors:
        groups = {target: sorted([i for i, (a, y) in enumerate(zip(values['actor'], values['label'])) if a == actor and y == target], key=lambda i: str(values['member'][i])) for target in (0, 1)}
        assert len(groups[0]) == len(groups[1]) == 16
        for ordinal in range(16):
            for command in itertools.product((0, 1), repeat=3):
                p.append([clip_p[groups[y][ordinal], column] for column, y in enumerate(command)])
                equal = int(len(set(command)) == 1)
                targets.append(equal)
                weights.append(3 if equal else 1)
                owners.append(actor)
                ordinals.append(ordinal)
                commands.append(command)
    p, targets, weights, owners = np.asarray(p), np.asarray(targets), np.asarray(weights, np.float64), np.asarray(owners)
    for name, expected in (('episode_probabilities', p), ('y', targets), ('weights', weights), ('actor', owners), ('ordinal', ordinals), ('commands', commands)):
        assert np.array_equal(recorded[name], expected)
    scores = {name: probability(arrays(OUT / f'{name}_head.npz'), basis(p, name)) for name in ('AT', 'AVT')}
    metrics = {}
    for name in ('AT', 'AVT'):
        close(scores[name], recorded[name])
        metrics[name] = dict(accuracy=float(np.average((scores[name] >= .5) == targets, weights=weights)),
                             brier=float(np.average((scores[name] - targets) ** 2, weights=weights)))
        close([metrics[name]['accuracy'], metrics[name]['brier']], [result['relation'][name]['accuracy'], result['relation'][name]['brier']])
    delta, rates = [], []
    for actor in actors:
        take = owners == actor
        av, at = scores['AVT'][take], scores['AT'][take]
        delta.append([np.average(((av >= .5) == targets[take]).astype(float) - ((at >= .5) == targets[take]).astype(float), weights=weights[take]),
                      np.average((av - targets[take]) ** 2 - (at - targets[take]) ** 2, weights=weights[take])])
        rates.append(np.average((av >= .5) == targets[take], weights=weights[take]))
    delta = np.asarray(delta)
    close(delta, result['actor_differences'])
    rng = np.random.default_rng(20261105 if role == 'development' else 20261106)
    indices = rng.integers(len(actors), size=(10000, len(actors)))
    intervals = np.quantile(delta[indices].mean(1), [.025, .975], axis=0).T
    full_interval = np.quantile(np.asarray(rates)[indices].mean(1), [.025, .975])
    close(full_interval, result['AVT_actor_bootstrap_95'])
    close(intervals, [result['AVT_minus_AT']['accuracy_actor_bootstrap_95'], result['AVT_minus_AT']['brier_actor_bootstrap_95']])
    close(delta.mean(0), [result['AVT_minus_AT']['accuracy'], result['AVT_minus_AT']['brier']])
    sentence = {name: float(np.mean((predicted[:, column] >= .5) == values['label'])) for column, name in enumerate(('A', 'V', 'T'))}
    for name in sentence:
        close(sentence[name], result['sentence_accuracy'][name])
    rng = np.random.default_rng(20261107 if role == 'development' else 20261108)
    shuffled = []
    head = arrays(OUT / 'AVT_head.npz')
    for _ in range(100):
        altered = p.copy()
        for actor in actors:
            take = np.flatnonzero(owners == actor)
            altered[take, 1] = p[rng.permutation(take), 1]
        score = probability(head, basis(altered, 'AVT'))
        shuffled.append(float(np.average((score >= .5) == targets, weights=weights)))
    close(shuffled, result['shuffled_video_accuracy'])
    gate = sentence['A'] >= .9 and sentence['V'] >= .9 and sentence['T'] >= .99 and full_interval[0] > 5/6 and intervals[0, 0] > 0
    assert bool(gate) == result['registered_quality_gate']
    report = dict(schema='hcsn.grid-held-role.independent-output-audit.v1', role=role, candidate_sha256=sha(OUT / 'CANDIDATE_FREEZE.json'),
        result_sha256=sha(OUT / f'{role}_RESULT.json'), output_sha256=sha(OUT / f'{role}_OUTPUTS.npz'),
        clip_count=len(rows), actors=actors, episode_count=len(targets), sentence_accuracy=sentence, relation=metrics,
        clip_prediction_max_error=prediction_error, actor_differences=delta.tolist(), paired_actor_bootstrap_95=intervals.tolist(),
        AVT_actor_bootstrap_95=full_interval.tolist(), shuffle_recompute_max_error=float(np.max(np.abs(np.asarray(shuffled) - result['shuffled_video_accuracy']))),
        registered_gate_recomputed=bool(gate), exact_registered_episode_pairing=True, real_media_opened=False, encoder_inference_performed=False, frozen_head_predictions_recomputed=True, fit_performed=False,
        limitation='Registered historical recording-group confirmation only; actor-cluster intervals with four confirmation speakers are bounded-group descriptive evidence, not global unseen identity/open-domain/analytic-core/GPU/production qualification.',
        all_blockers_closed=False)
    target = HERE / f'REVIEW_GRID_{role.upper()}.json'
    with target.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), role=role, registered_gate=bool(gate), sentence=sentence, delta_accuracy=float(delta[:, 0].mean())), sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['development', 'confirmation'])
    main(parser.parse_args().role)

"""Recompute CREMA development metrics from frozen heads and recorded outputs."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np

from audit_audio_candidate import arrays, probability, read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R1 = ROOT / 'experiments/hcsn_video_followup_20261101'
LANES = {
    'raw': ('hcsn_video_raw_r2_20261101', 'run002', 20261103, 20261104),
    'visual': ('hcsn_video_pretrained_feasibility_r2_20261101', 'run001', 20261103, 20261104),
    'audio': ('hcsn_audio_pretrained_r2_20261101', 'run001', 20261110, None),
    'joint': ('hcsn_joint_pretrained_av_r2_20261101', 'run001', 20261113, 20261114),
}


def features(p, name):
    if name == 'AT_unique':
        return np.column_stack((p[:, 0], p[:, 2], p[:, 0] * p[:, 2]))
    return np.column_stack([p[:, group].prod(1) for size in (1, 2, 3) for group in itertools.combinations(range(3), size)])


def close(a, b):
    assert np.allclose(a, b, atol=1e-12, rtol=0), (a, b)


def main(lane):
    directory, run, bootstrap_seed, shuffle_seed = LANES[lane]
    base = ROOT / 'experiments' / directory
    out = base / 'results' / run
    result, recorded = read(out / 'RESULT.json'), arrays(out / 'VALIDATION_OUTPUTS.npz')
    candidate = read(out / 'CANDIDATE_FREEZE.json')
    for name, digest in candidate['files'].items():
        assert sha(out / name) == digest
    episodes = arrays(R1 / 'inputs/data/validation.npz')
    for name in ('actor', 'y', 'sample_weight'):
        assert np.array_equal(recorded[name], episodes[name])
    p, y, weights, actors = recorded['probabilities'], recorded['y'], recorded['sample_weight'], np.unique(recorded['actor'])
    assert p.shape == (288, 3) and len(actors) == 6 and np.isfinite(p).all()
    assert ((p >= 0) & (p <= 1)).all()
    s = episodes['sentence_indices']
    assert np.array_equal(y, (s[:, 0] == s[:, 1]) & (s[:, 1] == s[:, 2]))
    names = ('AT_unique', 'AVT_R1V' if lane == 'audio' else 'AVT')
    scores = {name: probability(arrays(out / f'{name}_head.npz'), features(p, name)) for name in names}
    metrics = {}
    for name in names:
        if name in recorded:
            close(scores[name], recorded[name])
        metrics[name] = dict(accuracy=float(np.average((scores[name] >= .5) == y, weights=weights)),
                             brier=float(np.average((scores[name] - y) ** 2, weights=weights)))
        close(metrics[name]['accuracy'], result['relation'][name]['accuracy'])
        close(metrics[name]['brier'], result['relation'][name]['brier'])
    delta = []
    for actor in actors:
        take = recorded['actor'] == actor
        left, right = scores[names[1]][take], scores['AT_unique'][take]
        delta.append([np.average(((left >= .5) == y[take]).astype(float) - ((right >= .5) == y[take]).astype(float), weights=weights[take]),
                      np.average((left - y[take]) ** 2 - (right - y[take]) ** 2, weights=weights[take])])
    delta = np.array(delta)
    close(delta, result['actor_differences'])
    rng = np.random.default_rng(bootstrap_seed)
    bootstrap = delta[rng.integers(len(actors), size=(10000, len(actors)))].mean(1)
    interval = np.quantile(bootstrap, [.025, .975], axis=0).T
    reported_delta = result['AVT_R1V_minus_AT_unique' if lane == 'audio' else 'AVT_minus_AT_unique']
    close(delta.mean(0), [reported_delta['accuracy'], reported_delta['brier']])
    close(interval, reported_delta['actor_bootstrap_95'] if lane in ('audio', 'joint') else [reported_delta['accuracy_actor_bootstrap_95'], reported_delta['brier_actor_bootstrap_95']])
    sentence = {}
    for modality in ('audio', 'video'):
        if modality not in recorded:
            continue
        key = 'audio_clip' if lane == 'joint' and modality == 'audio' else ('video_clip' if lane == 'joint' else 'clip')
        clips = recorded[key]
        targets = np.array([int(str(c).split('_')[1] == 'IOM') for c in clips])
        assert len(clips) == len(set(clips)) == 72 and np.bincount(targets).tolist() == [36, 36]
        probabilities = recorded[modality]
        sentence[modality] = float(np.mean((probabilities >= .5) == targets))
        field = 'sentence_' + modality + '_accuracy' if lane == 'joint' else ('audio_sentence_accuracy' if lane == 'audio' else 'sentence_video_accuracy')
        close(sentence[modality], result[field])
        mapping = dict(zip(clips, probabilities))
        index = 0 if modality == 'audio' else 1
        mapped = [mapping[f"{actor}_{('DFA','IOM')[command[index]]}_{emotion}_XX"] for actor, command, emotion in zip(episodes['actor'], episodes['sentence_indices'], episodes['emotion'])]
        close(mapped, p[:, index])
        if lane in ('raw', 'visual'):
            for diagnostic in ('reverse', 'static'):
                close(np.mean((recorded[diagnostic] >= .5) == targets), result['diagnostics'][diagnostic])
    r1 = arrays(R1 / 'results/run002/VALIDATION_OUTPUTS.npz')
    attribution = {}
    for mi, modality in ((0, 'audio'), (1, 'video'), (2, 'text')):
        unchanged = modality == 'text' or (lane in ('raw', 'visual') and modality == 'audio') or (lane == 'audio' and modality == 'video')
        if unchanged:
            error = float(np.max(np.abs(p[:, mi] - r1['probabilities'][:, mi])))
            assert error < 1e-14
            attribution[modality] = dict(max_error_vs_R1=error, bit_identical=bool(np.array_equal(p[:, mi], r1['probabilities'][:, mi])))
    shuffle_error = None
    if shuffle_seed is not None:
        rng = np.random.default_rng(shuffle_seed)
        rates = []
        head = arrays(out / f'{names[1]}_head.npz')
        for _ in range(100):
            altered = p.copy()
            for actor in actors:
                take = np.flatnonzero(recorded['actor'] == actor)
                altered[take, 1] = p[rng.permutation(take), 1]
            predictions = probability(head, features(altered, names[1]))
            rates.append(float(np.average((predictions >= .5) == y, weights=weights)))
        close(rates, result['shuffled_video_accuracy'])
        shuffle_error = float(np.max(np.abs(np.asarray(rates) - result['shuffled_video_accuracy'])))
    if lane == 'audio':
        gate = sentence['audio'] >= .9
        assert gate == result['audio_gate']
    elif lane == 'joint':
        gate = sentence['audio'] >= .9 and sentence['video'] >= .9 and interval[0, 0] > 0
        assert gate == result['joint_gate']
    else:
        gate = sentence['video'] >= .9 and interval[0, 0] > 0
        assert gate == result['video_gate' if lane == 'raw' else 'video_development_gate']
    report = dict(schema='hcsn.crema-development.independent-output-audit.v1', lane=lane,
        result_sha256=sha(out / 'RESULT.json'), output_sha256=sha(out / 'VALIDATION_OUTPUTS.npz'), candidate_sha256=sha(out / 'CANDIDATE_FREEZE.json'),
        episodes=288, actor_count=6, clip_targets_checked=sentence, relation=metrics, actor_differences=delta.tolist(),
        paired_actor_bootstrap_95=interval.tolist(), registered_gate_recomputed=bool(gate), unchanged_modalities=attribution,
        shuffle_recompute_max_error=shuffle_error, real_media_opened=False, model_inference_performed=False, fit_performed=False,
        limitation='The original historical six-actor development panel is not fresh external confirmation. This audit recomputes frozen-output metrics and does not establish hidden pretraining-actor exclusion or production/GPU/energy adoption.', all_blockers_closed=False)
    target = HERE / f'REVIEW_CREMA_{lane.upper()}.json'
    with target.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), lane=lane, registered_gate=bool(gate), sentence=sentence, delta_accuracy=float(delta[:, 0].mean())), sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('lane', choices=list(LANES))
    main(parser.parse_args().lane)

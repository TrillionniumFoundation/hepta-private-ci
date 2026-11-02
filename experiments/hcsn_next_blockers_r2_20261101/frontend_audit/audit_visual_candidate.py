"""Independently recompute frozen visual-head predictions; no target refitting."""
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VISUAL = ROOT / 'experiments/hcsn_video_pretrained_feasibility_r2_20261101'
OUT = VISUAL / 'results/run001'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def arrays(path):
    with np.load(path, allow_pickle=False) as values:
        return {k: values[k] for k in values.files}


def probability(checkpoint, matrix):
    margin = ((matrix - checkpoint['mean']) / checkpoint['scale']) @ checkpoint['beta'][:-1] + checkpoint['beta'][-1]
    return np.exp(-np.logaddexp(0, -margin))


def check_fit(checkpoint, x, y, weights, record):
    mean, scale = x.mean(0), np.maximum(x.std(0), 1e-8)
    assert np.allclose(checkpoint['mean'], mean, atol=1e-12, rtol=0)
    assert np.allclose(checkpoint['scale'], scale, atol=1e-12, rtol=0)
    xx = (x - mean) / scale
    residual = weights * (probability(checkpoint, x) - y)
    gradient = np.concatenate((xx.T @ residual + checkpoint['beta'][:-1], [residual.sum()]))
    norm = float(np.max(np.abs(gradient)))
    assert abs(norm - record['gradient_inf']) < 1e-8
    assert record['success'] and record['status'] == 0
    assert record['features'] == x.shape[1] and record['rows'] == len(x)
    assert all(np.isfinite(v).all() for v in checkpoint.values())
    return dict(tag=record['tag'], mean_scale_max_error=float(max(np.max(np.abs(mean - checkpoint['mean'])), np.max(np.abs(scale - checkpoint['scale'])))),
                gradient_inf_recomputed=norm, optimizer_iterations=record['iterations'], optimizer_success=True)


def main():
    source = read(VISUAL / 'SOURCE_FREEZE.json')
    frozen = read(OUT / 'CANDIDATE_FREEZE.json')
    identity = frozen['identity']
    assert identity == source['identity']
    assert not frozen['validation_loaded']
    for relative, digest in identity['source_sha256'].items():
        assert sha(VISUAL / relative) == digest
    for relative, digest in identity['dependencies'].items():
        assert sha(ROOT / relative) == digest
    for name, digest in frozen['files'].items():
        assert sha(OUT / name) == digest
    assert sha(VISUAL / 'PROTOCOL.json') == identity['protocol_sha256']
    assert sha(VISUAL / 'inputs/train_features.npz') == frozen['train_features_sha256']
    assert sha(VISUAL / 'inputs/train_IDENTITY.json') == frozen['train_identity_sha256']
    feature_identity = read(VISUAL / 'inputs/train_IDENTITY.json')
    assert feature_identity['identity'] == identity and feature_identity['features_sha256'] == frozen['train_features_sha256']
    training = read(OUT / 'TRAINING.json')
    records = [json.loads(line) for line in (OUT / 'FIT_RECORDS.jsonl').read_text().splitlines()]
    assert records == training['fits'] and len(records) == 7
    assert not training['validation_loaded'] and training['pretrained_frozen'] and not training['new_neural_training']
    values = arrays(VISUAL / 'inputs/train_features.npz')
    assert values['frame_embeddings'].shape == (288, 25, 512) and values['tcn_logits'].shape == (288, 500)
    # Independently assemble five consecutive time-bin means and frozen logits.
    bins = np.stack([values['frame_embeddings'][:, start:start + 5].sum(1) / np.float32(5) for start in range(0, 25, 5)], axis=1)
    x = np.concatenate((bins.reshape(288, 2560), values['tcn_logits']), axis=1).astype(np.float64)
    assert x.shape == (288, 3060) and np.isfinite(x).all()
    cohort = read(ROOT / 'experiments/hcsn_four_stage_flow_20261031/data/COHORT.json')
    rows = sorted([r for r in cohort['records'] if r['split'] == 'train'], key=lambda r: r['clip'])
    assert values['clip'].tolist() == [r['clip'] for r in rows]
    assert values['actor'].tolist() == [r['actor'] for r in rows]
    y = np.array([0 if r['sentence'] == 'DFA' else 1 for r in rows])
    assert np.array_equal(y, values['label']) and np.bincount(y).tolist() == [144, 144]
    for row, metadata in zip(rows, feature_identity['records']):
        assert metadata['clip'] == row['clip'] and metadata['raw_sha256'] == row['sha256']
        assert len(metadata['selected_timestamps']) == 25
        assert np.all(np.asarray(metadata['selected_timestamps']) <= np.asarray(metadata['cutoffs']))
        assert metadata['accepted_end'] == metadata['origin'] + 1
        assert not metadata['live_causal_qualification']
    actors = sorted(set(values['actor']))
    predicted = np.full(288, np.nan)
    checked = []
    for fold in range(4):
        checkpoint = arrays(OUT / f'video_fold{fold}.npz')
        held_actors = set(actors[fold::4])
        held = np.array([a in held_actors for a in values['actor']])
        row = training['folds'][fold]
        assert set(row['held_actors']) == held_actors
        assert set(row['fit_actors']) == set(actors) - held_actors
        assert len(row['held_actors']) == 6 and len(row['fit_actors']) == 18
        checked.append(check_fit(checkpoint, x[~held], y[~held], np.ones((~held).sum()), records[fold]))
        predicted[held] = probability(checkpoint, x[held])
        assert np.mean((predicted[held] >= .5) == y[held]) == row['accuracy']
    checked.append(check_fit(arrays(OUT / 'video_full.npz'), x, y, np.ones(288), records[4]))
    oof = arrays(OUT / 'TRAIN_OOF.npz')
    error = float(np.max(np.abs(predicted - oof['video'])))
    assert error < 1e-14
    assert np.array_equal(oof['clip'], values['clip']) and np.array_equal(oof['label'], y)
    assert np.mean((predicted >= .5) == y) == training['video_oof_accuracy']
    inherited = ROOT / 'experiments/hcsn_video_followup_20261101'
    old = arrays(inherited / 'results/run002/TRAIN_OOF.npz')
    relation = arrays(inherited / 'inputs/data/train.npz')
    assert np.array_equal(oof['probabilities'][:, [0, 2]], old['probabilities'][:, [0, 2]])
    mapping = dict(zip(values['clip'], predicted))
    mapped = np.array([mapping[f"{actor}_{('DFA','IOM')[sentence[1]]}_{emotion}_XX"] for actor, emotion, sentence in zip(relation['actor'], relation['emotion'], relation['sentence_indices'])])
    assert np.max(np.abs(mapped - oof['probabilities'][:, 1])) < 1e-14
    p = oof['probabilities']
    for index, name in enumerate(('AT_unique', 'AVT')):
        if name == 'AT_unique':
            features = np.column_stack((p[:, 0], p[:, 2], p[:, 0] * p[:, 2]))
        else:
            features = np.column_stack([p[:, ix].prod(1) for size in (1, 2, 3) for ix in itertools.combinations(range(3), size)])
        checked.append(check_fit(arrays(OUT / f'{name}_head.npz'), features, relation['y'], relation['sample_weight'], records[5 + index]))
    result = dict(schema='hcsn.pretrained-visual.independent-candidate-audit.v1',
        candidate_sha256=sha(OUT / 'CANDIDATE_FREEZE.json'), feature_sha256=sha(VISUAL / 'inputs/train_features.npz'),
        source_freeze_sha256=sha(VISUAL / 'SOURCE_FREEZE.json'), frozen_candidate_files_checked=len(frozen['files']),
        fits=checked, video_oof_probability_max_error=error, video_oof_accuracy=float(np.mean((predicted >= .5) == y)),
        known_audio_text_unchanged=True, binary_sentence_targets_verified=True, independent_actor_partition_verified=True,
        input_clips=288, feature_dimensions=3060, held_media_decoded=False, fit_performed=False,
        limitation='Recorded optimizer success uses objective-reduction termination; independent gradient magnitudes retained. Offline presentation prefix and unknown pretraining actor overlap remain explicit. OOF68.06% is below90%; no tuning or adoption claim.',
        all_blockers_closed=False)
    target = HERE / 'REVIEW_VISUAL_CANDIDATE.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), fit_count=len(checked), video_oof_accuracy=result['video_oof_accuracy'], probability_max_error=error), sort_keys=True))


if __name__ == '__main__':
    main()

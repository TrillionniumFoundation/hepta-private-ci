"""Independent frozen audio-head normalization, OOF and relation audit."""
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import re

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AUDIO = ROOT / 'experiments/hcsn_audio_pretrained_r2_20261101'
OUT = AUDIO / 'results/run001'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def arrays(path):
    with np.load(path, allow_pickle=False) as values:
        return {k: values[k] for k in values.files}


def probability(checkpoint, matrix):
    margin = ((np.asarray(matrix, np.float64) - checkpoint['mean']) / checkpoint['scale']) @ checkpoint['beta'][:-1] + checkpoint['beta'][-1]
    return np.exp(-np.logaddexp(0, -margin))


def check_fit(checkpoint, x, y, weights, record):
    x = np.asarray(x, np.float64)
    mean, scale = x.mean(0), np.maximum(x.std(0), 1e-8)
    assert np.array_equal(mean, checkpoint['mean']) and np.array_equal(scale, checkpoint['scale'])
    xx = (x - mean) / scale
    residual = weights * (probability(checkpoint, x) - y)
    gradient = np.concatenate((xx.T @ residual + checkpoint['beta'][:-1], [residual.sum()]))
    norm = float(np.max(np.abs(gradient)))
    assert abs(norm - record['gradient_inf']) < 1e-8
    assert record['success'] and record['status'] == 0 and record['C'] == 1
    assert record['features'] == x.shape[1] and record['rows'] == len(x)
    return dict(tag=record['tag'], fit_only_mean_scale_exact=True, gradient_inf_recomputed=norm, optimizer_iterations=record['iterations'], optimizer_success=True)


def main():
    source = read(AUDIO / 'SOURCE_FREEZE.json')
    frozen = read(OUT / 'CANDIDATE_FREEZE.json')
    for relative, digest in source['source'].items():
        assert sha(ROOT / relative) == digest
    for name, digest in source['runtime_source_sha256'].items():
        assert sha(importlib.import_module(name).__file__) == digest
    publication_path = AUDIO / 'CANDIDATE_PUBLICATION.json'
    publication = read(publication_path) if publication_path.exists() else None
    if publication is not None:
        assert re.fullmatch('[0-9a-f]{40}', publication['source_commit'])
        assert publication['candidate_freeze_sha256'] == sha(OUT / 'CANDIDATE_FREEZE.json')
    assert frozen['source_freeze_sha256'] == sha(AUDIO / 'SOURCE_FREEZE.json')
    assert not frozen['development_loaded']
    for name, digest in frozen['files'].items():
        assert sha(OUT / name) == digest
    directory = Path(frozen['input_features_path'])
    if not directory.is_absolute():
        directory = ROOT / directory
    assert frozen['input_features_sha256'] == sha(directory / 'features.npz')
    assert frozen['input_identity_sha256'] == sha(directory / 'IDENTITY.json')
    identity = read(directory / 'IDENTITY.json')
    assert identity['features_sha256'] == frozen['input_features_sha256']
    assert identity['manifest_sha256'] == sha(directory / 'COHORT.json') == sha(AUDIO / 'TRAIN_COHORT.json')
    assert identity['checkpoint_sha256'] == frozen['checkpoint_sha256'] == source['checkpoint_sha256']
    assert identity['source_sha256'] == sha(AUDIO / 'encoder.py')
    values = arrays(directory / 'features.npz')
    x, y = values['features'], values['label']
    assert x.shape == (288, 1652) and values['ctc_logits'].shape == (288, 49, 29)
    assert np.isfinite(x).all() and np.isfinite(values['ctc_logits']).all()
    rows = sorted(read(directory / 'COHORT.json')['records'], key=lambda row: row['clip'])
    assert values['clip'].tolist() == [row['clip'] for row in rows]
    assert values['actor'].tolist() == [str(row['actor']) for row in rows]
    assert np.array_equal(y, [0 if row['sentence'] == 'DFA' else 1 for row in rows])
    assert np.bincount(y).tolist() == [144, 144]
    # The stored CTC part of the descriptor is independently reconstructible.
    ctc = values['ctc_logits'].astype(np.float64)
    bins = [ctc[:, lo:hi].mean(1) for lo, hi in ((0, 13), (13, 25), (25, 37), (37, 49))]
    ctc_error = float(np.max(np.abs(np.concatenate(bins, axis=1) - x[:, 1536:])))
    assert ctc_error < 2e-5
    for row, feature, logits, detail in zip(rows, x, values['ctc_logits'], identity['details']):
        assert detail['clip'] == row['clip'] and detail['raw_sha256'] == row['sha256']
        assert detail['feature_sha256'] == hashlib.sha256(feature.tobytes()).hexdigest()
        assert detail['ctc_sha256'] == hashlib.sha256(logits.tobytes()).hexdigest()
        prefix = detail['prefix']
        assert prefix['accepted_samples'] == 16000 and prefix['accepted_end'] == prefix['origin'] + 1
        assert not prefix['future_pcm_used'] and not prefix['full_recording_normalization']
        assert prefix['native_sample_rate'] - 1 <= prefix['native_samples'] <= prefix['native_sample_rate']
    training = read(OUT / 'TRAINING.json')
    records = training['fits']
    assert len(records) == 7 and not training['development_loaded'] and not training['hyperparameter_selection']
    actors = sorted(set(values['actor']))
    assert len(actors) == 24
    predicted = np.full(288, np.nan)
    checked = []
    for fold in range(4):
        row = training['folds'][fold]
        held_actors = set(actors[fold::4])
        assert set(row['held_actors']) == held_actors and set(row['fit_actors']) == set(actors) - held_actors
        assert len(row['held_actors']) == 6 and len(row['fit_actors']) == 18
        held = np.array([a in held_actors for a in values['actor']])
        assert row['held_clips'] == values['clip'][held].tolist()
        checkpoint = arrays(OUT / f'audio_fold{fold}.npz')
        checked.append(check_fit(checkpoint, x[~held], y[~held], np.ones((~held).sum()), records[fold]))
        predicted[held] = probability(checkpoint, x[held])
        assert np.mean((predicted[held] >= .5) == y[held]) == row['accuracy']
    checked.append(check_fit(arrays(OUT / 'audio_full_head.npz'), x, y, np.ones(288), records[4]))
    oof = arrays(OUT / 'TRAIN_OOF.npz')
    error = float(np.max(np.abs(predicted - oof['audio'])))
    assert error < 1e-14 and np.array_equal(oof['clip'], values['clip']) and np.array_equal(oof['label'], y)
    assert np.mean((predicted >= .5) == y) == training['sentence_oof_accuracy']
    inherited = ROOT / 'experiments/hcsn_video_followup_20261101'
    old = arrays(inherited / 'results/run002/TRAIN_OOF.npz')
    relation = arrays(OUT / 'RELATION_TRAIN_OOF.npz')
    original_relation = arrays(inherited / 'inputs/data/train.npz')
    for name in ('actor', 'y', 'sample_weight', 'sentence_indices'):
        assert np.array_equal(relation[name], original_relation[name])
    assert np.array_equal(relation['probabilities'][:, [1, 2]], old['probabilities'][:, [1, 2]])
    mapping = dict(zip(values['clip'], predicted))
    mapped = np.array([mapping[f"{actor}_{('DFA','IOM')[sentence[0]]}_{emotion}_XX"] for actor, emotion, sentence in zip(original_relation['actor'], original_relation['emotion'], original_relation['sentence_indices'])])
    assert np.max(np.abs(mapped - relation['probabilities'][:, 0])) < 1e-14
    p = relation['probabilities']
    for index, name in enumerate(('AT_unique', 'AVT_R1V')):
        features = np.column_stack((p[:, 0], p[:, 2], p[:, 0] * p[:, 2])) if name == 'AT_unique' else np.column_stack([p[:, ix].prod(1) for size in (1, 2, 3) for ix in itertools.combinations(range(3), size)])
        checked.append(check_fit(arrays(OUT / f'{name}_head.npz'), features, relation['y'], relation['sample_weight'], records[5 + index]))
    result = dict(schema='hcsn.pretrained-audio.independent-candidate-audit.v1', candidate_sha256=sha(OUT / 'CANDIDATE_FREEZE.json'),
        source_freeze_sha256=sha(AUDIO / 'SOURCE_FREEZE.json'), feature_sha256=sha(directory / 'features.npz'), frozen_candidate_files_checked=len(frozen['files']),
        local_publication_receipt_present=publication is not None, fits=checked, oof_probability_max_error=error, audio_oof_accuracy=float(np.mean((predicted >= .5) == y)), ctc_descriptor_max_error=ctc_error,
        inherited_video_text_bit_identical=True, input_clips=288, feature_dimensions=1652, target_counts=[144, 144],
        held_media_decoded=False, real_media_opened=False, fit_performed=False, all_blockers_closed=False,
        scope='Independent cached-feature/head audit. Frozen speech inference was not rerun; official model equivalence and future-PCM isolation are separately recorded preflight checks. Remote publication is a separate parent gate; this audit may run before publication.')
    target = HERE / 'REVIEW_AUDIO_CANDIDATE.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), fit_count=len(checked), audio_oof_accuracy=result['audio_oof_accuracy'], probability_max_error=error), sort_keys=True))


if __name__ == '__main__':
    main()

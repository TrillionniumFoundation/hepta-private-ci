"""Verify secondary GRID's five new fits and byte-identical primary controls."""
import itertools
import json
from pathlib import Path

import numpy as np

import audit_grid_candidate as common
from audit_audio_candidate import arrays, probability, read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'experiments/hcsn_grid_temporal_r2_20261101'
OUT = BASE / 'results/run001'
PRIMARY = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'
ORIGINAL = PRIMARY / 'results/run001'


def main():
    source, candidate = read(BASE / 'SOURCE_FREEZE.json'), read(OUT / 'CANDIDATE_FREEZE.json')
    assert candidate['source_freeze_sha256'] == sha(BASE / 'SOURCE_FREEZE.json')
    assert candidate['primary_candidate_sha256'] == sha(ORIGINAL / 'CANDIDATE_FREEZE.json')
    assert not candidate['held_media_accessed']
    for name, digest in source['files'].items():
        assert sha(BASE / name) == digest
    for name, digest in source['dependencies'].items():
        assert sha(ROOT / name) == digest
    for name, digest in candidate['files'].items():
        assert sha(OUT / name) == digest
    for name, digest in read(ORIGINAL / 'CANDIDATE_FREEZE.json')['files'].items():
        assert sha(ORIGINAL / name) == digest
    training = read(OUT / 'TRAINING.json')
    assert len(training['fits']) == 5 and not training['held_media_accessed']
    copied = training['copied_primary_files']
    expected_copies = {'A_classifier.npz', 'T_classifier.npz', 'AT_head.npz', *[f'{mod}_fold{fold}.npz' for mod in ('A', 'T') for fold in range(3)]}
    assert len(copied) == len(expected_copies) == 9 and {r['file'] for r in copied} == expected_copies
    for row in copied:
        assert sha(OUT / row['file']) == row['sha256'] == sha(ORIGINAL / row['file'])
    directory = BASE / 'features/train'
    assert sha(directory / 'FEATURES.npz') == training['secondary_features_sha256']
    assert sha(PRIMARY / 'features/train/FEATURES.npz') == training['primary_AT_features_sha256']
    identity = read(directory / 'IDENTITY.json')
    assert identity['features_sha256'] == sha(directory / 'FEATURES.npz')
    assert identity['source_freeze_sha256'] == sha(BASE / 'SOURCE_FREEZE.json')
    assert identity['primary_acquisition_sha256'] == sha(PRIMARY / 'inputs/TRAIN_ACQUISITION.json')
    assert identity['details'] == read(PRIMARY / 'features/train/IDENTITY.json')['details']
    values, original = arrays(directory / 'FEATURES.npz'), arrays(PRIMARY / 'features/train/FEATURES.npz')
    for name in ('member', 'actor', 'label'):
        assert np.array_equal(values[name], original[name])
    x, y = values['V'], values['label']
    assert x.shape == (192, 3060) and np.isfinite(x).all() and np.bincount(y).tolist() == [96, 96]
    actors = [1, 3, 4, 5, 6, 7]
    assert sorted(set(values['actor'])) == actors
    old, oof = arrays(ORIGINAL / 'TRAIN_OOF.npz'), arrays(OUT / 'TRAIN_OOF.npz')
    assert np.array_equal(oof['probabilities'][:, [0, 2]], old['probabilities'][:, [0, 2]])
    for name in ('member', 'actor', 'label', 'y', 'weights', 'episode_actor', 'ordinal', 'commands'):
        assert np.array_equal(oof[name], old[name])
    predicted = np.full(192, np.nan)
    checked = []
    common.OUT = OUT  # The independent helper reads optimizer receipt files here.
    records = {r['tag']: r for r in training['fits']}
    assert set(records) == {'V/fold0', 'V/fold1', 'V/fold2', 'V/full', 'AVT'}
    for fold in range(3):
        held = np.isin(values['actor'], actors[fold::3])
        cp = arrays(OUT / f'V_fold{fold}.npz')
        assert records[f'V/fold{fold}']['C'] == .1
        checked.append(common.check_fit(cp, x[~held], y[~held], np.ones((~held).sum()), records[f'V/fold{fold}']))
        predicted[held] = probability(cp, x[held])
    checked.append(common.check_fit(arrays(OUT / 'V_classifier.npz'), x, y, np.ones(192), records['V/full']))
    error = float(np.max(np.abs(predicted - oof['probabilities'][:, 1])))
    assert error < 1e-14
    accuracy = float(np.mean((predicted >= .5) == y))
    assert accuracy == training['oof_video_accuracy']
    # Rebuild every actor/ordinal/command selection from the fixed clip registry.
    q = []
    for actor in actors:
        groups = {target: sorted([i for i, (a, label) in enumerate(zip(values['actor'], y)) if a == actor and label == target], key=lambda i: str(values['member'][i])) for target in (0, 1)}
        assert len(groups[0]) == len(groups[1]) == 16
        for ordinal in range(16):
            for command in itertools.product((0, 1), repeat=3):
                q.append([oof['probabilities'][groups[target][ordinal], column] for column, target in enumerate(command)])
    q = np.asarray(q)
    assert np.array_equal(q, oof['episode_probabilities'])
    assert np.array_equal(q[:, [0, 2]], old['episode_probabilities'][:, [0, 2]])
    features = np.column_stack([q[:, group].prod(1) for size in (1, 2, 3) for group in itertools.combinations(range(3), size)])
    assert records['AVT']['C'] == 1
    checked.append(common.check_fit(arrays(OUT / 'AVT_head.npz'), features, oof['y'], oof['weights'], records['AVT']))
    result = dict(schema='hcsn.grid-temporal.independent-candidate-audit.v1', candidate_sha256=sha(OUT / 'CANDIDATE_FREEZE.json'),
        source_freeze_sha256=sha(BASE / 'SOURCE_FREEZE.json'), feature_sha256=sha(directory / 'FEATURES.npz'),
        frozen_candidate_files_checked=len(candidate['files']), fits=checked, exact_primary_files_reused=9,
        primary_AT_OOF_columns_bit_identical=True, primary_prefix_metadata_bit_identical=True, registered_episode_pairing_exact=True,
        OOF_video_probability_max_error=error, oof_video_accuracy=accuracy, input_clips=192, episode_count=768,
        real_media_opened=False, neural_encoder_inference_performed=False, frozen_head_predictions_recomputed=True, fit_performed=False, all_blockers_closed=False,
        scope='Five fixed secondary fits audited before held quality. No primary replacement, outcome-driven selection, or remote publication verification claim.')
    target = HERE / 'REVIEW_GRID_TEMPORAL_CANDIDATE.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), fits_checked=len(checked), video_oof_accuracy=accuracy, exact_primary_files_reused=9), sort_keys=True))


if __name__ == '__main__':
    main()

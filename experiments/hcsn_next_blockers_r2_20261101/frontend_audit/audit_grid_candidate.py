"""Independently recompute all nine GRID OOF predictions and 14 fit records."""
import itertools
import json
from pathlib import Path

import numpy as np

from audit_audio_candidate import arrays, probability, read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GRID = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'
OUT = GRID / 'results/run001'


def check_fit(checkpoint, matrix, labels, weights, record):
    matrix = np.asarray(matrix, np.float64)
    mean, scale = matrix.mean(0), np.maximum(matrix.std(0), 1e-8)
    assert np.array_equal(mean, checkpoint['mean']) and np.array_equal(scale, checkpoint['scale'])
    standardized = (matrix - mean) / scale
    residual = weights * (probability(checkpoint, matrix) - labels)
    gradient = np.concatenate((standardized.T @ residual + checkpoint['beta'][:-1] / record['C'], [residual.sum()]))
    norm = float(np.max(np.abs(gradient)))
    assert abs(norm - record['gradient_inf']) < 1e-8
    assert record['success'] and record['status'] == 0
    assert record['rows'] == len(labels) and record['features'] == matrix.shape[1]
    assert read(OUT / ('optimizer_' + record['tag'].replace('/', '_') + '.json')) == record
    return dict(tag=record['tag'], C=record['C'], rows=len(labels), features=matrix.shape[1], fit_only_mean_scale_exact=True,
                gradient_inf_recomputed=norm, optimizer_success=True, optimizer_iterations=record['iterations'])


def main():
    candidate = read(OUT / 'CANDIDATE_FREEZE.json')
    source = read(GRID / 'MODEL_SOURCE_FREEZE.json')
    assert not candidate['development_loaded'] and not candidate['confirmation_loaded']
    assert candidate['model_source_freeze_sha256'] == sha(GRID / 'MODEL_SOURCE_FREEZE.json')
    assert candidate['source_freeze_sha256'] == sha(GRID / 'SOURCE_FREEZE_V2.json')
    assert candidate['protocol_sha256'] == sha(GRID / 'PROTOCOL.json') and candidate['cohort_sha256'] == sha(GRID / 'COHORT_SELECTION.json')
    assert candidate['source_files'] == source['files']
    for name, digest in source['files'].items():
        assert sha(GRID / name) == digest
    for name, digest in source['dependencies'].items():
        assert sha(ROOT / name) == digest
    for name, digest in candidate['files'].items():
        assert sha(OUT / name) == digest
    directory = GRID / candidate['feature_root']
    assert sha(directory / 'FEATURES.npz') == candidate['train_feature_sha256'] == source['train_feature_bank_sha256']
    assert sha(directory / 'IDENTITY.json') == source['train_feature_identity_sha256']
    identity = read(directory / 'IDENTITY.json')
    assert identity['role'] == 'train' and identity['features_sha256'] == sha(directory / 'FEATURES.npz')
    assert identity['model_source_freeze_sha256'] in source['admitted_feature_source_freezes']
    assert identity['acquisition_sha256'] == sha(GRID / 'inputs/TRAIN_ACQUISITION.json')
    values = arrays(directory / 'FEATURES.npz')
    rows = [r for r in read(GRID / 'COHORT_SELECTION.json')['entries'] if r['role'] == 'train']
    assert len(rows) == 192
    assert values['member'].tolist() == [r['name'] for r in rows]
    assert values['actor'].tolist() == [r['speaker'] for r in rows]
    assert values['label'].tolist() == [r['sentence_target'] for r in rows]
    assert np.bincount(values['label']).tolist() == [96, 96]
    for name, width in (('A', 1536), ('V', 1024), ('T', 26)):
        assert values[name].shape == (192, width) and np.isfinite(values[name]).all()
    for row, text in zip(rows, values['T']):
        word = 'bin' if row['sentence_target'] == 0 else 'set'
        assert row['command'] == word
        expected = np.zeros(26, np.float32)
        for letter in word:
            expected[ord(letter) - ord('a')] += 1 / len(word)
        assert np.array_equal(text, expected)
    acquisition = {(r['speaker'], r['member']): r for r in read(GRID / 'inputs/TRAIN_ACQUISITION.json')['records']}
    for row, detail in zip(rows, identity['details']):
        assert (detail['speaker'], detail['member']) == (row['speaker'], row['name'])
        assert detail['raw_sha256'] == acquisition[row['speaker'], row['name']]['sha256']
        assert len(detail['selected_timestamps']) == 25
        assert np.all(np.asarray(detail['selected_timestamps']) <= detail['origin'] + np.arange(1, 26) / 25)
        assert detail['accepted_end'] == detail['origin'] + 1 and detail['audio_samples'] == 16000
    training = read(OUT / 'TRAINING.json')
    assert not training['development_loaded'] and not training['confirmation_loaded'] and len(training['fits']) == 14 and len(training['folds']) == 9
    fit_records = {record['tag']: record for record in training['fits']}
    assert len(fit_records) == 14
    actors = sorted(set(values['actor']))
    assert actors == [1, 3, 4, 5, 6, 7]
    p = np.full((192, 3), np.nan)
    checked = []
    for column, name in enumerate(('A', 'V', 'T')):
        for fold in range(3):
            held_actors = set(actors[fold::3])
            held = np.array([actor in held_actors for actor in values['actor']])
            row = next(r for r in training['folds'] if r['modality'] == name and r['fold'] == fold)
            assert set(row['held_actors']) == held_actors and set(row['fit_actors']) == set(actors) - held_actors
            assert len(row['fit_actors']) == 4 and len(row['held_actors']) == 2
            checkpoint = arrays(OUT / row['checkpoint'])
            record = fit_records[f'{name}/fold{fold}']
            assert record['C'] == .1
            checked.append(check_fit(checkpoint, values[name][~held], values['label'][~held], np.ones((~held).sum()), record))
            p[held, column] = probability(checkpoint, values[name][held])
        assert fit_records[f'{name}/full']['C'] == .1
        checked.append(check_fit(arrays(OUT / f'{name}_classifier.npz'), values[name], values['label'], np.ones(192), fit_records[f'{name}/full']))
        assert np.mean((p[:, column] >= .5) == values['label']) == training['oof_accuracy'][name]
    oof = arrays(OUT / 'TRAIN_OOF.npz')
    error = float(np.max(np.abs(p - oof['probabilities'])))
    assert error < 1e-14
    # Preserve the exact stored floating representation for checking relation
    # fit statistics after independently bounding every reconstructed OOF value.
    p = oof['probabilities'].copy()
    # Independently enumerate each actor's16 lexicographic bin/set pairs and all
    # eight command combinations, without calling the scientific episode code.
    q, y, weights, episode_actors, orders, commands = [], [], [], [], [], []
    for actor in actors:
        chosen = {target: sorted([i for i, (a, label) in enumerate(zip(values['actor'], values['label'])) if a == actor and label == target], key=lambda i: str(values['member'][i])) for target in (0, 1)}
        assert len(chosen[0]) == len(chosen[1]) == 16
        for ordinal in range(16):
            for command in itertools.product((0, 1), repeat=3):
                q.append([p[chosen[target][ordinal], column] for column, target in enumerate(command)])
                equal = int(len(set(command)) == 1)
                y.append(equal)
                weights.append(3 if equal else 1)
                episode_actors.append(actor)
                orders.append(ordinal)
                commands.append(command)
    q, y, weights = np.asarray(q), np.asarray(y), np.asarray(weights, np.float64)
    assert q.shape == (768, 3) and np.bincount(y).tolist() == [576, 192]
    assert np.max(np.abs(q - oof['episode_probabilities'])) < 1e-14
    for name, expected in (('y', y), ('weights', weights), ('episode_actor', episode_actors), ('ordinal', orders), ('commands', commands)):
        assert np.array_equal(oof[name], expected)
    for name in ('AT', 'AVT'):
        x = np.column_stack((q[:, 0], q[:, 2], q[:, 0] * q[:, 2])) if name == 'AT' else np.column_stack([q[:, group].prod(1) for size in (1, 2, 3) for group in itertools.combinations(range(3), size)])
        assert fit_records[name]['C'] == 1
        checked.append(check_fit(arrays(OUT / f'{name}_head.npz'), x, y, weights, fit_records[name]))
    result = dict(schema='hcsn.grid.independent-candidate-numerical-audit.v1', candidate_sha256=sha(OUT / 'CANDIDATE_FREEZE.json'),
        model_source_freeze_sha256=sha(GRID / 'MODEL_SOURCE_FREEZE.json'), feature_sha256=sha(directory / 'FEATURES.npz'),
        frozen_candidate_files_checked=len(candidate['files']), fits=checked, actor_folds_verified=9, OOF_probability_max_error=error,
        oof_accuracy=training['oof_accuracy'], clips=192, episode_count=768, exact_registered_command_pairing=True,
        held_media_decoded=False, real_media_opened=False, model_inference_performed=False, fit_performed=False, all_blockers_closed=False,
        scope='Cached-feature and frozen-fit audit. Registered training group only; no development/confirmation quality claim and no remote publication verification.')
    target = HERE / 'REVIEW_GRID_CANDIDATE.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), fits_checked=len(checked), OOF_probability_max_error=error, oof_accuracy=training['oof_accuracy']), sort_keys=True))


if __name__ == '__main__':
    main()

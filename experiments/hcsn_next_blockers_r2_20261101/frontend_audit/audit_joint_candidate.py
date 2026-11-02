"""Independent joint frozen-OOF mapping and two-head numerical audit."""
import itertools
import json
from pathlib import Path

import numpy as np

from audit_audio_candidate import arrays, check_fit, probability, read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JOINT = ROOT / 'experiments/hcsn_joint_pretrained_av_r2_20261101'
OUT = JOINT / 'results/run001'
AUDIO = ROOT / 'experiments/hcsn_audio_pretrained_r2_20261101/results/run001'
VIDEO = ROOT / 'experiments/hcsn_video_pretrained_feasibility_r2_20261101/results/run001'
R1 = ROOT / 'experiments/hcsn_video_followup_20261101'


def main():
    source = read(JOINT / 'SOURCE_FREEZE.json')
    candidate = read(OUT / 'CANDIDATE_FREEZE.json')
    assert not source['development_loaded'] and not candidate['development_loaded']
    assert candidate['source_freeze_sha256'] == sha(JOINT / 'SOURCE_FREEZE.json')
    assert candidate['dependencies'] == source['dependencies']
    for relative, expected in {**source['source'], **source['dependencies']}.items():
        assert sha(ROOT / relative) == expected
    for name, expected in candidate['files'].items():
        assert sha(OUT / name) == expected
    a, v = arrays(AUDIO / 'TRAIN_OOF.npz'), arrays(VIDEO / 'TRAIN_OOF.npz')
    cohorts = read(ROOT / 'experiments/hcsn_audio_pretrained_r2_20261101/TRAIN_COHORT.json')['records']
    wanted = {row['clip'] for row in cohorts}
    for provider in (a, v):
        assert len(provider['clip']) == len(set(provider['clip'])) == 288
        assert set(provider['clip']) == wanted
        assert provider['actor'].tolist() == [str(c).split('_')[0] for c in provider['clip']]
        assert provider['label'].tolist() == [int(str(c).split('_')[1] == 'IOM') for c in provider['clip']]
    af, vf = read(AUDIO / 'TRAINING.json')['folds'], read(VIDEO / 'TRAINING.json')['folds']
    assert len(af) == len(vf) == 4
    actors = sorted(set(a['actor']))
    for fold, (left, right) in enumerate(zip(af, vf)):
        for key in ('fold', 'fit_actors', 'held_actors'):
            assert left[key] == right[key]
        assert left['held_actors'] == actors[fold::4]
        assert set(left['fit_actors']) == set(actors) - set(left['held_actors'])
    episodes = arrays(R1 / 'inputs/data/train.npz')
    old = arrays(R1 / 'results/run002/TRAIN_OOF.npz')
    am = dict(zip(a['clip'], a['audio']))
    vm = dict(zip(v['clip'], v['video']))
    expected = np.array([[am[f"{actor}_{('DFA','IOM')[s[0]]}_{emotion}_XX"], vm[f"{actor}_{('DFA','IOM')[s[1]]}_{emotion}_XX"], text]
        for actor, emotion, s, text in zip(episodes['actor'], episodes['emotion'], episodes['sentence_indices'], old['probabilities'][:, 2])])
    oof = arrays(OUT / 'TRAIN_OOF.npz')
    assert np.array_equal(oof['probabilities'], expected)
    for name in ('actor', 'y', 'sample_weight', 'sentence_indices'):
        assert np.array_equal(oof[name], episodes[name])
    commands = episodes['sentence_indices']
    assert np.array_equal(episodes['y'], (commands[:, 0] == commands[:, 1]) & (commands[:, 1] == commands[:, 2]))
    training = read(OUT / 'TRAINING.json')
    assert not training['development_loaded'] and not training['new_provider_fitting'] and len(training['fits']) == 2
    assert training['audio_candidate_sha256'] == source['audio_candidate_sha256'] == sha(AUDIO / 'CANDIDATE_FREEZE.json')
    assert training['video_candidate_sha256'] == source['video_candidate_sha256'] == sha(VIDEO / 'CANDIDATE_FREEZE.json')
    checked = []
    training_metrics = {}
    p, y, weights = expected, episodes['y'], episodes['sample_weight']
    for i, name in enumerate(('AT_unique', 'AVT')):
        x = np.column_stack((p[:, 0], p[:, 2], p[:, 0] * p[:, 2])) if name == 'AT_unique' else np.column_stack([p[:, group].prod(1) for size in (1, 2, 3) for group in itertools.combinations(range(3), size)])
        checkpoint = arrays(OUT / f'{name}_head.npz')
        checked.append(check_fit(checkpoint, x, y, weights, training['fits'][i]))
        scores = probability(checkpoint, x)
        training_metrics[name] = dict(accuracy=float(np.average((scores >= .5) == y, weights=weights)), brier=float(np.average((scores - y) ** 2, weights=weights)))
    audio_baseline, joint_baseline = arrays(AUDIO / 'AT_unique_head.npz'), arrays(OUT / 'AT_unique_head.npz')
    assert all(np.array_equal(audio_baseline[name], joint_baseline[name]) for name in ('mean', 'scale', 'beta'))
    result = dict(schema='hcsn.joint-pretrained.independent-candidate-audit.v1', candidate_sha256=sha(OUT / 'CANDIDATE_FREEZE.json'),
        source_freeze_sha256=sha(JOINT / 'SOURCE_FREEZE.json'), frozen_candidate_files_checked=len(candidate['files']),
        fits=checked, training_metrics=training_metrics, exact_provider_clip_maps=True, provider_common_actor_folds_verified=4,
        inherited_text_bit_identical=True, clean_AT_head_bit_identical_to_audio_candidate=True, episodes=1152,
        held_media_decoded=False, real_media_opened=False, fit_performed=False, all_blockers_closed=False,
        scope='Local independent numerical audit of fixed two-head candidate; training scores are diagnostics, not development evidence. Remote publication readback is separate parent gate.')
    target = HERE / 'REVIEW_JOINT_CANDIDATE.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), fit_count=len(checked), mapping_exact=True, clean_AT_head_bit_identical=True), sort_keys=True))


if __name__ == '__main__':
    main()

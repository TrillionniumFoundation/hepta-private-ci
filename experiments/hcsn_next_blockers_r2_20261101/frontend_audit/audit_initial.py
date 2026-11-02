"""Independent record/metadata audit; never decode or fit held-out media."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def main():
    previous = ROOT / 'experiments/hcsn_video_followup_20261101'
    visual = ROOT / 'experiments/hcsn_video_pretrained_feasibility_r2_20261101'
    grid = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'
    cohort = read(ROOT / 'experiments/hcsn_four_stage_flow_20261031/data/COHORT.json')
    rows = sorted([r for r in cohort['records'] if r['split'] == 'train'], key=lambda r: r['clip'])
    train_actors = sorted({r['actor'] for r in rows})
    held_actors = sorted({r['actor'] for r in cohort['records'] if r['split'] == 'validation'})
    assert len(rows) == 288 and len(train_actors) == 24 and len(held_actors) == 6
    assert set(train_actors).isdisjoint(held_actors)
    binary = [int(r['sentence'] == 'IOM') for r in rows]
    assert all(r['sentence'] in ('DFA', 'IOM') for r in rows)
    assert binary.count(0) == binary.count(1) == 144
    training = read(previous / 'results/run002/TRAINING.json')
    freeze = read(previous / 'results/run002/CANDIDATE_FREEZE.json')
    assert freeze['training_sha256'] == digest(previous / 'results/run002/TRAINING.json')
    assert freeze['input_identity_sha256'] == digest(previous / 'INPUT_IDENTITY.json')
    assert not freeze['validation_loaded'] and not training['validation_loaded']
    for name, expected in freeze['checkpoints'].items():
        assert digest(previous / 'results/run002' / name) == expected
    outer = []
    for modality in ('audio', 'text'):
        seen = []
        for row in training['selected'][modality]['outer']:
            fit, held = set(row['fit_actors']), set(row['held_actors'])
            assert len(fit) == 18 and len(held) == 6 and fit.isdisjoint(held)
            assert fit | held == set(train_actors)
            assert list(row['held_actors']) == train_actors[row['fold']::4]
            assert fit.isdisjoint(held_actors) and held.isdisjoint(held_actors)
            seen.extend(held)
            outer.append(dict(modality=modality, fold=row['fold'], fit_count=len(fit), held_count=len(held)))
        assert sorted(seen) == train_actors
    with np.load(previous / 'results/run002/TRAIN_OOF.npz', allow_pickle=False) as z:
        oof = {k: z[k] for k in z.files}
    with np.load(previous / 'inputs/data/train.npz', allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    for key in ('actor', 'y', 'sentence_indices'):
        assert np.array_equal(oof[key], arrays[key])
    assert np.array_equal(arrays['y'], np.all(arrays['sentence_indices'] == arrays['sentence_indices'][:, :1], axis=1))
    assert np.isfinite(oof['probabilities']).all()
    assert ((oof['probabilities'] >= 0) & (oof['probabilities'] <= 1)).all()
    consistency_counts = {}
    for mi, modality in [(0, 'audio'), (2, 'text')]:
        keys = {}
        for actor, emotion, sentences, score in zip(arrays['actor'], arrays['emotion'], arrays['sentence_indices'], oof['probabilities'][:, mi]):
            key = (str(actor), str(emotion), int(sentences[mi]))
            if key in keys:
                assert keys[key] == float(score)
            keys[key] = float(score)
        assert len(keys) == 288
        consistency_counts[modality] = len(keys)
    # The failure ordinal is an independent metadata probe of training only.
    failed_row = rows[144]
    assert failed_row['clip'] == '1037_DFA_ANG_XX'
    media = ROOT.parent / 'video_raw_r2_media' / (failed_row['clip'] + '.flv')
    assert media.stat().st_size == failed_row['bytes'] and digest(media) == failed_row['sha256']
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_packets', '-show_frames', '-show_entries',
        'stream=codec_type,codec_name,has_b_frames,start_time:packet=stream_index,pts_time,dts_time,pos:frame=media_type,pts_time,best_effort_timestamp_time,pkt_pos,pict_type', '-of', 'json', str(media)]))
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    frames = [f for f in probe['packets_and_frames'] if f['type'] == 'frame' and f.get('media_type') == 'video']
    origin = max(float(audio['start_time']), float(frames[0]['best_effort_timestamp_time']))
    times = np.array([float(f['best_effort_timestamp_time']) for f in frames])
    cutoffs = origin + np.arange(1, 26) / 25
    selected = np.searchsorted(times, cutoffs, side='right') - 1
    examples = []
    for cutoff, i in zip(cutoffs, selected):
        frame = frames[int(i)]
        if frame['pict_type'] == 'B':
            examples.append(dict(cutoff=float(cutoff), selected_pts=float(times[i]), pict_type='B', packet_position=int(frame['pkt_pos'])))
    assert video['codec_name'] == 'h264' and video['has_b_frames'] == 2 and examples
    # Parse the complete reviewed source and record identities; the semantic
    # boundary findings below are manual code-review conclusions, not AST proof.
    files = [visual / n for n in ('encoder.py', 'study.py', 'PROTOCOL.json', 'SOURCE_FREEZE.json')]
    files += [grid / n for n in ('data.py', 'PROTOCOL.json', 'COHORT_SELECTION.json', 'SOURCE_FREEZE.json')]
    for path in files:
        if path.suffix == '.py':
            ast.parse(path.read_text())
    selection = read(grid / 'COHORT_SELECTION.json')
    entries = selection['entries']
    assert len(entries) == 384
    role_speakers = {role: sorted({r['speaker'] for r in entries if r['role'] == role}) for role in ('train', 'development', 'confirmation')}
    assert role_speakers == {'train': [1, 3, 4, 5, 6, 7], 'development': [8, 9], 'confirmation': [10, 11, 12, 13]}
    assert len({(r['speaker'], r['name']) for r in entries}) == 384
    assert sum(r['bytes'] for r in entries) == selection['raw_uncompressed_bytes'] < 170000000
    assert all(r['sentence_target'] == (0 if Path(r['name']).name.startswith('b') else 1) for r in entries)
    result = dict(schema='hcsn.frontend.independent-initial-audit.v1',
        source_files={str(p.relative_to(ROOT)): digest(p) for p in files},
        passed=dict(train_clips=288, training_actor_count=24, historical_development_actor_count=6, binary_target_counts={'DFA': 144, 'IOM': 144},
            inherited_outer_folds=outer, inherited_unique_probability_mappings=consistency_counts, inherited_oof_rows=len(oof['y']),
            inherited_checkpoints_bound=True, grid_selected_count=384, grid_raw_bytes=selection['raw_uncompressed_bytes'], grid_role_speakers=role_speakers),
        training_decoder_failure=dict(ordinal_zero_based=144, clip=failed_row['clip'], codec=video['codec_name'], has_b_frames=video['has_b_frames'], origin=origin, selected_B_frame_examples=examples[:5]),
        review_findings=[
            'Original no-B-frame extraction failure correctly enforced its original frozen protocol; its archived source/protocol and failed extraction are preserved. The repaired snapshot explicitly broadens to offline presentation-prefix decoding before any target fit.',
            'Presentation-timestamp selected pixels support an offline presentation-prefix task. B-frame references/reordering do not establish live causal physical-prefix availability; no strict streaming 1s claim follows.',
            'Visual encoder receives only the 25 cropped grayscale frames. Binary sentence labels train supervised heads; filenames and actor IDs route verified records and split folds, and are not numeric head features.',
            'Inherited audio/text OOF generation selects hyperparameters inside outer training actors, normalizes on each fit subset, and predicts outer-held actors. The new visual train fold uses the same actor partition. Pretraining actor overlap remains unknown.',
            'GRID uses native timestamp prefix selection and crops audio before resampling; complete offline decoding cost is explicit. It does not qualify online streaming latency.',
            'GRID acquisition namespacing, CRC/length checks, and legacy-speaker1 SHA check are coherent. Confirmation acquisition guard validates candidate/source/head hashes. At this snapshot prefix(row) has no role guard itself, and new cache use is not bound to acquisition-receipt SHA. Campaign must enforce verified manifest and confirmation guard before invoking prefix.'
        ], held_media_decoded=False, fit_performed=False, all_blockers_closed=False)
    target = HERE / 'REVIEW_INITIAL.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(result=str(target.relative_to(ROOT)), sha256=digest(target), passed=result['passed']), sort_keys=True))


if __name__ == '__main__':
    main()

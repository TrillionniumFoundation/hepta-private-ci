"""Generate, persist and independently score all five causal H1 actions."""

import argparse
import gzip
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.runtime import ACTIONS, initialize, public_digest, public_frame, transition
from ...abc_followup.native.forecast import Q
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ..sources import load_registered
from .common import AREA, ASSETS, MODEL, OBSERVER, sha, write
from .encoder import PublicEncoder
from .qualification import probabilities


ID_VIEWS = ('clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted')


def collect(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(args.protocol.read_text())
    for path, expected in protocol['frozen_candidate_sha256'].items():
        if sha(path) != expected:
            raise ValueError('Frozen qualification dependency changed: ' + path)
    predictor = json.loads(args.predictor.read_text())
    if protocol['predictor_sha256'] != sha(args.predictor):
        raise ValueError('Unregistered admission predictor')
    registration = {'schema': 'hepta.next.native-admission-access.v1',
                    'protocol_sha256': sha(args.protocol), 'study': args.study,
                    'registered_unix_ns': time.time_ns(), 'formal_sources_opened_once': True}
    write(output / 'access-registration.json', registration)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    if args.study == 'native_calibration':
        corpus = load_registered(args.cache, args.allocation, args.protocol, study=args.study)
    else:
        from ..xnist_sources import load_registered as load_qualification
        corpus = load_qualification(args.cache, args.allocation, args.protocol)
    role = 'next_' + args.study
    count = len(corpus.splits[role].ids) // 2
    if count != protocol['pair_count']:
        raise ValueError('Incorrect source count')
    generator = Snapshot.load(MODEL, expected_file_sha256=sha(MODEL))._model
    observer, _ = load_reward(OBSERVER, sha(OBSERVER))
    encoder = PublicEncoder()
    rows = []
    arrays = {k: [] for k in ('raw_probability', 'y', 'absent', 'writer', 'pair', 'action', 'utility', 'hidden')}
    commit_dir = output / 'commits'; commit_dir.mkdir()
    for case in range(count):
        views = (*ID_VIEWS, 'both_missing') if args.study == 'native_calibration' else (ID_VIEWS[case % 5], 'both_missing')
        for view_index, view in enumerate(views):
            for future_index in range(2 if args.study == 'native_calibration' else 1):
                seed = 7350017 + case * 1009 + ID_VIEWS.index(view) * 100000 if view != 'both_missing' else 8350017 + case * 1009
                seed += future_index * 10000000
                batch = make_batch(corpus, role, 1, seed, view=view, offset=case)
                writer = int(batch.source_ids[0][0].split(':writer:')[1].split(':')[0])
                with torch.inference_mode():
                    rng = torch.Generator().manual_seed(seed + 1000000)
                    prefix = initialize(generator, batch.observation, generator=rng)
                    prefix = transition(generator, prefix, 'refine_image', generator=rng)
                    frame = public_frame(prefix)
                    inputs, moments, work, hidden = encoder.encode(generator, frame, batch.observation)
                    hidden_q = np.asarray(inputs[0][478:510], dtype=np.float64) / Q
                    raw = probabilities(predictor, hidden_q)
                    x = inputs[0]
                    absent = x[448] == 0 and x[449] == 0 and x[460] == Q and x[471] == Q
                    if absent != (view == 'both_missing'):
                        raise ValueError('Public absence detector differs from declared view')
                    tag = f'{case:04d}-{view}-{future_index}'
                    commit = {'pair': case, 'view': view, 'future': future_index, 'public_digest': public_digest(frame),
                              'public_features_q24': inputs[0], 'raw_probability': raw.tolist(),
                              'ndu_moments': moments.tolist(), 'public_absent': absent,
                              'feature_work': work, 'committed_ns': time.time_ns()}
                    commit_path = commit_dir / (tag + '.json')
                    write(commit_path, commit)
                    for action_index, action in enumerate(ACTIONS):
                        started = time.time_ns()
                        future = transition(generator, prefix, action,
                                            generator=torch.Generator().manual_seed(seed + 2000000 + action_index * 3000000))
                        media = write_bundle(output / 'media' / f'{tag}-{action}', render_tokens(future.tokens[0]), future.pixels[0])
                        reopened, caption, hashes = read_bundle(media)
                        if not torch.equal(reopened[0], future.pixels[0]) or caption != render_tokens(future.tokens[0]):
                            raise ValueError('Actual decoded output mismatch')
                        score = observe_tensors(observer, reopened, [caption], batch.target.pixels, batch.target.labels)[0]
                        correct = int(score['caption_valid'] and all(score[k] == 0 for k in
                                      ('text_fact', 'relation', 'image_fact', 'crossmodal_disagreement')))
                        row = {'pair': case, 'writer': writer, 'source_ids': batch.source_ids[0], 'view': view,
                               'future': future_index, 'action': action, 'actual_media': media, 'media_sha256': hashes,
                               'score': score, 'correct': correct, 'commit_sha256': sha(commit_path),
                               'committed_ns': commit['committed_ns'], 'generation_started_ns': started,
                               'observed_ns': time.time_ns(), 'future_used_for_predicting': False}
                        rows.append(row)
                        for key, value in (('raw_probability', raw[action_index]), ('y', correct), ('absent', absent),
                                           ('writer', writer), ('pair', case), ('action', action_index),
                                           ('utility', score['utility']), ('hidden', hidden_q)):
                            arrays[key].append(value)
        if (case + 1) % 16 == 0:
            print(json.dumps({'study': args.study, 'completed_pairs': case + 1, 'outputs': len(rows)}), flush=True)
    np.savez_compressed(output / 'data.npz', **{k: np.asarray(v) for k, v in arrays.items()})
    with gzip.open(output / 'rows.jsonl.gz', 'wt') as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
    write(output / 'results.json', {'schema': 'hepta.next.native-admission-collection.v1',
          'study': args.study, 'source_pairs': count, 'independent_writers': len(set(arrays['writer'])),
          'actual_outputs': len(rows), 'actual_files': len(rows) * 2,
          'all_predictions_precede_actual_generation': all(r['committed_ns'] < r['generation_started_ns'] < r['observed_ns'] for r in rows),
          'data_sha256': sha(output / 'data.npz'), 'rows_sha256': sha(output / 'rows.jsonl.gz'),
          'registration_sha256': sha(output / 'access-registration.json'),
          'wall_ns': time.perf_counter_ns() - began, 'cpu_ns': time.process_time_ns() - cpu,
          'cost_scope': 'after registration through model load/source access/encoding/all actual generations/readback/scoring/persistence',
          'source_output_post_selection': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', choices=('native_calibration', 'native_qualification'), required=True)
    for name in ('cache', 'allocation', 'protocol', 'predictor', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    collect(parser.parse_args())

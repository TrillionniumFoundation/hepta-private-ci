"""Prospective actual-output census for root H2 and all four reachable H1 states."""

import argparse
import gzip
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, public_digest, public_frame, transition
from ...abc_followup.native.forecast import Q
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ..h2_sources import load_registered
from .common import MODEL, OBSERVER, sha, write
from .encoder import PublicEncoder
from .qualification import ACTIONS, ID_VIEWS, probabilities


def collect(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(args.protocol.read_text())
    for path, expected in protocol['frozen_candidate_sha256'].items():
        if sha(path) != expected:
            raise ValueError('Frozen H2 qualification dependency changed: ' + path)
    predictor = json.loads(args.predictor.read_text())
    development = json.loads(args.development.read_text())
    if (protocol['predictor_sha256'] != sha(args.predictor)
            or protocol['development_sha256'] != sha(args.development)
            or development['new_source_candidate_admitted'] is not True
            or development['predictor_sha256'] != sha(args.predictor)
            or protocol['frozen_candidate_sha256'].get(str(args.predictor.resolve())) != sha(args.predictor)
            or protocol['frozen_candidate_sha256'].get(str(args.development.resolve())) != sha(args.development)):
        raise ValueError('Old development feasibility and exact candidate required before new source access')
    write(output / 'access-registration.json', {'schema': 'hepta.next.native-h2-admission-access.v1',
          'protocol_path': str(args.protocol.resolve()), 'protocol_sha256': sha(args.protocol),
          'study': args.study, 'registered_unix_ns': time.time_ns(), 'source_allocation_sha256': sha(args.allocation),
          'predictor_path': str(args.predictor.resolve()), 'predictor_sha256': sha(args.predictor),
          'formal_sources_opened_once': True})
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    corpus, allocation = load_registered(args.cache, args.allocation, args.protocol, study=args.study)
    suffix = args.study.removeprefix('native_h2_')
    role = 'next_native_h2_' + suffix
    count = len(corpus.splits[role].ids) // 2
    if count != protocol['pair_count'] or count != (100 if suffix == 'calibration' else 1000):
        raise ValueError('Wrong prospectively fixed cohort size')
    generator = Snapshot.load(MODEL, expected_file_sha256=sha(MODEL))._model
    observer, _ = load_reward(OBSERVER, sha(OBSERVER))
    encoder = PublicEncoder(args.predictor)
    arrays = {k: [] for k in ('raw_probability', 'y', 'absent', 'writer', 'pair', 'action',
                             'horizon', 'node', 'group', 'utility', 'moments', 'source_ids')}
    commit_dir = output / 'commits'; commit_dir.mkdir()
    outputs, group = 0, 0
    with gzip.open(output / 'rows.jsonl.gz', 'xt') as journal:
        for case in range(count):
            views = (*ID_VIEWS, 'both_missing') if suffix == 'calibration' else (ID_VIEWS[case % 5], 'both_missing')
            for view in views:
                for future_index in range(2 if suffix == 'calibration' else 1):
                    view_index = (*ID_VIEWS, 'both_missing').index(view)
                    seed = 73110017 + case * 1009 + view_index * 1000000 + future_index * 10000000
                    batch = make_batch(corpus, role, 1, seed, view=view, offset=case)
                    writer = allocation['roles'][suffix]['pair_writer_ids'][case]
                    expected_ids = [row['source_id'] for row in allocation['roles'][suffix]['source_records'][2 * case:2 * case + 2]]
                    if list(batch.source_ids[0]) != expected_ids:
                        raise ValueError('Actual request is not the registered source pair')
                    with torch.inference_mode():
                        root = initialize(generator, batch.observation, generator=torch.Generator().manual_seed(seed + 100000))
                        nodes = {0: root}
                        for node in range(5):
                            prefix = nodes[node]
                            frame = public_frame(prefix)
                            inputs, moments, work, hidden = encoder.encode(generator, frame, batch.observation)
                            raw = probabilities(predictor, hidden, frame.remaining)
                            x = inputs[0]
                            absent = x[0] == 0 and x[1] == 0 and x[2] == Q and x[3] == Q
                            if absent != (view == 'both_missing'):
                                raise ValueError('Public absence detector differs from registered diagnostic view')
                            tag = f'{case:04d}-{view}-{future_index}-node{node}'
                            commit = {'pair': case, 'view': view, 'future': future_index, 'node': node,
                                      'public_digest': public_digest(frame), 'public_features_q24': x,
                                      'raw_probability': raw.tolist(), 'ndu_moments': moments.tolist(),
                                      'public_absent': absent, 'feature_work': work,
                                      'remaining': frame.remaining, 'committed_ns': time.time_ns()}
                            commit_path = commit_dir / (tag + '.json'); write(commit_path, commit)
                            for action_index, action in enumerate(ACTIONS):
                                started = time.time_ns()
                                future = transition(generator, prefix, action, generator=torch.Generator().manual_seed(
                                    seed + 2000000 + (5 * node + action_index) * 3000000))
                                if node == 0 and action_index:
                                    nodes[action_index] = future
                                media = write_bundle(output / 'media' / f'{tag}-{action}', render_tokens(future.tokens[0]), future.pixels[0])
                                reopened, caption, hashes = read_bundle(media)
                                if not torch.equal(reopened[0], future.pixels[0]) or caption != render_tokens(future.tokens[0]):
                                    raise ValueError('Actual decoded output mismatch')
                                score = observe_tensors(observer, reopened, [caption], batch.target.pixels, batch.target.labels)[0]
                                correct = int(score['caption_valid'] and all(score[k] == 0 for k in
                                              ('text_fact', 'relation', 'image_fact', 'crossmodal_disagreement')))
                                row = {'pair': case, 'writer': writer, 'source_ids': batch.source_ids[0], 'view': view,
                                       'future': future_index, 'node': node, 'horizon': frame.remaining,
                                       'action': action, 'actual_media': media, 'media_sha256': hashes,
                                       'score': score, 'correct': correct, 'commit_sha256': sha(commit_path),
                                       'committed_ns': commit['committed_ns'], 'generation_started_ns': started,
                                       'observed_ns': time.time_ns(), 'future_used_for_predicting': False}
                                if not row['committed_ns'] < started < row['observed_ns']:
                                    raise ValueError('Pre-innovation commitment order invalid')
                                journal.write(json.dumps(row, sort_keys=True) + '\n')
                                values = {'raw_probability': raw[action_index], 'y': correct, 'absent': absent,
                                          'writer': writer, 'pair': case, 'action': action_index, 'horizon': frame.remaining,
                                          'node': node, 'group': group, 'utility': score['utility'], 'moments': moments,
                                          'source_ids': batch.source_ids[0]}
                                for key, value in values.items(): arrays[key].append(value)
                                outputs += 1
                    group += 1
            if (case + 1) % 16 == 0:
                print(json.dumps({'study': args.study, 'completed_pairs': case + 1, 'outputs': outputs}), flush=True)
    expected_outputs = 30000 if suffix == 'calibration' else 50000
    if outputs != expected_outputs or any(sha(path) != expected for path, expected in protocol['frozen_candidate_sha256'].items()):
        raise ValueError('Incomplete census or candidate identity changed')
    np.savez_compressed(output / 'data.npz', **{k: np.asarray(v) for k, v in arrays.items()})
    write(output / 'results.json', {'schema': 'hepta.next.native-h2-admission-collection.v1',
          'study': args.study, 'source_pairs': count, 'independent_writers': len(set(arrays['writer'])),
          'actual_outputs': outputs, 'actual_files': outputs * 2, 'all_five_decision_states': True,
          'all_predictions_precede_actual_generation': True,
          'data_sha256': sha(output / 'data.npz'), 'rows_sha256': sha(output / 'rows.jsonl.gz'),
          'registration_sha256': sha(output / 'access-registration.json'),
          'wall_ns': time.perf_counter_ns() - began, 'cpu_ns': time.process_time_ns() - cpu,
          'cost_scope': 'after registration through model load/source access/encoding/all generations/readback/scoring/persistence',
          'source_output_post_selection': False, 'population_ECE_bound_claimed': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', choices=('native_h2_calibration', 'native_h2_qualification'), required=True)
    for name in ('cache', 'allocation', 'protocol', 'predictor', 'development', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    collect(parser.parse_args())

"""Fixed larger historical calibration/held-stage; no new XNIST source access."""

import argparse
import gzip
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, public_frame, public_digest, transition
from ...abc_followup.native.forecast import Q
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .common import MODEL, OBSERVER, SHARED, sha, write
from .encoder import PublicEncoder
from .old_sources import MANIFEST, MANIFEST_SHA, PREDICTOR_SHA
from .qualification import ACTIONS, ID_VIEWS, probabilities, fit_calibration, statistics
from .prospective import selected


def census(corpus, generator, observer, encoder, predictor, phase, phase_index, entries, output):
    output.mkdir(parents=True, exist_ok=False)
    arrays = {k: [] for k in ('raw_probability', 'y', 'absent', 'writer', 'pair', 'action',
                             'horizon', 'node', 'group', 'utility', 'moments', 'source_ids')}
    commits = output / 'commits'; commits.mkdir()
    with gzip.open(output / 'rows.jsonl.gz', 'xt') as journal:
        for index, entry in enumerate(entries):
            case = entry['pair_index']
            for view_index, view in enumerate((ID_VIEWS[index % 5], 'both_missing')):
                seed = 74120017 + phase_index * 10000000 + index * 1009 + view_index * 1000000
                batch = make_batch(corpus, 'forecast_calibration', 1, seed, view=view, offset=case)
                if list(batch.source_ids[0]) != entry['source_ids']:
                    raise ValueError('Actual old request is not the fixed registered source pair')
                with torch.inference_mode():
                    root = initialize(generator, batch.observation, generator=torch.Generator().manual_seed(seed + 100000))
                    nodes = {0: root}
                    for node in range(5):
                        prefix = nodes[node]; frame = public_frame(prefix)
                        inputs, moments, work, hidden = encoder.encode(generator, frame, batch.observation)
                        raw = probabilities(predictor, hidden, frame.remaining)
                        x = inputs[0]; absent = x[0] == 0 and x[1] == 0 and x[2] == Q and x[3] == Q
                        if absent != (view == 'both_missing'): raise ValueError('Public absence detector changed')
                        tag = f'{index:04d}-source{case}-{view}-node{node}'
                        commit = {'source_pair': case, 'phase': phase, 'view': view, 'node': node,
                                  'public_digest': public_digest(frame), 'public_features_q24': x,
                                  'raw_probability': raw.tolist(), 'ndu_moments': moments.tolist(),
                                  'public_absent': absent, 'feature_work': work,
                                  'remaining': frame.remaining, 'committed_ns': time.time_ns()}
                        commit_path = commits / (tag + '.json'); write(commit_path, commit)
                        for a, action in enumerate(ACTIONS):
                            began = time.time_ns()
                            future = transition(generator, prefix, action, generator=torch.Generator().manual_seed(
                                seed + 2000000 + (5 * node + a) * 3000000))
                            if node == 0 and a: nodes[a] = future
                            media = write_bundle(output / 'media' / f'{tag}-{action}', render_tokens(future.tokens[0]), future.pixels[0])
                            reopened, caption, hashes = read_bundle(media)
                            if not torch.equal(reopened[0], future.pixels[0]) or caption != render_tokens(future.tokens[0]):
                                raise ValueError('Actual old-development output failed round trip')
                            score = observe_tensors(observer, reopened, [caption], batch.target.pixels, batch.target.labels)[0]
                            correct = int(score['caption_valid'] and all(score[k] == 0 for k in
                                          ('text_fact', 'relation', 'image_fact', 'crossmodal_disagreement')))
                            row = {'source_pair': case, 'phase': phase, 'view': view, 'node': node,
                                   'source_ids': batch.source_ids[0], 'action': action, 'horizon': frame.remaining,
                                   'actual_media': media, 'media_sha256': hashes, 'score': score, 'correct': correct,
                                   'commit_sha256': sha(commit_path), 'committed_ns': commit['committed_ns'],
                                   'generation_started_ns': began, 'observed_ns': time.time_ns(),
                                   'future_used_for_predicting': False, 'new_source_role': False}
                            if not row['committed_ns'] < began < row['observed_ns']: raise ValueError('Causal commit violated')
                            journal.write(json.dumps(row, sort_keys=True) + '\n')
                            # The legacy array key writer is a source-pair cluster here;
                            # every statistic is explicitly called with writer_bound=False.
                            values = {'raw_probability': raw[a], 'y': correct, 'absent': absent, 'writer': case,
                                      'pair': case, 'action': a, 'horizon': frame.remaining, 'node': node,
                                      'group': index * 2 + view_index, 'utility': score['utility'],
                                      'moments': moments, 'source_ids': batch.source_ids[0]}
                            for key, value in values.items(): arrays[key].append(value)
            if (index + 1) % 20 == 0:
                print(json.dumps({'old_phase': phase, 'source_pairs': index + 1, 'actual_outputs': len(arrays['y'])}), flush=True)
    data = {k: np.asarray(v) for k, v in arrays.items()}
    if len(data['y']) != 20000 or len(set(data['pair'])) != 400:
        raise ValueError('Incomplete fixed old-development census')
    np.savez_compressed(output / 'data.npz', **data)
    write(output / 'results.json', {'schema': 'hepta.next.native-h2-expanded-old-census.v1',
          'phase': phase, 'source_pairs': 400, 'actual_outputs': 20000,
          'data_sha256': sha(output / 'data.npz'), 'rows_sha256': sha(output / 'rows.jsonl.gz'),
          'statistical_unit': 'historical source pair, not writer; no new independent qualification claim',
          'new_XNIST_outcomes_opened': False})
    return data


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(args.protocol.read_text())
    if (protocol['schema'] != 'hepta.next.native-h2-expanded-old-protocol.v1'
            or protocol['source_manifest_sha256'] != MANIFEST_SHA or sha(MANIFEST) != MANIFEST_SHA
            or protocol['predictor_sha256'] != PREDICTOR_SHA or sha(args.predictor) != PREDICTOR_SHA):
        raise ValueError('The fixed larger old-development stage is not registered')
    if protocol['frozen_candidate_sha256'].get(str(args.predictor.resolve())) != sha(args.predictor):
        raise ValueError('Actual predictor path is not part of this old-stage freeze')
    for path, expected in protocol['frozen_candidate_sha256'].items():
        if sha(path) != expected: raise ValueError('Frozen old-stage dependency changed: ' + path)
    write(args.output / 'registration.json', {'schema': 'hepta.next.native-h2-expanded-old-access.v1',
          'protocol_path': str(args.protocol.resolve()), 'protocol_sha256': sha(args.protocol),
          'frozen_candidate_sha256': protocol['frozen_candidate_sha256'],
          'predictor_sha256': sha(args.predictor), 'source_role': 'forecast_calibration',
          'new_XNIST_outcomes_opened': False, 'started_ns': time.time_ns()})
    began, cpu = time.perf_counter_ns(), time.process_time_ns(); torch.set_num_threads(1)
    corpus = load_roles(SHARED / 'abc2-assets/mnist', MANIFEST, roles=('forecast_calibration',))
    generator = Snapshot.load(MODEL, expected_file_sha256=sha(MODEL))._model
    observer, _ = load_reward(OBSERVER, sha(OBSERVER))
    predictor = json.loads(args.predictor.read_text()); encoder = PublicEncoder(args.predictor)
    calibration_data = census(corpus, generator, observer, encoder, predictor, 'calibration', 0,
                              protocol['roles']['calibration'], args.output / 'calibration')
    calibration = fit_calibration(predictor, calibration_data)
    write(args.output / 'old-calibration.json', {**calibration, 'predictor_sha256': sha(args.predictor),
          'calibration_data_sha256': sha(args.output / 'calibration/data.npz'),
          'phase': 'old_development_only', 'no_new_qualification_claim': True})
    # Calibration is persisted before any held validation generation begins.
    validation_data = census(corpus, generator, observer, encoder, predictor, 'validation', 1,
                             protocol['roles']['validation'], args.output / 'validation')
    before = statistics(calibration, calibration_data, writer_bound=False)
    after = statistics(calibration, validation_data, writer_bound=False)
    gates = {'old_split_point_ECE': max(before['ECE_ID'], before['ECE_all'], after['ECE_ID'], after['ECE_all']) <= .03,
             'old_split_nonvacuity': min(before['ID_acceptance'], after['ID_acceptance']) >= .25,
             'old_split_zero_OOD_false_source_pairs': before['OOD_false_units'] == after['OOD_false_units'] == 0}
    if any(sha(path) != expected for path, expected in protocol['frozen_candidate_sha256'].items()):
        raise ValueError('Expanded old-stage dependency changed during actual generation')
    selection = selected(calibration, validation_data)
    for diagnostics in selection.values():
        diagnostics['source_pairs'] = diagnostics.pop('writers')
        diagnostics['unit_is_writer'] = False
    record = {'schema': 'hepta.next.native-h2-expanded-old-development.v1', 'status': 'completed',
              'predictor_sha256': sha(args.predictor), 'registration_sha256': sha(args.output / 'registration.json'),
              'old_calibration': before, 'old_verification': after, 'old_feasibility_gates': gates,
              'new_source_candidate_admitted': all(gates.values()),
              'selected_policy_calibration': selection,
              'selected_diagnostic_is_not_independent_qualification': True,
              'previous_64_64_candidates_remain_failed': True, 'new_source_roles_and_gates_unchanged': True,
              'new_sources_opened': False, 'old_source_pairs': 800, 'actual_outputs': 40000,
              'wall_ns': time.perf_counter_ns() - began, 'cpu_ns': time.process_time_ns() - cpu,
              'old_calibration_only_not_deployable': True, 'production_authority': False}
    write(args.output / 'development.json', record); print(json.dumps(record), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('protocol', 'predictor', 'output'): p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())

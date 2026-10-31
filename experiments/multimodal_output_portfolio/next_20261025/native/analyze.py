"""Read-only evidence audit and preregistered writer-cluster estimates.

This module imports neither Torch nor the generator. It never opens source
pixels, fits a candidate, changes a protocol, or appends to execution journals.
The stored independent observer predictions are audited, not re-observed here.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import struct
import time

import numpy as np
from PIL import Image


ACTIONS = ('stop', 'refine_semantic', 'refine_image', 'refine_text', 'couple')
POLICIES = ('ndu', 'correctness', 'legacy_correctness')
Q = 2 ** 24
LOSS_WEIGHTS = dict(text_fact=.30, relation=.15, image_fact=.35,
                    crossmodal_disagreement=.10, pixel_mse=.10)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def writer(row):
    values = {int(value.split(':writer:')[1].split(':')[0]) for value in row['source_ids']}
    assert len(values) == 1
    return values.pop()


def correct(score):
    return int(score.get('caption_valid', False) and
               all(score[k] == 0 for k in ('text_fact', 'relation', 'image_fact', 'crossmodal_disagreement')))


def audit_media(paths, hashes, score):
    assert set(paths) == set(hashes) == {'text', 'image'}
    assert all(sha(path) == hashes[name] for name, path in paths.items())
    with Image.open(paths['image']) as image:
        assert image.format == 'PNG' and image.mode == 'L' and image.size == (56, 28)
        image.load()
    caption = Path(paths['text']).read_text()
    if score['caption_valid']:
        digits = score['caption_digits']
        assert caption == f"left {digits[0]} right {digits[1]} relation {score['caption_relation']}"
    loss = sum(LOSS_WEIGHTS[k] * score[k] for k in LOSS_WEIGHTS)
    assert abs(loss - score['joint_loss']) < 1e-12
    assert abs(1 - 2 * loss - score['utility']) < 1e-12


def confidence(calibration, raw, absent):
    groups = np.searchsorted(calibration['cuts'], raw, side='right')
    p = np.asarray(calibration['probabilities'])[groups]
    p = np.where(absent, calibration['absent_probability'], p)
    q = np.floor(p * Q + .5).astype(np.int64)
    return 1_000_000 - np.minimum(np.abs(Q - q) * 1_000_000 // Q, 1_000_000)


def ece(p, y):
    bins = np.minimum((p * 10).astype(int), 9)
    return sum(float(np.mean(bins == b) * abs(p[bins == b].mean() - y[bins == b].mean()))
               for b in range(10) if np.any(bins == b))


def audit_qualification(root, name, calibration):
    area = root / name
    with np.load(area / 'data.npz', allow_pickle=False) as packed:
        data = {k: packed[k] for k in packed.files}
    summary = read(area / 'results.json')
    assert sha(area / 'data.npz') == summary['data_sha256']
    assert sha(area / 'rows.jsonl.gz') == summary['rows_sha256']
    commit_cache, identities, writers = {}, set(), set()
    with gzip.open(area / 'rows.jsonl.gz', 'rt') as stream:
        count = 0
        for index, line in enumerate(stream):
            row = json.loads(line)
            identity = row['pair'], row['view'], row['future'], row['action']
            assert identity not in identities
            identities.add(identity)
            tag = f"{row['pair']:04d}-{row['view']}-{row['future']}"
            if tag not in commit_cache:
                path = area / 'commits' / (tag + '.json')
                commit_cache[tag] = read(path), sha(path)
            commit, digest = commit_cache[tag]
            action = ACTIONS.index(row['action'])
            assert row['commit_sha256'] == digest
            assert row['committed_ns'] == commit['committed_ns']
            assert row['committed_ns'] < row['generation_started_ns'] < row['observed_ns']
            assert row['future_used_for_predicting'] is False
            assert row['writer'] == writer(row) == int(data['writer'][index])
            assert row['correct'] == correct(row['score']) == int(data['y'][index])
            assert row['pair'] == int(data['pair'][index]) and action == int(data['action'][index])
            assert commit['public_absent'] == bool(data['absent'][index]) == (row['view'] == 'both_missing')
            assert commit['raw_probability'][action] == float(data['raw_probability'][index])
            assert row['score']['utility'] == float(data['utility'][index])
            audit_media(row['actual_media'], row['media_sha256'], row['score'])
            writers.add(row['writer']); count += 1
    assert count == len(data['y']) == summary['actual_outputs']
    assert len(writers) == summary['independent_writers']
    p = confidence(calibration, data['raw_probability'], data['absent']) / 1e6
    y, absent = data['y'], data['absent'].astype(bool)
    accepted = p >= .75
    ood_writers = np.unique(data['writer'][absent])
    false = sum(bool(accepted[absent & (data['writer'] == w)].any()) for w in ood_writers)
    assert false == 0, 'This audit closed form is registered for the observed zero-error case only'
    return {'actual_output_rows': count, 'actual_media_files_checked': count * 2,
            'public_prediction_commits_checked': len(commit_cache), 'writers': len(writers),
            'writer_ids': sorted(writers), 'ECE_ID': ece(p[~absent], y[~absent]),
            'ECE_all': ece(p, y), 'ID_acceptance': float(accepted[~absent].mean()),
            'OOD_false_writers': false, 'OOD_writers': len(ood_writers),
            'OOD_upper95': 1 - .05 ** (1 / len(ood_writers)),
            'by_action': {action: {'ECE_ID': ece(p[(data['action'] == i) & ~absent], y[(data['action'] == i) & ~absent]),
                                  'ECE_all': ece(p[data['action'] == i], y[data['action'] == i]),
                                  'ID_acceptance': float(accepted[(data['action'] == i) & ~absent].mean())}
                          for i, action in enumerate(ACTIONS)},
            'observer_network_reexecuted_by_this_audit': False}


def audit_projection(path, outcomes, objective):
    data = path.read_bytes()
    assert data[:8] == b'HNDUPJ01'
    count = struct.unpack('>I', data[8:12])[0]
    assert count == 2 * (len(outcomes) + 1) and len(data) == 12 + count * 201
    previous, entries = bytes(32), []
    for index in range(count):
        item = data[12 + 201 * index:12 + 201 * (index + 1)]
        assert struct.unpack('>Q', item[:8])[0] == index + 1
        assert item[9 + 32:9 + 64].hex() == objective
        assert item[9 + 128:9 + 160] == previous
        digest = hashlib.sha256(b'hepta.ndu.projection-journal-entry.v1' + item[:-32]).digest()
        assert digest == item[-32:]
        entries.append({'kind': item[8], 'identity': item[9:41].hex(), 'payload': item[105:137].hex()})
        previous = digest
    for index, outcome in enumerate(outcomes, 1):
        utility, selected = entries[2 * index:2 * index + 2]
        assert utility['kind'] == 1 and selected['kind'] == 2
        assert utility['identity'] == outcome['observation_sha256']
        assert utility['payload'] == selected['payload'] == outcome['modulator']
    return {'entries': count, 'utility_outcomes': len(outcomes), 'journal_sha256': sha(path)}


def audit_native(root, area, allocation, model, predictor, calibration):
    rows = [json.loads(line) for line in (area / 'rollouts.jsonl').read_text().splitlines()]
    result = read(area / 'results.json')
    assert sha(area / 'rollouts.jsonl') == result['rollouts_sha256'] and len(rows) == 576
    by_key = {(r['policy'], r['pair'], r['view']): r for r in rows}
    assert len(by_key) == len(rows)
    role = allocation['roles']['native']
    assert len(set(role['writer_ids'])) == 24
    native_resources, journals, identical_outputs = {}, {}, 0
    max_moment_error, max_raw_error = 0., 0.
    for pair in range(96):
        for view in (('clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted')[pair % 5], 'both_missing'):
            matched = [by_key[p, pair, view] for p in POLICIES]
            assert len({r['initial_public_digest'] for r in matched}) == 1
            for r in matched:
                assert r['source_ids'] == role['source_ids'][2 * pair:2 * pair + 2]
                assert writer(r) == role['pair_writer_ids'][pair]
            for i, left in enumerate(matched):
                for right in matched[i + 1:]:
                    if left['action'] is not None and left['action'] == right['action']:
                        assert left['media_sha256'] == right['media_sha256'] and left['scores'] == right['scores']
                        identical_outputs += 1
    for policy in POLICIES:
        selected_rows = [r for r in rows if r['policy'] == policy]
        resource = []
        for row in selected_rows:
            tag = f"{row['pair']:04d}-{row['view']}"
            decision = read(area / policy / ('decision-' + tag + '.json'))
            request, response = decision['request'], decision['response']
            candidates = response['decision']['candidates']
            assert response['decision_digest'] == row['decision_digest']
            assert response['decision']['selected_action'] == row['action']
            assert response['decision']['future_observation_available'] is False
            assert response['decision']['authority'] == 'deny_all'
            assert decision['received_ns'] == row['decision_received_ns']
            assert all(c['prior_modulator'] == row['prior_modulator'] for c in candidates)
            for index, candidate in enumerate(candidates):
                assert candidate['admitted'] == (not candidate['native_abstain'] and
                    candidate['confidence_ppm'] >= 750000 and candidate['ood_ppm'] <= 500000)
                resource.append(candidate)
                if policy != 'legacy_correctness':
                    x = np.asarray(request['candidates'][index]['features'], dtype=np.int64)
                    assert len(x) == 511 and x[-1] == Q
                    hidden = x[478:510] / Q
                    raw = hidden @ np.asarray(predictor['weight']).T + np.asarray(predictor['bias'])
                    raw = 1 / (1 + np.exp(-np.clip(raw, -80, 80)))
                    head = model['heads'][0]
                    affine = hidden @ np.asarray(head['weight']).T + np.asarray(head['bias'])
                    moments = np.logaddexp(affine, 0) + 1e-8
                    max_moment_error = max(max_moment_error, float(np.max(np.abs(moments - np.asarray(candidate['ndu_moments'], float)))))
                    max_raw_error = max(max_raw_error, float(np.max(np.abs(raw - np.asarray(candidate['raw_probabilities'], float)))))
                    assert int(confidence(calibration, raw[index], row['view'] == 'both_missing')) == candidate['confidence_ppm']
            eligible = [c for c in candidates if c['admitted'] and c['action'] != 'refine_semantic']
            if policy == 'ndu':
                chosen = min(eligible, key=lambda c: (float(c['ndu_moments'][ACTIONS.index(c['action'])]), ACTIONS.index(c['action']))) if eligible else None
                assert row['original_teacher_action_parity'] is True
            else:
                priority = {'stop': 1, 'refine_image': 2, 'couple': 3, 'refine_text': 4}
                chosen = max(eligible, key=lambda c: (c['probability_q24'], priority[c['action']])) if eligible else None
            assert (chosen['action'] if chosen else None) == row['action']
            if row['action'] is None:
                assert row['scores']['utility'] == -1 and row['continuation_generations'] == 0
                assert not (area / policy / ('outcome-' + tag + '.json')).exists()
            else:
                path = area / policy / ('outcome-' + tag + '.json')
                outcome = read(path)
                assert sha(path) == row['outcome_sha256']
                assert outcome['decision_digest'] == row['decision_digest'] and outcome['action'] == row['action']
                assert outcome['decision_received_ns'] < outcome['generation_started_ns'] < outcome['observed_ns']
                assert row['continuation_generations'] == int(row['action'] != 'stop')
                assert outcome['scores'] == row['scores']
                audit_media(outcome['media'], row['media_sha256'], row['scores'])
        previous, modulator, decisions, outcomes = '0' * 64, None, {}, []
        for index, line in enumerate((area / policy / 'state/control.jsonl').read_text().splitlines()):
            record = json.loads(line); event = record['event']
            assert record['previous'] == previous and record['sequence'] == index + 1
            payload = json.dumps(event, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
            digest = hashlib.sha256(b'hepta.closure.online-event.v1' + bytes.fromhex(previous) + payload).hexdigest()
            assert record['digest'] == digest
            if event['kind'] == 'decision':
                assert event['modulator'] == modulator
                assert all(c['prior_modulator'] == modulator for c in event['candidates'])
                assert event['request_id'] not in decisions
                decisions[event['request_id']] = digest
            elif event['kind'] == 'outcome':
                assert decisions[event['request_id']] == event['decision_digest']
                outcomes.append(event)
            else:
                assert index == 0 and event['kind'] == 'bootstrap'
            previous, modulator = digest, event['modulator']
        status = result['process_status'][policy][-1]
        assert previous == status['history_digest'] and modulator == status['modulator']
        assert len(decisions) == 192 and len(outcomes) == status['outcomes']
        assert len(resource) == status['native_sequence']
        assert all(s['authority'] == 'deny_all' and s['training_steps'] == 0 and s['weights_decoded_in_process'] == 1
                   for s in result['process_status'][policy])
        journals[policy] = audit_projection(area / policy / 'state/ndu/projection.journal', outcomes, status['objective_digest'])
        native_resources[policy] = {'ticks': len(resource), 'processes': len(result['process_status'][policy]),
            'all_process_resource_summaries_pass': all(s['native_resource_summary_passed'] for s in result['process_status'][policy]),
            **{field: {'mean': float(np.mean([c[field] for c in resource])),
                       'p95': float(np.quantile([c[field] for c in resource], .95, method='higher')),
                       'p99': float(np.quantile([c[field] for c in resource], .99, method='higher')),
                       'maximum': max(c[field] for c in resource)}
               for field in ('native_execution_micros', 'owner_micros', 'native_transient_bytes',
                             'owner_peak_bytes', 'native_checkpoint_bytes', 'native_write_amplification_ppm')}}
    assert max_moment_error < 1e-10 and max_raw_error < 1e-12
    assert all(x['owner_state_unchanged'] and not x['result']['ok'] for x in result['negative_cases'])
    assert all(x['before'] == x['after'] for x in result['recoveries'])
    return rows, {'matched_prefix_cases': 192, 'same_action_actual_output_pairwise_matches': identical_outputs,
                  'actual_emitted_outputs': sum(r['action'] is not None for r in rows),
                  'actual_continuation_generations': sum(r['continuation_generations'] for r in rows),
                  'actual_stop_outputs': sum(r['action'] == 'stop' for r in rows),
                  'native_resources': native_resources, 'projection_journals': journals,
                  'total_actual_owner_ticks': sum(v['ticks'] for v in native_resources.values()),
                  'negative_checks': len(result['negative_cases']), 'exact_recoveries': len(result['recoveries']),
                  'native_numpy_moment_max_error': max_moment_error, 'native_numpy_admission_raw_max_error': max_raw_error,
                  'native_original_teacher_max_error': result['max_native_original_teacher_error'],
                  'original_teacher_action_parity': {'matches': 192, 'total': 192}}


def estimates(rows, protocol):
    writers = sorted({writer(r) for r in rows})
    config = protocol['inference']
    samples = np.random.default_rng(config['seed']).integers(0, len(writers), (config['bootstrap_replicates'], len(writers)))
    names = ('utility', 'CE_gamma2_action_cost_0002', 'joint_correct', 'stage_ms', 'instrumented_ms', 'coverage')
    report = {}
    for scope in ('ID', 'all_source_with_null_utility_minus_one'):
        values, draws, summaries = {}, {}, {}
        for policy in POLICIES:
            selected = [r for r in rows if r['policy'] == policy and (scope != 'ID' or r['view'] != 'both_missing')]
            blocks = np.asarray([[[r['scores']['utility'], math.exp(-2 * (r['scores']['utility'] - .002 * r['continuation_generations'])),
                                  correct(r['scores']), r['request_ns'] / 1e6, r['instrumented_wall_ns'] / 1e6, r['action'] is not None]
                                 for r in selected if writer(r) == w] for w in writers])
            means = blocks.mean(axis=1)
            point, bootstrap = means.mean(0), means[samples].mean(1)
            point[1] = -math.log(point[1]) / 2
            bootstrap[:, 1] = -np.log(bootstrap[:, 1]) / 2
            values[policy], draws[policy] = point, bootstrap
            summaries[policy] = {name: {'estimate': float(point[i]), 'writer_cluster_95CI': np.quantile(bootstrap[:, i], [.025, .975]).tolist()}
                                 for i, name in enumerate(names)}
            summaries[policy]['rows'] = len(selected)
            summaries[policy]['actions'] = dict(Counter(r['action'] or 'reject' for r in selected))
            emitted = [r for r in selected if r['action'] is not None]
            p, y = np.asarray([r['selected_confidence_ppm'] / 1e6 for r in emitted]), np.asarray([correct(r['scores']) for r in emitted])
            summaries[policy]['selected_action_point_ECE'] = ece(p, y)
            summaries[policy]['selected_action_ECE_is_new_qualification'] = False
        comparisons = {}
        for baseline in POLICIES[1:]:
            delta, boot_delta = values['ndu'] - values[baseline], draws['ndu'] - draws[baseline]
            comparisons['ndu_minus_' + baseline] = {name: {'estimate': float(delta[i]), 'writer_cluster_95CI': np.quantile(boot_delta[:, i], [.025, .975]).tolist()}
                                                   for i, name in enumerate(names)}
        report[scope] = {'policies': summaries, 'comparisons': comparisons}
    return {'inference': {**config, 'writers': len(writers), 'pairs_per_writer': 4,
                         'paired_resamples': True, 'source_pairs_are_not_independent_writers': True},
            'scope': report}


def main(args):
    began = time.perf_counter_ns()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = read(args.code / 'NATIVE_PROTOCOL.json')
    pin_checks = {}
    for name in ('CALIBRATION', 'QUALIFICATION', 'NATIVE'):
        frozen = read(args.code / (name + '_PROTOCOL.json'))
        substituted = []
        for source, expected in frozen['frozen_candidate_sha256'].items():
            path = Path(source)
            if sha(path) != expected:
                assert name == 'CALIBRATION' and path.name == 'collect_qualification.py'
                path = args.runs / 'calibration-001/executed-source/collect_qualification.py'
                assert sha(path) == expected
                substituted.append({'historical_path': source, 'exact_executed_snapshot': str(path), 'sha256': expected})
        pin_checks[name] = {'files': len(frozen['frozen_candidate_sha256']), 'exact_execution_snapshot_mapping': substituted}
    calibration = read(args.runs / 'calibrator-001/calibration.json')
    cal = audit_qualification(args.runs, 'calibration-001', calibration)
    qualification = audit_qualification(args.runs, 'qualification-001', calibration)
    verification = read(args.runs / 'qualification-001/verification.json')
    for field in ('ECE_ID', 'ECE_all', 'ID_acceptance', 'OOD_upper95'):
        assert abs(qualification[field] - verification[field]) < 1e-12
    assert set(cal['writer_ids']).isdisjoint(qualification['writer_ids'])
    allocation = read(args.code.parent / 'SOURCE_ALLOCATION.json')
    native_writers = set(allocation['roles']['native']['writer_ids'])
    assert native_writers.isdisjoint(cal['writer_ids']) and native_writers.isdisjoint(qualification['writer_ids'])
    model = read(args.runs / 'model-002/weights.json')
    predictor = read(args.runs / 'predictor-001/predictor.json')
    rows, native = audit_native(args.runs, args.runs / 'confirm-001', allocation, model, predictor, calibration)
    statistical = estimates(rows, protocol)
    result = {'schema': 'hepta.next.native-independent-evidence-audit.v1', 'audit_script_sha256': sha(__file__),
              'frozen_protocols': pin_checks, 'calibration': cal, 'qualification': qualification,
              'qualification_gates': verification['gates'], 'native_execution': native,
              'statistics': statistical, 'wall_ns': time.perf_counter_ns() - began,
              'no_model_execution_or_new_source_access': True,
              'limitations': ['Observer network predictions audited as stored; no independent new observer run.',
                  'Qualification is pooled five-action point ECE and defined complete-absence OOD, not population ECE or general OOD.',
                  'Writer-cluster intervals are descriptive and do not establish policy superiority or noninferiority.',
                  'Whole daemon, production credentials and remote model-service execution remain outside this evidence.']}
    with (args.output / 'audit.json').open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write('\n')
    print(json.dumps({'audit_sha256': sha(args.output / 'audit.json'), 'ticks': native['total_actual_owner_ticks'],
                      'outputs': native['actual_emitted_outputs'], 'primary': statistical['scope']['ID']['comparisons']['ndu_minus_correctness']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--code', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())

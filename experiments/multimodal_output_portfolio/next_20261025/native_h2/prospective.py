"""One fixed H2 calibration, one verification, and source-cluster diagnostics."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time

import numpy as np

from ..native.qualification import ece
from .common import AREA, ALLOCATION, pins, sha, write
from .qualification import ACTIONS, ID_VIEWS, calibrated, fit_calibration, statistics


def freeze(study, predictor, development, output, extra=()):
    dev = json.loads(development.read_text())
    if not dev['new_source_candidate_admitted'] or dev['predictor_sha256'] != sha(predictor):
        raise ValueError('Failed old-development admission cannot open new sources')
    suffix = study.removeprefix('native_h2_')
    if suffix not in ('calibration', 'qualification'):
        raise ValueError('Unknown prospective phase')
    count = 100 if suffix == 'calibration' else 1000
    dependencies = [predictor, development, development.parent / 'registration.json', ALLOCATION,
                    AREA.parent / 'h2_sources.py', AREA.parent / 'sources.py', AREA.parent / 'xnist_sources.py',
                    *extra]
    record = {'schema': 'hepta.next.native-h2-prospective.v1', 'study': study,
              'registered_unix_ns': time.time_ns(), 'source_allocation_sha256': sha(ALLOCATION),
              'frozen_candidate_sha256': pins(dependencies), 'predictor_sha256': sha(predictor),
              'development_sha256': sha(development), 'pair_count': count, 'writer_count': count,
              'states': 'H2 root and every H1 child after semantic/image/text/couple',
              'actions_per_state': ACTIONS, 'target': 'immediate actual joint_fact_correct',
              'ID_views': ID_VIEWS, 'OOD': 'public all-input-absent; original bounded task definition only',
              'views_per_pair': 6 if suffix == 'calibration' else 2,
              'future_draws': 2 if suffix == 'calibration' else 1,
              'actual_outputs': 30000 if suffix == 'calibration' else 50000,
              'four_original_gates': {'calibration_and_verification_ECE_point_max': .03,
                                      'calibration_and_verification_OOD_FAR_point_max': .004999,
                                      'calibration_and_verification_ID_acceptance_min': .25,
                                      'verification_writer_OOD_upper95_max': .004999},
              'ece_is_population_bound': False, 'action_specific_gates_claimed': False,
              'selected_ECE_is_separate_report': True,
              'inference_unit': 'independent writer; repeated states/actions/views are not extra N',
              'after_outcomes': 'No candidate/cut/bin/mask/observer/threshold/sample-size change; failures retained',
              'production_authority': False}
    if suffix == 'qualification':
        calibration = next((p for p in extra if p.name == 'calibration.json'), None)
        if calibration is None:
            raise ValueError('Freeze actual calibrator before opening qualification')
        cal = json.loads(calibration.read_text())
        before = cal['calibration']
        if (cal['predictor_sha256'] != sha(predictor) or max(before['ECE_ID'], before['ECE_all']) > .03
                or before['OOD_FAR'] > .004999 or before['ID_acceptance'] < .25):
            raise ValueError('Failing calibration cannot spend the 1000-writer verification cohort')
        calibration_protocol = AREA / 'CALIBRATION_PROTOCOL.json'
        if cal.get('calibration_protocol_sha256') != sha(calibration_protocol):
            raise ValueError('Only the registered prospective calibration may open qualification')
        collection_path = Path(cal['source_collection_directory']).resolve()
        data, collection, access = load_census(collection_path, 'calibration')
        if (Path(access['protocol_path']).resolve() != calibration_protocol.resolve()
                or access['predictor_sha256'] != sha(predictor)
                or cal['source_collection_sha256'] != sha(collection_path / 'results.json')
                or cal['source_access_registration_sha256'] != sha(collection_path / 'access-registration.json')
                or cal['data_sha256'] != collection['data_sha256']
                or cal['rows_sha256'] != collection['rows_sha256']):
            raise ValueError('Calibration is not bound to the actual 100-writer output census')
        actual = fit_calibration(json.loads(predictor.read_text()), data)
        if any(cal.get(key) != value for key, value in actual.items()) or before != statistics(actual, data):
            raise ValueError('Calibration probabilities or statistics do not reproduce the recorded census')
        calibration_freeze = json.loads(calibration_protocol.read_text())['frozen_candidate_sha256']
        if (calibration_freeze.get(str(predictor.resolve())) != sha(predictor)
                or any(sha(path) != expected for path, expected in calibration_freeze.items())):
            raise ValueError('Prospective calibration function changed before qualification')
        continuity_paths = [calibration_protocol, collection_path / 'results.json',
                            collection_path / 'access-registration.json', collection_path / 'data.npz',
                            collection_path / 'rows.jsonl.gz']
        record['frozen_candidate_sha256'].update({str(path.resolve()): sha(path) for path in continuity_paths})
        record['calibration_sha256'] = sha(calibration)
    write(output, record)


def load_census(directory, suffix):
    result = json.loads((directory / 'results.json').read_text())
    access = json.loads((directory / 'access-registration.json').read_text())
    protocol = json.loads(Path(access['protocol_path']).read_text())
    allocation = json.loads(ALLOCATION.read_text())['roles'][suffix]
    if (sha(directory / 'data.npz') != result['data_sha256']
            or sha(directory / 'rows.jsonl.gz') != result['rows_sha256']
            or sha(directory / 'access-registration.json') != result['registration_sha256']
            or sha(access['protocol_path']) != access['protocol_sha256']
            or protocol['study'] != 'native_h2_' + suffix
            or protocol['source_allocation_sha256'] != sha(ALLOCATION)
            or access['source_allocation_sha256'] != sha(ALLOCATION)):
        raise ValueError('Actual data, fixed source role or protocol identity changed')
    with np.load(directory / 'data.npz', allow_pickle=False) as archive:
        data = {k: archive[k] for k in archive.files}
    groups_per_pair = 12 if suffix == 'calibration' else 2
    count = 100 if suffix == 'calibration' else 1000
    if (len(data['y']) != count * groups_per_pair * 25
            or len(set(data['writer'])) != count or len(set(data['pair'])) != count
            or set(Counter(data['group']).values()) != {25}
            or len(set(data['group'])) != count * groups_per_pair):
        raise ValueError('Incomplete five-state/five-action prospective census')
    for case in range(count):
        keep = data['pair'] == case
        expected = [row['source_id'] for row in allocation['source_records'][2 * case:2 * case + 2]]
        if (np.any(data['writer'][keep] != allocation['pair_writer_ids'][case])
                or np.any(data['source_ids'][keep] != expected)):
            raise ValueError('Scored rows do not bind their registered writer and source pair')
    for group in np.unique(data['group']):
        ids = np.flatnonzero(data['group'] == group)
        census = {(int(data['node'][i]), int(data['action'][i])) for i in ids}
        if census != {(node, a) for node in range(5) for a in range(5)}:
            raise ValueError('Repeated or missing causal candidate')
        if any(data['horizon'][i] != (2 if data['node'][i] == 0 else 1) for i in ids):
            raise ValueError('Horizon is not tied to actual causal depth')
    return data, result, access


def selected(calibration, data):
    confidence = calibrated(calibration, data['raw_probability'], data['absent'], data['horizon'], data['action'])
    rows = {'ndu': [], 'correctness': []}
    priority = (1, 0, 2, 4, 3)
    for group in np.unique(data['group'][~data['absent']]):
        ids = np.flatnonzero(data['group'] == group)
        by_node_action = {(int(data['node'][i]), int(data['action'][i])): i for i in ids}
        for policy in rows:
            node = 0
            for _ in range(2):
                horizon = 2 if node == 0 else 1
                eligible = [a for a in range(5) if confidence[by_node_action[node, a]] >= .75 and not (horizon == 1 and a == 1)]
                if not eligible: break
                if policy == 'ndu':
                    a = min(eligible, key=lambda a: (data['moments'][by_node_action[node, a], a], a))
                else:
                    a = max(eligible, key=lambda a: (confidence[by_node_action[node, a]], priority[a]))
                i = by_node_action[node, a]
                rows[policy].append([confidence[i], data['y'][i], horizon, a, data['writer'][i]])
                if not a or horizon == 1: break
                node = a
    result = {}
    for policy, values in rows.items():
        a = np.asarray(values).reshape(-1, 5)
        result[policy] = {'selected_steps': len(a), 'writers': len(set(a[:, 4])),
                          'ECE_ID': ece(a[:, 0], a[:, 1]) if len(a) else None,
                          'by_horizon': {str(h): {'steps': int((a[:, 2] == h).sum()),
                            'ECE_ID': ece(a[a[:, 2] == h, 0], a[a[:, 2] == h, 1]) if np.any(a[:, 2] == h) else None}
                            for h in (1, 2)},
                          'scope': 'Python teacher and calibrated-confidence policy; no native resource gate substitution',
                          'prediction_target': 'immediate emitted output at the visited state; not eventual terminal truth'}
    return result


def calibrate(predictor, directory, output):
    data, collection, access = load_census(directory, 'calibration')
    output.mkdir(parents=True, exist_ok=False)
    if access['predictor_sha256'] != sha(predictor):
        raise ValueError('Wrong actual calibration predictor')
    record = fit_calibration(json.loads(predictor.read_text()), data)
    record.update(predictor_sha256=sha(predictor), data_sha256=collection['data_sha256'],
                  source_collection_sha256=sha(directory / 'results.json'),
                  source_collection_directory=str(directory.resolve()),
                  source_access_registration_sha256=sha(directory / 'access-registration.json'),
                  rows_sha256=collection['rows_sha256'],
                  calibration_protocol_sha256=access['protocol_sha256'], calibration=statistics(record, data))
    write(output / 'calibration.json', record)
    write(output / 'calibrator-freeze.json', {'predictor_sha256': sha(predictor),
          'calibration_sha256': sha(output / 'calibration.json'), 'frozen_unix_ns': time.time_ns()})
    print(json.dumps(record['calibration']), flush=True)


def verify(calibration_path, directory, output):
    data, collection, access = load_census(directory, 'qualification')
    calibration = json.loads(calibration_path.read_text())
    protocol = json.loads(Path(access['protocol_path']).read_text())
    if (protocol['calibration_sha256'] != sha(calibration_path)
            or access['predictor_sha256'] != calibration['predictor_sha256']):
        raise ValueError('Actual frozen calibrator or predictor changed')
    result = statistics(calibration, data)
    before = calibration['calibration']
    max_ece = max(before['ECE_ID'], before['ECE_all'], result['ECE_ID'], result['ECE_all'])
    max_far = max(before['OOD_FAR'], result['OOD_FAR'])
    result['gates'] = {'calibration_and_verification_point_ece': max_ece <= .03,
                       'calibration_and_verification_point_far': max_far <= .004999,
                       'calibration_and_verification_id_nonvacuity': min(before['ID_acceptance'], result['ID_acceptance']) >= .25,
                       'verification_ood_writer_upper95': result['OOD_upper95'] <= .004999}
    result.update(schema='hepta.next.native-h2-admission-verification.v1',
                  study_qualified=all(result['gates'].values()),
                  native_measured_ece_ppm=math.ceil(max_ece * 1e6),
                  native_measured_false_acceptance_ppm=math.ceil(max_far * 1e6),
                  calibration_sha256=sha(calibration_path), data_sha256=collection['data_sha256'],
                  qualification_protocol_sha256=access['protocol_sha256'],
                  source_collection_sha256=sha(directory / 'results.json'),
                  selected_policy_calibration=selected(calibration, data),
                  old_qualification_inherited=False, production_authority=False)
    write(output, result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    f = sub.add_parser('freeze'); f.add_argument('--study', required=True)
    for n in ('predictor', 'development', 'output'): f.add_argument('--' + n, type=Path, required=True)
    f.add_argument('--extra', type=Path, nargs='*', default=[])
    c = sub.add_parser('calibrate'); c.add_argument('--predictor', type=Path, required=True)
    v = sub.add_parser('verify'); v.add_argument('--calibration', type=Path, required=True)
    for q in (c, v):
        q.add_argument('--directory', type=Path, required=True); q.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.command == 'freeze': freeze(a.study, a.predictor, a.development, a.output, a.extra)
    elif a.command == 'calibrate': calibrate(a.predictor, a.directory, a.output)
    else: verify(a.calibration, a.directory, a.output)

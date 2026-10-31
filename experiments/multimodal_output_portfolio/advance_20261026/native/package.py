"""Bind exact selected native weights, calibration, kernel and original owner ABI."""

import argparse
import hashlib
import json
from pathlib import Path
import platform

from .common import AREA, REPO, sha, write


def package(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = json.loads((args.calibration / 'REPORT.json').read_text())
    calibration = args.calibration / 'calibration.json'
    if report['weights_sha256'] != sha(args.weights):
        raise ValueError('Calibrator belongs to another selected model')
    old = report['old_development']
    measured = round(old['pooled_candidate_ece'] * 1e6)
    if measured > 30000:
        raise ValueError('Actual old development calibration already fails original runtime gate')
    verification = {
        'schema': 'hepta.advance.semantic-owner-verification.v1', 'study_qualified': False,
        'qualification_protocol_sha256': sha(AREA / 'PROTOCOL.json'),
        'calibration_sha256': sha(calibration), 'weights_sha256': sha(args.weights),
        'native_measured_ece_ppm': measured, 'native_measured_false_acceptance_ppm': 0,
        'measurement_scope': 'Old development mapped Q24 correctness; missing zero-confidence structural input. Independent source qualification has not run.',
        'nonempty_definition': 'fraction_of_ID_requests_with_at_least_one_admitted_action',
        'minimum_confidence_ppm': 750000, 'maximum_ece_ppm': 30000, 'maximum_false_acceptance_ppm': 4999,
        'old_development': old, 'independent_qualification': False,
        'missing_statistical_qualification_claimed': False,
        'independent_missing_speaker_is_distinct_model_input': False,
    }
    write(args.output / 'development-verification.json', verification)
    host = AREA / 'host.py'
    feature_profile = hashlib.sha256(b'advance.public176+route+remaining+action-index/128+observed-utility+audio-index/128+eligibility33+missing.v1').hexdigest()
    device = {'platform': platform.platform(), 'machine': platform.machine(),
              'python': platform.python_version(), 'logical_device': 'CPU', 'thread_limit': 1}
    write(args.output / 'device.json', device)
    pins = {'protocol': sha(AREA / 'PROTOCOL.json'), 'feature_profile': feature_profile,
        'weights': sha(args.weights), 'calibration': sha(calibration),
        'verification': sha(args.output / 'development-verification.json'), 'device': sha(args.output / 'device.json'),
        'upstream_model': sha(args.weights), 'source_manifest': sha(args.calibration / 'old-development-offline-labels.json'),
        'dataset': sha(args.calibration / 'old-development-public.npz'),
        'measured_ece_ppm': measured, 'measured_false_acceptance_ppm': 0}
    template = {'schema': 'hepta.advance.semantic-owner.v1', 'pins': pins,
        'weights_path': str(args.weights), 'calibration_path': str(calibration),
        'verification_path': str(args.output / 'development-verification.json'),
        'likelihood_path': str(args.likelihood), 'likelihood_sha256': sha(args.likelihood),
        'observer_path': str(host), 'observer_sha256': sha(host), 'max_native_ticks': 2864,
        'stream_id': 'template.not-executable', 'source_group_id': 'template.not-executable',
        'mode': 'development', 'policy': 'dynamic', 'emit_cost': .002, 'acquire_cost': .002,
        'numeric_modulation': True}
    write(args.output / 'template.json', template)
    print(json.dumps({'template': str(args.output / 'template.json'), 'sha256': sha(args.output / 'template.json'),
                      'old_development': old, 'study_qualified': False}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('weights', 'calibration', 'likelihood', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    package(p.parse_args())

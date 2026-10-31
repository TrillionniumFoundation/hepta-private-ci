"""Bind actually qualified admission and frozen NDU layers to one native artifact."""

import argparse
import json
from pathlib import Path
import platform

from .common import AREA, MODEL, OBSERVER, OLD_HEAD, OLD_PACKET, OLD_VERIFICATION, sha, write
from .encoder import PublicEncoder


def package(predictor_path, calibration_path, verification_path, output):
    output.mkdir(parents=True, exist_ok=False)
    predictor = json.loads(predictor_path.read_text())
    calibration = json.loads(calibration_path.read_text())
    verification = json.loads(verification_path.read_text())
    if (verification['study_qualified'] is not True or not all(verification['gates'].values())
            or verification['calibration_sha256'] != sha(calibration_path)
            or calibration['predictor_sha256'] != sha(predictor_path)):
        raise ValueError('Actual complete new qualification required; no old qualification transfer')
    PublicEncoder().export(output / 'value-layers.json')
    weights = json.loads((output / 'value-layers.json').read_text())
    weights['admission'] = {'predictor': {k: predictor[k] for k in ('weight', 'bias')},
                            **{k: calibration[k] for k in ('cuts', 'probabilities', 'absent_probability')}}
    weights['qualified_predictor_sha256'] = sha(predictor_path)
    weights['calibration_sha256'] = sha(calibration_path)
    weights['verification_sha256'] = sha(verification_path)
    weights['new_trainable_parameters'] = sum(len(row) for row in predictor['weight']) + len(predictor['bias'])
    weights['new_parameter_scope'] = 'offline admission head only; frozen NDU value weights are unchanged'
    write(output / 'weights.json', weights)
    host = {'machine': platform.machine(), 'platform': platform.platform(),
            'scope': 'observed research host, no production-host performance qualification'}
    write(output / 'host.json', host)
    write(output / 'package.json', {'schema': 'hepta.next.native-model-package.v1',
          'weights_path': str((output / 'weights.json').resolve()),
          'weights_sha256': sha(output / 'weights.json'),
          'predictor_path': str(predictor_path.resolve()), 'predictor_sha256': sha(predictor_path),
          'calibration_path': str(calibration_path.resolve()), 'calibration_sha256': sha(calibration_path),
          'verification_path': str(verification_path.resolve()), 'verification_sha256': sha(verification_path),
          'device_sha256': sha(output / 'host.json'),
          'encoder_sha256': sha(AREA / 'encoder.py'),
          'production_authority': False, 'H1_only': True})


def descriptor(package_path, selection, maximum, registration):
    package = json.loads(package_path.read_text())
    verified = json.loads(Path(package['verification_path']).read_text())
    pins = {'protocol': sha(AREA / 'QUALIFICATION_PROTOCOL.json'),
            'feature_profile': package['encoder_sha256'], 'weights': package['weights_sha256'],
            'calibration': package['calibration_sha256'], 'verification': package['verification_sha256'],
            'device': package['device_sha256'], 'upstream_model': sha(MODEL),
            'source_manifest': sha(AREA.parent / 'XNIST_QUALIFICATION_ALLOCATION.json'),
            'dataset': sha(AREA.parent / 'XNIST_QUALIFICATION_ALLOCATION.json'),
            'measured_ece_ppm': verified['native_measured_ece_ppm'],
            'measured_false_acceptance_ppm': verified['native_measured_false_acceptance_ppm']}
    return {'schema': 'hepta.next.native-ndu-online.v1', 'pins': pins,
            **{k: package[k] for k in ('weights_path', 'predictor_path', 'predictor_sha256',
                                       'calibration_path', 'verification_path')},
            'selection': selection, 'observer_path': str(OBSERVER), 'observer_sha256': sha(OBSERVER),
            'max_native_ticks': maximum, 'registration': registration}


def legacy_descriptor(maximum, registration):
    packet = json.loads(OLD_PACKET.read_text())
    return {'schema': 'hepta.closure.native-online.v1', 'pins': packet['pins'],
            'weights_path': str(OLD_HEAD / 'weights.json'),
            'calibration_path': str(OLD_HEAD / 'calibration.json'),
            'verification_path': str(OLD_VERIFICATION),
            'observer_path': str(OBSERVER), 'observer_sha256': sha(OBSERVER),
            'max_native_ticks': maximum, 'registration': registration}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('predictor', 'calibration', 'verification', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    package(args.predictor, args.calibration, args.verification, args.output)

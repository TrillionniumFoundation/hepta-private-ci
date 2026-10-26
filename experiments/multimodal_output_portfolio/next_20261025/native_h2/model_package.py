"""Require actual new H2 qualification before loading the native owner."""

import argparse
import json
from pathlib import Path
import platform

from .common import AREA, ALLOCATION, MODEL, SENSOR, qualified_dependencies, sha, write
from .encoder import PublicEncoder


def package(predictor_path, calibration_path, verification_path, output):
    qualified_dependencies(predictor_path, calibration_path)
    output.mkdir(parents=True, exist_ok=False)
    predictor = json.loads(predictor_path.read_text())
    calibration = json.loads(calibration_path.read_text())
    verification = json.loads(verification_path.read_text())
    if (verification['study_qualified'] is not True or not all(verification['gates'].values())
            or verification['calibration_sha256'] != sha(calibration_path)
            or calibration['predictor_sha256'] != sha(predictor_path)
            or verification['schema'] != 'hepta.next.native-h2-admission-verification.v1'
            or verification.get('qualification_protocol_sha256') != sha(AREA / 'QUALIFICATION_PROTOCOL.json')
            or verification.get('independent_units') != 1000 or verification.get('rows') != 50000):
        raise ValueError('Actual complete H2 qualification required; no old qualification transfer')
    PublicEncoder(predictor_path).export(output / 'value-layers.json')
    weights = json.loads((output / 'value-layers.json').read_text())
    weights['admission'] = {'predictors': predictor['heads'], 'strata': calibration['strata']}
    weights['qualified_predictor_sha256'] = sha(predictor_path)
    weights['calibration_sha256'] = sha(calibration_path)
    weights['verification_sha256'] = sha(verification_path)
    weights['new_trainable_parameters'] = predictor['new_trainable_parameters']
    weights['native_admission_parameters'] = 2 * (64 * 5 + 5)
    weights['new_parameter_scope'] = 'offline correctness only; evaluated teacher weights unchanged'
    write(output / 'weights.json', weights)
    write(output / 'host.json', {'machine': platform.machine(), 'platform': platform.platform(),
          'scope': 'observed research host, no production-host performance qualification'})
    write(output / 'package.json', {'schema': 'hepta.next.native-h2-model-package.v1',
          'weights_path': str((output / 'weights.json').resolve()), 'weights_sha256': sha(output / 'weights.json'),
          'predictor_path': str(predictor_path.resolve()), 'predictor_sha256': sha(predictor_path),
          'calibration_path': str(calibration_path.resolve()), 'calibration_sha256': sha(calibration_path),
          'verification_path': str(verification_path.resolve()), 'verification_sha256': sha(verification_path),
          'device_sha256': sha(output / 'host.json'), 'encoder_sha256': sha(AREA / 'encoder.py'),
          'production_authority': False, 'covered_states': 'H2 root and all four H1 children'})


def descriptor(package_path, selection, maximum, registration):
    package = json.loads(package_path.read_text())
    qualified_dependencies(package['predictor_path'], package['calibration_path'])
    verified = json.loads(Path(package['verification_path']).read_text())
    pins = {'protocol': sha(AREA / 'QUALIFICATION_PROTOCOL.json'),
            'feature_profile': package['encoder_sha256'], 'weights': package['weights_sha256'],
            'calibration': package['calibration_sha256'], 'verification': package['verification_sha256'],
            'device': package['device_sha256'], 'upstream_model': sha(MODEL),
            'source_manifest': sha(ALLOCATION), 'dataset': sha(ALLOCATION),
            'measured_ece_ppm': verified['native_measured_ece_ppm'],
            'measured_false_acceptance_ppm': verified['native_measured_false_acceptance_ppm']}
    return {'schema': 'hepta.next.native-h2-ndu-online.v1', 'pins': pins,
            **{k: package[k] for k in ('weights_path', 'predictor_path', 'predictor_sha256',
                                       'calibration_path', 'verification_path')},
            'selection': selection, 'observer_path': str(SENSOR), 'observer_sha256': sha(SENSOR),
            'max_native_ticks': maximum, 'registration': registration}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('predictor', 'calibration', 'verification', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    package(args.predictor, args.calibration, args.verification, args.output)

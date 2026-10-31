"""Immutable implementation/assets and a source-access protocol, without outcomes."""

import argparse
import json
from pathlib import Path
import time

from ...abc_recovery.base_recovery import file_sha, write_json
from ...v7.snapshot import Snapshot


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]


def pins():
    files = list(HERE.glob('*.py')) + [HERE / 'PROTOCOL.json', HERE.parent / 'sources.py']
    for group in ('abc_recovery', 'abc_next', 'abc_followup/control', 'v6', 'v7'):
        files.extend((BASE / group).glob('*.py'))
    files.append(BASE / 'abc_followup/control/PROTOCOL-v2.json')
    return {str(p.resolve()): file_sha(p) for p in sorted(set(files))}


def asset_pins(asset):
    old = json.loads((BASE / 'abc_followup/control/PROTOCOL-v2.json').read_text())
    paths = {str(asset / 'abc3-runs/public-sensor-001/sensor.pt'): old['sensor_sha256']}
    for entry in old['controllers']:
        seed = entry['seed']
        paths[str(asset / f'abc2-runs/training-001/seed-{seed}/output_ndu/model.pt')] = entry['model_file_sha256']
        paths[str(asset / f'abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt')] = entry['old_controller_sha256']
    paths.update({str(asset / 'abc2-runs/base-recovery-001/reward-observer.pt'): '8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003',
                  str(asset / 'abc2-runs/qualification-001/secondary-observer.pt'): 'b0851ce56189d159b53449cfc914cf84b9b63e82a6f0050228096666752595fe'})
    if any(file_sha(Path(path)) != expected for path, expected in paths.items()):
        raise ValueError('Frozen model, controller, sensor or observer changed')
    return paths


def load_model(asset, seed):
    old = json.loads((BASE / 'abc_followup/control/PROTOCOL-v2.json').read_text())
    entry = next(e for e in old['controllers'] if e['seed'] == seed)
    snapshot = Snapshot.load(asset / f'abc2-runs/training-001/seed-{seed}/output_ndu/model.pt',
                             expected_file_sha256=entry['model_file_sha256'])
    if snapshot.fingerprint != entry['model_snapshot_sha256']:
        raise ValueError('Generator semantic identity differs')
    return snapshot


def freeze(asset, development, output):
    result_path = development / 'result.json'
    result = json.loads(result_path.read_text())
    spec = json.loads((HERE / 'PROTOCOL.json').read_text())
    if result['status'] != 'completed' or result['source_sha256'] != pins() or [r['seed'] for r in result['records']] != spec['seeds']:
        raise ValueError('Complete unchanged development must precede fresh source access')
    files = pins() | asset_pins(asset) | {str(result_path.resolve()): file_sha(result_path)}
    for row in result['records']:
        path = development / f"seed-{row['seed']}/bundle.pt"
        if file_sha(path) != row['bundle_sha256']:
            raise ValueError('Trained candidate changed')
        files[str(path.resolve())] = row['bundle_sha256']
    allocation = HERE.parent / 'SOURCE_ALLOCATION.json'
    frozen = {'schema': 'hepta.closure.control-fresh-protocol.v1', 'study': 'control',
              'source_allocation_sha256': file_sha(allocation), 'frozen_candidate_sha256': files,
              'frozen_unix_ns': time.time_ns(), 'new_source_outcomes_opened': False,
              'evaluation': spec['prospective_evaluation'], 'seeds': spec['seeds'],
              'thresholds': {str(r['seed']): r['threshold'] for r in result['records']},
              'scope': '256 newly assigned historical MNIST train source pairs; available-record audit, unknown external use and writer clustering not certified'}
    if output.exists():
        raise FileExistsError('Frozen protocol must never be overwritten')
    write_json(output, frozen)
    print(json.dumps({'protocol': str(output), 'sha256': file_sha(output), 'thresholds': frozen['thresholds']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze(args.asset_root, args.development, args.output)

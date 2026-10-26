"""Exercise actual request/observer APIs on two already opened old source pairs."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import torch

from ...abc_next.compact_tree import scores
from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import write_json
from ...closure_20261025.control.registry import load_model
from ...closure_20261025.control.rollout import decode, emit_json
from ...next_20261025.native.common import OBSERVER, SENSOR, SHARED, TEACHER
from ...next_20261025.sources import MANIFEST_SHA
from ...v6.data import Observation, SourceCorpus, SourceSplit
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.sources import FILES
from .online import AffinePolicy, POLICIES, counterfactuals, request
from .register_confirm import implementation_closure, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    manifest_path = SHARED / 'abc2-runs/source-recovery-001/source-manifest.json'
    if sha(manifest_path) != MANIFEST_SHA:
        raise ValueError('Original development source ledger changed')
    manifest = json.loads(manifest_path.read_text())
    ids = manifest['roles']['forecast_calibration']['source_ids'][896:900]
    checkpoint = Path('/tmp/hepta-ndu-advance-control/development-001/ridge-0.1.json')
    predictor_path = Path('/tmp/hepta-ndu-next-native-h2/development-002/predictor.json')
    calibration_path = Path('/tmp/hepta-ndu-next-native-h2/calibrator-001/calibration.json')
    files = implementation_closure([Path(__file__)]) | {manifest_path, checkpoint, predictor_path, calibration_path}
    write_json(args.output / 'registration.json', {'schema': 'hepta.advance.old-source-api-smoke.v1',
        'registered_ns': time.time_ns(), 'source_role': 'old forecast_calibration pairs448,449 reused development',
        'source_ids': ids, 'new_source_roles_opened': False,
        'frozen_sha256': {str(path): sha(path) for path in files}})
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    cache = SHARED / 'abc2-assets/mnist'
    images, labels = [], []
    for name in ('train-images-idx3-ubyte.gz', 'train-labels-idx1-ubyte.gz'):
        if sha(cache / name) != FILES[name]:
            raise ValueError('Original MNIST archive changed')
    with gzip.open(cache / 'train-images-idx3-ubyte.gz', 'rb') as pictures, gzip.open(
            cache / 'train-labels-idx1-ubyte.gz', 'rb') as digits:
        for identity in ids:
            _, _, index, expected = identity.split(':'); index = int(index)
            pictures.seek(16 + index * 784); raw = pictures.read(784)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('Old source selected pixel SHA differs')
            digits.seek(8 + index); labels.append(digits.read(1)[0])
            images.append(torch.frombuffer(bytearray(raw), dtype=torch.uint8).reshape(1, 28, 28))
    corpus = SourceCorpus({'old': SourceSplit(torch.stack(images), torch.tensor(labels),
        tuple(ids), tuple(identity.rsplit(':', 1)[1] for identity in ids))}, manifest)
    snapshot = load_model(SHARED, 17); teacher = load_controller(TEACHER); sensor = load_sensor(SENSOR)
    candidate = AffinePolicy(json.loads(checkpoint.read_text()))
    predictor, calibration = json.loads(predictor_path.read_text()), json.loads(calibration_path.read_text())
    observer = load_reward(OBSERVER, expected_file_sha256=sha(OBSERVER))[0]
    spec = {'initial_namespace': 'advance-old-five-smoke-initial-v1', 'future_namespace': 'advance-old-five-smoke-future-v1'}
    records = []; count_cf = 0
    with (args.output / 'media.bin').open('x+b') as media, gzip.open(
            args.output / 'commitments.jsonl.gz', 'xt') as commits, gzip.open(
            args.output / 'counterfactuals.jsonl.gz', 'xt') as cf:
        for view in ('clean', 'noise', 'both_missing'):
            batch = make_batch(corpus, 'old', 2, 172621, view=view, offset=0)
            for case in range(2):
                observation = Observation(*(getattr(batch.observation, key)[case:case + 1].clone()
                    for key in ('pixels', 'mask', 'text_tokens')))
                for policy in POLICIES:
                    row, retained = request(snapshot._model, observation, teacher, candidate, sensor,
                        predictor, calibration, policy=policy, seed=17, case=case, view=view, draw=0,
                        spec=spec, media=media, commitments=commits)
                    if row['status'] == 'completed':
                        saved = row['terminal']; media.seek(saved['offset']); raw = media.read(204)
                        if hashlib.sha256(raw).hexdigest() != saved['sha256']:
                            raise ValueError('Actual smoke output readback differs')
                        pixels, _, caption = decode(raw)
                        # Target-bearing scoring runs after this request has closed.
                        target = type(batch.target)(*(getattr(batch.target, key)[case:case + 1]
                            for key in ('pixels', 'text_tokens', 'labels')))
                        with torch.inference_mode():
                            values = scores({'primary': observer}, pixels, caption, target)['primary']
                        row['scores'] = {key: float(value[0]) for key, value in values.items()}
                    records.append(row)
                    if retained is not None and row['status'] != 'failed':
                        result = counterfactuals(snapshot._model, teacher, retained, row, spec, media, commits)
                        emit_json(cf, result); count_cf += 1
    failures = [row for row in records if row['status'] == 'failed']
    snapshot.verify_integrity()
    write_json(args.output / 'result.json', {'status': 'passed' if not failures else 'failed',
        'requests': len(records), 'failures': len(failures), 'H1_counterfactual_nodes': count_cf,
        'new_source_roles_opened': False, 'records': records})
    print(json.dumps({'status': 'passed' if not failures else 'failed', 'requests': len(records),
        'failures': failures, 'H1_counterfactual_nodes': count_cf}))
    if failures:
        raise RuntimeError('Old-development API smoke failed; preserve all attempts')


if __name__ == '__main__':
    main()

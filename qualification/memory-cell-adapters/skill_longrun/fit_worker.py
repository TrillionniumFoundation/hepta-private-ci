"""One fixed-budget skill fit or clean rebuild from current authorized sources."""

import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import active_rows, child_main, identity, sha, skill_rows, validate_cell, validate_program
from reader import canonical_features
from tensor_cell import CellConfig, OutputSpec, TensorCell


def run(request):
    started = time.monotonic_ns()
    required = {'mode', 'checkpoint', 'initial_checkpoint', 'output', 'canonical_features_path',
                'source_rows_path', 'database', 'encoder_sha', 'seed', 'stage', 'protocol_path', 'protocol_sha256'}
    if set(request) != required:
        raise ValueError('fixed fit request fields required')
    raw = Path(request['protocol_path']).read_bytes()
    if sha(raw) != request['protocol_sha256']:
        raise ValueError('protocol identity changed')
    protocol = json.loads(raw)
    if protocol['fit'] != {'steps': 600, 'batch_size': 32, 'lr': 0.01, 'train_head': True,
                           'threads': 1, 'sample_seed': 'seed + stage', 'replay': 'all active skill rows'}:
        raise ValueError('fixed fit contract changed')
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    features, feature_identity = canonical_features(Path(request['canonical_features_path']))
    source_raw = Path(request['source_rows_path']).read_bytes()
    rows = json.loads(source_raw)
    if rows != active_rows(skill_rows(request['database'])):
        raise ValueError('training rows differ from actual SQLite skill source snapshot')
    indexes = [r['index'] for r in rows]
    if not rows or indexes != sorted(set(indexes)) or any(type(i) is not int or not 0 <= i < 8 for i in indexes):
        raise ValueError('unique sorted active skill sources required')
    for row in rows:
        validate_program(row['value'])
    initial = json.loads((Path(request['initial_checkpoint'])/'manifest.json').read_bytes())
    c = initial['config']
    if c['seed'] != request['seed'] or initial['source_ids'] or initial['training_history']:
        raise ValueError('initial architecture must be an untrained source-free checkpoint')
    if request['mode'] == 'update':
        cell = TensorCell.load(request['checkpoint'], request['encoder_sha'])
    elif request['mode'] == 'rebuild':
        config = CellConfig(f"skill-clean-{request['seed']}-{request['stage']}", rank=c['rank'],
                            input_dim=c['input_dim'], outputs=tuple(OutputSpec(**s) for s in c['outputs']), seed=c['seed'])
        cell = TensorCell(config, request['encoder_sha'])
        if cell.parameter_digest() != initial['parameter_sha256']:
            raise ValueError('clean initialization differs from retained untrained seed')
    else:
        raise ValueError('unknown maintenance mode')
    validate_cell(cell)
    targets = {f'op{i}': np.asarray([r['value'][i] for r in rows], dtype='<i8') for i in range(4)}
    ids = [r['source_id'] for r in rows]
    training = cell.fit(features['skill'][indexes], targets, source_ids=ids, steps=600, batch_size=32,
                        lr=0.01, seed=request['seed']+request['stage'], train_head=True)
    if training['unique_rows_seen'] != len(rows):
        raise ValueError('training did not expose every active source')
    generator = torch.Generator().manual_seed(request['seed']+request['stage'])
    schedule = np.stack([torch.randint(len(rows), (32,), generator=generator).numpy() for _ in range(600)]).astype('<i8').tobytes()
    if sha(schedule) != training['sample_schedule_sha256']:
        raise ValueError('reconstructed schedule differs from actual training digest')
    schedule_path = Path(request['output']).parent/'sample-schedule.i64'
    with schedule_path.open('xb') as handle:
        handle.write(schedule)
    cell.source_ids = set(ids)
    saved = cell.save(request['output'])
    return {'schema': 'hepta.memory.adapter-skill-longrun-fit.v1', 'kind': 'skill', 'pid': os.getpid(),
            'seed': request['seed'], 'stage': request['stage'], 'mode': request['mode'],
            'protocol_sha256': request['protocol_sha256'], 'loaded_previous_parameters': request['mode'] == 'update',
            'source_rows_sha256': sha(source_raw), 'source_database': identity(request['database']),
            'canonical_features': feature_identity, 'active_source_ids': sorted(ids),
            'initial_architecture_parameter_sha256': initial['parameter_sha256'], 'training': training,
            'sample_schedule': {'path': str(schedule_path), **identity(schedule_path), 'dtype': '<i8', 'shape': [600, 32],
                                'provenance': 'deterministically reconstructed; equals actual TensorCell.fit schedule digest'},
            'checkpoint': saved, 'parameter_sha256': cell.parameter_digest(), 'parameter_counts': cell.parameter_counts(),
            'wall_ns': time.monotonic_ns()-started, 'held_inputs_opened': False, 'native_runtime_executed': False}


if __name__ == '__main__':
    child_main(run, 'hepta.memory.adapter-skill-longrun-fit.v1')

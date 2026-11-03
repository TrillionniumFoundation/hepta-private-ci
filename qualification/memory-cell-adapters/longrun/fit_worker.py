"""One fixed-budget maintenance fit; called only by the longrun manager."""

import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from reader import canonical_features
from runtime_contract import canonical
from tensor_cell import CellConfig, OutputSpec, TensorCell


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def process_io():
    try:
        return {k: int(v) for line in Path('/proc/self/io').read_text().splitlines()
                for k, v in [line.split(':', 1)]}
    except OSError:
        return {}


def run(request):
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    before_io = process_io()
    raw = Path(request['protocol_path']).read_bytes()
    if sha(raw) != request['protocol_sha256']:
        raise ValueError('protocol identity changed')
    protocol = json.loads(raw)
    fit = protocol['fit']
    if (fit['steps'], fit['batch_size'], fit['lr'], fit['train_head']) != (600, 32, 0.01, True):
        raise ValueError('fixed fit contract changed')
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    features, feature_identity = canonical_features(Path(request['canonical_features_path']))
    source_raw = Path(request['source_rows_path']).read_bytes()
    rows = json.loads(source_raw)
    indexes = [r['index'] for r in rows]
    if not rows or indexes != sorted(set(indexes)) or any(r['kind'] != 'semantic' or not 0 <= r['index'] < 8 for r in rows):
        raise ValueError('unique sorted active semantic sources required')
    if any(len(r['value']) != 3 or any(type(v) is not int or not 0 <= v < 16 for v in r['value']) for r in rows):
        raise ValueError('policy outside declared 12-bit output')
    if request['mode'] == 'update':
        cell = TensorCell.load(request['checkpoint'], request['encoder_sha'])
        if cell.head_frozen:
            raise ValueError('maintenance requires the registered trainable head')
    elif request['mode'] == 'rebuild':
        # Reading architecture metadata is not loading old parameter tensors.
        initial = json.loads((Path(request['initial_checkpoint']) / 'manifest.json').read_bytes())
        c = initial['config']
        config = CellConfig(f"longrun-clean-{request['seed']}-{request['stage']}", rank=c['rank'],
                            input_dim=c['input_dim'], outputs=tuple(OutputSpec(**s) for s in c['outputs']), seed=request['seed'])
        cell = TensorCell(config, request['encoder_sha'])
    else:
        raise ValueError('unknown maintenance operation')
    if cell.config.input_dim != 384 or [(s.name, s.kind, s.size) for s in cell.config.outputs] != [('bits', 'binary', 12)]:
        raise ValueError('semantic architecture changed')
    bits = np.asarray([[(value >> bit) & 1 for value in row['value'] for bit in range(4)] for row in rows], dtype=np.float32)
    ids = [row['source_id'] for row in rows]
    receipt = cell.fit(features['semantic'][indexes], {'bits': bits}, source_ids=ids,
                       steps=600, batch_size=32, lr=0.01, seed=request['seed']+request['stage'], train_head=True)
    if receipt['unique_rows_seen'] != len(rows):
        raise ValueError('fixed fit failed to expose every active source')
    cell.source_ids = set(ids)
    saved = cell.save(request['output'])
    after_io = process_io()
    return {'schema': 'hepta.memory.adapter-longrun-fit.v1', 'pid': os.getpid(), 'mode': request['mode'],
            'seed': request['seed'], 'stage': request['stage'], 'protocol_sha256': request['protocol_sha256'],
            'loaded_previous_parameters': request['mode'] == 'update', 'source_rows_sha256': sha(source_raw),
            'active_source_ids': sorted(cell.source_ids), 'canonical_features': feature_identity,
            'parameter_sha256': cell.parameter_digest(), 'parameter_counts': cell.parameter_counts(),
            'training': receipt, 'checkpoint': saved, 'checkpoint_bytes': sum(p.stat().st_size for p in Path(request['output']).iterdir()),
            'wall_ns': time.monotonic_ns()-began, 'cpu_ns': time.process_time_ns()-cpu,
            'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'process_io_delta': {k: value-before_io.get(k, 0) for k, value in after_io.items()},
            'native_runtime_executed': False, 'held_inputs_opened': False}


if __name__ == '__main__':
    raw = sys.stdin.buffer.read(1048577)
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    try:
        if len(raw) > 1048576:
            raise ValueError('bounded request required')
        response, status = run(json.loads(raw)), 0
    except Exception as error:
        response, status = {'schema': 'hepta.memory.adapter-longrun-fit-error.v1', 'pid': os.getpid(),
                            'error': f'{type(error).__name__}: {error}', 'wall_ns': time.monotonic_ns()-started,
                            'cpu_ns': time.process_time_ns()-cpu, 'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, 2
    response['request_sha256'] = sha(raw)
    sys.stdout.buffer.write(canonical(response)+b'\n')
    raise SystemExit(status)

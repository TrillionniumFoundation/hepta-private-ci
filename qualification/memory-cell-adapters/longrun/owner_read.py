"""Fresh target-blind reads of eight declared addresses, plus exact SQL control."""

import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from owner import Owner
from reader import MeasuredCell, canonical_features, database_guard, snapshot_identity
from runtime_contract import canonical
from tensor_cell import TensorCell


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run(frame):
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    if set(frame) != {'checkpoint', 'encoder_sha', 'database', 'canonical_features_path', 'protocol_sha256'}:
        raise ValueError('reader accepts addresses and artifact paths only; no targets or training rows')
    features, feature_identity = canonical_features(Path(frame['canonical_features_path']))
    began = time.monotonic_ns()
    cell = TensorCell.load(frame['checkpoint'], frame['encoder_sha']).eval()
    loaded = time.monotonic_ns()-began
    if cell.config.input_dim != 384 or [(s.name, s.kind, s.size) for s in cell.config.outputs] != [('bits', 'binary', 12)]:
        raise ValueError('semantic output contract')
    measured = MeasuredCell(cell)
    arms, common_cut = [], None
    for name, retrieval in (('parameter', False), ('exact_sql', True)):
        owner = Owner(frame['database'], {'semantic': measured}, features, allow_value_reads=retrieval)
        try:
            audit = database_guard(owner, retrieval)
            cut = snapshot_identity(owner)
            if common_cut is not None and common_cut != cut:
                raise ValueError('source snapshot changed between arms')
            common_cut = cut
            rows, began = [], time.monotonic_ns()
            for index in range(8):
                prior = dict(owner.reads)
                result = owner.execute({'role': 'semantic', 'entity': index, 'workflow': None})
                rows.append({'entity': index, 'result': result,
                             'reads': {k: v-prior[k] for k, v in owner.reads.items()}})
            read_wall = time.monotonic_ns()-began
            owner.stop()
            prior = dict(owner.reads)
            stopped = owner.execute({'role': 'semantic', 'entity': 0, 'workflow': None})
            memory_stopped = owner.memory('semantic', 0)
            if stopped['status'] != 'owner_stopped' or memory_stopped['status'] != 'owner_stopped' or prior != owner.reads:
                raise ValueError('stopped owner performed a read')
            if not retrieval and (owner.reads['explicit_values'] or audit['source_payload_column_authorizations']):
                raise ValueError('parameter arm accessed source target values')
            arms.append({'arm': name, 'rows': rows, 'reads': dict(owner.reads), 'sql_audit': audit,
                         'read_wall_ns': read_wall, 'owner_stop_probe': stopped, 'memory_stop_probe': memory_stopped,
                         'owner_snapshot_sha256': cut})
        finally:
            owner.stop()
            owner.close()
    forbidden = [name for name in sys.modules if name in {'corpus', 'train', 'score', 'manager', 'fit_worker'}]
    if forbidden:
        raise ValueError('training or target module imported')
    raw_manifest = (Path(frame['checkpoint'])/'manifest.json').read_bytes()
    return {'schema': 'hepta.memory.adapter-longrun-read.v1', 'pid': os.getpid(), 'parent_pid': os.getppid(),
            'protocol_sha256': frame['protocol_sha256'], 'arms': arms, 'model_reads': measured.snapshot(),
            'training_modules_loaded': False, 'target_module_import_audit': forbidden, 'gradient_steps': 0,
            'canonical_features': feature_identity, 'parameter_sha256': cell.parameter_digest(),
            'manifest_sha256': sha(raw_manifest), 'source_ids': sorted(cell.source_ids),
            'checkpoint_bytes': sum(p.stat().st_size for p in Path(frame['checkpoint']).iterdir()),
            'model_load_wall_ns': loaded, 'wall_ns': time.monotonic_ns()-started, 'cpu_ns': time.process_time_ns()-cpu,
            'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, 'native_runtime_executed': False,
            'boundary': 'No encoder execution or target input; exact SQL is an explicit same-information baseline in this same fresh process'}


if __name__ == '__main__':
    torch.set_num_threads(1)
    raw = sys.stdin.buffer.read(1048577)
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    try:
        if len(raw) > 1048576:
            raise ValueError('bounded request required')
        with torch.inference_mode():
            response = run(json.loads(raw))
        status = 0
    except Exception as error:
        response, status = {'schema': 'hepta.memory.adapter-longrun-read-error.v1', 'pid': os.getpid(),
                            'error': f'{type(error).__name__}: {error}', 'wall_ns': time.monotonic_ns()-started,
                            'cpu_ns': time.process_time_ns()-cpu, 'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, 2
    response['request_sha256'] = sha(raw)
    sys.stdout.buffer.write(canonical(response)+b'\n')
    raise SystemExit(status)

"""Fresh skill reads and public execution probes; no target-generator imports."""

import os
from pathlib import Path
import sys
import time

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import child_main, executions, identity, validate_cell
from owner import Owner
from reader import MeasuredCell, canonical_features, database_guard, snapshot_identity
from tensor_cell import TensorCell


def observe(owner, model, workflow):
    before, model_before = dict(owner.reads), model.snapshot()
    result = owner.execute({'role': 'skill', 'entity': None, 'workflow': workflow})
    reads = {k: v-before[k] for k, v in owner.reads.items()}
    delta = {k: v-model_before[k] for k, v in model.snapshot().items()}
    if result['status'] in ('revoked', 'stale_source', 'owner_stopped') and (reads['model'] or reads['explicit_values'] or delta['calls']):
        raise ValueError('refused skill request performed value access or model forward')
    return {'workflow': workflow, 'result': result, 'reads': reads, 'model_reads': delta,
            'executions': executions(result['value']) if result['status'] == 'read' else []}


def stopped(owner, model):
    owner.stop()
    before, model_before = dict(owner.reads), model.snapshot()
    request = owner.execute({'role': 'skill', 'entity': None, 'workflow': 0})
    direct = owner.memory('skill', 0)
    after, model_after = dict(owner.reads), model.snapshot()
    passed = (request['status'] == direct['status'] == 'owner_stopped'
              and before == after and model_before == model_after)
    if not passed:
        raise ValueError('stopped owner performed a read or forward')
    return {'passed': passed, 'owner_stop_probe': request, 'memory_stop_probe': direct,
            'before_reads': before, 'after_reads': after,
            'before_model_reads': model_before, 'after_model_reads': model_after}


def guard(checkpoint, encoder, database, features, workflows, expected):
    """Manager-side refusal probe; the manager separately knows training truth."""
    began = time.monotonic_ns()
    cell = TensorCell.load(checkpoint, encoder).eval()
    validate_cell(cell)
    measured = MeasuredCell(cell)
    owner = Owner(str(database), {'skill': measured}, features)
    try:
        audit = database_guard(owner, False)
        rows = [observe(owner, measured, i) for i in workflows]
        stop = stopped(owner, measured)
        passed = (all(r['result']['status'] == expected for r in rows) and measured.calls == 0
                  and not audit['source_payload_column_authorizations'] and not owner.reads['explicit_values'])
        return {'passed': passed, 'kind': 'skill', 'expected_status': expected, 'rows': rows,
                'model_reads': measured.snapshot(), 'parameter_sha256': cell.parameter_digest(),
                'sql_audit': audit, 'reads': dict(owner.reads), 'stop': stop,
                'wall_ns': time.monotonic_ns()-began, 'target_blind_manager_claimed': False}
    finally:
        owner.close()


def run(frame):
    expected = {'checkpoint', 'encoder_sha', 'database', 'canonical_features_path', 'protocol_sha256'}
    if set(frame) != expected:
        raise ValueError('reader accepts artifact paths and identities only, never targets')
    forbidden = sorted(set(sys.modules) & {'targets', 'manager', 'fit_worker', 'corpus', 'train', 'score'})
    if forbidden:
        raise ValueError('target, training or manager module imported by reader')
    torch.set_num_threads(1)
    features, feature_identity = canonical_features(Path(frame['canonical_features_path']))
    began = time.monotonic_ns()
    cell = TensorCell.load(frame['checkpoint'], frame['encoder_sha']).eval()
    validate_cell(cell)
    load_wall = time.monotonic_ns()-began
    measured, arms, common_cut = MeasuredCell(cell), [], None
    with torch.inference_mode():
        for name, retrieval in (('parameter', False), ('exact_sql', True)):
            owner = Owner(frame['database'], {'skill': measured}, features, allow_value_reads=retrieval)
            try:
                audit = database_guard(owner, retrieval)
                cut = snapshot_identity(owner)
                if common_cut is not None and cut != common_cut:
                    raise ValueError('owner source snapshot differs between arms')
                common_cut = cut
                metadata = owner.db.execute("SELECT idx,identity,version,active FROM sources WHERE kind='skill' ORDER BY idx").fetchall()
                began = time.monotonic_ns()
                rows = [observe(owner, measured, i) for i in range(8)]
                read_wall = time.monotonic_ns()-began
                stop = stopped(owner, measured)
                if not retrieval and (owner.reads['explicit_values'] or audit['source_payload_column_authorizations']):
                    raise ValueError('parameter reader accessed skill source payload')
                arms.append({'arm': name, 'rows': rows, 'reads': dict(owner.reads), 'sql_audit': audit,
                             'read_wall_ns': read_wall, 'stop': stop, 'source_metadata': metadata,
                             'owner_snapshot_sha256': cut})
            finally:
                owner.close()
    return {'schema': 'hepta.memory.adapter-skill-longrun-read.v1', 'kind': 'skill',
            'pid': os.getpid(), 'parent_pid': os.getppid(), 'protocol_sha256': frame['protocol_sha256'],
            'arms': arms, 'model_reads': measured.snapshot(), 'canonical_features': feature_identity,
            'parameter_sha256': cell.parameter_digest(), 'source_ids': sorted(cell.source_ids),
            'manifest': identity(Path(frame['checkpoint'])/'manifest.json'), 'model_load_wall_ns': load_wall,
            'gradient_steps': 0, 'target_module_import_audit': forbidden, 'training_modules_loaded': False,
            'native_runtime_executed': False, 'held_inputs_opened': False,
            'boundary': 'Public runtime probes use predicted programs; targets are scored only by manager/auditor'}


if __name__ == '__main__':
    child_main(run, 'hepta.memory.adapter-skill-longrun-read.v1')

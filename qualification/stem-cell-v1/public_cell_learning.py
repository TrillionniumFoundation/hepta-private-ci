"""Public-data learning canary using the existing frozen Encoder/CellBank code.

Not the nine-arm 421M study, a full BANKING77 benchmark, or an efficacy gate.
Two 16-Cell banks have equal actual tensors, initialization and minibatch schedule;
active Heads differ. Equal training steps are NOT equal actual compute. The
shared Encoder pass is recorded ONCE, not silently multiplied or omitted.
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

from banking77_material import INTENTS, text_key
from matrix_materials import file_sha256, strict_json
from matrix_runtime import publish_prediction_bundle, write_json_exclusive
from next_round_matrix import _digest
from paired_execution import PHASES, _sha

ARMS = {'dense16': 16, 'sparse16_top2': 2}


def validate_inputs(inputs):
    if (not isinstance(inputs, dict) or set(inputs) != {'schema', 'intents', 'fit', 'heldout', 'input_id'}
            or inputs['schema'] != 'hepta.banking77-four-intent-inputs.v1' or inputs['intents'] != list(INTENTS)
            or inputs['input_id'] != _digest({k: v for k, v in inputs.items() if k != 'input_id'})):
        raise ValueError('content-bound four-intent inputs required')
    seen_ids, seen_text = set(), set()
    for split in ('fit', 'heldout'):
        rows = inputs[split]
        if not isinstance(rows, list) or not 4 <= len(rows) <= 256:
            raise ValueError('bounded nonempty input split required')
        for row in rows:
            if not isinstance(row, dict) or set(row) != ({'id', 'text', 'label'} if split == 'fit' else {'id', 'text'}):
                raise ValueError('heldout labels/extra fields cannot enter training')
            if (not isinstance(row['text'], str) or not text_key(row['text']) or len(row['text'].encode()) > 4096
                    or not isinstance(row['id'], str) or not row['id'] or len(row['id']) > 128):
                raise ValueError('invalid input identity/text')
            if row['id'] in seen_ids or text_key(row['text']) in seen_text:
                raise ValueError('duplicate input identity or normalized text across splits')
            seen_ids.add(row['id']); seen_text.add(text_key(row['text']))
            if split == 'fit' and (type(row['label']) is not int or not 0 <= row['label'] < 4):
                raise ValueError('invalid fitting label')
    if {r['label'] for r in inputs['fit']} != set(range(4)):
        raise ValueError('all four fitting classes required')


def freeze_plan(inputs, snapshot_sha256, *, steps=64, width_units=16, batch_size=16, seed=7347):
    validate_inputs(inputs); _sha(snapshot_sha256, 'Encoder snapshot')
    for name, value, limit in (('steps', steps, 128), ('width', width_units, 32), ('batch', batch_size, 64), ('seed', seed, 2**31-1)):
        if type(value) is not int or not 1 <= value <= limit:
            raise ValueError('invalid bounded ' + name)
    from execution_meter import EXTENDED_POLICY_SCHEMA
    from transformer_work_v3 import PROFILE
    body = dict(schema='hepta.public-cell-learning-plan.v1', input_id=inputs['input_id'], snapshot_sha256=snapshot_sha256,
                arms=dict(ARMS), train_steps=steps, width_units=width_units, batch_size=batch_size, seed=seed,
                context_tokens=256, feature_payload_cap=16*1024*1024,
                phase_caps=dict.fromkeys(PHASES, 10**13),
                measurement_policy=dict(schema=EXTENDED_POLICY_SCHEMA, arithmetic_profile=PROFILE, mode='strict',
                    wall_time_ns=600_000_000_000, max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None))
    return {**body, 'plan_id': _digest(body)}


def _validate_plan(inputs, plan):
    expected = freeze_plan(inputs, plan['snapshot_sha256'], steps=plan['train_steps'],
                           width_units=plan['width_units'], batch_size=plan['batch_size'], seed=plan['seed'])
    if _digest(plan) != _digest(expected):
        raise ValueError('learning plan differs from frozen protocol')


def execute_learning(inputs, plan, backend, output):
    """No heldout target argument. Fit existing banks and seal every terminal."""
    import torch
    from execution_meter import WorkLedger
    from matrix_bank import CellBank, state_digest, train_bank
    _validate_plan(inputs, plan)
    dimension = backend.dimension
    if (type(dimension) is not int or not 1 <= dimension <= 8192
            or sum(len(inputs[s]) for s in ('fit', 'heldout')) * dimension * 4 > plan['feature_payload_cap']):
        raise ValueError('shared feature payload exceeds bound')
    root = Path(output); root.mkdir(exist_ok=False)
    write_json_exclusive(root / 'plan.json', plan)
    shared = WorkLedger(plan['measurement_policy'], plan['phase_caps'])
    features, tokens = {}, {}
    try:
        for split, phase in (('fit', 'train'), ('heldout', 'inference')):
            with shared.scope(phase, 'encoder'):
                x = torch.empty((len(inputs[split]), dimension), dtype=torch.float32)
                tokens[split] = []
                for i, row in enumerate(inputs[split]):
                    public = dict(state=row['text'], question='Select the customer service intent.', options=list(INTENTS))
                    vector, length = backend.encode(public)
                    if (vector.shape != (dimension,) or vector.requires_grad or vector.dtype != torch.float32
                            or vector.device.type != 'cpu' or not torch.isfinite(vector).all().item()):
                        raise ValueError('invalid frozen Encoder feature')
                    if type(length) is not int or not 0 < length <= plan['context_tokens']:
                        raise ValueError('invalid actual token count')
                    x[i].copy_(vector); tokens[split].append(length)
                features[split] = x
        shared_report = shared.report()
        write_json_exclusive(root / 'shared-encoder.json', {'observation': shared_report, 'token_counts': tokens,
            'feature_payload_bytes': sum(v.numel()*v.element_size() for v in features.values()),
            'encoder_receipt': backend.receipt, 'counted_once_for_both_arms': True})
    except Exception as exc:
        write_json_exclusive(root / 'FAILED.json', {'error_type': type(exc).__name__, 'work_observation': shared.report()})
        raise
    terminals = {}
    for name, active in ARMS.items():
        bank = None
        dest = root / name; dest.mkdir()
        meter = WorkLedger(plan['measurement_policy'], plan['phase_caps'])
        try:
            # Primitive geometry only; do not borrow a misleading 421M arm ID.
            profile = dict(logical_cells=16, initial_logical_cells=16, split=False, ndu=False,
                           resident_stem_copies=1, active_cells_per_round_cap=active,
                           cell_head_budget_params=2_000_000, total_head_budget_params=32_000_000)
            with meter.scope('train', 'initialization'), torch.random.fork_rng(devices=[]):
                torch.random.default_generator.manual_seed(plan['seed'])
                bank = CellBank(dimension, 4, profile, plan['width_units'])
            initial = state_digest(bank)
            with meter.scope('inference', 'bank'), torch.inference_mode():
                before = bank(features['heldout']).tolist()
            y = torch.tensor([r['label'] for r in inputs['fit']], dtype=torch.long)
            with meter.scope('train', 'bank'):
                training = train_bank(bank, features['fit'], y, plan, plan['seed'])
            trained = state_digest(bank)
            with meter.scope('inference', 'bank'), torch.inference_mode():
                after = bank(features['heldout']).tolist()
            if initial == trained:
                raise ValueError('no actual parameter update occurred')
            if not all(math.isfinite(v) for matrix in (before, after) for row in matrix for v in row):
                raise ValueError('nonfinite sealed prediction')
            predictions = [{'id': r['id'], 'before_logits': b, 'after_logits': a}
                           for r, b, a in zip(inputs['heldout'], before, after, strict=True)]
            execution = dict(schema='hepta.public-cell-learning-arm.v1', plan_id=plan['plan_id'], input_id=inputs['input_id'],
                arm=name, inventory=bank.inventory(), initial_sha256=initial, trained_sha256=trained, training=training,
                work_observation=meter.report(), shared_encoder_sha256=file_sha256(root/'shared-encoder.json'),
                heldout_labels_loaded=False, matrix_arm_qualification=False, production_authorized=False)
            seal = publish_prediction_bundle(dest, bank, execution, predictions)
            terminals[name] = {'kind': 'completed', 'id': seal['seal_id']}
            del bank  # Banks are processed sequentially; weights remain in sealed files.
        except Exception as exc:
            failure = {'arm': name, 'plan_id': plan['plan_id'], 'error_type': type(exc).__name__,
                       'heldout_ids': [r['id'] for r in inputs['heldout']], 'work_observation': meter.report()}
            write_json_exclusive(dest / 'FAILED.json', failure)
            terminals[name] = {'kind': 'failed', 'id': file_sha256(dest/'FAILED.json')}
        finally:
            bank = None
    try:
        backend.reverify()
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json', {'error_type': type(exc).__name__, 'stage': 'Encoder_reverification'})
        raise
    result = {'schema': 'hepta.public-cell-learning-terminals.v1', 'plan_id': plan['plan_id'], 'terminals': terminals,
              'plan_sha256': file_sha256(root/'plan.json'), 'shared_encoder_sha256': file_sha256(root/'shared-encoder.json')}
    result['run_id'] = _digest(result)
    write_json_exclusive(root/'COMMITTED.json', result)
    return result


def _metrics(logits, targets):
    correct, nll, brier = [], [], []
    for row, target in zip(logits, targets, strict=True):
        if not isinstance(row, list) or len(row) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in row):
            raise ValueError('invalid four-class logits')
        pivot = max(row); exp = [math.exp(x-pivot) for x in row]; total = sum(exp)
        correct.append(int(max(range(4), key=row.__getitem__) == target))
        nll.append(math.log(total) + pivot - row[target])
        brier.append(sum((v/total-int(i==target))**2 for i,v in enumerate(exp)))
    return {'count': len(targets), 'accuracy': sum(correct)/len(targets), 'mean_nll': sum(nll)/len(targets),
            'brier': sum(brier)/len(targets), 'per_class_accuracy': {
                INTENTS[c]: sum(v for v,t in zip(correct,targets) if t==c)/targets.count(c) if c in targets else None for c in range(4)}}


def score_sealed(root, expected_run_id, inputs, labels):
    """Call only after all arms terminate. Descriptive scores, never a promotion."""
    from matrix_export import read_sealed
    from work_record import validate_work_record
    validate_inputs(inputs)
    root = Path(root)
    if (root/'FAILED.json').exists():
        raise ValueError('incomplete shared execution cannot be scored')
    terminal = strict_json(root/'COMMITTED.json')
    if terminal.get('run_id') != expected_run_id or _digest({k:v for k,v in terminal.items() if k!='run_id'}) != expected_run_id:
        raise ValueError('retained terminal identity changed')
    plan = strict_json(root/'plan.json'); _validate_plan(inputs, plan)
    if (terminal['plan_id'] != plan['plan_id'] or file_sha256(root/'plan.json') != terminal['plan_sha256']
            or file_sha256(root/'shared-encoder.json') != terminal['shared_encoder_sha256'] or set(terminal['terminals']) != set(ARMS)):
        raise ValueError('changed execution plan or missing registered arm')
    if (not isinstance(labels, dict) or set(labels) != {'schema','input_id','rows'}
            or labels['schema'] != 'hepta.banking77-four-intent-labels.v1' or labels['input_id'] != inputs['input_id']
            or not isinstance(labels['rows'],list) or len(labels['rows']) != len(inputs['heldout'])):
        raise ValueError('complete common heldout labels required')
    targets=[]
    for row, public in zip(labels['rows'],inputs['heldout'],strict=True):
        if (set(row) != {'id','label'} or row['id'] != public['id'] or type(row['label']) is not int or not 0<=row['label']<4):
            raise ValueError('heldout label identity or target mismatch')
        targets.append(row['label'])
    scores, initial, counts = {}, [], []
    for name in ARMS:
        end = terminal['terminals'][name]
        if end['kind'] == 'failed':
            failure_path=root/name/'FAILED.json'
            if file_sha256(failure_path)!=end['id']:
                raise ValueError('failure identity changed')
            failure=strict_json(failure_path)
            if failure['plan_id']!=plan['plan_id'] or failure['heldout_ids']!=[r['id'] for r in inputs['heldout']]:
                raise ValueError('failed denominator changed')
            validate_work_record(failure['work_observation'],expected_policy=plan['measurement_policy'])
            scores[name]={'status':'failed','task_opportunities':len(targets),'delivered_accuracy':0,
                          'failed_record':failure}
            continue
        if end['kind'] != 'completed':
            raise ValueError('unresolved arm is not a scored failure')
        ex, predictions, _ = read_sealed(root/name,end['id'])
        if (ex['plan_id']!=plan['plan_id'] or ex['input_id']!=inputs['input_id'] or ex['arm']!=name
                or ex['heldout_labels_loaded'] is not False or ex['shared_encoder_sha256']!=terminal['shared_encoder_sha256']
                or [r['id'] for r in predictions]!=[r['id'] for r in inputs['heldout']]):
            raise ValueError('sealed population/input mismatch')
        validate_work_record(ex['work_observation'],expected_policy=plan['measurement_policy'])
        initial.append(ex['initial_sha256']); counts.append(ex['inventory']['parameters'])
        scores[name]={'status':'completed','before':_metrics([r['before_logits'] for r in predictions],targets),
                      'after':_metrics([r['after_logits'] for r in predictions],targets),'execution':ex}
    if len(set(initial))>1 or len(set(counts))>1:
        raise ValueError('banks did not match initialization or actual tensor count')
    return {'schema':'hepta.public-cell-learning-scores.v1','run_id':expected_run_id,'labels_sha256':_digest(labels),
            'scores':scores,'all_arms_completed':all(r['status']=='completed' for r in scores.values()),
            'shared_encoder':strict_json(root/'shared-encoder.json'), 'fitting_examples':len(inputs['fit']),
            'heldout_examples':len(targets),'fixed_steps_not_matched_compute':True,'task_subset_not_full_benchmark':True,
            'source_group_independence_verified':False,'pretraining_contamination_checked':False,
            'observer_independence_established':False,'full_system_cost_measured':False,
            'efficacy_established':False,'production_authorized':False}


def main():
    from banking77_material import acquire, prepare
    from hf_encoder_kernel import snapshot_digest
    from hf_complete_checkpoint import ENCODER_PROFILE
    from matrix_runtime import LocalHFEncoder
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-probe',required=True); parser.add_argument('--output',required=True)
    parser.add_argument('--acquire-banking77',action='store_true',required=True)
    args=parser.parse_args(); root=Path(args.output); root.mkdir(exist_ok=False)
    try:
        data=acquire(root/'data')
        inputs, labels, selection=prepare((data/'banking_data/train.csv').read_bytes(),(data/'banking_data/test.csv').read_bytes())
        write_json_exclusive(root/'selection.json',selection)
        source=Path(args.public_probe)
        lock=strict_json(source/'source-lock.json'); material=strict_json(source/'downloaded-material.json')
        from public_encoder_probe import MODEL_ID
        if (lock['model_id']!=MODEL_ID or lock['upstream_revision']!='8949b909ec900327062f0ebf497f51aef5e6f0c8'
                or material['source_lock_sha256']!=file_sha256(source/'source-lock.json')):
            raise ValueError('learning requires the fixed public Encoder material')
        snapshot=source/'snapshot'; identity=snapshot_digest(snapshot)
        if identity!=material['snapshot_sha256']:
            raise ValueError('public Encoder material changed')
        plan=freeze_plan(inputs,identity)
        write_json_exclusive(root/'pre-execution-plan.json',plan)
        cfg=dict(snapshot_sha256=identity,context_tokens=plan['context_tokens'],encoder_profile=ENCODER_PROFILE,
                 upstream_revision='8949b909ec900327062f0ebf497f51aef5e6f0c8',material_approval_sha256=None)
        backend=LocalHFEncoder(snapshot,cfg,{'stem':'smaller_control'})
        import torch
        torch.set_num_threads(1)
        terminal=execute_learning(inputs,plan,backend,root/'trial')
        # Targets are joined only after both fixed training runs have terminated.
        # This is software separation, not process isolation or independent signing.
        result=score_sealed(root/'trial',terminal['run_id'],inputs,labels)
        result['source_files_sha256']={p.name:file_sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
        from banking77_material import REVISION
        result['dataset_revision']=REVISION
        result['dataset_files_sha256']=selection['raw_sha256']
        write_json_exclusive(root/'scores.json',result)
        print(__import__('json').dumps(result,sort_keys=True,allow_nan=False))
        return 0 if result['all_arms_completed'] else 2
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json',{'error_type':type(exc).__name__,'completed':False})
        raise


if __name__=='__main__':
    raise SystemExit(main())

"""Auditable, fail-closed local model-arm scheduling (research-only).

This does not download weights, observe outcomes, sign receipts, change a
production Worker, or select an admission winner. It only binds a finite,
preregistered set of standalone encoder/head jobs to vetted local snapshots.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from model_runner import snapshot_digest
from study import load_jsonl, validate_dataset


PREFIX = 'hepta.stem-cell-research-plan.v1'


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan_id(plan):
    return hashlib.sha256(canonical_json(plan).encode('utf-8')).hexdigest()


def _require_text(value, key):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'missing {key}')
    return value


def _validate_snapshots(descriptors, models):
    if set(descriptors) != set(models):
        raise ValueError('all candidate model snapshots must be explicitly pinned, no extras')
    result = {}
    for key in sorted(models):
        entry = descriptors[key]
        if not isinstance(entry, dict):
            raise ValueError(f'{key}: snapshot record must be an object')
        source = _require_text(entry.get('source'), 'source')
        if source != models[key]['source']:
            raise ValueError(f'{key}: model source mismatch')
        remote = _require_text(entry.get('upstream_revision'), 'upstream_revision')
        if not (len(remote) == 40 and all(c in '0123456789abcdef' for c in remote)):
            raise ValueError(f'{key}: upstream_revision must be immutable Git SHA')
        path = Path(_require_text(entry.get('snapshot_path'), 'snapshot_path')).resolve()
        if not path.is_dir():
            raise ValueError(f'{key}: local snapshot missing')
        expected = _require_text(entry.get('sha256'), 'sha256')
        if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise ValueError(f'{key}: invalid digest')
        if snapshot_digest(path) != expected:
            raise ValueError(f'{key}: snapshot bytes drifted')
        if entry.get('license_approved') is not True:
            raise ValueError(f'{key}: license not approved')
        if key == 'jina_zh' and entry.get('custom_code_reviewed') is not True:
            raise ValueError('jina_zh requires source-reviewed custom code')
        result[key] = {'source': source, 'upstream_revision': remote,
                       'snapshot_path': str(path), 'sha256': expected,
                       'license_approved': True,
                       'custom_code_reviewed': entry.get('custom_code_reviewed') is True}
    return result


def build_plan(dataset, descriptors, protocol, *, device, train_steps, seed, shots=None):
    if protocol.get('stage') != 'shadow_only' or any(protocol['authority'].values()):
        raise ValueError('only shadow/no-authority protocols may run')
    dataset_path = Path(dataset).resolve()
    groups = validate_dataset(list(load_jsonl(dataset_path)))
    required = {'train', 'calibration', 'held_out', 'future_1', 'future_2', 'ood'}
    if {row['split'] for row in groups.values()} != required:
        raise ValueError('all preregistered future/OOD/calibration splits required')
    if not isinstance(train_steps, int) or train_steps <= 0 or not isinstance(seed, int):
        raise ValueError('invalid training steps or seed')
    _require_text(device, 'device')
    models = protocol['model_candidates']
    snapshots = _validate_snapshots(descriptors, models)
    requested = protocol['experiment_1']['shot_counts'] if shots is None else list(shots)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError('duplicate/empty shot schedule')
    if any(n not in protocol['experiment_1']['shot_counts'] for n in requested):
        raise ValueError('shot schedule not preregistered')
    # Zero-shot is a frozen external no-change baseline, never an untrained Head.
    learnable = [s for s in requested if s > 0]
    classes = {row['label'] for row in groups.values()}
    if any(not isinstance(c, int) or c < 0 for c in classes):
        raise ValueError('invalid multiclass task labels')
    arms = []
    for model in sorted(models):
        for representation in sorted(protocol['experiment_2']['representations']):
            for head in sorted(protocol['experiment_2']['heads']):
                for budget in sorted(protocol['experiment_2']['trainable_parameter_budgets']):
                    for shot in sorted(learnable):
                        arm = f'{model}:{representation}:{head}:{budget}:{shot}'
                        arms.append({'arm': arm, 'model_key': model,
                                     'representation': representation,
                                     'head': head, 'budget': budget,
                                     'shots_per_class': shot, 'state': 'planned_unexecuted'})
    if not arms:
        raise ValueError('no trainable arms; zero-shot must use external baseline')
    return {'schema': PREFIX, 'authority': 'none', 'production_authorized': False,
            'protocol_sha256': hashlib.sha256(canonical_json(protocol).encode('utf-8')).hexdigest(),
            'model_runner_source_sha256': sha256_file(Path(__file__).with_name('model_runner.py')),
            'dataset_path': str(dataset_path), 'dataset_sha256': sha256_file(dataset_path),
            'samples': len(groups), 'train_steps': train_steps, 'seed': seed,
            'device': device, 'snapshots': snapshots,
            'requested_shots': requested, 'external_baselines': [
                'no_change', *protocol['teacher_baselines']],
            'arms': arms, 'execution_status': 'unexecuted'}


def write_plan(path, plan):
    path = Path(path)
    if path.exists():
        raise FileExistsError('frozen plan already exists; cannot overwrite')
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {**plan, 'plan_sha256': plan_id(plan)}
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + '\n')
    return record


def load_plan(path):
    full = json.loads(Path(path).read_text(encoding='utf-8'))
    digest = full.pop('plan_sha256')
    if digest != plan_id(full) or full['schema'] != PREFIX or full['execution_status'] != 'unexecuted':
        raise ValueError('modified or unsupported frozen plan')
    return full, digest


def execute_arm(plan_path, arm_name, output_path):
    plan, plan_digest = load_plan(plan_path)
    matches = [arm for arm in plan['arms'] if arm['arm'] == arm_name]
    if len(matches) != 1:
        raise ValueError('arm is not part of frozen plan')
    arm = matches[0]
    path = Path(output_path)
    if path.exists() or Path(str(path) + '.run.json').exists():
        raise FileExistsError('arm result already exists')
    if sha256_file(plan['dataset_path']) != plan['dataset_sha256']:
        raise ValueError('dataset drift, refusing execution')
    pinned = plan['snapshots'][arm['model_key']]
    if snapshot_digest(pinned['snapshot_path']) != pinned['sha256']:
        raise ValueError('weight snapshot drift, refusing execution')
    runner = Path(__file__).with_name('model_runner.py')
    if sha256_file(runner) != plan['model_runner_source_sha256']:
        raise ValueError('model runner source drift')
    actual_protocol = json.loads(Path(__file__).with_name('protocol.json').read_text(encoding='utf-8'))
    if hashlib.sha256(canonical_json(actual_protocol).encode('utf-8')).hexdigest() != plan['protocol_sha256']:
        raise ValueError('preregistered protocol drift')
    path.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(runner), '--dataset', plan['dataset_path'],
            '--snapshot', pinned['snapshot_path'],
            '--expected-snapshot-digest', pinned['sha256'],
            '--model-key', arm['model_key'], '--representation', arm['representation'],
            '--head', arm['head'], '--budget', str(arm['budget']),
            '--shots-per-class', str(arm['shots_per_class']),
            '--train-steps', str(plan['train_steps']), '--seed', str(plan['seed']),
            '--device', plan['device'], '--output', str(path)]
    if arm['model_key'] == 'jina_zh':
        argv.insert(-2, '--allow-audited-custom-code')
    # No shell; model_runner rechecks the weights and emits predictions only.
    subprocess.run(argv, check=True, env={**os.environ, 'HF_HUB_OFFLINE': '1',
                                          'TRANSFORMERS_OFFLINE': '1',
                                          'HF_DATASETS_OFFLINE': '1'})
    manifest = json.loads(Path(str(path) + '.run.json').read_text(encoding='utf-8'))
    if (manifest['model_digest'] != pinned['sha256'] or
            manifest['dataset_digest'] != plan['dataset_sha256'] or
            manifest['arm'] != arm_name or
            manifest['model_runner_source_sha256'] != plan['model_runner_source_sha256'] or
            manifest['protocol_sha256'] != sha256_file(Path(__file__).with_name('protocol.json')) or
            manifest.get('production_authorized') is not False):
        raise ValueError('arm output does not match frozen plan')
    receipt = {'schema': 'hepta.stem-arm-execution-reference.v1',
               'shadow_only': True, 'production_authorized': False,
               'plan_sha256': plan_digest, 'arm': arm_name,
               'predictions_sha256': sha256_file(path),
               'run_manifest_sha256': sha256_file(str(path) + '.run.json')}
    receipt_path = Path(str(path) + '.binding.json')
    with receipt_path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description='Offline frozen Stem model job planner')
    sub = parser.add_subparsers(dest='command', required=True)
    planner = sub.add_parser('plan')
    planner.add_argument('--dataset', required=True)
    planner.add_argument('--snapshots', required=True, help='operator-vetted local snapshot descriptor JSON')
    planner.add_argument('--output', required=True)
    planner.add_argument('--train-steps', type=int, default=100)
    planner.add_argument('--seed', type=int, default=7347)
    planner.add_argument('--device', default='cpu')
    run = sub.add_parser('run')
    run.add_argument('--plan', required=True)
    run.add_argument('--arm', required=True)
    run.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'plan':
        protocol = json.loads(Path(__file__).with_name('protocol.json').read_text(encoding='utf-8'))
        descriptors = json.loads(Path(args.snapshots).read_text(encoding='utf-8'))
        plan = build_plan(args.dataset, descriptors, protocol,
                          device=args.device, train_steps=args.train_steps, seed=args.seed)
        record = write_plan(args.output, plan)
        print(f"frozen {len(record['arms'])} unexecuted arms, plan={record['plan_sha256']}")
    else:
        result = execute_arm(args.plan, args.arm, args.output)
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()

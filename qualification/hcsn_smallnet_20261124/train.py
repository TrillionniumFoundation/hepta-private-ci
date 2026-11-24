"""Bounded training, development-only selection, and a separate sealed test stage."""

import argparse
import ast
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import random
import time
import traceback

import numpy as np
import torch

from .cost import CostMeter
from .data import make_data, probability_metrics
from .model import ModelConfig, SmallHCSN


HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
    tmp.replace(path)


def source_hashes():
    """Bind the training import closure, excluding unrelated in-progress tools."""
    pending = [__package__ + '.train', __package__ + '.campaign']
    found = {}
    while pending:
        module = pending.pop()
        if module in found:
            continue
        spec = importlib.util.find_spec(module)
        if spec is None:
            raise ImportError('missing training dependency: ' + module)
        if spec.origin is None:
            continue  # Namespace packages have no executable initializer.
        path = Path(spec.origin)
        if path.suffix != '.py':
            raise ValueError('training dependency is not a readable Python source: ' + module)
        found[module] = digest(path)
        package = module if spec.submodule_search_locations is not None else module.rpartition('.')[0]
        for level in range(1, len(module.split('.'))):
            pending.append('.'.join(module.split('.')[:level]))
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                name = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) \
                    if node.level else (node.module or '')
                names = [name] if node.module else [name + '.' + item.name for item in node.names]
            else:
                continue
            pending.extend(name for name in names if name == 'qualification' or name.startswith('qualification.'))
    return dict(sorted(found.items()))


def runtime_identity():
    return {'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'numpy': str(np.__version__), 'torch': str(torch.__version__),
            'threads': torch.get_num_threads(), 'device': 'cpu'}


def protocol_digest(p):
    return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def validate_protocol(p):
    if p['source_hashes'] != source_hashes():
        raise ValueError('training source dependency changed after protocol freeze')
    if p['runtime'] != runtime_identity():
        raise ValueError('Python/NumPy/Torch runtime or numerical thread count changed after freeze')


def freeze(path):
    if Path(path).exists():
        raise FileExistsError('never overwrite a frozen protocol')
    p = json.loads((HERE / 'protocol.json').read_text())
    p['source_hashes'] = source_hashes()
    p['runtime'] = runtime_identity()
    write_json(path, p)
    return p


def load_protocol(path):
    p = json.loads(Path(path).read_text())
    validate_protocol(p)
    return p


def config_for(p, arm, neurons):
    return ModelConfig(input_size=p['data']['input_size'], neurons=neurons,
                       boundary_mode=arm['boundary_mode'], message_mode=arm['message_mode'],
                       feature_bank=arm['feature_bank'], precision=p['precision'],
                       backend=p.get('backend_by_neurons', {}).get(str(neurons), p['backend']),
                       feature_normalization=p.get('feature_normalization', 'none'))


def initial_for(model, batch):
    return model.initial_state(len(batch.y), initial_margin=batch.initial_margin[:, None])


def forward_batch(model, batch):
    return model(batch.x, state=initial_for(model, batch), return_features=True)


@torch.no_grad()
def evaluate(model, batch, *, chunk=16, include_features=False):
    outputs, features = [], []
    state_bytes, max_mass_error = 0, 0.0
    for start in range(0, len(batch.y), chunk):
        part = batch.select(torch.arange(start, min(start + chunk, len(batch.y))))
        logits, latent, state = forward_batch(model, part)
        outputs.append(logits.cpu())
        if include_features:
            features.append(latent[-1].cpu())
        if hasattr(state, 'density'):
            mass = state.density[:, :, 0].sum(-1)
            max_mass_error = max(max_mass_error, float((mass - 1).abs().max()))
            max_mass_error = max(max_mass_error, model.last_diagnostics.get('mass_error', 0.0))
            state_bytes = max(state_bytes, sum(getattr(state, name).numel()
                * getattr(state, name).element_size()
                for name in ('density', 'boundary', 'drift', 'cost', 'message')))
    logits = torch.cat(outputs, 1)
    if not bool(torch.isfinite(logits).all()):
        raise FloatingPointError('nonfinite evaluation logits')
    metrics = probability_metrics(logits, batch)
    metrics.update(max_probability_balance_error=max_mass_error,
                   maximum_chunk_state_tensor_bytes=state_bytes,
                   state_bytes_scope='all five dynamic tensor fields; model, outputs and AD tape excluded')
    return metrics, logits, (torch.cat(features, 0) if include_features else None)


def fit(p, output, *, arm, neurons, seed, smoke=False):
    """Retain every terminal attempt, including setup and numerical failures."""
    torch.set_num_threads(1)
    validate_protocol(p)
    random.seed(seed)
    torch.manual_seed(seed)
    output = Path(output)
    if output.exists():
        raise FileExistsError('existing attempt is immutable; use its result, not a new retry')
    output.mkdir(parents=True)
    meter = CostMeter(scope='fit_body_including_setup_selection_checkpoint')
    t = p['training']
    binding = {'experiment_id': p['experiment_id'], 'protocol_sha256': protocol_digest(p),
               'source_hashes': p['source_hashes'], 'arm': arm, 'neurons': neurons,
               'seed': seed, 'smoke': smoke}
    model = optimizer = initial_state = best_state = generator = None
    train_data = dev_data = initial_metrics = best_metrics = None
    history, train_cpu, updates, attempts, best_step = [], 0.0, 0, 0, 0
    last_loss = None
    status, error, failure_trace = 'completed', None, None
    max_updates = min(12, t['max_updates']) if smoke else t['max_updates']
    cpu_budget = min(8., t['train_cpu_seconds']) if smoke else t['train_cpu_seconds']
    try:
        write_json(output / 'started.json', binding)
        split = ('smoke_train', 'smoke_dev') if smoke else ('train', 'dev')
        dtype = torch.float64 if p['precision'] == 'float64' else torch.float32
        train_data = make_data(split[0], per_source=16 if smoke else p['data']['train_per_source'],
                               length=p['data']['length'], dtype=dtype)
        dev_data = make_data(split[1], per_source=16 if smoke else p['data']['dev_per_source'],
                             length=p['data']['length'], dtype=dtype)
        model = SmallHCSN(config_for(p, arm, neurons))
        initial_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        best_state = initial_state
        optimizer = torch.optim.Adam(model.parameters(), lr=t['learning_rate'],
                                      weight_decay=t['weight_decay'])
        generator = torch.Generator().manual_seed(seed ^ 0x76AC)
        initial_metrics, _, _ = evaluate(model, dev_data)
        best_metrics = initial_metrics
        history.append({'step': 0, 'training_cpu_seconds': 0.0, 'development': initial_metrics})
        write_json(output / 'history.json', history)
        for step in range(1, max_updates + 1):
            if train_cpu >= cpu_budget:
                break
            start_cpu = time.process_time()
            attempts += 1
            try:
                indices = torch.randperm(len(train_data.y), generator=generator)[:t['batch_size']]
                batch = train_data.select(indices)
                optimizer.zero_grad(set_to_none=True)
                logits, _, _ = forward_batch(model, batch)
                target = batch.y.expand(logits.shape[0], -1).flatten()
                loss = (.8 * torch.nn.functional.cross_entropy(logits[-1], batch.y)
                        + .2 * torch.nn.functional.cross_entropy(logits.flatten(0, 1), target))
                loss.backward()
                grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), t['gradient_clip'])
                if not torch.isfinite(loss) or not torch.isfinite(grad_norm):
                    raise FloatingPointError('nonfinite loss or gradient')
                optimizer.step()
                updates, last_loss = step, float(loss.detach())
            finally:
                # Failed forwards/backwards/updates consume the same CPU ledger.
                train_cpu += time.process_time() - start_cpu
            if step % t['development_every'] == 0 or step == max_updates or train_cpu >= cpu_budget:
                metrics, _, _ = evaluate(model, dev_data)
                if metrics['cross_entropy'] < best_metrics['cross_entropy']:
                    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
                    best_metrics, best_step = metrics, step
                history.append({'step': step, 'training_cpu_seconds': train_cpu,
                                'loss': last_loss, 'development': metrics})
                write_json(output / 'history.json', history)
    except Exception as exc:
        status, error = 'failed', type(exc).__name__ + ': ' + str(exc)
        failure_trace = traceback.format_exc()
    checkpoint_sha = None
    if model is not None:
        try:
            checkpoint = {**binding, 'schema': 'hcsn-smallnet-checkpoint-v1',
                          'config': asdict(model.config), 'selected_model': best_state,
                          'initial_model': initial_state, 'last_model': model.state_dict(),
                          'optimizer': None if optimizer is None else optimizer.state_dict(),
                          'torch_rng': torch.get_rng_state(),
                          'minibatch_rng': None if generator is None else generator.get_state(),
                          'step': updates, 'best_step': best_step}
            temporary = output / 'checkpoint.pt.tmp'
            torch.save(checkpoint, temporary)
            temporary.replace(output / 'checkpoint.pt')
            checkpoint_sha = digest(output / 'checkpoint.pt')
        except Exception as exc:
            status = 'failed'
            error = (error + '; ' if error else '') + 'checkpoint: ' + type(exc).__name__ + ': ' + str(exc)
            failure_trace = (failure_trace or '') + traceback.format_exc()
    report = {**binding, 'status': status, 'error': error, 'traceback': failure_trace,
              'updates': updates, 'attempted_updates': attempts, 'selected_step': best_step,
              'last_training_loss': last_loss, 'training_cpu_seconds': train_cpu,
              'training_cpu_scope': 'attempted minibatch selection/forward/backward/update intervals, including failures; setup and development are in cost',
              'training_cpu_budget': cpu_budget, 'training_cpu_overrun': max(0., train_cpu - cpu_budget),
              'initial_development': initial_metrics, 'selected_development': best_metrics,
              'parameter_count': None if model is None else sum(v.numel() for v in model.parameters()),
              'train_data_sha256': None if train_data is None else train_data.digest(),
              'dev_data_sha256': None if dev_data is None else dev_data.digest(),
              'checkpoint_sha256': checkpoint_sha,
              'history_sha256': digest(output / 'history.json') if (output / 'history.json').exists() else None,
              'cost': meter.snapshot()}
    write_json(output / 'result.json', report)
    print(json.dumps({'attempt': output.name, 'status': status, 'updates': updates,
                      'selected_step': best_step,
                      'dev_accuracy': None if best_metrics is None else best_metrics['accuracy'],
                      'training_cpu': train_cpu, 'error': error}), flush=True)
    return report


def expected_attempts(p):
    return [f'n{n}-{a["id"]}-s{s}' for n in p['independent_neurons']
            for a in p['arms'] for s in p['seeds']]


def validate_attempts(p, output, *, expected_records=None):
    """Validate every formal terminal and its exact checkpoint before test opens."""
    validate_protocol(p)
    output = Path(output)
    roster = expected_attempts(p)
    if expected_records is not None and set(expected_records) != set(roster):
        raise ValueError('sealed attempt roster differs from the complete frozen roster')
    records = {}
    for neurons in p['independent_neurons']:
        for arm in p['arms']:
            for seed in p['seeds']:
                name = f'n{neurons}-{arm["id"]}-s{seed}'
                directory = output / name
                path = directory / 'result.json'
                result_sha = digest(path)
                if expected_records is not None and expected_records[name] != result_sha:
                    raise ValueError('training record changed after seal: ' + name)
                record = json.loads(path.read_text())
                identity = {'experiment_id': p['experiment_id'], 'protocol_sha256': protocol_digest(p),
                            'source_hashes': p['source_hashes'], 'arm': arm,
                            'neurons': neurons, 'seed': seed, 'smoke': False}
                if any(record.get(key) != value for key, value in identity.items()):
                    raise ValueError('attempt identity differs from its frozen roster slot: ' + name)
                if record.get('status') not in ('completed', 'failed'):
                    raise ValueError('all formal attempts must terminate before sealing')
                history_sha = record.get('history_sha256')
                if history_sha is not None and digest(directory / 'history.json') != history_sha:
                    raise ValueError('selection history changed: ' + name)
                checkpoint_sha = record.get('checkpoint_sha256')
                checkpoint_path = directory / 'checkpoint.pt'
                if checkpoint_sha is None:
                    if record['status'] != 'failed' or checkpoint_path.exists():
                        raise ValueError('completed or inconsistent attempt lacks a bound checkpoint: ' + name)
                else:
                    if digest(checkpoint_path) != checkpoint_sha:
                        raise ValueError('checkpoint changed: ' + name)
                    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=True)
                    if (checkpoint.get('schema') != 'hcsn-smallnet-checkpoint-v1'
                            or any(checkpoint.get(key) != value for key, value in identity.items())
                            or checkpoint.get('config') != asdict(config_for(p, arm, neurons))
                            or checkpoint.get('step') != record.get('updates')
                            or checkpoint.get('best_step') != record.get('selected_step')):
                        raise ValueError('checkpoint identity/configuration differs from its record: ' + name)
                    if record['status'] == 'completed':
                        for key in ('selected_model', 'initial_model'):
                            state = checkpoint.get(key)
                            if (not isinstance(state, dict) or not state
                                    or any(not isinstance(value, torch.Tensor)
                                        or (value.is_floating_point() and not bool(torch.isfinite(value).all()))
                                        for value in state.values())):
                                raise ValueError('completed checkpoint contains invalid model tensors: ' + name)
                if record['status'] == 'completed' and (
                        history_sha is None or record.get('selected_development') is None
                        or record.get('initial_development') is None):
                    raise ValueError('completed attempt lacks selection evidence: ' + name)
                records[name] = (record, result_sha)
    return records


def seal(p, output):
    output = Path(output)
    if (output / 'SEAL.json').exists():
        raise FileExistsError('selection was already sealed')
    meter = CostMeter(scope='common_selection_seal_preflight')
    records = validate_attempts(p, output)
    write_json(output / 'SEAL.json', {'protocol_sha256': protocol_digest(p),
        'source_hashes': p['source_hashes'], 'attempts': {name: value[1] for name, value in records.items()},
        'cost': meter.snapshot()})


def final_test(p, output):
    output = Path(output)
    total = CostMeter(scope='final_test_body_including_common_preflight')
    binding = json.loads((output / 'SEAL.json').read_text())
    if (binding.get('source_hashes') != p['source_hashes']
            or binding.get('protocol_sha256') != protocol_digest(p)):
        raise ValueError('sealed source/protocol mismatch')
    # No test data and no final claim is created until ALL checkpoint identities,
    # hashes and roster records have passed the common preflight.
    records = validate_attempts(p, output, expected_records=binding['attempts'])
    with (output / 'FINAL_CLAIM').open('x') as claim:
        claim.write(digest(output / 'SEAL.json') + '\n')
    dtype = torch.float64 if p['precision'] == 'float64' else torch.float32
    data = make_data('test', per_source=p['data']['test_per_source'], length=p['data']['length'], dtype=dtype)
    rows = []
    for name, (result, _) in records.items():
        directory = output / name
        if result['status'] == 'failed':
            rows.append({'attempt': name, 'status': 'unavailable', 'reason': result['error']})
            continue
        start = CostMeter(scope='one_selected_and_initial_test_evaluation')
        if digest(directory / 'checkpoint.pt') != result['checkpoint_sha256']:
            raise ValueError('checkpoint changed after common preflight: ' + name)
        ckpt = torch.load(directory / 'checkpoint.pt', map_location='cpu', weights_only=True)
        model = SmallHCSN(ModelConfig(**ckpt['config']))
        model.load_state_dict(ckpt['selected_model'])
        metrics, logits, _ = evaluate(model, data)
        model.load_state_dict(ckpt['initial_model'])
        initial, initial_logits, _ = evaluate(model, data)
        raw = {'ids': data.ids, 'labels': data.y.tolist(), 'source': data.source.tolist(),
               'prefix_logits': logits.tolist(), 'initial_prefix_logits': initial_logits.tolist(),
               'final_logits': logits[-1].tolist(), 'initial_margin': data.initial_margin.tolist(),
               'late_step': data.late_step.tolist(), 'source_hashes': p['source_hashes'],
               'protocol_sha256': protocol_digest(p), 'data_sha256': data.digest()}
        write_json(directory / 'test_predictions.json', raw)
        row = {'attempt': name, 'status': 'evaluated', 'neurons': result['neurons'],
               'arm': result['arm']['id'], 'seed': result['seed'], 'metrics': metrics,
               'initial_metrics': initial, 'selected_step': result['selected_step'],
               'data_sha256': data.digest(), 'predictions_sha256': digest(directory / 'test_predictions.json'),
               'cost': start.snapshot()}
        write_json(directory / 'test_result.json', row)
        rows.append(row)
    write_json(output / 'FINAL_RESULTS.json', {'experiment_id': p['experiment_id'],
        'protocol_sha256': protocol_digest(p), 'seal_sha256': digest(output / 'SEAL.json'),
        'cost': total.snapshot(), 'results': rows})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['freeze', 'smoke', 'train', 'seal', 'test'])
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output')
    parser.add_argument('--neurons', type=int, default=8)
    parser.add_argument('--seed', type=int, default=1101)
    parser.add_argument('--arm', default='qvi_full')
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.action == 'freeze':
        freeze(args.manifest)
        return
    p = load_protocol(args.manifest)
    if args.action in ('smoke', 'train'):
        arm = next(a for a in p['arms'] if a['id'] == args.arm)
        fit(p, args.output, arm=arm, neurons=args.neurons, seed=args.seed, smoke=args.action == 'smoke')
    elif args.action == 'seal':
        seal(p, args.output)
    else:
        final_test(p, args.output)


if __name__ == '__main__':
    main()

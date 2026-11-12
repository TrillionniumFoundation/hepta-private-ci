"""Bounded real HCSN model/Adam/RNG replay from immutable epoch checkpoints.

This is a new two-step recovery diagnostic, never completion of original C2.
The parent process fixes all checkpoint/source/data identities before launching
fresh worker interpreters. No original checkpoint or result is written.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import sys
import time


def digest(path):
    value = hashlib.sha256()
    size = 0
    with Path(path).open('rb') as stream:
        for raw in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(raw)
            size += len(raw)
    return {'bytes': size, 'sha256': value.hexdigest()}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def write_json(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def worker(args):
    started = time.monotonic()
    plan_path = Path(args.plan)
    require(digest(plan_path)['sha256'] == args.plan_sha256, 'plan hash differs')
    plan = json.loads(plan_path.read_bytes())
    require(plan['schema'] == 'hcsn-real-checkpoint-replay-plan-v1'
            and plan['steps'] == 2 and plan['confirmation_access'] is False,
            'unrecognized bounded replay plan')
    require(0 <= args.fit_index < len(plan['fits']), 'fit index outside frozen roster')
    require((args.mode == 'resume') == bool(args.resume_checkpoint)
            and (not args.omit_optimizer_state or args.mode == 'resume'), 'invalid resume/control mode')
    entry = plan['fits'][args.fit_index]
    out = Path(args.output)
    out.mkdir(exist_ok=False)
    bound_inputs = {**plan['program_inputs'], **entry['inputs']}
    for name, expected in bound_inputs.items():
        require(digest(name) == expected, 'bound input changed: ' + name)
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'c2_successor_v1'))
    import torch
    from c2_io import bind_study, state_equal, semantic_digest
    from c2_durable import publish_checkpoint, verify_checkpoint
    require(torch.__version__ == plan['torch_version']
            and torch.version.git_version == plan['torch_build'], 'Torch runtime/build differs')
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    study = bind_study(plan['study_source'])
    checkpoint = Path(entry['checkpoint'])
    original = torch.load(checkpoint, map_location='cpu', weights_only=True)
    require(type(original['epochs_completed']) is int
            and original['epochs_completed'] == entry['expected_epoch']
            and type(original['main_updates']) is int
            and original['main_updates'] == entry['expected_main_updates'], 'checkpoint epoch/update count differs')
    training_plan = json.loads(Path(entry['training_plan']).read_bytes())
    data, _, manifest = study.read_episodes(training_plan['prepared'], training_plan['manifest_sha256'])
    require(manifest.get('confirmation_access') is False, 'confirmation data forbidden')
    model = study.CoreStudyModel(**original['model_configuration'])
    optimizer, _ = study.adamw(model, training_plan['learning_rate'], 0.0)
    require(study.sources(model) == entry['model_sources'], 'actual loaded model source differs')
    order_rng = random.Random()
    start_index = 0
    state = original
    if args.resume_checkpoint:
        require(args.mode == 'resume', 'resume file only admitted in resume mode')
        resumed_path = Path(args.resume_checkpoint)
        require(digest(resumed_path)['sha256'] == args.resume_sha256, 'resume bytes differ')
        resumed = torch.load(resumed_path, map_location='cpu', weights_only=True)
        require(resumed['schema'] == 'hcsn-real-checkpoint-replay-state-v1'
                and resumed['plan_sha256'] == args.plan_sha256
                and resumed['origin'] == entry['checkpoint_identity']
                and resumed['cursor']['next_batch'] == 1, 'resume lineage/cursor differs')
        state = resumed['state']
        start_index = 1
    model.load_state_dict(state['model'], strict=True)
    if not args.omit_optimizer_state:
        optimizer.load_state_dict(state['optimizer'])
    order_rng.setstate(state['order_rng'])
    torch.set_rng_state(state['torch_rng'])
    initial_state = {'model': model.state_dict(), 'model_configuration': model.construction_configuration,
        'optimizer': optimizer.state_dict(), 'torch_rng': torch.get_rng_state(),
        'order_rng': order_rng.getstate(), 'epochs_completed': state['epochs_completed'],
        'main_updates': state['main_updates'], 'data_manifest_sha256': state['data_manifest_sha256']}
    if not args.omit_optimizer_state:
        require(state_equal(initial_state, state), 'fresh process did not restore complete state')
    if start_index:
        order = resumed['cursor']['episode_order_indices']
    else:
        order = list(range(len(data['train'])))
        order_rng.shuffle(order)
    require(sorted(order) == list(range(len(data['train']))), 'episode cursor is not a full permutation')
    require(state['data_manifest_sha256'] == training_plan['manifest_sha256'], 'checkpoint data differs')
    batch_size = training_plan['batch_size']
    require(len(data['train']) >= 2 * batch_size, 'two complete batches required')
    targets = [target for row in data['train'] for target in row['y']]
    require(sorted(set(targets)) == list(range(11)), 'training label support differs')
    weights = torch.bincount(torch.tensor(targets), minlength=11).double().rsqrt()
    weights /= weights.mean()
    updates = state['main_updates']
    step_reports = []
    terminal_batch = 1 if args.mode in ('producer', 'crash') else 2
    for index in range(start_index, terminal_batch):
        require(time.monotonic() - started < plan['worker_wall_seconds'], 'replay wall budget exhausted')
        selected = order[index * batch_size:(index + 1) * batch_size]
        ids, x, dt, labels = next(study.batches(data['train'], selected, batch_size))
        model.train()
        optimizer.zero_grad(set_to_none=True)
        value = study.backward_effective_batch(model, x, dt, labels, weights,
            micro_batch_size=training_plan['micro_batch_size'])
        active = [parameter for parameter in model.parameters() if parameter.requires_grad]
        require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
                    for parameter in active), 'missing/nonfinite gradient')
        norm = torch.nn.utils.clip_grad_norm_(active, 1.0)
        require(bool(torch.isfinite(norm)), 'nonfinite gradient norm')
        gradient_digest = semantic_digest({name: parameter.grad for name, parameter in model.named_parameters()
            if parameter.requires_grad})
        optimizer.step()
        updates += 1
        step_reports.append({'batch_index': index, 'episode_ids': ids, 'loss': value['loss'],
            'gradient_norm': float(norm), 'gradient_sha256': gradient_digest,
            'logical_main_updates': updates})
    final_state = {'model': model.state_dict(), 'model_configuration': model.construction_configuration,
        'optimizer': optimizer.state_dict(), 'torch_rng': torch.get_rng_state(),
        'order_rng': order_rng.getstate(), 'epochs_completed': original['epochs_completed'],
        'main_updates': updates, 'data_manifest_sha256': original['data_manifest_sha256']}
    payload = {'schema': 'hcsn-real-checkpoint-replay-state-v1', 'plan_sha256': args.plan_sha256,
        'origin': entry['checkpoint_identity'], 'state': final_state,
        'cursor': {'episode_order_indices': order, 'next_batch': terminal_batch}}
    checkpoint_path = out / 'state.pt'

    def verifier(path):
        if args.mode == 'crash':
            # Actual Torch serialization, flush and fsync precede this callback;
            # the durable publisher has not linked the canonical path yet.
            os._exit(73)
        return state_equal(torch.load(path, map_location='cpu', weights_only=True), payload)

    published = publish_checkpoint(checkpoint_path, lambda stream: torch.save(payload, stream),
        verifier, max_bytes=8 * 1024 * 1024)
    verify_checkpoint(checkpoint_path, published,
        lambda path: state_equal(torch.load(path, map_location='cpu', weights_only=True), payload))
    for name, expected in bound_inputs.items():
        require(digest(name) == expected, 'bound input mutated during replay: ' + name)
    require(digest(plan_path)['sha256'] == args.plan_sha256, 'plan changed while running')
    report = {'schema': 'hcsn-real-checkpoint-replay-worker-v1', 'mode': args.mode,
        'fit': entry['fit'], 'plan_sha256': args.plan_sha256,
        'checkpoint': published, 'semantic_sha256': semantic_digest(payload), 'steps': step_reports,
        'restored_state_equal': not args.omit_optimizer_state,
        'negative_control_omit_optimizer_state': args.omit_optimizer_state,
        'new_optimizer_steps': len(step_reports), 'origin_epoch': original['epochs_completed'],
        'original_c2_completion_claimed': False, 'scientific_admission': 'HOLD_NO_GO',
        'whole_worker_wall_seconds': time.monotonic() - started,
        'process_cpu_seconds': time.process_time(), 'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        'python': sys.version, 'torch': torch.__version__, 'torch_build': torch.version.git_version,
        'source_and_input_identities_unchanged': True}
    write_json(out / 'RESULT.json', report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--fit-index', type=int, required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=('reference', 'producer', 'resume', 'crash'), required=True)
    parser.add_argument('--resume-checkpoint')
    parser.add_argument('--resume-sha256')
    parser.add_argument('--omit-optimizer-state', action='store_true')
    worker(parser.parse_args())


if __name__ == '__main__':
    main()

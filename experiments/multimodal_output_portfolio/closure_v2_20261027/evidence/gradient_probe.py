"""Reconstruct selected training steps from saved actors and fresh media readback.

This never calls the trainer, its objective, its gradient helper, or its utility
scorer. It reuses the frozen generator/dataset implementation and checkpoints.
The reconstructed bytes were written during this audit, not retained from the
original training process, which kept only a whole-stream media commitment.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import torch

from ...continuation_20261027.joint.data import historical_corpus
from ...v6.data import make_batch
from ...v6.neural import NeuralState, parameter_hash
from ...v6.plan_training import ControlledSnapshot
from .gradient_probe_media import deliver_and_score, observer


WORK = Path('/workspace/scratch/95988d8d3ab1')
TRAIN = WORK/'ndu-direct-gradient-v2/development-full-001'
DEST = WORK/'ndu-direct-gradient-v2/probe-audit-001'
ASSETS = WORK/'ndu-original-assets/restored'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, record):
    with path.open('x') as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def frozen_actor_module():
    runtime = json.loads((TRAIN/'RUNTIME.json').read_text())
    path = TRAIN/'executed-source/actor.py'
    if digest(path) != runtime['sources']['actor.py']:
        raise AssertionError('Original executed actor source changed')
    name = 'experiments.multimodal_output_portfolio.closure_v2_20261027.joint.frozen_probe_actor'
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def main():
    DEST.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol = json.loads((TRAIN/'PROTOCOL.json').read_text())
    references = json.loads((TRAIN/'BASELINES.json').read_text())
    actor_api = frozen_actor_module()
    (DEST/'executed_source').mkdir()
    for name in ('gradient_probe.py', 'gradient_probe_media.py'):
        shutil.copyfile(Path(__file__).with_name(name), DEST/'executed_source'/name)
    save(DEST/'PROTOCOL.json', {'training_protocol_sha256': digest(TRAIN/'PROTOCOL.json'),
        'training_source_runtime_sha256': digest(TRAIN/'RUNTIME.json'),
        'probe_steps': [1, 201, 401], 'seeds': [17, 29, 43], 'arms': ['direct_mean', 'direct_risk'],
        'cost_absolute_tolerance': 2e-6, 'gradient_absolute_tolerance': 2e-5,
        'parameter_preclip_norm_tolerance': 2e-4,
        'score_scope': 'Independent captions, NumPy64 pixel MSE, reconstructed frozen reward CNN, independent utility and Gaussian-gradient formulas.',
        'source_scope': 'Historical training sources only; no qualification data, audit observer, or parameter updates.',
        'media_scope': 'Reconstructed audit media; not a claim that all original training PNGs were retained.',
        'created_ns': time.time_ns()})
    corpus = historical_corpus(ASSETS)
    reward_path = ASSETS/'ndu-runs/full-002/reward-observer.pt'
    reward = observer(reward_path)
    records = []
    n, k, dimensions, sigma = protocol['batch_size'], protocol['directions'], protocol['dimensions'], protocol['sigma']
    for seed in protocol['seeds']:
        reference = references[str(seed)]
        if digest(Path(reference['path'])) != reference['sha256']:
            raise AssertionError('The original strong base changed')
        base = ControlledSnapshot.load(reference['path'])
        basis = torch.load(TRAIN/f'BASIS-{seed}.pt', weights_only=True, map_location='cpu')
        recorded_basis = json.loads((TRAIN/f'BASIS-{seed}.json').read_text())
        if hashlib.sha256(basis.numpy().tobytes()).hexdigest() != recorded_basis['basis_sha256']:
            raise AssertionError('Frozen PCA basis changed')
        noises = {}
        generator = torch.Generator().manual_seed(seed*1019+271028)
        for zero_step in range(401):
            base_noise = torch.randn(n, base._base._model.hidden, generator=generator)
            eps = torch.randn(k, n, dimensions, generator=generator)
            if zero_step in (0, 200, 400):
                noises[zero_step+1] = (base_noise, eps)
        for arm in ('direct_mean', 'direct_risk'):
            history = json.loads((TRAIN/f'TRAINING-{seed}-{arm}.json').read_text())
            trace_path = TRAIN/f'TRACE-{seed}-{arm}.npz'
            if digest(trace_path) != history['trace_sha256']:
                raise AssertionError('Original cost/gradient trace changed')
            trace = np.load(trace_path)
            for step in (1, 201, 401):
                name = f'{seed}-{arm}-step-{step}'
                if step == 1:
                    torch.manual_seed(seed*73+19)
                    actor = actor_api.LatentActor(4*base._base._model.hidden, dimensions, protocol['hidden'])
                    if parameter_hash(actor) != history['actor_before']:
                        raise AssertionError('Initial actor reconstruction differs')
                    checkpoint_hash = None
                else:
                    checkpoint = next(row for row in history['checkpoints'] if row['step'] == step-1)
                    path = TRAIN/checkpoint['path']
                    if digest(path) != checkpoint['sha256']:
                        raise AssertionError('Original preceding actor checkpoint changed')
                    snapshot = actor_api.LatentSnapshot.load(path, base)
                    if snapshot.sigma != sigma or not torch.equal(snapshot.basis, basis):
                        raise AssertionError('Preceding actor distribution differs')
                    actor = snapshot.actor.requires_grad_(True)
                    checkpoint_hash = checkpoint['sha256']
                noise, eps = noises[step]
                zero_step = step-1
                condition = protocol['conditions'][zero_step % 4]
                batch_seed = seed*1000003+zero_step*19+271028
                batch = make_batch(corpus, 'train', n, batch_seed, corruption=condition)
                with torch.no_grad():
                    terminal, choices = actor_api.terminal_state(base, batch.observation, noise)
                    features = actor_api.state_features(terminal)
                mean = actor(features)
                coefficients = torch.cat((mean.detach()[None]+sigma*eps,
                                           mean.detach()[None]-sigma*eps)).flatten(0, 1)
                repeated = NeuralState(*(getattr(terminal, field).repeat(2*k, 1)
                                         for field in ('h', 'image', 'text', 'context')))
                with torch.no_grad():
                    generated = base._base._model.decode(actor_api.shift_state(repeated, coefficients, basis))
                target_pixels = batch.target.pixels.repeat(2*k, 1, 1, 1)
                target_labels = batch.target.labels.repeat(2*k, 1)
                archive = DEST/f'{name}.zip'
                utility, outcomes = deliver_and_score(archive, generated, target_pixels, target_labels, reward)
                independent_cost = (-utility if arm == 'direct_mean' else np.expm1(-protocol['gamma']*utility)/protocol['gamma']).reshape(2, k, n)
                independent_gradient = np.mean((independent_cost[0]-independent_cost[1])[..., None]*eps.numpy(), axis=0)/(2*sigma)
                cost_error = float(abs(independent_cost-trace['actual_costs'][zero_step]).max())
                gradient_error = float(abs(independent_gradient-trace['gradients'][zero_step]).max())
                clean_kl = mean.square().sum(-1).mean()/(2*sigma**2)
                objective = (mean*torch.from_numpy(independent_gradient).float()).sum(-1).mean()
                if condition == 'clean':
                    objective += protocol['clean_kl_coefficient']*clean_kl
                objective.backward()
                preclip_norm = float(torch.sqrt(sum(parameter.grad.double().square().sum() for parameter in actor.parameters())))
                norm_error = abs(preclip_norm-history['history'][zero_step]['preclip_gradient_norm'])
                if cost_error > 2e-6 or gradient_error > 2e-5 or norm_error > 2e-4:
                    raise AssertionError(f'Independent training probe differs: {name}: {cost_error}, {gradient_error}, {norm_error}')
                np.savez_compressed(DEST/f'{name}-inputs.npz', base_noise=noise.numpy(), directions=eps.numpy(),
                                    actual_costs=independent_cost, coefficient_gradients=independent_gradient,
                                    public_state_mean=mean.detach().numpy())
                save(DEST/f'{name}-outcomes.json', outcomes)
                record = {'seed': seed, 'arm': arm, 'step': step, 'condition': condition,
                    'examples': 2*k*n, 'source_ids': batch.source_ids, 'plans': choices.tolist(),
                    'preceding_checkpoint_sha256': checkpoint_hash, 'archive': archive.name,
                    'archive_sha256': digest(archive), 'maximum_cost_error': cost_error,
                    'maximum_coefficient_gradient_error': gradient_error, 'parameter_preclip_norm': preclip_norm,
                    'preclip_norm_error': norm_error, 'trace_sha256': digest(trace_path),
                    'input_sha256': digest(DEST/f'{name}-inputs.npz'), 'outcomes_sha256': digest(DEST/f'{name}-outcomes.json')}
                records.append(record)
                save(DEST/f'{name}-audit.json', record)
                print(json.dumps({key: record[key] for key in ('seed', 'arm', 'step', 'maximum_cost_error', 'maximum_coefficient_gradient_error', 'preclip_norm_error')}), flush=True)
    result = {'schema': 'hepta.ndu.direct-gradient-independent-probes.v1', 'passed': True,
        'probes': len(records), 'actual_reconstructed_bundles': sum(row['examples'] for row in records),
        'actual_media_members': 2*sum(row['examples'] for row in records), 'records': records,
        'maximum_cost_error': max(row['maximum_cost_error'] for row in records),
        'maximum_coefficient_gradient_error': max(row['maximum_coefficient_gradient_error'] for row in records),
        'maximum_preclip_norm_error': max(row['preclip_norm_error'] for row in records),
        'reward_observer_sha256': digest(reward_path), 'protocol_sha256': digest(DEST/'PROTOCOL.json'),
        'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu,
        'limitations': ['All18 probes are clean-condition steps because the saved checkpoints are200-step multiples.',
                       'This validates the recorded costs and gradients at the selected saved states, not every unretained original training artifact.',
                       'Fitted reward CNN is an imperfect fixed recognizer; this is not human semantic certification.'],
        'new_qualification_sources_scored': 0, 'parameter_updates_performed': 0}
    save(DEST/'RESULT.json', result)
    print(json.dumps({key: result[key] for key in result if key != 'records'}), flush=True)


if __name__ == '__main__':
    main()

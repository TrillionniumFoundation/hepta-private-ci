"""Train the complete-backend/control factorial before fresh heldout access."""

import argparse
import copy
import hashlib
import inspect
import json
import platform
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_validation_r12_20261031.content.models import FAMILIES, Model
from experiments.hcsn_validation_r12_20261031.content.study import load_selected
from .data import TASKS, DOMAINS, SPLITS, dataset
from .engine import ValueController, all_logits, policy_values, realized_returns, replay, model_hash


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
OLD = REPO / 'experiments/hcsn_validation_r12_20261031/content/results/formal001/PROTOCOL.json'
SEEDS = (12031, 12032, 12033)
MODES = ('frozen_backend', 'joint_backend')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def configure():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)


def tensors(values, ids=None):
    ids = slice(None) if ids is None else ids
    return tuple(torch.from_numpy(values[name][ids]) for name in ('x', 'dt', 'y'))


def freeze(output, updates=256):
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads((OLD.parent/'CANDIDATE_FREEZE.json').read_text())
    from ncps.torch import CfCCell
    sources = sorted(ROOT.glob('*.py'))
    sources += sorted((OLD.parents[2]).glob('*.py'))
    sources += sorted((OLD.parents[2]/'upstream').glob('*.py'))
    identity = {str(p.relative_to(REPO)): sha(p) for p in sources}
    inputs = {}
    for task in TASKS:
        for seed in SEEDS:
            for family in FAMILIES:
                job = f'{task}_s{seed}_joint_{family}'
                entry = original['candidates'][job]
                path = OLD.parent/entry['path']/'selected.pt'
                if sha(path) != entry['sha256']:
                    raise ValueError('Inherited checkpoint changed: ' + job)
                inputs[job] = dict(path=str(path.relative_to(REPO)), sha256=entry['sha256'])
    protocol = dict(schema='hcsn-r14.complete-backend.v1', updates=updates,
        batch_size=32, learning_rate=.003, grad_clip=1., validate_every=64,
        seeds=SEEDS, tasks=TASKS, domains=DOMAINS, splits=SPLITS, families=FAMILIES,
        modes=MODES, initialization='Original R12 selected JOINT complete backends for every mode; no new donor.',
        frozen='All encoder/core/readout parameters frozen and byte-verified; only shared controller learns.',
        joint='All eight backends plus their one exactly shared controller learn together. Same batches, updates, data, objective and initialization as frozen mode.',
        actions=['STOP', 'READ one raw frame then follow the same policy'],
        schedule='The complete timestamp schedule and finite observation budget are public before initial STOP. Payload frames remain inaccessible until paid READ. This does not cover unknown future arrival times.',
        initial_stop=True, read_fee=.0025, time_fee=.0005,
        light='Read every frame, then submit. Content weights identical across light/value arms.',
        value='One exact shared 10->24->2 critic per task/seed/mode. Scores see class predictions plus public clocks/budget/fees only.',
        objective='Per-prefix content CE + legal-action MSE to actual sample-path Q-pi targets; targets detached. No future/label inputs to actor.',
        selection='Select whole backend/controller group by maximum mean validation utility over eight cores; step zero eligible; earliest tie. Ordinary family selected on validation utility within seven ordinary families.',
        primary='Per task/mode: D-B versus matched ordinary_dual; also report D minus validation-selected strongest ordinary family. All five contrasts, all domains, all seeds.',
        estimand='A/B and C/D execute identical backend weights within each mode. In joint_backend these weights were jointly value-trained: B-A, D-C and the interaction are execution-control effects conditional on that training regime. They are not total effects of separately training light and value policies. D-B compares cores under the same value-training objective, shared critic and execution rule.',
        inference='Three inherited independent fit seeds; descriptive paired results only. No significance or foundation-core acceptance inferred from three seeds.',
        scope='Synthetic recall/binding; analytic remains the inherited fixed renewal gate, not a full conditional distribution network. This fixes the complete-backend freeze/control factorial only.',
        cost='Full child CPU receipts; joint/frozen backend training changes measured separately. Tariffs are not Joules. Actual causal prefix-recomputing dynamic actor timed; evaluator full-pass time is not claimed online saving.',
        runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__, cuda=torch.cuda.is_available(),
            ncps=version('ncps'), cfc_source_sha256=sha(inspect.getfile(CfCCell))),
        inherited_manifests={str((OLD.parent/n).relative_to(REPO)):sha(OLD.parent/n)
            for n in ['PROTOCOL.json','SOURCE_FREEZE.json','CANDIDATE_FREEZE.json']},
        inputs=inputs, historical_commit='9c97642cea5478cd9e7d078a192399bef9c9efc8')
    write(output/'PROTOCOL.json', protocol)
    write(output/'SOURCE_FREEZE.json', dict(files=identity, protocol_sha256=sha(output/'PROTOCOL.json'), heldout_opened=False))
    for path in identity:
        dest = output/'source'/path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((REPO/path).read_bytes())
    return dict(sources=len(identity), inputs=len(inputs), protocol_sha256=sha(output/'PROTOCOL.json'))


def verified(output):
    frozen = json.loads((output/'SOURCE_FREEZE.json').read_text())
    if sha(output/'PROTOCOL.json') != frozen['protocol_sha256']:
        raise ValueError('Protocol changed')
    for path, digest in frozen['files'].items():
        if sha(REPO/path) != digest:
            raise ValueError('Frozen source changed: '+path)
    protocol=json.loads((output/'PROTOCOL.json').read_text())
    for path, digest in protocol['inherited_manifests'].items():
        if sha(REPO/path)!=digest:
            raise ValueError('Inherited manifest changed: '+path)
    for row in protocol['inputs'].values():
        if sha(REPO/row['path'])!=row['sha256']:
            raise ValueError('Frozen inherited checkpoint changed: '+row['path'])
    from ncps.torch import CfCCell
    actual=dict(python=platform.python_version(),torch=torch.__version__,numpy=np.__version__,cuda=torch.cuda.is_available(),
                ncps=version('ncps'),cfc_source_sha256=sha(inspect.getfile(CfCCell)))
    if actual!=protocol['runtime']:
        raise ValueError('Frozen runtime identity changed')
    return protocol


def validation(models, controller, values):
    x, dt, y = tensors(values)
    result = {}
    with torch.no_grad():
        for family, model in models.items():
            logits = all_logits(model, x, dt)
            stats = replay(logits, policy_values(controller, logits, dt), dt, y)
            result[family] = {k: float(stats[k].float().mean()) for k in
                ('value_utility', 'light_utility', 'value_accuracy', 'light_accuracy', 'initial_stop', 'read_count', 'initial_selected')}
    return result


def train(output, task, seed, mode):
    protocol = verified(output)
    directory = output/'fits'/f'{task}_s{seed}_{mode}'
    directory.mkdir(parents=True, exist_ok=False)
    torch.manual_seed(seed+140000)
    controller = ValueController()
    models, initial = {}, {}
    for family in FAMILIES:
        job = f'{task}_s{seed}_joint_{family}'
        model, _, _, original_entry = load_selected(OLD, job)
        if original_entry['sha256']!=protocol['inputs'][job]['sha256']:
            raise ValueError('Loaded inherited candidate differs from R14 freeze')
        if mode == 'frozen_backend':
            model.requires_grad_(False)
        models[family] = model
        initial[family] = model_hash(model)
    parameters = list(controller.parameters())
    parameters += [p for model in models.values() for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(parameters, lr=protocol['learning_rate'])
    train_data, val = dataset(task, 'train'), dataset(task, 'val')
    write(directory/'DATA.json', {name: values['sha256'] for name, values in [('train', train_data), ('val', val)]})
    rng = np.random.default_rng(seed+141000)
    gradients = {family: dict(encoder=0, core=0, readout=0) for family in FAMILIES}
    trace, validations = [], []

    def snapshot(step):
        return dict(step=step, task=task, seed=seed, mode=mode,
            models={name: dict(config=m.config, state=copy.deepcopy(m.state_dict())) for name,m in models.items()},
            controller=copy.deepcopy(controller.state_dict()), initial_hashes=initial,
            protocol_sha256=sha(output/'PROTOCOL.json'))

    metrics = validation(models, controller, val)
    best_score = np.mean([v['value_utility'] for v in metrics.values()])
    best, best_metrics = snapshot(0), metrics
    validations.append(dict(step=0, score=float(best_score), cores=metrics))
    begin = time.process_time()
    for step in range(1, protocol['updates']+1):
        ids = rng.integers(len(train_data['y']), size=protocol['batch_size'])
        x, dt, y = tensors(train_data, ids)
        optimizer.zero_grad(set_to_none=True)
        losses, detached = [], {}
        for family, model in models.items():
            logits = all_logits(model, x, dt)
            q = policy_values(controller, logits, dt)
            target, _, _ = realized_returns(logits, q, dt, y)
            ce = F.cross_entropy(logits.flatten(0, 1), y[:, None].expand(logits.shape[:2]).flatten())
            # READ is illegal at terminal; STOP remains legal at every prefix.
            qloss = ((q[..., 0]-target[..., 0]).square().sum() +
                     (q[:, :-1, 1]-target[:, :-1, 1]).square().sum()) / (q.numel()-len(x))
            losses.append(ce+qloss)
            detached[family] = dict(ce=float(ce.detach()), value_mse=float(qloss.detach()))
        loss = torch.stack(losses).mean()
        loss.backward()
        for family, model in models.items():
            for group in gradients[family]:
                params = getattr(model, group).parameters()
                nonzero = any(p.grad is not None and bool(torch.count_nonzero(p.grad)) for p in params)
                gradients[family][group] += int(nonzero)
        norm = torch.nn.utils.clip_grad_norm_(parameters, protocol['grad_clip'])
        if not torch.isfinite(loss) or not torch.isfinite(norm):
            raise FloatingPointError('Nonfinite loss or gradient')
        optimizer.step()
        trace.append(dict(step=step, loss=float(loss.detach()), cores=detached, ids=ids.tolist(), cpu=time.process_time()-begin))
        if step % protocol['validate_every'] == 0 or step == protocol['updates']:
            metrics = validation(models, controller, val)
            score = float(np.mean([v['value_utility'] for v in metrics.values()]))
            validations.append(dict(step=step, score=score, cores=metrics))
            if score > best_score + 1e-12:
                best_score, best, best_metrics = score, snapshot(step), metrics
    final = snapshot(protocol['updates'])
    torch.save(final, directory/'final.pt')
    torch.save(best, directory/'selected.pt')
    changed = {}
    for family, model in models.items():
        model.load_state_dict(best['models'][family]['state'])
        changed[family] = model_hash(model) != initial[family]
    if mode == 'frozen_backend' and any(changed.values()):
        raise AssertionError('A fully frozen backend changed')
    controller.load_state_dict(best['controller'])
    from .engine import online_rollout
    alignment={}
    with torch.no_grad():
        vx,vdt,vy=tensors(val)
        for family,model in models.items():
            v_logits=all_logits(model,vx,vdt)
            offline=replay(v_logits,policy_values(controller,v_logits,vdt),vdt,vy)
            online=online_rollout(model,controller,vx,vdt,vy)
            alignment[family]=dict(reads=int((offline['read_count']!=online['reads']).sum()),
                predictions=int((offline['terminal_prediction']!=online['prediction']).sum()))
    write(directory/'ONLINE_VALIDATION_ALIGNMENT.json',alignment)
    if any(any(row.values()) for row in alignment.values()):
        write(directory/'FAILED.json',dict(reason='offline/online validation actor mismatch',alignment=alignment))
        raise AssertionError('Offline selection is not the actual online policy')
    ordinary = max([n for n in FAMILIES if n != 'analytic'], key=lambda n: best_metrics[n]['value_utility'])
    write(directory/'TRACE.json', trace)
    write(directory/'SUMMARY.json', dict(task=task, seed=seed, mode=mode, selected_step=best['step'],
        selection_score=float(best_score), validations=validations, ordinary_selected=ordinary,
        selected_checkpoint_sha256=sha(directory/'selected.pt'), final_checkpoint_sha256=sha(directory/'final.pt'),
        backend_changed=changed, nonzero_gradient_steps=gradients,
        parameters={n:sum(p.numel() for p in m.parameters()) for n,m in models.items()},
        controller_parameters=sum(p.numel() for p in controller.parameters()),
        body_training_cpu=time.process_time()-begin, initial_hashes=initial, heldout_opened=False,
        online_validation_alignment=alignment))
    return dict(task=task, seed=seed, mode=mode, step=best['step'], ordinary=ordinary, score=float(best_score))


def candidates(output):
    protocol = verified(output)
    frozen = {}
    for task in TASKS:
        for seed in SEEDS:
            for mode in MODES:
                path = output/'fits'/f'{task}_s{seed}_{mode}'
                summary = json.loads((path/'SUMMARY.json').read_text())
                if sha(path/'selected.pt') != summary['selected_checkpoint_sha256']:
                    raise ValueError('Checkpoint changed')
                frozen[str(path.relative_to(output))] = dict(sha256=summary['selected_checkpoint_sha256'], ordinary=summary['ordinary_selected'])
    write(output/'CANDIDATE_FREEZE.json', dict(candidates=frozen, protocol_sha256=sha(output/'PROTOCOL.json'), heldout_opened=False))
    return dict(groups=len(frozen), backends=len(frozen)*len(FAMILIES))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['freeze','train','candidates'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', choices=list(TASKS))
    parser.add_argument('--seed', type=int)
    parser.add_argument('--mode', choices=list(MODES))
    parser.add_argument('--updates', type=int, default=256)
    args = parser.parse_args()
    configure()
    if args.command == 'freeze': result = freeze(args.output, args.updates)
    elif args.command == 'train': result = train(args.output, args.task, args.seed, args.mode)
    else: result = candidates(args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()

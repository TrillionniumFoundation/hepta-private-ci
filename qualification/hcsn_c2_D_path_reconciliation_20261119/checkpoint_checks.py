"""Read serialized tensors and moments; never constructs or restores an optimizer."""
import hashlib
import inspect
import json
import random
from pathlib import Path
import sys

from audit_io import require, construction
from bound_io import identity


def equal(left, right):
    import torch
    if torch.is_tensor(left):
        return (torch.is_tensor(right) and left.dtype == right.dtype and left.shape == right.shape
                and torch.equal(left, right))
    if isinstance(left, dict):
        return isinstance(right, dict) and left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
    if isinstance(left, (tuple, list)):
        return type(left) is type(right) and len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def semantic_digest(value):
    """Independently implement the frozen writer's documented byte serialization."""
    import torch
    digest = hashlib.sha256()
    def visit(v):
        if torch.is_tensor(v):
            t = v.detach().cpu().contiguous()
            digest.update(json.dumps(['tensor', str(t.dtype), list(t.shape)]).encode())
            digest.update(t.numpy().tobytes())
        elif isinstance(v, dict):
            digest.update(b'dict')
            for key in sorted(v, key=lambda k: (type(k).__name__, repr(k))):
                visit(key)
                visit(v[key])
        elif isinstance(v, (tuple, list)):
            digest.update(type(v).__name__.encode())
            for child in v:
                visit(child)
        else:
            digest.update(json.dumps([type(v).__name__, v], allow_nan=False).encode())
    visit(value)
    return digest.hexdigest()


def network_digest(state):
    digest = hashlib.sha256()
    prefix = 'core.network.'
    selected = {k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)}
    require(selected, 'missing inner network state')
    for name, tensor in sorted(selected.items()):
        value = tensor.detach().cpu().contiguous()
        raw = json.dumps([name, str(value.dtype), list(value.shape)], sort_keys=True,
                         separators=(',', ':'), allow_nan=False) + '\n'
        digest.update(raw.encode())
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def model_and_groups(context, fit_plan, initial, source_map):
    import torch
    source = Path(context['source']).resolve()
    sys.path.insert(0, str(source/'proposals/localization-v3'))
    import cores
    from hcsn_study_support import sources
    require(Path(cores.__file__).resolve() == source/'proposals/localization-v3/cores.py', 'imported wrong core')
    cfg = construction(fit_plan)
    require(initial['model_configuration'] == cfg, 'initial config differs')
    model = cores.CoreStudyModel(**cfg)
    require(equal(dict(model.state_dict()), dict(initial['model'])), 'seeded constructor differs from original initial')
    require(sources(model) == source_map, 'actually loaded source map differs')
    for name, module in list(sys.modules.items()):
        if name.startswith('qualification.hcsn_differentiable') or name in ('cores', 'frozen_tables', 'hcsn_study_support'):
            path = Path(module.__file__).resolve()
            require(path.is_relative_to(source) and str(path) in source_map
                    and identity(path)['sha256'] == source_map[str(path)], 'loaded module identity')
    grouped = {}
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            hints = getattr(parameter, '_optim', {})
            require(isinstance(hints, dict) and not set(hints)-{'lr', 'weight_decay'}, 'optimizer hints')
            grouped.setdefault((hints.get('lr', fit_plan['learning_rate']), hints.get('weight_decay', 0.0)), []).append(name)
    groups = [{'lr': lr, 'weight_decay': decay, 'names': names} for (lr, decay), names in grouped.items()]
    frozen = {n for n, p in model.named_parameters() if not p.requires_grad} | {n for n, _ in model.named_buffers()}
    return model, groups, frozen


def validate_state(state, initial, groups, frozen, configuration, epoch, updates, data_sha,
                   expected_order=None, expected_torch=None):
    import torch
    require(state['model_configuration'] == configuration and state['data_manifest_sha256'] == data_sha,
            'checkpoint construction/data mismatch')
    require(state['epochs_completed'] == epoch and state['main_updates'] == updates, 'wrong checkpoint boundary')
    require(state['model'].keys() == initial['model'].keys(), 'model tensor membership')
    for name, value in state['model'].items():
        reference = initial['model'][name]
        require(value.dtype == reference.dtype and value.shape == reference.shape
                and bool(torch.isfinite(value).all()), 'invalid model tensor')
        if name in frozen:
            require(torch.equal(value, reference), 'frozen common/physical/buffer tensor changed')
    optimizer = state['optimizer']
    defaults = {k: v.default for k, v in inspect.signature(torch.optim.AdamW.__init__).parameters.items()
                if k not in ('self', 'params', 'lr', 'weight_decay') and v.default is not inspect.Parameter.empty}
    require(len(optimizer['param_groups']) == len(groups), 'optimizer groups')
    identifiers = []
    for actual, expected in zip(optimizer['param_groups'], groups):
        require(actual['lr'] == expected['lr'] and actual['weight_decay'] == expected['weight_decay']
                and all(actual.get(k, object()) == v for k, v in defaults.items()), 'optimizer hyperparameters')
        require(len(actual['params']) == len(expected['names']), 'optimizer parameter count')
        for ident, name in zip(actual['params'], expected['names']):
            identifiers.append(ident)
            moments = optimizer['state'][ident]
            require(set(moments) == {'step', 'exp_avg', 'exp_avg_sq'}
                    and float(moments['step']) == updates, 'optimizer counter/fields')
            for key in ('exp_avg', 'exp_avg_sq'):
                value, tensor = moments[key], state['model'][name]
                require(value.dtype == tensor.dtype and value.shape == tensor.shape
                        and bool(torch.isfinite(value).all()), 'Adam moment shape/dtype/finiteness')
            second = moments['exp_avg_sq']
            second = torch.view_as_real(second) if second.is_complex() else second
            require(bool((second >= 0).all()), 'negative Adam second moment')
    require(len(set(identifiers)) == len(identifiers) and set(identifiers) == set(optimizer['state']), 'duplicate/missing optimizer state')
    random.Random().setstate(state['order_rng'])
    torch.Generator(device='cpu').set_state(state['torch_rng'])
    if expected_order is not None:
        require(equal(state['order_rng'], expected_order), 'saved order RNG differs from journal boundary')
    if expected_torch is not None:
        require(torch.equal(state['torch_rng'], expected_torch), 'unexpected Torch RNG change in deterministic HCSN')
    return {'epoch': epoch, 'main_updates': updates, 'network_sha256': network_digest(state['model']),
            'model_semantic_sha256': semantic_digest(state['model'])}


def validate_witness(parent, restored, witness, parent_item, restored_item, parent_wall, source_map, work):
    require(equal(parent, restored), 'resume-start is not exact parent last state')
    require(witness['schema'] == 'hcsn-c2-before-first-step-witness-v1'
            and witness['checkpoint'] == restored_item and witness['parent_last'] == parent_item
            and witness['semantic_sha256'] == semantic_digest(restored), 'witness tensor/byte identity')
    require(witness['new_optimizer_steps_before_receipt'] == 0
            and witness['actual_restored_state_equal_parent_last'] is True
            and witness['parent_complete_outer_wall_charged'] == parent_wall
            and witness['source'] == source_map and witness['discarded_parent_work'] == work,
            'witness source/work/cost mismatch')

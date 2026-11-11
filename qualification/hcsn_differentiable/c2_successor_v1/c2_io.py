"""Byte-bound C2 admission, immutable writes, and semantic checkpoint identities."""
from dataclasses import dataclass
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
from types import SimpleNamespace

import torch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'recovery_v1'))
from c2_durable import publish_once, publish_checkpoint, append_receipt, read_receipts

from c2_boundary import require, validate_boundary, terminal_guard


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def identity(path):
    path = Path(path)
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def sync_directory(path):
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def exclusive_json(path, value):
    path = Path(path)
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    return publish_once(path, lambda stream: stream.write(raw),
                        lambda tmp: tmp.read_bytes() == raw, max_bytes=1 << 26)


def immutable_checkpoint(path, value):
    path = Path(path)
    def validate(tmp):
        loaded = torch.load(tmp, weights_only=True, map_location='cpu')
        return state_equal(loaded, value)
    return publish_checkpoint(path, lambda stream: torch.save(value, stream),
                              validate, max_bytes=1 << 32)


def atomic_alias(source, target):
    """Publish a complete immutable checkpoint through a mutable convenience name."""
    source, target = Path(source), Path(target)
    temporary = target.with_name(target.name + '.tmp')
    with temporary.open('xb') as stream, source.open('rb') as original:
        for block in iter(lambda: original.read(1024 * 1024), b''):
            stream.write(block)
        stream.flush()
        os.fsync(stream.fileno())
    require(sha(source) == sha(temporary), 'checkpoint alias copy differs')
    temporary.replace(target)
    sync_directory(target.parent)
    return identity(target)


def state_equal(left, right):
    if torch.is_tensor(left):
        return torch.is_tensor(right) and left.dtype == right.dtype and left.shape == right.shape and torch.equal(left, right)
    if isinstance(left, dict):
        return isinstance(right, dict) and left.keys() == right.keys() and all(state_equal(left[k], right[k]) for k in left)
    if isinstance(left, (tuple, list)):
        return type(left) is type(right) and len(left) == len(right) and all(state_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def semantic_digest(value):
    digest = hashlib.sha256()
    def visit(item):
        if torch.is_tensor(item):
            tensor = item.detach().cpu().contiguous()
            digest.update(json.dumps(['tensor', str(tensor.dtype), list(tensor.shape)]).encode())
            digest.update(tensor.numpy().tobytes())
        elif isinstance(item, dict):
            digest.update(b'dict')
            for key in sorted(item, key=lambda k: (type(k).__name__, repr(k))):
                visit(key)
                visit(item[key])
        elif isinstance(item, (tuple, list)):
            digest.update(type(item).__name__.encode())
            for child in item:
                visit(child)
        else:
            digest.update(json.dumps([type(item).__name__, item], allow_nan=False).encode())
    visit(value)
    return digest.hexdigest()


def runtime_identity():
    value = {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
        'resolved_executable_sha256': sha(Path(sys.executable).resolve()), 'packages': {}}
    for name in ('torch', 'numpy', 'mpmath', 'ncps', 'spikingjelly', 'einops', 'torchvision'):
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            value['packages'][name] = {'installed': False}
            continue
        record = distribution.read_text('RECORD')
        value['packages'][name] = {'version': distribution.version,
            'record_sha256': hashlib.sha256(record.encode()).hexdigest() if record else None}
    return value


def bind_study(source):
    source = Path(source).resolve()
    directory = source / 'proposals/localization-v3'
    sys.path.insert(0, str(directory))
    cores = importlib.import_module('cores')
    require(Path(cores.__file__).resolve() == directory / 'cores.py', 'wrong imported temporal core origin')
    support = importlib.import_module('hcsn_study_support')
    capacity = importlib.import_module('capacity')
    episodes = importlib.import_module('episodes')
    require(Path(support.__file__).resolve() == directory / 'hcsn_study_support.py'
            and Path(capacity.__file__).resolve() == source / 'proposals/localization-v2/capacity.py'
            and Path(episodes.__file__).resolve() == source / 'proposals/localization-v2/episodes.py',
            'wrong imported helper/data source origin')
    spec = importlib.util.spec_from_file_location('exact_v8_helpers_for_c2', directory / 'train.py')
    training = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(training)
    return SimpleNamespace(root=source, CoreStudyModel=cores.CoreStudyModel,
        tensor_digest=cores.tensor_digest, sources=support.sources, batches=support.batches,
        backward_effective_batch=support.backward_effective_batch, adamw=capacity.adamw,
        read_episodes=episodes.read_episodes, metrics=training.metrics,
        aggregate_training_objectives=training.aggregate_training_objectives, peak_rss=training.peak_rss)


def verify_files(identities):
    for name, expected in identities.items():
        require(identity(Path(name)) == expected, 'bound file changed: ' + name)


@dataclass
class BoundParent:
    parent: Path
    outer: dict
    prior: dict
    plan: dict
    state: dict
    best: dict
    initial: dict
    events: list
    data: dict
    manifest: dict
    boundary: dict
    eligibility: dict
    study: object
    inputs: dict
    sources: dict
    runtime: dict


def bind_parent(parent, outer_path, source, contract, *, data_reader=None):
    """Validate a real soft-wall parent; no optimizer step or forward is performed.

    The optional reader exists for explicitly synthetic software fixtures. The
    standalone runner always uses the exact original prepared-data reader.
    """
    parent, outer_path = Path(parent).resolve(), Path(outer_path).resolve()
    inputs = {}
    def read(path, digest=None, json_value=True):
        path = Path(path)
        require(path.is_file() and not path.is_symlink(), 'missing/nonregular parent input')
        item = identity(path)
        require(digest is None or item['sha256'] == digest, 'parent input hash differs: ' + str(path))
        require(str(path) not in inputs or inputs[str(path)] == item, 'parent input changed while reading')
        inputs[str(path)] = item
        return json.loads(path.read_bytes()) if json_value else path
    campaign = read(parent.parent / 'RESULT.json', contract['parent_campaign_result_sha256'])
    outer = read(outer_path)
    matches = [r for r in campaign['attempts'] if r['name'] == parent.name]
    require(len(matches) == 1 and matches[0] == outer, 'outer is not the bound original terminal roster row')
    prior = read(parent / 'result.json', outer['result_sha256'])
    plan = read(parent / 'plan.json', prior['plan_sha256'])
    require(plan['manifest_sha256'] == contract['data_manifest_sha256'], 'C2 data contract differs')
    require(prior['source_before'] == prior['source_after'], 'parent source evidence changed')
    runtime_file = read(contract['runtime_identity_path'], contract['runtime_identity_sha256'])
    actual_runtime = runtime_identity()
    require(actual_runtime == runtime_file, 'runtime differs from the original source-bound environment')
    require(torch.__version__ == prior['torch_version'] and torch.version.git_version == prior['torch_git_version'],
            'Torch runtime/build differs from original training')
    source = Path(source).resolve()
    core_path = str(source / 'proposals/localization-v3/cores.py')
    require(core_path in prior['source_before'], 'C2 must import the actual original v8 source path')
    sources = {}
    for name, digest in prior['source_before'].items():
        path = read(name, digest, False)
        sources[str(path)] = inputs[str(path)]
    study = bind_study(source)
    state_files = {'initial': ('initial.pt', 'initialization_sha256'),
        'state': ('last.pt', 'last_checkpoint_sha256'), 'best': ('best.pt', 'best_checkpoint_sha256')}
    payloads = {}
    for key, (name, field) in state_files.items():
        path = read(parent / name, prior[field], False)
        payloads[key] = torch.load(path, weights_only=True, map_location='cpu')
    if 'interrupted_checkpoint_sha256' in prior:
        read(parent / 'interrupted.pt', prior['interrupted_checkpoint_sha256'], False)
    event_path = read(parent / 'events.jsonl', prior['events_sha256'], False)
    events = [json.loads(line) for line in event_path.read_bytes().splitlines()]
    require(events[-1].get('kind') == 'finished' and events[-1].get('status') == 'budget_exhausted',
            'parent journal is not a complete soft-wall terminal journal')
    data, _, manifest = (data_reader or study.read_episodes)(plan['prepared'], plan['manifest_sha256'])
    require(manifest['mode'] == 'all-development' and manifest.get('confirmation_access') is False,
            'C2 prepared scope is not sealed ABC/D')
    require(manifest['frontend_sha256'] == prior['frontend_sha256'], 'prepared frontend identity differs')
    require(len(data['train']) == prior['episodes_train']
            and sum(len(r['y']) for r in data['train']) == prior['train_events']
            and sum(len(r['y']) for r in data['dev']) == prior['dev_events'], 'full training/development population differs')
    prepared = Path(plan['prepared']).resolve()
    read(prepared / 'data-manifest.json', plan['manifest_sha256'], False)
    read(prepared / 'frontend.json', manifest['frontend_sha256'], False)
    for entry in manifest['episodes']:
        require(entry['partition'] in ('train', 'dev'), 'unexpected confirmation partition')
        path = (prepared / entry['path']).resolve()
        require(path.is_relative_to(prepared), 'prepared episode escapes bound root')
        read(path, entry['sha256'], False)
    boundary = validate_boundary(checkpoint=payloads['state'], best=payloads['best'], initial=payloads['initial'],
        events=events, plan=plan, episodes=data['train'], model_factory=study.CoreStudyModel,
        optimizer_factory=study.adamw, candidate_origin='last.pt')
    eligibility = terminal_guard(outer=outer, report=prior, plan=plan, boundary=boundary,
        max_active_wall=contract['cumulative_active_wall_seconds'], max_epochs=contract['maximum_epochs'])
    require(prior['model_configuration'] == payloads['state']['model_configuration'], 'report/last construction differs')
    require(prior['best_epoch'] == boundary['stopping']['best_epoch'], 'report best epoch differs from retained prefix')
    verify_files(inputs)
    return BoundParent(parent, outer, prior, plan, payloads['state'], payloads['best'], payloads['initial'],
        events, data, manifest, boundary, eligibility, study, inputs, sources, actual_runtime)

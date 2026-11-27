"""Numeric-only evidence helpers for the regenerative task-value extension."""

import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ..hcsn_free_boundary_v1.model import HCSNClassifier
from ..hcsn_free_boundary_v1.training import load_weights


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
V1 = PACKAGE.with_name('hcsn_free_boundary_v1')
BACKBONE_RUN = V1 / 'results/study001/runs/mnist/free_dual/9101'
BACKBONE_SHA = '069ecacf9fa21cb8e4360893a2d6aa68621a1860d4baa6b9ae1c7343df289cfd'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as out:
        json.dump(value, out, indent=2, sort_keys=True, allow_nan=False)
        out.write('\n')


def load_backbone():
    checkpoint = BACKBONE_RUN / 'selected.npz'
    if sha(checkpoint) != BACKBONE_SHA:
        raise ValueError('Frozen MNIST backbone checkpoint changed')
    summary = read_json(BACKBONE_RUN / 'summary.json')
    model = HCSNClassifier(**summary['selected_model_config']).cpu().eval()
    load_weights(checkpoint, model)
    model.requires_grad_(False)
    return model


def verify_registration(output):
    registration = read_json(Path(output) / 'REGISTRATION.json')
    for name, digest in registration['files'].items():
        if sha(REPOSITORY / name) != digest:
            raise ValueError('Registered source/data changed: ' + name)
    return registration


def verify_selection(output):
    verify_registration(output)
    lock = read_json(Path(output) / 'SELECTION_LOCK.json')
    for name, digest in lock['files'].items():
        if sha(Path(output) / name) != digest:
            raise ValueError('Selected controller or teacher changed: ' + name)
    return lock


def save_state(path, state):
    """Generic nested tensor/primitive state; no pickle or opaque objects."""
    arrays = {}

    def encode(value):
        if isinstance(value, torch.Tensor):
            key = 'tensor_' + str(len(arrays))
            arrays[key] = value.detach().cpu().numpy()
            return {'tensor': key}
        if isinstance(value, dict):
            return {'dict': {key: encode(item) for key, item in value.items()}}
        if isinstance(value, list):
            return {'list': [encode(item) for item in value]}
        if value is None or isinstance(value, (str, int, float, bool)):
            return {'scalar': value}
        raise TypeError('State contains an unsupported object')

    tree = encode(state)
    arrays['_tree_utf8'] = np.frombuffer(json.dumps(tree, sort_keys=True).encode(), dtype=np.uint8)
    with Path(path).open('xb') as stream:
        np.savez_compressed(stream, **arrays)
    return sha(path)


def load_state(path):
    with np.load(path, allow_pickle=False) as archive:
        tree = json.loads(archive['_tree_utf8'].tobytes())

        def decode(node):
            if 'tensor' in node:
                return torch.from_numpy(np.array(archive[node['tensor']], copy=True))
            if 'dict' in node:
                return {key: decode(value) for key, value in node['dict'].items()}
            if 'list' in node:
                return [decode(value) for value in node['list']]
            return node['scalar']

        return decode(tree)


def state_identity(state):
    def encode(value):
        if isinstance(value, torch.Tensor):
            data = value.detach().cpu().numpy()
            return {'dtype': str(data.dtype), 'shape': list(data.shape),
                    'sha256': hashlib.sha256(data.tobytes()).hexdigest()}
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(encode(state), sort_keys=True).encode()).hexdigest()

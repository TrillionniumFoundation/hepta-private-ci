"""New image identities, causal frozen-backbone traces and a train-only model."""

from pathlib import Path
import time

import numpy as np
import torch

from .task_value import ObservationModel
from .task_value_common import V1, sha, read_json, write_json


def prepare_fresh(raw_root, output):
    """Reproduce all 640 previously used test episodes before taking 640:1024."""
    from ..continuous_spiking_network import data as reader

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    old = read_json(V1 / 'data/study001/mnist.json')
    native = read_json(V1 / 'data/native003/fresh_mnist.json')
    source = read_json(V1 / 'data/study001/SOURCES.json')
    raw_hashes = {}
    for item in source['files']:
        if item['path'].startswith('mnist/'):
            path = Path(raw_root) / item['path']
            if sha(path) != item['sha256'] or path.stat().st_size != item['bytes']:
                raise ValueError('Original raw MNIST differs')
            raw_hashes[item['path']] = item['sha256']
    data = reader._real_split('mnist', 1024, 'test', 912201, 32,
                              reader._mnist(Path(raw_root)), None)
    data.validate()
    for transform in old['transforms']:
        if transform['fit_split'] != 'train':
            raise ValueError('Transform must be fitted on original training only')
        lo, hi = transform['columns']
        presence = data.x[..., transform['presence_column']:transform['presence_column'] + 1] > 0
        mean, std = (np.asarray(transform[key], dtype=np.float32) for key in ('mean', 'std'))
        data.x[..., lo:hi] = np.where(presence, (data.x[..., lo:hi] - mean) / std, 0)
    old_paths = [(V1 / 'data/study001/mnist.npz', 0, 512),
                 (V1 / 'data/native003/fresh_mnist.npz', 512, 640)]
    reproduction = []
    for path, lo, hi in old_paths:
        with np.load(path, allow_pickle=False) as archive:
            comparisons = {'x': np.array_equal(archive['test_x'], data.x[lo:hi]),
                           'dt': np.array_equal(archive['test_dt'], data.dt[lo:hi]),
                           'labels': np.array_equal(archive['test_y'][:, -1], data.y[lo:hi])}
        if not all(comparisons.values()):
            raise ValueError('Previously used test prefix does not reproduce')
        reproduction.append({'path': str(path), 'sha256': sha(path), 'checks': comparisons})
    image_ids = data.metadata['image_source_ids'][640:1024]
    episode_ids = data.sample_ids[640:1024].tolist()
    if len(set(image_ids)) != 384:
        raise ValueError('New image identities must be unique')
    disjoint = {}
    for split, metadata in {**old['splits'], 'native003': native['splits']['test']}.items():
        overlap = set(image_ids) & set(metadata['image_source_ids'])
        if overlap:
            raise ValueError('New cohort overlaps an earlier image source')
        disjoint[split] = 0
    destination = output / 'fresh_mnist.npz'
    np.savez_compressed(destination, x=data.x[640:1024], dt=data.dt[640:1024],
                        labels=data.y[640:1024])
    write_json(output / 'fresh_mnist.json', {
        'schema': 'hcsn-v2-regenerative-task-fresh-data.v1', 'sha256': sha(destination),
        'seed': 912201, 'slice': [640, 1024], 'images': 384, 'tasks_per_stream': 3,
        'streams': 128, 'queue_permutation_seed': 73013,
        'image_source_ids': image_ids, 'episode_ids': episode_ids,
        'disjoint_image_source_counts': disjoint, 'prefix_reproduction': reproduction,
        'raw_mnist_sha256': raw_hashes, 'transforms': old['transforms'],
        'source_generation_only': True, 'inference_performed': False,
        'queue_assumption': 'Deterministically shuffled distinct images; approximate iid restart model, not a population independence theorem'})


def trace_split(model, split, output, fresh_path=None):
    start = time.process_time()
    if split == 'test':
        if fresh_path is None:
            raise ValueError('Fresh test path must be explicitly supplied after lock')
        path = Path(fresh_path)
        with np.load(path, allow_pickle=False) as archive:
            x, dt, labels = (np.array(archive[key], copy=True) for key in ('x', 'dt', 'labels'))
    else:
        path = V1 / 'data/study001/mnist.npz'
        with np.load(path, allow_pickle=False) as archive:
            x = np.array(archive[split + '_x'], copy=True)
            dt = np.array(archive[split + '_dt'], copy=True)
            labels = np.array(archive[split + '_y'][:, -1], copy=True)
    probabilities, predictions = [], []
    with torch.no_grad():
        for first in range(0, len(x), 32):
            logits = model(torch.from_numpy(x[first:first + 32]),
                           torch.from_numpy(dt[first:first + 32]),
                           return_sequence=True, return_aux=False)
            if not torch.isfinite(logits).all():
                raise FloatingPointError('Nonfinite causal prefix logits')
            probabilities.append(logits.softmax(-1).amax(-1).numpy())
            predictions.append(logits.argmax(-1).numpy())
    confidence, prediction = map(np.concatenate, (probabilities, predictions))
    correct = prediction == labels[:, None]
    target = Path(output) / (split + '.npz')
    with target.open('xb') as stream:
        np.savez_compressed(stream, confidence=confidence, prediction=prediction,
                            correct=correct, labels=labels)
    return {'source_sha256': sha(path), 'trace_sha256': sha(target), 'images': len(x),
            'all_prefix_model_steps': int(np.prod(confidence.shape)),
            'cpu_seconds': time.process_time() - start,
            'scope': 'Full causal prefix cache; actual complete inference cost, never counted as avoided computation'}


def fit_observation_model(trace_path, output, bins=4, shrinkage=5.0):
    with np.load(trace_path, allow_pickle=False) as archive:
        confidence = np.array(archive['confidence'], copy=True)
        correct = np.array(archive['correct'], copy=True)
    confidence = np.rint(confidence.astype(np.float64) * 10000) / 10000
    n, k = confidence.shape
    edges = np.zeros((k + 1, bins - 1))
    edges[1:] = np.quantile(confidence, np.arange(1, bins) / bins, axis=0).T
    state = np.stack([np.searchsorted(edges[t + 1], confidence[:, t], side='right')
                      for t in range(k)], axis=1)
    counts = np.zeros((k + 1, bins), dtype=np.int64)
    reward = np.zeros_like(counts, dtype=float)
    transition = np.zeros((k + 1, bins, bins))
    for prefix in range(1, k + 1):
        global_correct = correct[:, prefix - 1].mean()
        for z in range(bins):
            mask = state[:, prefix - 1] == z
            counts[prefix, z] = mask.sum()
            reward[prefix, z] = ((correct[mask, prefix - 1].sum() + shrinkage * global_correct)
                                 / (mask.sum() + shrinkage))
        if prefix < k:
            next_counts = np.bincount(state[:, prefix], minlength=bins)
            global_next = (next_counts + 1) / (n + bins)
            for z in range(bins):
                local = np.bincount(state[state[:, prefix - 1] == z, prefix], minlength=bins)
                transition[prefix, z] = (local + shrinkage * global_next) / (local.sum() + shrinkage)
    initial = np.bincount(state[:, 0], minlength=bins).astype(float) / n
    valid = np.ones((k + 1, bins), dtype=bool)
    valid[0] = False
    model = ObservationModel(reward, transition, initial, valid)
    model.validate()
    path = Path(output) / 'observation_model.npz'
    with path.open('xb') as stream:
        np.savez_compressed(stream, reward=reward, transition=transition,
                            initial=initial, valid=valid, edges=edges, counts=counts)
    write_json(Path(output) / 'OBSERVATION_MODEL.json', {
        'fit_split': 'train', 'images': n, 'confidence_bins': bins,
        'confidence_quantum': 0.0001,
        'shrinkage_pseudocount': shrinkage, 'empty_prefix_bins': int((counts[1:] == 0).sum()),
        'trace_sha256': sha(trace_path), 'model_sha256': sha(path),
        'model_scope': 'Coarsened, time-inhomogeneous Markov approximation to fixed neural traces; not an exact belief process',
        'reward': 'Observed training classification correctness, smoothed toward prefix-specific training mean',
        'transition': 'Training next-confidence-bin frequencies, smoothed toward prefix-specific next-bin distribution',
        'no_test_or_validation_fitting': True})
    return model, edges


def load_observation_model(path):
    with np.load(path, allow_pickle=False) as archive:
        model = ObservationModel(*(np.array(archive[key], copy=True)
                                 for key in ('reward', 'transition', 'initial', 'valid')))
        edges = np.array(archive['edges'], copy=True)
    model.validate()
    return model, edges


def load_trace(path):
    with np.load(path, allow_pickle=False) as archive:
        return {name: np.array(archive[name], copy=True) for name in archive.files}

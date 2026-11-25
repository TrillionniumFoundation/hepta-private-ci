"""Independent NumPy reconstruction of all saved training-test scalar metrics.

No model, Torch, trainer, or dataset module is imported. This verifies the
reported metrics against the committed logits, labels and stopping timestamps;
it does not independently replay the physical dynamics or infer a causal claim.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(logits, raw):
    a = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(raw['labels'], dtype=np.int64)
    late = np.asarray(raw['late_step'], dtype=np.int64)
    source = np.asarray(raw['source'], dtype=np.int64)
    if a.ndim != 3 or a.shape[1:] != (len(labels), 2) or not np.isfinite(a).all():
        raise ValueError('invalid finite prefix logits')
    centered = a - a.max(-1, keepdims=True)
    p = np.exp(centered)
    p /= p.sum(-1, keepdims=True)
    columns = np.arange(len(labels))
    final = p[-1]
    prediction = final.argmax(-1)
    eligible = p.max(-1) >= .8
    eligible[-1] = True
    stop = eligible.argmax(0)
    stop_correct = p[stop, columns].argmax(-1) == labels
    targets = np.eye(2)[labels]
    ce = (np.log(np.exp(centered[-1]).sum(-1)) - centered[-1, columns, labels]).mean()
    by_source = {str(int(s)): float((prediction[source == s] == labels[source == s]).mean())
                 for s in np.unique(source)}
    return {'accuracy': float((prediction == labels).mean()),
            'brier': float(np.square(final - targets).sum(-1).mean()),
            'cross_entropy': float(ce),
            'early_accuracy': float((p[0].argmax(-1) == labels).mean()),
            'pre_late_accuracy': float((p[late - 1, columns].argmax(-1) == labels).mean()),
            'stop_accuracy': float(stop_correct.mean()),
            'mean_stop_step': float(stop.mean()),
            'stopping_utility': float((stop_correct - .04 * stop / (len(a) - 1)).mean()),
            'stop_before_late_fraction': float((stop < late).mean()),
            'source_accuracy': by_source, 'worst_source_accuracy': min(by_source.values())}


def verify(root, output):
    root, output = Path(root), Path(output)
    if output.exists():
        raise FileExistsError('independent verification output is create-only')
    begin = time.perf_counter()
    final_path = root / 'FINAL_RESULTS.json'
    final = json.loads(final_path.read_text())
    if final['seal_sha256'] != sha(root / 'SEAL.json'):
        raise ValueError('final results do not bind the training seal')
    records = []
    for row in final['results']:
        if row['status'] != 'evaluated':
            records.append({'attempt': row['attempt'], 'status': 'unavailable'})
            continue
        directory = root / row['attempt']
        path = directory / 'test_predictions.json'
        if sha(path) != row['predictions_sha256']:
            raise ValueError('prediction bytes changed: ' + row['attempt'])
        if json.loads((directory / 'test_result.json').read_text()) != row:
            raise ValueError('aggregate and individual test result disagree')
        raw = json.loads(path.read_text())
        if raw['data_sha256'] != row['data_sha256']:
            raise ValueError('prediction data identity mismatch')
        differences = {}
        for prefix, key in [('prefix_logits', 'metrics'), ('initial_prefix_logits', 'initial_metrics')]:
            actual = metrics(raw[prefix], raw)
            for name, value in actual.items():
                if isinstance(value, dict):
                    if value != row[key][name]:
                        raise ValueError('per-source accuracy mismatch')
                else:
                    delta = abs(value - row[key][name])
                    differences[prefix + ':' + name] = delta
                    if delta > 2e-12:
                        raise ValueError('independent metric mismatch: ' + row['attempt'] + ':' + name)
        records.append({'attempt': row['attempt'], 'status': 'verified',
                        'predictions_sha256': row['predictions_sha256'],
                        'max_scalar_error': max(differences.values()),
                        'verified_scalar_count': len(differences),
                        'examples': len(raw['labels']), 'prefix_steps': len(raw['prefix_logits'])})
    report = {'schema': 1, 'method': 'independent NumPy reconstruction; no Torch/model/trainer imports',
              'final_results_sha256': sha(final_path), 'numpy': str(np.__version__),
              'rows': records, 'max_scalar_error': max((r.get('max_scalar_error', 0) for r in records), default=0),
              'wall_seconds': time.perf_counter() - begin,
              'scope': 'saved-logit metric consistency; physical trajectories not replayed'}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'verified': sum(r['status'] == 'verified' for r in records),
                      'max_scalar_error': report['max_scalar_error']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--training', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    verify(args.training, args.output)

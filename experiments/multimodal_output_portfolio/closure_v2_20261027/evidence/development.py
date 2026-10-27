"""Historical fit/validation diagnosis; no new qualification inputs are read."""

import hashlib
import json
from pathlib import Path

import numpy as np


BASE = Path('/workspace/scratch/95988d8d3ab1/ndu-continuation-evidence/study-002')
DEST = Path('/workspace/scratch/95988d8d3ab1/ndu-evidence-v2/development-001')


def projection(table, left, right):
    result = table.copy()
    for _ in range(2000):
        result *= (left / result.sum(1))[:, None]
        result *= (right / result.sum(0))[None, :]
        if max(abs(result.sum(1)-left).max(), abs(result.sum(0)-right).max()) < 1e-12:
            return result
    raise ArithmeticError('projection failed')


def fit(rows, boundaries, margin, coupling):
    bins = len(boundaries)+1
    counts = np.zeros((10, bins, 10))
    for row in rows:
        confidence = max(row['probabilities'])
        counts[row['observation'], np.searchsorted(boundaries, confidence), row['target']] += 1
    left = counts.sum(1)
    right = counts.sum(0)
    left = (left+margin/10)/(left.sum(0)+margin)
    right = (right+margin/bins)/(right.sum(0)+margin)
    result = np.zeros_like(counts)
    for target in range(10):
        independent = np.outer(left[:, target], right[:, target])
        if coupling is None:
            result[:, :, target] = independent
        else:
            raw = counts[:, :, target] + coupling*independent
            raw /= raw.sum()
            result[:, :, target] = projection(raw, left[:, target], right[:, target])
    return result


def score(law, rows, boundaries):
    likelihood = np.stack([law[r['observation'], np.searchsorted(boundaries, max(r['probabilities']))]
                           for r in rows])
    targets = np.array([r['target'] for r in rows])
    posterior = likelihood / likelihood.sum(1, keepdims=True)
    nll = -np.log(likelihood[np.arange(len(rows)), targets]).mean()
    accuracy = (posterior.argmax(1) == targets).mean()
    post_nll = -np.log(posterior[np.arange(len(rows)), targets]).mean()
    return {'conditional_nll': float(nll), 'posterior_nll': float(post_nll), 'accuracy': float(accuracy)}


def main():
    DEST.mkdir(parents=True, exist_ok=False)
    fit_rows = json.loads((BASE/'observations_fit.json').read_text())
    validation = json.loads((BASE/'observations_validation.json').read_text())
    record = {'fit_speakers': sorted({r['speaker'] for r in fit_rows}),
              'validation_speakers': sorted({r['speaker'] for r in validation}),
              'new_test_read': False, 'models': [],
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'input_sha256': {name: hashlib.sha256((BASE/name).read_bytes()).hexdigest()
                              for name in ('observations_fit.json', 'observations_validation.json')}}
    candidates = [.5, 2, 10, 50, 200, 1000, 4000]
    for bins in (2, 3, 4, 5):
        boundaries = np.quantile([max(r['probabilities']) for r in fit_rows], np.arange(1, bins)/bins)
        marginal = min(candidates, key=lambda s: score(fit(fit_rows, boundaries, s, None),
                                                       validation, boundaries)['conditional_nll'])
        for coupling in [None]+candidates:
            record['models'].append({'bins': bins, 'boundaries': boundaries.tolist(),
                'margin': marginal, 'coupling': coupling,
                **score(fit(fit_rows, boundaries, marginal, coupling), validation, boundaries)})
    (DEST/'RESULT.json').write_text(json.dumps(record, indent=2, sort_keys=True)+'\n')
    (DEST/'executed_development.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(record, sort_keys=True))


if __name__ == '__main__':
    main()

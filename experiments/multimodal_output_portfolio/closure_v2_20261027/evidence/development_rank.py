"""Historical diagnosis of the two highest-ranked frozen-observer labels."""

import hashlib
import json
from pathlib import Path

import numpy as np

from .development import BASE, projection


DEST = Path('/workspace/scratch/95988d8d3ab1/ndu-evidence-v2/development-002')


def fit(rows, margin, coupling):
    counts = np.zeros((10, 10, 10))
    for row in rows:
        first, second = np.argsort(-np.asarray(row['probabilities']), kind='stable')[:2]
        counts[first, second, row['target']] += 1
    left, right = counts.sum(1), counts.sum(0)
    left = (left+margin/10)/(left.sum(0)+margin)
    right = (right+margin/10)/(right.sum(0)+margin)
    result = np.zeros_like(counts)
    for target in range(10):
        legal = np.outer(left[:, target], right[:, target])*(1-np.eye(10))
        independent = projection(legal, left[:, target], right[:, target])
        if coupling is None:
            result[:, :, target] = independent
        else:
            raw = counts[:, :, target] + coupling*independent
            raw /= raw.sum()
            result[:, :, target] = projection(raw, left[:, target], right[:, target])
    return result


def score(law, rows):
    choices = np.array([np.argsort(-np.asarray(r['probabilities']), kind='stable')[:2] for r in rows])
    likelihood = law[choices[:, 0], choices[:, 1]]
    targets = np.array([r['target'] for r in rows])
    posterior = likelihood / likelihood.sum(1, keepdims=True)
    return {'conditional_nll': float(-np.log(likelihood[np.arange(len(rows)), targets]).mean()),
            'posterior_nll': float(-np.log(posterior[np.arange(len(rows)), targets]).mean()),
            'accuracy': float((posterior.argmax(1) == targets).mean())}


def main():
    DEST.mkdir(parents=True, exist_ok=False)
    fit_rows = json.loads((BASE/'observations_fit.json').read_text())
    validation = json.loads((BASE/'observations_validation.json').read_text())
    candidates = [.5, 2, 10, 50, 200, 1000, 4000]
    margin = min(candidates, key=lambda s: score(fit(fit_rows, s, None), validation)['conditional_nll'])
    record = {'scope': 'same event rank views; no new qualification read',
              'same_legal_support': 'top1 and top2 cannot equal, in every model',
              'models': [{'margin': margin, 'coupling': coupling,
                          **score(fit(fit_rows, margin, coupling), validation)}
                         for coupling in [None]+candidates],
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (DEST/'RESULT.json').write_text(json.dumps(record, indent=2, sort_keys=True)+'\n')
    (DEST/'executed_development_rank.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(record, sort_keys=True))


if __name__ == '__main__':
    main()

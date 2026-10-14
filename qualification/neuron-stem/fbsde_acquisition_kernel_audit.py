"""Independent arithmetic reconstruction of CV, with no policy/model imports."""
from itertools import product
import math

from four_gate_common import digest, require


def verified_counts(raw_rows, source_hashes, classes, record):
    """Direct dense arithmetic; verify all held-out folds before final refitting."""
    candidates = ('legacy', 'anchor:8', 'anchor:32', 'anchor:128', 'anchor:512')
    worlds = tuple(product(range(classes), repeat=4))
    folds = [int(h[:16], 16) % 4 for h in source_hashes]
    require(record['profile'] == 'joint_backoff_cv_v2' and
            record['fit_tuples_sha256'] == digest(raw_rows) and
            record['sources_sha256'] == digest(source_hashes) and
            record['source_folds'] == [list(p) for p in zip(source_hashes, folds)] and
            record['test_labels_used'] is False, 'kernel CV source binding mismatch')

    def table(rows, candidate):
        n = [0]*len(worlds)
        for row in rows:
            i = 0
            for x in row: i = i*classes+x
            n[i] += 1
        if candidate == 'legacy': return [v+.01 for v in n]
        strength = int(candidate.split(':')[1])
        c = [0]*classes
        yc = [[0]*classes for _ in range(classes)]
        abc = [[[0]*classes for _ in range(classes)] for _ in range(classes)]
        for y, a, b, z in rows: c[z] += 1; yc[y][z] += 1; abc[a][b][z] += 1
        return [n[i] + strength * ((c[z]+.5)/(len(rows)+classes*.5)) *
                ((yc[y][z]+.5)/(c[z]+classes*.5)) *
                ((abc[a][b][z]+.5)/(c[z]+classes**2*.5))
                for i, (y, a, b, z) in enumerate(worlds)]

    require(len(record['scores']) == len(candidates), 'complete CV grid required')
    scores = []
    for candidate, stored in zip(candidates, record['scores']):
        require(stored['candidate'] == candidate and len(stored['folds']) == 4, 'CV candidate order')
        total_loss = 0.; total_rows = 0
        for fold, summary in enumerate(stored['folds']):
            train = [r for r, f in zip(raw_rows, folds) if f != fold]
            test = [r for r, f in zip(raw_rows, folds) if f == fold]
            require(train and test, 'empty CV support')
            mass = table(train, candidate); loss = 0.
            # Four allowed histories; aggregate directly from complete model worlds.
            posterior = {}
            for pattern in ((0,), (0, 1), (0, 2), (0, 1, 2)):
                for w, value in zip(worlds, mass):
                    key = tuple((v, w[v+1]) for v in pattern)
                    vector = posterior.setdefault(key, [0.]*classes)
                    vector[w[0]] += value
            for row in test:
                for pattern in ((0,), (0, 1), (0, 2), (0, 1, 2)):
                    v = posterior[tuple((j, row[j+1]) for j in pattern)]
                    loss -= math.log(v[row[0]]/sum(v))/4
            require(summary['fold'] == fold and summary['fitting_rows'] == len(train) and
                    summary['held_rows'] == len(test) and
                    abs(summary['mean_conditional_log_loss']-loss/len(test)) < 1e-11,
                    'CV fold computation mismatch')
            total_loss += loss; total_rows += len(test)
        value = total_loss/total_rows
        require(abs(value-stored['mean_conditional_log_loss']) < 1e-11, 'CV aggregate mismatch')
        scores.append(value)
    winner = min(range(len(candidates)), key=lambda j: scores[j])
    require(record['selected'] == candidates[winner], 'CV winner mismatch')
    return table(raw_rows, candidates[winner])

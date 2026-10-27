"""Independent reconstruction of selected likelihoods and target priors."""

import json

import numpy as np


def balance(matrix, rows, columns):
    value = matrix/matrix.sum()
    for _ in range(4000):
        value = value/value.sum(axis=1, keepdims=True)*rows[:, None]
        value = value/value.sum(axis=0, keepdims=True)*columns[None, :]
        error = max(np.max(np.abs(value.sum(1)-rows)), np.max(np.abs(value.sum(0)-columns)))
        if error <= 2e-13:
            return value
    raise AssertionError('Independent matrix balance did not converge')


def reconstruct(run):
    observations = json.loads((run/'observations_fit.json').read_text())
    validation = json.loads((run/'observations_validation.json').read_text())
    selection = json.loads((run/'SELECTION.json').read_text())
    speakers = sorted({r['speaker'] for r in observations})
    confusion = np.zeros((len(speakers), 10, 10))
    rank_count = np.zeros((10, 10, 10))
    lookup, content = {}, set()
    for row in observations:
        if row['source_path'] in lookup or row['event_id'] in content:
            raise AssertionError('Duplicate training acquisition')
        lookup[row['source_path']] = row
        content.add(row['event_id'])
        confusion[speakers.index(row['speaker']), row['observation'], row['target']] += 1
        order = sorted(range(10), key=lambda i: (-row['probabilities'][i], i))
        rank_count[order[0], order[1], row['target']] += 1
    paired = np.zeros((10, 10, 100))
    for speaker in speakers:
        for left in range(10):
            for right in range(10):
                for k in range(20):
                    a = lookup[f'data/{speaker}/{left}_{speaker}_{k}.wav']
                    j = (7*k+11) % 20
                    b = lookup[f'data/{speaker}/{right}_{speaker}_{j}.wav']
                    if a['source_path'] == b['source_path']:
                        raise AssertionError('Distinct-event design contains alias side information')
                    paired[a['observation'], b['observation'], 10*left+right] += 1
    restored, errors, marginal_errors = {}, {}, {}
    for name, chosen in selection['selected'].items():
        margin, shrinkage = chosen['margin'], chosen['coupling']
        if name.startswith('pair_'):
            pooled = confusion.sum(0)
            marginal = (pooled+margin/10)/(pooled.sum(0)+margin)
            matrix = np.zeros((10, 10, 100))
            if shrinkage is not None:
                source_tables = (confusion+shrinkage*marginal[None])/(confusion.sum(1)[:, None]+shrinkage)
            for target in range(100):
                left, right = divmod(target, 10)
                base = np.outer(marginal[:, left], marginal[:, right])
                if shrinkage is None:
                    matrix[..., target] = base
                else:
                    if chosen['family'] == 'paired':
                        raw = paired[..., target]+shrinkage*base
                    else:
                        raw = sum(np.outer(table[:, left], table[:, right]) for table in source_tables)
                    matrix[..., target] = balance(raw, marginal[:, left], marginal[:, right])
            expected_left = np.column_stack([marginal[:, t//10] for t in range(100)])
            expected_right = np.column_stack([marginal[:, t % 10] for t in range(100)])
        else:
            a, b = rank_count.sum(1), rank_count.sum(0)
            left = (a+margin/10)/(a.sum(0)+margin)
            right = (b+margin/10)/(b.sum(0)+margin)
            matrix = np.zeros((10, 10, 10))
            for target in range(10):
                base = left[:, target, None]*right[None, :, target]
                np.fill_diagonal(base, 0)
                base = balance(base, left[:, target], right[:, target])
                matrix[..., target] = base if shrinkage is None else balance(
                    rank_count[..., target]+shrinkage*base, left[:, target], right[:, target])
            if np.max(abs(matrix[np.arange(10), np.arange(10)])) != 0:
                raise AssertionError('Impossible rank pairs acquired probability')
            expected_left, expected_right = left, right
        saved = np.asarray(json.loads((run/f'law_{name}.json').read_text())['table'])
        errors[name] = float(np.max(np.abs(matrix-saved)))
        marginal_errors[name] = float(max(np.max(abs(saved.sum(1)-expected_left)),
                                          np.max(abs(saved.sum(0)-expected_right))))
        if errors[name] > 1e-10 or marginal_errors[name] > 1e-10:
            raise AssertionError('Frozen law differs from independently reconstructed counts')
        restored[name] = matrix
    prior_fit = json.loads((run/'prior_fit_targets.json').read_text())
    prior_validation = json.loads((run/'prior_validation_targets.json').read_text())
    priors = json.loads((run/'PRIORS.json').read_text())
    maximum_prior_error = 0.
    for cue, arms in priors.items():
        count = np.zeros((10, 10))
        truth = [r['target'] for r in prior_validation if r['cue'] == cue]
        for row in prior_fit:
            if set(row) != {'sample_id', 'speaker', 'cue', 'target'}:
                raise AssertionError('Observation leaked into target-prior fitting')
            if row['cue'] == cue:
                count[row['target']//10, row['target'] % 10] += 1
        for arm, saved in arms.items():
            candidates = []
            for strength in (.5, 2., 10., 50., 200., 1000., 4000.):
                if arm == 'joint':
                    probability = (count+strength/100)/(count.sum()+strength)
                else:
                    probability = np.outer(count.sum(1)+strength/10, count.sum(0)+strength/10)/(count.sum()+strength)**2
                candidates.append((float(-np.log(probability.ravel()[truth]).mean()), probability.ravel()))
            best = min(candidates, key=lambda item: item[0])[1]
            maximum_prior_error = max(maximum_prior_error, float(np.max(abs(best-np.asarray(saved)))))
    if maximum_prior_error > 1e-12:
        raise AssertionError('Prior selected using a different target-only objective')
    return restored, priors, {'law_max_errors': errors, 'shared_marginal_max_errors': marginal_errors,
                              'prior_max_error': maximum_prior_error,
                              'fit_speakers': speakers, 'validation_speakers': sorted({r['speaker'] for r in validation})}

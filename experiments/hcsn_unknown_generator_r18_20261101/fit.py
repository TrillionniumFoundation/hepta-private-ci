"""Fit only from complete public training token sequences, never owner targets."""

import numpy as np


def fit(groups):
    particles, pooled, qs = [], np.zeros(4), []
    for prefixes in groups:
        sequences, distinct = [], []
        for prefix in prefixes:
            writes = prefix[prefix[:, 12] == 1]
            if len(writes) != 6:
                raise ValueError("Six public training WRITEs required")
            sequences.append(writes[:, 4:8].argmax(1))
            distinct.append(writes[-2, :4].argmax() != writes[-1, :4].argmax())
        sequence = np.stack(sequences)
        counts = np.bincount(sequence.ravel(), minlength=4)
        pi = (counts + .5) / (counts.sum() + 2)
        likelihoods = []
        candidates = [0., .1, .25, .4, .55, .7, .85, .95]
        for rho in candidates:
            likelihoods.append(np.log(rho * (sequence[:, 1:] == sequence[:, :-1])
                                      + (1 - rho) * pi[sequence[:, 1:]]).sum())
        q = float(np.clip(4 * (sum(distinct) + .5) / (len(distinct) + 1) - 3, 0, 1))
        particles.append(dict(pi=pi.tolist(), rho=candidates[int(np.argmax(likelihoods))], q=q))
        pooled += counts
        qs.append(q)
    return dict(markov_mixture=particles,
                pooled_iid=[dict(pi=((pooled + .5) / (pooled.sum() + 2)).tolist(), rho=0., q=float(np.mean(qs)))])

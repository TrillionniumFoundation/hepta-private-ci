"""Paired, fixed-bet evidence with optional stopping, conditional on the null.

D = correct(candidate) - correct(bank). Under E[D | past] <= 0 each
product of (1 + lambda*D) is a nonnegative supermartingale. A fixed mixture
inherits that property; Ville + union bound across Cells gives the boundary.
This does NOT verify iid/source assumptions, cover arbitrary drifting means,
certify future retention or authorize repeated fresh restarts of the same test.
"""
from __future__ import annotations

import math

from experiments.shared_stem_cell.wire import InputError

BETS = (0.125, 0.25, 0.5, 0.75)


def log_evidence(gains, losses):
    """Equal prior mixture, never select the best bet after seeing outcomes."""
    if any(type(v) is not int or not 0 <= v <= 8192 for v in (gains, losses)):
        raise InputError("bounded integer paired counts required")
    values = [gains*math.log1p(b) + losses*math.log1p(-b) for b in BETS]
    top = max(values)
    return top + math.log(math.fsum(math.exp(v-top) for v in values)/len(BETS))


class PairedEvidence:
    """One fresh stream, transactional batches; crossed Cells accept no more rows."""
    def __init__(self, *, cells=2, classes=4, alpha=0.025):
        if (type(cells) is not int or not 1 <= cells <= 64 or type(classes) is not int
                or not 2 <= classes <= 256 or type(alpha) not in (int, float)
                or not math.isfinite(alpha) or not 1e-6 <= alpha <= 0.05):
            raise InputError("closed sequential error budget and class profile required")
        self.cells, self.classes, self.alpha = cells, classes, alpha
        self.boundary = math.log(cells/alpha)
        self.seen = set()
        self.counts = [dict(cases=0, gains=0, losses=0, bank_correct=0,
                            candidate_correct=0, crossed=False) for _ in range(cells)]

    def update(self, ids, bank, candidate, labels, routes):
        values = (ids, bank, candidate, labels, routes)
        if (any(type(v) is not list for v in values) or not 1 <= len(ids) <= 512
                or any(len(v) != len(ids) for v in values) or len(self.seen)+len(ids) > 8192
                or any(not isinstance(v, str) or not 1 <= len(v.encode()) <= 256 for v in ids)
                or len(set(ids)) != len(ids) or self.seen.intersection(ids)):
            raise InputError("new bounded paired batch identities required")
        if (any(type(v) is not int or not 0 <= v < self.classes for a in (bank,candidate,labels) for v in a)
                or any(type(v) is not int or not 0 <= v < self.cells for v in routes)
                or any(self.counts[v]['crossed'] for v in routes)):
            raise InputError("invalid class, Cell, or already stopped Cell")
        counts = [dict(row) for row in self.counts]
        for b, p, y, cell in zip(bank, candidate, labels, routes):
            row = counts[cell]
            row['cases'] += 1
            row['bank_correct'] += int(b == y)
            row['candidate_correct'] += int(p == y)
            row['gains'] += int(p == y and b != y)
            row['losses'] += int(p != y and b == y)
        for row in counts:
            # Conservative numerical margin; no rounded displayed value is tested.
            row['crossed'] = log_evidence(row['gains'],row['losses']) >= self.boundary+1e-8
        self.counts, self.seen = counts, self.seen.union(ids)
        return self.snapshot()

    def snapshot(self):
        return {'schema':'hepta.paired-sequential-evidence.v1', 'alpha':self.alpha,
            'bets':list(BETS), 'log_boundary':self.boundary,
            'per_cell':[{'cell':i, **row, 'log_evidence':log_evidence(row['gains'],row['losses'])}
                        for i,row in enumerate(self.counts)],
            'all_crossed':all(row['crossed'] for row in self.counts),
            'assumptions_verified':False, 'retention_certified':False, 'production_accepted':False}

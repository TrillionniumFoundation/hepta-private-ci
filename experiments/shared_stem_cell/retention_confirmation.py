"""Paired fixed-candidate confirmation, separate from fitting/selection.

For each Cell, risk(candidate)-risk(bank)=P(loss)-P(gain). Use one-sided
Clopper-Pearson bounds with tail alpha/(2*Cells), then a union bound. Coverage
requires frozen candidates and iid observations within each Cell. This module
cannot verify those assumptions and NEVER issues production/retention authority.
"""
from __future__ import annotations

import math

from experiments.shared_stem_cell.wire import InputError


def upper_binomial(k, n, tail):
    """Invert P[Binomial(n,p)<=k]=tail; outward padding for float roundoff."""
    if (type(n) is not int or not 1 <= n <= 16384 or type(k) is not int
            or not 0 <= k <= n or type(tail) not in (int, float)
            or not math.isfinite(tail) or not 1e-12 <= tail < 0.5):
        raise InputError("bounded exact binomial counts/tail required")
    if k == n:
        return 1.0
    if k == 0:
        return min(1.0, -math.expm1(math.log(tail) / n) + 2e-12)
    coefficients = [math.lgamma(n+1)-math.lgamma(j+1)-math.lgamma(n-j+1) for j in range(k+1)]
    low, high = 0.0, 1.0
    for _ in range(64):
        p = (low + high) / 2
        if p == low or p == high:
            break
        values = [v+j*math.log(p)+(n-j)*math.log1p(-p) for j,v in enumerate(coefficients)]
        maximum = max(values)
        log_cdf = maximum + math.log(math.fsum(math.exp(v-maximum) for v in values))
        if log_cdf > math.log(tail):
            low = p
        else:
            high = p
    return min(1.0, high + 2e-12)


def paired_confirmation(bank, candidate, labels, routes, *, cells, classes, alpha=0.05):
    """Evaluate ONE previously selected candidate; never search these labels."""
    if (type(cells) is not int or not 1 <= cells <= 64 or type(classes) is not int
            or not 2 <= classes <= 256 or type(alpha) not in (int, float)
            or not math.isfinite(alpha) or not 1e-6 <= alpha <= 0.1
            or any(type(v) is not list for v in (bank, candidate, labels, routes))
            or not 1 <= len(labels) <= 16384 or any(len(v) != len(labels) for v in (bank,candidate,routes))):
        raise InputError("complete bounded paired confirmation required")
    if any(type(v) is not int or not 0 <= v < classes for a in (bank,candidate,labels) for v in a):
        raise InputError("exact class indices required")
    if any(type(v) is not int or not 0 <= v < cells for v in routes):
        raise InputError("exact observed Cell indices required")
    tail, rows = alpha / (2*cells), []
    for cell in range(cells):
        ids = [i for i,r in enumerate(routes) if r == cell]
        n = len(ids)
        gains = sum(candidate[i] == labels[i] and bank[i] != labels[i] for i in ids)
        losses = sum(candidate[i] != labels[i] and bank[i] == labels[i] for i in ids)
        upper = upper_binomial(losses,n,tail) if n else 1.0
        lower = max(0.0, 1-upper_binomial(n-gains,n,tail)) if n else 0.0
        rows.append({"cell": cell, "cases": n, "gains": gains, "losses": losses,
            "bank_correct": sum(bank[i] == labels[i] for i in ids),
            "candidate_correct": sum(candidate[i] == labels[i] for i in ids),
            "excess_error": (losses-gains)/n if n else None,
            "loss_probability_upper": upper, "gain_probability_lower": lower,
            "excess_error_upper": upper-lower,
            "nonregression_supported_under_iid": bool(n and upper <= lower)})
    return {"schema": "hepta.paired-confirmation.v1", "per_cell": rows,
        "alpha": alpha, "tail_per_bound": tail, "allowed_excess_error": 0.0,
        "supported_under_iid": all(r["nonregression_supported_under_iid"] for r in rows),
        "assumptions_verified": False, "retention_certified": False, "production_accepted": False}

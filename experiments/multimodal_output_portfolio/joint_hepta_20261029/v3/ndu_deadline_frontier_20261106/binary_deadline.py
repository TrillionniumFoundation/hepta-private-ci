"""Exact Neyman--Pearson minimax risk for the existing two-member catalog.

This analytic single-macro specialization avoids enumerating 2**n histories.
The early rule is pathwise equal to its full-sample rule; no optimal-cost claim.
"""
from fractions import Fraction as F
from functools import lru_cache
from math import comb


def minimax(n, p0=F(57, 100), p1=F(87, 100)):
    if (type(n) is not int or not 0 <= n <= 100
            or not isinstance(p0, F) or not isinstance(p1, F) or not 0 < p0 < p1 < 1):
        raise ValueError("Require a bounded sample cap and ordered probabilities")
    laws = [[F(comb(n, k))*p**k*(1-p)**(n-k) for k in range(n+1)] for p in (p0, p1)]
    for k in range(n+1):
        a, b = laws[0][k], laws[1][k]
        randomize = (sum(laws[1][:k+1])-sum(laws[0][k+1:]))/(a+b)
        if 0 <= randomize <= 1:
            risk = sum(laws[0][k+1:])+randomize*a
            lam = b/(a+b)
            lower = sum((min(lam*x, (1-lam)*y) for x, y in zip(*laws)), F(0))
            if lower != risk:
                raise ArithmeticError("Exact least-favorable-prior certificate failed")
            break
    else:
        raise ArithmeticError("No equal-error threshold found")

    @lru_cache(None)
    def early(i, successes, h):
        if successes > k:
            return F(h == 0), F(0)
        if successes+n-i < k:
            return F(h == 1), F(0)
        if i == n:
            return (randomize if h == 0 else 1-randomize), F(0)
        p = (p0, p1)[h]
        e0, c0 = early(i+1, successes, h)
        e1, c1 = early(i+1, successes+1, h)
        return (1-p)*e0+p*e1, 1+(1-p)*c0+p*c1

    errors, expected_n = zip(*(early(0, 0, h) for h in (0, 1)))
    if errors != (risk, risk):
        raise ArithmeticError("Early stopping changed the full-sample risk")
    return dict(n=n, threshold=k, randomize_one=randomize, risk=risk,
                least_favorable_prior_zero=lam, lower=lower,
                early_expected_samples=expected_n,
                early_expected_cost=tuple(F(3, 10)*v for v in expected_n),
                early_expected_model_time=tuple(3*v for v in expected_n),
                full_sample_cost=F(3, 10)*n, hard_model_time=3*n)

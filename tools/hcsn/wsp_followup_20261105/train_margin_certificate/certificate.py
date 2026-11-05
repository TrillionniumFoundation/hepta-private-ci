"""Exact certificates for one declared continuation-head necessary system.

No optimizer status establishes a certificate. Stored binary64 numbers are
interpreted as exact dyadic rationals; strict action comparisons are relaxed.
"""
from fractions import Fraction
import math


def f(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("nonfinite stored number")
    return Fraction.from_float(value)


def pack(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def unpack(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def parameters(original):
    if len(original) != 3 or any(len(row) != 49 for row in original):
        raise ValueError("the continuation group must be 3 by 49")
    c = [[f(x) for x in row] for row in original]
    radius_squared = sum((x*x for row in c for x in row), Fraction()) / 4
    lower = math.isqrt(radius_squared.numerator // radius_squared.denominator)
    upper = Fraction(lower if lower*lower >= radius_squared else lower+1)
    assert upper >= 0 and upper*upper >= radius_squared
    # All possible products and partial sums are far below binary64 overflow.
    no_overflow = 49 * max(abs(x)+upper for row in c for x in row) < 2**1000
    if not no_overflow:
        raise ValueError("the uniform no-overflow guard failed")
    unit = Fraction(1, 2**53)
    denominator = 1 - 98*unit
    gamma = 98*unit/denominator
    # |h_i|<=1, |delta_ji|<=R<=upper. This intentionally loose bound does
    # not assume the particular summation tree used by numpy.sum.
    error = [gamma*(sum(map(abs, row), Fraction())+49*upper)
             + 98*Fraction(1, 2**1074)/denominator for row in c]
    return c, radius_squared, upper, error


def equal_head_feasibility(original):
    """A rational common row satisfies every weak continuation comparison.

    This is a relaxation-feasibility construction, not an executed candidate
    or a claim that first-argmax can reproduce READ/REPAIR choices.
    """
    c, radius_squared, _, _ = parameters(original)
    common = [sum((row[j] for row in c), Fraction())/3 for j in range(49)]
    distance = sum(((row[j]-common[j])**2 for row in c for j in range(49)), Fraction())
    return {"construction": "exact rational coordinate mean of the three C continuation rows",
            "distance_squared": pack(distance), "radius_squared": pack(radius_squared),
            "weak_system_feasible": distance <= radius_squared,
            "first_argmax_realization_qualified": False,
            "candidate_model_constructed_or_saved": False}


def exact_witness(original, rows):
    """Verify y>=0 and d>R||A^Ty|| by an exact positive squared comparison."""
    c, radius_squared, upper, error = parameters(original)
    vector = [[Fraction() for _ in range(49)] for _ in range(3)]
    weighted_error, nonzero = Fraction(), 0
    for row in rows:
        y = f(row["multiplier"])
        if y < 0:
            raise ValueError("a dual multiplier is negative")
        a, b = row["target_action"]-1, row["competitor_action"]-1
        if a not in range(3) or b not in range(3) or a == b:
            raise ValueError("only two distinct continuation heads are admissible")
        hidden = [f(x) for x in row["hidden"]]
        if len(hidden) != 49 or hidden[-1] != 1 or any(abs(x)>1 for x in hidden):
            raise ValueError("hidden vector violates the fixed representation bound")
        if y:
            nonzero += 1
            for j, h in enumerate(hidden):
                product = y*h
                vector[a][j] += product
                vector[b][j] -= product
            weighted_error += y*(error[a]+error[b])
    ideal_d = -sum((vector[a][j]*c[a][j] for a in range(3) for j in range(49)), Fraction())
    norm_squared = sum((x*x for row in vector for x in row), Fraction())
    bound_squared = radius_squared*norm_squared
    def decision(d):
        return {"d": pack(d), "d_positive": d>0,
                "left_squared": pack(d*d), "right_squared": pack(bound_squared),
                "strict_separation": d>0 and d*d>bound_squared}
    return {"schema": "hepta.exact-training-margin-witness.v1", "rows": len(rows),
            "nonzero_multipliers": nonzero, "all_multipliers_nonnegative": True,
            "radius_squared": pack(radius_squared), "radius_upper": pack(upper),
            "dual_vector": [[pack(x) for x in row] for row in vector],
            "dual_vector_squared_norm": pack(norm_squared),
            "per_head_F64_absolute_error_bound": [pack(x) for x in error],
            "weighted_F64_error_bound": pack(weighted_error),
            "ideal_real": decision(ideal_d), "F64_necessary_relaxation": decision(ideal_d-weighted_error),
            "F64_scope": "conditional on binary64 round-to-nearest, gradual underflow, independent products and at most 48 additions per 49-term dot, and the verified no-overflow bound",
            "strict_ties_relaxed_to_weak": True,
            "positive_margin_requested": False}

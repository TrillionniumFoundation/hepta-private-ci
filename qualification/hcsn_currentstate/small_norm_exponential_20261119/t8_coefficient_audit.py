"""Exact algebraic audit of the upstream v2.8.0 degree-eight polynomial."""

import json
import time
import sympy as s


def audit():
    started = time.perf_counter()
    z, root, x3 = s.symbols("z"), s.sqrt(177), s.Rational(2, 3)
    x1, x2 = x3*(1+root)/88, x3*(1+root)/352
    x4 = (-271+29*root)/(315*x3)
    x5 = (-11+11*root)/(1260*x3)
    x6 = (-99+11*root)/(5040*x3)
    y2 = (857-58*root)/630
    outcomes = {}
    for name, x7 in (("upstream", (89-root)/(5040*x3)),
                     ("squared_denominator", (89-root)/(5040*x3*x3))):
        a4 = x1*z**3 + x2*z**4
        polynomial = s.expand(1+z+y2*z*z+(x3*z*z+a4)*(x4+x5*z+x6*z*z+x7*a4))
        differences = [s.simplify(polynomial.coeff(z, k)-s.Rational(1, s.factorial(k)))
                       for k in range(9)]
        outcomes[name] = {"coefficient_errors": [str(v) for v in differences],
                          "mismatched_degrees": [k for k, v in enumerate(differences) if v != 0]}
    if outcomes["upstream"]["mismatched_degrees"] != [5, 6, 7, 8]:
        raise AssertionError("unexpected upstream polynomial")
    if outcomes["squared_denominator"]["mismatched_degrees"]:
        raise AssertionError("modified formula is not Taylor degree eight")
    return {"schema": "hcsn-upstream-t8-exact-algebra-v1", "sympy_version": s.__version__,
            "source_url": "https://github.com/pytorch/pytorch/blob/v2.8.0/aten/src/ATen/native/LinearAlgebra.cpp",
            "source_git_blob": "2d7c2ff067c69a813588a1bd0e072ea763de8ef0",
            "function": "compute_T8", "arithmetic": "exact Q(sqrt(177)) polynomial coefficients",
            "outcomes": outcomes, "body_wall_seconds": time.perf_counter()-started,
            "model_calls": 0, "matrix_exponential_calls": 0,
            "scope": "The modified coefficient proves the polynomial identity, not a floating-point or gradient qualification."}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, allow_nan=False))

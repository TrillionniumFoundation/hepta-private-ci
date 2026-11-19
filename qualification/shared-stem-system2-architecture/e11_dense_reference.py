"""Independent dense exact-rational reference for E11 finite stochastic law.

This oracle deliberately does NOT call affine_trace(), gains() or certify().
It assembles all forward/backward/terminal equations as one simultaneous
linear system. It is a slow research control, not a deployed FBSDE solver.
"""
from __future__ import annotations

from fractions import Fraction as F
from e11_stochastic_tree import Law, State, Trace, number


def exact_dense_system(law: Law) -> tuple[Trace, dict]:
    if type(law) is not Law:
        raise ValueError("registered law required")
    p = law.checked()
    if law.steps > 3:
        raise ValueError("bounded dense control supports at most three levels")
    internal = 2**law.steps - 1
    total = 2*internal+1
    n = 2*total
    equations: list[tuple[dict[int, F], F]] = []

    def x(i: int) -> int:
        return 2*i

    def y(i: int) -> int:
        return 2*i+1

    def equation(coefficients: dict[int, F], constant: F) -> None:
        equations.append((coefficients, constant))

    equation({x(0): F(1)}, p["x0"])
    for i in range(internal):
        left = 2*i+1
        right = left+1
        # Two public successor states share SAME parent action/utility.
        for child, sign in ((left, -1), (right, +1)):
            equation({x(child): F(1), x(i): -F(1),
                      y(i): -p["a"]*p["h"]},
                     F(sign)*p["sigma"]*p["driver_scale"])
        # Exact conditional expectation under symmetric two-point support.
        equation({y(i): 1+p["lam"]*p["h"],
                  y(left): -F(1, 2), y(right): -F(1, 2),
                  x(i): -p["beta"]*p["h"]}, F(0))
    for i in range(internal, total):
        equation({y(i): F(1), x(i): -p["terminal_gain"]}, F(0))
    if len(equations) != n:
        raise ValueError("incorrect full equation count")

    rows = [[F(0)]*(n+1) for _ in range(n)]
    for r, (coefficients, rhs) in enumerate(equations):
        for j, value in coefficients.items():
            rows[r][j] = value
        rows[r][-1] = rhs

    pivots = 0
    eliminated = 0
    for col in range(n):
        pivot = next((r for r in range(col, n) if rows[r][col] != 0), None)
        if pivot is None:
            raise ValueError("singular global finite stochastic coupling")
        if pivot != col:
            rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v/divisor for v in rows[col]]
        pivots += 1
        for r in range(n):
            if r == col:
                continue
            factor = rows[r][col]
            if factor != 0:
                rows[r] = [a-factor*b for a, b in zip(rows[r], rows[col])]
                eliminated += 1
    solution = [row[-1] for row in rows]
    states = tuple(State(str(solution[x(i)]), str(solution[y(i)]))
                   for i in range(total))
    zz = tuple(str((solution[y(2*i+2)]-solution[y(2*i+1)])
                   / (2*p["driver_scale"])) for i in range(internal))
    return Trace(states, zz), {
        "source": "independent_simultaneous_dense_gaussian_elimination",
        "independent_affine_algorithm": True,
        "equation_count": n, "pivot_count": pivots,
        "nonzero_elimination_steps": eliminated,
        "physical_model_forwards": 0,
        "authority": "DENY_ALL",
    }

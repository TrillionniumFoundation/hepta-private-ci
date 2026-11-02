"""Independent small exact controls, with exhaustive primal policy enumeration.

Call run(direction_solver, maximum_solver). The former takes named arguments
matrix, value, obstacle, rhs, dmatrix, dobstacle, drhs and returns the directional
vector. The latter takes (a,b,da,db) and returns max(a,b)'s directional slope.
"""

import itertools

import numpy as np


def enumerate_primal(matrix, obstacle, rhs):
    candidates = []
    for choices in itertools.product((False, True), repeat=len(rhs)):
        active = np.asarray(choices)
        system, target = matrix.copy(), rhs.copy()
        system[active] = np.eye(len(rhs))[active]
        target[active] = obstacle[active]
        value = np.linalg.solve(system, target)
        first, second = value - obstacle, matrix @ value - rhs
        if min(first.min(), second.min()) >= -1e-11 and abs(np.minimum(first, second)).max() <= 1e-11:
            candidates.append(value)
    if not candidates or max(np.max(abs(v - candidates[0])) for v in candidates) > 1e-10:
        raise AssertionError("Independent exhaustive LCP solution not unique")
    return candidates[0]


def run(direction_solver, maximum_solver, steps=(1e-4, 3e-5)):
    records = []
    two = np.array([[2., -1.], [-1., 2.]])
    controls = []
    for forcing, expected in (([1.], [1.]), ([-1.], [0.])):
        controls.append((np.eye(1), np.zeros(1), np.zeros(1), np.zeros(1),
                         np.zeros((1, 1)), np.zeros(1), np.array(forcing), np.array(expected)))
    for forcing, expected in (([1., -1.], [.5, 0.]), ([-1., 1.], [0., .5]),
                              ([1., 1.], [1., 1.]), ([-1., -1.], [0., 0.])):
        controls.append((two, np.zeros(2), np.zeros(2), np.zeros(2),
                         np.zeros((2, 2)), np.zeros(2), np.array(forcing), np.array(expected)))
    controls.append((two, np.zeros(2), np.zeros(2), np.zeros(2),
                     np.zeros((2, 2)), np.array([1., 0.]), np.zeros(2), np.array([1., .5])))
    three = np.array([[2., -1., 0.], [-1., 3., -1.], [0., -1., 2.]])
    base, obstacle = np.ones(3), np.array([.5, 1., 1.])
    rhs, dmatrix = np.array([1., .5, 1.]), np.diag([.1, -.2, .3])
    for sign, expected in ((1., [.225, .25, .325]), (-1., [-.225, -.25, 0.])):
        controls.append((three, base, obstacle, rhs, sign * dmatrix,
                         sign * np.array([-.1, .25, 0.]),
                         sign * np.array([.3, -.3, .7]), np.array(expected)))
    for index, (a, v, o, b, da, do, db, expected) in enumerate(controls):
        found = np.asarray(direction_solver(matrix=a, value=v, obstacle=o, rhs=b,
                                           dmatrix=da, dobstacle=do, drhs=db))
        direct_error = float(abs(found - expected).max())
        reference_base = enumerate_primal(a, o, b)
        assert abs(reference_base - v).max() < 1e-12
        for step in steps:
            shifted = enumerate_primal(a + step * da, o + step * do, b + step * db)
            quotient = (shifted - v) / step
            fd_error = float(abs(quotient - found).max())
            records.append(dict(case=index, step=step, expected=expected.tolist(), found=found.tolist(),
                quotient=quotient.tolist(), direct_error=direct_error, one_sided_error=fd_error,
                passed=direct_error <= 1e-11 and fd_error <= 2e-4))
    maxima = []
    for a, b, da, db, expected in ((0., 0., -1., 2., 2.), (0., 0., 1., -2., 1.),
                                  (1., 0., -3., 7., -3.), (0., 1., 4., -2., -2.)):
        found = float(maximum_solver(a, b, da, db))
        maxima.append(dict(a=a, b=b, da=da, db=db, expected=expected, found=found,
                           passed=abs(found - expected) <= 1e-12))
    return dict(schema="hcsn-r20-independent-exact-directional-controls-v1",
                records=records, max_controls=maxima, passed=all(r["passed"] for r in records + maxima),
                limitation="Only small exact fixed-mesh LCP/max controls; no continuum or full neural gradient claim")


def run_candidate(steps=(1e-4, 3e-5)):
    from .directional import derivative, max_direction
    diagnostics = []

    def solve_direction(matrix, value, obstacle, rhs, dmatrix, dobstacle, drhs):
        # These classifications follow the explicitly constructed exact controls.
        contact, continuation = value - obstacle, matrix @ value - rhs
        states = np.where(contact > 0, 0, np.where(continuation > 0, 1, 2))
        result, record = derivative(np.diag(matrix), np.diag(matrix, -1), np.diag(matrix, 1),
            value, rhs, obstacle, drhs, dobstacle, dmatrix @ value, exact_states=states)
        diagnostics.append(record)
        return result

    result = run(solve_direction, max_direction, steps)
    result["candidate_diagnostics"] = diagnostics
    result["passed"] = result["passed"] and all(d["residual"] <= 1e-12 for d in diagnostics)
    return result

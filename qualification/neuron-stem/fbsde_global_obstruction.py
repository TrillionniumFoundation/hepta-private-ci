"""Exact-rational counterexamples to naive short-horizon FBSDE concatenation.

Deterministic, fully coupled boundary system: dX_t=Y_t dt, dY_t=0,
X_0=x0, Y_T=g X_T. This is an algebraic special case, not a theorem about
nonlinear/stochastic FBSDEs or any semantic reasoning ability.
"""
from __future__ import annotations

from fractions import Fraction as F


def require(condition, message):
    if not condition:
        raise ValueError(message)


def classify(x0: F, horizon: F, slope: F):
    if any(type(v) is not F or abs(v.numerator) > 10**6 or v.denominator > 10**6
           for v in (x0, horizon, slope)):
        raise ValueError("bounded exact rational inputs required")
    require(0 < horizon <= 4 and 0 < slope <= 4, "positive bounded time/slope")
    # (1-gT)Y_0=gX_0. No mesh may change this algebraic compatibility.
    coefficient = 1 - slope * horizon
    rhs = slope * x0
    if coefficient == 0:
        kind = "nonunique" if rhs == 0 else "no_solution"
        value = None
    else:
        kind = "unique"
        value = rhs / coefficient
    return {"boundary_case": kind, "analytic_initial_y": value,
            "coefficient": coefficient,
            "regular_decoupling_field_exists_on_whole_horizon": coefficient > 0}


def local_segment(x0: F, width: F, terminal_slope: F):
    """One short local interval with reset terminal field; unique when g*h<1."""
    require(0 < terminal_slope * width < 1, "no bounded local regular field")
    y = terminal_slope * x0 / (1 - terminal_slope * width)
    x_end = x0 + width * y
    assert y == terminal_slope * x_end
    return (x0, y, x_end)


def experiment_case(x0: F, horizon: F, slope: F, segments: int = 2):
    profile = classify(x0, horizon, slope)
    if type(segments) is not int or not 2 <= segments <= 16:
        raise ValueError("bounded segment count")
    step = horizon / segments
    require(slope * step < 1, "local segment length exceeds regular field")

    # Each independent short interval has a perfectly unique solution and
    # zero local terminal residual; reset at interfaces breaks global Y.
    wrong, x = [], x0
    for _ in range(segments):
        state = local_segment(x, step, slope)
        wrong.append(state)
        x = state[2]
    wrong_jump = max((abs(a[1] - b[1]) for a, b in zip(wrong, wrong[1:])),
                     default=F(0))
    assert wrong[-1][1] == slope * wrong[-1][2]

    correct = []
    if profile["regular_decoupling_field_exists_on_whole_horizon"]:
        # Backward transport the SAME global terminal field before solving
        # forward. Never replace it with slope at intermediate boundaries.
        fields = [F(0)] * segments + [slope]
        for k in range(segments - 1, -1, -1):
            require(1 - step * fields[k + 1] > 0, "global field pole")
            fields[k] = fields[k + 1] / (1 - step * fields[k + 1])
        x = x0
        for k in range(segments):
            y = fields[k] * x
            state = (x, y, x + step * y)
            require(state[1] == fields[k + 1] * state[2], "field interface mismatch")
            correct.append(state)
            x = state[2]
        require(all(a[1] == b[1] and a[2] == b[0]
                    for a, b in zip(correct, correct[1:])), "global trajectory discontinuity")
        require(correct[0][1] == profile["analytic_initial_y"], "global Y_0 mismatch")
        require(correct[-1][1] == slope * correct[-1][2], "global terminal mismatch")

    # At the degenerate global boundary X0=0,T=1/g, every constant Y is a
    # solution. Two distinct explicit examples show nonuniqueness.
    nonunique_examples = []
    if profile["boundary_case"] == "nonunique":
        for y in (F(0), F(1)):
            endpoint = x0 + horizon * y
            require(y == slope * endpoint, "invalid nonunique witness")
            nonunique_examples.append((x0, y, endpoint))
    return {
        "x0": str(x0), "horizon": str(horizon), "terminal_slope": str(slope),
        "segments": segments, "segment_length": str(step),
        "each_short_segment_unique": True,
        "each_short_segment_local_terminal_residual": "0",
        "reset_path": [[str(v) for v in row] for row in wrong],
        "reset_final_terminal_residual": "0",
        "reset_max_y_interface_jump": str(wrong_jump),
        "boundary_case": profile["boundary_case"],
        "analytic_initial_y": (str(profile["analytic_initial_y"])
                               if profile["analytic_initial_y"] is not None else None),
        "regular_global_field_admitted": bool(correct),
        "properly_stitched_path": [[str(v) for v in row] for row in correct],
        "nonunique_global_witnesses": [[str(v) for v in row]
                                      for row in nonunique_examples],
        "global_solvability_from_short_local_uniqueness": False,
        "general_fbsde_theorem_claimed": False,
        "production_accepted": False,
    }


def experiment():
    cases = [
        experiment_case(F(1), F(4, 5), F(1)),
        experiment_case(F(1), F(1), F(1)),
        experiment_case(F(0), F(1), F(1)),
        experiment_case(F(1), F(3, 2), F(1)),
    ]
    return {"schema": "hepta.fbsde.exact-global-obstruction.v1", "cases": cases,
            "source": "exact rational deterministic boundary profile",
            "independent_model_efficacy": False, "production_accepted": False}

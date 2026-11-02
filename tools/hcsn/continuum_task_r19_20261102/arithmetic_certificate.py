"""Exact rational checks of proof inequalities; no diffusion/grid experiment."""

from fractions import Fraction as Q
from math import factorial
from pathlib import Path
import hashlib
import json


def taylor(x, degree):
    return sum((x ** n / factorial(n) for n in range(degree + 1)), Q(0))


def run(output):
    x = Q(39, 50)
    assert taylor(x, 2) > 2
    assert taylor(Q(39, 20), 3) > 6
    assert 4 * Q(1, 5) < Q(9, 10) ** 2  # 2sqrt(rho)<.9.
    first_left_upper = Q(11, 70) + Q(13, 100) * Q(13, 10) * Q(9, 10)
    reset_lower = Q(421, 1000)
    jump_gap_lower = reset_lower - first_left_upper
    assert jump_gap_lower == Q(7823, 70000) > Q(447, 4000)
    lower_q = taylor(x, 3) / (1 + taylor(x, 3))
    g0 = Q(1, 5) + Q(3, 4) * lower_q
    g1 = Q(1, 10) + Q(2, 5) * lower_q
    resets, value = [], g1
    for _ in range(3):
        value = Q(1, 4) * g0 + Q(3, 4) * value - Q(29, 1000)
        resets.append(value)
    assert value == Q(12720913317, 25306336000) > Q(1, 2)
    assert taylor(Q(13, 40), 3) > Q(29, 21)
    bracket_left_upper = Q(268, 1000) + Q(13, 100) * Q(13, 10) * Q(9, 10)
    assert bracket_left_upper == Q(4201, 10000) < reset_lower
    assert x ** 3 / factorial(3) < Q(2, 25) and x / 4 < Q(1, 5)
    exp_upper = taylor(x, 2) + Q(1, 10)
    assert exp_upper == Q(10921, 5000) < Q(11, 5)
    b_upper = Q(12, 125) + Q(39, 80) * Q(11, 16)
    assert b_upper == Q(13797, 32000)
    assert taylor(Q(13, 8), 5) > 5
    assert Q(13, 30) > b_upper
    def exact(value):
        return dict(numerator=value.numerator, denominator=value.denominator)
    result = dict(schema="r19-exact-continuum-proof-arithmetic-v1",
        classification="Deductive rational proof checks only; no solver, random world, sampled boundary or convergence-rate experiment",
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        strict_jump=dict(no_reset_upper=exact(first_left_upper), new_reset_lower=exact(reset_lower), strict_gap_lower=exact(jump_gap_lower)),
        all_reset=dict(sigmoid_lower=exact(lower_q), policy_lower_returns=[exact(r) for r in resets], R3_above_half=exact(value - Q(1, 2))),
        reset_bracket=dict(lower_state=exact(Q(-1, 4)), upper_state=exact(Q(5, 4)), lower_no_reset_upper=exact(bracket_left_upper),
            B_upper=exact(b_upper), upper_payoff_lower=exact(Q(13, 30)), strict_upper_margin=exact(Q(13, 30) - b_upper)),
        all_exact_inequalities_hold=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2); stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)

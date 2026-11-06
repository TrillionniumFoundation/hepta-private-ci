"""Small exact/high-precision verification of the next-candidate theory notes.

This is a proof-reference check, not a deployment experiment or a new task bank.
Only Python's standard library is used. No existing repo is imported or modified.
"""

from collections import Counter, deque
from decimal import Decimal, localcontext
from fractions import Fraction as F
import json
from pathlib import Path


def ce(ps, xs, eta):
    return -(sum(p * (-eta * x).exp() for p, x in zip(ps, xs))).ln() / eta


def decimal_checks():
    with localcontext() as ctx:
        ctx.prec = 110
        D = Decimal
        half = D("0.5")
        eta = D(2)
        flat = ce([half, half], [D(0), half], eta)
        reset = half * ce([half, half], [D(0), D(1)], eta)
        assert reset < D("0.16") < flat
        transported = half * ce([half, half], [D(0), D(1)], eta * half)
        assert abs(flat - transported) < D("1e-105")

        ps = [D("0.25"), D("0.75")]
        xs = [D("-0.2"), D("1.3")]
        r, gamma = D("0.07"), D("0.8")
        lhs = ce(ps, [r + gamma * x for x in xs], eta)
        rhs = r + gamma * ce(ps, xs, eta * gamma)
        assert abs(lhs - rhs) < D("1e-105")

        # Random duration/reward joint events, followed by different lotteries.
        events = [
            (D("0.4"), D("0.1"), D("0.5"),
             [D("0.2"), D("0.8")], [D(0), D(1)]),
            (D("0.6"), D("-0.03"), D("0.25"),
             [D("0.7"), D("0.3")], [D("-0.1"), D("0.9")]),
        ]
        flattened_p, flattened_x = [], []
        root_p, correct_x, reset_x = [], [], []
        for p, reward, g, child_p, child_x in events:
            root_p.append(p)
            correct_x.append(reward + g * ce(child_p, child_x, eta * g))
            reset_x.append(reward + g * ce(child_p, child_x, eta))
            for pc, xc in zip(child_p, child_x):
                flattened_p.append(p * pc)
                flattened_x.append(reward + g * xc)
        flattened = ce(flattened_p, flattened_x, eta)
        propagated = ce(root_p, correct_x, eta)
        wrongly_reset = ce(root_p, reset_x, eta)
        assert abs(flattened - propagated) < D("1e-105")
        assert abs(flattened - wrongly_reset) > D("0.001")

        # Demonstrates why a CE-valued headroom bound cannot use gamma*U_eta.
        u_eta = ce([half, half], [D(0), D(1)], eta)
        u_eta_gamma = ce([half, half], [D(0), D(1)], eta * half)
        assert flat > half * u_eta
        assert abs(flat - half * u_eta_gamma) < D("1e-105")

        return {
            "decimal_precision": ctx.prec,
            "refinement_flat": str(flat),
            "refinement_local_reset": str(reset),
            "safe_stop": "0.16",
            "constant_gamma_reparameterization_error": str(abs(lhs - rhs)),
            "random_duration_flattened": str(flattened),
            "random_duration_transported": str(propagated),
            "random_duration_fixed_eta": str(wrongly_reset),
            "random_duration_transport_error": str(abs(flattened - propagated)),
            "headroom_requires_changed_risk_parameter": True,
        }


def likelihood_checks():
    # The outcome is (visible label, elapsed time). Label None is censoring.
    kernels = {
        "joint": {
            0: {(0, 1): F(9, 20), (1, 1): F(1, 20),
                (0, 3): F(1, 20), (1, 3): F(9, 20)},
            1: {(0, 1): F(1, 20), (1, 1): F(9, 20),
                (0, 3): F(9, 20), (1, 3): F(1, 20)},
        },
        "fast": {
            0: {(0, 1): F(7, 10), (1, 1): F(3, 10)},
            1: {(0, 1): F(3, 10), (1, 1): F(7, 10)},
        },
    }
    delta = F(1, 5)
    deadline = 5
    queue = deque([(0, F(1), F(1), False, False)])
    crossing = [F(0), F(0)]
    leaf_mass = [F(0), F(0)]
    stats = Counter()

    while queue:
        t, l0, l1, crossed0, crossed1 = queue.popleft()
        stats["nodes"] += 1
        mix = (l0 + l1) / 2
        excluded0 = l0 <= delta * mix
        excluded1 = l1 <= delta * mix
        assert not (excluded0 and excluded1)
        crossed0 = crossed0 or excluded0
        crossed1 = crossed1 or excluded1
        if t == deadline:
            leaf_mass[0] += l0
            leaf_mass[1] += l1
            crossing[0] += l0 * crossed0
            crossing[1] += l1 * crossed1
            stats["leaves"] += 1
            continue

        # Predictable design and timeout selection, depending on earlier data.
        design = "joint" if t < 2 and F(1, 3) <= l0 / l1 <= 3 else "fast"
        timeout = min(2 if design == "joint" else 1, deadline - t)
        observed = []
        for theta in (0, 1):
            out = Counter()
            for (label, duration), probability in kernels[design][theta].items():
                visible = (label, duration) if duration <= timeout else (None, timeout)
                out[visible] += probability
            assert sum(out.values()) == 1
            observed.append(out)
        assert observed[0].keys() == observed[1].keys()
        stats["adaptive_design_" + design] += 1

        # Each true-model mixture likelihood ratio has exact conditional mean.
        for theta, current_likelihood in enumerate((l0, l1)):
            next_expectation = F(0)
            for outcome in observed[theta]:
                p0, p1 = observed[0][outcome], observed[1][outcome]
                next_l = (l0 * p0, l1 * p1)
                next_mix = sum(next_l) / 2
                next_expectation += observed[theta][outcome] * next_mix / next_l[theta]
            assert next_expectation == mix / current_likelihood
            stats["conditional_martingale_checks"] += 1

        for (label, duration) in observed[0]:
            assert 0 < duration <= deadline - t
            p0, p1 = observed[0][(label, duration)], observed[1][(label, duration)]
            queue.append((t + duration, l0 * p0, l1 * p1, crossed0, crossed1))
            stats["censored_edges"] += label is None

    assert leaf_mass == [F(1), F(1)]
    assert all(x <= delta for x in crossing)
    assert stats["censored_edges"] > 0
    assert stats["adaptive_design_joint"] > 0 and stats["adaptive_design_fast"] > 0
    return {
        "deadline": deadline,
        "delta": str(delta),
        "true_model_ever_excluded_probabilities": [str(x) for x in crossing],
        "terminal_probability_mass": [str(x) for x in leaf_mass],
        "statistics": dict(stats),
    }


def main():
    result = {
        "status": "PASS",
        "scope": "proof-reference checks only; no candidate performance evidence",
        "decimal": decimal_checks(),
        "likelihood": likelihood_checks(),
        "global_vs_rectangular_counterexample": {
            "global_fixed_theta_minimum_expectation": "1/2",
            "adaptive_rectangular_adversary_value": "0",
        },
        "one_step_voc_counterexample": {
            "first_update_actionable_gain": "0",
            "two_updates_cost": "1/25",
            "two_updates_actionable_gain": "1/10",
            "two_updates_net_gain": "3/50",
        },
    }
    destination = Path(__file__).with_name("NEXT_THEORY_VERIFICATION.json")
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

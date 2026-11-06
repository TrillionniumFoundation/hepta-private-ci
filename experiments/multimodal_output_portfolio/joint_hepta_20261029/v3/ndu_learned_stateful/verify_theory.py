"""Independent finite checks for THEORY.md; does not import the fitted planner."""
import itertools
import json
import math
from fractions import Fraction as F
from pathlib import Path


def tv(p, q):
    return sum(abs(p.get(x, 0) - q.get(x, 0)) for x in p.keys() | q.keys()) / 2


def kl(p, q):
    return sum(float(v) * math.log(float(v / q[x])) for x, v in p.items() if v)


def censored(row, cap, current=0):
    out = {}
    for (label, duration, nxt), mass in row.items():
        obs = (label, duration, nxt) if duration <= cap else ("timeout", cap, current)
        out[obs] = out.get(obs, F(0)) + mass
    return out


def policies(depth):
    out = [("stop", 0), ("stop", 1)]
    if depth:
        out += [("query", a, b) for a in policies(depth - 1) for b in policies(depth - 1)]
    return out


def policy_value(policy, h, z, accuracy, fee):
    if policy[0] == "stop":
        return (F(11, 20) + F(9, 20) * z) * (policy[1] == h)
    py1 = accuracy if h == 1 else 1 - accuracy
    if z == 1:
        py1 = F(1, 2)
    return -fee + (1 - py1) * policy_value(policy[1], h, 1, accuracy, fee) + py1 * policy_value(policy[2], h, 1, accuracy, fee)


def value(policy, accuracy, fee):
    return sum(policy_value(policy, h, 0, accuracy, fee) for h in (0, 1)) / 2


def compositions(n, m):
    if m == 1:
        yield (n,)
    else:
        for count in range(n + 1):
            for rest in compositions(n - count, m - 1):
                yield (count,) + rest


def verify():
    checks = []
    details = {}

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    p, q = {}, {}
    for y0, y1 in itertools.product((0, 1), repeat=2):
        p[(y0, y1)] = (F(9, 10) if y0 else F(1, 10)) / 2
        q[(y0, y1)] = (F(1, 10) if y0 else F(9, 10)) / 2
    expected = .8 * math.log(9)
    check("stateful_KL_is_one_fresh_row", abs(kl(p, q) - expected) < 1e-14)
    details["stateful_kl"] = {"transcript": kl(p, q), "occupancy_formula": expected, "incorrect_query_count_formula": 2 * expected}

    events = (("0", 1, 0), ("1", 1, 1), ("0", 3, 1), ("1", 3, 0))
    p = dict(zip(events, map(F, (".4", ".1", ".2", ".3"))))
    q = dict(zip(events, map(F, (".1", ".4", ".3", ".2"))))
    reductions = []
    for cap in (1, 2, 3):
        pc, qc = censored(p, cap), censored(q, cap)
        check(f"censor_data_processing_cap_{cap}", tv(pc, qc) <= tv(p, q) and kl(pc, qc) <= kl(p, q) + 1e-14)
        reductions.append({"cap": cap, "tv": float(tv(pc, qc)), "kl": kl(pc, qc)})
    check("completion_at_cap_and_failure_transition", censored({("failure", 3, 1): F(1)}, 3) == {("failure", 3, 1): F(1)})
    check("timeout_does_not_leak_future_state", censored({("0", 3, 1): F(1)}, 1) == {("timeout", 1, 0): F(1)})
    details["censoring"] = {"raw_tv": float(tv(p, q)), "raw_kl": kl(p, q), "observed": reductions}

    a = F(1, 100)
    true_post, fitted_post = F(1, 2), a / (a + a * a)
    check("rare_positive_history_has_unstable_posterior", fitted_post - true_post > F(49, 100) and a - a * a < F(1, 100))
    details["posterior_counterexample"] = {"row_tv": float(a - a * a), "true": float(true_post), "fitted": float(fitted_post)}

    hazard_rows = []
    for length in range(6):
        for eps in (F(1, 100), F(1, 10), F(1, 2)):
            paths = {(): F(1)}
            for _ in range(length):
                nxt = {}
                for hist, mass in paths.items():
                    if hist and hist[-1] == 1:
                        nxt[hist + (1,)] = mass
                    else:
                        nxt[hist + (0,)] = mass * (1 - eps)
                        nxt[hist + (1,)] = mass * eps
                paths = nxt
            pure = {(0,) * length: F(1)}
            gamma = 1 - (1 - eps) ** length
            check(f"transcript_bound_attained_L{length}_eps{eps}", tv(pure, paths) == gamma)
            hazard_rows.append({"L": length, "epsilon": float(eps), "tv": float(tv(pure, paths)), "gamma": float(gamma)})
    details["tight_transcript_tv"] = hazard_rows

    menu = policies(2)
    vp = [value(pi, F(51, 100), F(1, 200)) for pi in menu]
    vq = [value(pi, F(49, 100), F(1, 200)) for pi in menu]
    fitted_i = max(range(len(menu)), key=lambda i: vq[i])
    span = F(101, 100)
    penalty = span * (1 - F(49, 50) ** 2)
    max_error = max(abs(x - y) for x, y in zip(vp, vq))
    regret = max(vp) - vp[fitted_i]
    gap_fit, gap_true = vq[fitted_i] - vq[0], vp[fitted_i] - vp[0]
    check("all_38_same_policy_values_obey_bound", len(menu) == 38 and max_error <= penalty)
    check("positive_plugin_regret_obeys_2E", regret == F(1, 50) and regret <= 2 * penalty)
    check("exact_STOP_baseline_needs_only_one_penalty", gap_true >= gap_fit - penalty)
    amortized = []
    for volume in (20, 100, 1000):
        lower = gap_fit - penalty - F(10, volume)
        truth = gap_true - F(10, volume)
        check(f"full_cost_certificate_M{volume}", truth >= lower)
        amortized.append({"M": volume, "hypothetical_setup_cost": 10, "true_net": float(truth), "lower": float(lower)})
    details["deterministic_transfer_example_not_benchmark"] = {"policies": len(menu), "max_value_error": float(max_error), "penalty_E": float(penalty), "regret": float(regret), "fitted_gap": float(gap_fit), "true_gap": float(gap_true), "amortization_arithmetic": amortized}

    distribution = (F(1, 2), F(1, 3), F(1, 6))
    tail_cases = []
    for n in range(1, 13):
        for eps in (F(1, 10), F(1, 4), F(1, 2)):
            tail = F(0)
            for counts in compositions(n, 3):
                distance = sum(abs(F(c, n) - p0) for c, p0 in zip(counts, distribution)) / 2
                if distance <= eps:
                    continue
                coefficient = math.factorial(n)
                for c in counts:
                    coefficient //= math.factorial(c)
                mass = F(coefficient)
                for c, p0 in zip(counts, distribution):
                    mass *= p0 ** c
                tail += mass
            upper = min(1., 6 * math.exp(-2 * n * float(eps) ** 2))
            check(f"exact_multinomial_tail_n{n}_eps{eps}", float(tail) <= upper + 1e-14)
            tail_cases.append({"n": n, "epsilon": float(eps), "tail": float(tail), "upper": upper})
    details["multinomial_tail_cases"] = tail_cases
    n, beta = 16, F(1, 2)
    empirical = dict(enumerate((F(8, 16), F(4, 16), F(4, 16))))
    truth = dict(enumerate(distribution))
    w = 3 * beta / (n + 3 * beta)
    smooth = {x: (1 - w) * empirical[x] + w / 3 for x in empirical}
    check("smoothing_bias_term", tv(truth, smooth) <= (1 - w) * tv(truth, empirical) + w)

    histories = list(itertools.product((0, 1), repeat=2))
    for decisions in itertools.product((0, 1), repeat=4):
        accuracies = []
        for orientation in (1, -1):
            accuracy = F(0)
            for h in (0, 1):
                py1 = F(9, 10) if (h == 1) == (orientation == 1) else F(1, 10)
                for hist, decision in zip(histories, decisions):
                    mass = F(1, 2)
                    for y in hist:
                        mass *= py1 if y else 1 - py1
                    accuracy += mass * (decision == h)
            accuracies.append(accuracy)
        check(f"orientation_swap_{decisions}", sum(accuracies) == 1)

    arithmetic = []
    for confidence_alpha, n in itertools.product((.025, .05), (16, 256, 8192)):
        empirical_radius = min(1., math.sqrt(math.log((2 ** 12 - 2) * 8 * 24 / confidence_alpha) / (2 * n)))
        weight = 6 / (n + 6)
        epsilon = (1 - weight) * empirical_radius + weight
        for deadline, fee in itertools.product((0, 1, 4), (.025, .3)):
            length = min(2, deadline)
            bound_span = 1 + length * fee + .02 * deadline
            gamma = 1 - (1 - epsilon) ** length
            loose_epsilon = min(1., empirical_radius + weight)
            frozen_penalty = (1 + 2 * fee + .02 * deadline) * min(1., 2 * loose_epsilon)
            arithmetic.append({"confidence_alpha": confidence_alpha, "matches_registered_kernel_budget": confidence_alpha == .025, "n": n, "deadline": deadline, "fee": fee, "empirical_radius": empirical_radius, "smoothing_weight": weight, "epsilon": epsilon, "looser_epsilon": loose_epsilon, "L": length, "B": bound_span, "gamma": gamma, "value_penalty_E": bound_span * gamma, "two_policy_penalty": 2 * bound_span * gamma, "frozen_looser_value_penalty": frozen_penalty})
    details["confidence_arithmetic_pre_result"] = arithmetic
    return {"status": "passed", "check_count": len(checks), "checks": checks, "details": details, "scope": "Independent finite mathematical checks, not benchmark performance, general-POMDP proof, or external independent review."}


if __name__ == "__main__":
    result = verify()
    target = Path(__file__).with_name("theory_verification.json")
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "check_count": result["check_count"], "output": str(target)}))

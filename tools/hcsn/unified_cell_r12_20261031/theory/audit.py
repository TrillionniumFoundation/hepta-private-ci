#!/usr/bin/env python3
"""Independent finite fixtures for the R12 local propositions, not task trials."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import scipy
from scipy.linalg import expm
from scipy.stats import norm, poisson


def generator(n=9, h=0.2, mu=0.0, sigma=1.0, kappa=6.0, retain=0.0):
    """Row generator; two content-major blocks, each n active + two recovery."""
    width = n + 2
    q = np.zeros((2 * width, 2 * width))
    up = sigma**2 / (2 * h**2) + max(mu, 0) / h
    down = sigma**2 / (2 * h**2) + max(-mu, 0) / h
    reset = n // 2
    for c in range(2):
        offset = c * width
        for i in range(n):
            if i + 1 < n:
                q[offset + i, offset + i + 1] += up
            q[offset + i, offset + (i - 1 if i else n)] += down
        q[offset + n, offset + n + 1] = kappa
        q[offset + n + 1, offset + reset] = kappa * retain
        q[offset + n + 1, (1 - c) * width + reset] = kappa * (1 - retain)
    np.fill_diagonal(q, -q.sum(axis=1))
    active = np.array([c * width + i for c in range(2) for i in range(n)])
    return q, active


def uniformized(q, dt, tolerance=1e-14):
    """Independent positive Poisson series, without clipping or renormalizing."""
    rate = float(max(-np.diag(q)))
    if rate == 0 or dt == 0:
        return np.eye(len(q)), 0.0, 0
    lam = rate * dt
    step = np.eye(len(q)) + q / rate
    power = np.eye(len(q))
    weight = np.exp(-lam)
    result = weight * power
    k = 0
    while poisson.sf(k, lam) > tolerance:
        k += 1
        power = power @ step
        weight *= lam / k
        result += weight * power
        if k > 10000:
            raise RuntimeError("Poisson series did not converge in fixture budget")
    return result, float(poisson.sf(k, lam)), k


def generator_checks():
    rows = []
    for mu in (-0.7, 0.0, 0.6):
        for sigma in (0.15, 0.8):
            q, active = generator(n=5, h=0.3, mu=mu, sigma=sigma, retain=0.65)
            off = q.copy()
            np.fill_diagonal(off, 0)
            for dt in (0.02, 0.4, 1.1):
                p = expm(dt * q)
                independently, tail, terms = uniformized(q, dt)
                killed = q[np.ix_(active, active)]
                survival = expm(dt * killed).sum(axis=1)
                row = {
                    "mu": mu, "sigma": sigma, "dt": dt,
                    "generator_row_error": float(abs(q.sum(axis=1)).max()),
                    "minimum_offdiagonal": float(off.min()),
                    "minimum_probability": float(p.min()),
                    "row_mass_error": float(abs(p.sum(axis=1) - 1).max()),
                    "semigroup_error": float(abs(expm(q * (dt + 0.17))
                        - p @ expm(q * 0.17)).max()),
                    "uniformization_error": float(abs(p - independently).max()),
                    "poisson_tail": tail, "poisson_terms": terms,
                    "min_survival": float(survival.min()),
                    "max_survival": float(survival.max()),
                }
                assert row["minimum_offdiagonal"] >= 0
                assert row["minimum_probability"] >= -1e-14
                assert row["row_mass_error"] < 1e-12
                assert row["semigroup_error"] < 1e-12
                assert row["uniformization_error"] < 1e-12
                assert -1e-12 <= survival.min() <= survival.max() <= 1 + 1e-12
                rows.append(row)
    return rows


def information_witnesses():
    n, h, dt = 9, 0.2, 0.5
    q, active = generator(n=n, h=h)
    x = np.arange(1, n + 1) * h
    k = q[np.ix_(active[:n], active[:n])]
    risk = 1 - expm(dt * k).sum(axis=1)
    diffuse = np.zeros(n)
    diffuse[[0, -1]] = 0.5
    point = np.eye(n)[n // 2]
    risks = [float(p @ risk) for p in (diffuse, point)]
    cost = 0.25
    assert abs(diffuse @ x - point @ x) < 1e-14
    assert risks[0] > cost > risks[1]
    width = n + 2
    joint_a, joint_b = np.zeros(len(q)), np.zeros(len(q))
    joint_a[[0, width + n - 1]] = 0.5
    joint_b[[n - 1, width]] = 0.5
    p = expm(dt * q)
    event_rates = np.zeros(len(q))
    event_rates[[0, width]] = 1.0 / (2 * h**2)
    integrated = np.zeros((len(q) + 1, len(q) + 1))
    integrated[:-1, :-1] = q
    integrated[:-1, -1] = event_rates
    expected_events = float(expm(dt * integrated)[0, -1])
    recovering = np.array([n, n + 1, width + n, width + n + 1])
    recovery_occupancy = float(p[0, recovering].sum())
    assert recovery_occupancy < risk[0] <= expected_events + 1e-13
    bit_one = np.r_[np.zeros(width), np.ones(width)]
    future_one = [float(law @ p @ bit_one) for law in (joint_a, joint_b)]
    assert future_one[0] > 0.5 > future_one[1]
    recovery_rate, recovery_dt = 2.0, 0.4
    recovery_q = np.array([[-2., 2., 0.], [0., -2., 2.], [0., 0., 0.]])
    ready = expm(recovery_dt * recovery_q)[:2, 2]
    expected = np.array([1 - np.exp(-0.8) * 1.8, 1 - np.exp(-0.8)])
    assert np.max(abs(ready - expected)) < 1e-14
    return {
        "same_mean_first_hit": {
            "distance_grid": x.tolist(), "diffuse_law": diffuse.tolist(),
            "point_law": point.tolist(), "mean": float(point @ x),
            "finite_ctmc_risks": risks, "intervention_cost": cost,
            "optimal_actions": ["intervene", "wait"],
            "continuum_brownian_risks": [
                float(norm.cdf(-0.2 / np.sqrt(dt)) + norm.cdf(-1.8 / np.sqrt(dt))),
                float(2 * norm.cdf(-1.0 / np.sqrt(dt)))],
            "interpretation": "Constructed information-loss witness, not a task trial."
        },
        "same_marginals_different_joint": {
            "joint_a": joint_a.tolist(), "joint_b": joint_b.tolist(),
            "future_bit_one": future_one, "optimal_bit_predictions": [1, 0],
            "mean_preserving_projection_erases_information": True,
        },
        "recovery_phase": {
            "rate": recovery_rate, "dt": recovery_dt,
            "ready_probabilities": ready.tolist(), "closed_form": expected.tolist(),
            "coarse_inactive_flag_is_not_markov": True,
        },
        "event_semantics": {"first_event_probability": float(risk[0]),
            "recovery_occupancy": recovery_occupancy,
            "expected_event_count": expected_events,
            "three_quantities_are_not_interchangeable": True},
    }


def posterior(p, likelihood):
    evidence = float(p @ likelihood)
    if evidence <= 0:
        raise ValueError("zero-evidence observation has no Bayesian posterior")
    return p * likelihood / evidence, evidence


def bayes_checks(rng):
    ratios, max_excess = [], 0.0
    for _ in range(80):
        p, q = rng.dirichlet(np.ones(6), size=2)
        likelihood = rng.uniform(0.01, 1, size=6)
        bp, zp = posterior(p, likelihood)
        bq, zq = posterior(q, likelihood)
        before = 0.5 * abs(p - q).sum()
        after = 0.5 * abs(bp - bq).sum()
        bound = min(1, likelihood.max() / min(zp, zq) * before)
        max_excess = max(max_excess, float(after - bound))
        assert after <= bound + 1e-13
        ratios.append(float(after / before))
    epsilon = 1e-6
    p, q = np.array([epsilon, 1 - epsilon]), np.array([0., 1.])
    likelihood = np.array([1., epsilon])
    bp, zp = posterior(p, likelihood)
    bq, zq = posterior(q, likelihood)
    after = float(0.5 * abs(bp - bq).sum())
    rejected = False
    try:
        posterior(np.array([1., 0.]), np.array([0., 1.]))
    except ValueError:
        rejected = True
    assert after > 0.49 and rejected
    return {"bounded_evidence_checks": len(ratios), "max_bound_excess": max_excess,
        "max_random_expansion": max(ratios), "rare_event_prior_tv": epsilon,
        "rare_event_posterior_tv": after, "amplification": after / epsilon,
        "evidence": [zp, zq], "zero_evidence_rejected": rejected}


def values(transitions, rewards, terminal):
    horizon = len(rewards)
    all_v = np.zeros((horizon + 1, len(terminal)))
    all_q = np.zeros_like(rewards)
    all_v[horizon] = terminal
    for t in reversed(range(horizon)):
        all_q[t] = rewards[t] + np.einsum("asj,j->sa", transitions[t], all_v[t + 1])
        all_v[t] = all_q[t].max(axis=1)
    return all_v, all_q


def regret_checks(rng):
    horizon, states, actions = 5, 3, 2
    p = rng.dirichlet(np.ones(states), size=(horizon, actions, states))
    perturbation = rng.dirichlet(np.ones(states), size=(horizon, actions, states))
    ph = 0.97 * p + 0.03 * perturbation
    r = rng.uniform(-0.7, 0.7, size=(horizon, states, actions))
    rh = r + rng.uniform(-0.01, 0.01, size=r.shape)
    terminal = rng.uniform(-0.2, 0.2, size=states)
    terminal_h = terminal + np.array([0.002, -0.003, 0.001])
    v, q = values(p, r, terminal)
    vh, qh = values(ph, rh, terminal_h)
    fit = 0.04 * np.sin(np.arange(qh.size)).reshape(qh.shape)
    qfit = qh + fit
    pi = qfit.argmax(axis=2)
    deployed = terminal.copy()
    for t in reversed(range(horizon)):
        deployed = np.array([r[t, s, pi[t, s]] + p[t, pi[t, s], s] @ deployed
                             for s in range(states)])
    er, ep = float(abs(r-rh).max()), float((0.5 * abs(p-ph).sum(axis=3)).max())
    eg = float(abs(terminal-terminal_h).max())
    rmax = float(max(abs(r).max(), abs(rh).max()))
    gmax = float(max(abs(terminal).max(), abs(terminal_h).max()))
    dh = eg + horizon*er + (rmax*horizon*(horizon-1) + 2*gmax*horizon)*ep
    fit_bound = float(abs(fit).max(axis=(1, 2)).sum())
    actual = float((v[0] - deployed).max())
    assert float(abs(v[0]-vh[0]).max()) <= dh + 1e-13
    assert actual <= 2*dh + 2*fit_bound + 1e-13
    # A fixed discounted Bellman operator, independently checked on random vectors.
    left, right = rng.normal(size=(2, states))
    gamma = 0.9
    tl = (r[0] + gamma*np.einsum("asj,j->sa", p[0], left)).max(axis=1)
    tr = (r[0] + gamma*np.einsum("asj,j->sa", p[0], right)).max(axis=1)
    ratio = float(abs(tl-tr).max() / abs(left-right).max())
    assert ratio <= gamma + 1e-13
    return {"horizon": horizon, "reward_error": er, "kernel_tv_error": ep,
        "terminal_error": eg, "model_value_bound": dh,
        "model_value_error": float(abs(v[0]-vh[0]).max()),
        "critic_error_sum": fit_bound, "actual_deployed_regret": actual,
        "deployed_regret_bound": 2*dh+2*fit_bound,
        "discount": gamma, "observed_contraction_ratio": ratio,
        "coverage_counterexample": {"true_q": [[0, 0], [1, -1]],
            "fitted_q": [[0, 0], [-1, 1]], "observed_state": 0,
            "observed_uniform_error": 0, "unseen_state_regret": 2}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("raw.json"))
    args = parser.parse_args()
    rng = np.random.default_rng(20261031)
    output = {"status": "conditional_fixture_checks_passed", "seed": 20261031,
        "scope": "Independent finite fixtures; no production-kernel audit or task confirmation.",
        "numpy": np.__version__, "scipy": scipy.__version__,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "propositions_sha256": hashlib.sha256(Path(__file__).with_name("PROPOSITIONS.md").read_bytes()).hexdigest(),
        "generator_checks": generator_checks(), "information_witnesses": information_witnesses(),
        "bayes_checks": bayes_checks(rng), "regret_checks": regret_checks(rng)}
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "output": str(args.output),
                      "generator_cases": len(output["generator_checks"])}))


if __name__ == "__main__":
    main()

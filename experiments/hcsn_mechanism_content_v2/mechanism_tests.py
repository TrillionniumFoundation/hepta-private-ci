"""Independent mechanism diagnostics; development smoke is not held-out evidence."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np

from .mechanism import (Config, generate_path, make_episode, run_arm,
                        transition_matrix, write_json)
from .renewal import (Physics, RenewalCore, content_from_counts, first_passage_cdf,
                      fit_ordinary, renewal_counts, sample_counts)


def kernel_diagnostics(samples=65536, repeats=20):
    cases = [(.3, 1.7, Physics(-.7, .45, .6, .16)),
             (.9, 2.2, Physics(-.4, .6, .6, .24)),
             (.15, .4, Physics(-.9, .2, .45, .16))]
    rng = np.random.default_rng(81231)
    rows = []
    for x, horizon, physics in cases:
        analytic, awork = renewal_counts(x, horizon, physics)
        numerical, nwork = renewal_counts(x, horizon, physics, numerical=True)
        events = sample_counts(rng, physics, x, horizon, samples)
        empirical = np.bincount(events, minlength=len(analytic)) / samples
        uncertainty = 6 * np.sqrt(analytic * (1 - analytic) / samples) + 4 / samples
        passed = bool(np.all(np.abs(empirical - analytic) <= uncertainty))
        started = time.perf_counter()
        for _ in range(repeats):
            renewal_counts(x, horizon, physics)
        analytic_seconds = (time.perf_counter() - started) / repeats
        started = time.perf_counter()
        for _ in range(repeats):
            renewal_counts(x, horizon, physics, numerical=True)
        numerical_seconds = (time.perf_counter() - started) / repeats
        initial = np.eye(5)[0]; matrix = transition_matrix(5)
        full = content_from_counts(analytic, initial, matrix)
        ablations = {}
        for name, kwargs in (("absorbing_no_repeat", {"reset_enabled": False}),
                             ("future_refractory_removed", {"refractory_enabled": False})):
            probs, work = renewal_counts(x, horizon, physics, **kwargs)
            ablations[name] = {"probabilities": probs.tolist(), "work": work,
                              "content_l1_from_full_process": float(np.abs(content_from_counts(probs, initial, matrix) - full).sum()),
                              "interpretation": "model_mismatch_on_same_true_process_not_architecture_win"}
        rows.append({"x": x, "horizon": horizon, "physics": asdict(physics),
                     "analytic": analytic.tolist(), "numerical": numerical.tolist(),
                     "independent_IG_empirical": empirical.tolist(), "IG_samples": samples,
                     "IG_six_sigma_plus_four_over_n_pass": passed,
                     "max_absolute_numeric_error": float(np.abs(analytic - numerical).max()),
                     "same_precision_target": 1e-8, "matched_precision_pass": bool(np.max(np.abs(analytic - numerical)) <= 1e-8),
                     "analytic_seconds_per_call": analytic_seconds,
                     "numerical_seconds_per_call": numerical_seconds,
                     "analytic_work": awork, "numerical_work": nwork, "ablations": ablations})
    return {"cases": rows, "timing_scope": "CPU kernel evaluation only; quadrature nodes are not simulation ticks",
            "numerical_scope": "independent density integral, not a learned ordinary neural core"}


def bridge_diagnostic(samples=8192):
    """Check a first-passage bridge marginal against killed Brownian density."""
    rng = np.random.default_rng(71349)
    x, t, physics = .7, .6, Physics(-.4, .5, .6, 1.0)
    matrix = transition_matrix(3)
    surviving_x = []
    for _ in range(samples):
        path = generate_path(rng, physics, [0., t], x, 0, matrix)
        if not path["events"]:
            surviving_x.append(path["x"][-1])
    y = np.linspace(0, 5, 20001)
    variance = physics.sigma**2 * t
    killed = (np.exp(-(y-x-physics.nu*t)**2 / (2*variance))
              - np.exp(-2*physics.nu*x / physics.sigma**2)
              * np.exp(-(y+x-physics.nu*t)**2 / (2*variance))) / np.sqrt(2*np.pi*variance)
    survival = float(1 - first_passage_cdf(t, x, physics.nu, physics.sigma))
    expected = float(np.trapezoid(y * killed, y) / survival)
    observed = float(np.mean(surviving_x))
    se = float(np.std(surviving_x) / np.sqrt(len(surviving_x)))
    return {"samples": samples, "survival_predicted": survival,
            "survival_observed": len(surviving_x) / samples,
            "survivor_mean_predicted": expected, "survivor_mean_observed": observed,
            "survivor_mean_standard_error": se,
            "mean_six_standard_error_pass": abs(observed - expected) < 6*se}


def development_smoke():
    started = time.perf_counter()
    ordinary, training, _ = fit_ordinary(seed=19281, train_size=256, epochs=4, width=32)
    config = Config(ticks=10, deadlines=(3, 6, 10), particles=2)
    episode = make_episode(912381, config)
    identity_before = json.dumps(episode, sort_keys=True)
    rows = []
    for core in (ordinary, RenewalCore()):
        for controller in ("lightweight", "task_value"):
            summary, trace, access, predictions = run_arm(core, controller, episode, config)
            assert all(not row["external_state_reset"] for row in access)
            assert not trace[0]["observed_state"]["has_read"]
            assert len(predictions) == len(config.deadlines)
            assert all(np.isclose(sum(row["probabilities"]), 1) for row in predictions)
            rows.append({"core": core.name, "controller": controller, **summary})
    assert identity_before == json.dumps(episode, sort_keys=True)
    return {"split": "development_smoke_not_test", "training": training,
            "kernel": kernel_diagnostics(2048, 2), "bridge": bridge_diagnostic(512),
            "arms": rows, "wall_seconds": time.perf_counter() - started,
            "purpose": "API and mechanism contract check; not quality/model selection"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--development-smoke", action="store_true")
    parser.add_argument("--samples", type=int, default=65536)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    output = Path(args.output); output.mkdir(parents=True, exist_ok=False)
    result = (development_smoke() if args.development_smoke else
              {"kernel": kernel_diagnostics(args.samples, args.repeats),
               "bridge": bridge_diagnostic(min(args.samples, 16384))})
    write_json(output / "diagnostics.json", result)
    print(json.dumps({"output": str(output), "development_smoke": args.development_smoke,
                      "wall_seconds": result.get("wall_seconds")}))


if __name__ == "__main__":
    main()

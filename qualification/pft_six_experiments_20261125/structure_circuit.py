"""PFT3/PFT4 synthetic research campaign with explicit qualification scope."""

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
from scipy.special import ndtr

from cells import ResearchCellNet, delayed_data, digest, evaluate, gradient_check


def impulse_qvi(steps=12, h=0.25):
    """Solve a finite-state, finite-horizon impulse Bellman VI exactly.

    Cost: h*x^2 while continuing, .18 per instantaneous reset to zero,
    terminal .5*x^2. State transition is a Gaussian binned on [-2,2], with
    tails assigned to endpoint bins. This qualifies that finite chain only.
    """
    grid = np.linspace(-2, 2, 81)
    edges = np.r_[-np.inf, (grid[1:] + grid[:-1]) / 2, np.inf]
    sd = 0.35 * np.sqrt(h)
    transition = np.diff(ndtr((edges[None, :] - grid[:, None]) / sd), axis=1)
    values, actions = np.zeros((steps + 1, len(grid))), []
    values[-1] = 0.5 * grid**2
    bounds, residual = np.empty(steps), 0.0
    zero = len(grid) // 2
    for t in range(steps - 1, -1, -1):
        continuation = h * grid**2 + transition @ values[t + 1]
        # Resetting twice cannot improve a positive-cost impulse to zero.
        intervention = 0.18 + continuation[zero]
        values[t] = np.minimum(continuation, intervention)
        reset = continuation > intervention
        actions.append(reset)
        positive = grid[(grid >= 0) & reset]
        bounds[t] = positive.min() if len(positive) else float(grid[-1] + 1)
        residual = max(residual, float(np.max(np.abs(
            values[t] - np.minimum(continuation, 0.18 + values[t, zero])))))
    policies = np.array(actions[::-1])
    def simulate(thresholds, seed, count=8192):
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(grid), count)
        total = np.zeros(count)
        resets = np.zeros(count)
        cdf = transition.cumsum(axis=1)
        for t in range(steps):
            reset = (policies[t, idx] if thresholds is None else
                     abs(grid[idx]) >= thresholds[t])
            total += 0.18 * reset
            resets += reset
            idx[reset] = zero
            total += h * grid[idx]**2
            draws = rng.random(count)
            idx = np.sum(draws[:, None] > cdf[idx], axis=1)
            idx = np.minimum(idx, len(grid) - 1)
        total += 0.5 * grid[idx]**2
        return float(total.mean()), float(resets.mean())
    candidates = np.linspace(0.15, 1.4, 26)
    learned = min(candidates, key=lambda b: simulate(np.full(steps, b), 7601)[0])
    rows = []
    for seed in (7611, 7612, 7613):
        for name, threshold in (("fixed", 0.75), ("validation_selected", learned),
                                ("finite_chain_qvi", None)):
            cost, resets = simulate(None if threshold is None else
                                    np.full(steps, threshold), seed)
            rows.append({"seed": seed, "policy": name, "mean_cost": cost,
                         "mean_resets": resets})
    return {"scope": "finite_state_impulse_Bellman_VI_not_continuum_HCSN_QVI",
            "grid_size": len(grid), "h": h, "steps": steps,
            "maximum_Bellman_residual": residual,
            "maximum_transition_mass_error": float(abs(transition.sum(1) - 1).max()),
            "bounds": bounds.tolist(), "validation_selected_threshold": float(learned),
            "heldout_policy_rows": rows,
            "network_use": "QVI-derived feature prior; its control cost is not the XOR task loss"}


def delayed_lq_probe():
    """PFT scaling on a known two-state delayed actuator, not an LLM claim.

    Raw U=sqrt(h)*Y, U'=A U+h*sqrt(h)*B a+sigma*h*noise.
    In Y coordinates B_h=h B. Observed position cannot react in one step.
    """
    h, horizon, lam = 0.2, 16, 0.12
    a = np.array([[1.0, h], [0.0, 0.95]])
    b = h * np.array([[0.0], [1.0]])
    q, qf, r = h * np.diag([1.0, 0.0]), np.diag([12.0, 0.0]), np.array([[h * lam]])
    p = qf.copy()
    gains = []
    residual = 0.0
    for _ in range(horizon):
        k = np.linalg.solve(r + b.T @ p @ b, b.T @ p @ a)
        new = q + a.T @ p @ a - a.T @ p @ b @ k
        residual = max(residual, float(abs(new - new.T).max()))
        gains.append(k)
        p = new
    gains = gains[::-1]
    greedy = np.linalg.solve(r + b.T @ qf @ b, b.T @ qf @ a)
    def run(kind, seed, gain=None, count=1024):
        rng = np.random.default_rng(seed)
        y = rng.normal(0, [1.0, 0.4], (count, 2))
        costs, energy = np.zeros(count), np.zeros(count)
        for t in range(horizon):
            k = gains[t] if kind == "pft_horizon" else greedy if kind == "greedy" else gain
            action = -(y @ k.T).reshape(-1)
            costs += np.einsum("bi,ij,bj->b", y, q, y) + r[0, 0] * action**2
            energy += h * action**2
            y = y @ a.T + action[:, None] @ b.T + 0.05 * np.sqrt(h) * rng.normal(size=y.shape)
        costs += np.einsum("bi,ij,bj->b", y, qf, y)
        return {"mean_cost": float(costs.mean()), "mean_action_energy": float(energy.mean()),
                "terminal_position_mse": float(np.mean(y[:, 0]**2))}
    fixed_options = [np.array([[kp, kv]]) for kp in (0.5, 1, 2, 4) for kv in (0.5, 1, 2, 4)]
    fixed = min(fixed_options, key=lambda k: run("fixed", 8811, k)["mean_cost"])
    rows = []
    for seed in (8821, 8822, 8823):
        for kind in ("fixed", "greedy", "pft_horizon"):
            rows.append({"policy": kind, "seed": seed, **run(kind, seed, fixed)})
    # Numerical coordinate identity is independent of outcome targets.
    y = np.array([0.4, -0.2])
    raw = np.sqrt(h) * y
    action = 0.7
    scale_error = float(abs((a @ raw + h * np.sqrt(h) * np.array([0, action])) /
                            np.sqrt(h) - (a @ y + b[:, 0] * action)).max())
    return {"scope": "known_linear_quadratic_delayed_actuator_not_HCSN_or_LLM",
            "h": h, "horizon": horizon, "lambda": lam,
            "raw_control_scale": "h*sqrt(h)", "normalized_control_scale": "h",
            "scaling_identity_error": scale_error, "riccati_symmetry_residual": residual,
            "one_step_observation_J": 0.0, "greedy_gain": greedy.tolist(),
            "fixed_gain_selected_on_validation_only": fixed.tolist(), "rows": rows,
            "target_access": "known control reference zero; no heldout classification labels"}


def aggregate(rows, keys):
    groups = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        groups.setdefault(key, []).append(row)
    return [{**dict(zip(keys, key)), "runs": len(items),
             "mean_accuracy": float(np.mean([i["test"]["accuracy"] for i in items])),
             "seed_sd_accuracy": float(np.std([i["test"]["accuracy"] for i in items], ddof=1))
             if len(items) > 1 else None,
             "mean_ce": float(np.mean([i["test"]["ce"] for i in items])),
             "mean_fit_wall_seconds": float(np.mean([i["fit"]["fit_wall_seconds"] for i in items]))}
            for key, items in groups.items()]


def campaign(widths, seeds, steps, output):
    started = time.perf_counter()
    check = gradient_check()
    if not check["passed"]:
        raise RuntimeError("BPTT/finite-difference agreement failed")
    qvi = impulse_qvi()
    rows3, rows4 = [], []
    modes = [(mode, boundary, False) for mode in ("boundary", "flow", "both")
             for boundary in ("fixed", "learned", "qvi_prior")
             if mode != "flow" or boundary == "fixed"]
    modes += [("boundary", "fixed", True), ("both", "fixed", True)]
    for width in widths:
        for seed in seeds:
            training = delayed_data(10000 + seed, 512, width)
            validation = delayed_data(20000 + seed, 128, width)
            test = delayed_data(30000 + seed, 1024, width, "laplace")
            hashes = {k: d["hash"] for k, d in (("train", training), ("validation", validation), ("test", test))}
            learned = None
            for mode, boundary, ordinary in modes:
                net = ResearchCellNet(width, seed, mode, ordinary, boundary,
                                      qvi_bounds=qvi["bounds"])
                fit = net.fit(training, validation, steps=steps, seed=seed)
                row = {"width": width, "seed": seed, "mode": mode,
                       "boundary": boundary, "features": "ordinary" if ordinary else "first_passage_F_G",
                       "data_hashes": hashes, "fit": fit, "test": evaluate(net, test)}
                rows3.append(row)
                print(json.dumps({"experiment": "PFT3", "width": width, "seed": seed,
                                  "mode": mode, "boundary": boundary, "ordinary": ordinary,
                                  "accuracy": row["test"]["accuracy"]}), flush=True)
                if (mode, boundary, ordinary) == ("both", "fixed", False):
                    learned = net, fit
                if (mode, boundary, ordinary) == ("both", "fixed", True):
                    rows4.append({"width": width, "seed": seed, "graph": "single_recurrent_ordinary",
                                  "data_hashes": hashes, "fit": fit, "test": row["test"]})
            net, fit = learned
            for ablation in (None, "delete_edges", "shuffle_messages"):
                rows4.append({"width": width, "seed": seed,
                              "graph": "learned" if ablation is None else ablation,
                              "data_hashes": hashes, "fit": fit, "test": evaluate(net, test, ablation)})
            fixed = ResearchCellNet(width, seed, graph="fixed")
            fit = fixed.fit(training, validation, steps=steps, seed=seed)
            rows4.append({"width": width, "seed": seed, "graph": "fixed_graph",
                          "data_hashes": hashes, "fit": fit, "test": evaluate(fixed, test)})
            # Durable partial progress is explicitly not a completed result.
            partial = {"status": "RUNNING", "rows3_completed": len(rows3), "rows4_completed": len(rows4)}
            (output / "pft34_progress.json").write_text(json.dumps(partial, indent=2) + "\n")
    common = {"status": "COMPLETED_RESEARCH_PROXY", "production_qualified": False,
              "widths": widths, "seeds": seeds, "gradient_check": check,
              "task": "delayed_XOR_early_bit_and_late_new_bit",
              "split": "512 normal train / 128 normal validation / 1024 Laplace independent-source test",
              "initial_states": "independent normal; train sd=.05, test sd=.10",
              "selection": "validation CE only; test once per selected candidate and specified ablation",
              "capacity": "same width and 2*width message dimensions; total parameters reported",
              "compute_matching": "same updates/batches; wall time reported, not equal-wall comparison",
              "hardware": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
              "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__), Path(__file__).with_name("cells.py"))}}
    pft3 = {**common, "experiment": "PFT3", "rows": rows3,
            "summary": aggregate(rows3, ("width", "mode", "boundary", "features")), "qvi_probe": qvi,
            "scope": "new NumPy value-feature recurrent network; not the probability-mass HCSN implementation",
            "claim_limits": ["uses BPTT, not direct full-network parameter inversion",
                             "frozen-law F/G are features, not moving-boundary network hit probabilities",
                             "QVI prior is optimal only for its explicit finite-chain impulse cost",
                             "learned boundary adds width trainable parameters; counts retained"]}
    pft4 = {**common, "experiment": "PFT4", "rows": rows4,
            "summary": aggregate(rows4, ("width", "graph")), "pft_horizon_probe": delayed_lq_probe(),
            "scope": "synthetic recurrent connectivity and independent PFT-scaling LQ mechanism probes",
            "claim_limits": ["fixed graph has equal stored capacity but fewer trainable parameters",
                             "single model is the capacity-matched ordinary-feature recurrent baseline",
                             "ablation harms do not alone prove learned graph superiority",
                             "LQ Riccati success does not qualify end-to-end HCSN PFT control"]}
    for name, result in (("pft3", pft3), ("pft4", pft4)):
        result["combined_wall_seconds"] = time.perf_counter() - started
        (output / (name + ".json")).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    (output / "pft34_progress.json").unlink(missing_ok=True)
    return pft3, pft4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--widths", type=int, nargs="+", default=[8, 16, 32, 64])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--steps", type=int, default=180)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output / name).exists() for name in ("pft3.json", "pft4.json")):
        raise FileExistsError("Use a new output directory; previous receipts are immutable")
    campaign(args.widths, args.seeds, args.steps, args.output)


if __name__ == "__main__":
    main()

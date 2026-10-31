"""Fresh clock-identification/control task; confirmation requires a source/model freeze."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import t as student_t

from .kernels import Params, log_discounted_hit, log_event_likelihood
from .likelihood_fit import fit_events


HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def protocol():
    return json.loads((HERE / "PROTOCOL.json").read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def source_hashes(cfg):
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in cfg["critical_source_files"]}


def validate_freeze(commit, bundle_path, cfg):
    """Reject a confirmation run if any source or checkpoint differs from the freeze."""
    if not commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Confirmation requires an explicit full git freeze commit.")
    paths = [HERE / name for name in cfg["critical_source_files"]] + [Path(bundle_path).resolve()]
    for path in paths:
        relative = path.relative_to(REPO).as_posix()
        saved = subprocess.run(["git", "show", f"{commit}:{relative}"], cwd=REPO,
                               capture_output=True, check=False)
        if saved.returncode or saved.stdout != path.read_bytes():
            raise ValueError(f"Freeze does not contain the current bytes of {relative}")


def sample_contracts(rng, class_id, count, cfg, regime="iid"):
    """Independent numpy Wald/Exponential simulator; never calls candidate CDF code."""
    mu, sigma, cancellation = cfg["truth"][class_id]
    clock = (rng.choice(cfg["ood"]["clock_factors"], count) if regime == "ood"
             else np.ones(count))
    distance = cfg["known_distance"]
    hit = rng.wald(distance / (mu * clock), distance ** 2 / (sigma ** 2 * clock))
    cancel = rng.exponential(1.0 / (cancellation * clock))
    return hit, cancel


def generate_records(seed, class_id, count, cfg, regime="iid"):
    rng = np.random.default_rng(np.random.SeedSequence([seed, class_id, 71]))
    hit, cancel = sample_contracts(rng, class_id, count, cfg, regime)
    horizon = rng.choice(cfg["train_horizons"], count)
    observed = (hit < cancel) & (hit <= horizon)
    return [("hit" if event else "no_hit", float(t), cfg["known_distance"])
            for event, t in zip(observed, np.where(observed, hit, horizon))]


def hazard_law(family, parameters, times):
    probability, shape, scale = parameters
    times = np.asarray(times, dtype=float)
    log_ratio = np.log(np.maximum(times, np.finfo(float).tiny) / scale)
    if family == "cure_weibull":
        exponent = np.exp(np.minimum(shape * log_ratio, 700))
        cdf = probability * (-np.expm1(-exponent))
        log_density = (math.log(probability * shape) - np.log(np.maximum(times, 1e-300))
                       + shape * log_ratio - exponent)
    else:
        fraction = expit(shape * log_ratio)
        cdf = probability * fraction
        log_density = (math.log(probability * shape) - np.log(np.maximum(times, 1e-300))
                       + shape * log_ratio - 2 * np.logaddexp(0, shape * log_ratio))
    return np.where(times > 0, cdf, 0.0), np.exp(log_density)


def hazard_objective(parameters, family, records):
    probability, shape, scale = parameters
    times = np.array([record[1] for record in records])
    events = np.array([record[0] == "hit" for record in records])
    ratio_log = np.log(times / scale)
    if family == "cure_weibull":
        exponent = np.exp(np.minimum(shape * ratio_log, 700))
        tail = np.exp(-exponent)
        cdf = probability * (-np.expm1(-exponent))
        log_pdf = math.log(probability * shape) - np.log(times) + shape * ratio_log - exponent
        event_score = np.column_stack((np.full_like(times, 1 / probability),
                                      1 / shape + (1 - exponent) * ratio_log,
                                      shape * (exponent - 1) / scale))
        tail_score = np.column_stack((tail - 1, -probability * tail * exponent * ratio_log,
                                     probability * tail * exponent * shape / scale))
    else:
        fraction = expit(shape * ratio_log)
        cdf = probability * fraction
        log_pdf = (math.log(probability * shape) - np.log(times) + shape * ratio_log
                   - 2 * np.logaddexp(0, shape * ratio_log))
        event_score = np.column_stack((np.full_like(times, 1 / probability),
                                      1 / shape + (1 - 2 * fraction) * ratio_log,
                                      -shape * (1 - 2 * fraction) / scale))
        curvature = fraction * (1 - fraction)
        tail_score = np.column_stack((-fraction, -probability * curvature * ratio_log,
                                     probability * curvature * shape / scale))
    survival = 1 - cdf
    score = np.where(events[:, None], event_score, tail_score / survival[:, None])
    return float(-np.mean(np.where(events, log_pdf, np.log(survival)))), -score.mean(axis=0)


def model_law(model, class_id, times, cfg):
    parameters = model["parameters"][class_id]
    if model["family"] != "fpt":
        return hazard_law(model["family"], parameters, times)
    p = Params(*parameters)
    distance = cfg["known_distance"]
    cdf, density = [], []
    for t in np.atleast_1d(times):
        cdf.append(0.0 if t <= 0 else math.exp(log_discounted_hit(distance, float(t), *parameters)))
        density.append(0.0 if t <= 0 else math.exp(log_event_likelihood("hit", float(t), distance, p)))
    return np.asarray(cdf), np.asarray(density)


def mean_nll(model, class_id, records, cfg):
    times = np.array([record[1] for record in records])
    events = np.array([record[0] == "hit" for record in records])
    if model["family"] == "fpt":
        p = Params(*model["parameters"][class_id])
        return -float(np.mean([log_event_likelihood(*record, p) for record in records]))
    cdf, density = model_law(model, class_id, times, cfg)
    return -float(np.mean(np.log(np.maximum(np.where(events, density, 1 - cdf), 1e-300))))


def train_bundle(cfg=None):
    """Fit fixed families with common data. Does not draw confirmation episodes."""
    cfg = protocol() if cfg is None else cfg
    started = time.perf_counter()
    result = {"protocol_sha256": digest(cfg), "source_sha256": source_hashes(cfg), "seeds": []}
    for seed, dev_seed in zip(cfg["train_seeds"], cfg["dev_seeds"]):
        records = [generate_records(seed, y, cfg["train_records_per_class"], cfg) for y in range(2)]
        dev = [generate_records(dev_seed, y, cfg["validation_records_per_class"], cfg) for y in range(2)]
        row = {"seed": seed, "train_data_sha256": digest(records), "dev_data_sha256": digest(dev), "models": {}}
        for family in cfg["model_families"]:
            begin = time.perf_counter()
            model = {"family": family, "parameters": [], "fit_details": [], "parameter_count": 6}
            for y in range(2):
                attempts = []
                if family == "fpt":
                    for initial in cfg["fpt_starts"]:
                        fit = fit_events(records[y], Params(*initial), cfg["fpt_bounds"])
                        params = [fit.params.mu, fit.params.sigma, fit.params.cancel_rate]
                        attempts.append({"parameters": params, "loss": float(fit.loss),
                                         "calls": int(fit.calls), "iterations": int(fit.iterations),
                                         "success": bool(fit.success), "elapsed": float(fit.elapsed)})
                else:
                    for initial in cfg["hazard_starts"]:
                        begin_fit = time.perf_counter()
                        fit = minimize(hazard_objective, initial, args=(family, records[y]), jac=True,
                                       method="L-BFGS-B", bounds=cfg["hazard_bounds"],
                                       options={"maxiter": cfg["optimizer_maxiter"], "ftol": 1e-11, "gtol": 1e-7})
                        attempts.append({"parameters": fit.x.tolist(), "loss": float(fit.fun),
                                         "calls": int(fit.nfev), "iterations": int(fit.nit),
                                         "success": bool(fit.success), "elapsed": time.perf_counter() - begin_fit})
                finite = [attempt for attempt in attempts if np.isfinite(attempt["loss"])]
                if not finite:
                    raise RuntimeError(f"All {family} fits failed for class {y}")
                best = min(finite, key=lambda attempt: attempt["loss"])
                model["parameters"].append(best["parameters"])
                model["fit_details"].append({"selected": best, "all_starts": attempts})
            model["fit_wall_seconds"] = time.perf_counter() - begin
            model["train_nll"] = [mean_nll(model, y, records[y], cfg) for y in range(2)]
            model["dev_nll"] = [mean_nll(model, y, dev[y], cfg) for y in range(2)]
            model["model_parameter_bytes"] = np.asarray(model["parameters"], dtype=np.float64).nbytes
            row["models"][family] = model
        result["seeds"].append(row)
    result["total_training_wall_seconds"] = time.perf_counter() - started
    return result


def episode_bank(seed, count, cfg, regime="iid"):
    rng = np.random.default_rng(np.random.SeedSequence([seed, 97]))
    labels = rng.integers(0, 2, count)
    context = (2 * labels - 1) * cfg["context_signal"] + rng.normal(0, cfg["context_noise_sd"], count)
    bank = []
    for y, signal in zip(labels, context):
        hit, cancel = sample_contracts(rng, int(y), cfg["max_queries"], cfg, regime)
        bank.append({"label": int(y), "context": float(signal), "latent_hit": hit.tolist(), "latent_cancel": cancel.tolist()})
    return bank


def controller_tables(model, cfg):
    begin = time.perf_counter()
    nodes, weights = np.polynomial.legendre.leggauss(cfg["quadrature_nodes"])
    tables, residuals = {}, []
    for horizon in cfg["wait_horizons"]:
        times, integral_weights = horizon * (nodes + 1) / 2, horizon * weights / 2
        classes, mean_duration, event_prob = [], [], []
        for y in range(2):
            cdf, density = model_law(model, y, times, cfg)
            hit_probability = float(model_law(model, y, [horizon], cfg)[0][0])
            masses = integral_weights * density
            residuals.append(float(abs(masses.sum() - hit_probability)))
            if masses.sum() > 0:
                masses *= hit_probability / masses.sum()
            elif hit_probability > 1e-12:
                raise ArithmeticError("Quadrature did not resolve a positive event mass")
            classes.append(np.r_[masses, 1 - hit_probability])
            mean_duration.append(float(np.dot(integral_weights, 1 - cdf)))
            event_prob.append(hit_probability)
        tables[horizon] = {"law": np.array(classes), "duration": np.array(mean_duration), "hit": np.array(event_prob)}
    return tables, {"controller_precompute_seconds": time.perf_counter() - begin,
                    "controller_table_bytes": sum(value.nbytes for table in tables.values() for value in table.values()),
                    "quadrature_max_mass_residual": max(residuals)}


def choose_horizon(prior, remaining, tables, cfg):
    posterior = np.array([1 - prior, prior])
    correct, wrong = cfg["reward_correct"], cfg["reward_wrong"]
    stop = wrong + (correct - wrong) * max(prior, 1 - prior)
    selected, best = None, stop
    for horizon, table in tables.items():
        if horizon > remaining + 1e-12:
            continue
        accuracy = np.max(posterior[:, None] * table["law"], axis=0).sum()
        cost = (cfg["query_cost"] + cfg["wait_cost_per_time"] * posterior.dot(table["duration"])
                + cfg["observed_hit_cost"] * posterior.dot(table["hit"]))
        value = wrong + (correct - wrong) * accuracy - cost
        if value > best + 1e-12:
            selected, best = horizon, value
    return selected


def rollout(model, episode, tables, cfg):
    # Only context and returned observations enter the posterior/controller.
    log_odds = 2 * cfg["context_signal"] * episode["context"] / cfg["context_noise_sd"] ** 2
    elapsed, queries, hits = 0.0, 0, 0
    for index in range(cfg["max_queries"]):
        horizon = choose_horizon(float(expit(log_odds)), cfg["deadline"] - elapsed, tables, cfg)
        if horizon is None:
            break
        hit = episode["latent_hit"][index]
        event = hit < episode["latent_cancel"][index] and hit <= horizon
        observed_time = hit if event else horizon
        likelihood = []
        for y in range(2):
            cdf, density = model_law(model, y, [observed_time], cfg)
            likelihood.append(float(density[0] if event else 1 - cdf[0]))
        log_odds += math.log(max(likelihood[1], 1e-300)) - math.log(max(likelihood[0], 1e-300))
        elapsed += observed_time
        queries += 1
        hits += int(event)
    prediction = int(log_odds >= 0)
    correct = prediction == episode["label"]
    cost = cfg["query_cost"] * queries + cfg["wait_cost_per_time"] * elapsed + cfg["observed_hit_cost"] * hits
    return {"utility": (cfg["reward_correct"] if correct else cfg["reward_wrong"]) - cost,
            "accuracy": float(correct), "queries": queries, "elapsed_task_time": elapsed,
            "observed_hits": hits, "resource_cost": cost}


def evaluate_bundle(bundle, split, cfg=None, bundle_path=None, freeze_commit=None):
    cfg = protocol() if cfg is None else cfg
    if split not in {"dev", "confirm", "ood"}:
        raise ValueError("Unknown evaluation split")
    if source_hashes(cfg) != bundle["source_sha256"] or digest(cfg) != bundle["protocol_sha256"]:
        raise ValueError("Source/protocol changed since training; train a new bundle")
    if split in {"confirm", "ood"}:
        if bundle_path is None:
            raise ValueError("Confirmation needs a frozen bundle path")
        validate_freeze(freeze_commit, bundle_path, cfg)
    original_cfg = cfg
    if split == "ood":
        cfg = dict(cfg, deadline=cfg["ood"]["deadline"], wait_cost_per_time=cfg["ood"]["wait_cost_per_time"])
    started = time.perf_counter()
    report = {"split": split, "freeze_commit": freeze_commit, "bundle_sha256": digest(bundle),
              "protocol_sha256": digest(original_cfg), "source_sha256": source_hashes(original_cfg), "seeds": []}
    for trained, eval_seed in zip(bundle["seeds"], cfg[f"{split}_seeds"]):
        bank_begin = time.perf_counter()
        bank = episode_bank(eval_seed, cfg[f"{split}_episodes_per_seed"], cfg, "ood" if split == "ood" else "iid")
        row = {"training_seed": trained["seed"], "evaluation_seed": eval_seed, "episode_bank_sha256": digest(bank),
               "simulator_seconds": time.perf_counter() - bank_begin, "models": {}}
        immediate = [float((episode["context"] >= 0) == episode["label"]) for episode in bank]
        row["immediate_stop"] = {"accuracy": float(np.mean(immediate)),
                                  "utility": float(np.mean(immediate) * (cfg["reward_correct"] - cfg["reward_wrong"]) + cfg["reward_wrong"])}
        for family, model in trained["models"].items():
            tables, costs = controller_tables(model, cfg)
            begin = time.perf_counter()
            raw = [rollout(model, episode, tables, cfg) for episode in bank]
            costs["controller_execution_seconds"] = time.perf_counter() - begin
            costs["fit_wall_seconds"] = model["fit_wall_seconds"]
            costs["model_parameter_bytes"] = model["model_parameter_bytes"]
            heldout = [generate_records(eval_seed, y, cfg["validation_records_per_class"], cfg,
                                       "ood" if split == "ood" else "iid") for y in range(2)]
            row["models"][family] = {"means": {key: float(np.mean([record[key] for record in raw])) for key in raw[0]},
                                      "heldout_event_nll": [mean_nll(model, y, heldout[y], cfg) for y in range(2)],
                                      "heldout_records_sha256": digest(heldout), "costs": costs, "raw": raw}
        report["seeds"].append(row)
    report["paired_contrasts"] = []
    for left, right in cfg["primary_contrasts"]:
        differences = [row["models"][left]["means"]["utility"] - row["models"][right]["means"]["utility"] for row in report["seeds"]]
        count = len(differences)
        standard_error = float(np.std(differences, ddof=1) / math.sqrt(count)) if count > 1 else 0.0
        critical = float(student_t.ppf(1 - 0.05 / (2 * len(cfg["primary_contrasts"])), count - 1)) if count > 1 else 0.0
        mean = float(np.mean(differences))
        report["paired_contrasts"].append({"left": left, "right": right, "seed_differences": differences,
                                            "mean": mean, "simultaneous_95_percent_interval": [mean - critical * standard_error, mean + critical * standard_error]})
    report["evaluation_wall_seconds"] = time.perf_counter() - started
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=["train", "dev", "confirm", "ood"])
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze-commit")
    args = parser.parse_args()
    if args.phase == "train":
        result, destination = train_bundle(), args.bundle
    else:
        if args.output is None:
            parser.error("Evaluation requires --output")
        result = evaluate_bundle(json.loads(args.bundle.read_text()), args.phase,
                                 bundle_path=args.bundle, freeze_commit=args.freeze_commit)
        destination = args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"phase": args.phase, "output": str(destination), "sha256": digest(result)}))


if __name__ == "__main__":
    main()

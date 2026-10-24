"""Proper categorical fitting with source-pair OOF and finite-family calibration."""

from copy import deepcopy
import math
import time

import torch
from torch.nn import functional as F

from ..v6.neural import parameter_hash
from .forecast import CategoricalForecast, DistributionHead, certainty_equivalent


def categorical_loss(logits, targets):
    mask = torch.isfinite(targets)
    if not mask.any():
        raise ValueError("A fitted batch must contain actual endpoint labels")
    # Linear interpolation preserves the exact label mean; bin width .01 gives
    # gamma=2 randomized-rounding CE bias at most gamma*width^2/8 = 2.5e-5.
    positions = (torch.nan_to_num(targets).clamp(-1, 1) + 1) * 100
    lower = positions.floor().long().clamp(0, 200)
    upper = (lower + 1).clamp(0, 200)
    fraction = positions - lower
    logp = F.log_softmax(logits, -1)
    losses = -(1 - fraction) * logp.gather(-1, lower[..., None]).squeeze(-1)
    losses -= fraction * logp.gather(-1, upper[..., None]).squeeze(-1)
    # Balance continuation heads, including two-step heads available only at
    # initialization. Invalid suffixes never receive a fabricated zero label.
    per_head = (losses * mask).sum(0) / mask.sum(0).clamp_min(1)
    return per_head[mask.any(0)].mean()


def _fit(data, allowed, initial, *, seed, steps, batch_size):
    model = deepcopy(initial).train()
    optimizer = torch.optim.Adam(model.parameters(), lr=.002)
    rng = torch.Generator().manual_seed(seed)
    gradients, history = 0., []
    for _ in range(steps):
        selected = allowed[torch.randint(len(allowed), (batch_size,), generator=rng)]
        objective = categorical_loss(model(data.features[selected]), data.targets[selected])
        if not torch.isfinite(objective):
            raise FloatingPointError("Nonfinite categorical objective")
        optimizer.zero_grad(set_to_none=True)
        objective.backward()
        gradients = max(gradients, sum(float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None))
        optimizer.step()
        history.append(float(objective.detach()))
    return model.eval().requires_grad_(False), {"objective_history": history, "gradient_abs_sum_max": gradients}


def catalogue_statistics(head, data, *, temperature=1., ids=None):
    """Every eligible state/suffix prediction, not only the stop head."""
    ids = torch.arange(len(data.features)) if ids is None else ids
    result = {key: torch.full_like(data.targets, float("nan"), dtype=torch.float64)
              for key in ("mean", "ce", "lower", "upper", "crps")}
    values = torch.linspace(-1, 1, 201, dtype=torch.float64)
    with torch.inference_mode():
        for block in ids.split(128):
            probabilities = (head(data.features[block]).double() / temperature).softmax(-1)
            cdf = probabilities.cumsum(-1)
            truth = values >= data.targets[block, :, None]
            result["mean"][block] = (probabilities * values).sum(-1)
            result["ce"][block] = certainty_equivalent(values, probabilities, 2.)
            result["lower"][block] = values[(cdf >= .05).long().argmax(-1)]
            result["upper"][block] = values[(cdf >= .95).long().argmax(-1)]
            result["crps"][block] = (cdf - truth.double()).square().sum(-1) * .01
    return result


def family_diagnostic(statistics, data, *, radius=None):
    """Source-balanced maxima over all views, inits, current states and suffixes."""
    per_pair = []
    valid = torch.isfinite(data.targets)
    if any(not torch.isfinite(statistics[key][valid]).all() for key in statistics):
        raise ValueError("A registered prediction is missing/nonfinite")
    for group in range(data.evidence["pairs"]):
        ids = (data.groups == group).nonzero().flatten()
        mask = valid[ids]
        actual = data.targets[ids][mask].double()
        mean, lower, upper = (statistics[key][ids][mask] for key in ("mean", "lower", "upper"))
        errors = (mean - actual).abs()
        item = {"pair": group, "labeled_predictions": len(actual), "mae": float(errors.mean()),
                "max_absolute_mean_error": float(errors.max()),
                "crps": float(statistics["crps"][ids][mask].mean()),
                "central90_coverage": float(((actual >= lower) & (actual <= upper)).double().mean()),
                "central90_width": float((upper - lower).mean())}
        if radius is not None:
            item["finite_family_all_covered"] = bool((errors <= radius + 1e-12).all())
            item["finite_family_mean_width"] = float(((mean + radius).clamp_max(1)
                                                       - (mean - radius).clamp_min(-1)).mean())
        per_pair.append(item)
    result = {"source_pairs": len(per_pair), "per_source_pair": per_pair,
              "labeled_predictions": int(torch.isfinite(data.targets).sum())}
    for name in ("mae", "crps", "central90_coverage", "central90_width"):
        result[f"source_balanced_{name}"] = sum(item[name] for item in per_pair) / len(per_pair)
    if radius is not None:
        result["finite_family_all_covered_fraction"] = sum(item["finite_family_all_covered"] for item in per_pair) / len(per_pair)
        result["source_balanced_finite_family_width"] = sum(item["finite_family_mean_width"] for item in per_pair) / len(per_pair)
    return result


def fit_forecast(snapshot, fit_data, calibration_data, metric_contract, *, seed=17, steps=600,
                 folds=4, batch_size=256, alpha=.1):
    if (folds != 4 or fit_data.evidence["pairs"] < 4 or steps < 1 or batch_size < 1
            or fit_data.evidence["role"] != "forecast_fit"
            or calibration_data.evidence["role"] != "forecast_calibration"
            or not 0 < alpha < 1):
        raise ValueError("Invalid source-pair forecast registration")
    fit_pixels = {value.rsplit(":", 1)[1] for pair in fit_data.evidence["source_pairs"] for value in pair}
    cal_pixels = {value.rsplit(":", 1)[1] for pair in calibration_data.evidence["source_pairs"] for value in pair}
    if fit_pixels & cal_pixels:
        raise ValueError("Forecast fit/calibration source leakage")
    for data in (fit_data, calibration_data):
        if (data.evidence["snapshot_sha256"] != snapshot.fingerprint
                or data.evidence["metric_contract_sha256"] != metric_contract.validate()
                or torch.isinf(data.targets).any() or not torch.isfinite(data.targets[:, 0]).all()
                or not torch.isfinite(data.features).all()
                or set(data.groups.tolist()) != set(range(data.evidence["pairs"]))):
            raise ValueError("Forecast data/source/model/metric binding mismatch")
    if fit_data.evidence["source_manifest_sha256"] != calibration_data.evidence["source_manifest_sha256"]:
        raise ValueError("Forecast source registrations differ")
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed + 31337)
        initial = DistributionHead()
    initial_hash = parameter_hash(initial)
    oof_logits = torch.empty(len(fit_data.features), 201, dtype=torch.float32)
    folds_report, fold_models = [], []
    for fold in range(folds):
        held = fit_data.groups.remainder(folds) == fold
        train_ids = (~held).nonzero().flatten()
        model, training = _fit(fit_data, train_ids, initial, seed=seed + fold * 104729,
                               steps=steps, batch_size=batch_size)
        ids = held.nonzero().flatten()
        with torch.inference_mode():
            for block in ids.split(256):
                oof_logits[block] = model(fit_data.features[block])[:, 0]
        folds_report.append({"fold": fold, "held_source_pairs": int(fit_data.groups[held].unique().numel()),
                              "train_source_pairs": int(fit_data.groups[~held].unique().numel()), **training})
        fold_models.append((model, ids))
    # Temperature is fitted ONLY to source-group-held-out predictions in the
    # fit role. The independently reserved calibration role is not optimized.
    log_temperature = torch.zeros((), requires_grad=True)
    optimizer = torch.optim.Adam([log_temperature], lr=.05)
    labels = fit_data.targets[:, 0]
    rng = torch.Generator().manual_seed(seed + 65537)
    for _ in range(150):
        ids = torch.randint(len(labels), (2048,), generator=rng)
        logits = oof_logits[ids, None] / log_temperature.exp().clamp(.25, 4.)
        objective = categorical_loss(logits, labels[ids, None])
        optimizer.zero_grad(set_to_none=True)
        objective.backward()
        optimizer.step()
    temperature = float(log_temperature.detach().exp().clamp(.25, 4.))
    model, final_training = _fit(fit_data, torch.arange(len(fit_data.features)), initial,
                                  seed=seed + 999983, steps=steps, batch_size=batch_size)
    cal_statistics = catalogue_statistics(model, calibration_data, temperature=temperature)
    cal_diagnostic = family_diagnostic(cal_statistics, calibration_data)
    maxima = sorted(row["max_absolute_mean_error"] for row in cal_diagnostic["per_source_pair"])
    rank = math.ceil((len(maxima) + 1) * (1 - alpha))
    radius = maxima[rank - 1] if rank <= len(maxima) else 2.
    calibration = {"method": "split_conformal_max_absolute_mean_error_over_finite_endpoint_family",
                   "alpha": alpha, "source_pairs": len(maxima), "order_statistic_rank": rank,
                   "radius": radius, "source_manifest_sha256": calibration_data.evidence["source_manifest_sha256"],
                   "source_pair_sha256": calibration_data.evidence["source_pair_sha256"],
                   "family": "all legal current-prefix/continuation-suffix predictions within total neural horizon4, full/allocation",
                   "views": calibration_data.evidence["views"],
                   "noise_scenarios": calibration_data.evidence["scenarios"],
                   "assumption": "exchangeable source-pair groups with the registered input and noise law",
                   "arbitrary_adaptive_or_shifted_coverage_claim": False,
                   "conditional_distribution_calibrated_claim": False}
    artifact = CategoricalForecast(model, snapshot.fingerprint, metric_contract, temperature=temperature,
                                    calibration=calibration, metadata={"fit_pairs": fit_data.evidence["pairs"], "seed": seed})
    oof_statistics = None
    for fold_model, ids in fold_models:
        values = catalogue_statistics(fold_model, fit_data, temperature=temperature, ids=ids)
        if oof_statistics is None:
            oof_statistics = values
        else:
            for key in values:
                oof_statistics[key][ids] = values[key][ids]
    oof_diagnostic = family_diagnostic(oof_statistics, fit_data)
    evidence = {"schema": "hepta.ndu-v7.categorical-forecast-fitting.v1", "seed": seed,
                "initial_parameter_sha256": initial_hash, "final_parameter_sha256": parameter_hash(model),
                "forecast_fingerprint": artifact.fingerprint, "snapshot_sha256": snapshot.fingerprint,
                "temperature": temperature, "temperature_data": "source-pair OOF stop forecasts in fit role only",
                "oof_report_scope": "backbone held out by source pair; scalar temperature assessed on its pooled fit scores",
                "folds": folds_report, "final_training": final_training, "optimizer_steps_each_fit": steps,
                "oof_diagnostic": oof_diagnostic, "calibration_diagnostic": cal_diagnostic,
                "calibration": calibration, "formal_holdout_opened": False,
                "wall_ns": time.perf_counter_ns() - start_wall, "cpu_ns": time.process_time_ns() - start_cpu,
                "model_work": {"gradient_training_examples": (folds + 1) * steps * batch_size,
                               "temperature_gradient_examples": 150 * 2048,
                               "oof_stop_forward_examples": len(fit_data.features),
                               "oof_all_heads_forward_examples": len(fit_data.features),
                               "calibration_all_heads_forward_examples": len(calibration_data.features)},
                "fit_dataset": fit_data.evidence, "calibration_dataset": calibration_data.evidence}
    return artifact, evidence

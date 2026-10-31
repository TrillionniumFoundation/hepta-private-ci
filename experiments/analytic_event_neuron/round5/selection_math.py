"""Matched development selectors over two declared candidate geometries."""

from copy import deepcopy
import time

import numpy as np

from .. import learners, task
from ..round4 import calibration as cal


def zero_context():
    """The inherited prior fitter counts this empty acquisition collection."""
    return {"obs": np.empty((0, 8))}


def single_model(component):
    model = cal.make_model(component, component, context_count=0)
    model["prior"] = 0.
    return model


def _development(old, new):
    if any(data["split"] != "calibration_development" or len(data["ids"]) < 2
           for data in (old, new)):
        raise ValueError("Selectors require separate labelled development collections")
    return [task.history(data) for data in (old, new)], [task.targets(data) for data in (old, new)]


def _choice(losses, anchor_loss, rows):
    for loss, row in zip(losses, rows):
        if not all(np.isfinite(value).all() for value in loss):
            raise ValueError("Candidate losses must be finite")
        difference = (loss[0] - anchor_loss).mean(1)
        mean = float(difference.mean())
        se = float(difference.std(ddof=1) / np.sqrt(len(difference)))
        row.update(old_nll_change=mean, old_paired_se=se,
                   old_upper_heuristic=mean + 1.645 * se,
                   new_nll=float(loss[1].mean()), eligible=mean + 1.645 * se <= .02)
    eligible = [i for i, row in enumerate(rows) if row["eligible"]]
    if not eligible:
        raise AssertionError("The unchanged anchor must be feasible")
    return min(eligible, key=lambda i: (rows[i]["new_nll"], i))


def select_prior(model, old, new, grid):
    if model["context_count"] != 0 or grid not in ("legacy", "full_range"):
        raise ValueError("A zero-context model and declared prior grid are required")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    histories, targets = _development(old, new)
    caches = [cal.component_cache(model, history) for history in histories]
    anchor = -cal.mixture_log_density(cal.distribution_from_cache(caches[0], 0.), targets[0])[:, 1:]
    priors = [strength * model["prior"] if grid == "legacy" else strength
              for strength in cal.STRENGTHS]
    rows = [{"strength": strength, "prior": prior} for strength, prior in zip(cal.STRENGTHS, priors)]
    losses = [[-cal.mixture_log_density(cal.distribution_from_cache(cache, prior, model["projection"]), target)[:, 1:]
               for cache, target in zip(caches, targets)] for prior in priors]
    chosen = _choice(losses, anchor, rows)
    selected = {**deepcopy(model), "prior": priors[chosen]}
    return selected, {"grid": grid, "fitted_prior": model["prior"], "candidates": rows,
                      "selected_index": chosen, "candidate_count": len(rows),
                      "development_dataset_digests": [task.dataset_digest(data) for data in (old, new)],
                      "development_labelled_queries": len(old["ids"]) + len(new["ids"]),
                      "public_context_histories": 0, "grids_not_assumed_nested": True,
                      "old_guard_is_selection_heuristic_not_guarantee": True,
                      "selection_wall_ns": time.perf_counter_ns() - started,
                      "selection_parent_cpu_ns": time.process_time_ns() - cpu}


def select_gaussian(anchor, endpoint, old, new, endpoint_name):
    if endpoint_name not in ("balanced_replay", "current_only_online"):
        raise ValueError("Declare the Gaussian interpolation endpoint")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    histories, targets = _development(old, new)
    mean, var = learners.predict(anchor, histories[0])
    base = .5 * (np.log(2 * np.pi * var[:, 1:]) + (targets[0][:, 1:] - mean[:, 1:]) ** 2 / var[:, 1:])
    rows, losses, models = [], [], []
    for strength in cal.STRENGTHS:
        parameters = ((1 - strength) * np.asarray(anchor["parameters"])
                      + strength * np.asarray(endpoint["parameters"]))
        candidate = {**deepcopy(endpoint), "parameters": parameters.tolist(),
                     "planning_q": float(parameters[1]), "planning_noise_scale": float(parameters[2])}
        current = []
        for history, target in zip(histories, targets):
            m, v = learners.predict(candidate, history)
            current.append(.5 * (np.log(2 * np.pi * v[:, 1:]) + (target[:, 1:] - m[:, 1:]) ** 2 / v[:, 1:]))
        rows.append({"strength": strength, "parameters": parameters.tolist()})
        losses.append(current)
        models.append(single_model(candidate))
    chosen = _choice(losses, base, rows)
    return models[chosen], {"endpoint": endpoint_name, "candidates": rows, "selected_index": chosen,
                           "candidate_count": len(rows), "public_context_histories": 0,
                           "development_dataset_digests": [task.dataset_digest(data) for data in (old, new)],
                           "development_labelled_queries": len(old["ids"]) + len(new["ids"]),
                           "old_guard_is_selection_heuristic_not_guarantee": True,
                           "selection_wall_ns": time.perf_counter_ns() - started,
                           "selection_parent_cpu_ns": time.process_time_ns() - cpu}

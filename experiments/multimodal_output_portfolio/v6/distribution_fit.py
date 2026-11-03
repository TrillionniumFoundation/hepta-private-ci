"""Source-group cross-fitting and finite empirical location/scale calibration.

Only the validation source split is used. One endpoint is selected independently
of utilities for each calibration pair, retaining all standardized residuals.
Development scores remain source-pair aggregates; correlated routes are never
reported as additional independent calibration or evaluation cases.
"""

from dataclasses import replace
import hashlib
import math
import random
import time

import torch

from .control import entropic_value
from .data import Observation, make_batch
from .distribution import ConditionalForecastBundle, PROFILE, VIEWS, public_features
from .forecast import RidgeHead, _collect, _observe
from .neural import ACTIONS, parameter_hash
from .observer import METRIC_DIGEST


def endpoint_plan(pairs, horizon, seed):
    """Choose view/initialization/endpoint before any utility label is read."""
    rng = random.Random(seed)
    plan = []
    for group in range(pairs):
        view, full = rng.choice(VIEWS), bool(rng.randrange(2))
        plan.append({"source_pair": group, "view": view, "full_initialization": full,
                     "endpoint": rng.randrange(1 + (4 if full else 2) * horizon)})
    return plan


def _batch(corpus, count, seed, offset, view):
    actual = "missing" if view in ("wrong_hint", "missing_no_hint") else view
    batch = make_batch(corpus, "validation", count, seed, actual, offset=offset,
                       drop_hint=view == "missing_no_hint")
    if view == "wrong_hint":
        tokens = batch.observation.text_tokens.clone()
        for position in (3, 5):
            selected = tokens[:, position] >= 14
            tokens[selected, position] = 14 + (tokens[selected, position] - 14 + 1) % 10
        batch = replace(batch, observation=Observation(batch.observation.pixels, batch.observation.mask, tokens))
    return batch


def _partition(snapshot, corpus, observer, count, seed, offset, horizon, counts, plan):
    xs, ys, groups, router_x, router_y, initial, starts, strata = [], [], [], [], [], [], {}, []
    size, source_ids = 0, None
    for view in VIEWS:
        batch = _batch(corpus, count, seed, offset, view)
        if source_ids is not None and batch.source_ids != source_ids:
            raise ValueError("Public views changed original source pairs")
        source_ids = batch.source_ids
        summaries = public_features(batch.observation)
        counts["public_summary_batch_calls"] += 1
        counts["public_summary_case_calls"] += count
        for full in (True, False):
            data = _collect(snapshot, batch, observer, seed, horizon, counts, full)
            repeats = len(data[1]) // count
            starts[(view, full)] = size
            xs.append(torch.cat((data[0], summaries.repeat(repeats, 1)), 1))
            ys.append(data[1])
            groups.append(torch.arange(count).repeat(repeats))
            actions = ACTIONS if full else ("refine_image", "refine_text")
            strata.extend((view, "full" if full else "allocation",
                           "initial" if endpoint == 0 else actions[(endpoint - 1) % len(actions)],
                           0 if endpoint == 0 else (endpoint - 1) // len(actions) + 1)
                          for endpoint in range(repeats) for _ in range(count))
            size += len(data[1])
            if full:
                router_x.append(torch.cat((data[2], summaries.repeat(horizon, 1)), 1))
                router_y.append(data[3])
                initial.append((data[4], batch))
    selected = torch.tensor([starts[(item["view"], item["full_initialization"])]
                             + item["endpoint"] * count + item["source_pair"] for item in plan])
    return {"x": torch.cat(xs), "y": torch.cat(ys), "groups": torch.cat(groups),
            "router_x": torch.cat(router_x), "router_y": torch.cat(router_y),
            "initial": initial, "selected": selected, "source_ids": source_ids,
            "strata": strata}


def grouped_error_scale(features, utilities, groups):
    """All views/routes of a pair are withheld together for its error target."""
    unique = sorted(set(groups.tolist()))
    if len(unique) < 4 or unique != list(range(len(unique))):
        raise ValueError("Four folds require consecutive identities for >=4 source pairs")
    fold = groups % 4
    out_of_fold = torch.empty_like(utilities)
    evidence = []
    for index in range(4):
        held = fold == index
        head = RidgeHead.fit(features[~held], utilities[~held])
        out_of_fold[held] = head(features[held]).squeeze(1).clamp(-1, 1)
        evidence.append({"fold": index, "held_source_pairs": [g for g in unique if g % 4 == index],
                         "training_source_pairs": [g for g in unique if g % 4 != index],
                         "held_rows": int(held.sum()), "training_rows": int((~held).sum())})
    absolute_error = (utilities - out_of_fold).abs()
    return RidgeHead.fit(features, absolute_error), evidence, absolute_error


def _score_rows(bundle, features, utilities):
    location, scale = bundle.location_scale(features)
    values = (location[:, None] + scale[:, None] * bundle.residuals[None, :]).clamp(-1, 1)
    ordered = values.sort(1).values
    size = values.shape[1]
    coefficients = 2 * torch.arange(1, size + 1, dtype=torch.float64) - size - 1
    crps = (values - utilities[:, None]).abs().mean(1) - (ordered * coefficients).sum(1) / size ** 2
    low, high = ordered[:, math.ceil(.05 * size) - 1], ordered[:, math.ceil(.95 * size) - 1]
    forecast_mean = values.mean(1)
    ce = torch.tensor([entropic_value(row.tolist(), [1 / size] * size, 2) for row in values], dtype=torch.float64)
    return {"crps": crps, "mean_absolute_error": (forecast_mean - utilities).abs(),
            "mean_error": forecast_mean - utilities, "observed_utility": utilities,
            "forecast_mean": forecast_mean, "forecast_ce_gamma2": ce,
            "interval90_covered": ((utilities >= low) & (utilities <= high)).double(),
            "interval90_width": high - low, "error_scale": scale,
            "scale_at_floor": (scale == .02).double(), "scale_at_ceiling": (scale == 2).double()}


def _source_scores(scores, groups):
    per_pair = [{"source_pair": group, **{name: value[groups == group].mean().item()
                 for name, value in scores.items()}} for group in sorted(set(groups.tolist()))]
    return {"source_pairs": len(per_pair), "rows": len(groups), "per_source_pair": per_pair,
            "pair_mean": {name: sum(record[name] for record in per_pair) / len(per_pair) for name in scores},
            "scope": "empirical source-pair aggregates; no conditional or selected-policy coverage guarantee"}


def _selected_diagnostics(scores, groups, strata, penalty):
    candidates = {}
    for index, (group, stratum) in enumerate(zip(groups.tolist(), strata)):
        candidates.setdefault((group, *stratum[:2]), []).append(index)
    result = {}
    for label, criterion in (("risk_neutral_mean", "forecast_mean"), ("risk_aware_gamma2", "forecast_ce_gamma2")):
        chosen = [max(indices, key=lambda i: float(scores[criterion][i]) - penalty * strata[i][3])
                  for indices in candidates.values()]
        selected = torch.tensor(chosen)
        result[label] = {**_source_scores({name: value[selected] for name, value in scores.items()}, groups[selected]),
            "selection_objective": criterion + " minus declared continuation-depth work penalty",
            "action_cost_penalty": penalty,
            "selection_scope": "collected legal endpoints within each source pair/view/initialization; not deployed receding-horizon policy",
            "selected_endpoints": [{"source_pair": int(groups[i]), "view": strata[i][0],
                                    "initialization": strata[i][1], "terminal_action": strata[i][2],
                                    "depth": strata[i][3], "registered_row": i} for i in chosen]}
    return result


def _tune_static(snapshot, collected, observer, horizon, penalty, counts):
    sequences = [tuple([action] * horizon) for action in ACTIONS]
    sequences += [tuple(ACTIONS[(start + i) % 4] for i in range(horizon)) for start in range(4)]
    sequences += [tuple(("refine_image", "refine_text")[(start + i) % 2] for i in range(horizon)) for start in range(2)]
    candidates = sorted({sequence[:length] for sequence in sequences for length in range(horizon + 1)},
                        key=lambda sequence: (len(sequence), sequence))
    utilities = {sequence: [] for sequence in candidates}
    for initial, batch in collected["initial"]:
        cache = {(): initial}
        for sequence in candidates:
            if sequence:
                cache[sequence] = snapshot.step(cache[sequence[:-1]], sequence[-1])
                counts["transition_batch_calls"] += 1
                counts["transition_case_calls"] += len(batch.source_ids)
            _, utility = _observe(snapshot, cache[sequence], batch, observer, counts)
            utilities[sequence].append(utility)
    records = []
    for sequence, parts in utilities.items():
        values = torch.cat(parts).tolist()
        mean = sum(values) / len(values)
        records.append({"sequence": list(sequence), "mean_external_utility": mean,
                        "selection_score": mean - penalty * len(sequence),
                        "action_cost": penalty * len(sequence),
                        "dev_empirical_entropic_utility_gamma2": entropic_value(values, [1 / len(values)] * len(values), 2)})
    return max(records, key=lambda row: row["selection_score"])["sequence"], records


@torch.inference_mode()
def fit_conditional_forecast(snapshot, corpus, observer_model, seed, fit_pairs=128,
                             calibration_pairs=64, dev_pairs=64, horizon=3, action_cost_penalty=.002):
    if (any(type(n) is not int or n < 2 for n in (fit_pairs, calibration_pairs, dev_pairs))
            or fit_pairs < 4 or calibration_pairs > 256 or type(horizon) is not int or horizon < 1
            or not math.isfinite(action_cost_penalty) or action_cost_penalty < 0):
        raise ValueError("Invalid conditional forecast partitions, horizon or penalty")
    source = corpus.splits["validation"]
    if 2 * (fit_pairs + calibration_pairs + dev_pairs) > len(source):
        raise ValueError("Insufficient source-disjoint validation pairs")
    if observer_model.training or any(parameter.requires_grad for parameter in observer_model.parameters()):
        raise ValueError("Offline utility observer must be frozen and in evaluation mode")
    started = time.perf_counter_ns()
    snapshot.verify_integrity()
    observer_digest = parameter_hash(observer_model)
    counts = {f"{operation}_{unit}_calls": 0 for operation in
              ("encode", "transition", "decode", "observer", "public_summary") for unit in ("batch", "case")}
    plans = {name: endpoint_plan(count, horizon, seed + 7919 + index * 104729)
             for index, (name, count) in enumerate((("fit", fit_pairs), ("calibration", calibration_pairs), ("dev", dev_pairs)))}
    parts, partitions, seen_ids, seen_pixels, offset = {}, {}, set(), set(), 0
    for index, (name, count) in enumerate((("fit", fit_pairs), ("calibration", calibration_pairs), ("dev", dev_pairs))):
        ids = list(source.ids[2 * offset:2 * (offset + count)])
        pixels = list(source.pixel_hashes[2 * offset:2 * (offset + count)])
        if (len(set(ids)) != len(ids) or len(set(pixels)) != len(pixels)
                or seen_ids.intersection(ids) or seen_pixels.intersection(pixels)):
            raise ValueError("Source identity/pixel leakage across forecast partitions")
        seen_ids.update(ids)
        seen_pixels.update(pixels)
        parts[name] = _partition(snapshot, corpus, observer_model, count, seed + index,
                                 offset, horizon, counts, plans[name])
        partitions[name] = {"pair_offset": offset, "pairs": count, "source_ids": ids, "pixel_hashes": pixels,
                            "identity_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
                            "pixel_set_sha256": hashlib.sha256("\n".join(sorted(pixels)).encode()).hexdigest(),
                            "rollout_rows": len(parts[name]["y"]), "endpoint_plan": plans[name]}
        offset += count
    fit, cal, dev = (parts[name] for name in ("fit", "calibration", "dev"))
    scale_head, folds, errors = grouped_error_scale(fit["x"], fit["y"], fit["groups"])
    utility_head = RidgeHead.fit(fit["x"], fit["y"])
    action_head = RidgeHead.fit(fit["router_x"], fit["router_y"])
    cal_x, cal_y = cal["x"][cal["selected"]], cal["y"][cal["selected"]]
    location = utility_head(cal_x).squeeze(1).clamp(-1, 1)
    scale = scale_head(cal_x).squeeze(1).clamp(.02, 2)
    residuals = (cal_y - location) / scale
    selected, sequence_scores = _tune_static(snapshot, dev, observer_model, horizon, action_cost_penalty, counts)
    bundle = ConditionalForecastBundle(utility_head, scale_head, action_head, residuals, snapshot.fingerprint, selected)
    dev_scores = _score_rows(bundle, dev["x"], dev["y"])
    selected_scores = {name: values[dev["selected"]] for name, values in dev_scores.items()}
    action_scores = {}
    for action in ("initial", *ACTIONS):
        mask = torch.tensor([stratum[2] == action for stratum in dev["strata"]])
        action_scores[action] = _source_scores({name: values[mask] for name, values in dev_scores.items()}, dev["groups"][mask])
    snapshot.verify_integrity()
    if parameter_hash(observer_model) != observer_digest:
        raise RuntimeError("Independent observer changed during forecast labeling")
    evidence = {"schema": "hepta.ndu-v6.heteroskedastic-forecast-evidence.v1", "profile": PROFILE,
        "seed": seed, "horizon": horizon, "snapshot_sha256": snapshot.fingerprint,
        "forecast_sha256": bundle.fingerprint, "observer_sha256": observer_digest, "metric_sha256": METRIC_DIGEST,
        "source_manifest_sha256": corpus.manifest["manifest_sha256"], "partitions": partitions,
        "source_pair_folds": folds, "out_of_fold_absolute_error_mean": errors.mean().item(),
        "scale_target": "absolute held-pair forecast error; not certified conditional standard deviation",
        "calibration_support": residuals.tolist(), "calibration_probabilities": [1 / calibration_pairs] * calibration_pairs,
        "calibration_source_pairs": calibration_pairs, "residual_scenarios": len(residuals),
        "calibration_selection_before_utility_observation": True,
        "calibration": _source_scores(_score_rows(bundle, cal_x, cal_y), torch.arange(calibration_pairs)),
        "dev_presampled_endpoints": _source_scores(selected_scores, torch.arange(dev_pairs)),
        "dev_all_registered_endpoints": _source_scores(dev_scores, dev["groups"]),
        "dev_forecast_selected_endpoints": _selected_diagnostics(dev_scores, dev["groups"], dev["strata"], action_cost_penalty),
        "dev_by_terminal_action": action_scores, "static_sequence": selected,
        "fixed_sequence_candidates": sequence_scores,
        "fixed_sequence_selection": {"objective": "mean external utility over six views minus continuation work penalty",
                                     "action_cost_penalty": action_cost_penalty, "stopping": "all prefixes including empty; shortest exact tie",
                                     "initialization": "full only; source pairs and views have equal total weight"},
        "offline_calls": counts, "offline_head_fits": 7,
        "offline_head_predictions": {"mean_case_calls": len(fit["x"]) + 2 * calibration_pairs + len(dev["x"]),
                                     "scale_case_calls": 2 * calibration_pairs + len(dev["x"]),
                                     "mean_batch_calls": 7, "scale_batch_calls": 3,
                                     "action_batch_calls": 0, "action_case_calls": 0},
        "offline_initial_plan_work_units": getattr(snapshot, "initial_plan_cost", 0) * counts["encode_case_calls"],
        "offline_accounting_scope": "encode calls include internal initial gate; initial-plan work counts fixed internal transitions only, not total training FLOPs",
        "offline_diagnostic_entropic_evaluations": len(dev["x"]) + calibration_pairs + len(sequence_scores),
        "wall_ns": time.perf_counter_ns() - started,
        "raw_output_labeling": "autoregressive captions; sigmoid image pixels quantized to 8-bit before RewardA",
        "claims": {"test_or_retention_used": False, "conditional_calibration": False,
                   "adaptive_policy_coverage": False, "global_policy_optimality": False}}
    return bundle, evidence

"""Frozen confirmation of content tracking and the full A/B/C/D experiment."""

import json
from pathlib import Path
import time

import numpy as np
from scipy.special import xlogy

from .cell import Cell
from .data import generate_sequences, generate_episode_tapes, EpisodeOwner, TRAIN_INTERVALS, OOD_INTERVALS
from .estimators import restore_model, posterior_ce
from .fit import array_hash, atomic_json
from .task_value import ExactBeliefDP, choose_values


def content_metrics(probabilities, data):
    bit = probabilities[..., 1::2].sum(axis=-1)
    target = data["labels"]
    joint_ce = posterior_ce(probabilities, data["teacher"])
    entropy = -float(np.mean(np.sum(xlogy(data["teacher"], data["teacher"]), axis=-1)))
    return {"joint_posterior_ce": joint_ce, "joint_posterior_kl": joint_ce - entropy,
            "bit_accuracy": float(np.mean((bit >= .5) == target)),
            "bit_brier": float(np.mean((bit - target) ** 2)),
            "mass_error": float(np.max(np.abs(probabilities.sum(axis=-1) - 1.)))}


def generic_hmm(cell, inputs):
    """Independent loop over Q/E arrays; it does not call HXFilter.step/forward."""
    from scipy.linalg import expm
    matrices = {float(dt): expm(cell.Q * float(dt)) for dt in np.unique(inputs[..., 8])}
    result = np.empty((*inputs.shape[:2], 20))
    for row, sequence in enumerate(inputs):
        posterior = cell.prior.copy()
        for t, x in enumerate(sequence):
            if x[9] > .5:
                posterior = posterior @ cell.R
            posterior = posterior @ matrices[float(x[8])]
            if x[7] > .5:
                posterior *= cell.E[:, np.argmax(x[:7])]
                posterior /= posterior.sum()
            result[row, t] = posterior
    return result


def execute_arm(payload, fitted_cell, world, tapes, control):
    if control not in ("fixed_read", "finite_horizon_value"):
        raise ValueError("Unknown controller: " + str(control))
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    model = restore_model(payload)
    planner = ExactBeliefDP(fitted_cell)
    setup_cpu = time.process_time() - cpu_start
    component_cpu = dict(controller=0., estimator=0., owner=0.)
    records = []
    max_margin_error = 0.
    for index, tape in enumerate(tapes):
        op = time.process_time()
        owner = EpisodeOwner(world, tape)
        component_cpu["owner"] += time.process_time() - op
        op = time.process_time()
        belief = model.start(fitted_cell.prior)
        component_cpu["estimator"] += time.process_time() - op
        actions, channels = [], []
        while True:
            op = time.process_time()
            schedule, budget = owner.remaining_schedule, owner.remaining_reads
            if control == "fixed_read":
                action = "READ" if budget and schedule else "STOP" + str(int((belief @ fitted_cell.reward[:, 1]) > (belief @ fitted_cell.reward[:, 0])))
                diagnostic = None
            else:
                diagnostic = planner.channels(belief, schedule, budget)
                action = diagnostic["action"]
            component_cpu["controller"] += time.process_time() - op
            actions.append(action)
            if diagnostic is not None:
                channels.append({k: diagnostic[k] for k in ("A", "B", "advantage", "stop", "reset_strictly_optimal", "action")})
            op = time.process_time()
            if action.startswith("STOP"):
                record = owner.finish(int(action[-1]))
                component_cpu["owner"] += time.process_time() - op
                break
            observation = owner.advance(action)
            component_cpu["owner"] += time.process_time() - op
            op = time.process_time()
            belief = model.step(observation["input"])
            component_cpu["estimator"] += time.process_time() - op
            max_margin_error = max(max_margin_error, float(abs(belief.sum() - 1.)))
        record.update(episode=index, actions=actions, channels=channels,
                      final_estimated_bit_probability=float(belief[1::2].sum()))
        records.append(record)
    elapsed = time.process_time() - cpu_start
    return {"control": control, "estimator_kind": payload["kind"],
            "controller_identity": planner.model_identity,
            "mean_utility": float(np.mean([r["utility"] for r in records])),
            "accuracy": float(np.mean([r["correct"] for r in records])),
            "mean_read_count": float(np.mean([r["counts"]["READ"] for r in records])),
            "mean_reset_count": float(np.mean([r["counts"]["RESET"] for r in records])),
            "mean_elapsed": float(np.mean([r["elapsed"] for r in records])),
            "online_cpu_per_episode": elapsed / len(tapes),
            "online_cpu_seconds": elapsed, "online_wall_seconds": time.perf_counter() - wall_start,
            "setup_cpu_seconds": setup_cpu, "component_cpu_seconds": component_cpu,
            "planner_cache": planner.cache_info(), "probability_mass_error": max_margin_error,
            "episodes": records}


def evaluate_seed(seed, output, selected_kind, frozen_hash):
    path = Path(output) / str(seed)
    fits = {kind: json.loads((path / (kind + ".json")).read_text())
            for kind in ("hx_distribution", "gru", "continuous_diagonal_ssm")}
    manifests = json.loads((path / "data_manifest.json").read_text())
    jobs = json.loads((path / "job_costs.json").read_text())
    models = {kind: data["selected_model"] for kind, data in fits.items()}
    fitted_cell = restore_model(models["hx_distribution"]).build_cell()
    world = Cell()
    # Full process CPU includes imports, construction, optimizer, selection and export.
    fit_cost = {kind: jobs[kind]["full_process_cpu_seconds"] for kind in fits}
    common_data = jobs["prepare"]["full_process_cpu_seconds"]
    rows = []
    for domain, intervals, sequence_offset, episode_offset in (
            ("iid", TRAIN_INTERVALS, 7000000, 9000000),
            ("ood", OOD_INTERVALS, 8000000, 10000000)):
        domain_start = time.process_time()
        data = generate_sequences(world, seed + sequence_offset, 192, intervals=intervals)
        tapes = generate_episode_tapes(seed + episode_offset, 128, intervals=intervals)
        confirmation_preparation = time.process_time() - domain_start
        content = {}
        fitted_predictions = None
        for kind, payload in models.items():
            op = time.process_time()
            predicted = restore_model(payload).forward(data["inputs"])
            content[kind] = content_metrics(predicted, data)
            content[kind]["inference_cpu_seconds"] = time.process_time() - op
            if kind == "hx_distribution":
                fitted_predictions = predicted
        op = time.process_time()
        hmm = generic_hmm(fitted_cell, data["inputs"])
        hmm_cpu = time.process_time() - op
        content["generic_fitted_hmm"] = content_metrics(hmm, data)
        content["generic_fitted_hmm"].update(inference_cpu_seconds=hmm_cpu,
                                            max_abs_difference_from_hx=float(np.max(np.abs(hmm - fitted_predictions))))
        content["privileged_true_model_bayes"] = content_metrics(data["teacher"], data)
        arms = {}
        assignments = {"A": (selected_kind, "fixed_read"), "B": (selected_kind, "finite_horizon_value"),
                       "C": ("hx_distribution", "fixed_read"), "D": ("hx_distribution", "finite_horizon_value")}
        # Seed-dependent fixed order prevents one arm always receiving first-run overhead.
        order = list(assignments)
        np.random.default_rng(seed + (1 if domain == "ood" else 0)).shuffle(order)
        for arm in order:
            kind, control = assignments[arm]
            result = execute_arm(models[kind], fitted_cell, world, tapes, control)
            direct_training = fit_cost[kind]
            if kind == "hx_distribution":
                method_training = fit_cost["hx_distribution"]
            else:
                method_training = sum(fit_cost.values())
            # Report preparation separately; identical common work is charged to each method.
            result.update(direct_training_cpu_seconds=direct_training,
                          common_model_calibration_cpu_seconds=fit_cost["hx_distribution"],
                          full_method_training_cpu_seconds=method_training,
                          common_data_cpu_seconds=common_data,
                          direct_cpu_per_episode=result["online_cpu_per_episode"] + (direct_training + common_data) / 1000.,
                          full_cpu_per_episode=result["online_cpu_per_episode"] + (method_training + common_data) / 1000.,
                          confirmation_preparation_cpu_seconds=confirmation_preparation)
            arms[arm] = result
        if len({v["controller_identity"] for v in arms.values()}) != 1:
            raise AssertionError("The four arms did not share exactly one fitted controller model")
        row = {"schema": "hcsn-r13-confirmation-v1", "seed": seed, "domain": domain,
               "freeze_hash": frozen_hash, "selected_ordinary_kind": selected_kind,
               "confirmation_data_hash": array_hash(data), "sequence_seed": seed + sequence_offset,
               "episode_seed": seed + episode_offset, "episode_count": len(tapes),
               "confirmation_preparation_cpu_seconds": confirmation_preparation,
               "arm_order": order, "content": content, "arms": arms,
               "scope": "Actual rollout utility. Shared planner forecasts Bayes successors; ordinary deployed updates retain their own recurrent state."}
        atomic_json(path / ("confirmation_" + domain + ".json"), row)
        rows.append(row)
    return rows

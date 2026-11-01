"""Fixed CPU budgets, exact deployed-policy targets, and validation-only choice."""

import copy
import json
from pathlib import Path
import time

import numpy as np
from scipy.linalg import expm
from scipy.special import expit

from ..unified_cell_r12_20261031.fit import atomic_json
from ..unified_cell_r12_20261031.task_value import ExactBeliefDP
from .execution import array_hash, collect_targets, execute, generate_data, make_tapes
from .models import GenericHMM, HXEstimator, ORDINARY_KINDS, RecurrentEstimator, restore, task_loss
from .task import TaskModel


def optimize(model, data, deadline, rng, alpha=None, legal=None, ce_weight=1., q_weight=0., learning_rate=.01):
    """Full BPTT/forward derivatives; each call starts a declared Adam stage."""
    moment = {k: np.zeros_like(v) for k, v in model.params.items()}
    variance = {k: np.zeros_like(v) for k, v in model.params.items()}
    history, updates, max_step = [], 0, 0.
    while time.process_time() < deadline:
        started = time.process_time()
        indices = rng.integers(len(data["inputs"]), size=min(32, len(data["inputs"])))
        args = (None, None) if alpha is None else (alpha[indices], legal[indices])
        loss, gradients = model.loss_grad(data["inputs"][indices], data["teacher"][indices],
                                          *args, ce_weight=ce_weight, q_weight=q_weight)
        if not np.isfinite(loss) or not all(np.isfinite(g).all() for g in gradients.values()):
            raise FloatingPointError("Nonfinite training objective or derivative")
        norm = np.sqrt(sum(np.sum(g * g) for g in gradients.values()))
        scale = min(1., 5. / max(norm, 1e-300))
        updates += 1
        for key, parameter in model.params.items():
            gradient = gradients[key] * scale
            moment[key] = .9 * moment[key] + .1 * gradient
            variance[key] = .999 * variance[key] + .001 * gradient * gradient
            parameter -= learning_rate * (moment[key] / (1 - .9 ** updates)) / (np.sqrt(variance[key] / (1 - .999 ** updates)) + 1e-8)
        if "emission_logits" in model.params:
            model.params["emission_logits"] -= model.params["emission_logits"].mean(axis=1, keepdims=True)
        max_step = max(max_step, time.process_time() - started)
        if updates == 1 or updates % 25 == 0:
            history.append(dict(update=updates, loss=loss, gradient_norm=float(norm)))
    return dict(updates=updates, last_loss=loss if updates else None, max_step_cpu_seconds=max_step, history=history)


def matched_gate(model, task, anchor=.45):
    """Initialize a logistic time gate to the same first-hit value AND slope.

    This is an ordinary sigmoid gate with a disclosed local match. It does not
    reproduce the joint distribution, renewal law or all temporal derivatives.
    """
    cell = task.cell
    killed = cell.survivor_generator()
    survival = cell.prior @ expm(killed * anchor)
    probability = 1 - float(survival.sum())
    density = float(survival @ cell.event_rate)
    slope = density / (probability * (1 - probability))
    if not 0 < probability < 1 or not np.isfinite(slope) or slope <= 0:
        raise ValueError("No valid local first-hit sigmoid match")
    model.gate_slope = slope
    model.params["Wg"][:] = 0.
    model.params["Wg"][9, :] = 1.
    model.params["bg"][:] = np.log(probability / (1 - probability)) / slope - anchor
    actual = float(expit(slope * (anchor + model.params["bg"][0])))
    return dict(anchor=anchor, first_hit_probability=probability, first_hit_density=density,
                sigmoid_slope=slope, initial_value_error=abs(actual - probability),
                initial_derivative_error=abs(slope * actual * (1 - actual) - density))


def fit(seed, output, protocol):
    path = Path(output) / str(seed)
    path.mkdir(parents=True, exist_ok=True)
    started, wall = time.process_time(), time.perf_counter()
    truth = TaskModel()
    prep_start = time.process_time()
    train = generate_data(truth, seed + 1000000, protocol["train_sequences"])
    validation = generate_data(truth, seed + 2000000, protocol["validation_sequences"])
    tapes = make_tapes(seed + 3000000, protocol["selection_episodes"])
    subset = np.random.default_rng(seed + 4000000).permutation(len(train["inputs"]))[:protocol["q_sequences"]]
    qdata = {k: v[subset] for k, v in train.items()}
    np.savez_compressed(path / "common_data.npz", **{"train_" + k: v for k, v in train.items()},
                        **{"validation_" + k: v for k, v in validation.items()}, q_indices=subset,
                        **{"selection_" + k: v for k, v in tapes.items()})
    preparation_cpu = time.process_time() - prep_start
    common_start = time.process_time()
    common = HXEstimator(seed)
    common_training = optimize(common, train, common_start + protocol["common_calibration_cpu_seconds"],
                               np.random.default_rng(seed + 5000000), learning_rate=.025)
    common_export = common.export()
    common = restore(common_export)
    common_task = common.build_cell()
    planner = ExactBeliefDP(common_task, reset_cost=common_task.reset_cost, latency_price=common_task.latency_price)
    common_cpu = time.process_time() - common_start
    atomic_json(path / "common_model.json", dict(model=common_export, training=common_training,
                                                task_identity=common_task.identity, planner_identity=planner.model_identity,
                                                cpu_seconds=common_cpu))
    results = {}
    for kind in ("hx_distribution", *ORDINARY_KINDS):
        candidate_start = time.process_time()
        model = restore(common_export) if kind == "hx_distribution" else RecurrentEstimator(kind, seed)
        gate = matched_gate(model, common_task) if kind == "matched_slope" else None
        warm = optimize(model, train, candidate_start + protocol["warmup_cpu_seconds"],
                        np.random.default_rng(seed + 6000000), learning_rate=.02 if kind == "hx_distribution" else .01)
        warm_cpu = time.process_time() - candidate_start
        warm_export = model.export()
        snapshot = restore(warm_export)
        target_planner = ExactBeliefDP(common_task, reset_cost=common_task.reset_cost,
                                      latency_price=common_task.latency_price)
        targets = collect_targets(truth, snapshot, target_planner, qdata, protocol["q_temperature"])
        # All methods pay for their own exact policy trees inside the same CPU
        # allowance. The snapshot and target versions remain in the evidence.
        target_hash = array_hash({"alpha": targets["alpha"], "legal": targets["legal"], "weights": targets["weights"]})
        np.savez_compressed(path / (kind + "_targets.npz"), alpha=targets["alpha"], legal=targets["legal"], weights=targets["weights"])
        qfit = optimize(model, qdata, candidate_start + protocol["candidate_cpu_seconds"],
                        np.random.default_rng(seed + 7000000), targets["alpha"], targets["weights"],
                        protocol["ce_weight"], protocol["q_weight"], .01)
        if not qfit["updates"]:
            raise RuntimeError("Candidate exhausted its budget before any Q-pi update")
        final_export = model.export()
        candidate_cpu = time.process_time() - candidate_start
        ce_start = time.process_time()
        ce_model = restore(warm_export)
        ce_training = optimize(ce_model, qdata, ce_start + max(0., protocol["candidate_cpu_seconds"] - warm_cpu),
                               np.random.default_rng(seed + 7000000), learning_rate=.01)
        ce_export = ce_model.export()
        ce_extra_cpu = time.process_time() - ce_start
        validated = restore(final_export)
        check_start = time.process_time()
        warm_pred = restore(warm_export).forward(qdata["inputs"])
        final_pred = validated.forward(qdata["inputs"])
        warm_loss = task_loss(warm_pred, qdata["teacher"], targets["alpha"], targets["weights"], 0., 1.)[0]
        final_loss = task_loss(final_pred, qdata["teacher"], targets["alpha"], targets["weights"], 0., 1.)[0]
        validation_ce = task_loss(validated.forward(validation["inputs"]), validation["teacher"])[0]
        validation_result = execute(truth, validated, planner, tapes, retain=True)
        warm_control_result = execute(truth, restore(warm_export), planner, tapes, retain=False)
        ce_control_result = execute(truth, restore(ce_export), planner, tapes, retain=False)
        validation_cpu = time.process_time() - check_start
        payload = dict(seed=seed, kind=kind, status="completed", common_planner_identity=planner.model_identity,
                       budget_cpu_seconds=protocol["candidate_cpu_seconds"], candidate_cpu_seconds=candidate_cpu,
                       overshoot_cpu_seconds=max(0., candidate_cpu - protocol["candidate_cpu_seconds"]),
                       warmup=warm, q_training=qfit, q_target_cpu_seconds=targets["cpu_seconds"],
                       q_target_count=targets["target_count"], q_target_hash=target_hash,
                       q_target_world_identity=truth.identity, q_target_actor=warm_export,
                       final_model=final_export, warm_model=warm_export,
                       ce_matched_model=ce_export, ce_matched_training=ce_training,
                       ce_matched_equivalent_cpu_seconds=warm_cpu + ce_extra_cpu,
                       ce_matched_additional_actual_cpu_seconds=ce_extra_cpu,
                       training_q_mse_before=warm_loss, training_q_mse_after=final_loss,
                       validation_posterior_ce=validation_ce, validation=validation_result,
                       warm_validation=warm_control_result, ce_matched_validation=ce_control_result,
                       validation_cpu_seconds=validation_cpu,
                       matched_gate_initialization=gate)
        atomic_json(path / (kind + ".json"), payload)
        results[kind] = payload
    reference_start = time.process_time()
    hmm = execute(truth, GenericHMM(common_task), planner, tapes, retain=True)
    reference_cpu = time.process_time() - reference_start
    atomic_json(path / "generic_hmm.json", hmm)
    candidates = {kind: results[kind]["validation"]["mean"]["utility"] for kind in ORDINARY_KINDS}
    candidates["generic_hmm"] = hmm["mean"]["utility"]
    # Deterministic tie order favors the ordinary matrix HMM, then the strongest
    # full joint recurrent candidate; no confirmation data have been generated.
    order = ("generic_hmm", "gru", "continuous_ssm", "dual_head", "matched_slope")
    selected = max(order, key=lambda kind: candidates[kind])
    ordinary_cpu = sum(results[k]["candidate_cpu_seconds"] + results[k]["validation_cpu_seconds"] for k in ORDINARY_KINDS) + reference_cpu
    summary = dict(schema="hcsn-r14-training-v1", seed=seed, status="completed", selected_ordinary=selected,
                   selection_scores=candidates, train_hash=array_hash(train), validation_hash=array_hash(validation),
                   q_data_hash=array_hash(qdata), selection_tape_hash=array_hash(tapes),
                   world_identity=truth.identity, common_task_identity=common_task.identity,
                   common_planner_identity=planner.model_identity,
                   preparation_cpu_seconds=preparation_cpu, common_calibration_cpu_seconds=common_cpu,
                   ordinary_candidate_and_selection_cpu_seconds=ordinary_cpu,
                   hx_candidate_and_validation_cpu_seconds=results["hx_distribution"]["candidate_cpu_seconds"] + results["hx_distribution"]["validation_cpu_seconds"],
                   ce_counterfactual_additional_actual_cpu_seconds=sum(v["ce_matched_additional_actual_cpu_seconds"] for v in results.values()),
                   total_process_cpu_seconds=time.process_time() - started,
                   wall_seconds=time.perf_counter() - wall,
                   q_mse={k: dict(before=v["training_q_mse_before"], after=v["training_q_mse_after"])
                          for k, v in results.items()})
    atomic_json(path / "TRAINING.json", summary)
    return summary

"""Matched nonlinear mask: ordinary BP, conditional solves plus BP, semantic start.

This is a bounded learning-curve study. Exhausting the budget is never labelled
convergence. Development selects among the same predeclared checkpoint epochs;
final data only evaluates the frozen selected state. Dense remains the backend.
"""

import copy
import time

import torch

from qualification.hcsn_confirmatory_v1.joint import (
    changes,
    restore,
    score,
    state,
    state_digest,
)
from qualification.hcsn_confirmatory_v1.joint_program import apply_program
from qualification.hcsn_confirmatory_v1.tasks import digest, generate

from .profiled import backward_step, forward_loss, parameter_mode, prepare
from .readout_run import plain


METHODS = ("joint_bp", "profile_bp", "program_profile_bp")


def fit_case(task, seed, cfg):
    c = cfg["profiled"]
    started, cpu_started = time.perf_counter(), time.process_time()
    train = generate(cfg["namespace"], seed, task, "train", c["train"], c["length"])
    dev = generate(cfg["namespace"], seed, task, "dev", c["dev"], c["length"])
    base, scaler, names = prepare(task, train, c["scale_floor"], c["ridge"])
    initial = state(base)
    baseline, _, _ = score(base, dev)
    common_seconds = time.perf_counter() - started
    result = {
        "task": task,
        "seed": seed,
        "train_sha256": digest(train),
        "dev_sha256": digest(dev),
        "base_state": initial,
        "base_state_sha256": state_digest(initial),
        "base_dev_mse": baseline,
        "feature_names": names,
        "scaler": plain(scaler),
        "common_seconds": common_seconds,
        "eligible_union_parameters": 51,
        "fixed_normalization": "train-only initial encoder; unchanged after every outer edit",
        "full_network_optimality_claim": False,
        "methods": {},
    }
    rotation = (c["tasks"].index(task) + cfg["seeds"].index(seed)) % len(METHODS)
    order = METHODS[rotation:] + METHODS[:rotation]
    result["order"] = list(order)
    for position, method in enumerate(order):
        begin, cpu_begin = time.perf_counter(), time.process_time()
        model = copy.deepcopy(base)
        profile = method != "joint_bp"
        eligible = parameter_mode(model, method)
        total = {
            "feature_seconds": 0.0,
            "conditional_solve_seconds": 0.0,
            "conditional_solves": 0,
            "forward_rows": 0,
            "backward_seconds": 0.0,
            "backward_rows": 0,
            "backward_passes": 0,
            "development_seconds": 0.0,
            "development_queries": 0,
            "optimizer_step_seconds": 0.0,
            "program_application_seconds": 0.0,
        }
        trace, completed, stop = [], 0, "budget_exhausted"
        selected, best = initial, baseline
        try:
            if method == "program_profile_bp":
                t0 = time.perf_counter()
                apply_program(model, task)
                total["program_application_seconds"] = time.perf_counter() - t0
            optimizer = torch.optim.Adam(
                [p for p in model.parameters() if p.requires_grad],
                lr=c["learning_rate"],
            )

            def checkpoint(step, allow_selection=True):
                nonlocal selected, best
                value, gradient, expense = backward_step(
                    model, train, c["ridge"], profile
                )
                for key, amount in expense.items():
                    total[key] += amount
                validation = None
                if allow_selection:
                    t0 = time.perf_counter()
                    validation, _, _ = score(model, dev)
                    total["development_seconds"] += time.perf_counter() - t0
                    total["development_queries"] += 1
                    if validation < best:
                        selected, best = state(model), validation
                trace.append(
                    {
                        "optimizer_steps": step,
                        "training_objective": value,
                        "training_gradient_inf": gradient,
                        "dev_mse": validation,
                        "selection_checkpoint": allow_selection,
                        "best_dev_mse": best,
                        "elapsed_seconds": time.perf_counter() - begin,
                        "state_sha256": state_digest(state(model)),
                    }
                )
                return gradient

            gradient = checkpoint(0)
            for step in range(1, c["max_steps"] + 1):
                _, _, expense = backward_step(model, train, c["ridge"], profile)
                for key, amount in expense.items():
                    total[key] += amount
                t0 = time.perf_counter()
                optimizer.step()
                total["optimizer_step_seconds"] += time.perf_counter() - t0
                completed = step
                expired = time.perf_counter() - begin >= c["arm_wall_seconds"]
                if step in c["checkpoints"] or step == c["max_steps"] or expired:
                    gradient = checkpoint(step, step in c["checkpoints"])
                    if gradient <= c["gradient_tolerance"]:
                        stop = "stationary_training_point"
                        break
                if expired:
                    stop = "wall_budget_exhausted"
                    break
            candidate = state(model)
            restore(model, selected)
            selected_changes = changes(initial, model)
            arm = {
                "status": "selected" if selected_changes else "no_update",
                "candidate_state": candidate,
                "selected_state": selected,
                "selected_state_sha256": state_digest(selected),
                "selected_changes": selected_changes,
                "selected_dev_mse": best,
                "training_stop": stop,
                "stationarity_is_global_optimality": False,
                "trace": trace,
            }
        except (ValueError, FloatingPointError, RuntimeError) as error:
            arm = {"status": "failed", "error": repr(error), "trace": trace}
        total.update(
            arm_seconds=time.perf_counter() - begin,
            arm_cpu_seconds=time.process_time() - cpu_begin,
            optimizer_steps_completed=completed,
            training_label_rows_read=total["forward_rows"],
            standalone_seconds_lower_bound=common_seconds + time.perf_counter() - begin,
            semantic_authoring_seconds=None if method == "program_profile_bp" else 0.0,
            semantic_authoring_tokens=None if method == "program_profile_bp" else 0,
            semantic_authoring_api_cost=None if method == "program_profile_bp" else 0.0,
        )
        result["methods"][method] = {
            **arm,
            "cost": total,
            "position": position,
            "gradient_parameter_names": list(eligible),
            "directly_solved_parameter_names": ["readout.weight", "readout.bias"]
            if profile
            else [],
            "encoder_operator_rebuilt_after_edit": True,
        }
    result["case_seconds"] = time.perf_counter() - started
    result["case_cpu_seconds"] = time.process_time() - cpu_started
    return result


def final_case(record, task, seed, cfg):
    from qualification.hcsn_confirmatory_v1.joint import build

    c = cfg["profiled"]
    results = []
    for split in ("final_iid", "final_clock"):
        data = generate(cfg["namespace"], seed, task, split, c["final"], c["length"])
        digest_value = digest(data)
        for method in ("conditional_incumbent",) + METHODS:
            arm = (
                record["methods"][method]
                if method in METHODS
                else {"status": "reference", "selected_state": record["base_state"]}
            )
            if arm["status"] == "failed":
                results.append(
                    {
                        "task": task,
                        "seed": seed,
                        "split": split,
                        "method": method,
                        "status": "failed",
                        "error": arm["error"],
                    }
                )
                continue
            started = time.perf_counter()
            model = build(task)
            restore(model, arm["selected_state"])
            mse, prediction, losses = score(model, data)
            results.append(
                {
                    "task": task,
                    "seed": seed,
                    "split": split,
                    "method": method,
                    "status": arm["status"],
                    "mse": mse,
                    "prediction": prediction,
                    "target": data["y"][:, 0].tolist(),
                    "sample_squared_errors": losses,
                    "ids": data["ids"].tolist(),
                    "data_sha256": digest_value,
                    "evaluation_seconds": time.perf_counter() - started,
                    "selected_state_sha256": state_digest(arm["selected_state"]),
                }
            )
    return results

"""Five head-only adaptation arms with sealed, separately executed final tests.

All methods start from the same selected, independently trained checkpoint.
They receive identical frozen final features and target conventions. Supervised
ridge and its development-selected blends are explicitly not strict WSP.
This experiment tests readout adaptation, not replacement of representation
learning or end-to-end pretraining by a weight program.
"""

import argparse
from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
import traceback

import torch
from torch import nn

from .cost import CostMeter
from .data import make_data
from .editing import propose, tensor_digest
from .model import ModelConfig, SmallHCSN
from . import train as training


METHODS = ("KEEP", "BP", "ANALYTIC", "STRICT_WSP", "HYBRID")
HEAD_NAMES = ("readout.weight", "readout.bias")
ALGORITHMS = {
    "objective": "mean over examples AND classes of squared signed-onehot error + ridge * sum(weight**2)",
    "targets": "2 * one_hot(label, 2) - 1",
    "bias_penalty": 0.0,
    "working_dtype": "float64; each evaluated/saved candidate is cast to parent parameter dtype",
    "BP": {"optimizer": "L-BFGS", "lr": 1.0, "history_size": 10,
           "max_iter": 1, "max_eval": 1, "line_search_fn": None,
           "tolerance_grad": 1e-7, "tolerance_change": 0.0,
           "early_stop": "pre-update gradient infinity norm <= 1e-7; L-BFGS returns without an update at that point",
           "candidate_steps": [24, 48, 72, 96]},
    "ANALYTIC": {"solver": "full augmented normal matrix, Cholesky solve",
                 "condition_number": "2-norm of regularized normal matrix; full SVD charged"},
    "HYBRID": {"solver": "independent same ridge solve followed by supervised development selection",
               "parent_to_ridge_blends": [.125, .25, .5, 1.0]},
    "STRICT_WSP": {"capability_rule": None, "unidentified_construction": "ABSTAIN"},
    "max_nonparent_development_candidates": 4,
    "selection": "lowest new-development unregularized signed-target MSE among old-retention-eligible candidates and KEEP",
    "minimum_selection_improvement": 1e-12,
    "budget": "per-arm CPU for construction, optimizer setup, all attempted updates and cached-development checks; atomic overrun is reported",
    "shared_cost": "checkpoint loading, data generation, complete frozen feature extraction and cache IO are charged equally to all five arms",
    "old_retention": "aggregate old-development accuracy and Brier gates; worst-source accuracy is reported, not guaranteed",
    "data": {"train": "adapt_train", "new_dev": "adapt_dev", "old_dev": "dev",
             "new_test": "adapt_test", "old_test": "test"},
}


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def adaptation_hashes(p):
    own = {name: training.digest(Path(__file__).with_name(name))
           for name in ("adaptation_suite.py", "editing.py")}
    return {"adaptation": own, "training_closure": p["source_hashes"]}


def freeze_adaptation(p, path):
    training.validate_protocol(p)
    editing = p["editing"]
    if (tuple(editing["methods"]) != METHODS or tuple(editing["eligible_names"]) != HEAD_NAMES
            or editing["strict_wsp_rule"] is not None or editing["bp_steps"] != 96
            or not 0 < editing["ridge"] < 1 or not 0 < editing["cpu_seconds"] <= 60):
        raise ValueError("this implementation requires the declared five-arm, 96-step head-only protocol")
    ap = {"schema": "hcsn-head-adaptation-protocol-v1",
          "training_protocol_sha256": training.protocol_digest(p),
          "source_hashes": adaptation_hashes(p), "editing": deepcopy(editing),
          "algorithms": deepcopy(ALGORITHMS), "claim_scope": __doc__.strip()}
    _write_new(path, ap)
    return ap


def validate_adaptation_protocol(p, ap):
    training.validate_protocol(p)
    if (ap["training_protocol_sha256"] != training.protocol_digest(p)
            or ap["source_hashes"] != adaptation_hashes(p)
            or ap["editing"] != p["editing"] or ap["algorithms"] != ALGORITHMS):
        raise ValueError("adaptation code, objective, selection rule, or parent protocol changed after freeze")


@dataclass(frozen=True)
class FeatureBundle:
    features: torch.Tensor
    labels: torch.Tensor
    sources: torch.Tensor
    dataset_sha256: str

    def validate(self, dimensions):
        n = len(self.labels)
        if (self.features.shape != (n, dimensions) or n < 1
                or self.labels.shape != (n,) or self.sources.shape != (n,)
                or self.labels.dtype != torch.int64
                or not bool(((self.labels == 0) | (self.labels == 1)).all())
                or not bool(torch.isfinite(self.features).all())
                or self.features.device.type != "cpu"):
            raise ValueError("finite CPU final features with the common binary labels required")

    def targets(self):
        return 2 * nn.functional.one_hot(self.labels, 2).double() - 1

    def augmented(self):
        z = self.features.double()
        return torch.cat((z, torch.ones(len(z), 1, dtype=torch.float64)), 1)

    def serializable(self):
        return {"features": self.features, "labels": self.labels,
                "sources": self.sources, "dataset_sha256": self.dataset_sha256}


def head_theta(state):
    return torch.cat((state["readout.weight"].detach().double().T,
                      state["readout.bias"].detach().double()[None]), 0)


def ridge_objective(theta, augmented, targets, ridge):
    return (augmented @ theta - targets).square().mean() + ridge * theta[:-1].square().sum()


def solve_ridge(augmented, targets, ridge, *, counters=None):
    """Exact conditional optimum for the documented MSE convention.

    H = X^T X / (n * classes) + lambda diag(1,...,1,0).
    H Theta = X^T Y / (n * classes); the appended bias is unregularized.
    """
    if (augmented.ndim != 2 or targets.ndim != 2 or len(augmented) != len(targets)
            or len(augmented) < 1 or targets.shape[1] != 2 or not ridge > 0
            or augmented.dtype != torch.float64 or targets.dtype != torch.float64):
        raise ValueError("finite double matrices, binary targets and positive ridge required")
    if not bool(torch.isfinite(augmented).all() and torch.isfinite(targets).all()):
        raise ValueError("nonfinite ridge inputs")
    scale = targets.numel()
    penalty = torch.ones(augmented.shape[1], dtype=torch.float64)
    penalty[-1] = 0
    normal = augmented.T @ augmented / scale + ridge * torch.diag(penalty)
    rhs = augmented.T @ targets / scale
    if counters is not None:
        counters["condition_svd_calls"] += 1
    condition = float(torch.linalg.cond(normal))
    if counters is not None:
        counters["cholesky_factorizations"] += 1
    factor, info = torch.linalg.cholesky_ex(normal, check_errors=False)
    if int(info) != 0 or not math.isfinite(condition):
        raise FloatingPointError("regularized normal matrix is not a finite positive definite system")
    if counters is not None:
        counters["linear_system_solves"] += 1
    result = torch.cholesky_solve(rhs, factor)
    residual = float((normal @ result - rhs).abs().max())
    if not bool(torch.isfinite(result).all()) or not math.isfinite(residual):
        raise FloatingPointError("nonfinite conditional solve")
    return result, {"matrix_shape": list(normal.shape), "normal_condition_2": condition,
                    "normal_residual_linf": residual, "condition_svd_calls": 1,
                    "cholesky_factorizations": 1, "linear_system_solves": 1,
                    "normalization_denominator": scale, "bias_regularized": False}


def _cast(theta, dtype):
    return theta.detach().to(dtype).double()


def _metrics(theta, bundle, dtype):
    with torch.no_grad():
        logits = nn.functional.linear(bundle.features.to(dtype), theta[:-1].T.to(dtype),
                                      theta[-1].to(dtype)).double()
        if not bool(torch.isfinite(logits).all()):
            raise FloatingPointError("nonfinite native-dtype head candidate")
        probabilities = logits.softmax(-1)
        correct = logits.argmax(-1) == bundle.labels
        per_source = {str(s): float(correct[bundle.sources == s].double().mean())
                      for s in bundle.sources.unique().tolist()}
        target = nn.functional.one_hot(bundle.labels, 2).double()
        return {"mse": float((logits - bundle.targets()).square().mean()),
                "accuracy": float(correct.double().mean()),
                "brier": float((probabilities - target).square().sum(-1).mean()),
                "cross_entropy": float(nn.functional.cross_entropy(logits, bundle.labels)),
                "source_accuracy": per_source, "worst_source_accuracy": min(per_source.values()),
                "examples": len(bundle.labels), "sources": len(per_source)}


def run_head_method(method, model, bundles, editing):
    """Pure candidate construction/selection; final tests and IO are external.

    The loss uses frozen features. Its backward calls train only the existing
    readout. All non-head parameters are protected by byte comparison when the
    selected checkpoint is installed and reloaded.
    """
    if method not in METHODS or set(bundles) != {"train", "new_dev", "old_dev"}:
        raise ValueError("declared method and all three common data bundles required")
    started, cpu_started = time.perf_counter(), time.process_time()
    phase_costs = {}

    def timed(name, operation):
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            return operation()
        finally:
            row = phase_costs.setdefault(name, {"calls": 0, "cpu_seconds": 0.0, "wall_seconds": 0.0})
            row["calls"] += 1
            row["cpu_seconds"] += time.process_time() - cpu
            row["wall_seconds"] += time.perf_counter() - wall

    state = model.state_dict()
    dtype = state["readout.weight"].dtype
    parent = head_theta(state)
    for bundle in bundles.values():
        bundle.validate(parent.shape[0] - 1)
    matrix, target = bundles["train"].augmented(), bundles["train"].targets()
    ridge = float(editing["ridge"])
    parent_old = timed("common_cached_baseline_evaluation", lambda: _metrics(parent, bundles["old_dev"], dtype))
    parent_new = timed("common_cached_baseline_evaluation", lambda: _metrics(parent, bundles["new_dev"], dtype))
    selected, selected_old, selected_new, selected_name = parent.clone(), parent_old, parent_new, "KEEP"
    counters = {"optimizer_steps_attempted": 0, "optimizer_steps_completed": 0,
                "closure_calls": 0, "backward_calls": 0, "development_candidates": 0,
                "condition_svd_calls": 0, "cholesky_factorizations": 0, "linear_system_solves": 0,
                "conditional_solve_attempts": 0, "head_development_forward_calls": 2,
                "regularized_objective_evaluations": 0}
    observations, solver, error, status = [], {}, None, "completed"
    last = parent.clone()

    def used_cpu():
        return time.process_time() - cpu_started

    def _observe(theta, name):
        nonlocal selected, selected_old, selected_new, selected_name
        if counters["development_candidates"] >= ALGORITHMS["max_nonparent_development_candidates"]:
            raise RuntimeError("development query budget exhausted")
        counters["development_candidates"] += 1
        candidate = _cast(theta, dtype)
        if not bool(torch.isfinite(candidate).all()):
            observations.append({"name": name, "status": "failed", "error": "nonfinite_candidate"})
            raise FloatingPointError("nonfinite candidate after native parameter cast")
        counters["head_development_forward_calls"] += 2
        old, new = _metrics(candidate, bundles["old_dev"], dtype), _metrics(candidate, bundles["new_dev"], dtype)
        eligible = (old["accuracy"] >= parent_old["accuracy"] - editing["max_dev_old_accuracy_loss"]
                    and old["brier"] <= parent_old["brier"] + editing["max_dev_old_brier_increase"])
        improved = new["mse"] < selected_new["mse"] - ALGORITHMS["minimum_selection_improvement"]
        chosen = eligible and improved
        counters["regularized_objective_evaluations"] += 1
        observations.append({"name": name, "status": "evaluated", "old_development": old,
            "new_development": new, "retention_eligible": eligible, "selected_at_this_stage": chosen,
            "train_regularized_objective": float(ridge_objective(candidate, matrix, target, ridge)),
            "delta_l2": float(torch.linalg.vector_norm(candidate - parent)), "cpu_seconds": used_cpu()})
        if chosen:
            selected, selected_old, selected_new, selected_name = candidate.clone(), old, new, name

    def observe(theta, name):
        return timed("cached_candidate_development_selection", lambda: _observe(theta, name))

    try:
        if method == "STRICT_WSP":
            candidate, receipt = timed("strict_program_execution", lambda: propose(model, rule=None, editable_names=HEAD_NAMES))
            if receipt["status"] != "ABSTAIN" or tensor_digest(candidate) != tensor_digest(state):
                raise RuntimeError("unsupported capability rule must abstain without consulting task labels")
            solver["weight_program"] = receipt
            status = "ABSTAIN"
        elif method in ("ANALYTIC", "HYBRID"):
            # Each arm independently builds/solves its own normal system.
            counters["conditional_solve_attempts"] += 1
            solution, diagnostics = timed("conditional_normal_matrix_and_solve",
                lambda: solve_ridge(matrix, target, ridge, counters=counters))
            solver.update(diagnostics)
            last = solution.detach().clone()
            alphas = [1.0] if method == "ANALYTIC" else ALGORITHMS["HYBRID"]["parent_to_ridge_blends"]
            for alpha in alphas:
                # One indivisible solve may overrun. Its first evaluation remains
                # charged; additional hybrid searches stop at the shared cap.
                if counters["development_candidates"] and used_cpu() >= editing["cpu_seconds"]:
                    break
                observe(parent + alpha * (solution - parent), "ridge" if method == "ANALYTIC" else f"blend_{alpha:g}")
        elif method == "BP":
            theta = nn.Parameter(parent.clone())
            optimizer = timed("BP_optimizer_setup", lambda: torch.optim.LBFGS(
                [theta], lr=1.0, max_iter=1, max_eval=1, history_size=10,
                line_search_fn=None, tolerance_grad=1e-7, tolerance_change=0.0))
            solver["optimizer"] = deepcopy(ALGORITHMS["BP"])
            solver["termination_reason"] = "step_budget"
            for step in range(1, editing["bp_steps"] + 1):
                if used_cpu() >= editing["cpu_seconds"]:
                    solver["termination_reason"] = "cpu_budget"
                    break
                def closure():
                    if counters["closure_calls"] >= editing["bp_steps"]:
                        raise RuntimeError("96 backward evaluations is a hard budget")
                    counters["closure_calls"] += 1
                    optimizer.zero_grad(set_to_none=True)
                    counters["regularized_objective_evaluations"] += 1
                    loss = ridge_objective(theta, matrix, target, ridge)
                    if not bool(torch.isfinite(loss)):
                        raise FloatingPointError("nonfinite L-BFGS objective")
                    counters["backward_calls"] += 1
                    loss.backward()
                    if not bool(torch.isfinite(theta.grad).all()):
                        raise FloatingPointError("nonfinite L-BFGS gradient")
                    return loss
                counters["optimizer_steps_attempted"] += 1
                timed("BP_forward_backward_updates", lambda: optimizer.step(closure))
                counters["optimizer_steps_completed"] += 1
                last = theta.detach().clone()
                gradient_linf = float(theta.grad.detach().abs().max())
                converged = gradient_linf <= ALGORITHMS["BP"]["tolerance_grad"]
                solver["last_closure_gradient_linf"] = gradient_linf
                if (step in ALGORITHMS["BP"]["candidate_steps"]
                        or converged or used_cpu() >= editing["cpu_seconds"] or step == editing["bp_steps"]):
                    observe(last, f"step_{step}")
                if converged:
                    solver["termination_reason"] = "gradient_converged"
                    break
            solver["optimizer_state"] = optimizer.state_dict()
        # KEEP intentionally has no proposal or nonparent development query.
    except (RuntimeError, ValueError, FloatingPointError) as exc:
        status, error = "failed", type(exc).__name__ + ": " + str(exc)
        observations.append({"status": "failed_attempt", "error": error, "traceback": traceback.format_exc(),
                             "cpu_seconds": used_cpu()})

    # Optimizer tensors go in the checkpoint, never the JSON report.
    optimizer_state = solver.pop("optimizer_state", None)
    elapsed_cpu = used_cpu()
    counters["regularized_objective_evaluations"] += 2
    report = {"method": method, "status": status, "error": error, "selected_candidate": selected_name,
              "adoption": "KEEP" if torch.equal(selected, parent) else "ADOPT",
              "editable_names": list(HEAD_NAMES), "working_dtype": "torch.float64",
              "eligible_scalar_count": parent.numel(), "frozen_feature_dimension": parent.shape[0] - 1,
              "adaptation_training_rows": len(bundles["train"].labels), "target_classes": 2,
              "checkpoint_parameter_dtype": str(dtype), "solver": solver, "counters": counters,
              "phase_costs_including_failures": phase_costs,
              "history": observations, "parent_old_development": parent_old, "parent_new_development": parent_new,
              "selected_old_development": selected_old, "selected_new_development": selected_new,
              "parent_train_objective": float(ridge_objective(parent, matrix, target, ridge)),
              "selected_train_objective": float(ridge_objective(selected, matrix, target, ridge)),
              "selected_delta_l2": float(torch.linalg.vector_norm(selected - parent)),
              "construction_selection_cpu_seconds": elapsed_cpu,
              "construction_selection_wall_seconds": time.perf_counter() - started,
              "cpu_budget": editing["cpu_seconds"], "cpu_budget_overrun": max(0., elapsed_cpu - editing["cpu_seconds"]),
              "program_discovery_cost": "not instrumented; total learning-time speedup is not established"}
    return selected, report, {"last_theta": last, "optimizer": optimizer_state}


def _install(parent_state, theta):
    candidate = {name: value.detach().clone() for name, value in parent_state.items()}
    candidate["readout.weight"] = theta[:-1].T.to(parent_state["readout.weight"])
    candidate["readout.bias"] = theta[-1].to(parent_state["readout.bias"])
    for name in parent_state:
        if name not in HEAD_NAMES and not torch.equal(candidate[name], parent_state[name]):
            raise RuntimeError("head-only adaptation altered a protected field")
    return candidate


def _fit_adaptation(p, checkpoint_path, output_dir, *, adaptation_protocol):
    """Fit all five methods; never constructs a final-test split."""
    meter = CostMeter()
    validate_adaptation_protocol(p, adaptation_protocol)
    torch.set_num_threads(1)
    output, checkpoint_path = Path(output_dir), Path(checkpoint_path)
    output.mkdir(parents=True, exist_ok=False)
    _write_new(output / "STARTED.json", {"adaptation_protocol_sha256": training.protocol_digest(adaptation_protocol),
                                        "checkpoint_path": str(checkpoint_path)})
    shared_meter = meter
    checkpoint_sha = training.digest(checkpoint_path)
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    parent_record_path = checkpoint_path.parent / "result.json"
    parent_record = json.loads(parent_record_path.read_text())
    if (checkpoint["protocol_sha256"] != training.protocol_digest(p)
            or checkpoint["source_hashes"] != p["source_hashes"]
            or checkpoint["arm"]["id"] != "qvi_full" or checkpoint["smoke"]
            or checkpoint["seed"] not in p["seeds"]
            or checkpoint["neurons"] not in p["independent_neurons"]
            or parent_record["status"] != "completed"
            or parent_record["checkpoint_sha256"] != checkpoint_sha
            or parent_record["selected_step"] != checkpoint["best_step"]
            or any(parent_record[key] != checkpoint[key] for key in
                   ("protocol_sha256", "source_hashes", "arm", "neurons", "seed", "smoke"))):
        raise ValueError("formal parent must be the sealed-protocol selected qvi_full checkpoint")
    expected_arm = next(arm for arm in p["arms"] if arm["id"] == "qvi_full")
    if (checkpoint["arm"] != expected_arm or
            ModelConfig(**checkpoint["config"]) != training.config_for(p, expected_arm, checkpoint["neurons"])):
        raise ValueError("parent configuration does not match its formal training slot")
    name = f'n{checkpoint["config"]["neurons"]}-qvi_full-s{checkpoint["seed"]}'
    if output.name != name:
        raise ValueError("adaptation attempt path must identify its exact independent trained parent")
    model = SmallHCSN(ModelConfig(**checkpoint["config"]))
    model.load_state_dict(checkpoint["selected_model"])
    model.eval()
    parent_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    bundles, extraction = {}, {}
    dtype = model.input_drive.weight.dtype
    for key, split in (("train", "adapt_train"), ("new_dev", "adapt_dev"), ("old_dev", "dev")):
        batch = make_data(split, per_source=p["data"]["train_per_source"] if key == "train" else p["data"]["dev_per_source"],
                          length=p["data"]["length"], dtype=dtype)
        metrics, _, features = training.evaluate(model, batch, include_features=True)
        bundles[key] = FeatureBundle(features, batch.y, batch.source, batch.digest())
        extraction[key] = {"dataset_sha256": batch.digest(), "metrics": metrics,
                           "feature_shape": list(features.shape), "source_ids": batch.source.unique().tolist(),
                           "full_model_forward_chunks": math.ceil(len(batch.y) / 16),
                           "complete_forward_event_rows": len(batch.x) * len(batch.y),
                           "feature_tensor_sha256": tensor_digest({"features": features})}
    torch.save({key: bundle.serializable() for key, bundle in bundles.items()}, output / "shared_features.pt")
    cache_sha = training.digest(output / "shared_features.pt")
    shared = shared_meter.snapshot()
    method_records, method_costs = {}, {}
    for method in METHODS:
        arm_meter = CostMeter()
        directory = output / method
        directory.mkdir()
        selected, report, solver_state = run_head_method(method, model, bundles, p["editing"])
        selected_state = _install(parent_state, selected)
        native = {"schema": "hcsn-head-adaptation-checkpoint-v1", "config": checkpoint["config"],
                  "selected_model": selected_state, "parent_model": parent_state,
                  "solver_state": solver_state, "method": method, "seed": checkpoint["seed"],
                  "parent_checkpoint_sha256": checkpoint_sha,
                  "training_protocol_sha256": training.protocol_digest(p),
                  "adaptation_protocol_sha256": training.protocol_digest(adaptation_protocol)}
        torch.save(native, directory / "checkpoint.pt")
        restored = torch.load(directory / "checkpoint.pt", map_location="cpu", weights_only=True)
        reloaded = SmallHCSN(ModelConfig(**restored["config"]))
        reloaded.load_state_dict(restored["selected_model"])
        reload_equal = tensor_digest(reloaded.state_dict()) == tensor_digest(selected_state)
        restored_theta = head_theta(reloaded.state_dict())
        for key in ("old_dev", "new_dev"):
            if _metrics(restored_theta, bundles[key], dtype) != report["selected_" + ("old" if key == "old_dev" else "new") + "_development"]:
                raise RuntimeError("saved selected checkpoint does not reproduce its cached-feature selection result")
        if not reload_equal:
            raise RuntimeError("saved full selected checkpoint changed during serialization")
        report.update(parent_checkpoint_sha256=checkpoint_sha, selected_tensor_sha256=tensor_digest(selected_state),
                      selected_checkpoint_sha256=training.digest(directory / "checkpoint.pt"),
                      checkpoint_reload={"complete_state_exact": True,
                          "native_readout_reproduces_selection": True,
                          "full_model_forward": "performed only by the separately sealed final-test stage"},
                      shared_cost_allocation_fraction=1 / len(METHODS),
                      own_cost_before_result_serialization=arm_meter.snapshot())
        _write_new(directory / "result.json", report)
        method_records[method] = {"result_sha256": training.digest(directory / "result.json"),
                                  "checkpoint_sha256": report["selected_checkpoint_sha256"]}
        complete = arm_meter.snapshot()
        complete["allocated_shared_cpu_seconds"] = shared["cpu_seconds"] / len(METHODS)
        complete["allocated_shared_wall_seconds"] = shared["wall_seconds"] / len(METHODS)
        complete["accounted_cpu_seconds"] = complete["cpu_seconds"] + complete["allocated_shared_cpu_seconds"]
        complete["accounted_wall_seconds"] = complete["wall_seconds"] + complete["allocated_shared_wall_seconds"]
        complete["standalone_repeated_feature_cpu_seconds"] = complete["cpu_seconds"] + shared["cpu_seconds"]
        complete["measurement_boundary"] = "includes arm setup, every failed attempt, selection, selected checkpoint write/reload, result write and hashes"
        method_costs[method] = complete
    if tensor_digest(model.state_dict()) != tensor_digest(parent_state):
        raise RuntimeError("adaptation mutated the common parent")
    result = {"schema": "hcsn-five-arm-adaptation-v1", "attempt": name, "seed": checkpoint["seed"],
              "neurons": model.config.neurons, "parent_checkpoint_sha256": checkpoint_sha,
              "parent_tensor_sha256": tensor_digest(parent_state),
              "parent_selected_step": checkpoint["best_step"],
              "parent_training_result_sha256": training.digest(parent_record_path),
              "inherited_parent_training_cost": parent_record["cost"],
              "inherited_parent_update_cpu_seconds": parent_record["training_cpu_seconds"],
              "adaptation_protocol_sha256": training.protocol_digest(adaptation_protocol),
              "training_protocol_sha256": training.protocol_digest(p),
              "shared_feature_cache_sha256": cache_sha, "shared_feature_extraction": extraction,
              "shared_cost": shared, "method_costs": method_costs, "methods": method_records,
              "parent_unchanged": True, "parent_checkpoint_load": "selected_model; not last_model or initial_model",
              "cost_before_summary_serialization": meter.snapshot(),
              "claim_scope": "same frozen representation and head domain; strict WSP abstains on unidentified capability"}
    _write_new(output / "ADAPTATION_RESULT.json", result)
    _write_new(output / "SEAL.json", {"adaptation_protocol_sha256": training.protocol_digest(adaptation_protocol),
        "attempt": name, "summary_sha256": training.digest(output / "ADAPTATION_RESULT.json"),
        "cache_sha256": cache_sha, "methods": method_records})
    return result


def fit_adaptation(p, checkpoint_path, output_dir, *, adaptation_protocol):
    """Create-only wrapper that leaves a costed record if preparation/IO fails."""
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError("formal adaptation attempts are immutable; no retry into an existing directory")
    meter = CostMeter()
    try:
        return _fit_adaptation(p, checkpoint_path, output, adaptation_protocol=adaptation_protocol)
    except Exception as exc:
        output.mkdir(parents=True, exist_ok=True)
        _write_new(output / "FAILURE.json", {"status": "failed_preparation_or_serialization",
            "error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc(),
            "cost": meter.snapshot(), "holdout_opened": False,
            "policy": "retain this failed attempt; it cannot be silently replaced or sealed as completed"})
        raise


def _expected(p):
    return [f"n{neurons}-qvi_full-s{seed}" for neurons in p["independent_neurons"] for seed in p["seeds"]]


def _validate_attempt(p, ap, directory):
    directory = Path(directory)
    seal = json.loads((directory / "SEAL.json").read_text())
    if (seal["adaptation_protocol_sha256"] != training.protocol_digest(ap)
            or seal["attempt"] != directory.name or set(seal["methods"]) != set(METHODS)
            or seal["summary_sha256"] != training.digest(directory / "ADAPTATION_RESULT.json")
            or seal["cache_sha256"] != training.digest(directory / "shared_features.pt")):
        raise ValueError("adaptation attempt identity or sealed common inputs changed")
    result = json.loads((directory / "ADAPTATION_RESULT.json").read_text())
    if (result["adaptation_protocol_sha256"] != training.protocol_digest(ap)
            or result["training_protocol_sha256"] != training.protocol_digest(p)
            or result["methods"] != seal["methods"] or result["attempt"] != directory.name
            or result["neurons"] not in p["independent_neurons"] or result["seed"] not in p["seeds"]
            or directory.name != f'n{result["neurons"]}-qvi_full-s{result["seed"]}'):
        raise ValueError("adaptation summary does not belong to the frozen experiment")
    arm = next(arm for arm in p["arms"] if arm["id"] == "qvi_full")
    expected_config = training.config_for(p, arm, result["neurons"])
    for method, bound in seal["methods"].items():
        if (training.digest(directory / method / "result.json") != bound["result_sha256"]
                or training.digest(directory / method / "checkpoint.pt") != bound["checkpoint_sha256"]):
            raise ValueError("sealed candidate changed")
        checkpoint = torch.load(directory / method / "checkpoint.pt", map_location="cpu", weights_only=True)
        method_result = json.loads((directory / method / "result.json").read_text())
        if (checkpoint["schema"] != "hcsn-head-adaptation-checkpoint-v1"
                or checkpoint["method"] != method or checkpoint["seed"] != result["seed"]
                or ModelConfig(**checkpoint["config"]) != expected_config
                or checkpoint["training_protocol_sha256"] != training.protocol_digest(p)
                or checkpoint["adaptation_protocol_sha256"] != training.protocol_digest(ap)
                or checkpoint["parent_checkpoint_sha256"] != result["parent_checkpoint_sha256"]
                or method_result["parent_checkpoint_sha256"] != result["parent_checkpoint_sha256"]
                or method_result["method"] != method
                or method_result["status"] not in ("completed", "failed", "ABSTAIN")
                or method_result["selected_checkpoint_sha256"] != bound["checkpoint_sha256"]):
            raise ValueError("selected candidate metadata/configuration does not belong to this exact parent and arm")
        parent, candidate = checkpoint["parent_model"], checkpoint["selected_model"]
        if (not isinstance(parent, dict) or not isinstance(candidate, dict) or parent.keys() != candidate.keys()
                or tensor_digest(parent) != result["parent_tensor_sha256"]
                or tensor_digest(candidate) != method_result["selected_tensor_sha256"]):
            raise ValueError("candidate or common parent complete tensor identity changed")
        for key, value in candidate.items():
            if (not isinstance(value, torch.Tensor) or value.shape != parent[key].shape
                    or value.dtype != parent[key].dtype
                    or (value.is_floating_point() and not bool(torch.isfinite(value).all()))
                    or (key not in HEAD_NAMES and not torch.equal(value, parent[key]))):
                raise ValueError("candidate violated the shared head mask or complete tensor schema")
        # A strict state load checks model schema as well, before holdout exists.
        checked_model = SmallHCSN(expected_config)
        checked_model.load_state_dict(candidate)
    return result


def seal_adaptations(p, adaptation_root, *, adaptation_protocol):
    validate_adaptation_protocol(p, adaptation_protocol)
    root = Path(adaptation_root)
    records = {}
    for name in _expected(p):
        _validate_attempt(p, adaptation_protocol, root / name)
        records[name] = training.digest(root / name / "SEAL.json")
    seal = {"adaptation_protocol_sha256": training.protocol_digest(adaptation_protocol), "attempts": records}
    _write_new(root / "GLOBAL_ADAPTATION_SEAL.json", seal)
    return seal


def final_test_adaptation(p, output_dir, *, adaptation_protocol, training_seal_path, adaptation_seal_path):
    """Open holdouts only after validating ALL training and adaptation attempts."""
    whole_meter = CostMeter()
    validate_adaptation_protocol(p, adaptation_protocol)
    torch.set_num_threads(1)
    output = Path(output_dir)
    training_seal_path, adaptation_seal_path = Path(training_seal_path), Path(adaptation_seal_path)
    training_seal = json.loads(training_seal_path.read_text())
    if (training_seal["source_hashes"] != p["source_hashes"]
            or training_seal["protocol_sha256"] != training.protocol_digest(p)):
        raise ValueError("global training seal changed")
    trained = training.validate_attempts(p, training_seal_path.parent, expected_records=training_seal["attempts"])
    global_seal = json.loads(adaptation_seal_path.read_text())
    if (global_seal["adaptation_protocol_sha256"] != training.protocol_digest(adaptation_protocol)
            or set(global_seal["attempts"]) != set(_expected(p))
            or output.resolve().parent != adaptation_seal_path.resolve().parent
            or output.name not in global_seal["attempts"]):
        raise ValueError("all independent parents and methods must be sealed before any final test")
    for name, seal_sha in global_seal["attempts"].items():
        directory = adaptation_seal_path.parent / name
        if training.digest(directory / "SEAL.json") != seal_sha:
            raise ValueError("global adaptation roster changed")
        record = _validate_attempt(p, adaptation_protocol, directory)
        if (trained[name][0]["status"] != "completed"
                or record["parent_checkpoint_sha256"] != trained[name][0]["checkpoint_sha256"]):
            raise ValueError("adapted parent differs from the formally trained selected checkpoint")
        trained_checkpoint = torch.load(training_seal_path.parent / name / "checkpoint.pt", map_location="cpu", weights_only=True)
        if tensor_digest(trained_checkpoint["selected_model"]) != record["parent_tensor_sha256"]:
            raise ValueError("candidate parent tensors differ from the actual trained selected model")
    with (output / "FINAL_CLAIM").open("x") as handle:
        handle.write(training.digest(adaptation_seal_path) + "\n")
    summary = json.loads((output / "ADAPTATION_RESULT.json").read_text())
    first = torch.load(output / "KEEP" / "checkpoint.pt", map_location="cpu", weights_only=True)
    dtype = first["selected_model"]["readout.weight"].dtype
    batches = {name: make_data(split, per_source=p["data"]["test_per_source"], length=p["data"]["length"], dtype=dtype)
               for name, split in (("old", "test"), ("new", "adapt_test"))}
    results = {}
    for method in METHODS:
        meter = CostMeter()
        directory = output / method
        selection = json.loads((directory / "result.json").read_text())
        selection_status = {"optimization_status": selection["status"],
                            "optimization_error": selection["error"], "adoption": selection["adoption"],
                            "selected_candidate": selection["selected_candidate"],
                            "algorithm": ("supervised ridge plus development-selected parent blend" if method == "HYBRID"
                                          else "label-free unidentified capability: ABSTAIN" if method == "STRICT_WSP"
                                          else method)}
        try:
            checkpoint = torch.load(directory / "checkpoint.pt", map_location="cpu", weights_only=True)
            if (checkpoint["method"] != method or checkpoint["parent_checkpoint_sha256"] != summary["parent_checkpoint_sha256"]
                    or checkpoint["adaptation_protocol_sha256"] != training.protocol_digest(adaptation_protocol)):
                raise ValueError("selected checkpoint identity mismatch")
            model = SmallHCSN(ModelConfig(**checkpoint["config"]))
            model.load_state_dict(checkpoint["selected_model"])
            model.eval()
            metrics, predictions = {}, {}
            for split, batch in batches.items():
                values, logits, _ = training.evaluate(model, batch)
                target = 2 * nn.functional.one_hot(batch.y, 2).double() - 1
                values["signed_target_mse"] = float((logits[-1].double() - target).square().mean())
                metrics[split] = values
                predictions[split] = {"ids": batch.ids, "labels": batch.y.tolist(), "source": batch.source.tolist(),
                    "all_prefix_logits": logits.tolist(), "initial_margin": batch.initial_margin.tolist(),
                    "late_step": batch.late_step.tolist(), "dataset_sha256": batch.digest()}
            _write_new(directory / "test_predictions.json", predictions)
            row = {"method": method, "status": "evaluated", "metrics": metrics,
                   **selection_status,
                   "checkpoint_sha256": training.digest(directory / "checkpoint.pt"),
                   "predictions_sha256": training.digest(directory / "test_predictions.json"), "cost": meter.snapshot()}
        except (RuntimeError, ValueError, FloatingPointError) as exc:
            row = {"method": method, "status": "failed", "error": type(exc).__name__ + ": " + str(exc),
                   **selection_status,
                   "traceback": traceback.format_exc(), "cost": meter.snapshot()}
        _write_new(directory / "test_result.json", row)
        row["complete_cost_including_result_write"] = meter.snapshot()
        results[method] = row
    final = {"attempt": output.name, "seed": summary["seed"], "neurons": summary["neurons"],
             "training_seal_sha256": training.digest(training_seal_path),
             "global_adaptation_seal_sha256": training.digest(adaptation_seal_path),
             "results": results, "cost_before_final_json": whole_meter.snapshot(),
             "final_selection_permitted": False,
             "scope": "one frozen holdout evaluation; development-selected candidates are never changed"}
    _write_new(output / "FINAL_RESULTS.json", final)
    return final


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "fit", "seal", "test"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--adaptation-manifest", required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--output")
    parser.add_argument("--training-seal")
    parser.add_argument("--adaptation-seal")
    args = parser.parse_args()
    torch.set_num_threads(1)
    p = training.load_protocol(args.manifest)
    if args.action == "freeze":
        freeze_adaptation(p, args.adaptation_manifest)
        return
    ap = json.loads(Path(args.adaptation_manifest).read_text())
    if args.action == "fit":
        result = fit_adaptation(p, args.checkpoint, args.output, adaptation_protocol=ap)
    elif args.action == "seal":
        result = seal_adaptations(p, args.output, adaptation_protocol=ap)
    else:
        result = final_test_adaptation(p, args.output, adaptation_protocol=ap,
            training_seal_path=args.training_seal, adaptation_seal_path=args.adaptation_seal)
    print(json.dumps({"action": args.action, "attempt": result.get("attempt"), "completed": True}), flush=True)


if __name__ == "__main__":
    main()

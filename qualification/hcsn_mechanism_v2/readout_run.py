"""Fixed-representation adaptation with converged conditional BP and full costs."""

import hashlib
import time

import torch

from qualification.hcsn_confirmatory_v1.run import encoder
from qualification.hcsn_confirmatory_v1.tasks import digest, generate

from .readout import optimality, solve_arm
from .representation import feature_banks, fit_scaler, predict, ridge_fit, standardize


METHODS = ("direct", "local_bp", "semantic_program", "program_then_bp")


def plain(value):
    if isinstance(value, torch.Tensor):
        return value.detach().tolist()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def matrix_sha(value):
    tensor = value.detach().cpu().contiguous()
    return hashlib.sha256(
        str((list(tensor.shape), str(tensor.dtype))).encode() + tensor.numpy().tobytes()
    ).hexdigest()


def state(value):
    return {"weight": plain(value["weight"]), "bias": plain(value["bias"])}


def fit_case(task, seed, cfg):
    c = cfg["readout"]
    start, cpu_start = time.perf_counter(), time.process_time()
    train = generate(cfg["namespace"], seed, task, "train", c["train"], c["length"])
    dev = generate(cfg["namespace"], seed, task, "dev", c["dev"], c["length"])
    model = encoder(task)
    train_bank, names = feature_banks(model, train)
    dev_bank, _ = feature_banks(model, dev)
    tx, dx = train_bank["same_generator"], dev_bank["same_generator"]
    ty, dy = torch.from_numpy(train["y"][:, 0]), torch.from_numpy(dev["y"][:, 0])
    common_seconds, common_cpu = (
        time.perf_counter() - start,
        time.process_time() - cpu_start,
    )
    result = {
        "task": task,
        "seed": seed,
        "train_sha256": digest(train),
        "dev_sha256": digest(dev),
        "feature_names": names,
        "feature_bank": "same_generator",
        "pool": "legacy",
        "train_feature_sha256": matrix_sha(tx),
        "dev_feature_sha256": matrix_sha(dx),
        "common_feature_seconds": common_seconds,
        "common_feature_cpu_seconds": common_cpu,
        "common_encoder_events": (c["train"] + c["dev"]) * c["length"],
        "parameter_scope": "21 readout parameters; all 30 encoder/boundary parameters frozen",
        "full_network_optimality_claim": False,
        "scalers": {},
    }
    rotation = (cfg["tasks"].index(task) + cfg["seeds"].index(seed)) % len(METHODS)
    order = METHODS[rotation:] + METHODS[:rotation]
    for normalization in c["scalers"]:
        s0, c0 = time.perf_counter(), time.process_time()
        scaler = fit_scaler(tx, normalization, c["scale_floor"])
        x, d = standardize(tx, scaler), standardize(dx, scaler)
        preprocessing_seconds, preprocessing_cpu = (
            time.perf_counter() - s0,
            time.process_time() - c0,
        )
        zero = {"weight": x.new_zeros(x.shape[1]), "bias": x.new_zeros(())}
        zero_mse = float(dy.square().mean())
        arms = {}
        for position, method in enumerate(order):
            fitted, costs = solve_arm(method, task, names, scaler, x, ty, c)
            t0 = time.perf_counter()
            candidate_prediction = predict(d, fitted)
            dev_mse = float((candidate_prediction - dy).square().mean())
            accept = dev_mse < zero_mse
            selected = fitted if accept else zero
            costs["selection_seconds"] = time.perf_counter() - t0
            costs["standalone_seconds_lower_bound"] = (
                common_seconds
                + preprocessing_seconds
                + costs["total_arm_seconds"]
                + costs["selection_seconds"]
            )
            arms[method] = {
                "position": position,
                "candidate": state(fitted),
                "selected": state(selected),
                "status": "selected" if accept else "no_update",
                "dev_candidate_mse": dev_mse,
                "dev_zero_mse": zero_mse,
                "dev_selected_mse": min(dev_mse, zero_mse),
                "cost": costs,
            }
        audit_start = time.perf_counter()
        # A post-fit train-only diagnostic. It never feeds any optimizer.
        optimum = ridge_fit(x, ty, ridge=c["ridge"])
        for method in METHODS:
            checks = optimality(x, ty, arms[method]["candidate"], c["ridge"], optimum)
            checks["objective_tolerance"] = c["objective_tolerance"]
            checks["within_objective_tolerance"] = (
                abs(checks["objective_gap"]) <= c["objective_tolerance"]
            )
            arms[method]["optimality"] = checks
        result["scalers"][normalization] = {
            "scaler": plain(scaler),
            "preprocessing_seconds": preprocessing_seconds,
            "preprocessing_cpu_seconds": preprocessing_cpu,
            "order": list(order),
            "oracle_diagnostic_seconds": time.perf_counter() - audit_start,
            "solver_diagnostics": optimum["diagnostics"],
            "methods": arms,
        }
    result["case_seconds"] = time.perf_counter() - start
    result["case_cpu_seconds"] = time.process_time() - cpu_start
    return result


def final_case(record, task, seed, cfg):
    c = cfg["readout"]
    model = encoder(task)
    results = []
    for split in ("final_iid", "final_clock"):
        start, cpu_start = time.perf_counter(), time.process_time()
        data = generate(cfg["namespace"], seed, task, split, c["final"], c["length"])
        bank, _ = feature_banks(model, data)
        common = time.perf_counter() - start
        common_cpu = time.process_time() - cpu_start
        target = torch.from_numpy(data["y"][:, 0])
        for normalization, saved in record["scalers"].items():
            x = standardize(bank["same_generator"], saved["scaler"])
            for method in METHODS:
                arm = saved["methods"][method]
                raw = predict(x, arm["selected"])
                for link in (
                    ("identity", "clip_unit")
                    if task == "first_passage"
                    else ("identity",)
                ):
                    prediction = raw if link == "identity" else raw.clamp(0, 1)
                    losses = (prediction - target).square()
                    results.append(
                        {
                            "task": task,
                            "seed": seed,
                            "split": split,
                            "shift_kind": "same distribution"
                            if split == "final_iid"
                            else "new trajectories and longer physical horizon; not paired resampling",
                            "normalization": normalization,
                            "method": method,
                            "link": link,
                            "status": arm["status"],
                            "data_sha256": digest(data),
                            "mse": float(losses.mean()),
                            "sample_squared_errors": losses.tolist(),
                            "prediction": prediction.tolist(),
                            "raw_prediction": raw.tolist(),
                            "target": target.tolist(),
                            "ids": data["ids"].tolist(),
                            "common_final_features_seconds": common,
                            "common_final_features_cpu_seconds": common_cpu,
                        }
                    )
    return results

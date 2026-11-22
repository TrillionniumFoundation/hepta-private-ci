"""Feature x scaling x shared output-projection mechanism study.

The caller freezes source/config/namespace and enforces global phase consumption,
process budgets and serialization costs. No CLI, retry policy or hidden search
is implemented here. Old final data must never enter these functions.
"""

import hashlib
import time

import torch

from qualification.hcsn_confirmatory_v1.run import encoder
from qualification.hcsn_confirmatory_v1.tasks import TASKS, digest, generate

from .representation import (
    BANKS,
    feature_banks,
    fit_scaler,
    predict,
    ridge_fit,
    shift_diagnostics,
    spectrum_diagnostics,
    standardize,
)


def _record(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, dict):
        return {key: _record(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_record(item) for item in value]
    return value


def _matrix_digest(value):
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(
        str((array.shape, array.dtype)).encode() + array.tobytes()
    ).hexdigest()


def _links(task):
    return ("identity", "clip_unit") if task == "first_passage" else ("identity",)


def _input_summary(data):
    x, dt = data["x"], data["dt"]
    return {
        "x_min": x.min(axis=(0, 1)).tolist(),
        "x_max": x.max(axis=(0, 1)).tolist(),
        "x_mean": x.mean(axis=(0, 1)).tolist(),
        "x_std": x.std(axis=(0, 1)).tolist(),
        "dt_min": float(dt.min()),
        "dt_max": float(dt.max()),
        "horizon_min": float(dt.sum(1).min()),
        "horizon_max": float(dt.sum(1).max()),
        "horizon_mean": float(dt.sum(1).mean()),
        "samples": len(x),
        "length": x.shape[1],
    }


def _identity(task, seed, cfg):
    if task not in TASKS or type(seed) is not int or seed not in cfg["seeds"]:
        raise ValueError("predeclared task and seed required")
    return {
        "task": task,
        "seed": seed,
        "namespace": cfg["namespace"],
        "pools": cfg["pools"],
        "scalers": cfg["scalers"],
        "scale_floor": cfg["scale_floor"],
        "ridge": cfg["ridge"],
        "train": cfg["train"],
        "dev": cfg["dev"],
        "final": cfg["final"],
        "length": cfg["length"],
        "banks": list(BANKS),
        "links": list(_links(task)),
        "selection": "candidate dev MSE < train-mean incumbent dev MSE",
        "link_scope": "shared post-fit projection; raw MSE+ridge training unchanged",
    }


def fit_case(task, seed, cfg):
    started = time.perf_counter()
    identity = _identity(task, seed, cfg)
    train = generate(cfg["namespace"], seed, task, "train", cfg["train"], cfg["length"])
    dev = generate(cfg["namespace"], seed, task, "dev", cfg["dev"], cfg["length"])
    model = encoder(task)
    ty, dy = torch.from_numpy(train["y"][:, 0]), torch.from_numpy(dev["y"][:, 0])
    incumbent = {"weight": torch.zeros(20, dtype=torch.float64), "bias": ty.mean()}
    base_mse = float((ty.mean() - dy).square().mean())
    result = {
        "identity": identity,
        "train_sha256": digest(train),
        "dev_sha256": digest(dev),
        "train_input_summary": _input_summary(train),
        "dev_input_summary": _input_summary(dev),
        "train_ids": train["ids"].tolist(),
        "dev_ids": dev["ids"].tolist(),
        "train_target": ty.tolist(),
        "methods": {},
        "training_features": {},
        "outer_input_dependence": {
            "drive_input_weights": model.encoder.drive.weight.detach().tolist(),
            "boundary_input_weights": model.boundary.weight.detach().tolist(),
            "writer_input_weights": model.encoder.writer.weight.detach().tolist(),
            "population_receives_content_feedback": False,
            "analytic_channels_use_writer": False,
            "interpretation": "with zero drive/boundary weights, call/risk depend only on clock",
        },
    }
    for pooling in cfg["pools"]:
        feature_start = time.perf_counter()
        training, names = feature_banks(model, train, pooling)
        development, _ = feature_banks(model, dev, pooling)
        feature_seconds = time.perf_counter() - feature_start
        extra = [
            names.index(f"{pool}.{name}")
            for pool in ("last", "mean")
            for name in ("call", "risk")
        ]
        for bank in BANKS:
            raw = training[bank]
            feature_key = f"{pooling}/{bank}"
            result["training_features"][feature_key] = {
                "values": raw.tolist(),
                "sha256": _matrix_digest(raw),
                "names": names,
                "spectrum_raw": spectrum_diagnostics(raw, extra),
                "shared_full_bank_seconds": feature_seconds,
            }
            for scaling in cfg["scalers"]:
                adaptation = time.perf_counter()
                scaler = fit_scaler(raw, scaling, cfg["scale_floor"])
                tx, dx = (
                    standardize(raw, scaler),
                    standardize(development[bank], scaler),
                )
                candidate = ridge_fit(tx, ty, cfg["ridge"])
                diagnostic = spectrum_diagnostics(tx, extra)
                shared_fit_seconds = time.perf_counter() - adaptation
                for link in _links(task):
                    evaluate_started = time.perf_counter()
                    predictions = predict(dx, candidate, link)
                    dev_mse = float((predictions - dy).square().mean())
                    accept = dev_mse < base_mse
                    key = f"{pooling}/{bank}/{scaling}/{link}"
                    result["methods"][key] = {
                        "pooling": pooling,
                        "bank": bank,
                        "scaling": scaling,
                        "link": link,
                        "status": "selected" if accept else "no_update",
                        "scaler": _record(scaler),
                        "candidate": _record(candidate),
                        "selected": _record(candidate if accept else incumbent),
                        "incumbent": _record(incumbent),
                        "base_dev_mse": base_mse,
                        "candidate_dev_mse": dev_mse,
                        "selected_dev_mse": min(dev_mse, base_mse),
                        "train_standardized_spectrum": diagnostic,
                        "development_shift": shift_diagnostics(
                            development[bank], scaler, candidate
                        ),
                        "eligible_parameters": 21,
                        "feature_key": feature_key,
                        "shared_fit_seconds": shared_fit_seconds,
                        "selection_seconds": time.perf_counter() - evaluate_started,
                        "standalone_wall_lower_bound": feature_seconds
                        + shared_fit_seconds
                        + time.perf_counter()
                        - evaluate_started,
                    }
    result["case_wall_before_serialization"] = time.perf_counter() - started
    result["cost_scope"] = (
        "case wall includes data/features/solves/evaluation; caller must meter import, serialization and exit"
    )
    return result


def _evaluation(values, scaler, state, target, link):
    standardized = standardize(values, scaler)
    raw, output = predict(standardized, state), predict(standardized, state, link)
    errors = (output - target).square()
    return {
        "raw_prediction": raw.tolist(),
        "prediction": output.tolist(),
        "raw_mse": float((raw - target).square().mean()),
        "mse": float(errors.mean()),
        "sample_squared_errors": errors.tolist(),
        "shift": shift_diagnostics(values, scaler, state),
    }


def final_case(record, task, seed, cfg):
    started = time.perf_counter()
    if record["identity"] != _identity(task, seed, cfg):
        raise ValueError("representation case identity or hyperparameters changed")
    model = encoder(task)
    result = {"task": task, "seed": seed, "results": [], "data": {}}
    for split in ("final_iid", "final_clock"):
        data = generate(
            cfg["namespace"], seed, task, split, cfg["final"], cfg["length"]
        )
        target = torch.from_numpy(data["y"][:, 0])
        result["data"][split] = {
            "sha256": digest(data),
            "ids": data["ids"].tolist(),
            "target": target.tolist(),
            "input_summary": _input_summary(data),
            "shift_semantics": (
                "longer horizon AND new trajectory/input distribution; not paired resampling"
                if split == "final_clock"
                else "independent IID window"
            ),
        }
        for pooling in cfg["pools"]:
            banks, names = feature_banks(model, data, pooling)
            extra = [
                names.index(f"{pool}.{name}")
                for pool in ("last", "mean")
                for name in ("call", "risk")
            ]
            for key, method in record["methods"].items():
                if method["pooling"] != pooling:
                    continue
                values = banks[method["bank"]]
                scaler, link = method["scaler"], method["link"]
                candidate = _evaluation(
                    values, scaler, method["candidate"], target, link
                )
                selected = _evaluation(values, scaler, method["selected"], target, link)
                row = {
                    "case": f"{task}/{seed}",
                    "method": key,
                    "split": split,
                    "status": method["status"],
                    "candidate": candidate,
                    "selected": selected,
                    "no_update_mse": float(
                        (target.new_tensor(method["incumbent"]["bias"]) - target)
                        .square()
                        .mean()
                    ),
                    "feature_sha256": _matrix_digest(values),
                    "data_sha256": digest(data),
                }
                if method["bank"] == "same_generator":
                    z = standardize(values, scaler)
                    muted = z.clone()
                    muted[:, extra] = (
                        0  # exact algebraic removal of these readout terms, no refit
                    )
                    muted_raw = predict(muted, method["candidate"])
                    full_raw = predict(z, method["candidate"])
                    row["value_risk_contribution"] = {
                        "scope": "frozen candidate readout, analytic columns fixed at training means; not a causal re-fit",
                        "raw_delta": (full_raw - muted_raw).tolist(),
                        "mean_muted_raw_mse": float(
                            (muted_raw - target).square().mean()
                        ),
                        "muted_prediction": predict(
                            muted, method["candidate"], link
                        ).tolist(),
                    }
                result["results"].append(row)
    result["case_wall_before_serialization"] = time.perf_counter() - started
    return result

"""Frozen two-event native/history controllers; fit on explicit train/dev only."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..field_bridge_20261027.controls import _observations, choose, history_features
from ..field_bridge_20261027.protocol import P as V1
from .native_fast import native_features_fast

SCHEMA = "hepta.field-bridge-v2.primary-runtime-controller.v1"
LIBRARY_SHA = "bfad6ca9d91d958296fa47c7f8ace4414b7ddf659e079ae5394c37bd104ceac3"
ALPHAS = (0.0001, 0.01, 1.0)
TRANSFORMS = (("raw", None), ("common_standardization_k1", 1),
              ("common_standardization_k2", 2), ("common_standardization_k4", 4))
FAMILIES = {"native": ("pure_native40", "raw16_native24"),
            "history": ("original_history40", "raw16_rff24")}
RFF_SEED = 271029
CONDITIONS = tuple(V1["training_conditions"])


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def matrix_sha(value):
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes()).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _standardizer(value):
    return {"mean": value.mean(0).tolist(), "scale": np.maximum(value.std(0), 1e-6).tolist(),
            "std_floor": 1e-6, "std_ddof": 0, "fit_scope": "training_features_only"}


def _standardize(value, normalizer, width):
    mean, scale = np.asarray(normalizer["mean"]), np.asarray(normalizer["scale"])
    if (mean.shape != (width,) or scale.shape != (width,) or not np.isfinite(mean).all()
            or not np.isfinite(scale).all() or np.any(scale < 1e-6)):
        raise ValueError("Invalid frozen feature normalizer")
    return (value - mean) / scale


def _transform(x0, x1, transform):
    if (transform["name"], transform["k"]) not in TRANSFORMS:
        raise ValueError("Unregistered public-input transform")
    if transform["k"] is None:
        return x0, x1
    return tuple((np.clip(_standardize(x, transform["normalizer"], 8)
                         / transform["k"], -1, 1) + 1) / 2 for x in (x0, x1))


def _hybrid_history(raw, transformed, spec):
    weights = np.asarray(spec["weights"], dtype=np.float64)
    if (weights.shape != (16, 12) or not np.isfinite(weights).all()
            or matrix_sha(weights) != spec["weight_sha256"]):
        raise ValueError("Invalid frozen Fourier weights")
    projection = _standardize(transformed, spec["normalizer"], 16) @ weights
    return np.column_stack((raw, np.cos(projection) / np.sqrt(12), np.sin(projection) / np.sqrt(12)))


def select(readout, x0, x1, bridge=None, case_prefix="", reset=False, receipt_path=None):
    """Select without labels/fitting; a reset changes only the native checkpoint.

    Native receipts bind transformed observations. The summary also binds raw
    observations and the complete frozen controller needed to reproduce them.
    A raw16-native24 controller still sees raw x0 when its native state resets.
    """
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    if (readout.get("schema") != SCHEMA or readout.get("authority") != "DENY_ALL"
            or readout.get("native_owner_integration") is not False or type(reset) is not bool):
        raise ValueError("Invalid frozen runtime controller or reset declaration")
    representation, family = readout["representation"], readout["family"]
    if representation not in FAMILIES or family not in FAMILIES[representation]:
        raise ValueError("Unknown registered representation family")
    x0, x1 = _observations(x0, x1)
    raw = np.column_stack((x0, x1))
    phase = time.perf_counter_ns()
    u0, u1 = _transform(x0, x1, readout["transform"])
    transform_ns = time.perf_counter_ns() - phase
    phase = time.perf_counter_ns()
    native_summary = {"original_sparse_tick_calls": 0, "native_ns": 0,
                      "bridge_roundtrip_ns": 0, "complete_receipts_written": False}
    if representation == "native":
        if (bridge is None or readout["native_library_sha256"] != LIBRARY_SHA
                or bridge.binary_sha256 != LIBRARY_SHA):
            raise ValueError("Pinned native bridge is required")
        native = native_features_fast(bridge, u0, u1, case_prefix, reset, receipt_path)
        native_summary = dict(bridge.last_feature_batch)
        if family == "pure_native40":
            features = native
        else:
            indices = np.asarray(readout["native_selector"]["indices"])
            if (indices.shape != (24,) or not np.issubdtype(indices.dtype, np.integer)
                    or len(set(indices.tolist())) != 24 or np.any(indices < 0) or np.any(indices >= 40)):
                raise ValueError("Invalid frozen native coordinate selector")
            features = np.column_stack((raw, native[:, indices]))
    else:
        if reset or receipt_path is not None:
            raise ValueError("History controllers have no native reset or receipt file")
        features = history_features(u0, u1) if family == "original_history40" else _hybrid_history(
            raw, np.column_stack((u0, u1)), readout["fourier"])
    representation_ns = time.perf_counter_ns() - phase
    phase = time.perf_counter_ns()
    actions = choose(readout["head"], features)
    head_ns = time.perf_counter_ns() - phase
    summary = dict(native_summary)
    summary.update(schema="hepta.field-bridge-v2.primary-runtime-selection.v1", rows=len(x0),
        representation=representation, family=family, target_accesses=0, authority="DENY_ALL",
        native_owner_integration=False, controller_sha256=object_sha(readout),
        raw_history_sha256=matrix_sha(raw), transformed_history_sha256=matrix_sha(np.column_stack((u0, u1))),
        feature_matrix_sha256=matrix_sha(features), action_indices=actions.tolist(),
        raw_history_preserved=family.startswith("raw16_"), reset_before_readout=reset,
        reset_scope="native checkpoint only; raw history unchanged" if reset else "no intervention",
        common_transform_ns=transform_ns, representation_wall_ns=representation_ns, head_wall_ns=head_ns,
        select_wall_ns=time.perf_counter_ns() - started, select_python_cpu_ns=time.process_time_ns() - cpu,
        cost_scope="public input validation/transform, feature extraction, optional full native receipts, frozen head and provenance; excludes model/media")
    return actions, summary


def _bank(bank, role):
    if bank.get("role") != role:
        raise ValueError("Fitting requires explicitly declared train and development banks")
    x0, x1 = _observations(bank["x0"], bank["x1"])
    returns = np.asarray(bank["returns"], dtype=np.float64)
    if returns.shape != (len(x0), 5) or not np.isfinite(returns).all() or len(x0) % len(CONDITIONS):
        raise ValueError("Action-return rows or condition grouping are invalid")
    return x0, x1, returns


def _heads(train_x, train_returns, dev_x, dev_returns):
    normalizer = _standardizer(train_x)
    z = np.column_stack((_standardize(train_x, normalizer, 40), np.ones(len(train_x))))
    gram, cross = z.T @ z, z.T @ train_returns
    penalty = np.diag(np.r_[np.ones(40), 0.0])
    records = []
    for alpha in ALPHAS:
        started = time.perf_counter_ns()
        coefficient = np.linalg.solve(gram + alpha * penalty, cross)
        head = {"schema": "hepta.field-bridge.ridge-readout.v1", "coefficient": coefficient.tolist(),
                "normalizer": normalizer, "chosen_alpha": alpha, "parameter_count": 205,
                "normalizer_statistic_count": 80, "intercept_penalized": False}
        train_actions, dev_actions = choose(head, train_x), choose(head, dev_x)
        train_values = train_returns[np.arange(len(train_x)), train_actions]
        dev_values = dev_returns[np.arange(len(dev_x)), dev_actions]
        records.append({"head": head, "alpha": alpha, "train_value": float(train_values.mean()),
            "dev_value": float(dev_values.mean()), "dev_oracle_regret": float(dev_returns.max(1).mean()-dev_values.mean()),
            "train_action_indices": train_actions.tolist(), "dev_action_indices": dev_actions.tolist(),
            "train_regression_mse": float(np.mean((z @ coefficient-train_returns)**2)),
            "development_by_condition": {name: float(values.mean()) for name, values in
                zip(CONDITIONS, np.split(dev_values, len(CONDITIONS)), strict=True)},
            "solve_and_score_wall_ns": time.perf_counter_ns()-started})
    return records


def fit_controllers(train, development, bridge, case_prefix, metadata=None, feature_destination=None):
    """Retain all 48 heads; dev selects independently within two 24-head grids."""
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    if bridge.binary_sha256 != LIBRARY_SHA:
        raise ValueError("Wrong native library")
    if feature_destination is not None and Path(feature_destination).exists():
        raise ValueError("Refusing to replace existing feature evidence")
    t0, t1, tr = _bank(train, "train")
    d0, d1, dr = _bank(development, "development")
    common = _standardizer(np.concatenate((t0, t1)))
    train_raw, dev_raw = np.column_stack((t0, t1)), np.column_stack((d0, d1))
    weights = np.random.default_rng(RFF_SEED).normal(size=(16, 12)) / np.sqrt(16)
    candidates, transformations, saved_features = [], [], {}
    for transform_index, (name, k) in enumerate(TRANSFORMS):
        phase = time.perf_counter_ns()
        transform = {"name": name, "k": k, "normalizer": common}
        u0, u1 = _transform(t0, t1, transform)
        v0, v1 = _transform(d0, d1, transform)
        native_train = native_features_fast(bridge, u0, u1, f"{case_prefix}-{transform_index}-train")
        train_cost = dict(bridge.last_feature_batch)
        native_dev = native_features_fast(bridge, v0, v1, f"{case_prefix}-{transform_index}-dev")
        dev_cost = dict(bridge.last_feature_batch)
        variance = native_train.var(0)
        indices = np.lexsort((np.arange(40), -variance))[:24]
        selector = {"indices": indices.tolist(), "training_variance": variance.tolist(),
                    "fit_scope": "training_features_only", "tie_break": "ascending original index"}
        train_u, dev_u = np.column_stack((u0, u1)), np.column_stack((v0, v1))
        fourier = {"seed": RFF_SEED, "weights": weights.tolist(), "weight_sha256": matrix_sha(weights),
                   "normalizer": _standardizer(train_u)}
        pairs = {"pure_native40": (native_train, native_dev),
            "raw16_native24": (np.column_stack((train_raw, native_train[:, indices])),
                               np.column_stack((dev_raw, native_dev[:, indices]))),
            "original_history40": (history_features(u0, u1), history_features(v0, v1)),
            "raw16_rff24": (_hybrid_history(train_raw, train_u, fourier), _hybrid_history(dev_raw, dev_u, fourier))}
        construction_ns = time.perf_counter_ns()-phase
        feature_hashes = {}
        for representation, families in FAMILIES.items():
            for family_index, family in enumerate(families):
                train_x, dev_x = pairs[family]
                feature_hashes[family] = {"train": matrix_sha(train_x), "development": matrix_sha(dev_x)}
                if feature_destination is not None:
                    saved_features[f"{transform_index}.{family}.train"] = train_x
                    saved_features[f"{transform_index}.{family}.development"] = dev_x
                for alpha_index, fitted in enumerate(_heads(train_x, tr, dev_x, dr)):
                    readout = {"schema": SCHEMA, "representation": representation, "family": family,
                        "transform": transform, "native_selector": selector if representation == "native" else None,
                        "fourier": fourier if family == "raw16_rff24" else None, "head": fitted.pop("head"),
                        "native_library_sha256": LIBRARY_SHA if representation == "native" else None,
                        "authority": "DENY_ALL", "native_owner_integration": False,
                        "fit_metadata": metadata or {}, "training_rows": len(t0), "development_rows": len(d0)}
                    candidates.append(fitted | {"representation": representation, "family": family,
                        "transform": name, "candidate_index": family_index*12+transform_index*3+alpha_index,
                        "controller": readout})
        transformations.append({"transform": transform, "native_train_cost": train_cost,
            "native_development_cost": dev_cost, "all_feature_construction_wall_ns": construction_ns,
            "feature_matrix_sha256": feature_hashes, "native_selector": selector, "fourier": fourier})
    selected = {rep: max((c for c in candidates if c["representation"] == rep),
                        key=lambda c: (c["dev_value"], -c["candidate_index"])) for rep in FAMILIES}
    feature_receipt = None
    if feature_destination is not None:
        phase = time.perf_counter_ns()
        np.savez_compressed(feature_destination, **saved_features)
        feature_receipt = {"file": Path(feature_destination).name, "sha256": file_sha(feature_destination),
                           "matrices": len(saved_features), "write_wall_ns": time.perf_counter_ns()-phase}
    train_fixed, dev_fixed = int(tr.mean(0).argmax()), int(dr.mean(0).argmax())
    result = {"schema": "hepta.field-bridge-v2.primary-runtime-fit.v1",
        "models": {rep: selected[rep]["controller"] for rep in FAMILIES},
        "selected": {rep: {key: selected[rep][key] for key in
            ("candidate_index", "family", "transform", "alpha", "train_value", "dev_value")} for rep in FAMILIES},
        "candidates": sorted(candidates, key=lambda c: (c["representation"], c["candidate_index"])),
        "transformations": transformations, "feature_evidence": feature_receipt,
        "heads_fitted": len(candidates), "conditions": list(CONDITIONS),
        "fixed_diagnostics": {"train_selected_action": train_fixed, "development_selected_action": dev_fixed,
            "train_values": tr.mean(0).tolist(), "development_values": dr.mean(0).tolist(),
            "development_training_selected_value": float(dr[:, train_fixed].mean()),
            "development_row_oracle": float(dr.max(1).mean())},
        "original_sparse_tick_calls": 8*(len(t0)+len(d0)), "runtime_fixed_fallback": False,
        "training_only_fit": True, "development_selection_only": True, "development_refit": False,
        "selection_tie_break": "family then transform then alpha index", "metadata": metadata or {},
        "fit_wall_ns": time.perf_counter_ns()-started, "fit_python_cpu_ns": time.process_time_ns()-cpu}
    return json.loads(json.dumps(result, allow_nan=False))


def fit_runtime(model, corpus, observer, bridge, seed, profile, out, *, protocol=None):
    """Build declared reward-only banks and complete retained fitting evidence."""
    from ..field_bridge_20261027.run import bank_set
    from ..v6.neural import parameter_hash

    protocol = protocol or {}
    registered = {"readout_ridges": list(ALPHAS), "runtime_families": {k: list(v) for k, v in FAMILIES.items()},
        "runtime_transforms": [{"name": n, "k": k} for n, k in TRANSFORMS],
        "runtime_rff_seed": RFF_SEED, "runtime_fixed_fallback": False,
        "runtime_conditions": list(CONDITIONS), "training_conditions": list(CONDITIONS),
        "refinement_charge": V1["refinement_charge"]}
    if any(key in protocol and protocol[key] != value for key, value in registered.items()):
        raise ValueError("Runtime family differs from the registered equal-budget recipe")
    offsets = {"runtime_train_offset": 3500, "runtime_train_pairs": 512,
               "readout_development_offset": 600, "readout_development_pairs": 256}
    if any(key in protocol and protocol[key] != value for key, value in offsets.items()):
        raise ValueError("Runtime data split differs from the registered split")
    if profile not in {"frozen", "ordinary", "field"} or seed not in V1["seeds"]:
        raise ValueError("Unexpected runtime fitting checkpoint")
    started = time.perf_counter_ns()
    root = Path(out) / "runtime" / f"{seed}-{profile}"
    root.mkdir(parents=True, exist_ok=False)
    model_hash, observer_hash = parameter_hash(model), parameter_hash(observer)
    train = bank_set(model, corpus, observer, split="train", offset=3500, count=512, seed=seed, role="train")
    dev = bank_set(model, corpus, observer, split="validation", offset=600, count=256, seed=seed+701, role="development")
    train["role"], dev["role"] = "train", "development"
    if parameter_hash(model) != model_hash or parameter_hash(observer) != observer_hash:
        raise RuntimeError("Fitting bank generation mutated a frozen model")
    np.savez_compressed(root / "banks.npz", **{f"{prefix}_{key}": bank[key] for prefix, bank in
                        (("train", train), ("dev", dev)) for key in ("x0", "x1", "returns")})
    hard = {f"{prefix}_condition{index}_{key}": output[key].detach().cpu().numpy()
            for prefix, bank in (("train", train), ("dev", dev))
            for index, output in enumerate(bank["outputs"]) for key in ("pixels_u8", "token_ids")}
    np.savez_compressed(root / "hard-bank-outputs.npz", **hard)
    identities = {"train": train["source_ids"], "development": dev["source_ids"],
        "train_resources": train["resources"], "development_resources": dev["resources"],
        "model_sha256": model_hash, "reward_observer_sha256": observer_hash, "conditions": list(CONDITIONS),
        "data_splits": offsets, "hard_outputs_sha256": file_sha(root / "hard-bank-outputs.npz"),
        "bank_seed_schedule": {"training_seed": seed, "development_seed": seed+701,
            "corruption_seed": "bank_seed*1009+condition_index", "latent_noise_seed": "bank_seed*2017+condition_index"},
        "action_order": ["stop", "refine_image", "refine_text", "refine_semantic", "couple"],
        "return_formula": "hard utility minus refinement_charge*(1+(action_index!=0))",
        "refinement_charge": V1["refinement_charge"],
        "hard_array_shapes": {key: list(value.shape) for key, value in hard.items()},
        "hard_array_dtypes": {key: str(value.dtype) for key, value in hard.items()},
        "bank_generation_wall_ns": time.perf_counter_ns()-started, "audit_observer_accessed": False}
    _write(root / "BANK_IDENTITIES.json", identities)
    metadata = {"seed": seed, "profile": profile, "model_sha256": model_hash,
        "banks_sha256": file_sha(root / "banks.npz"), "bank_identities_sha256": file_sha(root / "BANK_IDENTITIES.json")}
    fitted = fit_controllers(train, dev, bridge, f"primary-{seed}-{profile}", metadata, root / "features.npz")
    fitted["total_bank_and_fit_wall_ns"] = time.perf_counter_ns()-started
    fitted["shared_train_development_label_rows"] = int(train["returns"].size+dev["returns"].size)
    _write(root / "READOUTS.json", fitted)
    return fitted["models"]

"""Matched-size native/history features and training-only continuation readouts.

Runtime feature extraction and choose() accept no targets. fit_readout() consumes
only explicit training/development return banks; those returns already include
the caller's fixed action costs. It never scores a task or reads a test bank.
"""

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .native_bridge import Q24

FEATURE_WIDTH = 40
OBSERVATION_WIDTH = 8
ACTION_COUNT = 5
ACTION_ORDER = ("stop", "refine_image", "refine_text", "refine_semantic", "couple")
ALPHAS = (1e-4, 0.01, 1.0)
STD_FLOOR = 1e-6


def _matrix(value, name, width):
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != width or array.shape[0] == 0:
        raise ValueError(f"{name} must be a nonempty N x {width} matrix")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains non-finite values")
    return np.ascontiguousarray(array)


def _observations(x0, x1):
    x0 = _matrix(x0, "first public observations", OBSERVATION_WIDTH)
    x1 = _matrix(x1, "second public observations", OBSERVATION_WIDTH)
    if x0.shape != x1.shape:
        raise ValueError("Two public observation events must have the same shape")
    if np.any(x0 < 0) or np.any(x0 > 1) or np.any(x1 < 0) or np.any(x1 > 1):
        raise ValueError("Public observation features must already be bounded in [0,1]")
    return x0, x1


def native_features(bridge, x0, x1, case_prefix, reset=False, receipt_path=None):
    """Return real second-tick activation/eligibility (N x 40), with no labels.

    Two public eight-vectors are mapped by 2*x-1 and nearest/ties-even Q24.
    Readback identity hashes their original float64 little-endian bytes, x0
    followed by x1; the case identity separately binds scope. Reset removes the
    first checkpoint, while retaining the same second public observation.
    """
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    x0, x1 = _observations(x0, x1)
    if not isinstance(case_prefix, str) or not case_prefix or len(case_prefix.encode()) > 230:
        raise ValueError("Case prefix must contain 1..230 UTF-8 bytes")
    if type(reset) is not bool:
        raise ValueError("Reset must be explicitly boolean")
    path = Path(receipt_path) if receipt_path is not None else None
    summary_path = path.with_name(path.name + ".summary.json") if path is not None else None
    if path is not None:
        if path.exists() or summary_path.exists():
            raise ValueError("Refusing to replace existing native feature evidence")
        path.parent.mkdir(parents=True, exist_ok=True)
    result = np.empty((len(x0), FEATURE_WIDTH), dtype=np.float64)
    native_ns, roundtrip_ns, tick_calls = 0, 0, 0
    with path.open("x", encoding="utf-8") if path is not None else nullcontext() as log:
        for index, (first, second) in enumerate(zip(x0, x1, strict=True)):
            raw = np.stack((first, second)).astype("<f8", copy=False).tobytes(order="C")
            public_digest = hashlib.sha256(raw).hexdigest()
            request = dict(
                case=f"{case_prefix}:{index:08d}", readback_digest=public_digest,
                features_q24=np.rint((2 * first - 1) * Q24).astype(np.int64).tolist(),
                next_features_q24=np.rint((2 * second - 1) * Q24).astype(np.int64).tolist(),
                reset_before_readout=reset,
            )
            receipt = bridge.tick_pair(**request)
            if receipt["case"] != request["case"] or receipt["original_sparse_tick_calls"] != 2:
                raise RuntimeError("Native execution did not match the requested two-event case")
            successor = receipt["ticks"][1]
            state = np.asarray(successor["activation_q24"] + successor["eligibility_q24"], dtype=np.float64)
            if state.shape != (FEATURE_WIDTH,) or not np.isfinite(state).all():
                raise RuntimeError("Native successor feature shape or value mismatch")
            if any(tick["authority"] != "DENY_ALL" or not tick["requires_calibration"]
                   for tick in receipt["ticks"]):
                raise RuntimeError("Native state feature extraction changed authority")
            result[index] = state / Q24
            native_ns += sum(tick["native_ns"] for tick in receipt["ticks"])
            roundtrip_ns += receipt["bridge_roundtrip_ns"]
            tick_calls += receipt["original_sparse_tick_calls"]
            if log is not None:
                log.write(json.dumps({
                    "schema": "hepta.field-bridge.public-feature-receipt.v1",
                    "case_index": index, "public_feature_sha256": public_digest,
                    "public_feature_byte_encoding": "2x8 little-endian float64 row-major, first then second",
                    "request": request, "native": receipt,
                }, sort_keys=True, allow_nan=False) + "\n")
    summary = dict(
        schema="hepta.field-bridge.native-feature-batch.v1", rows=len(x0), feature_width=FEATURE_WIDTH,
        original_sparse_tick_calls=tick_calls, native_ns=native_ns, bridge_roundtrip_ns=roundtrip_ns,
        feature_batch_wall_ns=time.perf_counter_ns() - started,
        feature_batch_python_cpu_ns=time.process_time_ns() - cpu_started,
        reset_before_readout=reset, target_accesses=0, authority="DENY_ALL",
        native_owner_integration=False,
        feature_matrix_sha256=hashlib.sha256(result.astype("<f8", copy=False).tobytes()).hexdigest(),
    )
    bridge.last_feature_batch = summary
    if summary_path is not None:
        with summary_path.open("x", encoding="utf-8") as destination:
            json.dump(summary, destination, indent=2, sort_keys=True, allow_nan=False)
            destination.write("\n")
    return result


def history_features(x0, x1):
    """Matched 40-dimensional deterministic features retaining both raw events."""
    x0, x1 = _observations(x0, x1)
    return np.concatenate((x0, x1, x0 * x0, x1 * x1, x1 - x0), axis=1)


def choose(model, X):
    """Select only from frozen features/model; exact ties choose the lowest index."""
    X = _matrix(X, "runtime features", FEATURE_WIDTH)
    if model.get("schema") != "hepta.field-bridge.ridge-readout.v1":
        raise ValueError("Unknown frozen readout schema")
    coefficient = np.asarray(model["coefficient"], dtype=np.float64)
    mean = np.asarray(model["normalizer"]["mean"], dtype=np.float64)
    scale = np.asarray(model["normalizer"]["scale"], dtype=np.float64)
    if (coefficient.shape != (FEATURE_WIDTH + 1, ACTION_COUNT)
            or mean.shape != (FEATURE_WIDTH,) or scale.shape != (FEATURE_WIDTH,)
            or not np.isfinite(coefficient).all() or not np.isfinite(mean).all()
            or not np.isfinite(scale).all() or np.any(scale < STD_FLOOR)):
        raise ValueError("Frozen readout has invalid coefficients or normalizer")
    standardized = (X - mean) / scale
    prediction = standardized @ coefficient[:-1] + coefficient[-1]
    if not np.isfinite(prediction).all():
        raise ValueError("Frozen readout produced non-finite predictions")
    return np.argmax(prediction, axis=1).astype(np.int64)


def fit_readout(train_X, train_action_returns, dev_X, dev_returns):
    """Fit 41 x 5 ridge heads on training rows; choose alpha by dev net return.

    Normalization uses training rows only. The intercept is unpenalized. Each
    alpha sees exactly the same training rows and development action-return
    matrix. A tied dev mean selects the first prespecified alpha; the chosen
    model is not refitted on development or test examples.
    """
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    train_X = _matrix(train_X, "training features", FEATURE_WIDTH)
    train_action_returns = _matrix(train_action_returns, "training action returns", ACTION_COUNT)
    dev_X = _matrix(dev_X, "development features", FEATURE_WIDTH)
    dev_returns = _matrix(dev_returns, "development action returns", ACTION_COUNT)
    if len(train_X) != len(train_action_returns) or len(dev_X) != len(dev_returns):
        raise ValueError("Feature rows and supplied action-return rows do not align")
    mean = train_X.mean(axis=0)
    scale = np.maximum(train_X.std(axis=0, ddof=0), STD_FLOOR)
    normalized = (train_X - mean) / scale
    augmented = np.column_stack((normalized, np.ones(len(train_X))))
    penalty = np.diag(np.r_[np.ones(FEATURE_WIDTH), 0.0])
    gram, cross = augmented.T @ augmented, augmented.T @ train_action_returns
    if not all(np.isfinite(value).all() for value in (mean, scale, gram, cross)):
        raise ValueError("Training statistics overflowed")
    best, best_value, candidates = None, -np.inf, []
    dev_oracle = float(dev_returns.max(axis=1).mean())
    for alpha in ALPHAS:
        alpha_started = time.perf_counter_ns()
        coefficient = np.linalg.solve(gram + alpha * penalty, cross)
        if not np.isfinite(coefficient).all():
            raise ValueError("Ridge coefficients are not finite")
        model = dict(
            schema="hepta.field-bridge.ridge-readout.v1", coefficient=coefficient.tolist(),
            normalizer=dict(mean=mean.tolist(), scale=scale.tolist(), std_floor=STD_FLOOR,
                            fit_scope="training_rows_only", std_ddof=0),
            chosen_alpha=alpha, action_order=list(ACTION_ORDER), parameter_count=205,
            normalizer_statistic_count=80, intercept_penalized=False,
            argmax_tie_break="lowest_action_index", alpha_tie_break="first_prespecified_alpha",
        )
        dev_actions = choose(model, dev_X)
        training_actions = choose(model, train_X)
        dev_value = float(dev_returns[np.arange(len(dev_X)), dev_actions].mean())
        candidates.append(dict(
            alpha=alpha, dev_mean_net_return=dev_value,
            dev_oracle_mean_net_return=dev_oracle, dev_mean_regret=dev_oracle - dev_value,
            train_mean_net_return=float(train_action_returns[np.arange(len(train_X)), training_actions].mean()),
            train_return_regression_mse=float(np.mean((augmented @ coefficient - train_action_returns) ** 2)),
            fit_and_development_selection_wall_ns=time.perf_counter_ns() - alpha_started,
        ))
        if dev_value > best_value:
            best, best_value = model, dev_value
    best["metrics"] = dict(
        training_rows=len(train_X), development_rows=len(dev_X), candidates=candidates,
        selected_dev_mean_net_return=best_value, selected_dev_mean_regret=dev_oracle - best_value,
        fit_wall_ns=time.perf_counter_ns() - started, fit_python_cpu_ns=time.process_time_ns() - cpu_started,
        alpha_candidate_count=len(ALPHAS), training_fit_count=len(ALPHAS),
        fitting_scope="training_only; alpha_selection_development_only; no_refit",
        cost_handling="supplied_action_returns_already_net_of_fixed_action_costs",
        numpy_version=np.__version__,
    )
    # Round-trip guards the promised plain-JSON frozen model contract.
    return json.loads(json.dumps(best, allow_nan=False))

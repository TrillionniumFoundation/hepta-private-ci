"""Separately frozen H12 action-delta predictors with complete-trajectory cross-validation.

Only eight explicitly fitting trajectories may enter fit(). No audit argument
exists. Predicting uses frozen JSON arrays only and does not fit any statistic.
Set OPENBLAS_NUM_THREADS=1 before importing NumPy for the registered run budget.
"""

import hashlib
import json

import numpy as np

FIELD_WIDTH = 12
PROJECTION_SEED = 271030
STD_FLOOR = 1e-8
FEATURE_CLIP = 10.0
DELTA_LIMIT = 2.0
VALUE_BOUNDS = (-1.004, .998)
MODES = ("field", "generic", "richer")
CANDIDATES = ([dict(family="ridge", basis=basis, regularization=alpha)
               for basis in ("linear", "quadratic") for alpha in (.01, .1, 1., 10.)]
              + [dict(family="rbf", width=width, regularization=alpha)
                 for width in (.5, 1., 2.) for alpha in (.001, .01, .1, 1.)])


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _data(records):
    if not isinstance(records, list) or not records:
        raise ValueError("Supply a nonempty list of complete-branch fitting records")
    clean, keys = [], set()
    for record in records:
        if record.get("partition", "fit") != "fit" or record.get("role", "fit") != "fit":
            raise ValueError("Audit/test/retention records cannot enter fitting")
        trajectory, step = record["trajectory"], record["step"]
        if type(trajectory) not in (int, str) or type(step) is not int or step < 0:
            raise ValueError("Trajectory must be int/string and step a nonnegative integer")
        key = (json.dumps(trajectory), step)
        if key in keys:
            raise ValueError("Duplicate trajectory/step record")
        keys.add(key)
        state = np.asarray(record["state"], dtype=float)
        current = float(record["current_value"])
        actions = np.asarray(record["action_values"], dtype=float)
        if (state.ndim != 1 or len(state) < FIELD_WIDTH or actions.shape != (4,)
                or not np.isfinite(state).all() or not np.isfinite(actions).all() or not np.isfinite(current)):
            raise ValueError("Invalid rich state, current value, or four-action outcome vector")
        if abs(state[0] - current) > 1e-12 or abs(actions[0] - current) > 1e-12:
            raise ValueError("Current field value and no-change action must match current_value")
        clean.append(dict(trajectory=trajectory, step=step, state=state.tolist(), current_value=current,
                          action_values=actions.tolist(), partition="fit"))
    dimensions = {len(r["state"]) for r in clean}
    trajectories = sorted({json.dumps(r["trajectory"]) for r in clean})
    if len(dimensions) != 1 or len(trajectories) != 8:
        raise ValueError("Fit requires one state width and exactly eight complete fitting trajectories")
    if trajectories != [json.dumps(i) for i in range(8)]:
        raise ValueError("Directional fitting accepts only inherited trajectories 0..7")
    raw = np.asarray([r["state"] for r in clean])
    current = np.asarray([r["current_value"] for r in clean])
    values = np.asarray([r["action_values"] for r in clean])
    return clean, raw, current, values, trajectories


def _projection(width, mode):
    if mode == "field":
        return np.eye(width, FIELD_WIDTH)
    if mode == "richer":
        return np.eye(width)
    if mode != "generic":
        raise ValueError("Unknown field predictor representation")
    raw = np.random.default_rng(PROJECTION_SEED).normal(size=(width, FIELD_WIDTH))
    projection, triangular = np.linalg.qr(raw, mode="reduced")
    # Canonical positive diagonal removes the QR sign ambiguity.
    signs = np.where(np.diag(triangular) < 0, -1., 1.)
    return projection * signs


def _normalizer(raw):
    return dict(mean=raw.mean(axis=0).tolist(), scale=np.maximum(raw.std(axis=0), STD_FLOOR).tolist())


def _transform(raw, normalizer, projection):
    standardized = np.clip((raw - normalizer["mean"]) / normalizer["scale"], -FEATURE_CLIP, FEATURE_CLIP)
    return np.clip(standardized @ projection, -FEATURE_CLIP, FEATURE_CLIP)


def _basis(x, family):
    if family == "linear":
        return x
    if family != "quadratic":
        raise ValueError("Unknown ridge basis")
    left, right = np.triu_indices(x.shape[1])
    return np.column_stack((x, x[:, left] * x[:, right]))


def _kernel(x, y, width):
    distance = np.maximum((x * x).sum(1)[:, None] + (y * y).sum(1)[None, :] - 2 * x @ y.T, 0.)
    return np.exp(-distance / (2 * width * width * x.shape[1]))


def _fit_family(x, target, candidate):
    mean = target.mean(axis=0)
    centered_target = target - mean
    alpha = candidate["regularization"]
    if candidate["family"] == "ridge":
        basis = _basis(x, candidate["basis"])
        basis_mean = basis.mean(axis=0)
        centered = basis - basis_mean
        if centered.shape[1] <= len(centered):
            coefficient = np.linalg.solve(centered.T @ centered + alpha * np.eye(centered.shape[1]),
                                          centered.T @ centered_target)
        else:
            coefficient = centered.T @ np.linalg.solve(centered @ centered.T + alpha * np.eye(len(centered)),
                                                       centered_target)
        result = dict(target_mean=mean.tolist(), basis_mean=basis_mean.tolist(), coefficient=coefficient.tolist())
    else:
        kernel = _kernel(x, x, candidate["width"])
        column_mean = kernel.mean(axis=0)
        grand_mean = float(kernel.mean())
        centered = kernel - column_mean[None, :] - column_mean[:, None] + grand_mean
        coefficient = np.linalg.solve(centered + alpha * np.eye(len(x)), centered_target)
        result = dict(target_mean=mean.tolist(), centers=x.tolist(), kernel_column_mean=column_mean.tolist(),
                      kernel_grand_mean=grand_mean, coefficient=coefficient.tolist())
    if not np.isfinite(np.asarray(result["coefficient"])).all():
        raise FloatingPointError("Nonfinite fitted coefficient")
    return result


def _predict_delta(x, fitted, candidate):
    coefficient = np.asarray(fitted["coefficient"])
    if candidate["family"] == "ridge":
        centered = _basis(x, candidate["basis"]) - fitted["basis_mean"]
    else:
        kernel = _kernel(x, np.asarray(fitted["centers"]), candidate["width"])
        centered = (kernel - kernel.mean(axis=1)[:, None] - fitted["kernel_column_mean"]
                    + fitted["kernel_grand_mean"])
    return np.clip(centered @ coefficient + fitted["target_mean"], -DELTA_LIMIT, DELTA_LIMIT)


def _absolute(delta, current):
    values = np.clip(current[:, None] + delta, *VALUE_BOUNDS)
    return np.column_stack((current, values))


def fit(records, mode):
    """Fit one representation using the identical 20-candidate/8-fold budget.

    Validation MSE averages the three nonzero action delta errors within each
    held-out trajectory, then averages the eight trajectories equally. Action 0
    is an exact identity and is excluded from model selection error. Candidate
    ties select the first listed candidate. No validation data is refitted into
    a fold normalizer. The chosen candidate is finally fit on the eight fitting
    trajectories only; future audit trajectories are not accepted by this API.
    """
    clean, raw, current, values, trajectories = _data(records)
    projection = _projection(raw.shape[1], mode)
    target = values[:, 1:] - current[:, None]
    row_hashes = [content_hash(r) for r in clean]
    groups = np.asarray([json.dumps(r["trajectory"]) for r in clean])
    folds, cache = [], []
    for trajectory in trajectories:
        train, held = np.flatnonzero(groups != trajectory), np.flatnonzero(groups == trajectory)
        normalizer = _normalizer(raw[train])
        cache.append((_transform(raw[train], normalizer, projection), target[train],
                      _transform(raw[held], normalizer, projection), current[held], values[held]))
        folds.append(dict(heldout_trajectory=json.loads(trajectory), train_indices=train.tolist(),
                          heldout_indices=held.tolist(), normalizer=normalizer,
                          train_record_sha256=[row_hashes[i] for i in train],
                          heldout_record_sha256=[row_hashes[i] for i in held]))
    candidates = []
    for index, candidate in enumerate(CANDIDATES):
        errors = []
        for train_x, train_y, held_x, held_current, held_values in cache:
            fitted = _fit_family(train_x, train_y, candidate)
            prediction = _absolute(_predict_delta(held_x, fitted, candidate), held_current)
            errors.append(float(np.mean((prediction[:, 1:] - held_values[:, 1:]) ** 2)))
        candidates.append(dict(index=index, **candidate, trajectory_mse=errors, mean_mse=float(np.mean(errors))))
    selected = min(range(len(candidates)), key=lambda index: (candidates[index]["mean_mse"], index))
    normalizer = _normalizer(raw)
    candidate = CANDIDATES[selected]
    fitted = _fit_family(_transform(raw, normalizer, projection), target, candidate)
    controller = dict(schema="hepta.field-bridge-v2.directional-delta-value-controller.v1", mode=mode,
                      input_width=raw.shape[1], representation_width=projection.shape[1],
                      observation_order="original H7, five directional features, remaining original 18 rich features",
                      normalizer=normalizer, projection=projection.tolist(), projection_seed=PROJECTION_SEED,
                      selected_index=selected, selected_candidate=candidate, fitted=fitted,
                      cv=dict(candidates=candidates, folds=folds, candidate_count=20, trajectory_fold_count=8,
                              candidate_fold_fits=160, final_refits=1, tie_break="first_listed_candidate",
                              loss="mean three nonzero-action delta squared errors; equal trajectory weighting"),
                      fit_row_count=len(clean), fit_trajectories=[json.loads(t) for t in trajectories],
                      fit_record_sha256=row_hashes, fit_content_sha256=content_hash(clean),
                      fit_partition="fit_only", normalization="raw train-fold mean/std; ddof0; before representation",
                      transform_clip="raw standardized coordinates then projected coordinates, both [-10,10]",
                      std_floor=STD_FLOOR, feature_clip=FEATURE_CLIP, delta_clip=[-DELTA_LIMIT, DELTA_LIMIT],
                      value_bounds=list(VALUE_BOUNDS), no_change_action=0, no_change_exact=True,
                      kernel_definition="exp(-squared Euclidean distance/(2*width^2*representation_width))",
                      quadratic_definition="linear terms followed by x_i*x_j for row-major i<=j",
                      regularization="unscaled positive lambda; unpenalized centered intercept",
                      scientific_interpretation="empirical complete-branch delta model; no field sufficiency theorem")
    return json.loads(json.dumps(controller, allow_nan=False))


def predict(controller, raw, current_value):
    """Return four frozen predicted absolute values; action zero is exact current."""
    if controller.get("schema") != "hepta.field-bridge-v2.directional-delta-value-controller.v1":
        raise ValueError("Unknown frozen field controller schema")
    if (controller.get("value_bounds") != list(VALUE_BOUNDS)
            or controller.get("delta_clip") != [-DELTA_LIMIT, DELTA_LIMIT]
            or controller.get("feature_clip") != FEATURE_CLIP):
        raise ValueError("Frozen prediction rule differs from registered bounds")
    raw = np.asarray(raw, dtype=float)
    current = float(current_value)
    if raw.shape != (controller["input_width"],) or not np.isfinite(raw).all() or not np.isfinite(current):
        raise ValueError("Invalid frozen predictor input")
    if abs(raw[0] - current) > 1e-12:
        raise ValueError("First field coordinate must match the supplied current value")
    features = _transform(raw[None, :], controller["normalizer"], np.asarray(controller["projection"]))
    delta = _predict_delta(features, controller["fitted"], controller["selected_candidate"])
    result = _absolute(delta, np.asarray([current]))[0]
    if not np.isfinite(result).all():
        raise FloatingPointError("Frozen value prediction is nonfinite")
    return result.tolist()

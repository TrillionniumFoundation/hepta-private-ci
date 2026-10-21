"""Independent evaluation of the four *generated* raw output modalities.

The evaluator never renders an output or consumes a controller risk estimate.
Canonical prototypes and truth are evaluator-only data at inference time.  The
primary loss and ambiguity threshold are fixed before held-out evaluation.
"""

from collections.abc import Mapping

import numpy as np


MODALITIES = ("text", "audio", "image", "video")
CLASS_COUNT = 8
RAW_ERROR_CAP = 2.0
CONTRADICTION_WEIGHT = 0.25
OMISSION_MARGIN = 0.1


def _finite_array(value, name):
    source = np.asarray(value)
    if not np.issubdtype(source.dtype, np.number) or np.iscomplexobj(source):
        raise ValueError(f"{name} must contain real numeric values")
    result = np.asarray(source, dtype=np.float64)
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} contains non-finite values")
    return result


def _check_modalities(value, name):
    if not isinstance(value, Mapping) or set(value) != set(MODALITIES):
        raise ValueError(f"{name} must contain exactly {MODALITIES}")


def _squared_distances(values, prototypes):
    # Eight per-prototype operations avoid an [world, class, feature] temporary.
    # Direct differences also avoid cancellation for exact reconstructions.
    with np.errstate(over="ignore", invalid="ignore"):
        distances = np.column_stack(
            [np.mean(np.square(values - prototype), axis=1)
             for prototype in prototypes]
        )
    if not np.all(np.isfinite(distances)):
        raise ValueError("generated/prototype squared distances are non-finite")
    return distances


def score_outputs(outputs: dict, truth: np.ndarray, canonical: dict) -> dict:
    """Return one value per world for independently scored raw generations.

    Every modality must have shape [world, feature], with eight canonical class
    prototypes of the same feature dimension.  Class IDs are evaluator truth,
    never probabilities supplied by the generation controller.

    ``raw_error`` is the mean over modalities of true-prototype MSE divided by
    the mean MSE between distinct prototype *indices*, then clipped to [0, 2].
    ``loss = raw_error + 0.25 * contradiction``.  ``quality`` and its explicit
    alias ``correct_fraction`` are the fraction of modalities whose nearest
    prototype has the correct joint semantic class.  ``class_error`` measures
    the corresponding discrete joint-attribute error.

    ``contradiction`` is the fraction of the six modality pairs whose nearest
    classes disagree.  Consistently wrong outputs therefore incur raw/class
    error even when contradiction is zero.

    ``omission`` is an ambiguity proxy: the fraction of modalities with a gap
    below 0.1 between the smallest two normalized prototype distances.  It is
    not an actual decoder abstention and does not alter the frozen loss.
    ``resolved_correct_fraction`` additionally requires this margin to pass;
    it exposes accidental correct predictions from ties in nearest-class
    scoring.  Ties use NumPy's deterministic first-index rule.
    """
    _check_modalities(outputs, "outputs")
    _check_modalities(canonical, "canonical")
    truth = np.asarray(truth)
    if truth.ndim != 1 or truth.size == 0:
        raise ValueError("truth must be a nonempty one-dimensional array")
    if not np.issubdtype(truth.dtype, np.integer):
        raise ValueError("truth must contain integer class IDs")
    if np.any(truth < 0) or np.any(truth >= CLASS_COUNT):
        raise ValueError("truth class IDs must be in [0, 7]")

    count = truth.size
    raw_errors = []
    predictions = []
    omissions = []
    off_diagonal = ~np.eye(CLASS_COUNT, dtype=bool)
    for modality in MODALITIES:
        generated = _finite_array(outputs[modality], f"outputs[{modality}]")
        prototypes = _finite_array(canonical[modality], f"canonical[{modality}]")
        if prototypes.ndim != 2 or prototypes.shape[0] != CLASS_COUNT:
            raise ValueError(f"canonical[{modality}] must have shape [8, feature]")
        if prototypes.shape[1] == 0:
            raise ValueError(f"canonical[{modality}] has no features")
        if generated.shape != (count, prototypes.shape[1]):
            raise ValueError(f"outputs[{modality}] has incompatible shape")
        prototype_distances = _squared_distances(prototypes, prototypes)
        normalizer = float(prototype_distances[off_diagonal].mean())
        if normalizer <= 0:
            raise ValueError(f"canonical[{modality}] has no semantic variation")
        distances = _squared_distances(generated, prototypes) / normalizer
        raw_errors.append(
            np.minimum(distances[np.arange(count), truth], RAW_ERROR_CAP)
        )
        predictions.append(np.argmin(distances, axis=1))
        nearest_two = np.partition(distances, 1, axis=1)[:, :2]
        margin = nearest_two[:, 1] - nearest_two[:, 0]
        omissions.append(margin < OMISSION_MARGIN)

    predicted_class = np.column_stack(predictions)
    omitted = np.column_stack(omissions)
    correct = predicted_class == truth[:, None]
    quality = correct.mean(axis=1)
    # The world contract fixes class = 2 * color + direction.  These report
    # partial attribute correctness without changing joint-class quality.
    color_accuracy = (predicted_class // 2 == truth[:, None] // 2).mean(axis=1)
    direction_accuracy = (predicted_class % 2 == truth[:, None] % 2).mean(axis=1)
    raw_error = np.column_stack(raw_errors).mean(axis=1)
    pairwise_disagreements = [
        predicted_class[:, left] != predicted_class[:, right]
        for left in range(len(MODALITIES))
        for right in range(left + 1, len(MODALITIES))
    ]
    contradiction = np.column_stack(pairwise_disagreements).mean(axis=1)
    return {
        "loss": raw_error + CONTRADICTION_WEIGHT * contradiction,
        "quality": quality,
        "correct_fraction": quality.copy(),
        "class_error": 1.0 - quality,
        "color_accuracy": color_accuracy,
        "direction_accuracy": direction_accuracy,
        "attribute_accuracy": (color_accuracy + direction_accuracy) / 2.0,
        "contradiction": contradiction,
        "raw_error": raw_error,
        "omission": omitted.mean(axis=1),
        "resolved_correct_fraction": (correct & ~omitted).mean(axis=1),
    }


def _cvar_rows(values, alpha):
    # Empirical probability mass is 1/n per observation.  The boundary sample
    # contributes only the fraction needed to complete the worst (1-alpha).
    ordered = np.sort(values, axis=1)[:, ::-1]
    tail_mass = (1.0 - alpha) * ordered.shape[1]
    whole = int(np.floor(tail_mass))
    fraction = tail_mass - whole
    tail_sum = ordered[:, :whole].sum(axis=1)
    if whole < ordered.shape[1]:
        tail_sum = tail_sum + fraction * ordered[:, whole]
    return tail_sum / tail_mass


def cvar(values, alpha=0.9):
    """Empirical upper-tail CVaR with exact fractional-boundary weighting."""
    values = _finite_array(values, "values")
    if values.ndim != 1 or values.size == 0:
        raise ValueError("CVaR requires a nonempty one-dimensional array")
    if not np.isfinite(alpha) or not 0.0 <= alpha < 1.0:
        raise ValueError("alpha must satisfy 0 <= alpha < 1")
    return float(_cvar_rows(values[None, :], alpha)[0])


def summarize(scores: dict) -> dict:
    """Summarize worlds from one training seed; do not pool seeds silently."""
    required = {"loss", "quality", "contradiction", "raw_error"}
    if not isinstance(scores, Mapping) or not required.issubset(scores):
        raise ValueError(f"scores must include {sorted(required)}")
    arrays = {name: _finite_array(value, name) for name, value in scores.items()}
    count = arrays["loss"].size
    if count == 0 or any(value.shape != (count,) for value in arrays.values()):
        raise ValueError("scores must be nonempty one-dimensional arrays of equal length")
    result = {f"mean_{name}": float(value.mean()) for name, value in arrays.items()}
    result.update({"n": int(count), "cvar90": cvar(arrays["loss"], alpha=0.9)})
    return result


def paired_bootstrap(
    candidate,
    baseline,
    statistic="mean",
    seed=0,
    replicates=2000,
    shared_worlds=True,
    confidence=0.95,
):
    """Paired seed/world bootstrap for arrays shaped [training seed, world].

    The estimate is the mean of the per-seed candidate-minus-baseline
    statistics.  The two arms retain identical sampled seed/world indices.
    If the same worlds are evaluated under every seed, ``shared_worlds=True``
    resamples one common world-index vector and a seed-index vector per
    replicate (a crossed two-way bootstrap).  Set it to False only when each
    seed has its own independent world set; worlds are then resampled within
    each sampled seed.  For ``cvar90``, tail loss is calculated separately for
    each seed before averaging, never by silently pooling training runs.

    These are percentile intervals, not a test of a global efficient frontier.
    With only three training seeds they provide limited evidence about
    training variability, regardless of the number of worlds or replicates.
    """
    candidate = _finite_array(candidate, "candidate")
    baseline = _finite_array(baseline, "baseline")
    if candidate.ndim != 2 or candidate.shape != baseline.shape:
        raise ValueError("candidate and baseline must share shape [seed, world]")
    seed_count, world_count = candidate.shape
    if seed_count == 0 or world_count == 0:
        raise ValueError("bootstrap arrays must contain at least one seed and world")
    if statistic not in ("mean", "cvar90"):
        raise ValueError("statistic must be 'mean' or 'cvar90'")
    if isinstance(replicates, bool) or not isinstance(replicates, (int, np.integer)):
        raise ValueError("replicates must be an integer")
    if replicates < 2:
        raise ValueError("replicates must be at least two")
    if not np.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must satisfy 0 < confidence < 1")
    if not isinstance(shared_worlds, (bool, np.bool_)):
        raise ValueError("shared_worlds must be a boolean")

    def row_statistic(values):
        if statistic == "mean":
            return values.mean(axis=1)
        return _cvar_rows(values, 0.9)

    estimate = float((row_statistic(candidate) - row_statistic(baseline)).mean())
    rng = np.random.default_rng(seed)
    sampled_differences = np.empty(replicates, dtype=np.float64)
    for iteration in range(replicates):
        sampled_seeds = rng.integers(seed_count, size=seed_count)
        if shared_worlds:
            sampled_worlds = rng.integers(world_count, size=world_count)[None, :]
        else:
            sampled_worlds = rng.integers(world_count, size=(seed_count, world_count))
        left = candidate[sampled_seeds[:, None], sampled_worlds]
        right = baseline[sampled_seeds[:, None], sampled_worlds]
        sampled_differences[iteration] = (
            row_statistic(left) - row_statistic(right)
        ).mean()
    tail = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(sampled_differences, [tail, 1.0 - tail])
    return {
        "statistic": statistic,
        "estimate": estimate,
        "ci_low": float(lower),
        "ci_high": float(upper),
        "confidence": float(confidence),
        "n_seeds": int(seed_count),
        "n_worlds_per_seed": int(world_count),
        "bootstrap_replicates": int(replicates),
        "shared_worlds": bool(shared_worlds),
    }

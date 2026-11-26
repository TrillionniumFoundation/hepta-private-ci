"""Common-parent sufficient equations for a bounded first-order research step.

The caller authenticates peers. Content hashes bind bytes and replay identity;
they do not prove honest data, independent people, privacy, or adoption rights.
"""
import math
import re

import numpy as np

from profile_io import canonical, digest, fields, require, sha

COMMON_SCHEMA = "hepta.smallhcsn.common-linearization.v1"
CONTRIBUTION_SCHEMA = "hepta.smallhcsn.normal-equation-contribution.v1"
OBJECTIVE = "sum of half weighted residual squares; alpha-coordinate ridge applied once globally"
SHARED_FIELDS = ("parent_state_sha256", "coordinate_sha256", "coordinate_layout",
                 "objective_state", "output", "derivative", "second_order_autograd")
MAX_BYTES = 128 * 1024


def _array(value):
    result = np.asarray(value, dtype=np.float64)
    require(bool(np.isfinite(result).all()), "finite numerical array required")
    return result


def _geometry(gram, moment, square, observation_count):
    """Check diagonally equilibrated geometry without spectral projection.

    Congruence scaling preserves PSD and rank while separating feature and
    residual energy scales. Unresolved ranges or underflow are refused.
    """
    dimension = len(moment)
    require(square != 0 or not bool(np.any(moment)),
            "zero residual energy requires a zero moment")
    require(bool(np.any(gram)) or not bool(np.any(moment)),
            "zero Gram requires a zero moment")
    joint = np.block([[gram, moment[:, None]], [moment[None, :], np.array([[square]])]])
    diagonal = np.diag(joint)
    require(bool((diagonal >= 0).all()),
            "invalid sufficient-equation geometry: negative diagonal (not positive definite or semidefinite)")
    zero = diagonal == 0
    require(not bool(np.any(joint[zero, :])) and not bool(np.any(joint[:, zero])),
            "invalid sufficient-equation range: zero diagonal requires a zero row and column")
    active = np.flatnonzero(~zero)
    if not len(active):
        return
    try:
        roots = np.sqrt(diagonal[active])
        block = joint[np.ix_(active, active)]
        larger = np.maximum(roots[:, None], roots[None, :])
        smaller = np.minimum(roots[:, None], roots[None, :])
        with np.errstate(over="raise", invalid="raise", divide="raise", under="ignore"):
            intermediate = block / larger
            normalized = intermediate / smaller
        require(not bool(np.any((block != 0) & (intermediate == 0)))
                and not bool(np.any((intermediate != 0) & (normalized == 0))),
                "sufficient-equation congruence underflow is numerically unresolved")
        require(bool(np.isfinite(normalized).all()), "nonfinite sufficient-equation correlation")
        entry_tolerance = 64 * np.finfo(float).eps * len(active)
        require(bool((np.abs(normalized) <= 1. + entry_tolerance).all()),
                "invalid sufficient-equation geometry: Cauchy-Schwarz bound")
        symmetric = .5 * normalized + .5 * normalized.T
        norm = float(np.linalg.norm(symmetric, ord=2))
        tolerance = 64 * np.finfo(float).eps * len(active) * norm
        eigenvalues = np.linalg.eigvalsh(symmetric)
        require(float(np.max(np.abs(normalized - normalized.T))) <= tolerance
                and float(eigenvalues.min()) >= -tolerance
                and int(np.count_nonzero(eigenvalues > tolerance)) <= observation_count,
                "invalid sufficient-equation geometry")
        gram_indices = np.flatnonzero(active < dimension)
        if len(gram_indices):
            local = symmetric[np.ix_(gram_indices, gram_indices)]
            values, vectors = np.linalg.eigh(local)
            threshold = (64 * np.finfo(float).eps * len(gram_indices)
                         * float(np.max(np.abs(values))))
            require(float(values.min()) >= -threshold,
                    "invalid sufficient-equation Gram geometry")
            if square > 0:
                standardized_moment = normalized[gram_indices, -1]
                moment_scale = float(np.max(np.abs(standardized_moment)))
                if moment_scale:
                    null = vectors[:, values <= threshold]
                    direction = standardized_moment / moment_scale
                    range_error = float(np.linalg.norm(null.T @ direction))
                    range_tolerance = (64 * np.finfo(float).eps * len(gram_indices)
                                       * float(np.linalg.norm(direction)))
                    require(range_error <= range_tolerance,
                            "moment outside numerically resolved Gram range")
    except (FloatingPointError, np.linalg.LinAlgError) as error:
        raise ValueError("sufficient-equation geometry is numerically unresolved") from error


def _solve_and_measure(gram, moment, square, ridge):
    """Solve the same quadratic only when its FP64 geometry is resolved.

    Symmetrization removes the skew part, which contributes zero to the
    quadratic. No eigenvalue is clipped and no objective coefficient changes.
    """
    dimension = len(moment)
    require(bool(np.isfinite(gram).all() and np.isfinite(moment).all())
            and math.isfinite(square), "nonfinite aggregate sufficient equations")
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            symmetric = .5 * gram + .5 * gram.T
            operator = symmetric + ridge * np.eye(dimension)
            require(bool(np.isfinite(operator).all()), "nonfinite regularized operator")
            scale = float(np.max(np.abs(operator)))
            require(scale > 0, "zero regularized operator")
            normalized = operator / scale
            values = np.linalg.eigvalsh(normalized)
            spectral_floor = 64 * np.finfo(float).eps * dimension * float(np.max(np.abs(values)))
            require(float(values.min()) > spectral_floor,
                    "regularized operator is not reliably positive definite")
            factor = np.linalg.cholesky(normalized)
            right = moment / scale
            delta = np.linalg.solve(factor.T, np.linalg.solve(factor, right))
            require(bool(np.isfinite(right).all() and np.isfinite(delta).all()),
                    "nonfinite peer normal-equation solution")
            error_norm = math.hypot(*(normalized @ delta - right))
            right_norm = math.hypot(*right)
            require(math.isfinite(error_norm) and math.isfinite(right_norm),
                    "unrepresentable normal-equation residual")
            # Algebraically the original ||A delta-b|| / max(1, ||b||),
            # without squaring large entries or forming an overflowing 1/scale.
            residual = (error_norm / max(1. / scale, right_norm) if scale >= 1.
                        else (scale * error_norm) / max(1., scale * right_norm))
            require(math.isfinite(residual) and residual <= 1e-10,
                    "peer normal-equation solve failed its fixed residual gate")
            gram_scale = float(np.max(np.abs(symmetric)))
            if gram_scale:
                normalized_eigenvalues = np.linalg.eigvalsh(symmetric / gram_scale)
                rank_tolerance = 64 * np.finfo(float).eps * dimension * max(0., float(normalized_eigenvalues[-1]))
                rank = int(np.count_nonzero(normalized_eigenvalues > rank_tolerance))
                eigenvalues = normalized_eigenvalues * gram_scale
                tolerance = rank_tolerance * gram_scale
            else:
                eigenvalues, tolerance, rank = np.zeros(dimension), 0., 0
            objective_scale = max(gram_scale, float(np.max(np.abs(moment))), square, ridge)
            scaled_gram = symmetric / objective_scale
            scaled_moment = moment / objective_scale
            constant, scaled_ridge = square / objective_scale, ridge / objective_scale
            require(not bool(np.any((symmetric != 0) & (scaled_gram == 0)))
                    and not bool(np.any((moment != 0) & (scaled_moment == 0)))
                    and (square == 0 or constant != 0) and scaled_ridge > 0,
                    "quadratic objective coefficient normalization underflow")
            quadratic = float(delta @ scaled_gram @ delta)
            linear = float(delta @ scaled_moment)
            data_normalized = .5 * math.fsum((quadratic, -2 * linear, constant))
            regularized_delta = math.sqrt(scaled_ridge) * delta
            require(not bool(np.any((delta != 0) & (regularized_delta == 0))),
                    "quadratic ridge-factor underflow")
            penalty_normalized = .5 * float(regularized_delta @ regularized_delta)
            require(penalty_normalized > 0 or not bool(np.any(delta)),
                    "quadratic ridge-energy underflow")
            regularized_normalized = data_normalized + penalty_normalized
            objective_tolerance = (128 * np.finfo(float).eps * dimension
                * math.fsum((abs(quadratic), 2 * abs(linear), abs(constant), penalty_normalized)))
            require(data_normalized >= 0 and regularized_normalized >= 0
                    and regularized_normalized <= .5 * constant + objective_tolerance,
                    "quadratic objective is negative or its minimum is numerically unresolved")
            require(data_normalized > 0 or not bool(np.any(delta)),
                    "zero quadratic residual at a nonzero ridge solution is numerically unresolved")
            data_objective = data_normalized * objective_scale
            regularized_objective = regularized_normalized * objective_scale
            require((data_normalized == 0 or data_objective > 0)
                    and (regularized_normalized == 0 or regularized_objective > 0),
                    "quadratic objective restoration underflow")
            require(bool(np.isfinite(eigenvalues).all()) and math.isfinite(tolerance)
                    and all(math.isfinite(value) for value in
                            (objective_tolerance, data_objective, regularized_objective)),
                    "nonfinite aggregate diagnostics or objective")
    except (FloatingPointError, OverflowError, np.linalg.LinAlgError) as error:
        raise ValueError("aggregate quadratic solve is numerically unresolved") from error
    return delta, residual, eigenvalues, tolerance, rank, data_objective, regularized_objective


def _common(common):
    fields(common, ("schema", "round", "roster", "profile_sha256", "candidate_sha256",
                    "source_binding_sha256", "runtime", "linearization", "objective", "ridge"),
           "common linearization")
    require(common["schema"] == COMMON_SCHEMA and common["objective"] == OBJECTIVE,
            "unsupported shared objective")
    require(isinstance(common["round"], str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", common["round"]),
            "bounded round identifier required")
    roster = common["roster"]
    require(isinstance(roster, list) and 2 <= len(roster) <= 16
            and all(isinstance(n, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", n) for n in roster)
            and roster == sorted(set(roster)), "canonical frozen peer roster required")
    for key in ("profile_sha256", "candidate_sha256", "source_binding_sha256"):
        digest(common[key])
    shared = common["linearization"]
    fields(shared, SHARED_FIELDS, "shared derivative semantics")
    for key in ("parent_state_sha256", "coordinate_sha256"):
        digest(shared[key])
    require(1 <= len(shared["coordinate_layout"]) <= 32
            and sha(canonical(shared["coordinate_layout"])) == shared["coordinate_sha256"],
            "shared coordinate layout differs")
    require(shared["second_order_autograd"] is False, "first-order equations required")
    require(type(common["ridge"]) in (int, float) and math.isfinite(common["ridge"])
            and common["ridge"] > 0, "this peer solver requires positive finite global ridge")
    require(len(canonical(common)) <= MAX_BYTES, "common metadata bound")
    return len(shared["coordinate_layout"])


def common_problem(profile, linearization, *, round_id, roster, ridge):
    """Freeze common physical, coordinate, runtime, and objective identities."""
    profile.require_frozen()
    metadata = linearization.metadata
    require(metadata["parent_state_sha256"] == profile.model_state_sha256,
            "linearization differs from frozen profile")
    result = {
        "schema": COMMON_SCHEMA, "round": round_id, "roster": sorted(roster),
        "profile_sha256": profile.profile_sha256, "candidate_sha256": profile.candidate_sha256,
        "source_binding_sha256": profile.source_binding_sha256,
        "runtime": dict(profile.manifest["runtime"]),
        "linearization": {key: metadata[key] for key in SHARED_FIELDS},
        "objective": OBJECTIVE, "ridge": ridge,
    }
    _common(result)
    return result


def contribute(common, linearization, targets, *, node, batch_sha256, observation_weights=None):
    """Return one unregularized G, b, c contribution for this frozen peer round."""
    dimension = _common(common)
    digest(batch_sha256)
    require(node in common["roster"], "peer outside frozen roster")
    metadata = linearization.metadata
    require({key: metadata[key] for key in SHARED_FIELDS} == common["linearization"],
            "incompatible parent, coordinates, output or derivative semantics")
    digest(metadata["linearization_sha256"])
    jacobian, base, target = map(_array, (linearization.jacobian, linearization.base_output, targets))
    require(base.ndim == 1 and 1 <= len(base) <= 64 and target.shape == base.shape
            and jacobian.shape == (len(base), dimension), "bounded local numerical system required")
    weights = np.ones(len(base)) if observation_weights is None else _array(observation_weights)
    require(weights.shape == base.shape and bool((weights > 0).all()), "positive observation weights required")
    operator = np.sqrt(weights)[:, None] * jacobian
    right = np.sqrt(weights) * (target - base)
    body = {
        "schema": CONTRIBUTION_SCHEMA, "common_sha256": sha(canonical(common)),
        "node": node, "batch_sha256": batch_sha256,
        "local_linearization_sha256": metadata["linearization_sha256"],
        "observation_count": len(base), "gram": (operator.T @ operator).tolist(),
        "moment": (operator.T @ right).tolist(), "residual_square": float(right @ right),
    }
    raw = canonical(body)
    require(len(raw) <= MAX_BYTES, "contribution byte bound")
    return {"body": body, "sha256": sha(raw)}


def solve_common(common, contributions):
    """Deterministically add peer equations; never average local parameter fits."""
    dimension = _common(common)
    require(isinstance(contributions, list) and len(contributions) == len(common["roster"]),
            "one contribution from every frozen peer required")
    common_sha256 = sha(canonical(common))
    validated, seen, batches = [], set(), set()
    for envelope in contributions:
        fields(envelope, ("body", "sha256"), "contribution envelope")
        body = envelope["body"]
        fields(body, ("schema", "common_sha256", "node", "batch_sha256", "local_linearization_sha256",
                      "observation_count", "gram", "moment", "residual_square"), "contribution")
        raw = canonical(body)
        require(len(raw) <= MAX_BYTES and sha(raw) == digest(envelope["sha256"]),
                "contribution bytes differ")
        require(body["schema"] == CONTRIBUTION_SCHEMA and body["common_sha256"] == common_sha256,
                "stale or incompatible shared round")
        node = body["node"]
        require(node in common["roster"] and node not in seen, "unknown or replayed peer")
        require(digest(body["batch_sha256"]) not in batches, "duplicate batch identity")
        digest(body["local_linearization_sha256"])
        require(type(body["observation_count"]) is int and 1 <= body["observation_count"] <= 64,
                "bounded observation count required")
        gram, moment = _array(body["gram"]), _array(body["moment"])
        square = body["residual_square"]
        require(gram.shape == (dimension, dimension) and moment.shape == (dimension,),
                "contribution dimensions differ")
        require(type(square) in (int, float) and math.isfinite(square) and square >= 0,
                "nonnegative finite residual square required")
        _geometry(gram, moment, square, body["observation_count"])
        seen.add(node)
        batches.add(body["batch_sha256"])
        validated.append((node, gram, moment, square, envelope))
    require(seen == set(common["roster"]), "incomplete peer set")
    gram, moment, square, count = np.zeros((dimension, dimension)), np.zeros(dimension), 0., 0
    receipts = []
    try:
        with np.errstate(over="raise", invalid="raise"):
            for node, local_gram, local_moment, local_square, envelope in sorted(validated, key=lambda row: row[0]):
                gram += local_gram
                moment += local_moment
                square += local_square
                count += envelope["body"]["observation_count"]
                receipts.append({"node": node, "sha256": envelope["sha256"]})
    except FloatingPointError as error:
        raise ValueError("aggregate sufficient equations overflow") from error
    delta, residual, eigenvalues, tolerance, rank, data_objective, regularized_objective = _solve_and_measure(
        gram, moment, square, common["ridge"])
    return {
        "schema": "hepta.smallhcsn.aggregate-step.v1", "common_sha256": common_sha256,
        "parent_state_sha256": common["linearization"]["parent_state_sha256"],
        "coordinate_sha256": common["linearization"]["coordinate_sha256"],
        "contributions": receipts, "observation_count": count, "delta": delta.tolist(),
        "ridge": common["ridge"], "ridge_applications": 1,
        "relative_normal_residual": residual, "gram_rank_estimate": rank,
        "gram_rank_tolerance": tolerance, "gram_eigenvalues": eigenvalues.tolist(),
        "rank_method": "Gram eigenvalues; less reliable than original-Jacobian SVD under ill conditioning",
        "objective_at_zero": .5 * square, "linearized_data_objective": data_objective,
        "regularized_objective": regularized_objective,
        "actual_nonlinear_improvement_measured": False, "production_adoption": False,
    }

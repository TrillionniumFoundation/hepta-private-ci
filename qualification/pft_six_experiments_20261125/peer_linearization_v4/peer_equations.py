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
        joint = np.block([[gram, moment[:, None]], [moment[None, :], np.array([[square]])]])
        tolerance = 64 * np.finfo(float).eps * (dimension + 1) * max(1., float(np.linalg.norm(joint, ord=2)))
        eigenvalues = np.linalg.eigvalsh((joint + joint.T) / 2)
        require(float(np.max(np.abs(gram - gram.T))) <= tolerance
                and float(eigenvalues.min()) >= -tolerance
                and int(np.count_nonzero(eigenvalues > tolerance)) <= body["observation_count"],
                "invalid sufficient-equation geometry")
        seen.add(node)
        batches.add(body["batch_sha256"])
        validated.append((node, gram, moment, square, envelope))
    require(seen == set(common["roster"]), "incomplete peer set")
    gram, moment, square, count = np.zeros((dimension, dimension)), np.zeros(dimension), 0., 0
    receipts = []
    for node, local_gram, local_moment, local_square, envelope in sorted(validated, key=lambda row: row[0]):
        gram += local_gram
        moment += local_moment
        square += local_square
        count += envelope["body"]["observation_count"]
        receipts.append({"node": node, "sha256": envelope["sha256"]})
    operator = gram + common["ridge"] * np.eye(dimension)
    delta = np.linalg.solve(operator, moment)
    residual = float(np.linalg.norm(operator @ delta - moment) / max(1., np.linalg.norm(moment)))
    require(bool(np.isfinite(delta).all()) and residual <= 1e-10,
            "peer normal-equation solve failed its fixed residual gate")
    eigenvalues = np.linalg.eigvalsh((gram + gram.T) / 2)
    tolerance = 64 * np.finfo(float).eps * dimension * max(0., float(eigenvalues[-1]))
    rank = int(np.count_nonzero(eigenvalues > tolerance))
    data_objective = float(.5 * (delta @ gram @ delta - 2 * delta @ moment + square))
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
        "regularized_objective": data_objective + .5 * common["ridge"] * float(delta @ delta),
        "actual_nonlinear_improvement_measured": False, "production_adoption": False,
    }

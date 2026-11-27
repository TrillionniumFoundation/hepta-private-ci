"""Unexecuted WeightCode-style Hepta boundary-program core, not a model runner.

Input is a hash-bound, already-produced baseline trace. Output is two 10x4 real
proposal directions plus a predetermined random control. It cannot publish an
artifact, edit a source, generate an uncounted model trace or select on feedback.
F32 realization/evaluation must use the separately sealed predecessor helpers.
"""

import math
import re
import time

import numpy as np

from boundary_inverse import Abstain, Constants, invert_boundary


def checked_array(trace, name, shape, dtype):
    value = np.asarray(trace[name])
    if value.shape != shape or value.dtype != np.dtype(dtype):
        raise Abstain("TRACE_SCHEMA_" + name)
    if value.dtype.kind in "fc" and not np.isfinite(value).all():
        raise Abstain("TRACE_NONFINITE_" + name)
    return value


def actors_from_ids(trace):
    """Require the frozen query/group/gallery relationship, no invented actors."""
    groups = np.asarray(trace["query_groups"])
    query = np.asarray(trace["query_id"])
    gallery = np.asarray(trace["gallery_id"])
    if groups.shape != (80,) or query.shape != (80,) or gallery.shape != (80, 2):
        raise Abstain("ACTOR_METADATA_SCHEMA")
    if any(value.dtype.kind not in "US" for value in (groups, query, gallery)):
        raise Abstain("ACTOR_METADATA_NOT_PLAIN_STRINGS")
    actors = []
    for group, qid, gids in zip(groups.tolist(), query.tolist(), gallery.tolist()):
        group = group.decode("utf-8") if isinstance(group, bytes) else str(group)
        match = re.fullmatch(r"ravdess-actor-([0-9]{2})", group)
        if not match:
            raise Abstain("ACTOR_GROUP_UNBOUND")
        actor = match.group(1)
        # Public producer must confirm this suffix rule before execution.
        for item in (qid, *gids):
            item = item.decode("utf-8") if isinstance(item, bytes) else str(item)
            filename = item.rsplit("/", 1)[-1].split(".", 1)[0]
            if filename.rsplit("-", 1)[-1] != actor:
                raise Abstain("QUERY_GALLERY_ACTOR_MISMATCH")
        actors.append(actor)
    return np.asarray(actors)


def solve_shared_keys(keys, residual, correct_rows, start_operation):
    """One shared constrained 10x4 ridge solve; every row is retained."""
    start_operation("shared_10x4_fit", {"rows": int(len(keys)), "radius": 1.0,
                                       "ridge": .02, "protection_weight": .25})
    failed = ~correct_rows
    nf, nc = int(failed.sum()), int(correct_rows.sum())
    if nf == 0 or nc == 0:
        raise Abstain("EMPTY_FAILED_OR_PROTECTION_GROUP")
    kf, kc = keys[failed], keys[correct_rows]
    rf = residual[failed]
    hessian = kf.T @ kf / nf + .25*(kc.T @ kc) / nc + .02*np.eye(10)
    hessian = (hessian + hessian.T) / 2
    right = kf.T @ rf / nf
    if not np.isfinite(hessian).all() or not np.isfinite(right).all():
        raise Abstain("NONFINITE_NORMAL_EQUATIONS")
    eigenvalues, eigenvectors = np.linalg.eigh(hessian)
    if not np.isfinite(eigenvalues).all() or not np.isfinite(eigenvectors).all():
        raise Abstain("NONFINITE_EIGENSOLVE")
    scale = max(1.0, float(np.linalg.norm(hessian)))
    if (float(eigenvalues.min()) < .01
            or float(np.linalg.norm(eigenvectors.T@eigenvectors-np.eye(10))) > 1e-10
            or float(np.linalg.norm(hessian@eigenvectors-eigenvectors*eigenvalues)) > 1e-10*scale):
        raise Abstain("EIGENSOLVE_NOT_QUALIFIED")
    coordinates = eigenvectors.T @ right

    def at(multiplier):
        return eigenvectors @ (coordinates/(eigenvalues[:, None]+multiplier))

    delta = at(0.0)
    iterations = 0
    multiplier = 0.0
    if float(np.linalg.norm(delta)) > 1.0:
        low, high = 0.0, float(np.linalg.norm(right))
        if not math.isfinite(high) or high <= 0:
            raise Abstain("TRUST_REGION_BRACKET")
        if float(np.linalg.norm(at(high))) > 1.0 + 1e-12:
            raise Abstain("TRUST_REGION_UPPER_NOT_FEASIBLE")
        for iterations in range(1, 129):
            middle = low + (high-low)/2
            if middle == low or middle == high:
                break
            if float(np.linalg.norm(at(middle))) > 1.0:
                low = middle
            else:
                high = middle
        multiplier = high
        delta = at(high)
    if not np.isfinite(delta).all() or float(np.linalg.norm(delta)) > 1.0+1e-12:
        raise Abstain("TRUST_REGION_NUMERICAL_REJECT")
    stationarity = float(np.linalg.norm((hessian+multiplier*np.eye(10))@delta-right))
    if stationarity > 1e-10*max(1.0, float(np.linalg.norm(right))):
        raise Abstain("STATIONARITY_RESIDUAL")
    if not float(np.linalg.norm(delta)) > 0.0:
        raise Abstain("ZERO_BOUNDARY_DIRECTION")
    return delta, {"lagrange_multiplier": multiplier, "iterations": iterations,
                   "continuous_frobenius_norm": float(np.linalg.norm(delta)),
                   "stationarity_residual": stationarity,
                   "eigenvalue_minimum": float(eigenvalues.min()),
                   "failed_rows": nf, "protected_rows": nc,
                   "real_surrogate_optimality_only": True}


def construct(trace, raw_cost, reset_absolute, constants, start_operation, wall_seconds=180):
    """Construct fixed proposals. Caller must fsync start_operation before work.

    The caller also binds source/trace hashes and verifies actual drift/cost bits.
    No caller-supplied optimizer or inference callback is accepted.
    """
    if not isinstance(constants, Constants):
        raise Abstain("CONSTANTS_SCHEMA")
    constants.validate()
    if not callable(start_operation):
        raise Abstain("DURABLE_OPERATION_LEDGER_REQUIRED")
    wall_seconds = float(wall_seconds)
    if not math.isfinite(wall_seconds) or wall_seconds <= 0:
        raise Abstain("INVALID_DEADLINE")
    deadline = time.monotonic()+min(180.0, wall_seconds)
    slow = checked_array(trace, "slow_ticks", (3,), "int64")
    if not np.array_equal(slow, [0, 2, 4]):
        raise Abstain("SLOW_TICK_ORDER")
    keys = checked_array(trace, "sender_keys", (3, 160, 10), "float32")
    preactivation = checked_array(trace, "sender_z", (3, 160, 4), "float32")
    boundaries = checked_array(trace, "sender_boundary", (3, 160, 4), "float64")
    checked_array(trace, "sender_drift", (3, 160, 4), "float64")
    checked_array(trace, "sender_cost", (3, 160, 4), "float64")
    correct = checked_array(trace, "parent_correct", (80,), "bool")
    y = checked_array(trace, "y", (80,), "int64")
    if not np.isin(y, [0, 1]).all() or not np.all(keys[:, :, -1].view(np.uint32) == 0x3f800000):
        raise Abstain("ROLE_OR_AFFINE_INTERCEPT")
    actors = actors_from_ids(trace)
    theta, absolute = np.asarray(raw_cost), np.asarray(reset_absolute)
    if theta.shape != (4,) or theta.dtype != np.dtype("float32"):
        raise Abstain("ORIGINAL_THETA_SCHEMA")
    if absolute.shape != (4,) or absolute.dtype != np.dtype("float64"):
        raise Abstain("ORIGINAL_RESET_SCHEMA")
    if not np.isfinite(theta).all() or not np.isfinite(absolute).all():
        raise Abstain("NONFINITE_ORIGINAL_TENSOR")
    donor_queries = np.flatnonzero(correct)
    if len(np.unique(actors[donor_queries])) < 2:
        raise Abstain("INSUFFICIENT_CORRECT_DONOR_ACTORS")
    if not 0 < len(donor_queries) < 80:
        raise Abstain("EMPTY_FAILED_OR_PROTECTION_QUERIES")
    prototype = np.empty((2, 3, 4), dtype=np.float64)
    reference_z = np.empty_like(prototype)
    roots = []
    target_z = np.empty_like(prototype)
    for role in (0, 1):  # 0=MATCH, 1=DECOY; never a fixed candidate index
        donor_rows = 2*donor_queries + (y[donor_queries] if role == 0 else 1-y[donor_queries])
        prototype[role] = boundaries[:, donor_rows].mean(axis=1, dtype=np.float64)
        reference_z[role] = preactivation[:, donor_rows].mean(axis=1, dtype=np.float64)
        for tick in range(3):
            for sender in range(4):
                boundary = float(prototype[role, tick, sender])
                margin = float(absolute[sender])-boundary
                if not (1/6 < margin < 11/6):
                    raise Abstain("TARGET_RESET_OUTSIDE_ORIGINAL_SIX_BIN_HULL")
                descriptor = {"role": role, "slow_tick": int(slow[tick]), "sender": sender,
                              "boundary": boundary, "reference_z": float(reference_z[role, tick, sender])}
                start_operation("scalar_coupled_qvi_inverse", descriptor)
                result = invert_boundary(boundary, float(absolute[sender]), float(theta[sender]),
                                         descriptor["reference_z"], constants, deadline)
                roots.append({**descriptor, **result})
                target_z[role, tick, sender] = result["z"]
    # Query-major, candidate-major, slow-tick-major. Shared ten keys for four outputs.
    flat_keys = keys.transpose(1, 0, 2).reshape(480, 10).astype(np.float64)
    flat_old_z = preactivation.transpose(1, 0, 2).reshape(480, 4).astype(np.float64)
    rows_correct = np.repeat(correct, 6)
    roles = np.asarray([0 if c == int(y[q]) else 1 for q in range(80) for c in range(2)])
    proposal_directions, fits = {}, {}
    for name, wrong in (("BOUNDARY_PROGRAM", False), ("WRONG_BOUNDARY_ROLE", True)):
        if time.monotonic() > deadline:
            raise Abstain("COMPILE_DEADLINE")
        selected_roles = 1-roles if wrong else roles
        desired_z = target_z[selected_roles].reshape(480, 4)
        residual = desired_z-flat_old_z
        residual[rows_correct] = 0.0
        proposal_directions[name], fits[name] = solve_shared_keys(flat_keys, residual, rows_correct,
                                                                 start_operation)
    rng = np.random.default_rng(20261129)
    random = rng.normal(size=(10, 4))
    random *= proposal_directions["BOUNDARY_PROGRAM"] != 0.0
    random *= np.linalg.norm(proposal_directions["BOUNDARY_PROGRAM"])/np.linalg.norm(random)
    proposal_directions["MATCHED_RANDOM"] = random
    return {"status": "REAL_PROPOSALS_ONLY_F32_REALIZATION_REQUIRED", "directions": proposal_directions,
            "boundary_prototypes": prototype, "reference_z": reference_z, "reference_z_role": "diagnostic_only_not_root_selection", "target_z": target_z,
            "root_records": roots, "fits": fits,
            "scope": "input_drive.weight.T in first9 rows, input_drive.bias in last row",
            "doses": {"BOUNDARY_PROGRAM": [.25, 1.0], "WRONG_BOUNDARY_ROLE": [1.0], "MATCHED_RANDOM": [1.0]},
            "new_full_rollouts_performed_here": 0, "new_backward_performed_here": 0,
            "constant_float_hex": {key: float(value).hex() for key, value in vars(constants).items()}}

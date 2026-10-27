"""Causal three-decision policies with candidate-specific continuation values.

Fit/selection banks contain full four-ary trees; deployment sees only its own
causal public events. A candidate's earlier heads follow its frozen later heads,
never a privileged max over future rewards. No fitting occurs in select().
"""

import hashlib
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from .native_stream import Q24, NativeSession, file_sha

SCHEMA = "hepta.field-bridge-v3.runtime-controller.v1"
REPRESENTATIONS = ("current", "history", "native", "reset_native")
TRANSFORMS = (("raw", None), ("k1", 1), ("k2", 2), ("k4", 4))
ALPHAS = (0.0001, 0.01, 1.0)
RFF_SEED = 271033
STAGE_NODES = ((0,), tuple(range(1, 5)), tuple(range(5, 21)))


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def array_sha(value):
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes()).hexdigest()


def node_path(node):
    if type(node) is not int or not 0 <= node < 85:
        raise ValueError("Expected a BFS node in the bounded 85-state tree")
    nodes = [node]
    while node:
        node = (node-1)//4
        nodes.append(node)
    return tuple(reversed(nodes))


def node_actions(node):
    path = node_path(node)
    return [child-4*parent for parent, child in zip(path[:-1], path[1:], strict=True)]


def _events(value):
    value = np.asarray(value, dtype=np.float64)
    if value.shape[-1:] != (16,) or not np.isfinite(value).all() or np.any(np.abs(value) > 1):
        raise ValueError("Public events require finite sixteen-dimensional signed bounded values")
    return value


def _histories(value):
    value = _events(value)
    if value.ndim != 3 or len(value) == 0 or not 1 <= value.shape[1] <= 3:
        raise ValueError("Expected N x causal-rounds(1..3) x16 public history")
    if np.any(value[:, 0, 8:] != 0):
        raise ValueError("Initial event has neither feedback nor a selected predecessor action")
    if value.shape[1] > 1:
        follow = value[:, 1:]
        if (np.any(follow[:, :, 8] != 1) or np.any(np.abs(follow[:, :, 9:11]) != 1)
                or not np.all((follow[:, :, 12:] == 0) | (follow[:, :, 12:] == 1))
                or np.any(follow[:, :, 12:].sum(-1) != 1)):
            raise ValueError("A later event requires delivered feedback and one previous non-stop action")
    return value


def _normalizer(values):
    return {"mean": values.mean(0).tolist(), "scale": np.maximum(values.std(0), 1e-6).tolist(),
            "ddof": 0, "std_floor": 1e-6, "scope": "runtime_fit_only"}


def _standardize(values, spec, width):
    mean, scale = np.asarray(spec["mean"]), np.asarray(spec["scale"])
    if (mean.shape != (width,) or scale.shape != (width,) or not np.isfinite(mean).all()
            or not np.isfinite(scale).all() or np.any(scale < 1e-6)):
        raise ValueError("Invalid frozen training normalizer")
    return (values-mean)/scale


def _transform(events, spec):
    if (spec.get("name"), spec.get("k")) not in TRANSFORMS:
        raise ValueError("Unregistered public-event transform")
    return events if spec["k"] is None else np.clip(
        _standardize(events, spec["normalizer"], 16)/spec["k"], -1, 1)


def _pad(history):
    output = np.zeros((len(history), 3, 16), dtype=np.float64)
    output[:, :history.shape[1]] = history
    return output.reshape(len(history), 48)


def _fourier(width, frequencies):
    weights = np.random.default_rng(RFF_SEED).normal(size=(width, frequencies))/np.sqrt(width)
    return {"seed": RFF_SEED, "input_width": width, "frequencies": frequencies,
            "weights": weights.tolist(), "weight_sha256": array_sha(weights),
            "formula": "concat(cos(xW),sin(xW))/sqrt(frequencies); fixed weights independent of labels",
            "contraction": "numpy.einsum('bi,ij->bj', optimize=False); batch-independent reduction"}


def _rff(values, spec):
    weights = np.asarray(spec["weights"], dtype=np.float64)
    if (weights.shape != (values.shape[-1], spec["frequencies"])
            or not np.isfinite(weights).all() or array_sha(weights) != spec["weight_sha256"]
            or spec["seed"] != RFF_SEED):
        raise ValueError("Invalid fixed Fourier specification")
    projection = np.einsum("bi,ij->bj", values, weights, optimize=False)
    return np.concatenate((np.cos(projection), np.sin(projection)), axis=-1)/np.sqrt(spec["frequencies"])


def _non_native_features(representation, histories, transform, fourier):
    transformed = _transform(histories, transform)
    if representation == "current":
        return np.column_stack((histories[:, -1], _rff(transformed[:, -1], fourier)))
    return np.column_stack((_pad(histories), _rff(_pad(transformed), fourier)))


def _native_event(session, history, transform, reset):
    raw = history.astype("<f8", copy=False).tobytes()
    if session.history_bytes != raw[:-16*8] or session.clock != 2*(len(history)-1):
        raise ValueError("Native state and immutable public history prefix disagree")
    current = _transform(history[-1], transform)
    signed = np.rint(current*Q24).astype(np.int64).tolist()
    digest = hashlib.sha256(b"hepta.field-v3.public-history.v1"+
        bytes.fromhex(object_sha(transform))+raw).hexdigest()
    if reset and len(history) > 1:
        session.reset()
    receipts = []
    for start in (0, 8):
        features, receipt = session.tick(signed[start:start+8], readback_digest=digest)
        receipts.append(receipt)
    session.history_bytes = raw
    return features, receipts


def _validate_controller(controller):
    if (controller.get("schema") != SCHEMA or controller.get("representation") not in REPRESENTATIONS
            or controller.get("authority") != "DENY_ALL" or controller.get("native_owner_integration") is not False
            or controller.get("feature_width") != 88 or len(controller.get("heads", ())) != 3
            or controller.get("alpha") not in ALPHAS):
        raise ValueError("Invalid frozen V3 runtime policy")
    for stage, head in enumerate(controller["heads"]):
        coefficient = np.asarray(head["coefficient"])
        if coefficient.shape != (89, 5) or not np.isfinite(coefficient).all() or head["stage"] != stage:
            raise ValueError("Invalid frozen stage coefficients")


def _choose(head, features):
    z = _standardize(features, head["normalizer"], 88)
    return np.einsum("bi,ij->bj", np.column_stack((z, np.ones(len(z)))),
                     np.asarray(head["coefficient"]), optimize=False)


def select(controller, histories, *, bridge=None, sessions=None, receipt_path=None):
    """Execute one causal decision without targets, candidate branches or fitting.

    Native callers retain one session per live episode and pass the corresponding
    active subset each round. A fresh session, replayed prefix, changed controller
    or resumed stopped episode is rejected. Stage0 is the root after common couple.
    """
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    _validate_controller(controller)
    histories = _histories(histories)
    stage, rep = histories.shape[1]-1, controller["representation"]
    controller_sha = object_sha(controller)
    path = Path(receipt_path) if receipt_path is not None else None
    if path is not None and path.exists():
        raise ValueError("Refusing to replace native decision evidence")
    native_records, native_ns, ticks = [], 0, 0
    phase = time.perf_counter_ns()
    if rep in {"native", "reset_native"}:
        if (bridge is None or bridge.binary_sha256 != controller["native_library_sha256"]
                or sessions is None or len(sessions) != len(histories)
                or any(not isinstance(session, NativeSession) for session in sessions)
                or len({session.handle for session in sessions}) != len(sessions)):
            raise ValueError("Registered native library and retained episode sessions are required")
        for session, history in zip(sessions, histories, strict=True):
            if (not isinstance(session, NativeSession) or session.bridge is not bridge or session.closed
                    or session.controller_binding not in (None, controller_sha)
                    or session.clock != 2*stage or session.history_bytes != history[:-1].astype("<f8").tobytes()):
                raise ValueError("Native session, controller or causal prefix differs")
            if stage and (getattr(session, "selected_action", None) in (None, 0)
                          or history[-1, 12:].argmax()+1 != session.selected_action):
                raise ValueError("Feedback must follow this episode's previously selected non-stop action")
        state_features = []
        for session, history in zip(sessions, histories, strict=True):
            native, records = _native_event(session, history, controller["transform"], rep == "reset_native")
            session.controller_binding = controller_sha
            state_features.append(native)
            ticks += 2
            native_ns += sum(row["native_ns"] for row in records)
            native_records.append({"case": session.case, "round": stage, "raw_history": history.tolist(),
                "raw_history_sha256": array_sha(history), "transformed_current_event": _transform(history[-1], controller["transform"]).tolist(),
                "reset_before_round": rep == "reset_native" and stage > 0, "ticks": records})
        features = np.column_stack((_pad(histories), np.asarray(state_features)))
    else:
        if sessions is not None or receipt_path is not None:
            raise ValueError("Non-native policies cannot consume native sessions or write native receipts")
        features = _non_native_features(rep, histories, controller["transform"], controller["fourier"])
    representation_ns = time.perf_counter_ns()-phase
    phase = time.perf_counter_ns()
    actions = _choose(controller["heads"][stage], features).argmax(1)
    head_ns = time.perf_counter_ns()-phase
    if rep in {"native", "reset_native"}:
        for session, action, record in zip(sessions, actions, native_records, strict=True):
            session.selected_action = int(action)
            record.update(action=int(action), controller_sha256=controller_sha)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x") as output:
                for record in native_records:
                    output.write(json.dumps(record, sort_keys=True, allow_nan=False)+"\n")
    return actions, {"schema": "hepta.field-bridge-v3.runtime-selection.v1", "rows": len(histories),
        "round": stage, "representation": rep, "native_tick_calls": ticks, "native_ns": native_ns,
        "controller_sha256": controller_sha, "public_history_sha256": array_sha(histories),
        "feature_matrix_sha256": array_sha(features), "action_indices": actions.tolist(),
        "representation_wall_ns": representation_ns, "head_wall_ns": head_ns,
        "select_wall_ns": time.perf_counter_ns()-started, "select_python_cpu_ns": time.process_time_ns()-cpu,
        "native_records": native_records if path is None else None,
        "native_receipt_path": str(path) if path is not None else None,
        "target_accesses": 0, "future_events_accessed": 0, "authority": "DENY_ALL",
        "native_owner_integration": False, "requires_calibration": rep in {"native", "reset_native"}}


def _bank(bank, role):
    if bank.get("role") != role:
        raise ValueError("Only declared runtime_fit/runtime_select banks enter fitting")
    events = _events(bank["events"])
    values = np.asarray(bank["terminal_values"], dtype=np.float64)
    if (events.ndim != 3 or events.shape[1:] != (21, 16) or len(events) == 0
            or values.shape != (len(events), 85) or not np.isfinite(values).all()
            or np.any(values < -1.01) or np.any(values > 1)):
        raise ValueError("Incomplete events/terminal values for the declared four-ary tree")
    ids = bank.get("source_ids")
    if (ids is None or len(ids) != len(events) or any(len(pair) != 2 or
            any(not isinstance(item, str) or not item for item in pair) for pair in ids)):
        raise ValueError("Source-pair identities are required")
    for node in range(21):
        history = events[:, node_path(node)]
        _histories(history)
        if node and np.any(events[:, node, 12:].argmax(1)+1 != node_actions(node)[-1]):
            raise ValueError("BFS action provenance differs from its public event")
    return events, values, [[str(value) for value in pair] for pair in ids]


def _tree_features(events, rep, transform, fourier, bridge, prefix):
    features = np.empty((len(events), 21, 88), dtype=np.float64)
    before = bridge.tick_count if bridge is not None else 0
    if rep in {"current", "history"}:
        for node in range(21):
            features[:, node] = _non_native_features(rep, events[:, node_path(node)], transform, fourier)
    else:
        for case, event in enumerate(events):
            sessions = []
            try:
                for node in range(21):
                    session = bridge.open(f"{prefix}:{case}") if node == 0 else sessions[(node-1)//4].fork()
                    sessions.append(session)
                    history = event[list(node_path(node))]
                    native, _ = _native_event(session, history, transform, rep == "reset_native")
                    features[case, node] = np.r_[_pad(history[None])[0], native]
            finally:
                for session in sessions:
                    session.close()
        if bridge.tick_count-before != 42*len(events):
            raise RuntimeError("Native fitting work differed from the complete tree contract")
    return features


def _ridge(features, targets, alpha, stage):
    normalizer = _normalizer(features)
    z = np.column_stack((_standardize(features, normalizer, 88), np.ones(len(features))))
    penalty = np.diag(np.r_[np.ones(88), 0.0])
    coefficient = np.linalg.solve(z.T @ z+alpha*penalty, z.T @ targets)
    return {"stage": stage, "coefficient": coefficient.tolist(), "normalizer": normalizer,
        "alpha": alpha, "parameter_count": 445, "intercept_penalized": False,
        "fit_rows": len(features), "targets_sha256": array_sha(targets),
        "fit_mse": float(np.mean((z @ coefficient-targets)**2))}


def _fit_policy(features, values, alpha):
    heads = [None]*3
    continuation = values.copy()
    all_actions = np.empty((len(features), 21), dtype=np.int64)
    for stage in (2, 1, 0):
        nodes = np.asarray(STAGE_NODES[stage])
        targets = np.stack((values[:, nodes], *[continuation[:, 4*nodes+action] for action in range(1, 5)]), axis=-1)
        heads[stage] = _ridge(features[:, nodes].reshape(-1, 88), targets.reshape(-1, 5), alpha, stage)
        actions = _choose(heads[stage], features[:, nodes].reshape(-1, 88)).argmax(1).reshape(len(features), -1)
        all_actions[:, nodes] = actions
        continuation[:, nodes] = np.take_along_axis(targets, actions[..., None], axis=-1)[..., 0]
    return heads, all_actions, continuation[:, 0]


def evaluate_tree(heads, features, terminal_values):
    """Evaluate each actual selected branch, with stop reusing its current node."""
    nodes = np.zeros(len(features), dtype=np.int64)
    active = np.ones(len(features), dtype=bool)
    for stage in range(3):
        rows = np.flatnonzero(active)
        if not len(rows):
            break
        actions = _choose(heads[stage], features[rows, nodes[rows]]).argmax(1)
        moving = rows[actions != 0]
        nodes[moving] = 4*nodes[moving]+actions[actions != 0]
        active[rows[actions == 0]] = False
    return terminal_values[np.arange(len(features)), nodes], nodes


def _save_feature(archive, name, values):
    if archive is not None:
        with archive.open(name+".npy", "w", force_zip64=True) as output:
            np.lib.format.write_array(output, np.ascontiguousarray(values), allow_pickle=False)


def fit_controllers(train, selection, bridge, metadata=None, feature_destination=None):
    """Fit exactly 48 policies /144 stage heads; never accepts audit/test roles.

    Events are N x21 x16, terminal_values N x85, and source_ids N x2.
    terminal_values already include all charged transitions, including any common
    initial couple. No value is substituted for the candidate's own future policy.
    """
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    te, tv, tids = _bank(train, "runtime_fit")
    se, sv, sids = _bank(selection, "runtime_select")
    if {v for row in tids for v in row} & {v for row in sids for v in row}:
        raise ValueError("Runtime fitting and selection source identities overlap")
    if bridge is None or bridge.closed:
        raise ValueError("An open pinned original native stream is required")
    destination = Path(feature_destination) if feature_destination is not None else None
    if destination is not None and destination.exists():
        raise ValueError("Refusing to replace fitting feature evidence")
    common = _normalizer(te.reshape(-1, 16))
    identity = {"training_events_sha256": array_sha(te), "training_values_sha256": array_sha(tv),
        "selection_events_sha256": array_sha(se), "selection_values_sha256": array_sha(sv),
        "training_source_ids_sha256": object_sha(tids), "selection_source_ids_sha256": object_sha(sids),
        "metadata": metadata or {}}
    candidates, feature_records = [], []
    tick_before, native_before = bridge.tick_count, bridge.native_ns
    archive = zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) if destination else None
    try:
        for transform_index, (name, k) in enumerate(TRANSFORMS):
            transform = {"name": name, "k": k, "normalizer": common}
            for rep in REPRESENTATIONS:
                fourier = _fourier(16, 36) if rep == "current" else _fourier(48, 20) if rep == "history" else None
                before = time.perf_counter_ns()
                tx = _tree_features(te, rep, transform, fourier, bridge, f"v3-fit-{name}-{rep}")
                sx = _tree_features(se, rep, transform, fourier, bridge, f"v3-select-{name}-{rep}")
                feature_records.append({"representation": rep, "transform": name,
                    "training_sha256": array_sha(tx), "selection_sha256": array_sha(sx),
                    "feature_wall_ns": time.perf_counter_ns()-before})
                for role, matrix in (("train", tx), ("selection", sx)):
                    _save_feature(archive, f"{name}.{rep}.{role}", matrix)
                for alpha_index, alpha in enumerate(ALPHAS):
                    fit_started = time.perf_counter_ns()
                    heads, train_actions, backward_return = _fit_policy(tx, tv, alpha)
                    train_return, train_nodes = evaluate_tree(heads, tx, tv)
                    selection_return, selection_nodes = evaluate_tree(heads, sx, sv)
                    if not np.array_equal(train_return, backward_return):
                        raise RuntimeError("Backward targets do not follow the fitted later heads")
                    controller = {"schema": SCHEMA, "representation": rep, "feature_width": 88,
                        "alpha": alpha, "transform": transform, "fourier": fourier, "heads": heads,
                        "native_library_sha256": bridge.binary_sha256 if rep in {"native", "reset_native"} else None,
                        "authority": "DENY_ALL", "native_owner_integration": False,
                        "fit_identities": identity, "future_value_definition": "same candidate later frozen heads",
                        "head_contraction": "numpy.einsum('bi,ij->bj', optimize=False); batch-independent reduction",
                        "head_coefficients": 1335, "candidate_index": transform_index*3+alpha_index}
                    candidates.append({"representation": rep, "candidate_index": controller["candidate_index"],
                        "controller": controller, "training_mean_value": float(train_return.mean()),
                        "selection_mean_value": float(selection_return.mean()),
                        "training_terminal_nodes": train_nodes.tolist(), "selection_terminal_nodes": selection_nodes.tolist(),
                        "training_all_node_actions_sha256": array_sha(train_actions),
                        "fit_wall_ns": time.perf_counter_ns()-fit_started})
    finally:
        if archive is not None:
            archive.close()
    chosen = {rep: max((row for row in candidates if row["representation"] == rep),
                      key=lambda row: (row["selection_mean_value"], -row["candidate_index"])) for rep in REPRESENTATIONS}
    fixed_node = int(sv.mean(0).argmax())
    result = {"schema": "hepta.field-bridge-v3.runtime-fitting.v1", "models": {rep: row["controller"] for rep, row in chosen.items()},
        "selected": {rep: {key: row[key] for key in ("candidate_index", "training_mean_value", "selection_mean_value")} for rep, row in chosen.items()},
        "candidates": candidates, "candidate_policies": 48, "stage_head_fits": 144,
        "candidates_per_representation": 12, "head_coefficients_per_policy": 1335,
        "training_base_trees": len(te), "selection_base_trees": len(se), "fit_identities": identity,
        "fixed_policy": {"node": fixed_node, "actions": node_actions(fixed_node),
            "selection_mean_values_all85": sv.mean(0).tolist(), "training_mean_values_all85": tv.mean(0).tolist(),
            "tie_break": "lowest BFS node; no fitted-family fallback"},
        "feature_matrices": feature_records, "native_tick_calls": bridge.tick_count-tick_before,
        "native_ns": bridge.native_ns-native_before,
        "native_expected_tick_calls": 4*2*42*(len(te)+len(se)),
        "feature_evidence": None if destination is None else {"path": str(destination), "sha256": file_sha(destination), "matrices": 32},
        "all_targets_from_fit_only": True, "selection_used_only_to_choose_frozen_candidates": True,
        "fit_wall_ns": time.perf_counter_ns()-started, "fit_python_cpu_ns": time.process_time_ns()-cpu}
    if result["native_tick_calls"] != result["native_expected_tick_calls"]:
        raise RuntimeError("Unaccounted native fitting work")
    return json.loads(json.dumps(result, allow_nan=False))

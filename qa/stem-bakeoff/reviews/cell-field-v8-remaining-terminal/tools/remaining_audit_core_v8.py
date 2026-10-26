"""Independent terminal-response algebra and actual prefix verification.

Uses the qualified physical Adam JVP primitive and actual head gradients, never
the producer's terminal proposal, controller, or safety search. No selection
arrays enter this module. All nominal/replay work is separately accounted.
"""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


METHODS = ("myopic_h1", "loss2_remaining", "full_adjoint_remaining", "terminal_field8_remaining")
WEIGHTS = np.r_[np.full(4, .25), np.full(4, .0625)]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def required_hash(value, key):
    pin = value.get(key)
    require(isinstance(pin, str) and len(pin) == 64 and all(c in "0123456789abcdef" for c in pin),
        "mandatory external SHA256 pin missing or malformed: "+key)
    return pin


def bind_execution_identity(report, pins):
    for key in ("protocol_sha256", "source_sha256"):
        require(report.get(key) == required_hash(pins, key), "report differs from external execution identity: "+key)
    commit = pins.get("source_commit")
    require(isinstance(commit, str) and len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
        and report.get("source_commit") == commit, "report differs from external execution commit")


def file_hash(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "ordinary input file required")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 32 << 20, "bounded ordinary JSON required")
    return json.loads(path.read_bytes())


def load_policy_record(directory, compressed=False):
    index = read(directory/"result.json")
    if index["schema"] != "hepta.remaining-terminal-policy-record-index.v8":
        require(not compressed or index["schema"] == "hepta.remaining-terminal-policy-error.v8",
            "registered compressed storage revision requires an index for every available prefix")
        return index
    pin = index["policy_record"]
    require(pin["file"] == "policy-record.json.gz" and type(pin["bytes"]) is int
        and type(pin["uncompressed_bytes"]) is int and 0 < pin["uncompressed_bytes"] <= 32 << 20,
        "bounded fixed compressed ledger")
    path = directory/pin["file"]
    require(file_hash(path) == pin["sha256"] and path.stat().st_size == pin["bytes"], "compressed ledger bytes")
    with path.open("rb") as stream:
        require(stream.read(8)[4:8] == b"\0"*4, "deterministic gzip timestamp")
    with gzip.open(path, "rb") as stream:
        raw = stream.read((32 << 20)+1)
    require(len(raw) == pin["uncompressed_bytes"] and digest(raw) == pin["uncompressed_sha256"], "expanded ledger bytes")
    record = json.loads(raw)
    require(canonical(record)+b"\n" == raw and all(value == record.get(key)
        for key, value in index.items() if key not in {"schema", "policy_record"}), "lossless canonical ledger/index agreement")
    return record


def array_hash(array):
    array = np.ascontiguousarray(array)
    return digest(canonical([array.dtype.str, list(array.shape)])+array.tobytes())


def errors(value):
    if isinstance(value, dict):
        return ([value["error"]] if value.get("error") else []) + [
            e for k, v in value.items() if k != "error" for e in errors(v)]
    if isinstance(value, list):
        return [e for v in value for e in errors(v)]
    return []


def panel_values(state, panels, gradients=False):
    values, rows = [], []
    for x, y in panels:
        x = np.asarray(x, dtype=np.float64)
        normalized = x/np.maximum(np.sqrt(np.square(x).sum(axis=1, keepdims=True)), 1e-12)*np.sqrt(x.shape[1])
        loss, derivative = state.head.loss_gradients(normalized, y, 0.)
        values.append(loss)
        if gradients:
            rows.append(np.concatenate([derivative[n].ravel() for n in state.names]))
    values = np.asarray(values)
    require(np.isfinite(values).all(), "finite actual panel losses required")
    return (values, np.asarray(rows)) if gradients else values


def check_seal(root, expected=None):
    root = Path(root)
    if expected:
        require(file_hash(root/"control_seal.json") == expected, "original complete control seal changed")
    seal = read(root/"control_seal.json")
    paths = {p.relative_to(root).as_posix(): p for p in root.rglob("*")
        if p.is_file() and p != root/"control_seal.json"}
    require(set(paths) == set(seal["files"]), "exact complete control inventory required")
    for name, path in paths.items():
        require(path.stat().st_size == seal["files"][name]["bytes"]
            and file_hash(path) == seal["files"][name]["sha256"], "sealed bytes differ: "+name)
    return seal


def independent_response(origin, train, panels, method, remaining):
    """Forward JVPs replace the producer's backwards adjoints/pseudoinverse."""
    from cell_field_response_v5 import AdamDerivative
    h, p = (1 if method == "myopic_h1" else remaining), origin.parameter_count
    state, vectors, gradients = origin.clone(), [origin.vector()], {}
    values = None
    for k in range(h):
        state.advance(*train, intervention=np.zeros(p))
        vectors.append(state.vector())
        if method == "loss2_remaining" or k == h-1:
            values, gradients[k+1] = panel_values(state, panels, True)
    field, jvp_count = None, 0
    if method == "loss2_remaining" and h > 1:
        retained = .02*gradients[1].reshape(2, 4, p).mean(axis=1)
        for k in range(1, h):
            c = np.hstack((gradients[k].reshape(2, 4, p).mean(axis=1), np.zeros((2, 2*p))))
            lifted = np.linalg.lstsq(c, retained, rcond=1e-10)[0]
            derivative = AdamDerivative(origin, vectors[k], origin.step_count+k, train)
            output = gradients[k+1]@derivative.jvp(lifted)[:p]
            retained = output.reshape(2, 4, p).mean(axis=1)
            jvp_count += 1
    else:
        if method == "terminal_field8_remaining":
            tangent = np.concatenate((np.eye(3*p), np.zeros((3*p, p))), axis=1)
            for k in range(h):
                derivative = AdamDerivative(origin, vectors[k], origin.step_count+k, train)
                tangent = derivative.jvp(tangent)
                if k == 0:
                    tangent[:p, 3*p:] += .02*np.eye(p)
                jvp_count += 1
            observed = gradients[h]@tangent[:p]
            field, output = observed[:, :3*p], observed[:, 3*p:]
        else:
            tangent = np.vstack((.02*np.eye(p), np.zeros((2*p, p))))
            for k in range(1, h):
                derivative = AdamDerivative(origin, vectors[k], origin.step_count+k, train)
                tangent = derivative.jvp(tangent)
                jvp_count += 1
            output = gradients[h]@tangent[:p]
    return {"map": output, "field": field, "terminal": state.vector(), "panels": values,
        "nominal_updates": h, "jvp_steps": jvp_count,
        "panel_head_evaluations": 8*h if method == "loss2_remaining" else 8}


def check_portfolio(record, origin, proposed, anchors, panels, accepted=None, following=None):
    from cell_field_state import dataset_digest
    attempts = record["attempts"]
    require(record["schema"] == "hepta.cell-field-fixed-portfolio.v8"
        and 1 <= len(attempts) <= 2 and [v["filter"] for v in attempts]
        == ["single_ray_v7", "joint_actual_old_v8"][:len(attempts)]
        and (len(attempts) == 1) == bool(attempts[0]["record"]["certified"]), "fixed old-first whole-step portfolio")
    for attempt in attempts:
        inner = attempt["record"]
        require(inner["initial_state_sha256"] == origin.digest() and inner["horizon"] == 1
            and inner["dt"] == .02 and inner["action_bound"] == 4. and inner["threshold_slack"] == 0.
            and inner["original_old_anchors"] == anchors.tolist()
            and inner["old_panel_sha256"] == [dataset_digest(*p) for p in panels]
            and inner["committed_optimizer_steps"] == 0 and len(inner["step_records"]) == 1,
            "same origin, intended horizon and immutable empirical panel bounds")
        step = inner["step_records"][0]
        if attempt["filter"] == "single_ray_v7" and step["trials"]:
            require(step["trials"][0]["kind"] == "intended"
                and step["trials"][0]["action_sha256"] == digest(proposed.tobytes())
                and len(step["trials"]) <= 16, "single-ray intended action and bounded retained trials")
        if attempt["filter"] == "joint_actual_old_v8":
            require(np.array_equal(step["intended_action"], proposed), "joint uses the same intended action")
    chosen = attempts[-1]
    require(record["selected_filter"] == chosen["filter"] and all(record[k] == chosen["record"][k]
        for k in ("status", "certified", "returned_state_sha256", "certified_optimizer_steps")), "selected complete certificate")
    for key in ("verified_optimizer_steps", "panel_head_evaluations"):
        require(record[key] == sum(a["record"][key] for a in attempts), "every paid attempt remains charged")
    require(record["cpu_ns"] >= sum(a["record"]["cpu_ns"] for a in attempts) > 0
        and record["wall_ns"] >= sum(a["record"]["wall_ns"] for a in attempts) > 0
        and record["discarded_safe_prefix_steps"] == sum(a["record"]["prospective_safe_steps"]
            for a in attempts if not a["record"]["certified"]), "cost and discarded-prefix accounting")
    if accepted is not None:
        step = chosen["record"]["step_records"][0]
        require(record["certified"] and not errors(record) and record["certified_optimizer_steps"] == 1
            and record["returned_state_sha256"] == following.digest()
            and step["old_losses"] == panel_values(following, panels).tolist(), "adopted exact, error-free original-panel certificate")
        if chosen["filter"] == "single_ray_v7":
            require(step["trials"][-1]["action_sha256"] == digest(accepted.tobytes()), "selected single-ray action")
        else:
            require(np.array_equal(step["accepted_action"], accepted), "selected joint action")
    return {"attempts": len(attempts), "panel_queries": record["panel_head_evaluations"],
        "optimizer_updates": record["verified_optimizer_steps"], "selected_filter": chosen["filter"]}

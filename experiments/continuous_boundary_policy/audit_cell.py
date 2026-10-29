"""Independent NumPy inference and native score/profile receipt validation."""

import hashlib
import json

import numpy as np

from .audit_math import close, require

Q = 1 << 24
BANK = np.array([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])
GRU_SHAPES = {
    **{f"W{k}": (18, 6) for k in ("z", "r", "n")},
    **{f"U{k}": (6, 6) for k in ("z", "r", "n")},
    **{f"b{k}": (6,) for k in ("z", "r", "n")},
    "head": (6, 2),
    "head_bias": (2,),
}
ELMAN_SHAPES = {
    "W": (18, 6),
    "U": (6, 6),
    "b": (6,),
    "M": (24, 12),
    "head": (12, 2),
    "head_bias": (2,),
}
OBJECTIVE = hashlib.sha256(
    b"finite-window-production-minus-discounted-failure-maintenance.v1"
).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def hash_text(value, name, nonzero=True):
    require(
        isinstance(value, str)
        and len(value) == 64
        and all(x in "0123456789abcdef" for x in value),
        f"Malformed {name} digest",
    )
    require(not nonzero or value != "0" * 64, f"Zero {name} digest")
    return value


def signs():
    inputs = np.ones((18, 6))
    inputs[11:] = np.outer([1, 1, -1, -1, -1, -1, 1], BANK)
    return {
        "Wn": inputs,
        "Un": np.outer(BANK, BANK),
        "head": np.column_stack((BANK, -BANK)),
    }


def validate_cell(snapshot, expected_kind=None):
    require(
        snapshot.get("schema") == "hepta.continuous-boundary-policy.cell.v1",
        "Unknown cell schema",
    )
    architecture = snapshot["architecture"]
    kind = architecture["kind"]
    require(
        kind in {"dual", "gru", "elman"}
        and (expected_kind is None or kind == expected_kind),
        "Cell architecture mismatch",
    )
    shapes = ELMAN_SHAPES if kind == "elman" else GRU_SHAPES
    require(
        set(snapshot["params"]) == set(shapes), "Unexpected/missing model coefficients"
    )
    params = {
        name: np.asarray(value, dtype=float)
        for name, value in snapshot["params"].items()
    }
    for name, shape in shapes.items():
        require(
            params[name].shape == shape
            and np.isfinite(params[name]).all()
            and np.all(np.abs(params[name]) <= 8),
            f"Invalid bounded coefficient {name}",
        )
    require(
        sum(v.size for v in params.values()) == 464,
        "Model does not have 464 actual coefficients",
    )
    required_metadata = {
        "input_dims": 18,
        "persistent_state_dims": 6,
        "trainable_scalars": 464,
        "parameter_shapes": {name: list(shape) for name, shape in shapes.items()},
        "fixed_numeric_coefficients": 0 if kind == "elman" else 156,
        "matrix_multiply_scalars_per_tick": 456 if kind == "elman" else 444,
        "stop_logit": 0.0,
        "score_bound": 8.0,
    }
    require(
        all(architecture.get(k) == v for k, v in required_metadata.items()),
        "Forged architecture budget metadata",
    )
    fixed = (
        {}
        if kind == "elman"
        else {name: value.tolist() for name, value in signs().items()}
    )
    require(
        snapshot.get("fixed_sign_arrays") == fixed,
        "Fixed structural coefficients changed",
    )
    require(
        snapshot.get("dual_input_constraint_rows")
        == ([] if kind == "elman" else list(range(11, 18))),
        "Dual input constraint metadata changed",
    )
    if kind == "dual":
        require(
            np.all(params["Wn"][11:] >= 0)
            and np.all(params["Un"] >= 0)
            and np.all(params["head"] >= 0),
            "Signed dual prior violated",
        )
    return params, kind


def inference(features, reset, previous, params, kind):
    """Independent single-row recurrence; no import of cells.forward/step."""
    x, old = np.asarray(features, dtype=float), np.asarray(previous, dtype=float)
    require(
        x.shape == (18,)
        and old.shape == (6,)
        and np.isfinite(x).all()
        and np.isfinite(old).all()
        and np.max(np.abs(old)) <= 1
        and np.max(np.abs(x)) <= 4
        and np.isfinite(reset)
        and 0 <= reset <= 1,
        "Invalid recurrent input/state",
    )
    old = old * (1 - reset)
    if kind == "elman":
        hidden = np.tanh(x @ params["W"] + old @ params["U"] + params["b"])
        readout = np.tanh(np.concatenate((x, hidden)) @ params["M"])
        head = params["head"]
    else:
        fixed = signs()
        gate = lambda value: (np.tanh(value / 2) + 1) / 2
        z = gate(x @ params["Wz"] + old @ params["Uz"] + params["bz"])
        r = gate(x @ params["Wr"] + old @ params["Ur"] + params["br"])
        candidate = np.tanh(
            x @ (params["Wn"] * fixed["Wn"])
            + (r * old) @ (params["Un"] * fixed["Un"])
            + params["bn"]
        )
        hidden = old * (1 - z) + z * candidate
        readout, head = hidden, params["head"] * fixed["head"]
    logits = 8 * np.tanh((readout @ head + params["head_bias"]) / 8)
    return np.r_[logits, 0.0], hidden


def selected(scores):
    require(
        isinstance(scores, list)
        and len(scores) == 3
        and all(isinstance(v, int) and not isinstance(v, bool) for v in scores)
        and scores[2] == 0,
        "Malformed exact native scores",
    )
    return max(range(3), key=lambda index: (scores[index], index))


def verify_score_receipt(step, episode, elapsed, score_binary_sha):
    scores = step["scores_q24"]
    action = selected(scores)
    require(
        all(abs(value) <= 8 * Q for value in scores),
        "Continuous scores exceed Q24 bound",
    )
    require(
        scores == [int(round(float(value) * Q)) for value in step["scores_float"]],
        "Q24 conversion mismatch",
    )
    source = {
        "row_id": f"{episode['episode_id']}.t{elapsed}",
        "model_sha256": episode["checkpoint_sha256"],
        "objective_sha256": OBJECTIVE,
        "observation_sha256": digest(
            {"features": step["features"], "reset_fraction": step["reset_fraction"]}
        ),
        "state_sha256": digest(
            {"before": step["hidden_before"], "after": step["hidden_after"]}
        ),
        "scores_q24": scores,
    }
    receipt = step["native_receipt"]
    require(
        receipt.get("schema") == "hepta.boundary-policy.score-receipt.v1",
        "Unknown score receipt",
    )
    require(
        all(receipt.get(key) == value for key, value in source.items()),
        "Native input/model/state binding mismatch",
    )
    require(
        receipt.get("native_binary_sha256") == score_binary_sha,
        "Wrong native score host binary",
    )
    require(
        receipt.get("owner_authority") == "DENY_ALL"
        and receipt.get("durable_owner_execution") is False
        and receipt.get("model_inference_executed") is False
        and receipt.get("actual_kernel_calls") == 0
        and receipt.get("actual_ndu_calls") == 1,
        "Direct NDU path contains hidden sparse execution or wrong authority",
    )
    require(
        receipt["action"] == ("keep", "repair", "stop")[action]
        and step["action"] == ("wait", "repair", "stop")[action],
        "Native action disagrees with exact tie rule",
    )
    frontier = [
        name
        for name, value in zip(("keep", "repair", "abstain"), scores)
        if value == max(scores)
    ]
    require(
        sorted(receipt["native_ndu_frontier"]) == sorted(frontier)
        and receipt["tie"] == (len(frontier) > 1),
        "Native frontier/tie mismatch",
    )
    support = digest(
        {
            "schema": "hepta.boundary-policy.score-support.v1",
            "native_binary_sha256": score_binary_sha,
            "row": source,
        }
    )
    require(receipt["support_sha256"] == support, "Native support digest mismatch")
    hash_text(receipt["native_ndu_digest"], "opaque native NDU")
    require(
        receipt["receipt_sha256"]
        == digest({k: v for k, v in receipt.items() if k != "receipt_sha256"}),
        "Native receipt digest mismatch",
    )


def q24_multiply(a, b):
    whole, remainder = divmod(abs(a * b), Q)
    rounded = whole + int(2 * remainder > Q or (2 * remainder == Q and whole % 2))
    return -rounded if a * b < 0 else rounded


def verify_sparse_step(step, episode, elapsed, profile, previous_native):
    x = step["features"]
    expected = {
        "raw_q24": [int(round(v * Q)) for v in x[:15] + x[16:18]],
        "continuous": {
            "margin_q24": int(round(x[11] * Q)),
            "risk_q24": int(round(x[14] * Q)),
            "flow_q24": int(round(x[15] * Q)),
        },
    }
    require(
        step["native_features"] == expected, "Sparse common18 input conversion mismatch"
    )
    row = step["native_row"]
    require(
        row["case_id"] == episode["episode_id"] and row["step"] == elapsed + 1,
        "Sparse case/tick identity mismatch",
    )
    require(
        row["checkpoint_before"] == previous_native, "Sparse checkpoint chain mismatch"
    )
    for name in ("checkpoint_after", "input_feature_digest", "temporal_digest"):
        hash_text(row[name], name)
    require(
        row["profile_masks"] == [True, True, True], "Sparse typed-input mask changed"
    )
    activation = row["activation_q24"]
    require(
        isinstance(activation, list)
        and len(activation) == 20
        and all(
            isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 8 * Q
            for v in activation
        ),
        "Invalid sparse activation",
    )
    scores = [
        bias + sum(q24_multiply(w, a) for w, a in zip(weights, activation))
        for weights, bias in zip(profile["head_weights_q24"], profile["head_bias_q24"])
    ]
    require(row["readout"]["scores_q24"] == scores, "Sparse native head score mismatch")
    action = selected(scores)
    require(
        row["readout"]["action"] == ("keep", "repair", "stop")[action]
        and step["action"] == ("wait", "repair", "stop")[action]
        and row["terminal"] == (action == 2),
        "Sparse NDU action mismatch",
    )
    frontier = [
        name
        for name, score in zip(("keep", "repair", "abstain"), scores)
        if score == max(scores)
    ]
    require(
        sorted(row["readout"]["native_ndu_frontier"]) == sorted(frontier)
        and row["readout"]["tie"] == (len(frontier) > 1),
        "Sparse NDU frontier mismatch",
    )
    hash_text(row["readout"]["native_ndu_digest"], "opaque sparse NDU")
    require(
        row["receipt_digest"]
        == digest({k: v for k, v in row.items() if k != "receipt_digest"}),
        "Sparse row digest mismatch",
    )
    return row["checkpoint_after"]

"""Bound numerical one-step shadow calls; declarations do not prove provenance.

No action, training, readback label or task-utility calculation is performed.
The host supplies the model mapping, units and any training-evidence reference.
"""

from hashlib import sha256
from io import BytesIO
import json
from math import prod
from pathlib import Path
from time import perf_counter, process_time
from zipfile import ZipFile

import numpy as np

from .contracts import JOINT_SUPPORT
from .crossed_training_fit import model_digest
from .models import KINDS, Model, softmax
from .native_ledger import (
    Artifact,
    _canonical,
    _digest,
    _identity,
    _require,
    _snapshot,
    _text,
)

ENCODING = "action_history.encode-v1:v/(1+v);known-bits"
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024


def feature_schema_digest(feature_names):
    """Bind the ordered columns and declared encoding, not its execution."""
    names = list(feature_names)
    _require(1 <= len(names) <= 256, "invalid feature names")
    for name in names:
        _text(name)
    _require(len(set(names)) == len(names), "duplicate feature names")
    return sha256(
        _canonical({"encoding": ENCODING, "feature_names": names})
    ).hexdigest()


def _contract(value, snapshot, checkpoint_sha256, schema_sha256):
    keys = {
        "schema",
        "checkpoint_sha256",
        "feature_names",
        "feature_encoding",
        "feature_schema_sha256",
        "action_columns",
        "joint_support",
        "target_domain",
        "success_definition",
        "duration_unit",
        "cost_unit",
        "model_origin",
        "training_evidence_ref",
    }
    _require(
        type(value) is dict and set(value) == keys, "explicit model contract required"
    )
    _require(
        value["schema"] == "pred1-native-shadow-model-contract-v1",
        "wrong model contract",
    )
    _require(
        value["checkpoint_sha256"] == checkpoint_sha256, "contract checkpoint differs"
    )
    _require(
        value["feature_names"] == snapshot["feature_names"]
        and value["feature_encoding"] == ENCODING
        and value["feature_schema_sha256"] == schema_sha256
        and feature_schema_digest(value["feature_names"]) == schema_sha256,
        "feature schema or mapping differs",
    )
    columns = value["action_columns"]
    _require(
        type(columns) is list and 1 <= len(columns) <= 256, "invalid action columns"
    )
    for name in columns:
        _text(name)
    _require(len(set(columns)) == len(columns), "duplicate action columns")
    _require(
        value["joint_support"] == JOINT_SUPPORT.tolist(), "32-class support differs"
    )
    _require(
        value["target_domain"] == "declared_native_one_step", "native mapping required"
    )
    for name in ("success_definition", "duration_unit", "cost_unit"):
        _text(value[name])
    origin = value["model_origin"]
    _require(
        origin in ("fixture_random_initialization", "declared_native_training"),
        "model origin requires a separately declared native mapping",
    )
    if origin == "fixture_random_initialization":
        _require(
            value["training_evidence_ref"] is None,
            "random model cannot claim training evidence",
        )
    else:
        _text(value["training_evidence_ref"])
    return columns


def _load_verified(path, expected, input_dim, action_dim):
    with Path(path).open("rb") as stream:
        encoded = stream.read(MAX_CHECKPOINT_BYTES + 1)
    _require(len(encoded) <= MAX_CHECKPOINT_BYTES, "checkpoint byte limit exceeded")
    _require(sha256(encoded).hexdigest() == expected, "checkpoint SHA256 differs")
    headers = {}
    with ZipFile(BytesIO(encoded)) as archive:
        entries = archive.infolist()
        _require(
            len(entries) <= 128
            and len({e.filename for e in entries}) == len(entries)
            and sum(e.file_size for e in entries) <= MAX_CHECKPOINT_BYTES,
            "checkpoint expanded byte limit exceeded",
        )
        # ZIP sizes alone do not bound allocations claimed inside NPY headers.
        for entry in entries:
            with archive.open(entry) as stream:
                version = np.lib.format.read_magic(stream)
                _require(version in ((1, 0), (2, 0)), "unsupported NPY version")
                reader = (
                    np.lib.format.read_array_header_1_0
                    if version == (1, 0)
                    else np.lib.format.read_array_header_2_0
                )
                shape, _, dtype = reader(stream, max_header_size=8192)
                _require(
                    len(shape) <= 2
                    and all(type(n) is int and 0 < n <= 256 for n in shape)
                    and not dtype.hasobject
                    and dtype.fields is None
                    and dtype.subdtype is None,
                    "invalid bounded NPY header",
                )
                size = prod(shape) * dtype.itemsize
                _require(
                    stream.tell() + size == entry.file_size
                    and size <= MAX_CHECKPOINT_BYTES,
                    "NPY byte size differs",
                )
            if entry.filename == "config.npy":
                _require(
                    shape == () and dtype.kind in "US" and 0 < dtype.itemsize <= 4096,
                    "invalid checkpoint config header",
                )
            elif entry.filename == "steps.npy":
                _require(
                    shape == () and dtype.kind in "iu" and dtype.itemsize <= 8,
                    "invalid checkpoint steps header",
                )
            else:
                _require(
                    entry.filename.startswith(("p_", "m_", "v_"))
                    and entry.filename.endswith(".npy")
                    and dtype.kind == "f"
                    and dtype.itemsize == 8,
                    "invalid checkpoint parameter header",
                )
            headers[entry.filename] = shape
    _require(
        "config.npy" in headers and "steps.npy" in headers,
        "checkpoint metadata missing",
    )
    with np.load(BytesIO(encoded), allow_pickle=False) as archive:
        config = json.loads(str(archive["config"]))
    _require(
        type(config) is dict
        and set(config)
        == {
            "kind",
            "input_dim",
            "action_dim",
            "output_dim",
            "hidden_dim",
            "seed",
        },
        "checkpoint config fields differ",
    )
    for name in ("input_dim", "action_dim", "output_dim", "hidden_dim"):
        _require(
            type(config[name]) is int and 1 <= config[name] <= 256,
            "invalid checkpoint dimension",
        )
    _require(
        config["kind"] in KINDS
        and type(config["seed"]) is int
        and 0 <= config["seed"] < 2**64,
        "invalid checkpoint model configuration",
    )
    _require(
        config["input_dim"] == input_dim
        and config["action_dim"] == action_dim
        and config["output_dim"] == len(JOINT_SUPPORT),
        "checkpoint dimensions differ",
    )
    template = Model(**config)
    expected_shapes = {"config.npy": (), "steps.npy": ()}
    expected_shapes.update(
        {
            f"{group}_{name}.npy": array.shape
            for group in ("p", "m", "v")
            for name, array in template.params.items()
        }
    )
    _require(headers == expected_shapes, "checkpoint member shapes differ")
    # Reuse the exact verified bytes even if the path changes during inference.
    return Model.load(BytesIO(encoded)), len(encoded)


def _state_digest(state):
    return sha256(
        _canonical({k: v.tolist() for k, v in sorted(state.items())})
    ).hexdigest()


def shadow_predict(
    path,
    snapshot_path,
    checkpoint_path,
    *,
    expected_checkpoint_sha256,
    expected_feature_schema_sha256,
    identity,
    candidates,
    model_contract,
):
    """Score supplied one-step candidates from one shared observed prefix.

    One candidate issues one head call. Units and model-origin declarations are
    retained verbatim; they are not training, authentication or utility evidence.
    """
    wall, cpu = perf_counter(), process_time()
    _digest(expected_checkpoint_sha256)
    _digest(expected_feature_schema_sha256)
    _identity(identity)
    frozen = Artifact.read(snapshot_path)
    snapshot = _snapshot(frozen)
    _require(identity == snapshot["identity"], "snapshot identity differs")
    columns = _contract(
        model_contract,
        snapshot,
        expected_checkpoint_sha256,
        expected_feature_schema_sha256,
    )
    _require(
        type(candidates) is list and 1 <= len(candidates) <= 64,
        "need 1..64 explicit candidate queries",
    )
    queries, ids = [], set()
    for candidate in candidates:
        _require(
            type(candidate) is dict and set(candidate) == {"candidate_id", "action"},
            "candidate fields differ",
        )
        _text(candidate["candidate_id"])
        _require(candidate["candidate_id"] not in ids, "duplicate candidate identity")
        ids.add(candidate["candidate_id"])
        action = np.asarray(candidate["action"], dtype=np.float64)
        _require(
            action.shape == (len(columns),) and np.isfinite(action).all(),
            "candidate action must match finite declared columns",
        )
        queries.append((candidate["candidate_id"], action.copy()))
    model, size = _load_verified(
        checkpoint_path,
        expected_checkpoint_sha256,
        len(snapshot["feature_names"]),
        len(columns),
    )
    parameters_before = model_digest(model, optimizer=True)
    x = np.asarray(snapshot["features"], dtype=np.float64)
    rows = x[-1:] if model.kind == "single_step" else x
    state = model.initial_state()
    for row in rows:
        state = model.observe(row[None, :], state)
        _require(
            all(np.isfinite(value).all() for value in state.values()),
            "nonfinite model state",
        )
    for value in state.values():
        value.setflags(write=False)
    state_before = _state_digest(state)
    predictions = []
    for candidate_id, action in queries:
        logits = model.predict_from_state(state, action[None, :])
        _require(
            logits.shape == (1, len(JOINT_SUPPORT)) and np.isfinite(logits).all(),
            "nonfinite or incorrectly shaped model output",
        )
        probabilities = softmax(logits)
        _require(
            np.isfinite(probabilities).all()
            and (probabilities >= 0).all()
            and np.isclose(probabilities.sum(), 1.0),
            "invalid model probabilities",
        )
        _require(
            _state_digest(state) == state_before,
            "candidate query modified observed state",
        )
        predictions.append(
            {
                "candidate_id": candidate_id,
                "action": action.tolist(),
                "logits": logits[0].tolist(),
                "probabilities": probabilities[0].tolist(),
            }
        )
    _require(
        parameters_before == model_digest(model, optimizer=True),
        "shadow inference modified model",
    )
    artifact = Artifact.make(
        {
            "schema": "pred1-native-model-shadow-v1",
            "identity": identity,
            "snapshot_digest": frozen.digest,
            "snapshot_cursor": snapshot["cursor"],
            "decision_at": snapshot["decision_at"],
            "clock_id": snapshot["clock_id"],
            "checkpoint_sha256": expected_checkpoint_sha256,
            "checkpoint_bytes": size,
            "model_parameter_sha256": model_digest(model),
            "model_optimizer_state_sha256": parameters_before,
            "model_contract": model_contract,
            "model_contract_sha256": sha256(_canonical(model_contract)).hexdigest(),
            "feature_schema_sha256": expected_feature_schema_sha256,
            "state_sha256_before_heads": state_before,
            "state_sha256_after_heads": _state_digest(state),
            "predictions": predictions,
            "metering": {
                "history_encoder_passes": 1,
                "snapshot_rows": len(x),
                "state_transition_calls": len(rows),
                "candidate_head_calls": len(queries),
                "horizon": 1,
                "latent_rollout_steps": 0,
                "action_executions": 0,
                "wall_seconds": perf_counter() - wall,
                "process_cpu_seconds": process_time() - cpu,
                "scope": "validation, checkpoint hash/load/template check and inference; excludes result artifact serialization/hash/save/fsync",
                "physical_cost_complete": False,
                "financial_cost": None,
                "energy_joules": None,
            },
            "independent_evaluation": False,
            "training_performed": False,
            "real_owner_provenance_authenticated": False,
            "native_task_benefit_established": False,
            "scope": "one-step shadow only; no action execution, future labels or counterfactual utility",
        }
    )
    artifact.save(path)
    return artifact

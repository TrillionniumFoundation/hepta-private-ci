"""Exact native handoff transport for admitted complete research checkpoints.

Conversion and restoration confer no scientific or production authority. The
caller supplies the independently pinned controller contract and source closure.
Use a fresh Python process so the verified research modules are loaded afresh.
"""

import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def verified_modules(code, origin, controller_closure, expected_controller_sha):
    code = Path(code).resolve()
    require(len(controller_closure) <= 1_048_576, "bounded controller source closure required")
    current = json.loads(controller_closure)
    require(isinstance(current, dict) and 0 < len(current) <= 256,
            "bounded controller source closure required")
    require(sha(canonical(current)) == expected_controller_sha, "controller source closure changed")
    for identities in (origin, current):
        for name, expected in identities.items():
            require(Path(name).name == name and Path(name).suffix in (".py", ".json")
                    and sha((code/name).read_bytes()) == expected, "executed research source changed")
    names = ("cell_field_state", "cell_learning_models", "cell_field_controller_v7")
    require(all(name+".py" in current for name in names), "complete restore source closure missing")
    sys.path.insert(0, str(code))
    modules = [importlib.import_module(name) for name in names]
    require(all(Path(module.__file__).resolve() == code/(name+".py")
                for module, name in zip(modules, names, strict=True)), "wrong imported source location")
    return modules


def controller_metadata(state, source, expected_contract):
    snapshot = json.loads(source)
    contract = snapshot["contract"]
    require(canonical(snapshot) == source and canonical(contract) == canonical(expected_contract),
            "controller is not the exact independently pinned canonical contract")
    require(contract["optimizer_origin_protocol_sha256"] == state.bindings["protocol_sha256"],
            "optimizer origin protocol was rewritten")
    horizon, p = snapshot["plan_horizon"], state.parameter_count
    actions = np.asarray(snapshot["resolved_actions"], dtype=np.float64).reshape(horizon, p)
    metadata = {"schema": "hepta.cell-controller-handoff.v7",
        "resume_boundary": "committed-state-with-frozen-plan",
        "protocol_sha256": snapshot["protocol_sha256"],
        "optimizer_origin_protocol_sha256": contract["optimizer_origin_protocol_sha256"],
        "controller_source_sha256": contract["controller_source_sha256"],
        "state_sha256": state.digest(), "source_controller_json": source.decode(),
        "source_controller_sha256": sha(source),
        "panel_anchors_sha256": sha(canonical(contract["original_old_anchors"])),
        "panel_identity_sha256": sha(canonical({key: contract[key] for key in
            ("training_sha256", "current_panel_sha256", "old_panel_sha256")})),
        "controller_config_sha256": sha(canonical(contract["configuration"])),
        "receipt_chain_sha256": sha(canonical({key: snapshot[key] for key in
            ("certificate_chain", "receipt_chain", "counters")}))}
    for key in ("original_warmup_state_sha256", "warmup_step_count", "absolute_step", "registered_steps",
                "plan_origin_step", "plan_origin_state_sha256", "plan_horizon", "action_cursor",
                "intended_plan_sha256", "resolved_plan_sha256"):
        metadata[key] = snapshot[key]
    encoded = canonical(metadata)
    require(len(encoded) <= 65536 and len(source) <= 32768, "native controller metadata limit exceeded")
    return encoded, actions


def checkpoint(state, source_controller, expected_contract, code, controller_closure):
    """Validate through the actual frozen loader before encoding any bytes."""
    _, _, controller = verified_modules(code, state.bindings["executed_code_sha256"],
        controller_closure, expected_contract["controller_source_sha256"])
    controller.load_snapshot(source_controller, state, expected_contract,
        expected_sha256=sha(source_controller))
    metadata, actions = controller_metadata(state, source_controller, expected_contract)
    bindings = state.bindings
    cell = f"{bindings['task']}-{bindings['head_mode']}-seed{bindings['seed']}"
    state_metadata = canonical(state._metadata())
    require(len(state_metadata) <= 65536, "native optimizer metadata limit exceeded")
    return {"cell_id": cell, "state_metadata": state_metadata,
        "controller_metadata": metadata, "vector": state.vector().copy(), "actions": actions.copy()}


def _blob(value):
    return struct.pack(">I", len(value))+value


def encode(serving_payload, protocol_sha256, predecessor_sha256, checkpoints):
    require(0 < len(serving_payload) <= 65536 and serving_payload[:8] == b"HPTACV05"
            and 0 < len(checkpoints) <= 64, "bounded existing typed serving payload required")
    data = bytearray(b"HPTHOF07"+bytes.fromhex(protocol_sha256))
    data += bytes([int(predecessor_sha256 is not None)])
    if predecessor_sha256 is not None:
        data += bytes.fromhex(predecessor_sha256)
    data += _blob(serving_payload)+struct.pack(">H", len(checkpoints))
    for row in checkpoints:
        vector = np.asarray(row["vector"], dtype=np.float64)
        actions = np.asarray(row["actions"], dtype=np.float64)
        require(vector.shape in ((108,), (156,)) and actions.ndim == 2
                and actions.shape[1] == len(vector)//3 and len(actions) <= 8
                and np.isfinite(vector).all() and np.isfinite(actions).all(), "finite complete state/plan required")
        data += _blob(row["cell_id"].encode("ascii"))+_blob(row["state_metadata"])+_blob(row["controller_metadata"])
        data += struct.pack(">H", len(vector))+np.asarray(vector, dtype="<f8").tobytes()
        data += bytes([len(actions)])+np.asarray(actions, dtype="<f8").tobytes()
    require(len(data) <= 8*1024*1024, "native handoff envelope limit exceeded")
    return bytes(data)


def restore_native_dump(record, code, controller_closure, expected_contract, output):
    """Restore a native-validated dump with an independently pinned contract.

    Native checks are still required: this function verifies the same full-state
    digest through CellTrainingState.save/load and the actual controller loader.
    The output is an explicit research training branch, never live activation.
    """
    metadata_bytes = record["state_metadata_json"].encode()
    metadata = json.loads(metadata_bytes)
    wrapper_bytes = record["controller_metadata_json"].encode()
    wrapper = json.loads(wrapper_bytes)
    state_module, models, controller = verified_modules(code, metadata["bindings"]["executed_code_sha256"],
        controller_closure, expected_contract["controller_source_sha256"])
    state = state_module.CellTrainingState(models.NumpyCellHead(**metadata["head"]),
        bindings=metadata["bindings"], protocol=metadata["protocol"], contexts=metadata["contexts"],
        active_context=metadata["active_context"])
    vector = np.frombuffer(bytes.fromhex(record["state_vector_le_hex"]), dtype="<f8").copy()
    state.set_vector(vector)
    for name in ("step_count", "sampler_draw_count", "external_batch_count"):
        require(type(metadata[name]) is int and 0 <= metadata[name] < 2**63, "invalid optimizer counter")
        setattr(state, name, metadata[name])
    state.rng.bit_generator.state = metadata["rng"]
    require(canonical(state._metadata()) == metadata_bytes and state.digest() == wrapper["state_sha256"]
            and state.bindings["protocol_sha256"] == wrapper["optimizer_origin_protocol_sha256"],
            "native full-state restoration changed metadata, tensors or origin identity")
    source = wrapper["source_controller_json"].encode()
    snapshot = controller.load_snapshot(source, state, expected_contract,
        expected_sha256=wrapper["source_controller_sha256"])
    regenerated, actions = controller_metadata(state, source, expected_contract)
    require(regenerated == wrapper_bytes
            and np.asarray(actions, dtype="<f8").tobytes().hex() == record["resolved_actions_le_hex"],
            "native controller plan, anchors, counters or cursor changed")
    output = Path(output)
    state.save(output)
    restored = state_module.CellTrainingState.load(output, state.bindings, state.protocol, state.contexts, state.digest())
    (output/"controller.json").write_bytes(source)
    require(restored.digest() == state.digest(), "existing checkpoint loader changed complete state")
    return restored, snapshot

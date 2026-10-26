"""Versioned complete-state transport with explicitly pinned research loaders.

The original controller bytes keep their real schema. No conversion rewrites a
V8 controller as V7 or asserts safety for an uncommitted forecast tail.
"""

import importlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[0]/"../trained-cell-v7"))
from handoff_v7 import canonical, controller_metadata as common_metadata, require, sha


PROFILES = {
    7: ("cell_field_controller_v7", "hepta.cell-field-controller.v7", b"HPTHOF07"),
    8: ("cell_field_controller_v8", "hepta.cell-field-controller.v8", b"HPTHOF08"),
}


def verified_modules(code, origin, closure, expected_sha256, version):
    require(version in PROFILES and len(closure) <= 1_048_576, "bounded explicit controller profile required")
    code = Path(code).resolve()
    current = json.loads(closure)
    require(isinstance(current, dict) and 0 < len(current) <= 256
            and sha(canonical(current)) == expected_sha256, "pinned source closure changed")
    for identities in (origin, current):
        for name, digest in identities.items():
            require(Path(name).name == name and Path(name).suffix in (".py", ".json")
                    and sha((code/name).read_bytes()) == digest, "executed research source changed")
    names = ("cell_field_state", "cell_learning_models", PROFILES[version][0])
    require(all(name+".py" in current for name in names), "complete versioned loader closure missing")
    sys.path.insert(0, str(code))
    modules = [importlib.import_module(name) for name in names]
    require(all(Path(module.__file__).resolve() == code/(name+".py")
                for module, name in zip(modules, names, strict=True)), "stale imported research module")
    return modules


def controller_metadata(state, source, contract, version):
    snapshot = json.loads(source)
    require(version in PROFILES and snapshot["schema"] == PROFILES[version][1],
            "controller mode substitution")
    encoded, actions = common_metadata(state, source, contract)
    if version == 7:
        return encoded, actions
    wrapper = json.loads(encoded)
    wrapper["schema"] = "hepta.cell-controller-handoff.v8"
    for field in ("forecast_horizon", "forecast_plan_sha256"):
        wrapper[field] = snapshot[field]
    return canonical(wrapper), actions


def checkpoint(state, source, contract, code, closure, version):
    _, _, controller = verified_modules(code, state.bindings["executed_code_sha256"], closure,
        contract["controller_source_sha256"], version)
    controller.load_snapshot(source, state, contract, expected_sha256=sha(source))
    metadata, actions = controller_metadata(state, source, contract, version)
    state_metadata = canonical(state._metadata())
    require(len(metadata) <= 65536 and len(state_metadata) <= 65536 and len(source) <= 32768,
            "bounded complete checkpoint metadata required")
    bindings = state.bindings
    return {"cell_id": f"{bindings['task']}-{bindings['head_mode']}-seed{bindings['seed']}",
        "state_metadata": state_metadata, "controller_metadata": metadata,
        "vector": state.vector().copy(), "actions": actions.copy()}


def encode(serving_payload, protocol_sha256, predecessor_sha256, checkpoints, version):
    require(version in PROFILES and 0 < len(serving_payload) <= 65536
            and serving_payload[:8] == b"HPTACV05" and 0 < len(checkpoints) <= 64,
            "bounded explicit handoff profile required")
    def blob(value):
        return struct.pack(">I", len(value))+value
    data = bytearray(PROFILES[version][2]+bytes.fromhex(protocol_sha256))
    data += bytes([int(predecessor_sha256 is not None)])
    if predecessor_sha256 is not None:
        data += bytes.fromhex(predecessor_sha256)
    data += blob(serving_payload)+struct.pack(">H", len(checkpoints))
    for row in checkpoints:
        vector = np.asarray(row["vector"], dtype=np.float64)
        actions = np.asarray(row["actions"], dtype=np.float64)
        require(vector.shape in ((108,), (156,)) and actions.ndim == 2 and len(actions) <= 8
                and actions.shape[1] == len(vector)//3
                and np.isfinite(vector).all() and np.isfinite(actions).all(), "invalid complete numeric state")
        data += blob(row["cell_id"].encode("ascii"))+blob(row["state_metadata"])+blob(row["controller_metadata"])
        data += struct.pack(">H", len(vector))+np.asarray(vector, dtype="<f8").tobytes()
        data += bytes([len(actions)])+np.asarray(actions, dtype="<f8").tobytes()
    require(len(data) <= 8*1024*1024, "bounded handoff envelope required")
    return bytes(data)


def restore_native_dump(record, code, closure, contract, output, version):
    metadata_bytes = record["state_metadata_json"].encode()
    metadata = json.loads(metadata_bytes)
    wrapper_bytes = record["controller_metadata_json"].encode()
    wrapper = json.loads(wrapper_bytes)
    require(wrapper["schema"] == f"hepta.cell-controller-handoff.v{version}", "native wrapper mode differs")
    states, models, controller = verified_modules(code, metadata["bindings"]["executed_code_sha256"],
        closure, contract["controller_source_sha256"], version)
    state = states.CellTrainingState(models.NumpyCellHead(**metadata["head"]), bindings=metadata["bindings"],
        protocol=metadata["protocol"], contexts=metadata["contexts"], active_context=metadata["active_context"])
    state.set_vector(np.frombuffer(bytes.fromhex(record["state_vector_le_hex"]), dtype="<f8").copy())
    for field in ("step_count", "sampler_draw_count", "external_batch_count"):
        require(type(metadata[field]) is int and 0 <= metadata[field] < 2**63, "invalid optimizer counter")
        setattr(state, field, metadata[field])
    state.rng.bit_generator.state = metadata["rng"]
    require(canonical(state._metadata()) == metadata_bytes and state.digest() == wrapper["state_sha256"],
            "native full-state identity changed")
    source = wrapper["source_controller_json"].encode()
    snapshot = controller.load_snapshot(source, state, contract,
        expected_sha256=wrapper["source_controller_sha256"])
    regenerated, actions = controller_metadata(state, source, contract, version)
    require(regenerated == wrapper_bytes and np.asarray(actions, dtype="<f8").tobytes().hex()
            == record["resolved_actions_le_hex"], "forecast, prefix, contract or cursor identity changed")
    output = Path(output)
    state.save(output)
    restored = states.CellTrainingState.load(output, state.bindings, state.protocol, state.contexts, state.digest())
    (output/"controller.json").write_bytes(source)
    require(restored.digest() == state.digest(), "complete checkpoint loader changed state")
    return restored, snapshot

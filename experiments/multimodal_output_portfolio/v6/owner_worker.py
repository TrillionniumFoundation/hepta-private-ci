"""Pinned, one-request CPU backend for the existing InferenceWorker driver.

Paths come from immutable host registration, never generation request fields.
This executes a bounded action sequence; it grants no authority, performs no
training, and does not activate a daemon or qualify neuron calibration.
"""

import hashlib
import io
import json
import math
from pathlib import Path
import platform
import resource
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import numpy as np
import PIL
from PIL import Image
import torch

from experiments.multimodal_output_portfolio.v6 import neural
from experiments.multimodal_output_portfolio.v6.data import Observation, render_tokens

SCHEMA = "hepta.inference.generation.v1"
SOURCE_NAMES = ("conditioned.py", "data.py", "neural.py", "observer.py", "owner_worker.py", "plan_training.py")
MAX_BYTES = 256 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_digest():
    return sha("".join(f"{name}\0{sha(Path(__file__).with_name(name).read_bytes())}\n"
                       for name in SOURCE_NAMES).encode())


def runtime_versions():
    return [platform.python_version(), str(torch.__version__), np.__version__, PIL.__version__]


def device_digest():
    # Reported local CPU platform tuple; this is not unique hardware attestation.
    value = {"system": platform.system(), "release": platform.release(), "machine": platform.machine()}
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def parameters_digest(snapshot):
    if hasattr(snapshot, "_base"):
        # Explicit composition of base/gate tensor identities, separate from
        # full snapshot, configuration and serialized checkpoint identities.
        return sha(b"hepta.inference.generation-weights.v1\0"
                   + neural.parameter_hash(snapshot._base._model).encode()
                   + neural.parameter_hash(snapshot._gate).encode())
    return neural.parameter_hash(snapshot._model)


def exact_fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("Unknown or missing wire fields")


def tensor_bits(values, count, lower, upper):
    if (not isinstance(values, list) or len(values) != count
            or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in values)):
        raise ValueError("Invalid float32 bit vector")
    array = np.asarray(values, dtype="<u4").view("<f4")
    if not np.isfinite(array).all() or (array < lower).any() or (array > upper).any():
        raise ValueError("Unbounded public input")
    return torch.from_numpy(array.copy()).reshape(1, 1, 28, 56)


def validate_checkpoint_config(record, pins):
    """Reject incompatible allocation dimensions before constructing any model.

    The registered native profile permits base widths 16..128 and gate widths
    1..128. Its config digest retains the existing snapshot.config convention;
    the complete checkpoint and snapshot pins also bind controlled gate config.
    """
    if not isinstance(record, dict):
        raise ValueError("Unregistered snapshot record")
    schema = record.get("schema")
    controlled = schema in ("hepta.ndu-v6.controlled-snapshot.v1", "hepta.ndu-v6.controlled-snapshot.v2")
    if controlled:
        from experiments.multimodal_output_portfolio.v6.plan_training import PLANS
        if record.get("plans") != PLANS:
            raise ValueError("Unregistered controlled plan structure")
        if schema.endswith(".v1"):
            base = {"schema": "hepta.ndu-v6.neural-snapshot.v1", "config": record.get("base_config")}
        else:
            base = record.get("base_record")
            if not isinstance(base, dict) or base.get("schema") != neural.CONDITIONED_SCHEMA:
                raise ValueError("Unregistered controlled base structure")
    else:
        base = record
    base_schema, config = base.get("schema"), base.get("config")
    if base_schema == "hepta.ndu-v6.neural-snapshot.v1":
        exact_fields(config, "hidden noise_scale")
    elif base_schema == neural.CONDITIONED_SCHEMA:
        exact_fields(config, "hidden noise_scale architecture command_gain layer_norm_eps")
        if (config["architecture"] != neural.CONDITIONED_ARCHITECTURE
                or config["command_gain"] != .5 or config["layer_norm_eps"] != 1e-5):
            raise ValueError("Unregistered conditioned configuration")
    else:
        raise ValueError("Unregistered snapshot schema")
    width = config["hidden"]
    if (type(pins["hidden"]) is not int or type(width) is not int
            or not 16 <= width <= 128 or width != pins["hidden"]
            or type(config["noise_scale"]) not in (int, float)
            or not math.isfinite(config["noise_scale"]) or not 0 <= config["noise_scale"] <= 1):
        raise ValueError("Unbounded or mismatched checkpoint configuration")
    config_digest = sha(json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    if (config_digest != pins["config_sha256"]
            or (base_schema == neural.CONDITIONED_SCHEMA and base.get("config_sha256") != config_digest)):
        raise ValueError("Snapshot/configuration identity mismatch")
    if controlled:
        gate = record.get("gate_config")
        exact_fields(gate, "context_size hidden")
        if (type(gate["context_size"]) is not int or gate["context_size"] != width
                or type(gate["hidden"]) is not int or not 1 <= gate["hidden"] <= 128):
            raise ValueError("Unbounded or mismatched controlled gate configuration")
    return schema


def execute(envelope):
    exact_fields(envelope, "checkpoint request_json")
    raw = envelope["request_json"].encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("Oversized request")
    request = json.loads(raw)
    exact_fields(request, "schema request_id objective_sha256 input_source_sha256 model required_modalities pixels_f32 mask_f32 text_tokens noise_seed content_control actions")
    pins = request["model"]
    exact_fields(pins, "checkpoint_sha256 snapshot_sha256 parameters_sha256 config_sha256 source_sha256 python_sha256 device_sha256 runtime_versions hidden")
    if (request["schema"] != SCHEMA or type(request["required_modalities"]) is not int
            or request["required_modalities"] != 3 or type(request["content_control"]) is not bool
            or type(request["noise_seed"]) is not int or not 0 <= request["noise_seed"] <= 2**63 - 1
            or not isinstance(request["actions"], list) or len(request["actions"]) > 8
            or any(action not in neural.ACTIONS for action in request["actions"])
            or (not request["content_control"] and any(action not in ("refine_image", "refine_text") for action in request["actions"]))):
        raise ValueError("Unsupported request profile")
    checkpoint = Path(envelope["checkpoint"])
    if checkpoint.is_symlink() or checkpoint.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Unregistered or oversized checkpoint")
    identity = (sha(checkpoint.read_bytes()), source_digest(), sha(Path(sys.executable).read_bytes()))
    if (identity != (pins["checkpoint_sha256"], pins["source_sha256"], pins["python_sha256"])
            or runtime_versions() != pins["runtime_versions"] or device_digest() != pins["device_sha256"]):
        raise ValueError("Registered artifact/source/runtime identity mismatch")
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    record = neural.read_checkpoint(checkpoint, pins["checkpoint_sha256"])
    schema = validate_checkpoint_config(record, pins)
    del record
    if schema in ("hepta.ndu-v6.controlled-snapshot.v1", "hepta.ndu-v6.controlled-snapshot.v2"):
        from experiments.multimodal_output_portfolio.v6.plan_training import ControlledSnapshot
        snapshot = ControlledSnapshot.load(checkpoint, expected_file_sha256=pins["checkpoint_sha256"])
    elif schema in ("hepta.ndu-v6.neural-snapshot.v1", "hepta.ndu-v6.conditioned-snapshot.v2"):
        snapshot = neural.load_snapshot(checkpoint, expected_file_sha256=pins["checkpoint_sha256"])
    else:
        raise ValueError("Unregistered snapshot schema")
    config_digest = sha(json.dumps(snapshot.config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    if (snapshot.fingerprint != pins["snapshot_sha256"] or parameters_digest(snapshot) != pins["parameters_sha256"]
            or config_digest != pins["config_sha256"] or snapshot.config["hidden"] != pins["hidden"]):
        raise ValueError("Snapshot/configuration identity mismatch")
    tokens = request["text_tokens"]
    if not isinstance(tokens, list) or len(tokens) != 8 or any(type(v) is not int or not 0 <= v < 24 for v in tokens):
        raise ValueError("Invalid public tokens")
    pixels = tensor_bits(request["pixels_f32"], 28 * 56, 0, 1)
    mask = tensor_bits(request["mask_f32"], 28 * 56, 0, 1)
    if not ((mask == 0) | (mask == 1)).all():
        raise ValueError("Invalid missingness mask")
    observation = Observation(pixels, mask, torch.tensor([tokens], dtype=torch.long))

    def record(state):
        values = snapshot.state_features(state).detach().cpu().numpy().astype("<f4").reshape(-1)
        if len(values) != 4 * pins["hidden"] or not np.isfinite(values).all() or (np.abs(values) > 8).any():
            raise ValueError("Invalid latent state")
        backend = snapshot.state_key(state)
        plan = state.plan_indices[0] if hasattr(state, "plan_indices") else None
        data = b"hepta.inference.generation-state.v1\0" + snapshot.fingerprint.encode() + backend.encode()
        data += struct.pack("<i", -2 if plan is None else plan) + values.tobytes()
        return {"values_f32": values.view("<u4").tolist(), "backend_state_sha256": backend,
                "plan_index": plan, "state_sha256": sha(data)}

    state = snapshot.encode(observation, noise_seed=request["noise_seed"], content_control=request["content_control"])
    states = [record(state)]
    for action in request["actions"]:
        state = snapshot.step(state, action)
        states.append(record(state))
    output = snapshot.decode(state)
    if not all(torch.isfinite(value).all() for value in (output.image_logits, output.text_logits, output.digit_logits)):
        raise ValueError("Nonfinite decoder output")
    token_ids = output.token_ids[0].tolist()
    caption = render_tokens(token_ids)
    array = (output.image_logits.sigmoid().squeeze().numpy() * 255).round()
    if array.shape != (28, 56) or not np.isfinite(array).all() or array.min() < 0 or array.max() > 255:
        raise ValueError("Invalid decoder pixels")
    array = array.astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    png = buffer.getvalue()
    with Image.open(io.BytesIO(png)) as reopened:
        if reopened.mode != "L" or reopened.size != (56, 28) or not np.array_equal(np.asarray(reopened), array):
            raise ValueError("Emitted PNG round trip differs")
    snapshot.verify_integrity()
    if identity != (sha(checkpoint.read_bytes()), source_digest(), sha(Path(sys.executable).read_bytes())):
        raise ValueError("Artifact/source changed during execution")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    return {"schema": SCHEMA, "request_sha256": sha(raw), "model": pins, "states": states,
            "token_ids": token_ids, "caption": caption, "png": list(png),
            "png_sha256": sha(png), "text_sha256": sha(caption.encode()),
            "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
            "peak_rss_bytes": rss, "authority": "deny_all"}


if __name__ == "__main__":
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Oversized envelope")
    result = json.dumps(execute(json.loads(data)), separators=(",", ":"), allow_nan=False)
    if len(result.encode()) > MAX_BYTES:
        raise ValueError("Oversized execution result")
    print(result)

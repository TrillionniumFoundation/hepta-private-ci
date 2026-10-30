"""Fail-closed, versioned precision contract for the HCSN observation/gap state.

This is an opt-in V2 persistence boundary. Legacy V1 files are accepted only
with an explicit expected floating dtype and the original field schema.
Checksums detect accidental damage, NOT malicious rewriting or provenance.
The original frozen flow/api.py and its scientific receipts are not changed.
"""

import hashlib
import os
from pathlib import Path
import tempfile
import zipfile

import jax
import jax.numpy as jnp
import numpy as np

SCHEMA_V1 = "hcsn_observation_gap_state_v1"
SCHEMA_V2 = "hcsn_observation_gap_state_v2"
PARAMETERS = frozenset((
    "input", "recurrent", "bias", "gate_input", "gate_physical", "gate_bias",
    "dynamics", "raw_physical", "raw_decay", "raw_cost",
))
STATES = frozenset((
    "probability", "content", "physical", "decay", "cost", "elapsed",
    "events", "reward", "observations",
))
METADATA = frozenset(("schema", "precision", "payload_sha256"))
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024


def _digest(arrays):
    """Domain-separated deterministic digest of exact array bytes, shapes and dtypes."""
    h = hashlib.sha256(b"hcsn-observation-gap-checkpoint-v2\0")
    for key in sorted(arrays):
        value = np.asarray(arrays[key])
        h.update(key.encode("utf-8") + b"\0")
        h.update(value.dtype.str.encode("ascii") + b"\0")
        h.update(repr(value.shape).encode("ascii") + b"\0")
        h.update(np.ascontiguousarray(value).tobytes())
    return h.hexdigest()


def _expected(precision):
    if precision not in ("float32", "float64"):
        raise ValueError("Caller must explicitly request float32 or float64")
    if precision == "float64" and not jax.config.jax_enable_x64:
        raise RuntimeError("Refusing float64 restore: enable JAX x64 before initialization")
    return np.dtype(precision)


def _validate_arrays(params, state, dtype):
    if set(params) != PARAMETERS or set(state) != STATES:
        raise ValueError("Missing or unexpected checkpoint fields")
    for collection in (params, state):
        for key, value in collection.items():
            value = np.asarray(value)
            if key == "observations":
                if value.dtype != np.dtype("int32"):
                    raise ValueError("Observation counter must be int32")
            elif value.dtype != dtype:
                raise ValueError(f"{key} dtype {value.dtype} is not {dtype}")
            if not np.isfinite(value).all():
                raise ValueError(f"{key} contains a nonfinite value")

    bias = params["bias"]
    if bias.ndim != 1 or len(bias) == 0:
        raise ValueError("Invalid hidden width")
    width = len(bias)
    incoming = params["input"]
    if incoming.ndim != 2 or incoming.shape[0] <= 0:
        raise ValueError("Invalid input width")
    inp = incoming.shape[0]
    param_shapes = dict(input=(inp, width), recurrent=(width, width),
                        bias=(width,), gate_input=(inp, width),
                        gate_physical=(10, width), gate_bias=(width,),
                        dynamics=(inp, 3), raw_physical=(5,),
                        raw_decay=(width,), raw_cost=())
    state_shapes = dict(probability=(10,), content=(width,), physical=(5,),
                        decay=(width,), cost=(), elapsed=(), events=(), reward=(),
                        observations=())
    if any(params[k].shape != shape for k, shape in param_shapes.items()):
        raise ValueError("Invalid parameter tensor dimensions")
    if any(state[k].shape != shape for k, shape in state_shapes.items()):
        raise ValueError("Invalid state tensor dimensions")

    p, theta = state["probability"], state["physical"]
    tol = 1e-5 if dtype == np.dtype("float32") else 1e-10
    if p.min() < -tol or abs(float(p.sum(dtype=np.float64)) - 1.) > tol:
        raise ValueError("Active plus refractory mass not conserved")
    lower = np.array([-.3, .3, .35, -.3, .3])
    upper = np.array([.5, .6, 1.5, .1, 1.2])
    if np.any(theta < lower - 1e-7) or np.any(theta > upper + 1e-7):
        raise ValueError("Physical state is outside declared finite domain")
    if not (np.all((state["decay"] > 0.02 - tol) & (state["decay"] < .2 + tol))
            and 0.1 - tol <= float(state["cost"]) <= .5 + tol):
        raise ValueError("Decay or cost state outside admitted range")
    if (float(state["elapsed"]) < 0 or float(state["events"]) < -tol
            or int(state["observations"]) < 0):
        raise ValueError("Invalid cumulative time/event/observation counters")


def _archive_entries(path, limit):
    with zipfile.ZipFile(path) as archive:
        names = [entry.filename for entry in archive.infolist()]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate ZIP archive member")
        if not names or len(names) > 25 or any(not name.endswith(".npy") for name in names):
            raise ValueError("Unexpected archive members")
        if sum(e.file_size for e in archive.infolist()) > limit:
            raise ValueError("Uncompressed checkpoint exceeds byte limit")


def load_checked(path, *, expected_precision, max_bytes=MAX_UNCOMPRESSED_BYTES):
    """Restore V1/V2 arrays without silent JAX float64->float32 conversion."""
    dtype = _expected(expected_precision)
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    _archive_entries(path, max_bytes)
    with np.load(path, allow_pickle=False) as archive:
        names = set(archive.files)
        if "schema" not in names:
            raise ValueError("Missing checkpoint version")
        version = str(np.asarray(archive["schema"]).item())
        if version == SCHEMA_V1:
            expected = {"schema"}
        elif version == SCHEMA_V2:
            expected = METADATA
        else:
            raise ValueError("Unknown checkpoint schema")
        field_names = {f"params__{k}" for k in PARAMETERS} | {f"state__{k}" for k in STATES}
        if names != expected | field_names:
            raise ValueError("Missing or unexpected checkpoint fields")
        params = {k: np.asarray(archive[f"params__{k}"]) for k in PARAMETERS}
        state = {k: np.asarray(archive[f"state__{k}"]) for k in STATES}
        _validate_arrays(params, state, dtype)
        if version == SCHEMA_V2:
            if str(np.asarray(archive["precision"]).item()) != expected_precision:
                raise ValueError("Checkpoint precision metadata mismatch")
            observed = str(np.asarray(archive["payload_sha256"]).item())
            if observed != _digest({**{f"params__{k}": v for k, v in params.items()},
                                    **{f"state__{k}": v for k, v in state.items()}}):
                raise ValueError("Checkpoint checksum mismatch")
    jparams = {k: jnp.asarray(v) for k, v in params.items()}
    jstate = {k: jnp.asarray(v) for k, v in state.items()}
    if any(np.dtype(v.dtype) != dtype for v in (*jparams.values(), *(
            v for k, v in jstate.items() if k != "observations"))):
        raise RuntimeError("JAX changed the floating-point precision during restore")
    return jparams, jstate


def save_v2(path, params, state, *, precision):
    """Write a new, checksummed snapshot; refuse replacement of existing files."""
    dtype = _expected(precision)
    normalized_params = {k: np.asarray(v) for k, v in params.items()}
    normalized_state = {k: np.asarray(v) for k, v in state.items()}
    _validate_arrays(normalized_params, normalized_state, dtype)
    arrays = {**{f"params__{k}": v for k, v in normalized_params.items()},
              **{f"state__{k}": v for k, v in normalized_state.items()}}
    arrays["schema"] = np.asarray(SCHEMA_V2)
    arrays["precision"] = np.asarray(precision)
    arrays["payload_sha256"] = np.asarray(_digest({k: v for k, v in arrays.items()
                                                   if k.startswith(("params__", "state__"))}))
    dest = Path(path)
    if dest.exists():
        raise FileExistsError("Never overwrite an existing checkpoint")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=".hcsn-", suffix=".npz",
                                     delete=False) as handle:
        tmp = Path(handle.name)
    try:
        np.savez(tmp, **arrays)
        _archive_entries(tmp, MAX_UNCOMPRESSED_BYTES)
        if dest.exists():
            raise FileExistsError("Checkpoint appeared during save")
        os.link(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)

"""CPU generation checkpoints with exact frozen identities and cold continuation.

Only primitive containers and tensors are serialized, and loading always uses
``weights_only=True``. Digests detect changed artifacts; they are not signatures.
Bitwise continuation applies to the recorded CPU runtime and supplied budget
schedule. Physical wall/CPU cost and native-owner receipts remain runtime-owned.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import tempfile

import torch

from .contract import JointGenerationProfile, canonical, digest
from .hepta_core import STATE_FIELDS
from .model import ACTIONS, MODALITIES, JointGenerator, State, tensor_digest


SCHEMA = "hepta.joint-generation.checkpoint.v1"
NAMED_SCHEMA = "hepta.joint-generation.checkpoint.v2"
NAMED_RNG_LAW = "separate_actor_and_emission_cpu_streams.v1"
HERE = Path(__file__).parent
MAX_BYTES = 256 * 1024 * 1024


def _safe(value, depth=0):
    if depth > 32:
        raise ValueError("Checkpoint nesting is excessive")
    if torch.is_tensor(value):
        if value.device.type != "cpu" or value.layout != torch.strided:
            raise ValueError("This checkpoint profile supports dense CPU tensors only")
        if value.is_floating_point() and not bool(torch.isfinite(value).all()):
            raise ValueError("Checkpoint tensors must be finite")
        return value.detach().contiguous().clone()
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (list, tuple):
        return type(value)(_safe(item, depth + 1) for item in value)
    if isinstance(value, dict) and all(type(key) is str for key in value):
        return {key: _safe(item, depth + 1) for key, item in value.items()}
    raise ValueError("Checkpoint contains an unsafe or nonfinite value")


def _profile(value):
    raw = value.to_dict() if isinstance(value, JointGenerationProfile) else value
    return JointGenerationProfile.from_dict(raw)


def _sources():
    paths = [HERE / name for name in ("model.py", "hepta_core.py", "contract.py", "checkpoint.py", "runtime.py", "media.py")]
    paths.append(HERE.parent / "unified_20261028/profile.py")
    return {str(path.relative_to(HERE.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def generation_metadata(model, public, profile, **extras):
    """Bind before encoding/advancing; pass the same anchor to every later save."""
    anchor = {"schema": "hepta.joint-generation.episode-anchor.v1",
              "parameter_snapshot_sha256": tensor_digest(model.state_dict()),
              "input_sha256": tensor_digest(public), "profile_sha256": _profile(profile).digest}
    if set(extras) & set(anchor):
        raise ValueError("Generation metadata cannot override its initial episode identities")
    return _safe({**anchor, **extras})


def _named_states(value):
    if not isinstance(value, dict) or set(value) != {"actor", "emission"}:
        raise ValueError("Named RNGs must contain exactly actor and emission")
    states = _safe(value)
    for state in states.values():
        if not torch.is_tensor(state) or state.dtype != torch.uint8 or state.ndim != 1:
            raise ValueError("Named RNG states must be one-dimensional CPU byte tensors")
        try:
            torch.Generator(device="cpu").set_state(state)
        except RuntimeError as exc:
            raise ValueError("Unsupported named CPU RNG state") from exc
    return states


def restore_named_rngs(metadata):
    """Restore isolated generators; no physical clocks or execution ledger."""
    if metadata.get("named_rng_law") != NAMED_RNG_LAW:
        raise ValueError("Unsupported or missing named RNG law")
    states = _named_states(metadata.get("named_rng_states"))
    result = {}
    for name, state in states.items():
        result[name] = torch.Generator(device="cpu")
        result[name].set_state(state)
    return result


def _validate_state(model, state):
    if not isinstance(state, State) or type(state.steps) is not int or state.steps < 0 or type(state.stopped) is not bool:
        raise ValueError("Invalid generation state clock")
    anchor = next(model.parameters())
    batch = state.context.shape[0] if state.context.ndim == 2 else 0
    shapes = {"context": (batch, model.width), "shared": (batch, model.width),
              "slots": (batch, 4, model.width), "feedback": (batch, 3)}
    if batch < 1 or len(state.core) != model.config["depth"]:
        raise ValueError("Generation state shape/depth differs from model")
    values = [(getattr(state, key), shape) for key, shape in shapes.items()]
    for layer in state.core:
        if set(layer) != set(STATE_FIELDS):
            raise ValueError("Hepta persistent state is incomplete")
        values.extend((value, (batch, model.width)) for value in layer.values())
    if any(value.shape != shape or value.device != anchor.device or value.dtype != anchor.dtype
           or not bool(torch.isfinite(value).all()) for value, shape in values):
        raise ValueError("Persistent tensors differ in shape/device/dtype or are nonfinite")


def save_checkpoint(path, model, state, rng, profile, public, metadata=None, *, named_rngs=None):
    """Write an immutable .pt plus .manifest.json; return externally hashable IDs.

    A noninitial state requires an anchor obtained by ``generation_metadata``
    before the episode started. The live model cannot change under that anchor.
    With named_rngs, rng is the actor stream and schema v2 additionally binds
    the independent emission stream. Omitting it preserves the v1 single-RNG API.
    """
    profile = _profile(profile)
    if metadata is None:
        if state.steps:
            raise ValueError("A mid-episode checkpoint requires the initial parameter anchor")
        metadata = generation_metadata(model, public, profile)
    metadata = _safe(metadata)
    if set(metadata) & {"named_rng_states", "named_rng_law"}:
        raise ValueError("Named RNG fields are supplied through named_rngs, not user metadata")
    expected = generation_metadata(model, public, profile)
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError("Model/profile/input changed during the anchored episode")
    _validate_state(model, state)
    if str(rng.device) != "cpu":
        raise ValueError("The registered generation RNG is CPU-only")
    named = None
    if named_rngs is not None:
        if (not isinstance(named_rngs, dict) or set(named_rngs) != {"actor", "emission"}
                or any(not isinstance(g, torch.Generator) or str(g.device) != "cpu" for g in named_rngs.values())
                or named_rngs["actor"] is named_rngs["emission"]):
            raise ValueError("Supply separate CPU actor and emission generators")
        named = _named_states({name: generator.get_state() for name, generator in named_rngs.items()})
        if not torch.equal(rng.get_state(), named["actor"]):
            raise ValueError("The legacy rng argument must identify the named actor state")
    config = _safe(model.config)
    dtype = str(next(model.parameters()).dtype)
    if dtype not in ("torch.float32", "torch.float64"):
        raise ValueError("Checkpoint supports float32/float64 generation")
    runtime = {"torch": str(torch.__version__), "python": platform.python_version(),
               "machine": platform.machine(), "threads": torch.get_num_threads(),
               "interop_threads": torch.get_num_interop_threads(),
               "deterministic": torch.are_deterministic_algorithms_enabled(),
               "warn_only": torch.is_deterministic_algorithms_warn_only_enabled(),
               "matmul_precision": torch.get_float32_matmul_precision(),
               "mkldnn_enabled": bool(torch.backends.mkldnn.enabled),
               "mkldnn_deterministic": bool(torch.backends.mkldnn.deterministic)}
    if named is not None:
        import numpy as np
        from PIL import __version__ as pillow_version
        runtime.update(numpy=np.__version__, pillow=pillow_version)
    payload = _safe({"schema": NAMED_SCHEMA if named is not None else SCHEMA, "config": config, "dtype": dtype,
                     "model": dict(model.state_dict()), "state": state.tensors(),
                     "training": {name: module.training for name, module in model.named_modules()},
                     "rng": rng.get_state(), "global_rng": torch.get_rng_state(),
                     "profile": profile.to_dict(), "metadata": metadata,
                     "runtime": runtime, "source_sha256": _sources(),
                     **({"named_rng_states": named, "named_rng_law": NAMED_RNG_LAW} if named is not None else {})})
    identities = {"schema": payload["schema"], "payload_sha256": tensor_digest(payload),
                  "model_sha256": tensor_digest(payload["model"]), "state_sha256": tensor_digest(payload["state"]),
                  "profile_sha256": profile.digest, "input_sha256": tensor_digest(public),
                  "config_sha256": digest(config), "generation_sha256": tensor_digest(metadata),
                  "rng_sha256": tensor_digest({"episode": payload["rng"], "global": payload["global_rng"]})}
    if named is not None:
        identities["named_rng_sha256"] = tensor_digest(named)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    manifest = path.with_suffix(path.suffix + ".manifest.json")
    if path.exists() or manifest.exists():
        raise FileExistsError("Generation checkpoints are immutable")
    with path.open("xb") as handle:
        torch.save(payload, handle)
    identities["file_bytes"] = path.stat().st_size
    identities["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with manifest.open("x", encoding="utf-8") as handle:
        json.dump(identities, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    return identities


def load_checkpoint(path, *, profile=None, public=None):
    """Return model, State, actor/legacy RNG, metadata with optional named states."""
    path = Path(path)
    identities = json.loads(path.with_suffix(path.suffix + ".manifest.json").read_text())
    if (path.stat().st_size > MAX_BYTES or path.stat().st_size != identities["file_bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != identities["file_sha256"]):
        raise ValueError("Checkpoint bytes differ from their frozen manifest")
    payload = _safe(torch.load(path, map_location="cpu", weights_only=True))
    named = None
    if payload["schema"] == NAMED_SCHEMA:
        if payload.get("named_rng_law") != NAMED_RNG_LAW:
            raise ValueError("Checkpoint named RNG law changed")
        named = _named_states(payload.get("named_rng_states"))
        if not torch.equal(payload["rng"], named["actor"]):
            raise ValueError("Checkpoint actor RNG identities disagree")
    elif payload["schema"] != SCHEMA or "named_rng_states" in payload or "named_rng_law" in payload:
        raise ValueError("Unsupported checkpoint RNG schema")
    restored_profile = _profile(payload["profile"])
    checks = {"schema": payload["schema"], "payload_sha256": tensor_digest(payload),
              "model_sha256": tensor_digest(payload["model"]), "state_sha256": tensor_digest(payload["state"]),
              "profile_sha256": restored_profile.digest, "input_sha256": payload["metadata"]["input_sha256"],
              "config_sha256": digest(payload["config"]), "generation_sha256": tensor_digest(payload["metadata"]),
              "rng_sha256": tensor_digest({"episode": payload["rng"], "global": payload["global_rng"]})}
    if named is not None:
        checks["named_rng_sha256"] = tensor_digest(named)
    if any(identities.get(key) != value for key, value in checks.items()):
        raise ValueError("Checkpoint tensor/model/profile identities disagree")
    if (profile is not None and canonical(_profile(profile).to_dict()) != canonical(payload["profile"])):
        raise ValueError("Requested profile differs from the exact frozen profile")
    if public is not None and tensor_digest(public) != identities["input_sha256"]:
        raise ValueError("Public input differs from the checkpointed episode")
    if payload["source_sha256"] != _sources():
        raise ValueError("Generation implementation changed since the checkpoint")
    runtime, config = payload["runtime"], payload["config"]
    if named is not None:
        import numpy as np
        from PIL import __version__ as pillow_version
        if runtime.get("numpy") != np.__version__ or runtime.get("pillow") != pillow_version:
            raise ValueError("Bitwise codec continuation requires the recorded NumPy/Pillow versions")
    if (runtime["torch"] != str(torch.__version__) or runtime["python"] != platform.python_version()
            or runtime["machine"] != platform.machine()):
        raise ValueError("Bitwise continuation requires the recorded CPU software/architecture")
    if (set(config) != {"width", "depth", "mode", "boundary"} or type(config["width"]) is not int
            or type(config["depth"]) is not int or not 1 <= config["width"] <= 512 or not 1 <= config["depth"] <= 16):
        raise ValueError("Checkpoint model configuration exceeds the bounded research profile")
    if payload["dtype"] not in ("torch.float32", "torch.float64"):
        raise ValueError("Unregistered checkpoint tensor precision")
    torch.set_num_threads(runtime["threads"])
    if torch.get_num_interop_threads() != runtime["interop_threads"]:
        torch.set_num_interop_threads(runtime["interop_threads"])
    torch.use_deterministic_algorithms(runtime["deterministic"], warn_only=runtime["warn_only"])
    torch.set_float32_matmul_precision(runtime["matmul_precision"])
    torch.backends.mkldnn.enabled = runtime["mkldnn_enabled"]
    torch.backends.mkldnn.deterministic = runtime["mkldnn_deterministic"]
    model = JointGenerator(**config).to(dtype=getattr(torch, payload["dtype"].split(".")[-1]))
    model.load_state_dict(payload["model"], strict=True)
    modules = dict(model.named_modules())
    if set(modules) != set(payload["training"]):
        raise ValueError("Checkpoint module execution modes are incomplete")
    for name, module in modules.items():
        if type(payload["training"][name]) is not bool:
            raise ValueError("Invalid module execution mode")
        module.training = payload["training"][name]
    state = State(**payload["state"])
    _validate_state(model, state)
    metadata = payload["metadata"]
    if (metadata["parameter_snapshot_sha256"] != tensor_digest(model.state_dict())
            or metadata["profile_sha256"] != restored_profile.digest):
        raise ValueError("Loaded weights differ from the episode parameter anchor")
    rng = torch.Generator(device="cpu"); rng.set_state(payload["rng"])
    torch.set_rng_state(payload["global_rng"])
    named_info = {"named_rng_states": named, "named_rng_law": NAMED_RNG_LAW} if named is not None else {}
    return model, state, rng, {**metadata, "profile": payload["profile"],
                             "checkpoint_identities": identities, **named_info}


def continuation_digest(model, state, rng, public, actions, metadata):
    """Continue registered transitions and stochastic emission in a cold process.

    An action named ``sample`` samples the actor; other names force that action.
    The deterministic service-cost schedule is a checkpoint verification fixture,
    not a substitute for the physically measured deployment ledger.
    Named v2 streams also run the real codecs and compare emitted file bytes.
    """
    from .runtime import HORIZON, INITIAL_BUDGET, TARIFF
    profile = _profile(metadata["profile"])
    if (metadata["parameter_snapshot_sha256"] != tensor_digest(model.state_dict())
            or metadata["input_sha256"] != tensor_digest(public) or metadata["profile_sha256"] != profile.digest):
        raise ValueError("Continuation violates its frozen model/input/profile anchor")
    budget = float(metadata.get("remaining_budget", INITIAL_BUDGET))
    named = restore_named_rngs(metadata) if "named_rng_states" in metadata else None
    actor_rng, emission_rng = (named["actor"], named["emission"]) if named is not None else (rng, rng)
    if named is not None and not torch.equal(rng.get_state(), actor_rng.get_state()):
        raise ValueError("Supplied actor RNG differs from the frozen named state")
    records = []
    with torch.no_grad():
        for requested in actions:
            if state.stopped:
                break
            if requested not in (*ACTIONS, "sample"):
                raise ValueError("Unknown continuation action")
            law, _ = model.policy(state, budget / INITIAL_BUDGET, HORIZON)
            # Match execute(): forced horizon STOP does not consume an actor draw.
            if requested == "sample" and state.steps >= HORIZON:
                index = ACTIONS.index("stop")
            elif requested == "sample":
                index = int(torch.multinomial(law.exp(), 1, generator=actor_rng).item())
            else:
                index = ACTIONS.index(requested)
            if not bool(torch.isfinite(law[:, index]).all()):
                raise ValueError("Continuation action violates the frozen horizon mask")
            action = ACTIONS[index]
            record = {"requested": requested, "action": action, "actor_probabilities": law.exp().tolist(),
                      "actor_log_law_sha256": tensor_digest(law), "before_sha256": tensor_digest(state.tensors())}
            state, _ = model.advance(state, action, public)
            budget -= TARIFF[action]
            record["after_sha256"] = tensor_digest(state.tensors()); records.append(record)
        sampled, _, probability = model.sample(state, emission_rng)
    if tensor_digest(model.state_dict()) != metadata["parameter_snapshot_sha256"]:
        raise ValueError("Model parameters changed during continuation")
    named_result = {}
    if named is not None:
        from .media import write_read
        with tempfile.TemporaryDirectory(prefix="hepta-cold-codec-") as temporary:
            readback, artifacts = write_read(sampled, Path(temporary) / "outputs",
                audio_rate=metadata.get("audio_rate", 2048), frame_ms=metadata.get("frame_ms", 120))
        named_result = {"named_rng_law": NAMED_RNG_LAW,
                        "named_rng_sha256": {name: tensor_digest(generator.get_state()) for name, generator in named.items()},
                        "artifact_sha256": artifacts, "readback_sha256": tensor_digest(readback)}
    return {"schema": "hepta.joint-generation.cold-continuation.v1", "actions": records,
            "model_sha256": metadata["parameter_snapshot_sha256"], "profile_sha256": profile.digest,
            "input_sha256": metadata["input_sha256"], "state_sha256": tensor_digest(state.tensors()),
            "emission_sha256": tensor_digest(sampled), "emission_log_probability_sha256": tensor_digest(probability),
            "emission_log_probability": probability.tolist(), "rng_sha256": tensor_digest(actor_rng.get_state()),
            "global_rng_sha256": tensor_digest(torch.get_rng_state()), "remaining_fixture_budget": budget,
            "physical_runtime_ledger_included": False, **named_result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--actions", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.public.stat().st_size > MAX_BYTES:
        raise ValueError("Public tensor input exceeds the bounded checkpoint profile")
    public = _safe(torch.load(args.public, map_location="cpu", weights_only=True))
    model, state, rng, metadata = load_checkpoint(args.resume, public=public)
    result = continuation_digest(model, state, rng, public, args.actions.split(","), metadata)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")

"""Frozen V4 RR feature execution with lossless state/RNG snapshots.

This is a research inference backend, not a production inference owner. Native
V1 sparse state and this external RR state remain explicitly distinct.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import subprocess

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
Q = 1 << 24
ZERO = "0" * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1 << 20):
            hasher.update(block)
    return hasher.hexdigest()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("BoundedProtocolDocumentExceeded")
    return json.loads(path.read_text())


def owned(root, relative):
    if Path(relative).is_absolute():
        raise ValueError("AbsoluteOwnedArtifactPathRejected")
    path = (Path(root) / relative).resolve()
    path.relative_to(Path(root).resolve())
    return path


def write(path, value, immutable=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = canonical(value)
    if immutable and path.exists():
        if path.read_bytes() != data:
            raise ValueError("ConflictingImmutableArtifact")
        return sha(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="write-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return sha(path)


def validate_current_execution_identity(manifest):
    for name, expected in manifest["source_sha256"].items():
        if sha(WORKSPACE / name) != expected:
            raise ValueError("FrozenSourceIdentityMismatch")
    if sha(manifest["artifact_path"]) != manifest["artifact_sha256"]:
        raise ValueError("FrozenWeightArtifactMismatch")
    if sha(manifest["native_binary_path"]) != manifest["native_binary_sha256"]:
        raise ValueError("FrozenNativeBinaryMismatch")


def load_policy(manifest):
    validate_current_execution_identity(manifest)
    sys.path.insert(0, str(WORKSPACE))
    import numpy as np
    import torch
    from rrsnn_v4.models import RRPolicy
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    blob = torch.load(manifest["artifact_path"], map_location="cpu", weights_only=True)
    metadata = blob["metadata"]
    if blob["variant"] != "rr_full":
        raise ValueError("OnlyFrozenRRFullFeatureProfile")
    model = RRPolicy(input_size=metadata["input_size"], hidden_size=metadata["hidden_size"],
                     grid_size=metadata["grid_size"], refractory_phases=metadata["refractory_phases"],
                     trace_tau=metadata["trace_tau"], variant="rr_full")
    model.load_state_dict(blob["state_dict"], strict=True)
    model.eval()
    if model.input_size != 22 or model.hidden_size != 8:
        raise ValueError("UnsupportedFeatureBridgeDimensions")
    if str(torch.__version__) != manifest["torch_version"] or np.__version__ != manifest["numpy_version"]:
        raise ValueError("NumericRuntimeIdentityMismatch")
    return model, np, torch


def snapshot(state, rng, binding):
    import numpy as np
    import torch
    fields = {}
    for name, value in vars(state).items():
        array = value.detach().cpu().numpy() if torch.is_tensor(value) else value
        array = np.ascontiguousarray(array)
        fields[name] = {"kind": "torch" if torch.is_tensor(value) else "numpy",
                        "dtype": array.dtype.str, "shape": list(array.shape),
                        "bytes_hex": array.tobytes().hex()}
    random_state = json.loads(json.dumps(rng.bit_generator.state))
    for name in ("state", "inc"):
        random_state["state"][name] = str(random_state["state"][name])
    return {"schema": "rrsnn.v4.lossless-feature-state.v1", "binding": binding,
            "fields": fields, "pcg64": random_state}


def restore(value, binding, hidden=8, state_size=18):
    import numpy as np
    import torch
    from rrsnn_v4.models import CoupledState
    if set(value) != {"schema", "binding", "fields", "pcg64"} or value["binding"] != binding:
        raise ValueError("ExecutionStateBindingMismatch")
    if value["schema"] != "rrsnn.v4.lossless-feature-state.v1":
        raise ValueError("ExecutionStateSchemaMismatch")
    expected = {"indices": ("numpy", "<i8", [1, hidden]), "trace": ("numpy", "<f8", [1, hidden]),
        "context": ("torch", "<f4", [1, hidden]), "drift": ("torch", "<f4", [1, hidden]),
        "boundary": ("torch", "<f4", [1, hidden]), "time": ("numpy", "<f8", [1]),
        "total_counts": ("numpy", "<i8", [1, hidden]), "observed": ("numpy", "|b1", [1]),
        "pending_initial_score": ("torch", "<f8", [1]), "initial_resource": ("torch", "<f4", [1, 1])}
    if set(value["fields"]) != set(expected):
        raise ValueError("MissingOrUnknownExecutionStateField")
    decoded = {}
    for name, (kind, dtype, shape) in expected.items():
        record = value["fields"][name]
        if set(record) != {"kind", "dtype", "shape", "bytes_hex"} or (record["kind"], record["dtype"], record["shape"]) != (kind, dtype, shape):
            raise ValueError("ExecutionStateNumericProfileMismatch")
        array = np.frombuffer(bytes.fromhex(record["bytes_hex"]), dtype=dtype).copy().reshape(shape)
        if not np.isfinite(array).all():
            raise ValueError("NonfiniteExecutionState")
        decoded[name] = torch.from_numpy(array) if kind == "torch" else array
    if ((decoded["indices"] < 0).any() or (decoded["indices"] >= state_size).any()
            or (decoded["trace"] < 0).any() or (decoded["time"] < 0).any()
            or (decoded["total_counts"] < 0).any()):
        raise ValueError("InvalidExecutionStateRange")
    random_state = json.loads(json.dumps(value["pcg64"]))
    if (set(random_state) != {"bit_generator", "state", "has_uint32", "uinteger"}
            or random_state["bit_generator"] != "PCG64"
            or set(random_state["state"]) != {"state", "inc"}
            or type(random_state["has_uint32"]) is not int or random_state["has_uint32"] not in (0, 1)
            or type(random_state["uinteger"]) is not int or not 0 <= random_state["uinteger"] < 2**32):
        raise ValueError("InvalidPCG64Profile")
    for name in ("state", "inc"):
        raw = random_state["state"][name]
        if not isinstance(raw, str) or not raw.isdecimal() or str(int(raw)) != raw or not 0 <= int(raw) < 2**128:
            raise ValueError("InvalidPCG64Integer")
        random_state["state"][name] = int(raw)
    rng = np.random.Generator(np.random.PCG64())
    rng.bit_generator.state = random_state
    return CoupledState(**decoded), rng


def initialize(root, manifest_path, seed):
    root = Path(root)
    root.mkdir(mode=0o700)
    manifest = read(manifest_path)
    model, np, torch = load_policy(manifest)
    rng = np.random.default_rng(seed)
    with torch.no_grad():
        state = model.initial_state(1, rng)
    binding = {"manifest_sha256": sha(manifest_path), "artifact_sha256": manifest["artifact_sha256"]}
    state_value = snapshot(state, rng, binding)
    state_path = root / "states" / (digest(state_value) + ".json")
    write(state_path, state_value)
    frontier = {"schema": "rrsnn.v4.feature-joint-frontier.v1", "manifest_sha256": sha(manifest_path),
        "sequence": 0, "native_checkpoint": ZERO, "state_path": str(state_path.relative_to(root)),
        "state_sha256": sha(state_path), "history": [], "previous_frontier_sha256": None}
    write(root / "frontier.json", frontier)
    return {"frontier_sha256": sha(root / "frontier.json"), "state_sha256": sha(state_path)}


def memory(field):
    lines = Path("/proc/self/status").read_text().splitlines()
    return int(next(line for line in lines if line.startswith(field)).split()[1]) * 1024


def reference(manifest_path, admissions_path, seed):
    manifest = read(manifest_path)
    model, np, torch = load_policy(manifest)
    rng = np.random.default_rng(seed)
    binding = {"manifest_sha256": sha(manifest_path), "artifact_sha256": manifest["artifact_sha256"]}
    rows = []
    with torch.no_grad():
        state = model.initial_state(1, rng)
        for path in read(admissions_path):
            admission = read(path)
            observation = torch.tensor([admission["features_q24"]], dtype=torch.float32) / Q
            state, output = model.step(state, observation, admission["dt_micros"] / 1e6, rng,
                                       event_mask=admission["event_mask"], record_spikes=True)
            rows.append({"state_sha256": digest(snapshot(state, rng, binding)),
                "drive_q24": np.rint(output["latent"][0].numpy().astype(np.float64) * Q).astype(np.int64).tolist(),
                "actual_internal_spikes": int(output["actual_counts"].sum()), "spike_times": output["spike_times"]})
    return {"rows": rows, "scope": "uninterrupted frozen RRPolicy execution, no sidecar/native owner"}


def prepare(root, manifest_path, admission_path, request):
    root = Path(root)
    manifest = read(manifest_path)
    # Cached execution is historical evidence, but current admitted code/weights
    # must still match the frozen identity before that evidence can be reused.
    validate_current_execution_identity(manifest)
    admission = read(admission_path)
    frontier = read(root / "frontier.json")
    if sha(manifest_path) != admission["manifest_sha256"] or sha(root / "frontier.json") != admission["expected_frontier_sha256"]:
        raise ValueError("TrustedFrontierOrManifestMismatch")
    if (request["admission_sha256"] != sha(admission_path)
            or request["request"]["feature_vector_q24"] != admission["features_q24"]
            or request["request"]["weights_digest"] != manifest["weights_digest"]
            or request["request"]["model_id"] != manifest["model_id"]
            or request["request"]["expected_output_width"] != 8
            or admission["previous_native_checkpoint"] != frontier["native_checkpoint"]
            or admission["sequence"] != frontier["sequence"] + 1):
        raise ValueError("RequestAdmissionBindingMismatch")
    if sha(owned(root, frontier["state_path"])) != frontier["state_sha256"]:
        raise ValueError("ExternalRRStatePinMismatch")
    described = subprocess.run([manifest["native_binary_path"], "describe", str(manifest_path), str(admission_path)],
                               capture_output=True, text=True, timeout=30)
    if described.returncode or canonical(json.loads(described.stdout)) != canonical(request):
        raise ValueError("OfficialRequestDescriptorMismatch")
    key = digest({"request_digest": request["request_digest"], "admission_sha256": sha(admission_path),
                  "previous_frontier_sha256": sha(root / "frontier.json"), "manifest_sha256": sha(manifest_path)})
    trusted_path = os.environ.get("RR_BRIDGE_TRUSTED_PREPARED_PATH")
    trusted_pin = os.environ.get("RR_BRIDGE_TRUSTED_PREPARED_SHA256")
    if bool(trusted_path) != bool(trusted_pin):
        raise ValueError("IncompleteIndependentPreparedBinding")
    path = owned(root, trusted_path) if trusted_path else None
    cached = path is not None
    if cached:
        if sha(path) != trusted_pin:
            raise ValueError("IndependentPreparedArtifactPinMismatch")
        prepared = read(path)
        if prepared["key"] != key:
            raise ValueError("ConflictingPreparedRequest")
        if sha(owned(root, prepared["state_after_path"])) != prepared["state_after_sha256"]:
            raise ValueError("PreparedStatePinMismatch")
    else:
        model, np, torch = load_policy(manifest)
        binding = {"manifest_sha256": sha(manifest_path), "artifact_sha256": manifest["artifact_sha256"]}
        state, rng = restore(read(owned(root, frontier["state_path"])), binding, model.hidden_size, model.operator.state_size)
        if (type(admission["event_mask"]) is not bool or type(admission["dt_micros"]) is not int
                or admission["dt_micros"] < 0
                or admission["time_micros"] != manifest["native_time_origin_micros"] + admission["neural_time_micros"]
                or abs(float(state.time[0]) + admission["dt_micros"] / 1e6 - admission["neural_time_micros"] / 1e6) > 1e-12):
            raise ValueError("HostElapsedTimeBindingMismatch")
        observation = torch.tensor([admission["features_q24"]], dtype=torch.float32) / Q
        started = time.perf_counter_ns()
        with torch.no_grad():
            following, output = model.step(state, observation, admission["dt_micros"] / 1e6, rng,
                                            event_mask=admission["event_mask"], record_spikes=True)
        latency = (time.perf_counter_ns() - started) // 1000
        next_value = snapshot(following, rng, binding)
        next_path = root / "states" / (digest(next_value) + ".json")
        write(next_path, next_value)
        drive = np.rint(output["latent"][0].numpy().astype(np.float64) * Q).astype(np.int64).tolist()
        prepared = {"schema": "rrsnn.v4.prepared-rr-feature.v1", "key": key,
            "execution_id": f"local-{time.time_ns()}-{os.getpid()}",
            "request_digest": request["request_digest"], "request": request["request"],
            "admission_path": str(Path(admission_path).resolve().relative_to(root.resolve())), "admission_sha256": sha(admission_path),
            "previous_frontier_sha256": sha(root / "frontier.json"), "previous_state_sha256": frontier["state_sha256"],
            "state_after_path": str(next_path.relative_to(root)), "state_after_sha256": sha(next_path),
            "drive_q24": drive, "prediction_q24": [0] * 8,
            "latent_float32": output["latent"][0].tolist(), "head_logits_not_routed": output["logits"][0].tolist(),
            "actual_internal_spikes": int(output["actual_counts"].sum()), "spike_times": output["spike_times"],
            "resident_bytes": memory("VmRSS:"), "transient_upper_bound_bytes": memory("VmHWM:"),
            "allocation_measurement_scope": "conservative entire backend process VmHWM; not isolated temporary allocations",
            "latency_micros": latency, "artifact_sha256": manifest["artifact_sha256"]}
        # No directory discovery or unpinned cache adoption. A fresh computation
        # from the trusted prior state may coexist with an unconfirmed orphan.
        path = root / "prepared" / (digest(prepared) + ".json")
        write(path, prepared)
        with (root / "executions.ndjson").open("ab") as stream:
            stream.write(canonical({"key": key, "prepared_sha256": sha(path), "state_after_sha256": sha(next_path),
                                   "actual_internal_spikes": prepared["actual_internal_spikes"]}) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    return {**prepared, "prepared_path": str(path.resolve()), "prepared_sha256": sha(path),
            "backend_executed": not cached, "cached": cached}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["initialize", "prepare", "reference"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--admissions", type=Path)
    parser.add_argument("--seed", type=int, default=441901)
    args = parser.parse_args()
    try:
        if args.mode == "initialize":
            result = initialize(args.root, args.manifest, args.seed)
        elif args.mode == "reference":
            result = reference(args.manifest, args.admissions, args.seed)
        else:
            result = prepare(args.root, args.manifest, args.admission, json.load(sys.stdin))
        print(json.dumps(result, allow_nan=False))
    except Exception as error:
        print(json.dumps({"error": type(error).__name__ + ": " + str(error)}), file=sys.stderr)
        raise SystemExit(2)

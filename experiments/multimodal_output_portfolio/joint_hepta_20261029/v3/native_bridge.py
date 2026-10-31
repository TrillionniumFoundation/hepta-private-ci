"""Export actual JointGenerator weights to a standalone Rust content backend.

Python handles export, process orchestration and independent comparison only.
Every encoder, content transition, policy, decoder, prefix commit and restore
in the native session executes in Rust. This Linux research profile uses FP64
and a separately named sampler; it does not claim Torch RNG bit equivalence.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import resource
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time


NATIVE_SOURCE = Path(__file__).with_name("native_generation")
MAGIC = b"HEPTAPK3"
MAX_PACKET = 64 * 1024 * 1024
MODALITIES = ("image", "audio", "video", "text")


def pack(metadata, tensors):
    """Canonical little-endian bounded tensor packet with a SHA-256 trailer."""
    import numpy as np
    out = bytearray(MAGIC)
    def u32(value):
        out.extend(struct.pack("<I", value))
    def string(value):
        value = value.encode("utf8")
        if len(value) > 8192:
            raise ValueError("Metadata string bound")
        u32(len(value)); out.extend(value)
    u32(len(metadata))
    for key in sorted(metadata):
        string(key); string(str(metadata[key]))
    u32(len(tensors))
    for key in sorted(tensors):
        array = np.asarray(tensors[key], dtype="<f8")
        if array.ndim > 8 or array.size > 4_000_000 or not np.isfinite(array).all():
            raise ValueError("Invalid tensor domain")
        string(key); u32(array.ndim)
        for dimension in array.shape:
            u32(dimension)
        u32(array.size); out.extend(array.tobytes(order="C"))
    if len(out) > MAX_PACKET:
        raise ValueError("Packet byte bound")
    out.extend(hashlib.sha256(out).hexdigest().encode("ascii"))
    return bytes(out)


def unpack(data):
    import numpy as np
    if len(data) < 76 or len(data) > MAX_PACKET + 64:
        raise ValueError("Packet byte bound")
    body, checksum = data[:-64], data[-64:]
    if body[:8] != MAGIC or hashlib.sha256(body).hexdigest().encode() != checksum:
        raise ValueError("Packet identity mismatch")
    offset = 8
    def take(size):
        nonlocal offset
        if size < 0 or offset + size > len(body):
            raise ValueError("Truncated packet")
        value = body[offset:offset + size]; offset += size
        return value
    def u32(maximum):
        value = struct.unpack("<I", take(4))[0]
        if value > maximum:
            raise ValueError("Packet count bound")
        return value
    def string():
        return take(u32(8192)).decode("utf8")
    metadata, tensors = {}, {}
    for _ in range(u32(256)):
        key, value = string(), string()
        if key in metadata:
            raise ValueError("Duplicate metadata")
        metadata[key] = value
    for _ in range(u32(512)):
        key = string(); shape = tuple(u32(4_000_000) for _ in range(u32(8)))
        size = u32(4_000_000)
        if size != int(np.prod(shape, dtype=np.int64)) or key in tensors:
            raise ValueError("Tensor shape or identity")
        array = np.frombuffer(take(size * 8), dtype="<f8").copy().reshape(shape)
        if not np.isfinite(array).all():
            raise ValueError("Nonfinite tensor")
        tensors[key] = array
    if offset != len(body):
        raise ValueError("Trailing packet data")
    return metadata, tensors


def build_native(output, *, rustc=None):
    """Compile only these stdlib sources, without Cargo/network/dependency builds."""
    compiler = rustc or shutil.which("rustc")
    if compiler is None:
        raise RuntimeError("Supply a verified local rustc path")
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    version = subprocess.run([str(compiler), "--version"], capture_output=True, text=True, check=True).stdout.strip()
    command = [str(compiler), "--edition=2024", "-O", "-C", "target-cpu=generic",
               str(NATIVE_SOURCE / "main.rs"), "-o", str(output)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    receipt = {"schema": "hepta.native-content-build.v3", "compiler": version,
               "command": command, "platform": "linux-stdlib-plus-system-libm",
               "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(NATIVE_SOURCE.glob("*.rs"))},
               "binary_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    output.with_suffix(output.suffix + ".build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return output, receipt


def export_model(model, public, directory, *, allow_initial_stop=True,
                 suppress_redundant_verify=None):
    """Export one single-context public input and exact selected weight values."""
    import torch
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    expected = {"image", "image_mask", "audio", "audio_mask", "video", "video_mask", "tokens"}
    if set(public) != expected or any(value.shape[0] != 1 for value in public.values()):
        raise ValueError("Native public schema is one complete context")
    state = model.state_dict()
    if suppress_redundant_verify is None:
        suppress_redundant_verify = model.config.get("verify_mode") == "deduplicate"
    if any(value.dtype not in (torch.float32, torch.float64) for value in state.values()):
        raise ValueError("Unsupported model precision")
    metadata = {"kind": "joint-generator-weights-v3", "width": str(model.config["width"]),
                "depth": str(model.config["depth"]), "mode": model.config["mode"],
                "boundary": model.config["boundary"], "numeric_profile": "fp64-linux-libm-v1",
                "source_dtypes": ",".join(sorted({str(v.dtype) for v in state.values()})),
                "allow_initial_stop": str(allow_initial_stop).lower(),
                "suppress_redundant_verify": str(suppress_redundant_verify).lower()}
    weights = pack(metadata, {name: value.detach().cpu().double().numpy() for name, value in state.items()})
    inputs = pack({"kind": "joint-generator-public-v3"},
                  {name: value.detach().cpu().double().numpy() for name, value in public.items()})
    wp, ip = directory / "weights.hps", directory / "public.hps"
    wp.write_bytes(weights); ip.write_bytes(inputs)
    manifest = {"schema": "hepta.native-content-export.v3", "model_config": model.config,
                "weights_sha256": hashlib.sha256(weights).hexdigest(),
                "public_sha256": hashlib.sha256(inputs).hexdigest(),
                "parameters": sum(p.numel() for p in model.parameters()),
                "tensor_count": len(state), "weights_bytes": len(weights),
                "native_math": metadata["numeric_profile"], "original_model_mutated": False}
    (directory / "EXPORT.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return wp, ip, manifest


@dataclass
class NativeSession:
    binary: Path
    weights: Path
    public: Path
    directory: Path
    head: str = ""
    calls: list = field(default_factory=list)

    def command(self, name, *args, check=True):
        started = time.perf_counter()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = subprocess.run([str(self.binary), name, str(self.weights), str(self.public),
                                 str(self.directory), *map(str, args)], capture_output=True, text=True)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.calls.append({"operation": name, "returncode": result.returncode,
                           "wall_seconds": time.perf_counter() - started,
                           "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                           "scope": "whole_native_process_including_weight_read_and_full_journal_replay"})
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip())
        if not check:
            return result
        value = json.loads(result.stdout)
        if "head" in value:
            self.head = value["head"]
        return value

    def create(self, *, seed=17, sampler="mean"):
        return self.command("init", seed, sampler)

    def refresh(self, *, expected_head=None):
        return self.command("status", *([expected_head] if expected_head is not None else []))

    def step(self, action):
        return self.command("step", self.head, action)

    def auto(self, remaining=1.0):
        return self.command("auto", self.head, remaining)

    def commit(self, modality, count, *, fault=""):
        arguments = [self.head, modality, count]
        if fault:
            arguments.append(fault)
        return self.command("commit", *arguments, check=not bool(fault))

    def inspect(self, remaining=1.0):
        with tempfile.TemporaryDirectory(prefix="hepta-native-inspect-") as temp:
            target = Path(temp) / "state.hps"
            self.command("inspect", target, remaining)
            return unpack(target.read_bytes())

    def export(self, output, *, audio_rate=2048, frame_ms=120):
        return self.command("export", output, audio_rate, frame_ms)


def reference_tensors(model, state, remaining, *, allow_initial_stop, verified,
                      suppress_redundant_verify):
    import torch
    tensors = {name: getattr(state, name).detach().cpu().double().numpy().reshape(-1)
               for name in ("context", "shared", "slots", "feedback")}
    for layer, values in enumerate(state.core):
        for name, value in values.items():
            tensors[f"core.{layer}.{name}"] = value.detach().cpu().double().numpy().reshape(-1)
    for name, value in model.outputs(state).items():
        if name == "text":
            value = torch.cat(value, -1)
        tensors[f"output.{name}"] = value.detach().cpu().double().numpy().reshape(-1)
    features = model.features(state, remaining)
    logits = model.actor(features)
    tensors["actor.logits"] = logits.detach().cpu().double().numpy().reshape(-1)
    masked = logits.clone()
    if state.steps == 0 and not allow_initial_stop:
        masked[:, -1] = -torch.inf
    if suppress_redundant_verify and verified:
        masked[:, 5] = -torch.inf
    if state.steps >= 6 or state.stopped:
        masked[:, :-1] = -torch.inf
    tensors["policy.probabilities"] = masked.softmax(-1).detach().cpu().double().numpy().reshape(-1)
    for name in ("critic", "delivery_critic"):
        tensors[name] = getattr(model, name)(features).detach().cpu().double().numpy().reshape(-1)
    return tensors


def differential(model, public, directory, binary, *, actions=("shared", "image", "verify", "audio", "video", "text", "stop"),
                 allow_initial_stop=True, suppress_redundant_verify=None):
    """Compare every content state/head against independent original Torch code."""
    import numpy as np
    import torch
    root = Path(directory); root.mkdir(parents=True, exist_ok=False)
    if suppress_redundant_verify is None:
        suppress_redundant_verify = model.config.get("verify_mode") == "deduplicate"
    wp, ip, manifest = export_model(model, public, root / "export",
                                   allow_initial_stop=allow_initial_stop,
                                   suppress_redundant_verify=suppress_redundant_verify)
    native = NativeSession(Path(binary), wp, ip, root / "session"); native.create()
    double = deepcopy(model).cpu().double().eval()
    fp32 = deepcopy(model).cpu().float().eval()
    public64 = {k: v.detach().cpu().to(torch.int64 if k == "tokens" else torch.float64) for k, v in public.items()}
    public32 = {k: v.detach().cpu().to(torch.int64 if k == "tokens" else torch.float32) for k, v in public.items()}
    s64, s32 = double.encode(public64), fp32.encode(public32)
    records, verified = [], False
    content_revision, verified_revision = 0, -1
    with torch.no_grad():
        for index, action in enumerate((None, *actions)):
            if action is not None:
                native.step(action); s64, _ = double.advance(s64, action, public64); s32, _ = fp32.advance(s32, action, public32)
                if action == "verify":
                    verified = True
                    verified_revision = content_revision
                elif action != "stop":
                    verified = False
                    content_revision += 1
            # Every inspect runs in a new OS process and reconstructs the chain.
            metadata, actual = native.inspect(1.0)
            expected_metadata = {"steps": str(s64.steps), "stopped": str(s64.stopped).lower(),
                                 "verified": str(verified).lower(), "content_revision": str(content_revision),
                                 "verified_revision": str(verified_revision)}
            if any(metadata.get(k) != v for k, v in expected_metadata.items()):
                raise RuntimeError("Native discrete generation state differs from the reference history")
            if hasattr(s64, "content_revision") and (s64.content_revision != content_revision or
                                                     s64.verified_revision != verified_revision):
                raise RuntimeError("Original Torch revision semantics differ from native history")
            options = dict(allow_initial_stop=allow_initial_stop, verified=verified,
                           suppress_redundant_verify=suppress_redundant_verify)
            expected64 = reference_tensors(double, s64, 1.0, **options)
            expected32 = reference_tensors(fp32, s32, 1.0, **options)
            error64 = {k: float(np.max(np.abs(actual[k] - v))) for k, v in expected64.items()}
            error32 = {k: float(np.max(np.abs(actual[k] - v))) for k, v in expected32.items()}
            records.append({"index": index, "action": action, "head": native.head,
                            "discrete_state_matches": True,
                            "max_absolute_fp64": max(error64.values()), "max_absolute_fp32": max(error32.values()),
                            "fp64_errors_by_tensor": error64, "fp32_errors_by_tensor": error32})
    result = {"schema": "hepta.native-content-differential.v3", "export": manifest,
              "native_binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
              "steps": records, "maximum_fp64_absolute": max(r["max_absolute_fp64"] for r in records),
              "maximum_fp32_absolute": max(r["max_absolute_fp32"] for r in records),
              "tested_selected_weights": True, "native_executes_content": True,
              "tolerance_fp64": 1e-9, "tolerance_fp32": 5e-5,
              "independent_process_replay": True, "open_domain_quality_claim": False}
    result["passed"] = result["maximum_fp64_absolute"] < 1e-9 and result["maximum_fp32_absolute"] < 5e-5
    (root / "DIFFERENTIAL.json").write_text(json.dumps(result, indent=2) + "\n")
    return result

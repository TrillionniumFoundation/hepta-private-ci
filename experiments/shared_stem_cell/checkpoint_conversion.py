"""Explicit, resource-limited weights-only conversion; never a model-load fallback.

The disposable subprocess is NOT a hostile-code security sandbox. Only an
explicitly accepted, SHA-bound source may be converted. No unrestricted pickle,
custom globals, remote code, model instantiation, serving or promotion occurs.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

MAX_BYTES = 2 * 1024**3
MAX_TENSORS = 10000


def digest_file(path: Path, maximum=MAX_BYTES):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("linked conversion input/output")
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("missing/oversized conversion input/output")
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            total += len(block)
            if total > maximum:
                raise ValueError("conversion file grew beyond limit")
            h.update(block)
    return h.hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def write(path, value):
    with path.open("xb") as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def tensor_record(value):
    import torch
    flat = value.detach().cpu().contiguous().reshape(-1).view(torch.uint8)
    shape = list(value.shape)
    dtype = str(value.dtype)
    return {"shape": shape, "dtype": dtype, "bytes": value.numel() * value.element_size(),
            "sha256": hashlib.sha256(json_bytes([dtype, shape]) + flat.numpy().tobytes()).hexdigest()}


def _worker(source: Path, expected: str, output: Path):
    import resource
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    # Runtime floor is pinned, not an assertion that every later build is secure.
    version = tuple(int(v) for v in torch.__version__.split("+")[0].split(".")[:2])
    if version < (2, 10):
        raise ValueError("conversion requires reviewed Torch >=2.10")
    torch.set_num_threads(1)
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    if digest_file(source) != expected:
        raise ValueError("conversion source digest drift")
    # No add_safe_globals, no weights_only=False, no dynamic class repair.
    state = torch.load(source, map_location="cpu", weights_only=True)
    if type(state) not in (dict, OrderedDict) or not 1 <= len(state) <= MAX_TENSORS:
        raise ValueError("plain bounded state_dict required")
    allowed = {torch.float16, torch.float32, torch.float64, torch.bfloat16,
               torch.int64, torch.int32, torch.int16, torch.int8, torch.uint8, torch.bool}
    tensors, inventory, total = {}, {}, 0
    for key, value in state.items():
        if not isinstance(key, str) or not 1 <= len(key.encode()) <= 512:
            raise ValueError("invalid tensor key")
        if (type(value) is not torch.Tensor or value.layout != torch.strided
                or value.dtype not in allowed or value.ndim > 8 or value.numel() == 0):
            raise ValueError("plain nonempty dense tensor required")
        total += value.numel() * value.element_size()
        if total > MAX_BYTES or not bool(torch.isfinite(value).all()):
            raise ValueError("tensor budget/nonfinite value")
        # Keep every key, including tied keys; no unknown parameters discarded.
        tensors[key] = value.detach().contiguous().clone()
        inventory[key] = tensor_record(tensors[key])
    target = output / "model.safetensors"
    if target.exists():
        raise ValueError("conversion target already exists")
    save_file(tensors, str(target), metadata={"format": "pt"})
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    with safe_open(str(target), framework="pt", device="cpu") as saved:
        if set(saved.keys()) != set(tensors):
            raise ValueError("converted key set drift")
        for key, value in tensors.items():
            if not torch.equal(saved.get_tensor(key), value):
                raise ValueError("converted tensor values drift")
    if digest_file(source) != expected:
        raise ValueError("source changed during conversion")
    write(output / "conversion.json", {
        "schema": "hepta.weights-only-conversion.v1", "source_sha256": expected,
        "converted_sha256": digest_file(target), "torch_version": torch.__version__,
        "converter_sha256": digest_file(Path(__file__)), "tensor_count": len(tensors),
        "tensor_bytes": total, "tensors": inventory, "weights_only": True,
        "custom_globals_added": False, "hostile_code_sandbox": False,
        "independent_attestation": False, "production_accepted": False})


def convert(source: Path, expected: str, output: Path, *, accepted=False):
    """Create a separate artifact; ordinary inference continues to require safetensors."""
    if accepted is not True:
        raise ValueError("explicit weights-only conversion acceptance required")
    if (not isinstance(expected, str) or len(expected) != 64
            or any(c not in "0123456789abcdef" for c in expected)):
        raise ValueError("immutable source SHA256 required")
    source, output = source.absolute(), output.absolute()
    if digest_file(source) != expected:
        raise ValueError("conversion source digest mismatch")
    if output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("linked conversion destination")
    output.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PYTHON", "TORCH_FORCE", "HF_", "HUGGING"))}
    env.update(TORCH_FORCE_WEIGHTS_ONLY_LOAD="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1", HF_HUB_OFFLINE="1")
    try:
        with (output / "worker.log").open("xb") as log:
            result = subprocess.run([sys.executable, "-I", str(Path(__file__).absolute()),
                "--worker", "--source", str(source), "--sha256", expected,
                "--output", str(output)], env=env, cwd=output,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                timeout=180, check=False)
        if result.returncode != 0:
            raise ValueError(f"weights-only worker failed ({result.returncode}); inspect worker.log")
        report = json.loads((output / "conversion.json").read_bytes())
        if (report["source_sha256"] != expected
                or report["converter_sha256"] != digest_file(Path(__file__))
                or report["converted_sha256"] != digest_file(output / "model.safetensors")
                or digest_file(source) != expected):
            raise ValueError("conversion receipt/source drift")
        return report
    except Exception as error:
        write(output / "failure.json", {"error": type(error).__name__, "message": str(error),
                                        "production_accepted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-weights-only-conversion", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        _worker(args.source, args.sha256, args.output)
    else:
        convert(args.source, args.sha256, args.output,
                accepted=args.allow_weights_only_conversion)

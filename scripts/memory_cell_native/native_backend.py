"""Pinned CPU backend metadata; inspection does not load or run model weights."""

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import sys

SYSTEM = (
    "Answer using stored memory in the specified scope. Return only the value. "
    "If unknown, say 'unknown'. Do not cite sources."
)
ENCODER = b"hepta.memory-cell.query-utf8-q16-padded512.v1"
HEAD = b"hepta.memory-cell.hidden-tanh-and-next-token-top-probabilities.v1"
QUANTIZATION = b"hepta.memory-cell.cpu-float32-unquantized.v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_set(root, paths):
    rows = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular pinned source/model file required")
        rows[str(path.relative_to(root))] = {
            "sha256": file_sha(path),
            "bytes": path.stat().st_size,
        }
    return rows


def inspect(repo, model, checkpoint):
    repo, model, checkpoint = map(
        lambda p: Path(p).resolve(strict=True), (repo, model, checkpoint)
    )
    sources = []
    for name in ("memory_cell", "memory_cell_native"):
        sources.extend((repo / "scripts" / name).glob("*.py"))
    sources.append(repo / "scripts/memory_cell_network/model_child.py")
    code = file_set(repo, sources)
    versions = {
        name: importlib.metadata.version(name)
        for name in (
            "torch",
            "transformers",
            "peft",
            "tokenizers",
            "safetensors",
            "numpy",
        )
    }
    runtime = {
        "python": platform.python_version(),
        "executable_sha256": file_sha(Path(sys.executable).resolve()),
        "versions": versions,
        "sources": code,
    }
    inventory = file_set(
        model,
        (
            p
            for p in model.rglob("*")
            if p.is_file() and ".cache" not in p.relative_to(model).parts
        ),
    )
    tokenizer = {
        k: v
        for k, v in inventory.items()
        if "token" in k or k in ("vocab.json", "merges.txt")
    }
    manifest_bytes = (checkpoint / "lineage.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest["base_identity"] != sha(canonical(inventory)):
        raise ValueError("retained checkpoint base differs from actual model files")
    adapter = file_sha(checkpoint / "adapter_model.safetensors")
    if adapter != manifest["adapter_sha256"]:
        raise ValueError("adapter bytes changed")
    pins = {
        "manifest_sha256": sha(manifest_bytes),
        "base_identity": manifest["base_identity"],
        "adapter_sha256": adapter,
        "weights_digest": sha((manifest["base_identity"] + adapter).encode()),
        "tokenizer_digest": sha(canonical(tokenizer)),
        "preprocessor_digest": sha(SYSTEM.encode()),
        "quantization_digest": sha(QUANTIZATION),
        "runtime_digest": sha(canonical(runtime)),
        "device_digest": sha(
            canonical(
                {
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "processor": platform.processor(),
                    "backend": "cpu",
                    "threads": 2,
                }
            )
        ),
        "worker_sha256": file_sha(repo / "scripts/memory_cell_native/native_worker.py"),
        "launcher_sha256": file_sha(
            repo / "scripts/memory_cell_network/model_child.py"
        ),
    }
    return pins, {"runtime": runtime, "model": inventory, "lineage": manifest}


def prompt(scope, question):
    return f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\nScope: {scope}\n{question}<|im_end|>\n<|im_start|>assistant\n"


def features(question):
    raw = question.encode()
    if not 1 <= len(raw) <= 512:
        raise ValueError("bounded query UTF-8 required")
    return [v << 16 for v in raw] + [0] * (512 - len(raw))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--checkpoint", required=True)
    args = parser.parse_args()
    pins, evidence = inspect(args.repo, args.model, args.checkpoint)
    print(json.dumps({"pins": pins, "inspection": evidence}, sort_keys=True))

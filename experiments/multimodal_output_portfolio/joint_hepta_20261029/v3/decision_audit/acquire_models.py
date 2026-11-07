"""Acquire immutable public model revisions without duplicating a Hub cache."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import time
import urllib.request
import uuid


MODELS = {
    "vlm": ("HuggingFaceTB/SmolVLM2-256M-Video-Instruct", "067788b187b95ebe7b2e040b3e4299e342e5b8fd", {
        "model.safetensors": (1025998224, "dcc8f4c00d30d70bb3028a1bfc373e1b1972e25919f8788183cae4ae72431ce2")}),
    "sd": ("segmind/tiny-sd", "cad0bd7495fa6c4bcca01b19a723dc91627fe84f", {
        "text_encoder/pytorch_model.bin": (246187869, "f99d8915149c782551f7d14aae5ca0b6e76a6e94d30e5dc86a349b228fbf92ad"),
        "unet/diffusion_pytorch_model.bin": (646923637, "c9b63e57cb1479c946c73bf5484bc1a823dbe565158ea0ee40015a18844d9f29"),
        "vae/diffusion_pytorch_model.bin": (167407857, "279228e5296858f5d330db506ff6a51fdcad0d69f87634b5e9133406110af9bf")}),
}
INPUT_REVISION = "4be1ef917419575e5f13bc54939a3f57aa22deff"


def digest_file(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def resource_snapshot(path):
    result = {"filesystem_free_bytes": shutil.disk_usage(path).free}
    cgroup = Path("/sys/fs/cgroup")
    if (cgroup / "memory.max").exists():
        maximum = (cgroup / "memory.max").read_text().strip()
        if maximum.isdigit():
            stats = dict(line.split() for line in (cgroup / "memory.stat").read_text().splitlines())
            current = int((cgroup / "memory.current").read_text())
            reclaimable = max(0, int(stats["file"]) - int(stats["shmem"])) + int(stats.get("slab_reclaimable", 0))
            result.update(cgroup_limit_bytes=int(maximum), cgroup_current_bytes=current,
                          reclaimable_estimate_bytes=reclaimable,
                          headroom_estimate_bytes=max(0, int(maximum) - current + reclaimable))
    return result


def _json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _append_attempt(root, value, event):
    with (root / "ACQUISITION_ATTEMPTS.jsonl").open("a") as stream:
        stream.write(json.dumps({**value, "event": event}, sort_keys=True) + "\n")


def download(url, target, size=None, expected_sha256=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("Refusing a symlink download target")
    if target.exists() and expected_sha256 and digest_file(target) == expected_sha256:
        return {"path": target.name, "size": target.stat().st_size, "sha256": expected_sha256, "source": url}
    partial = target.with_name(target.name + ".part")
    sha, count = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=90) as response, partial.open("wb") as output:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            output.write(block); sha.update(block); count += len(block)
            if size is not None and count > size:
                raise ValueError("Downloaded object exceeds its pinned size")
    actual = sha.hexdigest()
    if size is not None and count != size or expected_sha256 and actual != expected_sha256:
        raise ValueError(f"Pinned object verification failed: bytes={count}, sha256={actual}")
    partial.replace(target)
    return {"path": target.name, "size": count, "sha256": actual, "source": url}


def acquire(root, *, preflight_only=False):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    progress = {"schema": "hepta.dual-model-acquisition.v1", "started_unix": started,
                "preflight": resource_snapshot(root), "models": {}, "complete": False,
                "preflight_only": preflight_only, "attempt_id": uuid.uuid4().hex,
                "status": "started"}
    _append_attempt(root, progress, "started")
    try:
        # Existing files have not been hashed yet: reserve full replacements.
        pending = sum(size for _, _, weights in MODELS.values() for size, _ in weights.values()) + 16 * 1024**2
        progress["pending_download_bytes"] = pending
        if progress["preflight"]["filesystem_free_bytes"] < pending + 64 * 1024**2:
            raise RuntimeError("Insufficient space for pinned model bytes")
        if str(root.resolve()).startswith("/dev/shm/") and progress["preflight"].get("headroom_estimate_bytes", pending) < pending + 512 * 1024**2:
            raise RuntimeError("Insufficient cgroup headroom for tmpfs models and acquisition reserve")
        if preflight_only:
            progress["download_admission"] = "passed_at_snapshot_only"
            progress["status"] = "preflight_snapshot_passed"
            return progress
        for key, (model, revision, weights) in MODELS.items():
            metadata = _json(f"https://huggingface.co/api/models/{model}/revision/{revision}?blobs=true")
            if metadata["sha"] != revision:
                raise ValueError("Model revision changed")
            manifest = {"model": model, "revision": revision, "files": [], "complete": False}
            for item in metadata["siblings"]:
                name = item["rfilename"]; parts = PurePosixPath(name)
                if parts.is_absolute() or ".." in parts.parts:
                    raise ValueError("Unsafe repository path")
                if name not in weights and (name.startswith("onnx/") or not (name.endswith((".json", ".txt")) or name == "README.md")):
                    continue
                size, expected = weights.get(name, (item.get("size"), None))
                if name in weights and (item.get("lfs", {}).get("sha256") != expected or item.get("size") != size):
                    raise ValueError("Model LFS identity differs from reviewed pin")
                record = download(f"https://huggingface.co/{model}/resolve/{revision}/{name}", root / key / name, size, expected)
                record["path"] = name; manifest["files"].append(record)
                _write(root / key / "MANIFEST.json", manifest)
                print(json.dumps({"downloaded": key + "/" + name, "bytes": record["size"]}), flush=True)
            if not set(weights).issubset({r["path"] for r in manifest["files"]}):
                raise ValueError("Required pinned weights absent")
            manifest["complete"] = True; _write(root / key / "MANIFEST.json", manifest)
            progress["models"][key] = {"manifest_sha256": digest_file(root / key / "MANIFEST.json")}
        dataset = "huggingface/documentation-images"
        metadata = _json(f"https://huggingface.co/api/datasets/{dataset}/revision/{INPUT_REVISION}")
        if metadata["sha"] != INPUT_REVISION or not any(x["rfilename"] == "bee.jpg" for x in metadata["siblings"]):
            raise ValueError("Pinned public input absent")
        record = download(f"https://huggingface.co/datasets/{dataset}/resolve/{INPUT_REVISION}/bee.jpg", root / "task" / "input.jpg")
        _write(root / "task" / "INPUT_MANIFEST.json", {"dataset": dataset, "revision": INPUT_REVISION, **record})
        progress["complete"] = True
        progress["status"] = "completed"
    except BaseException as error:
        progress["status"] = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
        progress["error"] = {"type": type(error).__name__, "message": str(error).split("https://")[0]}
        raise
    finally:
        progress["elapsed_seconds"] = time.time() - started
        progress["final_resources"] = resource_snapshot(root)
        _append_attempt(root, progress, "finished")
        _write(root / "ACQUISITION.json", progress)
    return progress


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--root", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(acquire(args.root, preflight_only=args.preflight_only)), flush=True)

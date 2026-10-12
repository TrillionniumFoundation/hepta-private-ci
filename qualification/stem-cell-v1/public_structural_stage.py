"""Explicit public-input provisioner for an isolated research host.

Only this staging command has network access. The existing inference loader
stays offline/safetensors-only; no fallback, conversion, signer or deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen

from development_study_data import write_once
from public_structural_data import DATA_BYTES, DATA_GIT_BLOB, DATA_REVISION, prepare_dataset

MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
WEIGHTS_SHA256 = "3c9f31665447c8911517620762200d2245a2518d6e7208acc78cd9db317e21ad"
MODEL_FILES = ("config.json", "model.safetensors", "special_tokens_map.json",
               "tokenizer.json", "tokenizer_config.json", "vocab.txt")
MAX_FILE_BYTES = 160_000_000


def download_checked(url, destination, expected_size, algorithm, expected_hash):
    """Create once and stream within an exact bound. Partial failures stay visible."""
    if (type(expected_size) is not int or not 1 <= expected_size <= MAX_FILE_BYTES
            or algorithm not in {"sha1", "sha256"} or type(expected_hash) is not str
            or len(expected_hash) != (40 if algorithm == "sha1" else 64)
            or any(c not in "0123456789abcdef" for c in expected_hash)):
        raise ValueError("invalid publisher file pin")
    target = Path(destination)
    h = hashlib.new(algorithm)
    sha256 = hashlib.sha256()
    if algorithm == "sha1":
        h.update(f"blob {expected_size}\0".encode())
    size = 0
    # URLs are constructed ONLY from the fixed publishers/revisions in stage().
    with target.open("xb") as writer, urlopen(url, timeout=60) as reader:
        if reader.status != 200:
            raise ValueError("publisher did not return a complete file")
        while chunk := reader.read(min(1_048_576, expected_size - size + 1)):
            size += len(chunk)
            if size > expected_size:
                raise ValueError("download exceeds pinned byte count")
            writer.write(chunk)
            h.update(chunk)
            sha256.update(chunk)
    if size != expected_size or h.hexdigest() != expected_hash:
        raise ValueError("download differs from pinned publisher bytes")
    return {"bytes": size, "sha256": sha256.hexdigest(),
            "publisher_algorithm": algorithm, "publisher_digest": expected_hash}


def model_pins(info):
    """Validate pinned HF metadata, not a moving main branch or arbitrary code."""
    if info.sha != REVISION:
        raise ValueError("model revision drift")
    inventory = {item.rfilename: item for item in info.siblings}
    if len(inventory) != len(info.siblings) or not set(MODEL_FILES) <= set(inventory):
        raise ValueError("incomplete or duplicate model inventory")
    pins = {}
    for name in MODEL_FILES:
        item = inventory[name]
        if type(item.size) is not int or not 0 < item.size <= MAX_FILE_BYTES:
            raise ValueError("invalid model file size")
        lfs = item.lfs
        if lfs is None:
            algorithm, expected = "sha1", item.blob_id
        else:
            algorithm = "sha256"
            expected = lfs.sha256 if hasattr(lfs, "sha256") else lfs["sha256"]
        if name == "model.safetensors" and (algorithm != "sha256" or expected != WEIGHTS_SHA256):
            raise ValueError("fixed safetensors weight identity changed")
        pins[name] = (item.size, algorithm, expected)
    if sum(p[0] for p in pins.values()) > 256_000_000:
        raise ValueError("model snapshot exceeds staging budget")
    return pins


def stage(output):
    output = Path(output)
    source_root = Path(__file__).resolve().parents[2]
    if output.resolve().is_relative_to(source_root):
        raise ValueError("public inputs must be staged outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    write_once(output / "PLAN.json", {"model": MODEL, "revision": REVISION,
        "weights_sha256": WEIGHTS_SHA256, "data_revision": DATA_REVISION,
        "data_git_blob": DATA_GIT_BLOB, "time_basis": "publisher_partition",
        "production_authorized": False})
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(MODEL, revision=REVISION, files_metadata=True, token=False)
        pins = model_pins(info)
        write_once(output / "publisher-model-pins.json", pins)
        snapshot = output / "model"
        snapshot.mkdir()
        observed = {}
        for name, (size, algorithm, expected) in pins.items():
            url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}"
            observed[name] = download_checked(url, snapshot / name, size, algorithm, expected)
        config = json.loads((snapshot / "config.json").read_text())
        tokenizer = json.loads((snapshot / "tokenizer_config.json").read_text())
        if (config.get("model_type") != "bert" or config.get("hidden_size") != 384
                or config.get("max_position_embeddings") != 512
                or "auto_map" in config or "auto_map" in tokenizer):
            raise ValueError("unexpected native BGE model/tokenizer architecture")
        root = f"https://raw.githubusercontent.com/clinc/oos-eval/{DATA_REVISION}"
        download_checked(f"{root}/data/data_full.json", output / "publisher.json",
                         DATA_BYTES, "sha1", DATA_GIT_BLOB)
        download_checked(f"{root}/LICENSE", output / "CLINC_LICENSE.txt", 19467,
                         "sha1", "1a16e05564d2aaa880bbe9e506a0a0226d8742cc")
        dataset_sha, config_sha = prepare_dataset(output / "publisher.json", output)
        from model_runner import snapshot_digest
        result = {"schema": "hepta.stem.public-stage.v1", "model": MODEL, "revision": REVISION,
            "snapshot_sha256": snapshot_digest(snapshot), "model_files": observed,
            "model_license": "MIT", "dataset_sha256": dataset_sha, "config_sha256": config_sha,
            "cpu_ns": time.process_time_ns() - start_cpu, "wall_ns": time.perf_counter_ns() - start_wall,
            "genuine_future_windows": False, "production_authorized": False}
        write_once(output / "stage.json", result)
        return result
    except Exception as error:
        write_once(output / "FAILED.json", {"error_type": type(error).__name__, "message": str(error),
            "cpu_ns": time.process_time_ns() - start_cpu, "wall_ns": time.perf_counter_ns() - start_wall,
            "production_authorized": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage(args.output)

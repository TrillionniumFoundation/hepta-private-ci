#!/usr/bin/env python3
"""Bounded local Jina v5 snapshot byte census; shadow-only evidence, no authority.

Attests actual local model/tokenizer/adapter/code files against a separately
approved manifest digest. Does NOT authenticate the issuer of that digest,
prove the model used every file, or replace signed artifact CAS/load receipts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import time

from jina_v5 import MODELS, TASKS, sha256_record

MAX_FILES = 2048
MAX_TOTAL_BYTES = 16 * (1024 ** 3)
MAX_FILE_BYTES = 8 * (1024 ** 3)
READ_CHUNK = 4 * 1024 * 1024


def _sha(value, length):
    return (type(value) is str and len(value) == length
            and all(char in "0123456789abcdef" for char in value)
            and value != "0" * length)


def _dir(path, label):
    if not isinstance(path, (str, os.PathLike)):
        raise ValueError(label + " must be a local filesystem path")
    raw = Path(path).absolute()
    if raw.is_symlink():
        raise ValueError(label + " cannot be a directory symlink")
    result = raw.resolve(strict=True)
    if not result.is_dir():
        raise ValueError(label + " must be a regular directory")
    return result


def _hash_regular_file(path, expected_root):
    real = path.resolve(strict=True)
    if not real.is_relative_to(expected_root):
        raise ValueError("snapshot file escapes approved model cache root")
    if path.is_symlink() and not real.is_relative_to(expected_root / "blobs"):
        raise ValueError("model snapshot file symlink must reference this HF cache's blobs")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(real, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("snapshot member is not a regular file")
        if not 0 < before.st_size <= MAX_FILE_BYTES:
            raise ValueError("snapshot file size outside model artifact bound")
        h = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            prefix = stream.read(min(256, before.st_size))
            if path.name.endswith(".safetensors") and (
                prefix.startswith(b"version https://git-lfs.github.com/spec/")
                or prefix.startswith(b"version https://git-lfs")
            ):
                raise ValueError("snapshot holds a Git LFS pointer, not loaded model weights")
            h.update(prefix)
            for chunk in iter(lambda: stream.read(READ_CHUNK), b""):
                h.update(chunk)
            if stream.tell() != before.st_size:
                raise ValueError("snapshot size changed during hashing")
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("snapshot file modified during attestation")
        return before.st_size, h.hexdigest()
    finally:
        os.close(fd)


def attest_snapshot(model_id, revision, task, *, store_root, snapshot_dir,
                    expected_digest=None):
    """Hash *all* snapshot files, including task adapter and custom model code.

    The approved store root is exactly HF's models--OWNER--REPO cache root.
    Local snapshot files may symlink to that root's blobs; they may not escape
    it. Files are streamed and bounded, never copied to the output manifest.
    """
    if model_id not in MODELS or task not in TASKS or not _sha(revision, 40):
        raise ValueError("registered model/task and exact 40-hex revision required")
    spec = MODELS[model_id]
    expected_root_name = "models--" + spec.repository.replace("/", "--")
    root = _dir(store_root, "approved model cache root")
    snap = _dir(snapshot_dir, "snapshot")
    if root.name != expected_root_name:
        raise ValueError("approved cache root does not match selected model repository")
    if snap.parent != root / "snapshots" or snap.name != revision:
        raise ValueError("snapshot must be the exact pinned models--repo/snapshots/SHA")
    if expected_digest is not None and not _sha(expected_digest, 64):
        raise ValueError("expected snapshot digest must be a nonzero canonical SHA256")

    started = time.perf_counter_ns()
    records, total = [], 0
    for member in sorted(snap.rglob("*")):
        rel = member.relative_to(snap).as_posix()
        if any(part in (".git", ".cache", "__pycache__") for part in member.relative_to(snap).parts):
            raise ValueError("unreviewed mutable/hidden metadata inside model snapshot")
        if member.is_dir():
            if member.is_symlink():
                raise ValueError("snapshot directory symlinks not allowed")
            continue
        if not member.is_file():
            raise ValueError("nonregular or broken snapshot entry")
        if len(records) >= MAX_FILES:
            raise ValueError("snapshot file count exceeded the frozen envelope")
        size, sha = _hash_regular_file(member, root)
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("snapshot exceeds maximum streamed model artifact bytes")
        records.append({"path": rel, "size_bytes": size, "sha256": sha})
    observed = {record["path"] for record in records}
    required = {
        "config.json", "modules.json", "tokenizer.json", "model.safetensors",
        f"adapters/{task}/adapter_config.json",
        f"adapters/{task}/adapter_model.safetensors",
    }
    missing = sorted(required - observed)
    if missing:
        raise ValueError("incomplete Jina v5 model/tokenizer/task-adapter snapshot: " +
                         ", ".join(missing))
    # Config and custom model/Python code are included in records even when
    # the selected runtime does not execute a particular module.
    evidence = {
        "schema": "hepta.jina-v5-local-artifact-census.v1",
        "repository": spec.repository,
        "model_id": model_id,
        "revision": revision,
        "task_adapter": task,
        "files": records,
        "total_bytes": total,
    }
    observed_digest = sha256_record(evidence)
    if expected_digest is not None and observed_digest != expected_digest:
        raise ValueError("local snapshot differs from independently precommitted file census")
    return {
        "schema": "hepta.jina-v5-snapshot-check.v1",
        "status": ("operator_digest_match_shadow_only"
                   if expected_digest is not None else "observed_unapproved_shadow_only"),
        "model_id": model_id,
        "repository": spec.repository,
        "revision": revision,
        "task_adapter": task,
        "manifest_sha256": observed_digest,
        "matches_precommitted_digest": expected_digest is not None,
        "file_count": len(records),
        "total_bytes": total,
        "files": records,
        "verification_wall_ms": (time.perf_counter_ns() - started) / 1e6,
        "signed_artifact_cas_verified": False,
        "production_load_receipt_verified": False,
        "actual_encoder_forward_verified": False,
        "production_promotion_permitted": False,
    }


def write_census_report(output, report, *, store_root):
    """Create-once research evidence outside the approved cache."""
    out = Path(output).absolute()
    protected = _dir(store_root, "approved model cache root")
    if out.resolve(strict=False).is_relative_to(protected):
        raise ValueError("model evidence output cannot modify the approved cache")
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(out, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", choices=sorted(MODELS), required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--task", choices=TASKS, required=True)
    p.add_argument("--store-root", type=Path, required=True)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--expected-digest", help="approved full 64-hex manifest, not a branch name")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    report = attest_snapshot(
        a.model, a.revision, a.task,
        store_root=a.store_root, snapshot_dir=a.snapshot,
        expected_digest=a.expected_digest,
    )
    write_census_report(a.out, report, store_root=a.store_root)


if __name__ == "__main__":
    main()

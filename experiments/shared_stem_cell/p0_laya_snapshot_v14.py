"""Pinned, research-only Laya 0.3.20 snapshot loader (no unpinned Hub fallback).

The published Laya 0.3.20 ``load`` signature has NO ``revision`` keyword;
Laya's library internally calls snapshot_download at the *default revision*.
Instead download an exact pinned full commit, inspect Hub LFS metadata, verify
all five model inputs, and pass the local snapshot path to ``laya.load``.
The underlying Laya Agent then does its own strict safetensors state load.
Neither content hashing nor GitHub Actions constitute independent signatures.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

MODEL_ID = "convaiinnovations/laya"
REVISION = "c5d78730f3493e4fe16d61507ef4b78eef7318cf"
PATTERNS = ("rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*")
REQUIRED = frozenset({
    "rl_agent_config.json", "model.safetensors", "tokenizer/tokenizer.json",
    "tokenizer/tokenizer_config.json", "encoder/config.json",
})
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024 + 30 * 1024 * 1024


class Invalid(ValueError):
    pass


def _exact_file(path: str) -> bool:
    if type(path) is not str or not 0 < len(path) <= 128:
        return False
    p = PurePosixPath(path)
    return (
            p.parts == tuple(part for part in path.split("/") if part) and
            all(part not in (".", "..") for part in p.parts) and
            (path in ("rl_agent_config.json", "model.safetensors") or
             (len(p.parts) == 2 and p.parts[0] in ("tokenizer", "encoder") and
              not p.parts[1].startswith("."))))


def _sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    length = 0
    with path.open("rb") as file:
        while chunk := file.read(4 * 1024 * 1024):
            length += len(chunk)
            if length > MAX_FILE_BYTES:
                raise Invalid("oversized original Laya source file")
            h.update(chunk)
    if not length:
        raise Invalid("empty original model source file")
    return h.hexdigest(), length


def _metadata_digest(sibling):
    lfs = getattr(sibling, "lfs", None)
    if isinstance(lfs, dict):
        return lfs.get("sha256")
    if lfs is not None:
        return getattr(lfs, "sha256", None)
    return None


def load_pinned_laya(*, model_info=None, download=None, load_agent=None):
    """Return `(native_agent, read_only_receipt)` or fail closed.

    All injected inputs are for isolated tests only. Product callers use the
    pinned API and original Laya 0.3.20 native inference implementation.
    """
    if model_info is None or download is None:
        from huggingface_hub import HfApi, snapshot_download
        model_info = model_info or HfApi().model_info
        download = download or snapshot_download
    if load_agent is None:
        import laya
        load_agent = laya.load
    info = model_info(repo_id=MODEL_ID, revision=REVISION, files_metadata=True)
    if getattr(info, "sha", None) != REVISION:
        raise Invalid("Laya original publisher revision mismatch")
    sibling_list = getattr(info, "siblings", None)
    if type(sibling_list) not in (tuple, list) or not sibling_list:
        raise Invalid("missing immutable Hub Laya file inventory")
    expected = {}
    for sibling in sibling_list:
        name = getattr(sibling, "rfilename", None)
        if not _exact_file(name):
            continue  # unrelated upstream root directories are not loaded
        if name in expected:
            raise Invalid("duplicate native Laya source file inventory")
        expected[name] = sibling
    if not REQUIRED.issubset(expected):
        raise Invalid("original Laya checkpoint or tokenizer/encoder config missing")
    if not _metadata_digest(expected["model.safetensors"]):
        raise Invalid("original Laya checkpoint has no publisher LFS SHA256")
    snapshot = Path(download(repo_id=MODEL_ID, revision=REVISION,
                             allow_patterns=list(PATTERNS)))
    if not snapshot.is_dir():
        raise Invalid("pinned Laya snapshot not materialized")
    checked = {}
    total_bytes = 0
    for name in sorted(expected):
        path = snapshot.joinpath(*PurePosixPath(name).parts)
        if not path.is_file():
            raise Invalid("missing original Laya snapshot material: " + name)
        sha, size = _sha256_file(path)
        reported_size = getattr(expected[name], "size", None)
        if type(reported_size) is int and reported_size > 0 and size != reported_size:
            raise Invalid("original Laya checkpoint publisher size differs: " + name)
        published = _metadata_digest(expected[name])
        if published is not None and (type(published) is not str or
                                      len(published) != 64 or
                                      sha != published.lower()):
            raise Invalid("original Laya source publisher LFS SHA mismatch: " + name)
        total_bytes += size
        if total_bytes > MAX_SOURCE_BYTES:
            raise Invalid("unbounded original Laya checkpoint inventory")
        checked[name] = {"sha256": sha, "size": size,
                         "publisher_lfs_sha256_checked": published is not None}
    # The *only* call to original native Laya. A local path forces it to load
    # precisely the verified files instead of its unpinned Hub default branch.
    agent = load_agent(str(snapshot), device="cpu", fast=False)
    if agent is None or not callable(getattr(agent, "predict", None)):
        raise Invalid("original native Laya agent interface absent")
    return agent, {
        "schema": "hepta.p0.original-laya-pinned-snapshot.v14",
        "model": MODEL_ID, "model_revision": REVISION,
        "expected_source_file_count": len(checked),
        "checked_source_bytes": total_bytes,
        "publisher_lfs_model_digest_checked": True,
        "files": checked,
        "original_native_loader_called_on_local_verified_snapshot": True,
        "publisher_signature_independently_verified": False,
        "held_human_labels_accessed": False,
        "production_promotion_permitted": False,
        "authority": "DENY_ALL",
    }

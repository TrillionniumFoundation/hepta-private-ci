"""Verify consumed model files against a pinned upstream Git/LFS manifest.

This establishes source identity, not safe code, data rights, or model selection.
The metadata must be obtained from the authenticated HTTPS origin by the caller;
a locally authored manifest alone is not an independent trust root.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILES = 1024
MAX_FILE_BYTES = 8 * 1024**3


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def normalized_hub_manifest(info: Any) -> dict[str, Any]:
    files = []
    for sibling in info.siblings or []:
        lfs = sibling.lfs
        lfs_sha = (lfs.get("sha256") if isinstance(lfs, dict)
                   else getattr(lfs, "sha256", None)) if lfs else None
        files.append({"path": sibling.rfilename, "bytes": sibling.size,
                      "git_blob": sibling.blob_id, "lfs_sha256": lfs_sha})
    return {"revision": info.sha, "files": files}


def verify_snapshot_files(root: Path, revision: str,
                          consumed: Iterable[dict[str, Any]],
                          manifest: dict[str, Any]) -> dict[str, Any]:
    if not HEX40.fullmatch(revision) or manifest.get("revision") != revision:
        raise ValueError("upstream revision mismatch")
    rows = list(consumed)
    if not rows or len(rows) > MAX_FILES:
        raise ValueError("consumed file count out of bounds")
    upstream = manifest.get("files")
    if not isinstance(upstream, list) or len(upstream) > MAX_FILES:
        raise ValueError("upstream file count out of bounds")
    by_path = {}
    for row in upstream:
        name = row.get("path")
        if not isinstance(name, str) or name in by_path:
            raise ValueError("duplicate or invalid upstream path")
        by_path[name] = row
    base = root.resolve(strict=True)
    seen = set()
    verified = []
    for row in rows:
        name = row.get("path")
        if not isinstance(name, str) or name in seen:
            raise ValueError("duplicate or invalid consumed path")
        path_name = PurePosixPath(name)
        if path_name.is_absolute() or ".." in path_name.parts or str(path_name) != name:
            raise ValueError("unsafe consumed path")
        seen.add(name)
        expected = by_path.get(name)
        if expected is None:
            raise ValueError("consumed file absent from pinned upstream revision")
        path = root / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(base):
            raise ValueError("snapshot path escapes immutable root")
        with path.open("rb") as stream:
            size = path.stat().st_size
            if (type(row.get("bytes")) is not int or size != row["bytes"] or
                    type(expected.get("bytes")) is not int or size != expected["bytes"] or
                    not 0 < size <= MAX_FILE_BYTES):
                raise ValueError(f"snapshot size mismatch: {name}")
            sha256 = hashlib.sha256()
            git_blob = hashlib.sha1(f"blob {size}\0".encode("ascii"))
            while chunk := stream.read(1024 * 1024):
                sha256.update(chunk)
                git_blob.update(chunk)
        actual = sha256.hexdigest()
        if actual != row.get("sha256"):
            raise ValueError("snapshot bytes changed since hashing")
        lfs = expected.get("lfs_sha256")
        blob = expected.get("git_blob")
        if lfs is not None:
            if not isinstance(lfs, str) or not HEX64.fullmatch(lfs) or actual != lfs:
                raise ValueError("snapshot LFS digest mismatch")
        elif not isinstance(blob, str) or not HEX40.fullmatch(blob) or git_blob.hexdigest() != blob:
            raise ValueError("snapshot Git blob mismatch")
        verified.append({"path": name, "bytes": size, "sha256": actual})
    verified.sort(key=lambda row: row["path"])
    return {"schema": "hepta.model-snapshot-upstream-identity.v1",
            "revision": revision,
            "manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest(),
            "verified_files_sha256": hashlib.sha256(canonical(verified)).hexdigest(),
            "verified_file_count": len(verified),
            "snapshot_matches_pinned_revision": True,
            "selection_authority": False, "production_activation": False}


def snapshot_supply_chain_admission(base: dict[str, Any]) -> dict[str, bool]:
    identity = base.get("upstream_identity") or {}
    revision = base.get("revision")
    # The upstream verifier hashes compact JSON; the pre-existing bakeoff
    # manifest hashes that same byte list plus its trailing newline. Bind both
    # domains to the actual consumed list instead of comparing unlike digests.
    rows = base.get("files")
    valid_rows = (isinstance(rows, list) and 0 < len(rows) <= MAX_FILES and
                  all(isinstance(row, dict) and set(row) == {"path", "bytes", "sha256"} and
                      isinstance(row["path"], str) and type(row["bytes"]) is int and
                      0 < row["bytes"] <= MAX_FILE_BYTES and
                      isinstance(row["sha256"], str) and HEX64.fullmatch(row["sha256"]) is not None
                      for row in rows))
    if valid_rows:
        paths = [row["path"] for row in rows]
        valid_rows = (paths == sorted(set(paths)) and all(
            not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts and
            str(PurePosixPath(path)) == path for path in paths))
    compact = canonical(rows) if valid_rows else b""
    byte_proof = (valid_rows and identity.get("verified_file_count") == len(rows) and
                  identity.get("verified_files_sha256") == hashlib.sha256(compact).hexdigest() and
                  base.get("snapshot_digest") == hashlib.sha256(compact + b"\n").hexdigest())
    exact = (isinstance(revision, str) and HEX40.fullmatch(revision) is not None
             and revision == base.get("observed_hub_sha")
             and identity.get("revision") == revision
             and byte_proof
             and base.get("snapshot_matches_pinned_revision") is True
             and identity.get("snapshot_matches_pinned_revision") is True)
    snapshot = base.get("snapshot_digest")
    license_profile = base.get("license_profile")
    return {"exact_revision_bound": exact,
            "snapshot_content_addressed": isinstance(snapshot, str) and HEX64.fullmatch(snapshot) is not None,
            "license_metadata_present": bool(license_profile),
            "permissive_distribution_license": license_profile in {"apache-2.0", "mit"},
            "no_unreviewed_remote_code": base.get("trust_remote_code") is False}


def audit_from_origin(root: Path, repo: str, revision: str) -> dict[str, Any]:
    """Fetch public source metadata without credentials or executing model code."""
    import urllib.request
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("invalid model repository")
    if not HEX40.fullmatch(revision):
        raise ValueError("revision must be an exact Git commit")
    url = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
    with urllib.request.urlopen(url, timeout=25) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("upstream metadata exceeds limit")
    info = json.loads(raw)
    manifest = {"revision": info.get("sha"), "files": [
        {"path": row["rfilename"], "bytes": row.get("size"),
         "git_blob": row.get("blobId"),
         "lfs_sha256": (row.get("lfs") or {}).get("sha256")}
        for row in info.get("siblings", [])]}
    consumed = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".cache" not in path.relative_to(root).parts:
            sha = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    sha.update(chunk)
            consumed.append({"path": str(path.relative_to(root)),
                             "bytes": path.stat().st_size, "sha256": sha.hexdigest()})
    result = verify_snapshot_files(root, revision, consumed, manifest)
    result.update({"validator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "origin": url, "origin_response_sha256": hashlib.sha256(raw).hexdigest(),
                   "model_repo": repo, "snapshot_root": str(root),
                   "model_code_executed": False, "remote_code_reviewed": False,
                   "historical_execution_requalified": False})
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_from_origin(args.root, args.repo, args.revision)
    data = canonical(result)
    with args.output.open("xb") as stream:
        stream.write(data)
    print(json.dumps({"status": "PASS_PINNED_UPSTREAM_SNAPSHOT_IDENTITY",
                      "audit_sha256": hashlib.sha256(data).hexdigest(), **result}))

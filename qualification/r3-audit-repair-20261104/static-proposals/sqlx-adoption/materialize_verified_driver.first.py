#!/usr/bin/env python3
"""Materialize only the exact approved published crate; do not resolve or build it."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parent
INPUT = json.loads((ROOT / "input-manifest.json").read_text())
ARCHIVE_BYTES = 93440
ARCHIVE_SHA256 = "488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c"
PACKAGE = "sqlx-sqlite-0.9.0"
VCS = "003b698e99e024f3621b8043a2426fde5b741171"


def identity(data):
    return {"blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.destination.exists() or args.destination.is_symlink() or args.receipt.exists():
        raise RuntimeError("destination and receipt must both be new")
    raw = args.archive.read_bytes()
    if len(raw) != ARCHIVE_BYTES or hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("published crate bytes/hash do not match the observed Cargo.lock input")
    files = {}
    directories = set()
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                    or str(path) != member.name.rstrip("/")
                    or not path.parts or path.parts[0] != PACKAGE):
                raise RuntimeError("unsafe or unexpected package member path")
            relative = PurePosixPath(*path.parts[1:])
            key = str(relative)
            if key in seen:
                raise RuntimeError("duplicate package member")
            seen.add(key)
            if member.isdir():
                directories.add(key)
                continue
            if not member.isfile() or key == ".":
                raise RuntimeError("non-regular package member requires independent review")
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("missing package member data")
            data = source.read()
            if len(data) != member.size:
                raise RuntimeError("truncated package member")
            files[key] = (data, 0o755 if member.mode & 0o111 else 0o644)
    expected_sources = {s["path"]: s for s in INPUT["git_source_inventory"]["sources"]}
    rust_sources = {path for path in files if path.startswith("src/") and path.endswith(".rs")}
    if rust_sources != set(expected_sources):
        raise RuntimeError("published Rust source roster differs from the reviewed complete Git tree")
    for path, expected in expected_sources.items():
        actual = identity(files[path][0])
        if actual != {key: expected[key] for key in actual}:
            raise RuntimeError("published source differs from fixed source: " + path)
    expected_cargo = next(f["pre"] for f in INPUT["files"] if f["path"].endswith(PACKAGE + "/Cargo.toml"))
    if identity(files["Cargo.toml"][0]) != expected_cargo:
        raise RuntimeError("normalized driver manifest differs from the observed published manifest")
    cargo = tomllib.loads(files["Cargo.toml"][0].decode())
    if (cargo["package"]["name"], cargo["package"]["version"], cargo["package"]["edition"]) != ("sqlx-sqlite", "0.9.0", "2021"):
        raise RuntimeError("unexpected package identity")
    vcs = json.loads(files[".cargo_vcs_info.json"][0])
    if vcs["git"]["sha1"] != VCS or vcs["path_in_vcs"] != "sqlx-sqlite":
        raise RuntimeError("unexpected published VCS identity")
    for license_path in ("LICENSE-APACHE", "LICENSE-MIT"):
        if license_path not in files or len(files[license_path][0]) < 200:
            raise RuntimeError("complete regular published license text is required")
    # All byte/source guards pass before any destination is created.
    args.destination.mkdir(parents=True, exist_ok=False)
    for directory in sorted(directories):
        (args.destination / directory).mkdir(parents=True, exist_ok=True)
    inventory = []
    for relative, (data, mode) in sorted(files.items()):
        target = args.destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(mode)
        if identity(target.read_bytes()) != identity(data):
            raise RuntimeError("post-write byte verification failed")
        inventory.append({"path": relative, "mode": format(mode, "o"), **identity(data)})
    receipt = {"schema": "hepta.sqlx.published-crate-materialization.v1",
               "status": "EXACT_PUBLISHED_ARCHIVE_MATERIALIZED",
               "archive": {"bytes": len(raw), "sha256": ARCHIVE_SHA256},
               "actual_vcs": VCS, "members": inventory,
               "complete_regular_files": len(inventory), "rust_sources": len(rust_sources),
               "driver_patch_applied": False, "scaffold_applied": False,
               "locks_generated": False, "cargo_bazel_or_tests_run": False}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "members": len(inventory),
                      "rust_sources": len(rust_sources), "no_build": True}))


if __name__ == "__main__":
    main()

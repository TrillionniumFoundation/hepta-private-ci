#!/usr/bin/env python3
"""Disposable, non-promoting Matrix 0.19.1 SQLite ABI compatibility experiment.

Authenticates a pinned upstream Cargo manifest by its exact Git blob before
changing ONE dependency only in a scratch copy. A subsequent real Cargo resolve
and compile must still succeed. No signature, advisory waiver or release here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib

SCHEMA = "hepta.matrix-disposable-sqlite-abi-trial.v1"
AUDIT_SCHEMA = "hepta.matrix-disposable-sqlite-abi-audit.v1"
SOURCE_SCHEMA = "hepta.matrix-minimal-hepta-0.19-anymap3-stage.v1"
WORKSPACE_SCHEMA = "hepta.matrix-narrow-sdk-workspace-probe.v1"
RELEASE = "b18166c68bb958a21f0bca8b2d8320cb53583362"
MIGRATION = "9c5fdd2cf5be1b7b8b20541e56d7a109db968534"
MANIFEST_BLOB = "c98e26838da17f295de1fbb0f2960174bddae419"
MANIFEST = Path("crates/matrix-sdk-sqlite/Cargo.toml")
OLD = b'rusqlite = { version = "0.40.2", default-features = false, features = ["limits", "fallible_uint", "cache"] }'
NEW = OLD.replace(b'"0.40.2"', b'"0.39.0"')
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
FORBIDDEN = {"anymap2", "starlark", "codex-cli", "codex-state",
             "codex-execpolicy", "codex-hepta-matrixd"}

def sha256(blob):
    return hashlib.sha256(blob).hexdigest()

def git_blob(blob):
    return hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest()

def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result

def read_json(path, limit=32 * 1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("untrusted JSON evidence")
    return json.loads(path.read_bytes(), object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))

def candidate_bytes(blob):
    if type(blob) is not bytes or not 0 < len(blob) <= 128 * 1024:
        raise ValueError("unbounded/missing SQLite manifest")
    if git_blob(blob) != MANIFEST_BLOB or blob.count(OLD) != 1 or NEW in blob:
        raise ValueError("candidate does not match pinned upstream manifest")
    amended = blob.replace(OLD, NEW, 1)
    a, b = tomllib.loads(blob.decode()), tomllib.loads(amended.decode())
    if (a["package"]["name"], a["package"]["version"]) != ("matrix-sdk-sqlite", "0.19.1"):
        raise ValueError("wrong Matrix SDK family")
    if a["dependencies"]["rusqlite"] != {
        "version": "0.40.2", "default-features": False,
        "features": ["limits", "fallible_uint", "cache"],
    }:
        raise ValueError("changed release dependency contract")
    expected = json.loads(json.dumps(a))
    expected["dependencies"]["rusqlite"]["version"] = "0.39.0"
    if expected != b or amended.replace(NEW, OLD, 1) != blob:
        raise ValueError("unrelated upstream source modification")
    return amended

def stage(sdk_root, hepta_root, source, narrowed, hepta_sha):
    sdk_root, hepta_root = Path(sdk_root).resolve(), Path(hepta_root).resolve()
    if (not HEX40.fullmatch(hepta_sha) or sdk_root == hepta_root
            or sdk_root.is_relative_to(hepta_root) or hepta_root.is_relative_to(sdk_root)
            or not sdk_root.is_dir() or not hepta_root.is_dir()):
        raise ValueError("untrusted scratch roots")
    if (type(source) is not dict or source.get("schema") != SOURCE_SCHEMA
            or source.get("hepta_source_sha") != hepta_sha
            or source.get("signed_upstream_release_sha") != RELEASE
            or source.get("upstream_anymap_change_sha") != MIGRATION
            or not HEX64.fullmatch(source.get("minimal_upstream_patch_sha256", ""))
            or not HEX64.fullmatch(source.get("hepta_candidate_manifest_sha256", ""))
            or Path(source.get("sdk_source_root", "")).resolve() != sdk_root
            or source.get("production_authorized") is not False
            or source.get("cargo_resolution_verified") is not False
            or type(narrowed) is not dict or narrowed.get("schema") != WORKSPACE_SCHEMA
            or narrowed.get("source_sha") != hepta_sha
            or narrowed.get("previous_stage_manifest_sha256") !=
                source["hepta_candidate_manifest_sha256"]
            or narrowed.get("only_direct_workspace_member") != "hepta-matrix-sdk"
            or narrowed.get("cargo_resolution_verified") is not False
            or narrowed.get("production_authorized") is not False):
        raise ValueError("missing pinned source/workspace provenance")
    file = sdk_root / MANIFEST
    if file.is_symlink() or not file.is_file():
        raise ValueError("unsafe upstream manifest path")
    original = file.read_bytes()
    changed = candidate_bytes(original)
    file.write_bytes(changed)
    if file.read_bytes() != changed:
        raise ValueError("scratch write failed")
    return {
        "schema": SCHEMA, "hepta_source_sha": hepta_sha, "sdk_root": str(sdk_root),
        "release_sha": RELEASE, "upstream_git_blob": MANIFEST_BLOB,
        "source_manifest_sha256": sha256(original),
        "trial_manifest_sha256": sha256(changed),
        "only_delta": "rusqlite 0.40.2 to 0.39.0; all features unchanged",
        "expected_rusqlite": "0.39.0", "expected_libsqlite3_sys": "0.37.0",
        "reviewer_approved": False, "cargo_resolution_verified": False,
        "compile_verified": False, "cargo_deny_verified": False,
        "e2ee_runtime_verified": False, "wal_restart_verified": False,
        "production_cargo_lock_modified": False, "production_authorized": False,
    }

def audit_metadata(meta, report, sdk_root, hepta_root):
    sdk_root, hepta_root = Path(sdk_root).resolve(), Path(hepta_root).resolve()
    if (type(report) is not dict or report.get("schema") != SCHEMA
            or report.get("sdk_root") != str(sdk_root)
            or not HEX40.fullmatch(report.get("hepta_source_sha", ""))
            or not HEX64.fullmatch(report.get("trial_manifest_sha256", ""))
            or report.get("expected_rusqlite") != "0.39.0"
            or report.get("expected_libsqlite3_sys") != "0.37.0"
            or report.get("production_authorized") is not False):
        raise ValueError("modified or unverifiable trial receipt")
    file = sdk_root / MANIFEST
    if (file.is_symlink() or not file.is_file()
            or sha256(file.read_bytes()) != report["trial_manifest_sha256"]):
        raise ValueError("candidate changed after staging")
    if type(meta) is not dict or type(meta.get("packages")) is not list:
        raise ValueError("missing real Cargo metadata")
    pkgs = meta["packages"]
    by_id = {p.get("id"): p for p in pkgs if type(p) is dict}
    if len(by_id) != len(pkgs) or None in by_id:
        raise ValueError("duplicate/malformed packages")
    nodes = meta.get("resolve", {}).get("nodes")
    if type(nodes) is not list or not set(meta.get("workspace_members", [])) <= set(by_id):
        raise ValueError("missing full Cargo graph")
    edges, features = {}, {}
    for item in nodes:
        if type(item) is not dict or item.get("id") not in by_id or item["id"] in edges:
            raise ValueError("duplicate/dangling Cargo node")
        children = set()
        for dep in item.get("deps", []):
            if type(dep) is not dict or dep.get("pkg") not in by_id:
                raise ValueError("unregistered Cargo dependency")
            kinds = dep.get("dep_kinds")
            if type(kinds) is not list or not kinds:
                raise ValueError("missing dependency kind")
            for kind in kinds:
                if type(kind) is not dict or kind.get("kind") not in (None, "dev", "build"):
                    raise ValueError("unknown dependency kind")
                if kind["kind"] is None:
                    children.add(dep["pkg"])
        edges[item["id"]] = children
        features[item["id"]] = item.get("features", [])
    if set(edges) != set(by_id):
        raise ValueError("incomplete Cargo resolution")
    if {p.get("name") for p in pkgs} & FORBIDDEN:
        raise ValueError("legacy/CLI runtime component entered isolated graph")

    def single(name, version=None):
        found = [p for p in pkgs if p.get("name") == name]
        if len(found) != 1 or (version is not None and found[0].get("version") != version):
            raise ValueError("missing or multiply resolved " + name)
        return found[0]
    root = single("codex-hepta-matrix-sdk")
    sdk = single("matrix-sdk", "0.19.1")
    sqlite = single("matrix-sdk-sqlite", "0.19.1")
    crypto = single("matrix-sdk-crypto", "0.19.1")
    rusqlite = single("rusqlite", "0.39.0")
    ffi = single("libsqlite3-sys", "0.37.0")
    blake = single("blake3")
    anymap = single("anymap3")
    if ffi.get("links") != "sqlite3" or not {"e2e-encryption", "sqlite"} <= set(features[sdk["id"]]):
        raise ValueError("SQLite link/E2EE features not validated")
    # The trial must use genuine registry packages, not a local stand-in
    # that happens to declare the target versions and links=sqlite3.
    registry = "registry+https://github.com/rust-lang/crates.io-index"
    for package in (rusqlite, ffi):
        # Report the exact invalid evidence field, never silently adopt a
        # path/git crate or a registry package with no trusted checksum.
        # Cargo may finish dependency resolution while its returned package
        # provenance is still insufficient for a secure admission decision.
        if package.get("source") != registry:
            raise ValueError(
                f"native SQLite crate {package['name']} has non-canonical registry source"
            )
        checksum = package.get("checksum")
        if not isinstance(checksum, str) or not HEX64.fullmatch(checksum):
            raise ValueError(
                f"native SQLite crate {package['name']} is missing a 64-hex registry checksum"
            )
    if (Path(root.get("manifest_path", "")).resolve() !=
            hepta_root / "codex-rs/hepta-matrix-sdk/Cargo.toml"
            or Path(sqlite.get("manifest_path", "")).resolve() != file
            or Path(sdk.get("manifest_path", "")).resolve() !=
                sdk_root / "crates/matrix-sdk/Cargo.toml"
            or Path(crypto.get("manifest_path", "")).resolve() !=
                sdk_root / "crates/matrix-sdk-crypto/Cargo.toml"):
        raise ValueError("source path swapped")
    def direct(a, b):
        if b["id"] not in edges[a["id"]]:
            raise ValueError("not a runtime edge: " + a["name"] + " -> " + b["name"])
    direct(root, sdk)
    direct(sdk, sqlite)
    direct(sqlite, rusqlite)
    direct(rusqlite, ffi)
    seen, todo = set(), [sdk["id"]]
    while todo:
        item = todo.pop()
        if item in seen:
            continue
        seen.add(item)
        todo.extend(edges[item] - seen)
    if (crypto["id"] not in seen or blake["id"] not in seen or anymap["id"] not in seen
            or tuple(int(p) for p in blake["version"].split(".")[:3]) < (1, 8, 7)):
        raise ValueError("candidate SDK does not reach patched crypto/AnyMap3")
    return {
        "schema": AUDIT_SCHEMA, "source_sha": report["hepta_source_sha"],
        "candidate_sha256": report["trial_manifest_sha256"],
        "actual_cargo_metadata_checked": True, "runtime_edges_checked": True,
        "sqlite_chain": ["matrix-sdk-sqlite 0.19.1", "rusqlite 0.39.0", "libsqlite3-sys 0.37.0"],
        "sdk_runtime_closure_size": len(seen),
        "compile_verified": False, "cargo_deny_verified": False,
        "e2ee_runtime_verified": False, "wal_restart_verified": False,
        "reviewer_approved": False, "production_authorized": False,
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    a = sub.add_parser("stage")
    a.add_argument("--sdk-root", required=True)
    a.add_argument("--hepta-stage", required=True)
    a.add_argument("--source-report", required=True)
    a.add_argument("--workspace-report", required=True)
    a.add_argument("--hepta-sha", required=True)
    a.add_argument("--output", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--sdk-root", required=True)
    a.add_argument("--hepta-stage", required=True)
    a.add_argument("--trial-report", required=True)
    a.add_argument("--metadata", required=True)
    a.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    sdk, hepta = Path(args.sdk_root).resolve(), Path(args.hepta_stage).resolve()
    if output.exists() or output.is_relative_to(sdk) or output.is_relative_to(hepta):
        parser.error("output must be new and outside all mutable SDK/Hepta sources")
    if args.action == "stage":
        value = stage(sdk, hepta, read_json(args.source_report),
                      read_json(args.workspace_report), args.hepta_sha)
    else:
        value = audit_metadata(read_json(args.metadata), read_json(args.trial_report),
                               sdk, hepta)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(value, sort_keys=True))

if __name__ == "__main__":
    sys.exit(main())

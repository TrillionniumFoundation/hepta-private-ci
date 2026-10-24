#!/usr/bin/env python3
"""Verify a prepared original SDK and its actual complete Cargo resolution.

No build, network or dependency installation. The output is source evidence,
not a statement that the binary compiled or that PasteText worked in a window.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("prepare_original_sdk", Path(__file__).with_name("prepare-native-clipboard-sdk.py"))
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(hepta, prepared, original_bytes, candidate_bytes, config_bytes):
    original = json.loads(original_bytes)
    candidate = json.loads(candidate_bytes)
    if original.get("version") != 1 or candidate.get("version") != 1 or not original.get("resolve") or not candidate.get("resolve"):
        raise ValueError("Both inputs must be full Cargo metadata with dependency resolution")
    PREPARE.require_clipboard_feature(original)
    PREPARE.require_clipboard_feature(candidate)
    manifest_bytes = (hepta / "third_party/makepad-patches/MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest["upstream_commit"] != PREPARE.BASE or manifest["upstream_repository"] != PREPARE.SOURCE:
        raise ValueError("Unsupported original SDK identity")
    prepared = prepared.resolve(strict=True)
    if Path(PREPARE.git(prepared, "rev-parse", "--show-toplevel").decode().strip()) != prepared:
        raise ValueError("Prepared SDK must be the independent source root")
    if PREPARE.git(prepared, "rev-parse", "HEAD").decode().strip() != PREPARE.BASE:
        raise ValueError("Prepared SDK original commit changed")
    if PREPARE.git(prepared, "write-tree").decode().strip() != manifest["patched_tree"]:
        raise ValueError("Prepared SDK tree differs from the exact reviewed patch")
    if PREPARE.git(prepared, "diff", "--name-only") or PREPARE.git(prepared, "ls-files", "--others", "--exclude-standard"):
        raise ValueError("Prepared SDK contains undeclared working source changes")
    for record in manifest["patches"]:
        PREPARE.check((hepta / "third_party/makepad-patches" / record["file"]).read_bytes(), record["sha256"], record["bytes"])
    for record in manifest["changed_files"]:
        PREPARE.check((prepared / record["path"]).read_bytes(), record["patched_sha256"], record["bytes"])
    PREPARE.check((prepared / manifest["license"]["path"]).read_bytes(), manifest["license"]["sha256"], manifest["license"]["bytes"])
    entries, config = PREPARE.cargo_override(original, prepared)
    if config_bytes != config.encode():
        raise ValueError("Cargo overrides do not cover the exact complete original SDK graph")
    if any((entry.get("source") or "").startswith("git+" + PREPARE.SOURCE) for entry in candidate["packages"]):
        raise ValueError("Candidate still resolves a Git SDK alongside the prepared SDK")
    resolved = []
    expected = {(entry["name"], entry["version"]): entry for entry in entries}
    sdk_names = {entry["name"] for entry in entries}
    original_sdk = {entry["id"]: entry for entry in original["packages"]
                    if entry.get("source") == PREPARE.ORIGINAL_SOURCE}
    original_others = {(entry["name"], entry["version"], entry.get("source"))
                       for entry in original["packages"] if entry["id"] not in original_sdk}
    candidate_sdk = {}
    for entry in candidate["packages"]:
        path = Path(entry["manifest_path"]).resolve(strict=True)
        identity = (entry["name"], entry["version"])
        inside = path.is_relative_to(prepared)
        if not inside:
            if (entry["name"] in sdk_names or entry["name"].startswith("makepad-")) and (*identity, entry.get("source")) not in original_others:
                raise ValueError("Substituted or duplicate SDK source: " + entry["name"])
            continue
        want = expected.get(identity)
        if (want is None or not inside or entry.get("source") is not None
                or path != prepared / want["manifest"]):
            raise ValueError("Mixed, missing or substituted SDK package: " + entry["name"])
        resolved.append({"name": entry["name"], "version": entry["version"], "manifest": want["manifest"]})
        candidate_sdk[entry["id"]] = entry
    if len(resolved) != len(entries) or len({(entry["name"], entry["version"]) for entry in resolved}) != len(entries):
        raise ValueError("Candidate does not resolve every original SDK package exactly once")
    original_nodes = {entry["id"]: entry for entry in original["resolve"]["nodes"]}
    candidate_nodes = {entry["id"]: entry for entry in candidate["resolve"]["nodes"]}
    candidate_by_identity = {(entry["name"], entry["version"]): entry for entry in candidate_sdk.values()}
    for package_id, entry in original_sdk.items():
        counterpart = candidate_by_identity[(entry["name"], entry["version"])]
        if package_id not in original_nodes or counterpart["id"] not in candidate_nodes:
            raise ValueError("An SDK package is absent from the actual Cargo dependency graph")
        def edges(node, packages):
            return {(dependency["name"], packages[dependency["pkg"]]["name"], packages[dependency["pkg"]]["version"])
                    for dependency in node["deps"] if dependency["pkg"] in packages}
        if edges(original_nodes[package_id], original_sdk) != edges(candidate_nodes[counterpart["id"]], candidate_sdk):
            raise ValueError("An original SDK dependency edge points to a different source: " + entry["name"])
    return {"schema": "hepta.verified-original-sdk-source.v1", "native_ui_feature": PREPARE.UI_FEATURE,
            "upstream_repository": PREPARE.SOURCE,
            "upstream_commit": PREPARE.BASE, "patched_tree": manifest["patched_tree"],
            "manifest_sha256": sha(manifest_bytes), "patches": manifest["patches"],
            "prepared_root": str(prepared), "resolved_packages": sorted(resolved, key=lambda item: (item["name"], item["version"])),
            "original_metadata_sha256": sha(original_bytes), "candidate_metadata_sha256": sha(candidate_bytes),
            "cargo_config_sha256": sha(config_bytes), "source_tree_verified": True,
            "all_sdk_packages_same_tree": True, "dependency_edges_verified": True,
            "compiled": False, "runtime_qualified": False,
            "effects_authority": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hepta-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--prepared-source", type=Path, required=True)
    parser.add_argument("--original-metadata", type=Path, required=True)
    parser.add_argument("--candidate-metadata", type=Path, required=True)
    parser.add_argument("--cargo-config", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(verify(options.hepta_root.resolve(strict=True), options.prepared_source,
                            options.original_metadata.read_bytes(), options.candidate_metadata.read_bytes(),
                            options.cargo_config.read_bytes()), indent=2) + "\n")

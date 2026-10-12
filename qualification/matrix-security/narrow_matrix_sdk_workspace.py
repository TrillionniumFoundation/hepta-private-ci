#!/usr/bin/env python3
"""Stage a narrowly resolved, REAL Hepta Matrix SDK adapter for diagnostics only.

The production Cargo workspace and locks are never touched. A successful
scratch SDK compile is NOT a full Hepta Matrixd compile, cargo-deny approval,
E2EE/WAL runtime qualification, or a license to activate any production route.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

SCHEMA = "hepta.matrix-narrow-sdk-workspace-probe.v1"
SOURCE_SCHEMA = "hepta.matrix-minimal-hepta-0.19-anymap3-stage.v1"
PINNED_RELEASE_SHA = "b18166c68bb958a21f0bca8b2d8320cb53583362"
PINNED_MIGRATION_SHA = "9c5fdd2cf5be1b7b8b20541e56d7a109db968534"
MEMBER = "hepta-matrix-sdk"
MAX_MANIFEST = 128 * 1024
MAX_METADATA = 32 * 1024 * 1024
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _as_document(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_MANIFEST:
        raise ValueError("missing or unbounded manifest bytes")
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("invalid Cargo manifest") from error


def rewrite_workspace(raw):
    """Replace only the resolver *membership* in a disposable manifest.

    Cargo may still add local path dependencies as workspace members. We do
    not disable E2EE/SQLite, change any SDK/crypto source, or prune packages
    from Cargo metadata. Dependencies are resolved by real Cargo afterwards.
    """
    doc = _as_document(raw)
    workspace = doc.get("workspace", {})
    members = workspace.get("members")
    expected = {"hepta-matrix-sdk", "hepta-matrixd", "cli", "execpolicy"}
    if (not isinstance(members, list) or any(type(m) is not str for m in members)
            or not expected.issubset(set(members)) or len(members) < 100
            or len(members) != len(set(members))
            or workspace.get("resolver") != "2"
            or "exclude" in workspace or "default-members" in workspace):
        raise ValueError("unexpected full-workspace membership contract")
    sdk = doc.get("workspace", {}).get("dependencies", {}).get("matrix-sdk")
    if (type(sdk) is not dict or type(sdk.get("path")) is not str
            or not sdk["path"].startswith("../")
            or sdk.get("default-features") is not False
            or sdk.get("features") != ["e2e-encryption", "sqlite"]):
        raise ValueError("not a vetted, out-of-worktree Matrix SDK candidate")
    source = raw.decode("utf-8")
    m = re.match(r"\A\[workspace\]\nmembers = \[\n(?:[^\n]*\n)*?\]\n", source)
    if m is None:
        raise ValueError("unexpected original Cargo members block")
    replacement = '[workspace]\nmembers = ["hepta-matrix-sdk"]\n'
    edited = replacement + source[m.end():]
    after = _as_document(edited)
    if after["workspace"]["members"] != [MEMBER]:
        raise ValueError("workspace edit not applied exactly")
    # No package/dependency/security configuration may have changed.
    expanded = dict(after["workspace"])
    expanded["members"] = members
    if expanded != workspace:
        raise ValueError("unrelated workspace property changed")
    for key in doc:
        if key != "workspace" and after.get(key) != doc[key]:
            raise ValueError("unrelated manifest property changed")
    if len(edited) >= len(raw):
        raise ValueError("workspace was not actually narrowed")
    return edited


def _git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, check=True, text=True)
    return result.stdout.strip()


def stage_narrow_sdk(stage, source_report, source_sha):
    """Mutate ONLY an externally detached scratch Hepta checkout."""
    stage = Path(stage).resolve()
    if not isinstance(source_sha, str) or not HEX40.fullmatch(source_sha):
        raise ValueError("unbound source SHA")
    if stage.is_symlink() or not (stage / ".git").exists():
        raise ValueError("not a detached audited Git worktree")
    if _git(stage, "rev-parse", "HEAD") != source_sha:
        raise ValueError("staged source identity mismatch")
    modified = _git(stage, "diff", "--name-only").splitlines()
    if modified != ["codex-rs/Cargo.toml"]:
        raise ValueError("unexpected scratch changes before SDK isolation")
    if (type(source_report) is not dict
            or source_report.get("schema") != SOURCE_SCHEMA
            or source_report.get("hepta_source_sha") != source_sha
            or source_report.get("signed_upstream_release_sha") != PINNED_RELEASE_SHA
            or source_report.get("upstream_anymap_change_sha") != PINNED_MIGRATION_SHA
            or not isinstance(source_report.get("minimal_upstream_patch_sha256"), str)
            or not HEX64.fullmatch(source_report["minimal_upstream_patch_sha256"])
            or source_report.get("production_authorized") is not False
            or source_report.get("cargo_resolution_verified") is not False):
        raise ValueError("unverified prior signed-release source staging")
    candidate = stage / "codex-rs/Cargo.toml"
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("untrusted scratch Cargo.toml")
    before = candidate.read_bytes()
    if digest(before) != source_report.get("hepta_candidate_manifest_sha256"):
        raise ValueError("mutated source candidate before workspace narrowing")
    candidate_root = Path(source_report.get("sdk_source_root", "")).resolve()
    if (not candidate_root.is_dir() or candidate_root.is_relative_to(stage)
            or candidate_root == stage
            or not (candidate_root / "crates/matrix-sdk/Cargo.toml").is_file()):
        raise ValueError("signed-release source directory missing or unsafe")
    sdk_clause = _as_document(before)["workspace"]["dependencies"]["matrix-sdk"]
    configured_sdk = (candidate.parent / sdk_clause["path"]).resolve()
    if configured_sdk != candidate_root / "crates/matrix-sdk":
        raise ValueError("Matrix SDK candidate path differs from pinned source report")
    new = rewrite_workspace(before)
    candidate.write_bytes(new)
    if _git(stage, "diff", "--name-only").splitlines() != ["codex-rs/Cargo.toml"]:
        raise ValueError("workspace experiment escaped staged manifest")
    return {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "previous_stage_manifest_sha256": digest(before),
        "narrowed_manifest_sha256": digest(new),
        "only_direct_workspace_member": MEMBER,
        "sdk_e2ee_and_sqlite_required": True,
        "hepta_production_workspace_modified": False,
        "production_cargo_lock_modified": False,
        "cargo_resolution_verified": False,
        "matrix_adapter_compilation_verified": False,
        "full_matrixd_compilation_verified": False,
        "signed_current_authorized": False,
        "cargo_deny_verified": False,
        "e2ee_runtime_verified": False,
        "sqlite_wal_recovery_verified": False,
        "production_authorized": False,
    }


def inspect_cargo_metadata(payload, *, candidate_root, stage_root):
    """Refuse old crypto, old anymap, CLI/Starlark or foreign SDK resolution."""
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_METADATA:
        raise ValueError("unbounded/incomplete Cargo metadata")
    try:
        data = json.loads(payload)
    except (UnicodeError, ValueError) as error:
        raise ValueError("malformed Cargo metadata") from error
    if type(data) is not dict or type(data.get("packages")) is not list:
        raise ValueError("missing actual Cargo package graph")
    packages = data["packages"]
    members = set(data.get("workspace_members", []))
    selected = [p for p in packages if p.get("name") == "codex-hepta-matrix-sdk"]
    sdk = [p for p in packages if p.get("name") == "matrix-sdk"]
    crypto = [p for p in packages if p.get("name") == "matrix-sdk-crypto"]
    names = {p.get("name") for p in packages}
    if (len(selected) != 1 or selected[0].get("id") not in members
            or len(sdk) != 1 or sdk[0].get("version") != "0.19.1"
            or not Path(sdk[0].get("manifest_path", "")).resolve()
                .is_relative_to(Path(candidate_root).resolve())
            or not Path(selected[0].get("manifest_path", "")).resolve()
                .is_relative_to(Path(stage_root).resolve())
            or not crypto or
            any(tuple(int(x) for x in p["version"].split(".")[:2]) < (0, 19)
                for p in crypto)
            or "anymap2" in names or "anymap3" not in names
            or "starlark" in names or "codex-cli" in names
            or "codex-hepta-matrixd" in names
            or not any(p.get("name") == "blake3" and
                       tuple(int(x) for x in p["version"].split(".")[:3]) >= (1, 8, 7)
                       for p in packages)):
        raise ValueError("narrowed graph is vulnerable, inconsistent, or still coupled to CLI")
    return {
        "schema": "hepta.matrix-narrow-sdk-graph-verification.v1",
        "package_count": len(packages),
        "sdk_version": sdk[0]["version"],
        "crypto_versions": sorted({p["version"] for p in crypto}),
        "anymap2": False,
        "anymap3": True,
        "cli_starlark_absent": True,
        "blake3_min_1_8_7": True,
        "matrix_adapter_compilation_verified": False,
        "full_matrixd_compilation_verified": False,
        "cargo_deny_verified": False,
        "production_authorized": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--source-report", type=Path, required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(args.stage.resolve()):
        p.error("output must be new and outside detached source checkout")
    report = json.loads(args.source_report.read_text(encoding="utf-8"))
    result = stage_narrow_sdk(args.stage, report, args.source_sha)
    with output.open("x", encoding="utf-8") as f:
        json.dump(result, f, sort_keys=True, indent=2)
        f.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

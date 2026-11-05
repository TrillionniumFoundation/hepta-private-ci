#!/usr/bin/env python3
"""Reconstruct the complete vendor source in an isolated directory; never build."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
DRIVER = ROOT.parent / "sqlx-native-lifetime-token-20261105"
PREFIX = "codex-rs/third_party/sqlx-sqlite-0.9.0/"
WORK = ROOT / "complete-vendor-static-assembly"


def identity(data):
    return {"blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    original = json.loads((ROOT / "published-crate-materialization.json").read_text())
    scaffold = json.loads((ROOT / "input-manifest.json").read_text())
    driver = json.loads((DRIVER / "input-manifest-v3.json").read_text())
    licenses = json.loads((ROOT / "vendor-license-overlay.json").read_text())
    if WORK.exists() or WORK.is_symlink():
        raise RuntimeError("assembly directory must be new")
    expected = {}
    mode_changes = []
    for member in original["members"]:
        source = ROOT / "original-published-package" / member["path"]
        data = source.read_bytes()
        assert identity(data) == {k: member[k] for k in ("blob", "bytes", "sha256")}
        assert format(source.stat().st_mode & 0o777, "o") == member["mode"]
        target = WORK / PREFIX / member["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
        expected[PREFIX + member["path"]] = identity(data)
        if member["mode"] != "644":
            mode_changes.append({"path": PREFIX + member["path"], "archive_mode": member["mode"], "vendor_mode": "100644"})
    cargo = next(f for f in scaffold["files"] if f["path"] == "codex-rs/Cargo.toml")
    data = (ROOT / "source/codex-rs/Cargo.toml").read_bytes()
    assert identity(data) == cargo["pre"]
    (WORK / cargo["path"]).write_bytes(data)
    expected[cargo["path"]] = cargo["pre"]
    env = os.environ.copy()
    env.update({"GIT_CEILING_DIRECTORIES": str(WORK), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    stages = []
    driver_patch = next(p for p in driver["patches"] if p["name"] == "full")
    operations = [
        ("reviewed-driver", DRIVER / driver_patch["path"], driver_patch, ["-p2", "--directory=" + PREFIX.rstrip("/")]),
        ("reviewed-scaffold", ROOT / "adoption-scaffold.patch", scaffold["patch"], []),
        ("upstream-license-overlay", ROOT / "vendor-license-overlay.patch", licenses["patch"], []),
    ]
    for name, patch, proof, flags in operations:
        assert identity(patch.read_bytes()) == {k: proof[k] for k in ("blob", "bytes", "sha256")}
        commands = []
        for check in (True, False):
            argv = ["git", "apply", "--whitespace=error-all", *flags]
            if check:
                argv.append("--check")
            result = subprocess.run(argv + [str(patch)], cwd=WORK, env=env, capture_output=True)
            commands.append({"argv": argv + [patch.name], "exit_code": result.returncode,
                             "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
            assert result.returncode == 0, commands[-1]
        if name == "reviewed-driver":
            for file in driver["files"]:
                path = PREFIX + file["path"].removeprefix("sqlx-sqlite/")
                expected[path] = {k: file[k] for k in ("blob", "bytes", "sha256")}
        elif name == "reviewed-scaffold":
            for file in scaffold["files"]:
                expected[file["path"]] = file["post"]
        else:
            for file in licenses["files"]:
                expected[file["path"]] = {k: file["vendor_overlay"][k] for k in ("blob", "bytes", "sha256")}
        actual = {}
        for file in WORK.rglob("*"):
            assert not file.is_symlink()
            if file.is_file():
                assert (file.stat().st_mode & 0o777) == 0o644
                actual[str(file.relative_to(WORK))] = identity(file.read_bytes())
        assert actual == expected, name
        stages.append({"name": name, "patch": identity(patch.read_bytes()), "commands": commands,
                       "exact_files": len(actual)})
    receipt = {
        "schema": "hepta.sqlx.complete-vendor-static-assembly.v1",
        "status": "COMPLETE_ARCHIVE_PLUS_REVIEWED_OVERLAYS_STATIC_PASS",
        "archive_bytes": 93440, "archive_sha256": original["archive"]["sha256"],
        "original_member_count": len(original["members"]), "original_member_bytes": sum(m["bytes"] for m in original["members"]),
        "all_original_source_hashes_verified": True,
        "mode_only_normalization": mode_changes,
        "mode_scope": "All vendor regular files are mode100644; original archive modes remain in the complete immutable member receipt.",
        "stages": stages, "final_files": len(expected),
        "final_source_map": [{"path": path, "mode": "100644", **info} for path, info in sorted(expected.items())],
        "scope": "Only isolated cloud source assembly. No complete product tree, dependency resolution, Cargo, Bazel, original tests, native worktree, target or ref mutation.",
        "lock_scope": "The published package's nested Cargo.lock is preserved original source data; the actual workspace Cargo.lock and MODULE.bazel.lock still require real original generation."
    }
    (ROOT / "complete-vendor-static-assembly.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "stages": len(stages), "files": len(expected),
                      "mode_only_changes": len(mode_changes), "cargo_bazel_tests_run": False}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate only source reconstruction and existing metadata; run no Cargo."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parent
INPUT = json.loads((ROOT / "input-manifest.json").read_text())
WORK = ROOT / "static-reconstruction"


def identity(data):
    return {"blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    WORK.mkdir(exist_ok=False)
    for file in INPUT["files"]:
        path = file["path"]
        if file["pre"] is not None:
            data = (ROOT / "source" / path).read_bytes()
            assert identity(data) == file["pre"]
            target = WORK / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        assert identity((ROOT / "repair-source" / path).read_bytes()) == file["post"]
    patch = ROOT / "adoption-scaffold.patch"
    assert identity(patch.read_bytes()) == INPUT["patch"]
    env = os.environ.copy()
    env["GIT_CEILING_DIRECTORIES"] = str(WORK)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    commands = []
    for check in (True, False):
        argv = ["git", "apply", "--whitespace=error-all"]
        if check:
            argv.append("--check")
        result = subprocess.run(argv + [str(patch)], cwd=WORK, env=env, capture_output=True)
        commands.append({"argv": argv + [patch.name], "exit_code": result.returncode,
                         "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
        assert result.returncode == 0, commands[-1]
    observed = {str(p.relative_to(WORK)): identity(p.read_bytes()) for p in WORK.rglob("*") if p.is_file()}
    assert observed == {f["path"]: f["post"] for f in INPUT["files"]}
    workspace_path = "codex-rs/Cargo.toml"
    old = tomllib.loads((ROOT / "source" / workspace_path).read_text())
    new = tomllib.loads((WORK / workspace_path).read_text())
    member = "third_party/sqlx-sqlite-0.9.0"
    assert member not in old["workspace"]["members"]
    assert new["workspace"]["members"].count(member) == 1
    new["workspace"]["members"].remove(member)
    assert new["patch"]["crates-io"].pop("sqlx-sqlite") == {"path": member}
    assert new == old
    driver_path = "codex-rs/third_party/sqlx-sqlite-0.9.0/Cargo.toml"
    old = tomllib.loads((ROOT / "source" / driver_path).read_text())
    new = tomllib.loads((WORK / driver_path).read_text())
    assert old["dev-dependencies"] == {}
    assert new["dev-dependencies"].pop("sqlx-core") == {"version": "=0.9.0", "features": ["_rt-tokio"]}
    assert new == old
    # This is a previously produced complete A metadata artifact, never a new native call.
    metadata_path = ROOT.parent.parent / "ci-audit/recovered-20261105/full-owning-compressed-archive/full-workspace-metadata-stdout.original"
    data = metadata_path.read_bytes()
    assert len(data) == INPUT["native_metadata"]["bytes"]
    assert hashlib.sha256(data).hexdigest() == INPUT["native_metadata"]["sha256"]
    metadata = json.loads(data)
    names = {"sqlx-sqlite", "sqlx-core", "libsqlite3-sys", "tokio", "codex-state"}
    packages = {p["id"]: p for p in metadata["packages"] if p["name"] in names}
    nodes = []
    for node in metadata["resolve"]["nodes"]:
        if node["id"] in packages:
            package = packages[node["id"]]
            # Avoid publishing machine-local manifest or target paths.
            nodes.append({"name": package["name"], "version": package["version"],
                          "features": node["features"],
                          "workspace_member": package["id"] in metadata["workspace_members"]})
    sqlite = [n for n in nodes if n["name"] == "sqlx-sqlite"]
    assert len(sqlite) == 1 and sqlite[0]["version"] == "0.9.0"
    assert sqlite[0]["features"] == INPUT["product_features"]
    assert not sqlite[0]["workspace_member"]
    output = {"schema": "hepta.sqlx.adoption-scaffold.static-proof.v1",
              "status": "STATIC_PATCH_AND_TOML_SCOPE_PASS",
              "commands": commands, "exact_three_postimages": observed,
              "only_workspace_member_and_patch_added": True,
              "only_driver_dev_runtime_edge_added": True,
              "observed_A_metadata": INPUT["native_metadata"],
              "observed_A_nodes": nodes,
              "proposed_B_member_not_executed": True,
              "cargo_bazel_native_or_ref_mutation": False,
              "complete_vendor_extraction_and_generated_locks_pending": True}
    (ROOT / "static-verification.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"status": output["status"], "postimages": len(observed),
                      "native_package_selection_or_tests_run": False}))


if __name__ == "__main__":
    main()

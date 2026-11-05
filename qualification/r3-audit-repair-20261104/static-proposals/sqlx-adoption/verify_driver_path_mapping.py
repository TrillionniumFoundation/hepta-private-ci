#!/usr/bin/env python3
"""Check the reviewed driver patches at the proposed vendor path, without Cargo."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
DRIVER = ROOT.parent / "sqlx-native-lifetime-token-20261105"
SOURCE = ROOT.parent / "sqlx-pre-registration-custody-20261105/sources/sqlx"
INPUT = json.loads((DRIVER / "input-manifest-v3.json").read_text())
WORK = ROOT / "static-driver-path-mapping"
PREFIX = "codex-rs/third_party/sqlx-sqlite-0.9.0/"


def identity(data):
    return {"blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def mapped(path):
    assert path.startswith("sqlx-sqlite/")
    return PREFIX + path.removeprefix("sqlx-sqlite/")


def inventory():
    return {str(p.relative_to(WORK)): identity(p.read_bytes())["blob"]
            for p in WORK.rglob("*") if p.is_file()}


def main():
    WORK.mkdir(exist_ok=False)
    for file in INPUT["files"]:
        if file["before_blob"] is not None:
            data = (SOURCE / file["path"]).read_bytes()
            assert identity(data)["blob"] == file["before_blob"]
            target = WORK / mapped(file["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    final = {mapped(f["path"]): f["blob"] for f in INPUT["files"]}
    env = os.environ.copy()
    env["GIT_CEILING_DIRECTORIES"] = str(WORK)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    phases = []
    for patch in INPUT["patches"]:
        path = DRIVER / patch["path"]
        assert identity(path.read_bytes()) == {k: patch[k] for k in ("blob", "bytes", "sha256")}
        commands = []
        for check in (True, False):
            argv = ["git", "apply", "--whitespace=error-all", "-p2", "--directory=" + PREFIX.rstrip("/")]
            if check:
                argv.append("--check")
            result = subprocess.run(argv + [str(path)], cwd=WORK, env=env, capture_output=True)
            commands.append({"argv": argv + [path.name], "exit_code": result.returncode,
                             "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
            assert result.returncode == 0, commands[-1]
        expected = dict(final)
        if patch["name"] in INPUT["negative_postimages"]:
            negative = INPUT["negative_postimages"][patch["name"]]
            expected[mapped(negative["path"])] = negative["blob"]
        actual = inventory()
        assert actual == expected, patch["name"]
        phases.append({"name": patch["name"], "patch_blob": patch["blob"],
                       "commands": commands, "exact_partial_source_map": actual})
    output = {"schema": "hepta.sqlx.vendor-path.static-proof.v1",
              "status": "STATIC_VENDOR_PATH_MAPPING_PASS",
              "phases": phases, "final_source_map": inventory(),
              "complete_crate_materialized": False,
              "native_cargo_bazel_or_ref_mutation": False,
              "scope": "The three original driver source preimages and five reviewed patch postimages only; this is not a complete vendor package or runtime qualification."}
    (ROOT / "driver-path-mapping-proof.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"status": output["status"], "phases": len(phases),
                      "mapped_postimages": len(final), "complete_crate_materialized": False}))


if __name__ == "__main__":
    main()

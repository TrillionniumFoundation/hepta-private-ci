#!/usr/bin/env python3
"""Capture the real locked workspace member profile without compiling tests."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "5d19a578ac28a6ce7fc67a348b10297dc370c19f"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=ROOT)


def snapshot():
    result = {}
    for item in git("ls-files", "--stage", "-z").split(b"\0"):
        if not item:
            continue
        meta, name = item.split(b"\t", 1)
        mode, expected, stage = meta.decode().split()
        name = os.fsdecode(name)
        require(stage == "0" and mode in {"100644", "100755", "120000"}, "unsupported source input")
        path = ROOT / name
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(blob == expected, "source bytes differ from tracked Git input: " + name)
        result[name] = {"mode": mode, "git_blob": blob, "bytes": len(data), "sha256": digest(data)}
    require(not git("status", "--porcelain=v1", "--untracked-files=all"), "dirty source")
    return dict(sorted(result.items()))


def profile(metadata, before):
    require(metadata["version"] == 1, "unexpected Cargo metadata version")
    require(Path(metadata["workspace_root"]).resolve() == ROOT / "codex-rs", "wrong workspace")
    members = metadata["workspace_members"]
    require(isinstance(members, list) and members and len(members) == len(set(members)), "duplicate or empty workspace IDs")
    rows = metadata["packages"]
    by_id = {row["id"]: row for row in rows}
    require(len(rows) == len(by_id) and set(by_id) == set(members), "no-deps package/member identities differ")
    projected, manifests = [], []
    for identifier in members:
        row = by_id[identifier]
        require(row["source"] is None, "workspace member is not a local package")
        path = Path(row["manifest_path"])
        require(path.is_absolute() and path.is_file() and not path.is_symlink(), "invalid manifest")
        relative = path.resolve().relative_to(ROOT).as_posix()
        require(relative in before and relative.endswith("/Cargo.toml"), "untracked member manifest")
        require(isinstance(row["name"], str) and row["name"] and isinstance(row["version"], str) and row["version"], "invalid member identity")
        projected.append({"name": row["name"], "version": row["version"], "manifest_path": relative})
        manifests.append({"id": identifier, "manifest_path": relative, **before[relative]})
    require(len({row["name"] for row in projected}) == len(projected), "duplicate workspace package name")
    require(len({row["manifest_path"] for row in projected}) == len(projected), "duplicate member manifest")
    require({"codex-hepta-memory", "codex-hepta-agentd"} <= {row["name"] for row in projected}, "missing original owner package")
    return {"schema": 1, "workspace_manifest": "codex-rs/Cargo.toml",
            "member_count": len(projected),
            "members": sorted(projected, key=lambda row: (row["name"], row["manifest_path"]))}, manifests


def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    require(not out.is_relative_to(ROOT), "output must be outside source")
    out.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": 1, "status": "failed", "base": BASE, "commands": [],
               "native_executions": 0, "test_qualification": False}
    before = None

    def run(name, argv, cwd=ROOT):
        stdout, stderr = out / (name + ".stdout"), out / (name + ".stderr")
        with stdout.open("wb") as output, stderr.open("wb") as errors:
            process = subprocess.run(argv, cwd=cwd, stdout=output, stderr=errors, check=False)
        receipt["commands"].append({"name": name, "argv": argv, "exit_code": process.returncode,
                                    "stdout_sha256": digest(stdout.read_bytes()), "stderr_sha256": digest(stderr.read_bytes())})
        if process.returncode:
            print(stderr.read_text(errors="replace")[-16000:], flush=True)
        require(process.returncode == 0, name + " failed")
        return stdout.read_bytes()

    try:
        receipt["source"] = git("rev-parse", "HEAD").decode().strip()
        receipt["tree"] = git("rev-parse", "HEAD^{tree}").decode().strip()
        require(receipt["source"] == os.environ["GITHUB_SHA"], "wrong dispatched source")
        before = snapshot()
        (out / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")
        version = run("rustc-version", ["rustc", "-Vv"]).decode()
        require(version.startswith("rustc 1.96.0 "), "wrong original toolchain")
        data = run("original-metadata", ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"], ROOT / "codex-rs")
        record, manifests = profile(json.loads(data), before)
        raw = (json.dumps(record, indent=2) + "\n").encode()
        (out / "workspace-profile.json").write_bytes(raw)
        (out / "workspace-manifests.json").write_text(json.dumps(manifests, indent=2) + "\n")
        encoded = base64.b64encode(raw).decode("ascii")
        identity = {"bytes": len(raw), "sha256": digest(raw),
                    "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
        print("EXACT_WORKSPACE_PROFILE_BEGIN=" + json.dumps(identity), flush=True)
        for offset in range(0, len(encoded), 12000):
            print("EXACT_WORKSPACE_PROFILE_FRAME=" + json.dumps({"offset": offset, "base64": encoded[offset:offset + 12000]}), flush=True)
        print("EXACT_WORKSPACE_PROFILE_END=" + json.dumps(identity), flush=True)
        receipt["workspace_profile"] = identity
        receipt["member_count"] = record["member_count"]
        require(snapshot() == before, "original metadata changed source")
        receipt["status"] = "passed"
    finally:
        after = snapshot()
        (out / "source-after.json").write_text(json.dumps(after, indent=2) + "\n")
        receipt["source_inputs_unchanged"] = before is not None and before == after
        if not receipt["source_inputs_unchanged"]:
            receipt["status"] = "failed"
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
                              for p in sorted(out.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("WORKSPACE_PROFILE_RESULT=" + json.dumps({key: value for key, value in receipt.items() if key != "outputs"}), flush=True)
    require(receipt["status"] == "passed", "profile capture failed")


if __name__ == "__main__":
    main()

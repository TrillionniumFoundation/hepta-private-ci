"""Byte-verify the frozen main crates; build an isolated research owner harness.

The unmodified repository justfile/run-nextest.py remains the test entry point.
No production workspace or frozen bridge source is changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent


def run(command, cwd, env):
    start = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
    return dict(command=command, cwd=str(cwd), returncode=result.returncode,
                stdout=result.stdout, stderr=result.stderr, wall_seconds=time.perf_counter()-start)


def prepare(args):
    build = args.build.resolve()
    build.mkdir(parents=True, exist_ok=True)
    upstream = args.existing_build.resolve() / "upstream"
    identity = json.loads((HERE / "SOURCE_IDENTITY.json").read_text())
    sources = {}
    for item in identity["files"]:
        data = (upstream / item["path"]).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != item["git_blob_sha"]:
            raise ValueError(("upstream identity mismatch", item["path"]))
        sources[item["path"]] = hashlib.sha256(data).hexdigest()
    owned = {}
    for path in sorted(HERE.glob("*.rs")):
        shutil.copyfile(path, build / path.name)
        owned[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(dict(upstream=sources, owned=owned), sort_keys=True).encode()).hexdigest()
    manifest = (args.existing_build / "Cargo.toml").read_text().replace("codex-task-native-v2", "codex-native-event-owner-r8")
    (build / "Cargo.toml").write_text(manifest)
    (build / "Cargo.lock").write_text((args.existing_build / "Cargo.lock").read_text().replace("codex-task-native-v2", "codex-native-event-owner-r8"))
    shutil.copyfile(args.existing_build / "nextest.toml", build / "nextest.toml")
    return build, sources, owned, digest, manifest


def main(args):
    build, sources, owned, digest, manifest = prepare(args)
    env = os.environ.copy()
    env.update(PATH=f"{args.toolchain}/bin:{args.tools}:{env['PATH']}", RUSTC=str(args.toolchain / "bin/rustc"),
               CARGO_HOME=str(args.existing_build / "cargo-home"), CARGO_TARGET_DIR=str(args.existing_build / "target"),
               CARGO_INCREMENTAL="0", CARGO_BUILD_JOBS="2", HEPTA_TASK_NATIVE_SOURCE_DIGEST=digest)
    commands = [run(["rustc", "--version", "--verbose"], build, env),
                run(["cargo", "generate-lockfile", "--offline", "--manifest-path", str(build / "Cargo.toml")], build, env),
                run(["cargo", "build", "--offline", "--locked", "--manifest-path", str(build / "Cargo.toml")], build, env)]
    if all(row["returncode"] == 0 for row in commands):
        commands.append(run(["just", "test", "--offline", "--locked", "--manifest-path", str(build / "Cargo.toml"),
                             "--config-file", str(build / "nextest.toml"), "-p", "codex-native-event-owner-r8"], args.workflow, env))
    binary = args.existing_build / "target/debug/codex-native-event-owner-r8"
    result = dict(schema="hcsn.native-event-owner-build.v1", success=all(x["returncode"] == 0 for x in commands),
                  source_digest=digest, source_files=sources, owned_files=owned, manifest=manifest,
                  binary=str(binary), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest() if binary.is_file() else None,
                  derived_lock=(build / "Cargo.lock").read_text(),
                  dependency_source="Cargo offline locked cache; archives must be present",
                  commands=commands, production_activation=False)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: result[k] for k in ("success", "source_digest", "binary")}))
    for row in commands:
        if row["returncode"]:
            print(row["stdout"] + row["stderr"])
    return result["success"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("build", "existing-build", "workflow", "toolchain", "tools", "report"):
        p.add_argument("--"+key, type=Path, required=True)
    raise SystemExit(0 if main(p.parse_args()) else 1)

"""Compile current Rust sources against fingerprint-verified preserved Cargo rlibs.

This is a direct rustc rebuild, not a fresh Cargo dependency build. Reproduction
may instead use the frozen upstream manifests to rebuild those dependencies.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, cwd, env):
    start = time.perf_counter()
    proc = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True)
    return dict(command=argv, cwd=str(cwd), returncode=proc.returncode,
                stdout=proc.stdout, stderr=proc.stderr, wall_seconds=time.perf_counter()-start)


def main(args):
    args.build.mkdir(parents=True, exist_ok=True)
    prior = json.loads(args.prior_report.read_text())
    if not prior["success"]:
        raise ValueError("unverified prior build")
    dependencies = prior["selected_dependencies"]
    for name, record in dependencies.items():
        if sha(Path(record["artifact"])) != record["sha256"]:
            raise ValueError(("dependency artifact changed", name))
    inventory = prior["dependency_artifact_sha256"]
    for name, expected in inventory.items():
        if sha(Path(name)) != expected:
            raise ValueError(("transitive dependency artifact changed", name))
    identity = json.loads((HERE/"src/SOURCE_IDENTITY.json").read_text())
    upstream = {}
    for item in identity["files"]:
        data = (args.upstream/item["path"]).read_bytes()
        blob = hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
        if blob != item["git_blob_sha"]:
            raise ValueError(("upstream Git blob changed", item["path"]))
        upstream[item["path"]] = hashlib.sha256(data).hexdigest()
    sources = {p.name: sha(p) for p in sorted((HERE/"src").glob("*.rs"))}
    digest = hashlib.sha256(json.dumps(dict(upstream=upstream, owned=sources), sort_keys=True).encode()).hexdigest()
    env = os.environ.copy()
    env["HEPTA_TASK_NATIVE_SOURCE_DIGEST"] = digest
    compiler = str(args.toolchain/"bin/rustc")
    deps = Path(next(iter(dependencies.values()))["artifact"]).parent
    common = [compiler, "--edition=2024", "--crate-name", "codex_native_event_owner_r9",
              "-C", "debuginfo=0", "-C", "opt-level=2", "-C", "strip=debuginfo",
              "-L", "dependency="+str(deps)]
    for name, record in dependencies.items():
        common += ["--extern", name+"="+record["artifact"]]
    commands = [command([compiler,"--version","--verbose"], args.build, env)]
    if commands[0]["stdout"] != prior["commands"][0]["stdout"]:
        raise ValueError("compiler differs from preserved rlibs")
    binary, tests = args.build/"native-owner-r9", args.build/"native-owner-r9-tests"
    for argv in [common+[str(HERE/"src/main.rs"),"-o",str(binary)],
                 common+["--test",str(HERE/"src/main.rs"),"-o",str(tests)]]:
        if commands[-1]["returncode"]:
            break
        commands.append(command(argv, args.build, env))
    result = dict(schema="hepta.r9.native.cached-build.v1", success=len(commands)==3 and all(not c["returncode"] for c in commands),
                  source_digest=digest, sources=sources, upstream=upstream,
                  selected_dependencies=dependencies, prior_report_sha256=sha(args.prior_report),
                  transitive_dependency_sha256=inventory,
                  binary=str(binary), binary_sha256=sha(binary) if binary.exists() else None,
                  tests=str(tests), tests_sha256=sha(tests) if tests.exists() else None,
                  commands=commands, fresh_cargo_build=False, production_activation=False)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("success","source_digest","binary")}))
    for row in commands:
        if row["returncode"]:
            print(row["stderr"])
    return result["success"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("build","upstream","toolchain","prior-report","report"):
        p.add_argument("--"+name,type=Path,required=True)
    raise SystemExit(0 if main(p.parse_args()) else 1)

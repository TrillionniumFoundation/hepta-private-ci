"""Compile the standalone research port using identified existing Rust artifacts.

No production manifest is changed. This is an explicit cached-artifact rustc
build, not a fresh Cargo build. Sources, artifacts, compiler and commands are
recorded; the actual upstream NeuronRuntime is linked without modification.
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
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, cwd, env):
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    return dict(command=[str(x) for x in command], cwd=str(cwd), returncode=result.returncode,
                stdout=result.stdout, stderr=result.stderr, wall_seconds=time.perf_counter() - started)


def build(args):
    args.output.mkdir(parents=True, exist_ok=False)
    identity = json.loads(args.upstream_identity.read_text())
    upstream = {}
    for item in identity["files"]:
        path = args.upstream / item["path"]
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != item["git_blob_sha"]:
            raise ValueError(("upstream changed", str(path)))
        upstream[item["path"]] = sha(path)
    artifacts = {str(p): sha(p) for p in sorted(args.dependencies.iterdir())
                 if p.is_file() and p.suffix in (".rlib", ".so")}
    selected = {}
    for name in ("serde", "serde_json", "libc", "codex_hepta_types", "codex_hepta_neuron"):
        files = list(args.dependencies.glob("lib" + name + "-*.rlib"))
        if len(files) != 1:
            raise ValueError(("ambiguous cached dependency", name, files))
        selected[name] = str(files[0])
    sources = {p.name: sha(p) for p in sorted(HERE.glob("*.rs"))}
    source_digest = hashlib.sha256(json.dumps(dict(sources=sources, upstream=upstream,
        dependencies=artifacts), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    env = os.environ.copy()
    env["HEPTA_TASK_NATIVE_SOURCE_DIGEST"] = source_digest
    binary, tests = args.output / "r7-native-policy", args.output / "r7-native-policy-tests"
    compiler = args.toolchain / "bin/rustc"
    common = [str(compiler), "--edition=2024", "--crate-name", "codex_r7_native_policy",
              "-C", "opt-level=2", "-C", "debuginfo=0", "-C", "strip=debuginfo",
              "-L", "dependency=" + str(args.dependencies)]
    for name, path in selected.items():
        common += ["--extern", name + "=" + path]
    commands = [run([str(compiler), "--version", "--verbose"], args.output, env)]
    commands += [run(common + [str(HERE / "main.rs"), "-o", str(binary)], args.output, env)]
    if commands[-1]["returncode"] == 0:
        commands += [run(common + ["--test", str(HERE / "main.rs"), "-o", str(tests)], args.output, env)]
    report = dict(schema="hepta.r7-native-build.v1", source_digest=source_digest, sources=sources,
        upstream_commit=identity["commit"], upstream_source_sha256=upstream,
        upstream_identity_sha256=sha(args.upstream_identity), selected_dependencies=selected,
        cached_dependency_sha256=artifacts, commands=commands, fresh_cargo_build=False,
        cached_dependency_source_archives_verified=False,
        cached_dependency_provenance="Pinned pre-existing native-loop Cargo artifacts; sources independently byte-verified against the public original Hepta source identity. Registry archives unavailable; this run does not requalify their source supply chain.",
        binary=str(binary), binary_sha256=sha(binary) if binary.exists() else None,
        tests=str(tests), tests_sha256=sha(tests) if tests.exists() else None,
        success=all(c["returncode"] == 0 for c in commands), production_activation=False)
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(dict(success=report["success"], binary=str(binary), report=str(args.report))))
    for command in commands:
        if command["returncode"]:
            print(command["stderr"])
    return 0 if report["success"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "report", "upstream", "upstream-identity", "dependencies", "toolchain"):
        parser.add_argument("--" + name, type=Path, required=True)
    raise SystemExit(build(parser.parse_args()))

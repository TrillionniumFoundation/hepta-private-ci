"""Run unchanged repository just fmt / just test in an isolated explicit workspace.

The standalone port is outside Cargo/Bazel production manifests. Test metadata
explicitly identifies the rustc-built test binary; this is nextest build reuse,
not a fresh Cargo test build. No tests are replaced by a custom runner.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
WORKFLOW = ("justfile", "scripts/run-nextest.py", "scripts/just-shell.py", "scripts/format.py", "codex-rs/rustfmt.toml")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    for name in WORKFLOW:
        destination = args.output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, destination)
    env = os.environ.copy()
    env["PATH"] = str(args.toolchain / "bin") + os.pathsep + str(args.tools) + os.pathsep + env["PATH"]
    cwd = args.output / "codex-rs"
    metadata = None
    if args.operation == "format":
        subprocess.run(["git", "init", "-q"], cwd=args.output, check=True)
        subprocess.run(["git", "add", "."], cwd=args.output, check=True)
        subprocess.run(["git", "-c", "user.name=Local formatter", "-c", "user.email=formatter@localhost",
                        "commit", "-qm", "Pin unchanged repository formatting workflow"], cwd=args.output, check=True)
        target = cwd / "isolated-native"
        target.mkdir()
        for path in HERE.glob("*.rs"):
            shutil.copyfile(path, target / path.name)
        (target / "rustfmt.toml").write_text('edition = "2024"\nmax_width = 110\n')
        command = ["just", "fmt"]
    else:
        build = json.loads(args.build_report.read_text())
        if not build["success"] or sha(build["tests"]) != build["tests_sha256"]:
            raise ValueError("test binary identity mismatch")
        if any(sha(HERE / name) != expected for name, expected in build["sources"].items()):
            raise ValueError("compiled Rust sources changed")
        name = "codex-r7-native-policy"
        identifier = f"path+file://{cwd}#{name}@0.1.0"
        (cwd / "Cargo.toml").write_text('[package]\nname="' + name + '"\nversion="0.1.0"\nedition="2024"\n[workspace]\n[[bin]]\nname="' + name + '"\npath=' + json.dumps(str(HERE / "main.rs")) + '\n')
        cargo = dict(packages=[dict(name=name, version="0.1.0", id=identifier, license=None, license_file=None,
            description=None, source=None, dependencies=[], targets=[dict(kind=["bin"], crate_types=["bin"], name=name,
            src_path=str(HERE / "main.rs"), edition="2024", doc=True, doctest=False, test=True)], features={},
            manifest_path=str(cwd / "Cargo.toml"), metadata=None, publish=None, authors=[], categories=[], keywords=[],
            readme=None, repository=None, homepage=None, documentation=None, edition="2024", links=None, default_run=None,
            rust_version=None)], workspace_members=[identifier], workspace_default_members=[identifier], resolve=None,
            target_directory=str(args.output), build_directory=str(args.output), version=1, workspace_root=str(cwd), metadata=None)
        binaries = {"rust-build-meta": {"target-directory": str(args.output), "base-output-directories": ["debug"],
            "non-test-binaries": {}, "linked-paths": []}, "rust-binaries": {name: {"binary-id": name, "binary-name": name,
            "package-id": identifier, "kind": "bin", "binary-path": build["tests"], "build-platform": "host"}}}
        (args.output / "cargo-metadata.json").write_text(json.dumps(cargo))
        (args.output / "binaries-metadata.json").write_text(json.dumps(binaries))
        (args.output / "nextest.toml").write_text('[profile.default]\nretries = 0\n[profile.local]\ninherits = "default"\n')
        metadata = dict(cargo=cargo, binaries=binaries)
        command = ["just", "test", "--cargo-metadata", str(args.output / "cargo-metadata.json"),
            "--binaries-metadata", str(args.output / "binaries-metadata.json"), "--config-file",
            str(args.output / "nextest.toml"), "--no-tests", "fail", "-j", "1"]
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if args.operation == "format" and result.returncode == 0:
        for path in target.glob("*.rs"):
            shutil.copyfile(path, HERE / path.name)
    report = dict(command=command, cwd=str(cwd), returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
        workflow_sha256={name: sha(REPO / name) for name in WORKFLOW}, source_sha256={p.name: sha(p) for p in HERE.glob("*.rs")},
        metadata=metadata, reused_direct_rustc_test_binary=args.operation == "test", fresh_cargo_test_build=False)
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("returncode", "stdout", "stderr")}))
    return result.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("format", "test"))
    for name in ("output", "report", "toolchain", "tools"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--build-report", type=Path)
    raise SystemExit(main(parser.parse_args()))

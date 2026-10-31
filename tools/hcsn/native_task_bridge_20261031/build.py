"""Build and qualify the adapter against 60 byte-pinned current-main Rust files.

This is an isolated, generated Cargo harness. It does not change the production
workspace, dependency manifests, native source files, or existing build targets.
The real repository just test recipe remains the test entry point.
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
CRATES = ("hepta-neuron", "hepta-infer-core", "hepta-types")
WORKSPACE = """[workspace]
resolver = "2"
members = ["hepta-neuron", "hepta-infer-core", "hepta-types"]
[workspace.package]
version = "0.0.0"
edition = "2024"
license = "Apache-2.0"
[workspace.dependencies]
serde = { version = "=1.0.229", features = ["rc"] }
serde_json = "=1.0.151"
sha2 = "=0.10.9"
pretty_assertions = "1.4.1"
[workspace.lints]
rust = {}
"""
NEXTEST = """[profile.default]
slow-timeout = { period = "10s", terminate-after = 2 }
retries = 0
[profile.local]
inherits = "default"
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest(build):
    native = build / "upstream" / "codex-rs"
    return f"""[package]
name = "codex-task-native-v2"
version = "0.1.0"
edition = "2024"
[workspace]
members = ["."]
[workspace.package]
version = "0.0.0"
edition = "2024"
license = "Apache-2.0"
[workspace.dependencies]
serde = {{ version = "=1.0.229", features = ["rc"] }}
serde_json = "=1.0.151"
sha2 = "=0.10.9"
pretty_assertions = "1.4.1"
[workspace.lints]
rust = {{}}
[[bin]]
name = "codex-task-native-v2"
path = "main.rs"
[dependencies]
codex-hepta-neuron = {{ path = {json.dumps(str(native / "hepta-neuron"))} }}
codex-hepta-types = {{ path = {json.dumps(str(native / "hepta-types"))} }}
serde = {{ version = "=1.0.229", features = ["derive"] }}
serde_json = "=1.0.151"
libc = "=0.2.186"
[profile.dev]
debug = 0
incremental = false
"""


def execute(command, cwd, environment):
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True)
    return dict(command=command, cwd=str(cwd), returncode=result.returncode,
                stdout=result.stdout, stderr=result.stderr,
                wall_seconds=time.monotonic() - started)


def build(args):
    target = args.build_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    identity = json.loads((HERE / "SOURCE_IDENTITY.json").read_text())
    upstream_sha256 = {}
    for item in identity["files"]:
        data = (args.source_root / item["path"]).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != item["git_blob_sha"]:
            raise ValueError(("pinned native source mismatch", item["path"], actual))
        destination = target / "upstream" / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        upstream_sha256[item["path"]] = sha(data)
    (target / "upstream" / "codex-rs" / "Cargo.toml").write_text(WORKSPACE)
    owned = {}
    for path in sorted(HERE.glob("*.rs")):
        shutil.copy2(path, target / path.name)
        owned[path.name] = sha(path.read_bytes())
    for name in ("build.py", "native-Cargo.lock", "rustfmt.toml"):
        owned[name] = sha((HERE / name).read_bytes())
    source = dict(upstream=identity, upstream_sha256=upstream_sha256, adapter_sha256=owned,
                  derived_upstream_workspace=WORKSPACE)
    source_digest = sha(json.dumps(source, sort_keys=True, separators=(",", ":")).encode())
    (target / "Cargo.toml").write_text(manifest(target))
    (target / "nextest.toml").write_text(NEXTEST)
    shutil.copy2(HERE / "native-Cargo.lock", target / "Cargo.lock")
    cargo_home = target / "cargo-home"
    (cargo_home / "registry").mkdir(parents=True, exist_ok=True)
    for name in ("index", "cache", "src"):
        link = cargo_home / "registry" / name
        if not link.exists():
            link.symlink_to(args.cargo_cache / "registry" / name, target_is_directory=True)
    environment = os.environ.copy()
    environment.update(PATH=str(args.toolchain / "bin") + os.pathsep + str(args.tools) + os.pathsep + environment["PATH"],
                       CARGO_HOME=str(cargo_home), RUSTC=str(args.toolchain / "bin" / "rustc"),
                       CARGO_TARGET_DIR=str(target / "target"), CARGO_INCREMENTAL="0", CARGO_BUILD_JOBS="2",
                       HEPTA_TASK_NATIVE_SOURCE_DIGEST=source_digest)
    commands = [execute(["rustc", "--version", "--verbose"], target, environment),
                execute(["just", "--version"], target, environment)]
    commands.append(execute(["cargo", "build", "--offline", "--locked", "--manifest-path", str(target / "Cargo.toml")], target, environment))
    if all(row["returncode"] == 0 for row in commands):
        commands.append(execute(["just", "test", "--offline", "--locked", "--manifest-path", str(target / "Cargo.toml"),
                                 "--config-file", str(target / "nextest.toml"), "-p", "codex-task-native-v2"],
                                args.workflow_root, environment))
    success = all(row["returncode"] == 0 for row in commands)
    binary = target / "target" / "debug" / "codex-task-native-v2"
    report = dict(schema="hepta.task.native-bridge.build.v2", success=success, source_digest=source_digest,
                  source=source, derived_adapter_manifest=manifest(target), nextest_config=NEXTEST,
                  commands=commands, binary=str(binary), binary_sha256=sha(binary.read_bytes()) if binary.is_file() else None,
                  native_physics_executed=False, production_activation=False, authority="DENY_ALL")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(dict(success=success, binary=str(binary), source_digest=source_digest,
                          report=str(args.report), returncodes=[row["returncode"] for row in commands])))
    if not success:
        for row in commands:
            if row["returncode"]:
                print(row["stdout"] + row["stderr"])
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--workflow-root", type=Path, required=True)
    parser.add_argument("--cargo-cache", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.report.exists():
        raise SystemExit("Refusing to overwrite previous evidence")
    raise SystemExit(0 if build(arguments) else 1)

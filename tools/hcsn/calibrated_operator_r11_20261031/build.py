"""Rebuild the research owner from pinned Hepta sources with offline Cargo.

The generated isolated workspace does not modify production manifests or Bazel
dependencies. Rust tests use the repository's unchanged `just test` recipe.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time
import tomllib

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BRIDGE = REPO / "tools/hcsn/native_task_bridge_20261031"
R9 = REPO / "tools/hcsn/round9_20261031/native/src"
PACKAGE = "codex-calibrated-operator"
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


def sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest(target):
    upstream = target / "upstream/codex-rs"
    return f"""[package]
name = "{PACKAGE}"
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
name = "{PACKAGE}"
path = {json.dumps(str(HERE / "native/main.rs"))}
[dependencies]
codex-hepta-neuron = {{ path = {json.dumps(str(upstream / "hepta-neuron"))} }}
codex-hepta-types = {{ path = {json.dumps(str(upstream / "hepta-types"))} }}
serde = {{ version = "=1.0.229", features = ["derive"] }}
serde_json = {{ version = "=1.0.151", features = ["float_roundtrip"] }}
libc = "=0.2.186"
[dev-dependencies]
pretty_assertions = "1.4.1"
[profile.dev]
debug = 0
incremental = false
opt-level = 2
"""


def execute(argv, cwd, env):
    wall = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(command=argv, cwd=str(cwd), returncode=result.returncode,
                stdout=result.stdout, stderr=result.stderr,
                wall_seconds=time.perf_counter() - wall,
                child_cpu_seconds=after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime)


def prepare(args):
    target = args.build.resolve()
    target.mkdir(parents=True, exist_ok=True)
    identity = json.loads((BRIDGE / "SOURCE_IDENTITY.json").read_text())
    sources = {}
    for item in identity["files"]:
        path = REPO / item["path"]
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != item["git_blob_sha"]:
            raise ValueError(("pinned upstream source mismatch", item["path"], blob))
        dest = target / "upstream" / item["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        sources[item["path"]] = sha(data)
    (target / "upstream/codex-rs/Cargo.toml").write_text(WORKSPACE)
    for path in sorted((HERE / "native").glob("*.rs")):
        sources[str(path.relative_to(REPO))] = sha(path.read_bytes())
    for name in ("cell.rs", "content.rs", "native.rs", "owner.rs", "schedule.rs"):
        sources[str((R9 / name).relative_to(REPO))] = sha((R9 / name).read_bytes())
    sources[str(Path(__file__).resolve().relative_to(REPO))] = sha(Path(__file__).read_bytes())
    for name in ("owner.rs", "store.rs", "task.rs"):
        path = REPO / "tools/hcsn/task_native_loop_20261031/native" / name
        sources[str(path.relative_to(REPO))] = sha(path.read_bytes())
    lock = (BRIDGE / "native-Cargo.lock").read_text().replace('name = "codex-task-native-v2"', f'name = "{PACKAGE}"')
    dependency_sources, patches = {}, []
    for package in tomllib.loads(lock)["package"]:
        if "source" not in package:
            continue
        name, version = package["name"], package["version"]
        stem = name + "-" + version
        archives = list((args.cargo_cache / "registry/cache").glob("*/" + stem + ".crate"))
        if archives:
            if len(archives) != 1 or sha(archives[0].read_bytes()) != package["checksum"]:
                raise ValueError(("cached archive checksum mismatch", name))
            dependency_sources[stem] = dict(archive_checksum_verified=True, archive_sha256=package["checksum"])
            continue
        if not args.cached_source_fallback:
            dependency_sources[stem] = dict(archive_checksum_verified=False, missing_archive=True)
            continue
        matches = list((args.cargo_cache / "registry/src").glob("*/" + stem))
        if len(matches) != 1:
            raise ValueError(("unambiguous cached source required", stem))
        source = matches[0]
        package_identity = tomllib.loads((source / "Cargo.toml").read_text())["package"]
        if (package_identity["name"], package_identity["version"]) != (name, version):
            raise ValueError(("cached source manifest identity mismatch", stem))
        destination = target / "vendor" / stem
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=False)
        inventory = {str(p.relative_to(destination)): sha(p.read_bytes())
                     for p in sorted(destination.rglob("*")) if p.is_file()}
        tree_digest = sha(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode())
        dependency_sources[stem] = dict(archive_checksum_verified=False, expected_archive_sha256=package["checksum"],
            source_snapshot_sha256=tree_digest, source_files=inventory,
            provenance="Previously unpacked local cache; content pinned for this build, archive unavailable")
        sources["cached-dependency/" + stem] = tree_digest
        patches.append(f'{name} = {{ path = "vendor/{stem}" }}')
    generated_manifest = manifest(target)
    if patches:
        generated_manifest += "\n[patch.crates-io]\n" + "\n".join(patches) + "\n"
    source_digest = sha(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode())
    (target / "Cargo.toml").write_text(generated_manifest)
    (target / "Cargo.lock").write_text(lock)
    nextest = "[profile.default]\nslow-timeout = { period = \"20s\", terminate-after = 3 }\nretries = 0\n[profile.local]\ninherits = \"default\"\n"
    (target / "nextest.toml").write_text(nextest)
    registry = target / "cargo-home/registry"
    registry.mkdir(parents=True, exist_ok=True)
    for part in ("src", "cache", "index"):
        link = registry / part
        if not link.exists():
            link.symlink_to(args.cargo_cache.resolve() / "registry" / part, target_is_directory=True)
    env = os.environ.copy()
    env.update(PATH=str(args.toolchain / "bin") + os.pathsep + str(args.tools) + os.pathsep + env["PATH"],
               RUSTC=str(args.toolchain / "bin/rustc"), CARGO_HOME=str(target / "cargo-home"),
               CARGO_TARGET_DIR=str(target / "target"), CARGO_INCREMENTAL="0", CARGO_BUILD_JOBS="2",
               HEPTA_TASK_NATIVE_SOURCE_DIGEST=source_digest)
    return target, identity, sources, source_digest, env, dependency_sources, generated_manifest


def main(args):
    target, identity, sources, digest, env, dependencies, generated_manifest = prepare(args)
    commands = []
    commands.append(execute([str(args.toolchain / "bin/rustc"), "--version", "--verbose"], target, env))
    commands.append(execute(["just", "--version"], REPO / "codex-rs", env))
    commands.append(execute(["cargo", "build", "--offline", "--manifest-path", str(target / "Cargo.toml")], target, env))
    if all(row["returncode"] == 0 for row in commands) and args.tests:
        commands.append(execute(["just", "test", "--offline", "--locked", "--manifest-path", str(target / "Cargo.toml"),
                                 "--config-file", str(target / "nextest.toml"), "-p", PACKAGE], REPO / "codex-rs", env))
    binary = target / "target/debug" / PACKAGE
    report = dict(schema="hcsn.task-native-loop.build.v1", success=all(row["returncode"] == 0 for row in commands),
                  pinned_task_base="e7eaa5e0be835269636216c8fe8b1ae2f1a22361", upstream=identity,
                  source_sha256=sources, source_digest=digest, generated_manifest=generated_manifest,
                  dependency_sources=dependencies,
                  all_dependency_archives_verified=all(d["archive_checksum_verified"] for d in dependencies.values()),
                  generated_lock_sha256=sha((target / "Cargo.lock").read_bytes()),
                  source_only_fresh_cargo_build=True, binary=str(binary),
                  binary_sha256=sha(binary.read_bytes()) if binary.is_file() else None,
                  tests_requested=args.tests, commands=commands, production_activation=False)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(dict(success=report["success"], binary=str(binary), report=str(args.report),
                          returncodes=[row["returncode"] for row in commands])))
    for row in commands:
        if row["returncode"]:
            print(row["stderr"][-12000:])
    return 0 if report["success"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--cargo-cache", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--cached-source-fallback", action="store_true",
                        help="Explicitly patch missing archives to identified local source snapshots; record the provenance limit")
    raise SystemExit(main(parser.parse_args()))

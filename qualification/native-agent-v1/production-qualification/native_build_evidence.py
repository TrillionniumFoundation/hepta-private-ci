"""Bind the qualification executable to current local libraries and one runtime.

This is observed build provenance, not a claim of a hermetic or reproducible
toolchain. Credentials, Cargo credentials files and provider keys are excluded.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

POLICY_VERSION = "hepta-native-context-policy-v3"
PROJECTION_VERSION = "hepta-native-request-projection-v1"
RUNTIME_REPOSITORY = "https://github.com/TrillionniumFoundation/hepta-runtime"
RUNNER = "qualification/native-agent-v1/runner"
GENERATED_PARTS = frozenset({"target", ".git", "__pycache__", ".pytest_cache"})


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], timeout=60)


def file_state(path):
    path = Path(path)
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(path),
                "target_sha256": digest(path) if path.is_file() else None}
    if not path.exists():
        return {"kind": "absent"}
    if not path.is_file():
        raise ValueError("source fingerprint is not a regular file: " + str(path))
    return {"kind": "file", "bytes": path.stat().st_size, "sha256": digest(path)}


def package_files(root):
    """All files, including untracked source, except common generated trees."""
    root = Path(root)
    result = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        parent = Path(parent)
        dirs[:] = sorted(d for d in dirs if d not in GENERATED_PARTS)
        for directory in list(dirs):
            path = parent / directory
            if path.is_symlink():
                raise ValueError("source directory symlink has no bound content: " + str(path))
        for name in sorted(files):
            if name in GENERATED_PARTS:
                continue
            path = parent / name
            result[str(path.relative_to(root))] = file_state(path)
    return result


def metadata_contract(metadata, source, runtime_revision, runtime_source=None):
    source = Path(source).resolve()
    runtime_source = Path(runtime_source).resolve() if runtime_source else None
    if not re.fullmatch(r"[0-9a-f]{40}", runtime_revision):
        raise ValueError("runtime must identify an exact base commit, not a branch")
    graphs = metadata.get("graphs", {})
    if set(graphs) != {"runner", "owner"}:
        raise ValueError("actual runner and owner resolved dependency graphs are required")
    runtime_packages = {}
    local = []
    identities = []
    for label, graph in graphs.items():
        packages = graph.get("packages", [])
        native = [p for p in packages if p.get("name") == "codex-hepta-native-agent"]
        if (len(native) != 1 or native[0].get("source") is not None
                or Path(native[0]["manifest_path"]).resolve() != source / "codex-rs/hepta-native-agent/Cargo.toml"):
            raise ValueError(label + " must resolve the current native-agent path exactly once")
        runtime = [p for p in packages if p.get("name") == "hepta-runtime"]
        if len(runtime) != 1:
            raise ValueError(label + " has duplicate or missing hepta-runtime packages")
        actual = runtime[0]
        actual_path = Path(actual["manifest_path"]).resolve()
        if runtime_source:
            if actual.get("source") is not None or actual_path != runtime_source / "Cargo.toml":
                raise ValueError(label + " did not resolve the declared runtime path patch")
        else:
            origin = actual.get("source") or ""
            repository = origin.split("?", 1)[0].split("#", 1)[0].removeprefix("git+").removesuffix(".git")
            if repository != RUNTIME_REPOSITORY or origin.rsplit("#", 1)[-1] != runtime_revision:
                raise ValueError(label + " runtime is not the pinned repository commit")
        identities.append((actual["name"], actual["version"], actual.get("source"), str(actual_path)))
        for package in packages:
            origin = package.get("source") or ""
            repository = origin.split("?", 1)[0].split("#", 1)[0].removeprefix("git+").removesuffix(".git")
            manifest = Path(package["manifest_path"]).resolve()
            in_runtime = runtime_source is not None and manifest.is_relative_to(runtime_source)
            if repository == RUNTIME_REPOSITORY or in_runtime:
                if runtime_source and (package.get("source") is not None or not in_runtime):
                    raise ValueError("a runtime crate bypassed the single patched runtime tree")
                if not runtime_source and origin.rsplit("#", 1)[-1] != runtime_revision:
                    raise ValueError("runtime graph contains another git revision: " + origin)
                runtime_packages[package["id"]] = package
            elif label == "runner" and package.get("source") is None:
                if not manifest.is_relative_to(source):
                    raise ValueError("unbound external path dependency: " + package["name"])
                local.append(package)
    if identities[0] != identities[1]:
        raise ValueError("owner and qualification runner resolve different runtime packages")
    return local, list(runtime_packages.values())


def repository_state(source):
    names = set()
    for command in (("diff", "--name-only", "-z", "HEAD", "--"),
                    ("ls-files", "--others", "--exclude-standard", "-z")):
        names.update(name for name in git(source, *command).decode().split("\0")
            if name and not (set(Path(name).parts) & GENERATED_PARTS))
    return {"root": str(source), "base_commit": git(source, "rev-parse", "HEAD").decode().strip(),
        "tracked_diff_sha256": hashlib.sha256(git(source, "diff", "--binary", "HEAD", "--")).hexdigest(),
        "dirty_files": {name: file_state(source / name) for name in sorted(names)}}


def patch_configuration(path, runtime_source):
    if not path:
        if runtime_source:
            raise ValueError("a runtime path variant requires its explicit Cargo patch configuration")
        return None
    path = Path(path).resolve()
    parsed = tomllib.loads(path.read_text())
    if set(parsed) != {"patch"} or not runtime_source:
        raise ValueError("only an explicit runtime [patch] configuration is supported")
    if not parsed["patch"]:
        raise ValueError("runtime patch configuration is empty")
    for repository, replacements in parsed["patch"].items():
        if repository.removesuffix(".git") != RUNTIME_REPOSITORY:
            raise ValueError("configuration patches an unrelated repository")
        for package, replacement in replacements.items():
            if set(replacement) != {"path"} or not Path(replacement["path"]).is_absolute():
                raise ValueError("runtime patch must have only an absolute source path")
            if not Path(replacement["path"]).resolve().is_relative_to(Path(runtime_source).resolve()):
                raise ValueError("runtime patch escaped the declared runtime worktree")
    return {"path": str(path), "sha256": digest(path), "configuration": parsed}


def source_snapshot(source, metadata, runtime_revision, runtime_source=None, cargo_config=None):
    source = Path(source).resolve()
    if Path(git(source, "rev-parse", "--show-toplevel").decode().strip()).resolve() != source:
        raise ValueError("source must identify the owner's git worktree root")
    local, runtime = metadata_contract(metadata, source, runtime_revision, runtime_source)
    patch = patch_configuration(cargo_config, runtime_source)
    runtime_repository = None
    if runtime_source:
        runtime_source = Path(runtime_source).resolve()
        if Path(git(runtime_source, "rev-parse", "--show-toplevel").decode().strip()).resolve() != runtime_source:
            raise ValueError("runtime source must identify its git worktree root")
        runtime_repository = repository_state(runtime_source)
        if runtime_repository["base_commit"] != runtime_revision:
            raise ValueError("runtime path HEAD changed from the supplied original base commit")
    policy = (source / "codex-rs/hepta-native-agent/src/context_policy.rs").read_text()
    projection = (source / "codex-rs/hepta-native-agent/src/context_projection.rs").read_text()
    if (f'pub const CONTEXT_POLICY_VERSION: &str = "{POLICY_VERSION}";' not in policy
            or f'pub const CONTEXT_PROJECTION_VERSION: &str = "{PROJECTION_VERSION}";' not in projection
            or not (source / "codex-rs/hepta-native-agent/src/events.rs").is_file()):
        raise ValueError("source lacks the current native streaming/context policy implementation")
    packages = []
    for package in sorted(local + runtime, key=lambda p: p["id"]):
        root = Path(package["manifest_path"]).resolve().parent
        if package in runtime and not runtime_source:
            actual = git(root, "rev-parse", "HEAD").decode().strip()
            if actual != runtime_revision or git(root, "diff", "--name-only", "HEAD", "--").strip():
                raise ValueError("runtime Cargo checkout is modified or has another commit")
        packages.append({"id": package["id"], "name": package["name"], "source": package.get("source"),
            "manifest_path": str(root / "Cargo.toml"), "files": package_files(root)})
    repository = repository_state(source)
    controls = {name: file_state(source / name) for name in (
        "Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config", ".cargo/config.toml",
        "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
        "codex-rs/hepta-agentd/Cargo.toml", "codex-rs/execution-core/Cargo.toml",
        "codex-rs/.cargo/config", "codex-rs/.cargo/config.toml", RUNNER + "/Cargo.lock")}
    return {"schema": "hepta.native-source-snapshot.v1", "source": str(source),
        "source_commit": repository["base_commit"], "source_repository": repository,
        "runtime_repository": runtime_repository, "cargo_patch": patch,
        "control_files": controls, "packages": packages,
        "runtime_revision": runtime_revision, "context_policy_version": POLICY_VERSION,
        "request_projection_version": PROJECTION_VERSION,
        "coverage": "All local path package files, runtime git package files, workspace control files and all git-dirty paths; generated target/.git/Python caches excluded. This is not a hermetic build proof."}


def verify_native_build(path, executable):
    path, executable = Path(path).resolve(), Path(executable).resolve()
    record = json.loads(path.read_bytes())
    if (record.get("schema") != "hepta.native-build.v1" or record.get("build_succeeded") is not True
            or record.get("context_policy_version") != POLICY_VERSION
            or record.get("request_projection_version") != PROJECTION_VERSION):
        raise ValueError("comparison requires current native-agent build evidence")
    binary = record.get("binary", {})
    if binary.get("sha256") != digest(executable) or binary.get("bytes") != executable.stat().st_size:
        raise ValueError("native executable differs from the observed current-source build")
    for name, expected in record.get("evidence_files", {}).items():
        if Path(name).name != name or digest(path.parent / name) != expected:
            raise ValueError("native build evidence changed: " + name)
    required = {"source-before.json", "source-after.json", "cargo-metadata.json", "native-build.log",
        "runner-cargo-metadata.json", "owner-cargo-metadata.json", "runner-metadata.log", "owner-metadata.log"}
    if record.get("runtime_source"):
        required.add("runtime-patch.toml")
    if not required.issubset(record.get("evidence_files", {})):
        raise ValueError("native source, dependency graph or actual build log is missing")
    before = json.loads((path.parent / "source-before.json").read_bytes())
    after = json.loads((path.parent / "source-after.json").read_bytes())
    metadata = json.loads((path.parent / "cargo-metadata.json").read_bytes())
    if set(record.get("metadata_commands", {})) != {"runner", "owner"}:
        raise ValueError("original runner/owner metadata commands are missing")
    for label in ("runner", "owner"):
        command = record["metadata_commands"][label]
        if command.get("exit_code") != 0 or "--locked" not in command.get("argv", []):
            raise ValueError("resolved graph did not come from a successful locked metadata command")
        if metadata.get("graphs", {}).get(label) != json.loads((path.parent / (label + "-cargo-metadata.json")).read_bytes()):
            raise ValueError("combined runtime graph differs from its original metadata output")
    if before != after or object_digest(before) != record.get("source_tree_sha256"):
        raise ValueError("native source changed while it was built")
    if source_snapshot(record["source"], metadata, record["runtime_revision"],
            record.get("runtime_source"), record.get("cargo_config")) != before:
        raise ValueError("native build source or runtime checkout changed since the build")
    command = record.get("command", {})
    if command.get("exit_code") != 0 or "--locked" not in command.get("argv", []):
        raise ValueError("missing successful locked native Cargo build")
    identity = json.loads(subprocess.check_output([str(executable), "--build-identity"], timeout=15))
    expected = {"schema": "hepta.native-qualification-build-identity.v1",
        "context_policy_version": POLICY_VERSION, "request_projection_version": PROJECTION_VERSION,
        "source_tree_sha256": record["source_tree_sha256"], "runtime_revision": record["runtime_revision"]}
    if identity != expected or record.get("binary_identity") != identity:
        raise ValueError("native executable lacks the current compiled source/runtime identity")
    return record

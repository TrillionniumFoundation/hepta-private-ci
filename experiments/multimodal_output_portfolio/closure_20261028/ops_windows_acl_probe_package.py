"""Package the unchanged Windows crate and its reviewed local dependency closure."""

import copy
import hashlib
import json
from pathlib import Path
import posixpath
import re
import tomllib


PACKAGE_DIRS = {
    "codex-api": "codex-api",
    "codex-async-utils": "async-utils",
    "codex-client": "codex-client",
    "codex-execpolicy": "execpolicy",
    "codex-extension-items": "ext/items",
    "codex-http-client": "http-client",
    "codex-network-proxy": "network-proxy",
    "codex-otel": "otel",
    "codex-protocol": "protocol",
    "codex-utils-absolute-path": "utils/absolute-path",
    "codex-utils-cache": "utils/cache",
    "codex-utils-cargo-bin": "utils/cargo-bin",
    "codex-utils-home-dir": "utils/home-dir",
    "codex-utils-image": "utils/image",
    "codex-utils-path-uri": "utils/path-uri",
    "codex-utils-pty": "utils/pty",
    "codex-utils-redacted-string": "utils/redacted-string",
    "codex-utils-rustls-provider": "utils/rustls-provider",
    "codex-utils-stable-hash": "utils/stable-hash",
    "codex-utils-string": "utils/string",
    "codex-utils-time": "utils/time",
    "codex-utils-windows-private-state": "utils/windows-private-state",
    "codex-websocket-client": "websocket-client",
    "codex-windows-sandbox": "windows-sandbox-rs",
    "pagable": "third_party/pagable-0.4.2-postcard-std",
    "paste": "third_party/paste-compat",
    "rama-crypto": "third_party/rama-crypto-0.3.0-time-backport",
    "starlark": "third_party/starlark-0.14.2-blake3-backport",
    "starlark_map": "third_party/starlark_map-0.14.2-stable-hash",
    "starlark_syntax": "third_party/starlark_syntax-0.14.2-maintained",
}
PACKAGE_ROOTS = tuple(f"codex-rs/{path}" for path in PACKAGE_DIRS.values())
BINARY_NAME = "hepta-windows-acl-native-probe"

LOCK_PROFILE_INPUT_SHA256 = "1538088f5066f174840141b149ff4dc0695a76f921e20bc2f6f474a5bcfdd5dc"
LOCK_PROFILE_RECORDS_SHA256 = "391456911a8e2712e61b46f6d3185e2c459afe936f5656c6c83d7f68f9c4ce14"
LOCK_PROFILE_OUTPUT_SHA256 = "c8b24275137bcc059625d8925b7f25102990802dbc566a635dd62e2d350c5736"
# Only Cargo-observed optional edges absent from this exact isolated workspace.
REMOVED_FEATURE_EDGES = {
    "ahash 0.8.12": ["serde"],
    "arrayvec 0.7.8": ["serde", "zeroize"],
    "bitflags 2.13.2": ["serde_core"],
    "block-buffer 0.12.1": ["zeroize"],
    "borsh 1.8.1": ["borsh-derive"],
    "bstr 1.13.1": ["regex-automata"],
    "chacha20 0.10.2": ["cipher 0.5.2", "zeroize"],
    "crypto-common 0.1.7": ["rand_core 0.6.4"],
    "crypto-common 0.2.2": ["getrandom 0.4.3", "rand_core 0.10.1"],
    "ctutils 0.4.8": ["subtle"],
    "digest 0.10.7": ["subtle"],
    "digest 0.11.3": ["zeroize"],
    "either 1.19.0": ["serde"],
    "env_logger 0.11.11": ["anstream", "anstyle"],
    "generic-array 0.14.7": ["zeroize"],
    "hashbrown 0.17.1": ["allocator-api2", "equivalent"],
    "hybrid-array 0.4.15": ["ctutils", "subtle", "zeroize"],
    "image 0.25.10": ["tiff"],
    "libredox 0.1.25": ["bitflags 2.13.2", "plain", "redox_syscall 0.9.5"],
    "mio 1.2.4": ["log"],
    "nix 0.31.3": ["memoffset"],
    "openssl-sys 0.9.117": ["openssl-src"],
    "proptest 1.12.0": ["bit-set 0.11.1", "bit-vec 0.10.1", "rusty-fork", "tempfile"],
    "reqwest 0.13.5": ["serde", "serde_json", "tokio-util", "wasm-streams 0.5.0"],
    "schemars 1.2.3": ["schemars_derive 1.2.3"],
    "semver 1.0.28": ["serde", "serde_core"],
    "serde_json 1.0.154": ["foldhash 0.2.0", "indexmap 2.14.2"],
    "strum 0.27.2": ["strum_macros 0.27.2"],
    "time 0.3.55": ["js-sys", "libc", "num_threads"],
    "tokio 1.53.3": ["tracing"],
    "tokio-util 0.7.20": ["futures-io", "futures-util", "slab"],
    "tonic 0.14.6": ["axum", "h2", "socket2"],
    "tower-http 0.6.11": ["async-compression", "futures-core", "http-body-util", "tokio", "tokio-util"],
    "tracing 0.1.44": ["log"],
    "tracing-subscriber 0.3.23": ["serde", "serde_json", "tracing-serde"],
    "uuid 1.28.0": ["atomic 0.6.1", "sha1_smol"],
    "web-time 1.1.0": ["serde"],
    "zeroize 1.9.1": ["serde", "zeroize_derive"],
}


def source_entries(root, git, controls):
    entries = {}
    controls = set(controls)
    for row in git(root, "ls-tree", "-rz", "HEAD", "--", *PACKAGE_ROOTS, *sorted(controls)).split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, blob = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if (kind != "blob" or mode not in ("100644", "100755") or path in entries
                or (path in controls and mode != "100644")
                or not re.fullmatch(r"[0-9a-f]{40}", blob)
                or Path(path).is_absolute() or ".." in Path(path).parts):
            raise ValueError(f"unexpected committed source kind/mode/path: {path}")
        entries[path] = (mode, blob)
    required = set(controls) | {f"{path}/Cargo.toml" for path in PACKAGE_ROOTS}
    if not required.issubset(entries):
        raise ValueError(f"missing source inventory: {sorted(required - set(entries))}")
    return dict(sorted(entries.items()))


def dependency_closure(lock_bytes):
    lock = tomllib.loads(lock_bytes.decode())
    if lock.get("version") != 4:
        raise ValueError("unexpected production lock version")
    packages = lock["package"]

    def resolve(dependency):
        match = re.fullmatch(r"([^ ]+)(?: ([^ ]+))?(?: \((.+)\))?", dependency)
        if match is None:
            raise ValueError(f"invalid locked dependency: {dependency}")
        name, version, source = match.groups()
        found = [p for p in packages if p["name"] == name
                 and (version is None or p["version"] == version)
                 and (source is None or p.get("source") == source)]
        if len(found) != 1:
            raise ValueError(f"ambiguous locked dependency: {dependency}")
        return found[0]

    pending, selected = [resolve("codex-windows-sandbox")], {}
    while pending:
        package = pending.pop()
        key = (package["name"], package["version"], package.get("source", ""))
        if key in selected:
            continue
        source = package.get("source")
        if source == "registry+https://github.com/rust-lang/crates.io-index":
            if not re.fullmatch(r"[0-9a-f]{64}", package.get("checksum", "")):
                raise ValueError(f"missing registry checksum: {key}")
        elif source is None:
            if package["name"] not in PACKAGE_DIRS:
                raise ValueError(f"unreviewed local package: {key}")
        elif not re.fullmatch(r"git\+https://[^?#]+\?rev=([0-9a-f]{40})#\1", source):
            raise ValueError(f"Git dependency is not pinned to its exact requested revision: {key}")
        selected[key] = package
        pending.extend(resolve(dependency) for dependency in package.get("dependencies", []))
    local = {p["name"] for p in selected.values() if "source" not in p}
    if local != set(PACKAGE_DIRS):
        raise ValueError("reviewed local package inventory differs from the locked closure")
    return [selected[key] for key in sorted(selected)]


def toml_value(value):
    if isinstance(value, (str, bool, int)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    raise ValueError(f"unsupported generated TOML value: {type(value).__name__}")


def toml_document(document):
    lines = []

    def table(path, values):
        if path:
            lines.extend(("[" + ".".join(json.dumps(part) for part in path) + "]",))
        for key, value in values.items():
            if not isinstance(value, dict):
                lines.append(f"{json.dumps(key)} = {toml_value(value)}")
        lines.append("")
        for key, value in values.items():
            if isinstance(value, dict):
                table((*path, key), value)

    table((), document)
    encoded = ("\n".join(lines) + "\n").encode()
    if tomllib.loads(encoded.decode()) != document:
        raise ValueError("generated workspace manifest changed TOML meaning")
    return encoded


def workspace_manifest(blobs, packages):
    document = tomllib.loads(blobs["codex-rs/Cargo.toml"].decode())
    workspace = document["workspace"]
    locals_by_name = {p["name"]: p for p in packages if "source" not in p}
    for name, path in PACKAGE_DIRS.items():
        package = tomllib.loads(blobs[f"codex-rs/{path}/Cargo.toml"].decode())
        version = package["package"]["version"]
        if version == {"workspace": True}:
            version = workspace["package"]["version"]
        if package["package"]["name"] != name or version != locals_by_name[name]["version"]:
            raise ValueError(f"local package identity differs from production lock: {path}")
        groups = [package, *package.get("target", {}).values()]
        for group in groups:
            for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
                for alias, spec in group.get(kind, {}).items():
                    if not isinstance(spec, dict):
                        continue
                    inherited = spec.get("workspace", False)
                    resolved = workspace["dependencies"][alias] if inherited else spec
                    if not isinstance(resolved, dict) or "path" not in resolved:
                        continue
                    base = "" if inherited else path
                    destination = posixpath.normpath(posixpath.join(base, resolved["path"]))
                    dependency_name = resolved.get("package", alias)
                    if PACKAGE_DIRS.get(dependency_name) != destination:
                        raise ValueError(f"local path dependency escapes reviewed closure: {path}: {alias}")
    document = copy.deepcopy(document)
    document["workspace"]["members"] = sorted(path for path in PACKAGE_DIRS.values() if not path.startswith("third_party/"))
    document["workspace"]["exclude"] = sorted(path for path in PACKAGE_DIRS.values() if path.startswith("third_party/"))
    selected = {p["name"] for p in packages}
    document["patch"] = {
        registry: {name: spec for name, spec in patches.items() if spec.get("package", name) in selected}
        for registry, patches in document.get("patch", {}).items()
    }
    for patches in document["patch"].values():
        for alias, spec in patches.items():
            if "path" in spec and PACKAGE_DIRS.get(spec.get("package", alias)) != spec["path"]:
                raise ValueError(f"patch path escapes reviewed closure: {alias}")
    return toml_document(document)


def isolated_lock(packages, blobs):
    # Cargo 1.96 resolved this exact manifest set in an independent diagnostic
    # copy. The large production workspace enabled additional optional edges;
    # they cannot be retained in the smaller workspace's --locked graph.
    input_paths = ("codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
                   "codex-rs/.cargo/config.toml", "codex-rs/rust-toolchain.toml",
                   *(f"codex-rs/{path}/Cargo.toml" for path in PACKAGE_DIRS.values()))
    inputs = {path: hashlib.sha256(blobs[path]).hexdigest() for path in input_paths}
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if fingerprint != LOCK_PROFILE_INPUT_SHA256:
        raise ValueError("unreviewed isolated lock profile inputs")
    record_fingerprint = hashlib.sha256(
        json.dumps(packages, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if record_fingerprint != LOCK_PROFILE_RECORDS_SHA256:
        raise ValueError("production lock records differ from the reviewed profile")

    def key(package):
        return (package["name"], package["version"], package.get("source", ""))

    original = {key(package): package for package in packages}
    # Preserve Cargo's existing semantic-version order, rather than comparing
    # version strings lexically (for example 0.9 must precede 0.10).
    production_order = {key(package): index for index, package in enumerate(
        tomllib.loads(blobs["codex-rs/Cargo.lock"].decode())["package"])}

    def resolve(dependency):
        match = re.fullmatch(r"([^ ]+)(?: ([^ ]+))?(?: \((.+)\))?", dependency)
        if match is None:
            raise ValueError(f"invalid production dependency: {dependency}")
        name, version, source = match.groups()
        found = [identity for identity in original if identity[0] == name
                 and (version is None or identity[1] == version)
                 and (source is None or identity[2] == source)]
        if len(found) != 1:
            raise ValueError(f"ambiguous production dependency: {dependency}")
        return found[0]

    edges = {identity: [resolve(dependency) for dependency in package.get("dependencies", [])]
             for identity, package in original.items()}
    for parent, removed in REMOVED_FEATURE_EDGES.items():
        name, version = parent.split(" ", 1)
        identity = (name, version, "registry+https://github.com/rust-lang/crates.io-index")
        if not set(removed).issubset(original[identity].get("dependencies", [])):
            raise ValueError(f"reviewed optional edge changed: {parent}")
        targets = {resolve(dependency) for dependency in removed}
        edges[identity] = [target for target in edges[identity] if target not in targets]

    pending = [identity for identity in original if not identity[2]]
    selected = set()
    while pending:
        identity = pending.pop()
        if identity not in selected:
            selected.add(identity)
            pending.extend(edges[identity])
    if len(selected) != 677 or len(original) - len(selected) != 34:
        raise ValueError("isolated dependency projection differs from Cargo's reviewed graph")

    def label(identity):
        name, version, source = identity
        same_name = [other for other in selected if other[0] == name]
        if len(same_name) == 1:
            return name
        if sum(other[1] == version for other in same_name) == 1:
            return f"{name} {version}"
        return f"{name} {version} ({source})"

    projected = []
    lines = ["# This file is automatically @generated by Cargo.",
             "# It is not intended for manual editing.", "version = 4", ""]
    for identity in sorted(selected, key=production_order.__getitem__):
        package = original[identity]
        if set(package) - {"name", "version", "source", "checksum", "dependencies"}:
            raise ValueError("unexpected production lock package fields")
        projected_package = {field: package[field] for field in ("name", "version", "source", "checksum")
                             if field in package}
        lines.append("[[package]]")
        for field, value in projected_package.items():
            lines.append(f"{field} = {toml_value(value)}")
        dependencies = [label(target) for target in sorted(edges[identity], key=production_order.__getitem__)]
        if dependencies:
            projected_package["dependencies"] = dependencies
            lines.append("dependencies = [")
            lines.extend(f" {toml_value(dependency)}," for dependency in dependencies)
            lines.append("]")
        lines.append("")
        projected.append(projected_package)
    encoded = "\n".join(lines).encode()
    if tomllib.loads(encoded.decode()) != {"version": 4, "package": projected}:
        raise ValueError("serialized isolated lock changed its projected graph")
    if hashlib.sha256(encoded).hexdigest() != LOCK_PROFILE_OUTPUT_SHA256:
        raise ValueError("isolated lock differs from Cargo's reviewed standard output")
    return encoded

def prepare(crate, blobs, relative):
    packages = dependency_closure(blobs["codex-rs/Cargo.lock"])
    manifest = workspace_manifest(blobs, packages)
    locked = isolated_lock(packages, blobs)
    copies = {path.removeprefix("codex-rs/"): data for path, data in blobs.items()
              if any(path.startswith(prefix + "/") for prefix in PACKAGE_ROOTS)}
    windows = "windows-sandbox-rs/"
    binary = windows + "src/isolated_acl_probe_main.rs"
    observer = windows + "src/isolated_acl_probe/observer.rs"
    support = windows + "src/isolated_acl_probe/support.rs"
    if any(path in copies for path in (binary, observer, support)):
        raise ValueError("generated probe paths collide with production sources")
    probe = blobs[(relative / "ops_windows_acl_probe.rs").as_posix()]
    declarations = (b"mod acl;\nmod elevated_admission;\nmod legacy_admission;\n"
                    b"mod support;\nmod token;\nmod winutil;\n")
    imports = (b"use crate::acl;\nuse crate::legacy_admission;\nuse crate::token;\n"
               b"use crate::winutil;\n#[path = \"support.rs\"]\nmod support;\n")
    if probe.count(declarations) != 1:
        raise ValueError("probe module declarations differ from the reviewed binding")
    copies[observer] = probe.replace(declarations, imports, 1) + (
        b"\npub(super) fn run() -> anyhow::Result<()> { main() }\n")
    copies[support] = blobs[(relative / "ops_windows_acl_probe_support.rs").as_posix()]
    copies[binary] = copies[windows + "src/lib.rs"] + (
        b"\n#[path = \"isolated_acl_probe/observer.rs\"]\nmod isolated_acl_probe_observer;\n"
        b"fn main() -> anyhow::Result<()> { isolated_acl_probe_observer::run() }\n")
    copies[windows + "Cargo.toml"] += (
        f'\n[[bin]]\nname = "{BINARY_NAME}"\npath = "src/isolated_acl_probe_main.rs"\n'.encode())
    copies.update({"Cargo.toml": manifest, "Cargo.lock": locked,
                   ".cargo/config.toml": blobs["codex-rs/.cargo/config.toml"],
                   "rust-toolchain.toml": blobs["codex-rs/rust-toolchain.toml"]})
    if any(Path(path).is_absolute() or ".." in Path(path).parts for path in copies):
        raise ValueError("copied source path escapes the isolated package")
    crate.mkdir(parents=True, exist_ok=False)
    for path, content in copies.items():
        destination = crate / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return manifest, locked, copies

#!/usr/bin/env python3
"""Compare complete original parser files with actual feature-selected HIA calls.

The only reference-source transformation removes paired HIA_NATIVE additions.
Both entire original files must match immutable byte length, SHA256 and Git blob.
Actual PathUri dependencies are built from the current repository in an isolated,
locked small project. No unrelated cached rlib or path/grammar stub is accepted.
"""

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib

import parser_cases


ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "codex-rs/apply-patch/src"
HERE = Path(__file__).resolve().parent
PINS = {
    "parser.rs": (22638, "6b8086467d0500f4fc9aa9a35cd33a0bce53c01bcb74b915b9efc6fcf187f7ce", "c400d075a684fda29c10269aef1958a27faf90aa"),
    "streaming_parser.rs": (34979, "5f4b8e60fd24ada7c1b6a696155de3da2b946f7b5436da90e377c9de04b1e578", "ff1b2f82feec7bdf454f6cba61ad5f15611f5573"),
}
ARGS_SHA = "749d513f1e23fc67fd862dfd577c182a845ec682ea69e83268bd4893072d6b94"
LOCK_SHA = "0617730b9259af552e2028a3716fb8a1a53f9e757c164b3015cccc5ab7ea142a"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def run(command, report, *, env=None, cwd=None, timeout=600, echo=False):
    start = time.monotonic()
    result = subprocess.run(list(map(str, command)), text=True, capture_output=True, env=env, cwd=cwd, timeout=timeout)
    report.setdefault("commands", []).append({
        "command": list(map(str, command)), "returncode": result.returncode,
        "elapsed_seconds": round(time.monotonic() - start, 6),
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stdout_bytes": len(result.stdout.encode()), "stderr_tail": result.stderr[-4000:],
    })
    if echo and result.stdout:
        print(result.stdout, end="", flush=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {command[0]}\n{result.stderr[-8000:]}\n{result.stdout[-4000:]}")
    return result.stdout


def original_rust_source(name, source):
    output, active, seen = [], None, set()
    for line in source.splitlines(keepends=True):
        begin = re.fullmatch(rb"[ \t]*// BEGIN HIA_NATIVE ([A-Za-z0-9_]+)\n", line)
        end = re.fullmatch(rb"[ \t]*// END HIA_NATIVE ([A-Za-z0-9_]+)\n", line)
        if begin:
            identifier = begin.group(1)
            if active is not None or identifier in seen:
                raise RuntimeError(f"nested/duplicate HIA source marker in {name}")
            active = identifier
            seen.add(identifier)
        elif end:
            if active != end.group(1):
                raise RuntimeError(f"unmatched HIA source marker in {name}")
            active = None
        elif b"// BEGIN HIA_NATIVE" in line or b"// END HIA_NATIVE" in line:
            raise RuntimeError(f"malformed HIA source marker in {name}")
        elif active is None:
            output.append(line)
    if active is not None or not seen:
        raise RuntimeError(f"missing/unfinished native routing markers in {name}")
    original = b"".join(output)
    actual = (len(original), hashlib.sha256(original).hexdigest(), hashlib.sha1(b"blob " + str(len(original)).encode() + b"\0" + original).hexdigest())
    if actual != PINS[name]:
        raise RuntimeError(f"complete original {name} changed: {actual!r}")
    return original, sorted(x.decode() for x in seen)


HOST_NAMES = {"codex_utils_path_uri", "codex_utils_absolute_path", "thiserror", "serde_json", "pretty_assertions", "tempfile"}
HOST_RECEIPT_SCHEMA = "codex.hia.parser-host-dependencies.v2"


def host_source_hashes():
    paths = [ROOT / "codex-rs/Cargo.toml"]
    for name in ["absolute-path", "path-uri"]:
        directory = ROOT / "codex-rs/utils" / name
        paths += [directory / "Cargo.toml", *sorted((directory / "src").rglob("*.rs"))]
    return {str(path.relative_to(ROOT)): sha256(path) for path in paths}


def host_receipt_provenance(receipt, receipt_path):
    """Resolve the preserved real original build or a fresh-build v2 bundle."""
    if receipt.get("schema") == HOST_RECEIPT_SCHEMA:
        return receipt["provenance"]
    if receipt.get("schema") != "codex.hia.parser-host-dependencies.v1":
        raise RuntimeError("unrecognized host dependency receipt schema")
    directory = Path(receipt_path).parent
    evidence_path = directory / "evidence.json"
    if sha256(evidence_path) != receipt["build_evidence_sha256"]:
        raise RuntimeError("original host build evidence hash differs")
    evidence = json.loads(evidence_path.read_text())
    names = {"manifest": "Cargo.toml", "lock": "Cargo.lock", "graph": "dependency-graph.json", "artifacts": "build-final-artifacts.jsonl"}
    provenance = {key: {"path": str(directory / name), "sha256": evidence["files"][name]} for key, name in names.items()}
    provenance["evidence"] = {"path": str(evidence_path), "sha256": receipt["build_evidence_sha256"]}
    return provenance


def verify_host_manifest(path):
    manifest = tomllib.loads(Path(path).read_text())
    allowed = {"package", "workspace", "lib", "bin", "dependencies", "dev-dependencies"}
    package = {"name": "codex-parser-original-oracle", "version": "0.0.0", "edition": "2024", "publish": False}
    if set(manifest) - allowed or manifest.get("package") != package or manifest.get("workspace") != {}:
        raise RuntimeError("host manifest package/features/profile declarations differ")
    expected = {
        "dependencies": {"codex-utils-path-uri": {"path": str(ROOT / "codex-rs/utils/path-uri")}, "serde_json": "1", "thiserror": "2.0.17"},
        "dev-dependencies": {"codex-utils-absolute-path": {"path": str(ROOT / "codex-rs/utils/absolute-path")}, "pretty_assertions": "1.4.1", "tempfile": "3.23.0"},
    }
    for section, requirements in expected.items():
        actual = dict(manifest.get(section, {}))
        for name in ["codex-utils-path-uri", "codex-utils-absolute-path"]:
            if name in actual:
                value = actual[name]
                if not isinstance(value, dict) or set(value) != {"path"}:
                    raise RuntimeError("host manifest path dependency features/default-features differ")
                actual[name] = {"path": str((Path(path).parent / value["path"]).resolve())}
        if actual != requirements:
            raise RuntimeError("host manifest dependency versions/features/default-features differ")


def verified_host_receipt(rustc, receipt_path):
    receipt_path = Path(receipt_path).resolve(strict=True)
    receipt = json.loads(receipt_path.read_text())
    if receipt["lock_sha256"] != LOCK_SHA or sha256(HERE / "parser_oracle_Cargo.lock") != LOCK_SHA:
        raise RuntimeError("host dependency lock differs")
    if receipt["rustc_sha256"] != sha256(rustc):
        raise RuntimeError("cached host dependencies used a different Rust compiler")
    provenance = host_receipt_provenance(receipt, receipt_path)
    if set(provenance) != {"manifest", "lock", "graph", "artifacts", "evidence"}:
        raise RuntimeError("host provenance inventory differs")
    paths = {}
    for name, item in provenance.items():
        path = Path(item["path"]).resolve(strict=True)
        if sha256(path) != item["sha256"]:
            raise RuntimeError(f"host provenance hash differs: {name}")
        paths[name] = path
    if provenance["evidence"]["sha256"] != receipt["build_evidence_sha256"] or provenance["artifacts"]["sha256"] != receipt["build_artifact_report_sha256"]:
        raise RuntimeError("host evidence/artifact hash binding differs")
    if sha256(paths["lock"]) != LOCK_SHA:
        raise RuntimeError("originating host lock differs")
    verify_host_manifest(paths["manifest"])
    evidence = json.loads(paths["evidence"].read_text())
    if evidence.get("schema") not in {"codex.hia.patch-parser-original-framework-evidence.v1", "codex.hia.parser-host-build-evidence.v1"}:
        raise RuntimeError("unrecognized actual host build evidence")
    if evidence["rustc_sha256"] != receipt["rustc_sha256"] or evidence["rustc_version"] != receipt["rustc_version"]:
        raise RuntimeError("originating host compiler evidence differs")
    for name in ["manifest", "lock", "graph", "artifacts"]:
        if evidence["files"].get(paths[name].name) != provenance[name]["sha256"]:
            raise RuntimeError(f"actual build does not bind host {name}")
    commands = [item["command"] if isinstance(item, dict) else item for item in evidence["commands"]]
    builds = [command for command in commands if len(command) > 1 and command[1] == "build"]
    valid_build = any("--locked" in command and "--manifest-path" in command and Path(command[command.index("--manifest-path") + 1]).resolve() == paths["manifest"] and "--message-format=json-render-diagnostics" in command for command in builds)
    if not valid_build or any(arg == "--all-features" or arg == "--no-default-features" or arg == "--features" or arg.startswith("--features=") for command in builds for arg in command):
        raise RuntimeError("actual host build command/feature selection differs")
    graph = json.loads(paths["graph"].read_text())
    packages = {package["id"]: package for package in graph["packages"]}
    names = sorted(package["name"] for package in packages.values())
    if names != receipt["packages"] or len(names) != receipt["package_count"] or any(name in {"codex-core", "codex-exec-server", "tokio", "tree-sitter", "tree-sitter-bash"} or "rama" in name for name in names):
        raise RuntimeError("actual host package graph differs")
    root = packages[graph["resolve"]["root"]]
    if Path(root["manifest_path"]).resolve() != paths["manifest"] or graph["workspace_members"] != [root["id"]]:
        raise RuntimeError("host graph resolves a different generating manifest")
    lock = tomllib.loads(paths["lock"].read_text())
    locked = {(item["name"], item["version"], item.get("source")) for item in lock["package"]}
    if any((item["name"], item["version"], item.get("source")) not in locked for item in packages.values()):
        raise RuntimeError("host graph includes a package outside the fixed lock")
    for name in ["path-uri", "absolute-path"]:
        matching = [package for package in packages.values() if package["name"] == "codex-utils-" + name]
        if len(matching) != 1 or Path(matching[0]["manifest_path"]).resolve() != ROOT / "codex-rs/utils" / name / "Cargo.toml":
            raise RuntimeError("host graph resolves an unrelated path dependency")
    if receipt["sources"] != host_source_hashes():
        raise RuntimeError("host source inventory or source hash differs")
    dep_dir = Path(receipt["dependency_dir"]).resolve(strict=True)
    if dep_dir != Path(graph["target_directory"]).resolve() / "debug/deps":
        raise RuntimeError("host artifact directory differs from the actual build")
    records = [json.loads(line) for line in paths["artifacts"].read_text().splitlines()]
    if [item for item in records if item.get("reason") == "build-finished"] != [{"reason": "build-finished", "success": True}]:
        raise RuntimeError("host artifact report is not a successful complete build")
    features = {item["id"]: item["features"] for item in graph["resolve"]["nodes"]}
    compiled = [item for item in records if item.get("reason") == "compiler-artifact"]
    inventory = set()
    direct = {}
    for item in compiled:
        package = packages.get(item["package_id"])
        if package is None or item["features"] != features[item["package_id"]] or Path(item["manifest_path"]).resolve() != Path(package["manifest_path"]).resolve():
            raise RuntimeError("compiled host package/features/manifest differ from its graph")
        for filename in item["filenames"]:
            path = Path(filename).resolve(strict=True)
            if path.parent == dep_dir and path.suffix in {".rlib", ".rmeta", ".so"}:
                inventory.add(str(path))
                name = item["target"]["name"]
                if name in HOST_NAMES and path.suffix == ".rlib":
                    if name in direct:
                        raise RuntimeError("duplicate direct host artifact")
                    direct[name] = {"path": str(path), "sha256": sha256(path), "features": item["features"], "profile": item["profile"], "package_id": item["package_id"]}
    if set(receipt["artifacts"]) != inventory:
        raise RuntimeError("host transitive artifact inventory differs from the complete Cargo report")
    if any(sha256(path) != digest for path, digest in receipt["artifacts"].items()):
        raise RuntimeError("cached transitive artifact differs from actual build receipt")
    if set(direct) != HOST_NAMES or receipt["rlibs"] != direct:
        raise RuntimeError("direct host rlib/features/profile/package_id differs from actual Cargo output")
    return dep_dir, {name: Path(item["path"]) for name, item in direct.items()}, receipt

def write_host_receipt(directory, rustc, sources, commands, env):
    """Describe only files and compiler records from the completed real build."""
    names = {"manifest": "Cargo.toml", "lock": "Cargo.lock", "graph": "dependency-graph.json", "artifacts": "build-artifacts.jsonl"}
    graph = json.loads((directory / names["graph"]).read_text())
    records = [json.loads(line) for line in (directory / names["artifacts"]).read_text().splitlines()]
    dep_dir = directory / "target/debug/deps"
    artifacts, direct = {}, {}
    for item in records:
        if item.get("reason") != "compiler-artifact":
            continue
        for filename in item["filenames"]:
            path = Path(filename)
            if path.parent == dep_dir and path.suffix in {".rlib", ".rmeta", ".so"}:
                artifacts[str(path)] = sha256(path)
                name = item["target"]["name"]
                if name in HOST_NAMES and path.suffix == ".rlib":
                    direct[name] = {"path": str(path), "sha256": sha256(path), "features": item["features"], "profile": item["profile"], "package_id": item["package_id"]}
    version = subprocess.check_output([str(rustc), "--version", "--verbose"], text=True)
    evidence = {
        "schema": "codex.hia.parser-host-build-evidence.v1", "rustc_sha256": sha256(rustc), "rustc_version": version,
        "commands": commands, "files": {name: sha256(directory / name) for name in names.values()},
        "cargo_environment": {key: env[key] for key in ["RUSTC", "CARGO_TARGET_DIR", "CARGO_BUILD_JOBS", "CARGO_PROFILE_DEV_DEBUG"]},
    }
    evidence_path = directory / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    provenance = {key: {"path": str(directory / name), "sha256": sha256(directory / name)} for key, name in names.items()}
    provenance["evidence"] = {"path": str(evidence_path), "sha256": sha256(evidence_path)}
    receipt = {
        "schema": HOST_RECEIPT_SCHEMA, "lock_sha256": LOCK_SHA, "rustc_sha256": sha256(rustc), "rustc_version": version,
        "dependency_dir": str(dep_dir), "rlibs": direct, "sources": sources, "artifacts": artifacts,
        "packages": sorted(package["name"] for package in graph["packages"]), "package_count": len(graph["packages"]),
        "build_evidence_sha256": sha256(evidence_path), "build_artifact_report_sha256": sha256(directory / names["artifacts"]),
        "provenance": provenance, "origin": "Actual fresh locked host-dependency Cargo build; no parser/path stub or unrelated cache.",
    }
    path = directory / "host-dependencies-receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    return path


def host_dependencies(rustc, temporary, report, receipt_path=None):
    """Build current real host crates, with a frozen lock and a fresh target dir."""
    lock = HERE / "parser_oracle_Cargo.lock"
    if sha256(lock) != LOCK_SHA:
        raise RuntimeError("the parser oracle dependency lock changed without an explicit pin update")
    if receipt_path is not None:
        dep_dir, dependencies, receipt = verified_host_receipt(rustc, receipt_path)
        report["host_dependencies"] = {**receipt, "reused_verified_build": True, "receipt_sha256": sha256(receipt_path)}
        return dep_dir, dependencies
    directory = temporary / "host-dependencies"
    directory.mkdir()
    target = directory / "target"
    manifest = directory / "Cargo.toml"
    manifest.write_text('''[package]
name = "codex-parser-original-oracle"
version = "0.0.0"
edition = "2024"
publish = false
[workspace]
[lib]
path = "lib.rs"
[dependencies]
codex-utils-path-uri = { path = %s }
serde_json = "1"
thiserror = "2.0.17"
[dev-dependencies]
codex-utils-absolute-path = { path = %s }
pretty_assertions = "1.4.1"
tempfile = "3.23.0"
''' % (json.dumps(str(ROOT / "codex-rs/utils/path-uri")), json.dumps(str(ROOT / "codex-rs/utils/absolute-path"))))
    (directory / "lib.rs").write_text("// Dependency build only; no parser or path implementation.\npub fn dependency_build_only() {}\n")
    shutil.copyfile(lock, directory / "Cargo.lock")
    cargo = Path(rustc).parent / "cargo"
    if not cargo.is_file():
        found = shutil.which("cargo")
        if found is None:
            raise RuntimeError("real Cargo is required to build the actual PathUri dependencies")
        cargo = Path(found)
    env = os.environ.copy()
    env.update(RUSTC=str(rustc), CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS="1", CARGO_PROFILE_DEV_DEBUG="0")
    base = [str(cargo), "--locked", "--manifest-path", str(manifest)]
    command_start = len(report.get("commands", []))
    initial_sources = host_source_hashes()
    graph_text = run([str(cargo), "metadata", *base[1:], "--format-version", "1", "--filter-platform", "x86_64-unknown-linux-gnu"], report, env=env)
    (directory / "dependency-graph.json").write_text(graph_text)
    graph = json.loads(graph_text)
    forbidden = {"codex-core", "codex-exec-server", "tokio", "tree-sitter", "tree-sitter-bash"}
    names = sorted(package["name"] for package in graph["packages"])
    if any(name in forbidden or "rama" in name for name in names):
        raise RuntimeError(f"isolated parser host dependency graph expanded unexpectedly: {names}")
    sources = {}
    for package in graph["packages"]:
        if package["name"] in {"codex-utils-path-uri", "codex-utils-absolute-path"}:
            p = Path(package["manifest_path"])
            expected = ROOT / "codex-rs/utils" / ("path-uri" if package["name"].endswith("path-uri") else "absolute-path") / "Cargo.toml"
            if p.resolve() != expected.resolve():
                raise RuntimeError("host path dependency resolved to an unrelated source")
            for source in [p, *sorted((p.parent / "src").rglob("*.rs"))]:
                sources[str(source)] = sha256(source)
    built = run([str(cargo), "build", *base[1:], "--jobs", "1", "--tests", "--message-format=json-render-diagnostics"], report, env=env)
    (directory / "build-artifacts.jsonl").write_text(built)
    dependencies = {}
    required = {"codex_utils_path_uri", "codex_utils_absolute_path", "thiserror", "serde_json", "pretty_assertions", "tempfile"}
    for line in built.splitlines():
        artifact = json.loads(line)
        if artifact.get("reason") == "compiler-artifact" and artifact["target"]["name"] in required:
            for filename in artifact["filenames"]:
                if filename.endswith(".rlib"):
                    dependencies[artifact["target"]["name"]] = Path(filename)
    if set(dependencies) != required or sha256(directory / "Cargo.lock") != LOCK_SHA:
        raise RuntimeError("the locked actual host build did not produce all required exact rlibs")
    if any(sha256(path) != digest for path, digest in sources.items()):
        raise RuntimeError("actual host dependency source changed during compilation")
    if host_source_hashes() != initial_sources:
        raise RuntimeError("current host sources changed during the fresh build")
    receipt_path = write_host_receipt(directory, rustc, initial_sources, report["commands"][command_start:], env)
    dep_dir, dependencies, receipt = verified_host_receipt(rustc, receipt_path)
    report["host_dependencies"] = {**receipt, "fresh_target_directory": True, "source_unchanged": True,
                                 "reused_verified_build": False, "receipt_path": str(receipt_path),
                                 "receipt_sha256": sha256(receipt_path)}
    return dep_dir, dependencies


def wrapper_text(parser, streaming, args, native=False):
    text = f'#[path = {json.dumps(str(parser))}]\npub mod parser;\n'
    text += f'#[path = {json.dumps(str(streaming))}]\npub mod streaming_parser;\n'
    if native:
        for name in ["hia_native_parser", "hia_native_streaming_parser"]:
            text += f'#[path = {json.dumps(str(OWNER / (name + ".rs")))}]\nmod {name};\n'
    text += 'pub use parser::{parse_patch, Hunk, ParseError, UpdateFileChunk};\n'
    text += 'pub use streaming_parser::StreamingPatchParser;\n'
    text += f'include!({json.dumps(str(args))});\n'
    return text


def build_parser_libraries(rustc, library_dir, temporary, report, *, opt_level=0, codegen_units=1, compile_tests=True, dependency_receipt=None):
    """Also usable by the external benchmark; the two libraries share all flags."""
    temporary = Path(temporary)
    temporary.mkdir(parents=True, exist_ok=True)
    original_dir = temporary / "original"
    original_dir.mkdir()
    recovered = {}
    for name in PINS:
        original, markers = original_rust_source(name, (OWNER / name).read_bytes())
        (original_dir / name).write_bytes(original)
        recovered[name] = {"bytes": len(original), "sha256": hashlib.sha256(original).hexdigest(), "git_blob": PINS[name][2], "removed_markers": markers}
    lib = (OWNER / "lib.rs").read_bytes()
    match = re.search(rb'(?m)^#\[derive\(Debug, PartialEq\)\]\npub struct ApplyPatchArgs \{\n(?:    .*\n)*\}\n', lib)
    if match is None or hashlib.sha256(match.group()).hexdigest() != ARGS_SHA:
        raise RuntimeError("the original ApplyPatchArgs data declaration changed")
    args_path = original_dir / "apply_patch_args.rs"
    args_path.write_bytes(match.group())
    dep_dir, deps = host_dependencies(rustc, temporary, report, dependency_receipt)
    flags = [str(rustc), "--edition=2024", "-C", f"opt-level={opt_level}", "-C", f"codegen-units={codegen_units}", "-C", "debug-assertions=on", "-C", "overflow-checks=on", "-L", f"dependency={dep_dir}"]
    for name in ["codex_utils_path_uri", "thiserror"]:
        flags += ["--extern", f"{name}={deps[name]}"]
    libraries = {}
    for name, native in [("parser_reference", False), ("parser_native", True)]:
        wrapper = temporary / f"{name}.rs"
        source_dir = OWNER if native else original_dir
        wrapper.write_text(wrapper_text(source_dir / "parser.rs", source_dir / "streaming_parser.rs", args_path, native))
        extra = ["--cfg", 'feature="hia-native"', "-L", f"native={library_dir}", "-l", "static=codex_hia_parser"] if native else []
        library = temporary / f"lib{name}.rlib"
        run(flags + extra + ["--crate-name", name, "--crate-type", "rlib", str(wrapper), "-o", str(library)], report)
        libraries[name] = library
        if compile_tests:
            tests = temporary / f"{name}_original_tests"
            test_flags = [item for dependency in ["codex_utils_absolute_path", "pretty_assertions", "tempfile"] for item in ["--extern", f"{dependency}={deps[dependency]}"]]
            run(flags + extra + test_flags + ["--test", str(wrapper), "-o", str(tests)], report)
            stdout = run([str(tests), "--test-threads=2"], report, echo=True)
            summary = re.search(r"test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;", stdout)
            if summary is None or int(summary.group(1)) < 17:
                raise RuntimeError(f"{name} did not execute the complete 17 original parser tests")
            report.setdefault("original_file_tests", {})[name] = {"passed": int(summary.group(1)), "skipped": 0, "binary_sha256": sha256(tests)}
    report["original_sources"] = recovered
    report["libraries"] = {name: {"path": str(path), "sha256": sha256(path)} for name, path in libraries.items()}
    return {"libraries": libraries, "dependency_dir": dep_dir, "dependencies": deps, "rustc_flags": flags}


def verify(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError("a real Rust compiler is required")
    library_dir = args.library_dir.resolve(strict=True)
    build_path = library_dir / "build.json"
    build = json.loads(build_path.read_text())
    module = build["modules"]["parser"]
    link = module["codex_link_abi"]
    archive = library_dir / "libcodex_hia_parser.a"
    if build.get("status") != "built" or build.get("compiler_fixed_point") is not True:
        raise RuntimeError("actual fixed-point B3 build is required")
    if module["source_sha256"] != sha256(ROOT / "hia/parser.hepta") or link["archive_sha256"] != sha256(archive) or link["symbol"] != "codex_hia_parser":
        raise RuntimeError("parser source/archive/symbol binding failed")
    paths = [OWNER / name for name in ["parser.rs", "streaming_parser.rs", "hia_native_parser.rs", "hia_native_streaming_parser.rs", "lib.rs"]]
    paths += [ROOT / "hia/parser.hepta", ROOT / "hia/parser_buffer_contract.json", HERE / "native_parser_caller.rs", HERE / "parser_cases.py", HERE / "parser_oracle_Cargo.lock", Path(__file__)]
    sources = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
    report["inputs"] = {"sources": sources, "build_report_sha256": sha256(build_path), "archive_sha256": sha256(archive), "compiler_sha256": build["compiler_sha256"], "baseline_head": "e53603879b77d215fe4d58b40be87376cd95754d"}
    report["rustc"] = run([rustc, "--version", "--verbose"], report).strip()
    with tempfile.TemporaryDirectory(prefix="codex-hia-parser-caller-") as directory:
        temporary = Path(directory)
        report["temporary_storage"] = {
            "directory": directory,
            "free_bytes_before_build": shutil.disk_usage(temporary).free,
        }
        built = build_parser_libraries(rustc, library_dir, temporary, report, dependency_receipt=args.dependency_receipt)
        case_path = temporary / "cases.jsonl"
        counts = {}
        with case_path.open("w") as output:
            for i, (family, case) in enumerate(itertools.chain(parser_cases.cases(), parser_cases.large_cases())):
                case.update(case_id=f"{i:06d}:{family}", family=family)
                output.write(json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n")
                counts[family] = counts.get(family, 0) + 1
        outputs = []
        for name, native in [("parser_reference", False), ("parser_native", True)]:
            binary = temporary / f"{name}_caller"
            command = built["rustc_flags"] + ["--extern", f"{name}={built['libraries'][name]}", "--extern", f"serde_json={built['dependencies']['serde_json']}"]
            if native:
                command += ["--cfg", 'feature="hia-native"', "-L", f"native={library_dir}", "-l", "static=codex_hia_parser", "-C", "link-arg=-Wl,--wrap=codex_hia_parser"]
            run(command + [str(HERE / "native_parser_caller.rs"), "-o", str(binary)], report)
            if native:
                symbols = run(["nm", "--defined-only", str(binary)], report)
                if not re.search(r"\bT codex_hia_parser$", symbols, re.MULTILINE) or "__wrap_codex_hia_parser" not in symbols:
                    raise RuntimeError("actual HIA implementation or counting forwarder missing from native caller")
            output_path = temporary / f"{name}.jsonl"
            with case_path.open("rb") as stdin, output_path.open("wb") as stdout:
                start = time.monotonic()
                result = subprocess.run([str(binary)], stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, timeout=300)
            elapsed = round(time.monotonic() - start, 6)
            termination_signal = signal.Signals(-result.returncode).name if result.returncode < 0 else None
            execution = {
                "binary_sha256": sha256(binary), "output_sha256": sha256(output_path),
                "output_bytes": output_path.stat().st_size, "returncode": result.returncode,
                "termination_signal": termination_signal, "elapsed_seconds": elapsed,
                "stderr_bytes": len(result.stderr), "stderr": result.stderr.decode(errors="replace"),
            }
            report.setdefault("executions", {})[name] = execution
            if result.returncode:
                complete_records, trailing_bytes = 0, 0
                with output_path.open("rb") as partial:
                    for block in iter(lambda: partial.read(1048576), b""):
                        complete_records += block.count(b"\n")
                        trailing_bytes = len(block.rsplit(b"\n", 1)[1]) if b"\n" in block else trailing_bytes + len(block)
                execution.update(complete_records=complete_records, trailing_record_bytes=trailing_bytes)
                with case_path.open() as requests:
                    for index, request in enumerate(requests):
                        if index == complete_records - 1:
                            execution["last_complete_case"] = json.loads(request)["case_id"]
                        if index == complete_records:
                            execution["first_incomplete_case"] = json.loads(request)["case_id"]
                            break
                raise RuntimeError(f"{name} transcript failed ({result.returncode}, {termination_signal}): {result.stderr[-8000:].decode(errors='replace')}")
            if native:
                match = re.search(rb"parser_native_operations=(\[[0-9,]+\])", result.stderr)
                if match is None:
                    raise RuntimeError("native public caller did not report actual forwarded HIA calls")
                report["actual_hia_operations"] = json.loads(match.group(1))
            outputs.append(output_path)
        comparisons = 0
        with case_path.open() as requests, outputs[0].open() as reference, outputs[1].open() as native:
            for line in requests:
                case = json.loads(line)
                expected = json.loads(next(reference))
                actual = json.loads(next(native))
                if expected.get("case_id") != case["case_id"] or expected != actual:
                    raise RuntimeError(f"complete original/native public transcript differs at {case['case_id']}")
                comparisons += 1
            if next(reference, None) is not None or next(native, None) is not None:
                raise RuntimeError("extra parser transcript records")
        report.update(cases=counts, original_rust_comparisons=comparisons, tests_skipped=0, corpus_sha256=sha256(case_path))
    if any(sha256(ROOT / path) != digest for path, digest in sources.items()):
        raise RuntimeError("production or test source changed during parser qualification")
    report.update(passed=True, source_unchanged=True, oracle="complete byte-pinned original files, independently compiled; actual current PathUri dependencies; no algorithm extraction, grammar mirror, fallback or skipped entry", caller="feature-selected public parser and streaming owners, with counted forwarding to the actual HIA symbol", scope="parser component public behavior and native dispatch; full crate, Core events, installed executables and performance remain separate gates")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--dependency-receipt", type=Path, help="source/compiler/feature/artifact-bound prior real host build")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {"schema": "codex.hia.native-parser-caller.v1", "passed": False, "commands": []}
    try:
        verify(args, report)
    except (OSError, RuntimeError, KeyError, ValueError, StopIteration, subprocess.SubprocessError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

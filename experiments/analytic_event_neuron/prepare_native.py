"""Build original pinned Hepta crates plus isolated experimental examples.

No production manifest/lock edits, network fetches, or precompiled rlib imports.
The caller supplies a Rust 1.90+ toolchain, just, rustfmt and lock-matching vendor.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
import tomllib


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(destination, *, cargo, rustc, rustfmt, just, vendor):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Fresh destination required; existing compiled artifacts must not be reused")
    manifest = json.loads((HERE / "NATIVE_SOURCE_MANIFEST.json").read_text())
    for item in manifest["files"]:
        source = ROOT / item["path"]
        data = source.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != item["sha"] or len(data) != item["size"]:
            raise ValueError(f"Pinned source mismatch: {item['path']}")
    destination.mkdir(parents=True)
    for item in manifest["files"]:
        relative = Path(item["path"]).relative_to("codex-rs")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item["path"], target)
    (destination / "Cargo.toml").write_text('''[workspace]
members = ["hepta-types", "hepta-infer-core", "hepta-neuron"]
resolver = "2"
[workspace.package]
version = "0.0.0"
edition = "2024"
license = "Apache-2.0"
[workspace.dependencies]
serde = { version = "=1.0.228", features = ["rc"] }
serde_json = "=1.0.149"
sha2 = "=0.10.9"
pretty_assertions = "=1.4.1"
[workspace.lints.rust]
[profile.dev]
debug = 0
incremental = false
''')
    (destination / ".cargo").mkdir()
    (destination / ".cargo/config.toml").write_text(
        '[source.crates-io]\nreplace-with = "vendored-sources"\n'
        '[source.vendored-sources]\ndirectory = ' + json.dumps(str(Path(vendor).resolve())) + '\n')
    tools = {name: str(Path(value).resolve()) for name, value in
             {"cargo": cargo, "rustc": rustc, "rustfmt": rustfmt, "just": just}.items()}
    # just is the repository-prescribed test entry point. These recipes apply to
    # this isolated workspace; the production workspace remains unchanged.
    (destination / "justfile").write_text(
        'set shell := ["sh", "-eu", "-c"]\n'
        'fmt:\n    "' + tools["rustfmt"] + '" --edition 2024 "' + str(HERE / "native.rs") + '"\n'
        'build:\n    "' + tools["cargo"] + '" build --offline --release -p codex-hepta-neuron --example analytic_event --example feedback_reference\n'
        'test:\n    "' + tools["cargo"] + '" test --offline -p codex-hepta-types -p codex-hepta-infer-core -p codex-hepta-neuron\n')
    env = dict(os.environ)
    env["RUSTC"] = tools["rustc"]
    env["LD_LIBRARY_PATH"] = str(Path(tools["rustc"]).parent.parent / "lib") + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    env["PATH"] = str(Path(tools["rustc"]).parent) + os.pathsep + str(Path(tools["cargo"]).parent) + os.pathsep + env.get("PATH", "")
    env["CARGO_TARGET_DIR"] = str(destination / "target")
    env["CARGO_HOME"] = str(destination / "cargo-home")
    logs = {}
    def invoke(recipe):
        started = time.perf_counter()
        result = subprocess.run([tools["just"], recipe], cwd=destination, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        path = destination / (recipe + ".log")
        path.write_text(result.stdout)
        logs[recipe] = {"returncode": result.returncode, "seconds": time.perf_counter() - started,
                        "log_sha256": sha256(path), "log": str(path)}
        if result.returncode:
            raise RuntimeError(f"just {recipe} failed: {path}\n{result.stdout[-6000:]}")
    invoke("fmt")
    example = destination / "hepta-neuron/examples/analytic_event"
    example.mkdir(parents=True)
    shutil.copy2(HERE / "native.rs", example / "main.rs")
    shutil.copy2(HERE / "native_head.rs", example / "native_head.rs")
    reference_source = ROOT / "experiments/multimodal_output_portfolio/repair_20261026/control/neuron_feedback_probe/native.rs"
    shutil.copy2(reference_source, destination / "hepta-neuron/examples/feedback_reference.rs")
    adapter_sources = {name: sha256(HERE / name) for name in ("native.rs", "native_head.rs")}
    source_digest = hashlib.sha256(json.dumps(adapter_sources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    env["AEN_NATIVE_SOURCE_SHA256"] = source_digest
    env["AEN_COMPILER_SHA256"] = sha256(tools["rustc"])
    invoke("build")
    invoke("test")
    repo_lock = tomllib.loads((ROOT / "codex-rs/Cargo.lock").read_text())
    built_lock = tomllib.loads((destination / "Cargo.lock").read_text())
    original_packages = {(p["name"], p["version"], p.get("source"), p.get("checksum")) for p in repo_lock["package"]}
    dependencies = [p for p in built_lock["package"] if p.get("source")]
    unmatched = [p for p in dependencies if (p["name"], p["version"], p.get("source"), p.get("checksum")) not in original_packages]
    if unmatched:
        raise ValueError(f"Resolved dependencies differ from original lock: {unmatched}")
    binary = destination / "target/release/examples/analytic_event"
    versions = {name: subprocess.run([path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, check=True, env=env).stdout.strip() for name, path in tools.items()}
    receipt = {"schema": "hepta.analytic-event.native-build.v1", "repository": manifest["repository"],
               "source_commit": manifest["commit"], "original_source_files": len(manifest["files"]),
               "original_source_manifest_sha256": sha256(HERE / "NATIVE_SOURCE_MANIFEST.json"),
               "original_source_git_blob_verified": True, "fresh_build": True,
               "original_lock_sha256": sha256(ROOT / "codex-rs/Cargo.lock"),
               "generated_lock_sha256": sha256(destination / "Cargo.lock"),
               "dependency_lock_subset_verified": True, "resolved_dependencies": dependencies,
               "adapter_source_sha256": adapter_sources, "adapter_tuple_sha256": source_digest,
               "tool_versions": versions, "tool_sha256": {name: sha256(path) for name, path in tools.items()},
               "platform": platform.platform(), "machine": platform.machine(), "libc": platform.libc_ver(),
               "commands": logs, "build_directory": str(destination), "binary": str(binary),
               "binary_sha256": sha256(binary), "production_source_modified": False,
               "reference_adapter_source_sha256": sha256(reference_source),
               "reference_binary": str(destination / "target/release/examples/feedback_reference"),
               "reference_binary_sha256": sha256(destination / "target/release/examples/feedback_reference"),
               "integration_scope": "original sparse kernel, typed NeuronModelPort and NeuronRuntime/SparseJournal; experimental local owner"}
    receipt_path = destination / "BUILD_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True)
    for name in ("cargo", "rustc", "rustfmt", "just", "vendor"):
        parser.add_argument("--" + name, required=True)
    arguments = vars(parser.parse_args())
    receipt = build(**arguments)
    print(json.dumps({"binary": receipt["binary"], "binary_sha256": receipt["binary_sha256"],
                      "receipt": str(Path(receipt["build_directory"]) / "BUILD_RECEIPT.json")}))


if __name__ == "__main__":
    main()

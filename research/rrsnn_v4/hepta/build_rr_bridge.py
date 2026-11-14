"""Bounded offline build; preserve final broker and immediately release caches."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import native_components as native

ROOT = native.ROOT
BUILD = ROOT / "rr_bridge_build"


def build():
    if shutil.disk_usage(ROOT).free < 240_000_000:
        raise RuntimeError("Insufficient space for bounded bridge build; fixed guard retained")
    before = native.upstream_identity()
    BUILD.mkdir(exist_ok=True)
    (BUILD / ".cargo").mkdir(exist_ok=True)
    (BUILD / ".cargo/config.toml").write_text('[source.crates-io]\nreplace-with="vendor"\n[source.vendor]\ndirectory='
        + json.dumps(str(native.UPSTREAM / "vendor")) + '\n[net]\noffline=true\n')
    manifest = '[package]\nname="codex-rrsnn-rr-feature-bridge"\nversion="0.1.0"\nedition="2024"\n[workspace]\n[dependencies]\nserde_json="=1.0.149"\n'
    for crate in ("hepta-types", "hepta-infer-core", "hepta-neuron"):
        manifest += 'codex-' + crate + '={path=' + json.dumps(str(native.UPSTREAM / crate)) + '}\n'
    manifest += '[[bin]]\nname="rrsnn-rr-feature-broker"\npath=' + json.dumps(str(ROOT / 'rr_bridge_native/src/main.rs'))
    manifest += '\n[profile.release]\ndebug=false\ncodegen-units=1\nopt-level=1\nstrip="debuginfo"\n'
    (BUILD / "Cargo.toml").write_text(manifest)
    (BUILD / "justfile").write_text('fmt:\n    cargo fmt --manifest-path Cargo.toml\n\nbuild:\n    cargo build --release --locked --offline --manifest-path Cargo.toml\n')
    env = dict(os.environ, PATH=str(native.RUST) + os.pathsep + os.environ["PATH"],
        RUSTC=str(native.RUST / "rustc"), RUSTDOC=str(native.RUST / "rustdoc"),
        CARGO_HOME=str(native.BUILD / "cargo_home"), CARGO_TARGET_DIR=str(BUILD / "target"),
        CARGO_BUILD_JOBS="1", CARGO_INCREMENTAL="0")
    os.sched_setaffinity(0, {8})
    steps = []
    for command in [["cargo", "generate-lockfile", "--offline"], [str(native.JUST), "fmt"], [str(native.JUST), "build"]]:
        start = time.perf_counter()
        result = subprocess.run(command, cwd=BUILD, env=env, text=True, capture_output=True)
        steps.append({"command": command, "code": result.returncode, "seconds": time.perf_counter() - start,
                      "stdout": result.stdout, "stderr": result.stderr})
        native.write_json(BUILD / "build.json", {"steps": steps, "all_passed": all(x["code"] == 0 for x in steps)})
        print(json.dumps({"command": command, "code": result.returncode, "tail": (result.stdout + result.stderr)[-3000:]}), flush=True)
        if result.returncode:
            raise RuntimeError("bridge build failed; evidence preserved")
    binary = BUILD / "bin/rrsnn-rr-feature-broker"
    binary.parent.mkdir(exist_ok=True)
    source = BUILD / "target/release/rrsnn-rr-feature-broker"
    if binary.exists():
        raise RuntimeError("refuse overwrite of preserved broker binary")
    os.link(source, binary)
    binary_hash = native.sha(binary)
    free_before = shutil.disk_usage(ROOT).free
    shutil.rmtree(BUILD / "target")
    assert native.sha(binary) == binary_hash
    assert native.upstream_identity() == before
    report = {"steps": steps, "all_passed": True, "upstream": before,
              "binary_sha256": binary_hash, "binary": str(binary),
              "profile": "release opt-level1, debuginfo stripped; correctness/fault bridge, not performance qualification",
              "cache_cleanup": {"free_before": free_before, "free_after": shutil.disk_usage(ROOT).free,
                                "only_removed": str(BUILD / "target")}}
    native.write_json(BUILD / "build.json", report)
    return binary


if __name__ == "__main__":
    build()

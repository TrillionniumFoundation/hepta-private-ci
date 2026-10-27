"""Compile unchanged repository Rust sources in an explicitly scoped leaf graph.

This is not a full-product build. Only unused dev-dependencies of the transitive
hepta-contracts crate are removed in the generated leaf manifest. Registry
versions and checksums must remain a subset of the repository Cargo.lock.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import tomllib

CRATES = ("hepta-types", "hepta-cognitive-types", "hepta-memory-retrieval", "hepta-contracts", "hepta-wire", "hepta-context-compiler")
TEST_PACKAGES = ("codex-hepta-cognitive-types", "codex-hepta-memory-retrieval", "codex-hepta-context-compiler")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def toml_value(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(key) + " = " + toml_value(item) for key, item in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    return json.dumps(value)


def qualify(output, tool_root, fixture_dir=None, fix_only=False):
    project = Path(__file__).resolve().parents[1]
    repo = project.parents[1]
    output, tool_root = Path(output).absolute(), Path(tool_root).absolute()
    env = dict(os.environ)
    env.update(RUSTUP_HOME=str(tool_root / "rustup"), CARGO_HOME=str(tool_root / "cargo"), PATH=os.pathsep.join((str(tool_root / "cargo/bin"), str(tool_root / "bin"), env["PATH"])))
    receipt_path = output / "NATIVE-QUALIFICATION.json"
    if fix_only:
        receipt = json.loads(receipt_path.read_bytes())
    else:
        output.mkdir(parents=True, exist_ok=False)
        receipt = {"schema": "hepta.memory.native-qualification.v1", "commands": [], "source_sha256": {}, "scope": "leaf graph; not full-product qualification", "manifest_adjustments": ["remove only transitive hepta-contracts dev-dependencies, which are not tested"]}
        original = tomllib.loads((repo / "codex-rs/Cargo.toml").read_text())
        sections = ["[workspace]", "members = " + toml_value([*CRATES, "bridge"]), 'resolver = "2"', "[workspace.package]"]
        for name in ("edition", "version", "license"):
            sections.append(name + " = " + toml_value(original["workspace"]["package"][name]))
        sections.append("[workspace.dependencies]")
        for name in ("ed25519-dalek", "rustix", "serde", "serde_json", "sha2", "zeroize"):
            sections.append(name + " = " + toml_value(original["workspace"]["dependencies"][name]))
        sections.append('codex-hepta-types = { path = "hepta-types" }')
        for group, lints in original["workspace"]["lints"].items():
            sections.append("[workspace.lints." + group + "]")
            sections.extend(name + " = " + toml_value(value) for name, value in lints.items())
        (output / "Cargo.toml").write_text("\n".join(sections) + "\n")
        for crate in CRATES:
            source, target = repo / "codex-rs" / crate, output / crate
            shutil.copytree(source, target)
            for path in source.rglob("*"):
                if path.is_file():
                    receipt["source_sha256"][str(path.relative_to(repo))] = sha(path)
            if crate == "hepta-contracts":
                manifest = target / "Cargo.toml"
                manifest.write_text(re.sub(r"(?ms)^\[dev-dependencies\].*?(?=^\[|\Z)", "", manifest.read_text()))
        for name in (".config/nextest.toml", ".cargo/config.toml"):
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / "codex-rs" / name, target)
            receipt["source_sha256"]["codex-rs/" + name] = sha(target)
        # The original test recipe is kept. Only overrides naming packages
        # absent from this declared leaf are removed; nextest rejects those
        # unmatched package filters before it can compile any selected test.
        nextest = output / ".config/nextest.toml"
        removed = []

        def applicable_override(match):
            packages = re.findall(r"package\(([^)]+)\)", match.group())
            absent = set(packages) - {"codex-" + crate for crate in CRATES}
            if absent:
                removed.extend(sorted(absent))
                return ""
            return match.group()

        nextest.write_text(re.sub(r"(?ms)^\[\[profile\.[^\]]+\.overrides\]\].*?(?=^\[|\Z)", applicable_override, nextest.read_text()))
        receipt["nextest_removed_unused_package_overrides"] = sorted(set(removed))
        receipt["leaf_nextest_sha256"] = sha(nextest)
        bridge = output / "bridge"
        (bridge / "src").mkdir(parents=True)
        shutil.copy2(Path(__file__).with_name("bridge.rs"), bridge / "src/main.rs")
        receipt["source_sha256"][str(Path(__file__).with_name("bridge.rs").relative_to(repo))] = sha(bridge / "src/main.rs")
        bridge_manifest = ['[package]', 'name = "native-memory-bridge"', 'version.workspace = true', 'edition.workspace = true', 'license.workspace = true', '[lints]', 'workspace = true', '[dependencies]']
        for crate in ("hepta-types", "hepta-cognitive-types", "hepta-memory-retrieval", "hepta-context-compiler"):
            bridge_manifest.append(f'codex-{crate} = {{ path = "../{crate}" }}')
        bridge_manifest.extend(('serde = { workspace = true, features = ["derive"] }', 'serde_json.workspace = true'))
        (bridge / "Cargo.toml").write_text("\n".join(bridge_manifest) + "\n")
        shutil.copy2(repo / "codex-rs/Cargo.lock", output / "Cargo.lock")
        receipt["repository_lock_sha256"] = sha(repo / "codex-rs/Cargo.lock")
        receipt["repository_manifest_sha256"] = sha(repo / "codex-rs/Cargo.toml")

    def run(arguments, *, cwd=output, expected=0):
        log = output / f"command-{len(receipt['commands']):02d}.log"
        start = time.perf_counter()
        with log.open("wb") as stream:
            result = subprocess.run(arguments, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
        item = {"argv": arguments, "cwd": str(cwd), "exit_code": result.returncode, "expected_exit_code": expected, "wall_seconds": time.perf_counter() - start, "log": log.name, "log_sha256": sha(log)}
        receipt["commands"].append(item)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        print(json.dumps(item), flush=True)
        if result.returncode != expected:
            raise RuntimeError("native command failed; inspect " + str(log))

    manifest = str(output / "Cargo.toml")
    packages = [item for package in TEST_PACKAGES for item in ("-p", package)]
    if fix_only:
        run(["just", "--justfile", str(repo / "justfile"), "fix", "--manifest-path", manifest, "--locked", "--allow-no-vcs", *packages, "-p", "native-memory-bridge"], cwd=repo)
        receipt["leaf_rust_changed_by_fix"] = [name for name, expected in receipt["source_sha256"].items() if name.endswith(".rs") and sha(output / ("bridge/src/main.rs" if name.endswith("native/bridge.rs") else name.removeprefix("codex-rs/"))) != expected]
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return receipt
    run(["cargo", "--version"])
    run(["rustc", "--version"])
    # Add the local bridge to the copied lock, then verify every external entry
    # before compiling or running tests with --locked.
    run(["cargo", "metadata", "--format-version=1", "--manifest-path", manifest])
    original_lock = tomllib.loads((repo / "codex-rs/Cargo.lock").read_text())
    leaf_lock = tomllib.loads((output / "Cargo.lock").read_text())
    fields = ("name", "version", "source", "checksum")
    allowed = {tuple(package.get(key) for key in fields) for package in original_lock["package"] if "source" in package}
    actual = {tuple(package.get(key) for key in fields) for package in leaf_lock["package"] if "source" in package}
    if not actual <= allowed:
        raise RuntimeError("leaf dependency drift from repository lock: " + repr(actual - allowed))
    receipt["locked_external_packages"] = [dict(zip(fields, package)) for package in sorted(actual)]
    receipt["leaf_lock_sha256"] = sha(output / "Cargo.lock")
    receipt["leaf_manifest_sha256"] = sha(output / "Cargo.toml")
    run(["just", "--justfile", str(repo / "justfile"), "test", "--manifest-path", manifest, "--locked", "--lib", *packages], cwd=repo)
    run(["cargo", "build", "--manifest-path", manifest, "--locked", "-p", "native-memory-bridge"])
    if fixture_dir:
        fixture_dir = Path(fixture_dir).absolute()
        binary = str(output / "target/debug/native-memory-bridge")
        for owner, expected in (("owner.json", 0), ("owner-revoked.json", 1)):
            run([binary, str(fixture_dir / "request.json"), str(fixture_dir / "readout.json"), str(fixture_dir / owner)], expected=expected)
        receipt["fixture_sha256"] = {name: sha(fixture_dir / name) for name in ("request.json", "readout.json", "owner.json", "owner-revoked.json")}
    receipt["source_still_matches"] = all(sha(repo / name) == expected for name, expected in receipt["source_sha256"].items())
    receipt["binary_sha256"] = sha(output / "target/debug/native-memory-bridge")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    if not receipt["source_still_matches"]:
        raise RuntimeError("repository source changed during leaf validation")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tool-root", required=True, type=Path)
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--fix-only", action="store_true")
    args = parser.parse_args()
    qualify(args.output, args.tool_root, args.fixture_dir, args.fix_only)

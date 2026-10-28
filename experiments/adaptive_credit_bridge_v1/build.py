"""Build an isolated bridge from unchanged production crates and verified packages."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request

from experiments.adaptive_neuron_v2.ledger import (
    measured_stage,
    sha,
    write_json_exclusive,
)
from experiments.adaptive_neuron_v2.provenance import verify

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CRATES = (
    "hepta-types",
    "hepta-intuition",
    "hepta-cognitive-types",
    "hepta-memory-retrieval",
    "hepta-learning-ledger",
)


def build(destination, compiler, source_seal, cache, bridge_seal=None):
    destination, compiler, cache = map(
        lambda p: Path(p).resolve(), (destination, compiler, cache)
    )
    with measured_stage(
        destination,
        identity={"stage": "signed_credit_bridge_build"},
        scope="Protected v2 source verification, exact production-crate materialization, local offline resolution, checksum verification and extraction of cached dependency packages, isolated compilation and executable hashing.",
    ) as cost:
        protected = verify(source_seal)
        from .provenance import verify_source

        integration_source = (
            verify_source(bridge_seal, source_seal)
            if bridge_seal is not None
            else {"development_only": True}
        )
        lock_before = sha(ROOT / "codex-rs/Cargo.lock")
        identities = {}
        for name in CRATES:
            source = ROOT / "codex-rs" / name
            target = destination / name
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(".rsync-tmp"))
            for p in source.rglob("*"):
                if p.is_file() and p.suffix in {".rs", ".toml"}:
                    identities[str(p.relative_to(ROOT))] = sha(
                        target / p.relative_to(source)
                    )
        bridge = destination / "bridge"
        (bridge / "src").mkdir(parents=True)
        for p in HERE.glob("*.rs"):
            shutil.copy2(p, bridge / "src" / p.name)
            identities[str(p.relative_to(ROOT))] = sha(p)
        original = ROOT / "codex-rs/hepta-intelligence/src/outcome_credit_v2.rs"
        shutil.copy2(original, bridge / "src/original_outcome_credit.rs")
        identities[str(original.relative_to(ROOT))] = sha(original)
        identities[str(Path(__file__).relative_to(ROOT))] = sha(__file__)
        identities["codex-rs/Cargo.lock"] = lock_before
        (bridge / "Cargo.toml").write_text("""[package]
name = "hepta-research-signed-credit-bridge"
version.workspace = true
edition.workspace = true
license.workspace = true
[[bin]]
name = "signed_credit_bridge"
path = "src/main.rs"
[dependencies]
codex-hepta-learning-ledger = {path="../hepta-learning-ledger"}
codex-hepta-types = {path="../hepta-types"}
ed25519-dalek.workspace = true
serde = {workspace=true,features=["derive"]}
serde_json.workspace = true
""")
        (destination / "Cargo.toml").write_text("""[workspace]
members=["bridge","hepta-types","hepta-intuition","hepta-cognitive-types","hepta-memory-retrieval","hepta-learning-ledger"]
resolver="2"
[workspace.package]
version="0.0.0"
edition="2024"
license="Apache-2.0"
[workspace.dependencies]
ed25519-dalek={version="=2.2.0",features=["pkcs8"]}
serde={version="=1.0.228",features=["rc"]}
serde_json={version="=1.0.149",features=["float_roundtrip"]}
sha2="=0.10.9"
pretty_assertions="=1.4.1"
[workspace.lints.rust]
[profile.release]
debug=0
incremental=false
codegen-units=1
lto="thin"
strip="symbols"
""")
        env = dict(
            os.environ,
            CARGO_HOME=str(cache),
            RUSTC=str(compiler / "rustc"),
            CARGO_NET_OFFLINE="true",
        )
        commands = []

        def command(arguments, log):
            value = [str(compiler / "cargo"), *arguments]
            result = subprocess.run(
                value, cwd=destination, env=env, capture_output=True, text=True
            )
            (destination / log).write_text(result.stdout + result.stderr)
            commands.append(
                {
                    "command": value,
                    "exit_code": result.returncode,
                    "log": log,
                    "log_sha256": sha(destination / log),
                }
            )
            if result.returncode:
                raise RuntimeError("isolated Cargo failed; preserved " + log)

        original_lock = tomllib.loads((ROOT / "codex-rs/Cargo.lock").read_text())[
            "package"
        ]
        by_name = {}
        for package in original_lock:
            by_name.setdefault(package["name"], []).append(package)
        registered = {
            (p["name"], p["version"], p.get("source"), p.get("checksum"))
            for p in original_lock
        }
        pending = [
            next(p for p in by_name[name] if p["version"] == version)
            for name, version in (
                ("ed25519-dalek", "2.2.0"),
                ("serde", "1.0.228"),
                ("serde_json", "1.0.149"),
                ("sha2", "0.10.9"),
                ("pretty_assertions", "1.4.1"),
            )
        ]
        closure = {}
        while pending:
            package = pending.pop()
            key = package["name"], package["version"]
            if key in closure:
                continue
            closure[key] = package
            for dependency in package.get("dependencies", []):
                parts = dependency.split()
                matches = by_name[parts[0]]
                if len(parts) > 1:
                    matches = [p for p in matches if p["version"] == parts[1]]
                if len(matches) != 1:
                    raise ValueError("Ambiguous frozen dependency: " + dependency)
                pending.extend(matches)
        vendor = destination / "vendor"
        vendor.mkdir()
        downloads = destination / "downloads"
        downloads.mkdir()
        original_vendor = (
            ROOT / "experiments/free_boundary_neuron/owner/runs/build01/vendor"
        )
        dependency_checks, download_bytes = [], 0
        for package in sorted(
            closure.values(), key=lambda p: (p["name"], p["version"])
        ):
            if not package.get("source"):
                continue
            name = package["name"] + "-" + package["version"]
            directory = vendor / name
            borrowed = original_vendor / name
            package_bytes = 0
            if borrowed.exists():
                checks = json.loads((borrowed / ".cargo-checksum.json").read_text())
                if checks["package"] != package["checksum"]:
                    raise ValueError("Borrowed package identity mismatch")
                for relative, value in checks["files"].items():
                    path = borrowed / relative
                    if (
                        path.is_symlink()
                        or not path.resolve().is_relative_to(borrowed.resolve())
                        or sha(path) != value
                    ):
                        raise ValueError("Borrowed dependency bytes changed")
                shutil.copytree(borrowed, directory)
                files = checks["files"]
                acquisition = "verified_preexisting_vendor_copy"
            else:
                candidates = list(
                    (cache / "registry/cache").glob("*/" + name + ".crate")
                )
                if not candidates:
                    target = downloads / (name + ".crate")
                    url = f"https://static.crates.io/crates/{package['name']}/{name}.crate"
                    with (
                        urllib.request.urlopen(url, timeout=60) as response,
                        target.open("xb") as output,
                    ):
                        shutil.copyfileobj(response, output)
                    download_bytes += target.stat().st_size
                    candidates = [target]
                    acquisition = "exact_frozen_checksum_download"
                else:
                    acquisition = "verified_preexisting_package_cache"
                if len(candidates) != 1 or sha(candidates[0]) != package["checksum"]:
                    raise ValueError(
                        "Cached/downloaded package checksum mismatch: " + name
                    )
                package_bytes = candidates[0].stat().st_size
                with tarfile.open(candidates[0], "r:gz") as source:
                    for entry in source.getmembers():
                        if not entry.isfile() and not entry.isdir():
                            raise ValueError("Unsupported dependency archive member")
                        if (
                            not Path(entry.name).is_relative_to(name)
                            or ".." in Path(entry.name).parts
                        ):
                            raise ValueError("Unsafe dependency archive name")
                    source.extractall(vendor, filter="data")
                files = {
                    str(p.relative_to(directory)): sha(p)
                    for p in directory.rglob("*")
                    if p.is_file()
                }
                (directory / ".cargo-checksum.json").write_text(
                    json.dumps({"package": package["checksum"], "files": files})
                )
            dependency_checks.append(
                {
                    "name": name,
                    "package_sha256": package["checksum"],
                    "package_bytes": package_bytes,
                    "verified_files": len(files),
                    "acquisition": acquisition,
                }
            )
        (destination / ".cargo").mkdir()
        (destination / ".cargo/config.toml").write_text(
            '[source.crates-io]\nreplace-with="vendor"\n[source.vendor]\ndirectory="vendor"\n'
        )
        env.update(
            CARGO_HOME=str(destination / "cargo-home"),
            SOURCE_DATE_EPOCH="0",
            CARGO_INCREMENTAL="0",
            RUSTFLAGS=f"--remap-path-prefix={destination}=/signed-credit-build --remap-path-prefix={ROOT}=/research-source",
        )
        command(["generate-lockfile", "--offline"], "resolve.log")
        resolved = tomllib.loads((destination / "Cargo.lock").read_text())["package"]
        if any(
            (p["name"], p["version"], p.get("source"), p.get("checksum"))
            not in registered
            for p in resolved
            if p.get("source")
        ):
            raise ValueError(
                "Private resolution drifted from frozen dependency closure"
            )
        command(
            [
                "build",
                "--offline",
                "--locked",
                "--release",
                "-j",
                "1",
                "-p",
                "hepta-research-signed-credit-bridge",
            ],
            "build.log",
        )
        binary = destination / "target/release/signed_credit_bridge"
        if (
            verify(source_seal) != protected
            or sha(ROOT / "codex-rs/Cargo.lock") != lock_before
            or (
                bridge_seal is not None
                and verify_source(bridge_seal, source_seal) != integration_source
            )
        ):
            raise ValueError("Protected scientific sources changed during bridge build")
        result = {
            "schema": "hepta.signed-credit-bridge.build.v1",
            "development_only": bridge_seal is None,
            "integration_source": integration_source,
            "complete": True,
            "source_sha256": identities,
            "protected_v2": protected,
            "scientific_lock_sha256": lock_before,
            "isolated_lock_sha256": sha(destination / "Cargo.lock"),
            "binary": str(binary),
            "binary_sha256": sha(binary),
            "binary_bytes": binary.stat().st_size,
            "compiler_sha256": sha(compiler / "rustc"),
            "compiler_version": subprocess.check_output(
                [str(compiler / "rustc"), "--version"], text=True
            ).strip(),
            "production_crates_unmodified": True,
            "outcome_adapter_unmodified": True,
            "qualified_legacy_write_enabled": False,
            "dependency_packages": dependency_checks,
            "commands": commands,
            "download_bytes": download_bytes,
        }
        write_json_exclusive(destination / "BUILD_RECEIPT.json", result)
        cost.update(
            binary_sha256=result["binary_sha256"],
            binary_bytes=result["binary_bytes"],
            production_source_inputs=len(identities),
            package_count=len(dependency_checks),
            build_receipt_sha256=sha(destination / "BUILD_RECEIPT.json"),
        )
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("destination", "compiler", "source-seal", "cache"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge-seal", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.destination,
                args.compiler,
                args.source_seal,
                args.cache,
                args.bridge_seal,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

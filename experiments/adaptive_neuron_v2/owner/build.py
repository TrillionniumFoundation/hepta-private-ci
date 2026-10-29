"""Measured, independently located builds of the original native-owner composition."""

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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def usage():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime, children.ru_utime + children.ru_stime


def required_source_paths(repository):
    paths = set()
    for name in ("hepta-types", "hepta-infer-core", "hepta-neuron"):
        paths.update(
            p
            for p in (repository / "codex-rs" / name).rglob("*")
            if p.is_file() and p.suffix in {".rs", ".toml"}
        )
    paths.update(Path(__file__).parent.glob("*.rs"))
    paths.update(
        repository / name
        for name in (
            "codex-rs/hepta-agentd/src/neuron_runtime.rs",
            "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
            "experiments/multimodal_output_portfolio/abc_next/native/measure.rs",
            "codex-rs/Cargo.lock",
            "experiments/adaptive_neuron_v2/owner/build.py",
        )
    )
    return sorted(paths)


def verify_build(receipt_path, binary, source_seal, verified_source=None):
    from experiments.adaptive_neuron_v2.provenance import verify

    source = verified_source or verify(source_seal)
    sealed = json.loads(Path(source_seal).read_text())["inputs"]
    receipt = json.loads(Path(receipt_path).read_text())
    repository = Path(__file__).resolve().parents[3]
    required = {
        str(p.relative_to(repository)) for p in required_source_paths(repository)
    }
    if (
        receipt.get("source") != source
        or receipt.get("development_only")
        or receipt.get("status") != "completed"
    ):
        raise ValueError(
            "Scientific execution requires a completed build made against this source seal"
        )
    if (
        receipt["binary_sha256"] != sha(binary)
        or receipt["binary_bytes"] != Path(binary).stat().st_size
    ):
        raise ValueError("Native executable differs from its measured build")
    if set(receipt["source_sha256"]) != required:
        raise ValueError("Native build input closure is incomplete or unexpected")
    if any(
        sealed.get(name, {}).get("sha256") != value
        for name, value in receipt["source_sha256"].items()
    ):
        raise ValueError("Native build inputs differ from the frozen source")
    if receipt["repository_lock_sha256"] != sealed["codex-rs/Cargo.lock"]["sha256"]:
        raise ValueError("Native dependency lock differs from the frozen source")
    return receipt


def build(
    repository, destination, compiler, vendor_root, reproducible=True, source_seal=None
):
    """Start accounting before validation, copying, vendor verification or Cargo."""
    started = time.perf_counter_ns()
    cpu_start, child_start = usage()
    receipt = {
        "schema": "hepta.adaptive-neuron.owner-build.v2",
        "timing_scope": "Input validation, source materialization, dependency checksum verification, borrowed vendor setup, Cargo and binary hash; excludes prior installation of the declared compiler and previously acquired immutable vendor cache.",
        "destination": str(destination),
        "reproducible": reproducible,
        "status": "started",
    }
    phases = []
    identities = {}
    created = False
    try:
        available = os.statvfs(destination.parent)
        physical_free = available.f_bfree * available.f_frsize
        receipt["physical_free_bytes_before"] = physical_free
        if physical_free < 256 * 1024 * 1024:
            raise OSError("Less than 256 MiB physical free space; build not started")
        destination.mkdir(parents=True, exist_ok=False)
        created = True
        if source_seal is not None:
            from experiments.adaptive_neuron_v2.provenance import verify

            receipt["source"] = verify(source_seal)
            sealed = json.loads(Path(source_seal).read_text())["inputs"]
            receipt["development_only"] = False
        else:
            receipt["source"] = {"development_only": True}
            receipt["development_only"] = True
            sealed = None
        phase = time.perf_counter_ns()
        for name in ("hepta-types", "hepta-infer-core", "hepta-neuron"):
            source = repository / "codex-rs" / name
            shutil.copytree(
                source, destination / name, ignore=shutil.ignore_patterns(".rsync-tmp")
            )
            identities.update(
                {
                    str(p.relative_to(repository)): sha(
                        destination / name / p.relative_to(source)
                    )
                    for p in source.rglob("*")
                    if p.is_file()
                    and p.suffix in {".rs", ".toml"}
                    and ".rsync-tmp" not in p.parts
                }
            )
        examples = destination / "hepta-neuron/examples"
        examples.mkdir(exist_ok=True)
        sources = {
            "original_owner.rs": repository
            / "codex-rs/hepta-agentd/src/neuron_runtime.rs",
            "original_credit.rs": repository
            / "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
            "measure.rs": repository
            / "experiments/multimodal_output_portfolio/abc_next/native/measure.rs",
        }
        sources.update({p.name: p for p in Path(__file__).parent.glob("*.rs")})
        for name, source in sources.items():
            if source.exists():
                data = source.read_bytes()
            else:
                data = subprocess.check_output(
                    ["git", "show", "HEAD:" + str(source.relative_to(repository))],
                    cwd=repository,
                )
            (examples / name).write_bytes(data)
            identities[str(source.relative_to(repository))] = hashlib.sha256(
                data
            ).hexdigest()
        identities["experiments/adaptive_neuron_v2/owner/build.py"] = sha(
            Path(__file__)
        )
        identities["codex-rs/Cargo.lock"] = sha(repository / "codex-rs/Cargo.lock")
        if set(identities) != {
            str(p.relative_to(repository)) for p in required_source_paths(repository)
        }:
            raise ValueError("Materialized native source closure changed")
        if sealed is not None and any(
            sealed.get(name, {}).get("sha256") != value
            for name, value in identities.items()
        ):
            raise ValueError("Materialized native inputs differ from the source seal")
        phases.append(
            {
                "phase": "source_materialization",
                "wall_ns": time.perf_counter_ns() - phase,
            }
        )
        phase = time.perf_counter_ns()
        packages = tomllib.loads((repository / "codex-rs/Cargo.lock").read_text())[
            "package"
        ]
        registry = {
            (p["name"], p["version"]): p.get("checksum")
            for p in packages
            if "source" in p
        }
        vendor_manifest = {}
        bytes_checked = 0
        for directory in sorted(vendor_root.iterdir()):
            checks = directory / ".cargo-checksum.json"
            if not checks.is_file():
                raise ValueError(
                    "Vendor entries must be immutable checked package directories"
                )
            info = json.loads(checks.read_text())
            package = tomllib.loads((directory / "Cargo.toml").read_text())["package"]
            if registry.get((package["name"], package["version"])) != info["package"]:
                raise ValueError("Vendor package differs from repository lock")
            for relative, expected in info["files"].items():
                path = directory / relative
                if (
                    path.is_symlink()
                    or not path.resolve().is_relative_to(directory.resolve())
                    or sha(path) != expected
                ):
                    raise ValueError("Vendor file checksum mismatch")
                bytes_checked += path.stat().st_size
            vendor_manifest[directory.name] = sha(checks)
        (destination / "vendor").symlink_to(
            vendor_root.resolve(), target_is_directory=True
        )
        (destination / ".cargo").mkdir()
        (destination / ".cargo/config.toml").write_text(
            '[source.crates-io]\nreplace-with="vendor"\n[source.vendor]\ndirectory="vendor"\n'
        )
        phases.append(
            {
                "phase": "borrowed_vendor_verification",
                "wall_ns": time.perf_counter_ns() - phase,
                "verified_file_bytes": bytes_checked,
                "download_bytes": 0,
                "package_manifests": vendor_manifest,
            }
        )
        (destination / "Cargo.toml").write_text("""[workspace]
members = ["hepta-types", "hepta-infer-core", "hepta-neuron"]
resolver = "2"
[workspace.package]
version = "0.0.0"
edition = "2024"
license = "Apache-2.0"
[workspace.dependencies]
serde = {version = "=1.0.228", features = ["rc"]}
serde_json = {version = "=1.0.149", features = ["float_roundtrip"]}
sha2 = "=0.10.9"
pretty_assertions = "=1.4.1"
[workspace.lints.rust]
[profile.release]
debug = 0
incremental = false
codegen-units = 1
lto = "thin"
strip = "symbols"
""")
        receipt["generated_workspace_manifest_sha256"] = sha(destination / "Cargo.toml")
        env = os.environ.copy()
        env.update(
            CARGO_HOME=str(destination / "cargo-home"),
            RUSTC=str(compiler / "rustc"),
            SOURCE_DATE_EPOCH="0",
            CARGO_INCREMENTAL="0",
        )
        if reproducible:
            env["RUSTFLAGS"] = " ".join(
                f"--remap-path-prefix={path}={name}"
                for path, name in [
                    (repository, "/research-source"),
                    (destination, "/research-build"),
                    (vendor_root, "/research-vendor"),
                ]
            )
        commands = []
        for args in (
            ["generate-lockfile", "--offline"],
            [
                "build",
                "--offline",
                "--locked",
                "--release",
                "-j",
                "1",
                "-p",
                "codex-hepta-neuron",
                "--example",
                "adaptive_neuron_host",
            ],
        ):
            command = [str(compiler / "cargo"), *args]
            phase = time.perf_counter_ns()
            result = subprocess.run(
                command, cwd=destination, env=env, capture_output=True, text=True
            )
            log_name = (
                "cargo-lock.log"
                if args[0] == "generate-lockfile"
                else "cargo-build.log"
            )
            (destination / log_name).write_text(result.stdout + result.stderr)
            commands.append(
                {
                    "command": command,
                    "exit_code": result.returncode,
                    "wall_ns": time.perf_counter_ns() - phase,
                    "log": log_name,
                    "log_sha256": sha(destination / log_name),
                }
            )
            receipt["commands"] = commands
            if result.returncode:
                raise RuntimeError(f"Cargo failed; preserved {destination / log_name}")
        resolved = tomllib.loads((destination / "Cargo.lock").read_text())["package"]

        def identity(p):
            return p["name"], p["version"], p.get("source"), p.get("checksum")

        if not {identity(p) for p in resolved} <= {identity(p) for p in packages}:
            raise ValueError("Dependency drift from repository lock")
        binary = destination / "target/release/examples/adaptive_neuron_host"
        receipt.update(
            status="completed",
            binary=str(binary),
            binary_sha256=sha(binary),
            binary_bytes=binary.stat().st_size,
            compiler_sha256=sha(compiler / "rustc"),
            compiler_version=subprocess.check_output(
                [str(compiler / "rustc"), "--version"], text=True
            ).strip(),
            lock_sha256=sha(destination / "Cargo.lock"),
            repository_lock_sha256=sha(repository / "codex-rs/Cargo.lock"),
            native_sources_unmodified=True,
            original_credit_module_unmodified=True,
            production_ledger_append=False,
            environment_overrides={
                k: env[k]
                for k in ("SOURCE_DATE_EPOCH", "CARGO_INCREMENTAL", "RUSTFLAGS")
                if k in env
            },
        )
    except Exception as error:
        receipt.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        own, child = usage()
        receipt.update(
            phases=phases,
            source_sha256=identities,
            total_wall_ns=time.perf_counter_ns() - started,
            parent_cpu_seconds=own - cpu_start,
            child_cpu_seconds=child - child_start,
        )
        serialized = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        if created:
            (destination / "BUILD_RECEIPT.json").write_text(serialized)
        else:
            failure = destination.parent / (destination.name + ".BUILD_FAILED.json")
            try:
                with failure.open("x") as output:
                    output.write(serialized)
            except OSError:
                print(serialized, flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--reproducible", action="store_true")
    parser.add_argument("--source-seal", type=Path)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    print(
        json.dumps(
            build(
                repository,
                args.destination.resolve(),
                args.compiler.resolve(),
                args.vendor_root.resolve(),
                args.reproducible,
                args.source_seal,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

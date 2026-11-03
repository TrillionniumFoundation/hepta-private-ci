#!/usr/bin/env python3
"""Replay exact product ZIP regressions with the vendored dependency.

This bounded native replay does not replace the complete core-plugins suite,
cross-platform CI, or encrypted and legacy compression fixture qualification.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import tomllib


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--minimum-free-mib", type=int, default=900)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if work.is_relative_to(repository):
        raise ValueError("Use a scratch directory outside the repository")
    if args.minimum_free_mib < 1:
        raise ValueError("minimum-free-mib must be positive")
    free_before = shutil.disk_usage(work).free
    if free_before < args.minimum_free_mib * 1024 * 1024:
        raise RuntimeError(
            f"Native replay requires at least {args.minimum_free_mib} MiB free"
        )
    source_path = repository / "codex-rs/core-plugins/src/startup_sync.rs"
    test_path = repository / "codex-rs/core-plugins/src/startup_sync_tests.rs"
    source = source_path.read_bytes()
    tests = test_path.read_bytes()
    start = source.index(b"fn extract_zipball_to_dir(")
    end = source.index(b"\n#[cfg(test)]", start)
    functions = source[start:end] + b"\n"
    start = tests.index(b"#[test]\nfn extract_zipball_preserves_compressed_payloads()")
    end = tests.index(b"#[tokio::test]", start)
    regression = tests[start:end]
    manifest_bytes = (repository / "codex-rs/Cargo.toml").read_bytes()
    lock_bytes = (repository / "codex-rs/Cargo.lock").read_bytes()
    manifest = tomllib.loads(manifest_bytes.decode())
    lock = tomllib.loads(lock_bytes.decode())
    zip_config = manifest["workspace"]["dependencies"]["zip"]
    vendor = repository / "codex-rs" / manifest["patch"]["crates-io"]["zip"]["path"]
    versions = {
        package["name"]: package["version"]
        for package in lock["package"]
        if package["name"] in {"zip", "tempfile", "pretty_assertions"}
    }
    crate = work / "crate"
    (crate / "src").mkdir(parents=True, exist_ok=True)
    (crate / "src/production.rs").write_bytes(functions)
    (crate / "src/regression.rs").write_bytes(regression)
    (crate / "src/lib.rs").write_text("""#[cfg(test)]
mod product_extraction_tests {
    use std::io::Write;
    use std::path::{Path, PathBuf};
    use pretty_assertions::assert_eq;
    use tempfile::tempdir;
    use zip::{ZipArchive, ZipWriter};
    use zip::write::SimpleFileOptions;
    include!("production.rs");
    include!("regression.rs");
}
""")
    (crate / "Cargo.toml").write_text(f"""[package]
name = "hepta-zip-feature-native-replay"
version = "0.0.0"
edition = "2024"
rust-version = "1.95"
publish = false

[workspace]
resolver = "3"

[dependencies]
zip = {{ version = "={versions["zip"]}", default-features = false, features = {json.dumps(zip_config["features"])} }}
tempfile = "={versions["tempfile"]}"
pretty_assertions = "={versions["pretty_assertions"]}"

[patch.crates-io]
zip = {{ path = {json.dumps(str(vendor))} }}
""")
    (crate / "Cargo.lock").write_bytes(lock_bytes)
    env = dict(os.environ)
    env.update(
        {
            "CARGO_TARGET_DIR": str(work / "target"),
            "CARGO_INCREMENTAL": "0",
            "CARGO_BUILD_JOBS": "1",
            "CARGO_PROFILE_DEV_DEBUG": "0",
            "CARGO_PROFILE_TEST_DEBUG": "0",
            "CARGO_TERM_COLOR": "never",
        }
    )
    vendor_inputs_before = {
        str(path.relative_to(vendor)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(vendor.rglob("*"))
        if path.is_file()
    }
    metadata_command = [
        args.cargo,
        "metadata",
        "--manifest-path",
        str(crate / "Cargo.toml"),
        "--format-version",
        "1",
    ]
    if args.offline:
        metadata_command.append("--offline")
    metadata = json.loads(subprocess.check_output(metadata_command, env=env))
    active_ids = {node["id"] for node in metadata["resolve"]["nodes"]}
    active = [
        package for package in metadata["packages"] if package["id"] in active_ids
    ]
    zip_packages = [package for package in active if package["name"] == "zip"]
    if (
        len(zip_packages) != 1
        or Path(zip_packages[0]["manifest_path"]) != vendor / "Cargo.toml"
    ):
        raise RuntimeError(
            "Native replay did not resolve the exact vendored ZIP source"
        )
    if any(package["name"] == "libbz2-rs-sys" for package in active):
        raise RuntimeError(
            "Native replay unexpectedly activates the Rust bzip2 backend"
        )
    command = [
        args.cargo,
        "test",
        "--manifest-path",
        str(crate / "Cargo.toml"),
        "--locked",
    ]
    if args.offline:
        command.append("--offline")
    command.extend(["--", "--nocapture"])
    log = work / "native.log"
    begin = time.monotonic()
    with log.open("w") as output:
        process = subprocess.run(
            command, cwd=crate, env=env, stdout=output, stderr=subprocess.STDOUT
        )
    log_text = log.read_text()
    vendor_inputs_after = {
        str(path.relative_to(vendor)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(vendor.rglob("*"))
        if path.is_file()
    }
    receipt = {
        "replay_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "command": command,
        "metadata_command": metadata_command,
        "exit_code": process.returncode,
        "elapsed_seconds": round(time.monotonic() - begin, 3),
        "resource_preflight": {
            "minimum_free_mib": args.minimum_free_mib,
            "free_before": free_before,
        },
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "exact_source_span_sha256": hashlib.sha256(functions).hexdigest(),
        "exact_regression_sha256": hashlib.sha256(regression).hexdigest(),
        "workspace_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "workspace_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "vendor_manifest_sha256": hashlib.sha256(
            (vendor / "Cargo.toml").read_bytes()
        ).hexdigest(),
        "vendor_inputs_before": vendor_inputs_before,
        "vendor_inputs_unchanged": vendor_inputs_before == vendor_inputs_after,
        "zip_configuration": zip_config,
        "zip_manifest_path": zip_packages[0]["manifest_path"],
        "active_libbz2_rs_sys": False,
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "format_cases": ["Stored", "Deflated", "Bzip2", "Zstd", "Xz"],
        "permission_case_count": 8,
        "passed": process.returncode == 0
        and "2 passed; 0 failed" in log_text
        and vendor_inputs_before == vendor_inputs_after,
        "scope": "Exact product functions and checked-in regressions, actual native build of the patched ZIP dependency; not full crate or cross-platform CI",
    }
    (work / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    print(log_text[-3500:])
    return process.returncode or (0 if receipt["passed"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())

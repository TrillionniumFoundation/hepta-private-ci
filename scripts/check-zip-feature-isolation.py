#!/usr/bin/env python3
"""Check ZIP backend isolation using Cargo's actual locked dependency graph."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=repository / "codex-rs/Cargo.toml"
    )
    parser.add_argument("--cargo", default=os.environ.get("CARGO", "cargo"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--check-deny", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    command = [
        args.cargo,
        "metadata",
        "--manifest-path",
        str(args.manifest.resolve()),
        "--all-features",
        "--locked",
        "--format-version",
        "1",
    ]
    if args.offline:
        command.append("--offline")
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.returncode:
        sys.stderr.write(process.stderr)
        return process.returncode
    metadata = json.loads(process.stdout)
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    selected = [
        {
            "name": packages[identifier]["name"],
            "version": packages[identifier]["version"],
            "features": node["features"],
            "dependencies": node["dependencies"],
            "source": packages[identifier]["source"],
        }
        for identifier, node in nodes.items()
        if packages[identifier]["name"]
        in {"zip", "bzip2", "bzip2-sys", "libbz2-rs-sys"}
    ]
    errors = []
    zip_packages = [package for package in selected if package["name"] == "zip"]
    bzip_packages = [package for package in selected if package["name"] == "bzip2"]
    if len(zip_packages) != 1 or len(bzip_packages) != 1:
        errors.append("Expected one active ZIP and one active bzip2 package")
    if any(package["name"] == "libbz2-rs-sys" for package in selected):
        errors.append("Unrequested Rust bzip2 backend remains Cargo-active")
    if not any(package["name"] == "bzip2-sys" for package in selected):
        errors.append("Required C bzip2 backend is missing")

    if len(zip_packages) == 1:
        features = set(zip_packages[0]["features"])
        retained = {
            "aes-crypto",
            "bzip2-rs",
            "deflate64",
            "deflate",
            "lzma",
            "time",
            "zstd",
            "xz",
        }
        if missing := retained - features:
            errors.append(f"Existing ZIP capabilities are missing: {sorted(missing)}")
        if "bzip2" in features:
            errors.append("ZIP's separate default bzip2 backend was activated")
    if len(bzip_packages) == 1 and set(bzip_packages[0]["features"]) != {"bzip2-sys"}:
        errors.append("bzip2 has features beyond the selected C backend")

    deny_receipt = None
    if args.check_deny:
        deny_command = [
            args.cargo,
            "deny",
            "--manifest-path",
            str(args.manifest.resolve()),
            "--all-features",
            "--locked",
            "list",
            "--config",
            str(repository / "codex-rs/deny.toml"),
            "--format",
            "json",
            "--layout",
            "crate",
        ]
        deny_env = dict(os.environ)
        if args.offline:
            deny_env["CARGO_NET_OFFLINE"] = "true"
        deny = subprocess.run(
            deny_command, capture_output=True, text=True, env=deny_env
        )
        deny_receipt = {
            "command": deny_command,
            "exit_code": deny.returncode,
            "stdout_sha256": hashlib.sha256(deny.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(deny.stderr.encode()).hexdigest(),
        }
        if deny.returncode:
            errors.append("cargo-deny license listing failed")
            sys.stderr.write(deny.stderr)
        else:
            license_list = json.loads(deny.stdout)
            critical_names = {"zip", "bzip2", "bzip2-sys", "libbz2-rs-sys"}
            listed = {
                tuple(identifier.split(" ", 2)[:2])
                for identifier in license_list
                if identifier.split(" ", 1)[0] in critical_names
            }
            expected = {(package["name"], package["version"]) for package in selected}
            deny_receipt["selected_packages"] = sorted(listed)
            if listed != expected:
                errors.append(
                    "cargo-deny ZIP/bzip2 coverage differs from actual Cargo resolution"
                )

    receipt = {
        "command": command,
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "metadata_sha256": hashlib.sha256(process.stdout.encode()).hexdigest(),
        "active_packages": selected,
        "deny_license_graph": deny_receipt,
        "errors": errors,
        "passed": not errors,
        "scope": "Locked Cargo feature resolution and optional cargo-deny package coverage; no Bazel or full CI claim",
    }
    encoded = json.dumps(receipt, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    sys.stdout.write(encoded)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

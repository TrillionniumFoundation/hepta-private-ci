#!/usr/bin/env python3
"""Run six focused tests against exact copies of the reviewed vendor sources.

The independent workspace retains the normalized vendor manifests and all Rust
source bytes. Only its root workspace/patch manifest and nextest configuration
are generated. Its lock starts from the consumer lock and is resolved separately.
These results do not replace compilation or tests of the root consumers.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET


VENDORS = {
    "aws-config": "aws-config-1.8.12",
    "matrix-sdk": "matrix-sdk-0.19.1",
    "matrix-sdk-sqlite": "matrix-sdk-sqlite-0.19.1",
    "i18n-config": "i18n-config-0.4.8",
    "starlark": "starlark-0.14.2",
    "zip": "zip-9.1.3",
}
TESTS = {
    "aws-config": [
        "login::dpop::compatibility_tests::dpop_proof_preserves_es256_header_payload_and_signature",
    ],
    "matrix-sdk": [
        "event_handler::compatibility_tests::event_context_clone_preserves_type_isolation_and_send_sync",
    ],
    "i18n-config": [
        "compatibility_tests::public_crate_loader_preserves_package_and_language_config",
        "compatibility_tests::public_config_loader_preserves_defaults_and_unicode",
        "compatibility_tests::public_parse_errors_keep_path_and_diagnostic",
    ],
    "starlark": [
        "pagable::heap_ref_id::compatibility_tests::blake3_adapter_preserves_known_digest_and_chunked_writes",
    ],
}
FEATURE_ARGS = {
    "aws-config": ["--features", "credentials-login"],
    "matrix-sdk": ["--no-default-features", "--features", "e2e-encryption,sqlite"],
    "i18n-config": [],
    "starlark": [],
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def inventory(directory):
    result = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"unexpected symlink in vendor source: {path}")
        if path.is_file():
            result.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": digest(path),
                }
            )
    return result


def verify_identity(source, copied):
    original = inventory(source)
    if original != inventory(copied):
        raise ValueError(f"copied vendor source differs: {source.name}")
    return original


def workspace_manifest():
    members = [f"vendors/{VENDORS[name]}" for name in TESTS]
    excluded = [f"vendors/{VENDORS[name]}" for name in VENDORS if name not in TESTS]
    lines = [
        "[workspace]",
        'resolver = "2"',
        f"members = {json.dumps(members)}",
        f"exclude = {json.dumps(excluded)}",
        "",
        "[patch.crates-io]",
    ]
    lines.extend(
        f'{name} = {{ path = "vendors/{directory}" }}'
        for name, directory in VENDORS.items()
    )
    return "\n".join(lines) + "\n"


def prepare_workspace(repo, work, output):
    if work.exists() and any(work.iterdir()):
        raise ValueError(
            "work directory must be new or empty; use a new path for a new attempt"
        )
    work.mkdir(parents=True, exist_ok=True)
    records = {}
    for name, directory in VENDORS.items():
        source = repo / "codex-rs/third_party" / directory
        if not (source / "HEPTA_SOURCE.json").is_file():
            raise ValueError(f"missing reviewed vendor provenance: {directory}")
        copied = work / "vendors" / directory
        shutil.copytree(source, copied)
        rows = verify_identity(source, copied)
        write_json(output / f"{directory}.source.json", rows)
        manifest = tomllib.loads((copied / "Cargo.toml").read_text())
        if manifest["package"]["name"] != name:
            raise ValueError(f"unexpected normalized package identity: {directory}")
        records[name] = {
            "directory": directory,
            "files": len(rows),
            "source_inventory": f"{directory}.source.json",
            "source_manifest_sha256": digest(source / "Cargo.toml"),
            "copied_manifest_sha256": digest(copied / "Cargo.toml"),
            "manifest_transformation": "none; only the independent workspace root is generated",
        }
    (work / "Cargo.toml").write_text(workspace_manifest())
    shutil.copy2(work / "Cargo.toml", output / "isolated.Cargo.toml")
    shutil.copy2(repo / "codex-rs/Cargo.lock", work / "Cargo.lock")
    config = work / ".config/nextest.toml"
    config.parent.mkdir()
    config.write_text(
        "[profile.default]\nretries = 0\n"
        'slow-timeout = { period = "60s", terminate-after = 3 }\n'
        "[profile.local]\nretries = 0\n"
        '[profile.local.junit]\npath = "junit.xml"\n'
    )
    shutil.copy2(config, output / "nextest.toml")
    return records


def validate_junit(path, expected):
    tree = ET.parse(path)
    cases = list(tree.iter("testcase"))
    observed = [case.get("name", "") for case in cases]
    if sorted(observed) != sorted(expected):
        raise ValueError(
            f"JUnit test identities differ: expected {expected}, observed {observed}"
        )
    bad = [
        case.get("name")
        for case in cases
        if any(case.find(tag) is not None for tag in ("skipped", "error", "failure"))
    ]
    if bad:
        raise ValueError(f"focused tests failed or skipped: {bad}")
    return {"tests": len(cases), "passed": len(cases), "skipped": 0, "names": observed}


def run_logged(command, label, cwd, output, env):
    log = output / f"{label}.log"
    started = time.monotonic()
    with log.open("wb") as stream:
        process = subprocess.run(
            command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT
        )
    data = log.read_bytes()
    compressed = output / f"{label}.log.gz"
    compressed.write_bytes(gzip.compress(data, mtime=0))
    log.unlink()
    result = {
        "command": command,
        "cwd": str(cwd),
        "exit_code": process.returncode,
        "seconds": time.monotonic() - started,
        "log": compressed.name,
        "log_uncompressed_bytes": len(data),
        "log_uncompressed_sha256": hashlib.sha256(data).hexdigest(),
        "log_gzip_sha256": digest(compressed),
    }
    write_json(output / f"{label}.json", result)
    print(json.dumps({"step": label, "exit_code": process.returncode}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    repo, work, output = args.repo.resolve(), args.work.resolve(), args.output.resolve()
    if work == output or output.is_relative_to(work):
        raise ValueError("output must be separate from the disposable build workspace")
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "hepta.vendor-compatibility.v2",
        "repo": str(repo),
        "work": str(work),
        "status": "preparing",
        "expected_tests": TESTS,
        "feature_arguments": FEATURE_ARGS,
        "root_lock_before_sha256": digest(repo / "codex-rs/Cargo.lock"),
        "entrypoint_sha256": digest(repo / "justfile"),
        "nextest_wrapper_sha256": digest(repo / "scripts/run-nextest.py"),
        "helper_sha256": digest(Path(__file__)),
        "scope": "Independent exact-source vendor tests; root consumer compilation and behavior require separate evidence.",
        "commands": [],
    }
    receipt_path = output / "RECEIPT.json"
    write_json(receipt_path, receipt)
    try:
        receipt["vendors"] = prepare_workspace(repo, work, output)
        if args.prepare_only:
            receipt["status"] = "prepared_only; no tests executed"
            return 0
        env = os.environ.copy()
        env.update(
            CARGO_TARGET_DIR=str(work / "target"),
            CARGO_PROFILE_DEV_DEBUG="0",
            CARGO_PROFILE_TEST_DEBUG="0",
            CARGO_INCREMENTAL="0",
        )
        env.setdefault("CARGO_BUILD_JOBS", "2")
        lock = run_logged(
            [
                "cargo",
                "update",
                "--workspace",
                "--manifest-path",
                str(work / "Cargo.toml"),
            ],
            "resolve",
            work,
            output,
            env,
        )
        receipt["commands"].append(lock)
        if lock["exit_code"]:
            raise RuntimeError(
                "independent dependency resolution failed; see resolve.log.gz"
            )
        (output / "isolated.Cargo.lock.gz").write_bytes(
            gzip.compress((work / "Cargo.lock").read_bytes(), mtime=0)
        )
        receipt["isolated_lock_sha256"] = digest(work / "Cargo.lock")
        metadata_command = [
            "cargo",
            "metadata",
            "--no-deps",
            "--format-version=1",
            "--locked",
            "--manifest-path",
            str(work / "Cargo.toml"),
        ]
        with (
            (output / "metadata.json").open("wb") as stdout,
            (output / "metadata.stderr.log").open("wb") as stderr,
        ):
            metadata = subprocess.run(
                metadata_command, cwd=work, env=env, stdout=stdout, stderr=stderr
            )
        if metadata.returncode:
            raise RuntimeError("independent metadata failed")
        failures = []
        passed = 0
        for name, expected in TESTS.items():
            junit = work / "target/nextest/local/junit.xml"
            junit.unlink(missing_ok=True)
            expression = " | ".join(f"test(={test})" for test in expected)
            command = [
                "just",
                "--justfile",
                str(repo / "justfile"),
                "test",
                "--manifest-path",
                str(work / "Cargo.toml"),
                "-p",
                name,
                "--lib",
                "--locked",
                *FEATURE_ARGS[name],
                "-E",
                expression,
            ]
            result = run_logged(command, name, repo, output, env)
            receipt["commands"].append(result)
            if result["exit_code"]:
                failures.append(f"{name}: command exited {result['exit_code']}")
            try:
                shutil.copy2(junit, output / f"{name}.junit.xml")
                result["junit"] = validate_junit(output / f"{name}.junit.xml", expected)
                passed += result["junit"]["passed"]
            except (OSError, ValueError, ET.ParseError) as error:
                failures.append(f"{name}: {error}")
            write_json(receipt_path, receipt)
        for name, directory in VENDORS.items():
            verify_identity(
                repo / "codex-rs/third_party" / directory, work / "vendors" / directory
            )
        if digest(work / "Cargo.lock") != receipt["isolated_lock_sha256"]:
            failures.append("isolated lock changed during locked tests")
        receipt.update(passed=passed, failures=failures)
        if failures or passed != 6:
            raise RuntimeError(
                "six exact focused tests did not all pass; see individual receipts"
            )
        receipt["status"] = "passed: six focused tests, zero skipped"
        return 0
    except Exception as error:
        receipt.update(status="failed", error=f"{type(error).__name__}: {error}")
        print(receipt["error"], file=sys.stderr)
        return 1
    finally:
        receipt["root_lock_after_sha256"] = digest(repo / "codex-rs/Cargo.lock")
        if receipt["root_lock_after_sha256"] != receipt["root_lock_before_sha256"]:
            receipt["root_lock_changed_externally"] = True
        write_json(receipt_path, receipt)


if __name__ == "__main__":
    raise SystemExit(main())

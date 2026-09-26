#!/usr/bin/env python3
"""Execute independent Supervisor checks; never turn metadata or skips into pass.

Outputs stay outside the checkout. Every command is tied to this committed
source identity, logs its real exit code, and retains earlier failures. Physical
fixture load and real Agentd lifecycle are separate, explicitly named checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "codex-hepta-supervisor"
QUALIFIED_ARTIFACTS = (
    "hepta-supervisord",
    "hepta-supervisor-release-controller",
    "hepta-authority-signer",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_qualified_artifacts(
    *,
    target: Path,
    output: Path,
    source_commit: str,
    source_tree: str,
    host_platform: str,
) -> dict[str, Any]:
    frozen = output / "qualified-artifacts"
    frozen.mkdir()
    artifacts: list[dict[str, Any]] = []
    for name in QUALIFIED_ARTIFACTS:
        source = target / "debug" / name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"qualified artifact is not a regular file: {source}")
        destination = frozen / name
        shutil.copyfile(source, destination)
        destination.chmod(0o500)
        source_digest = sha256_file(source)
        frozen_digest = sha256_file(destination)
        if source_digest != frozen_digest:
            raise ValueError(f"qualified artifact copy changed bytes: {name}")
        artifacts.append(
            {
                "name": name,
                "relative_path": f"qualified-artifacts/{name}",
                "sha256": frozen_digest,
                "size_bytes": destination.stat().st_size,
                "source_mode_octal": oct(source.stat().st_mode & 0o777),
            }
        )
    manifest = {
        "schema": "hepta.runtime-supervisor.qualified-artifacts.v1",
        "schema_version": 1,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "host_platform": host_platform,
        "artifacts": artifacts,
        "deployment_qualified": False,
        "independent_acceptance": False,
    }
    (output / "qualified-artifacts.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--host-instances", type=int, choices=(8, 64, 256), default=256)
    parser.add_argument("--command-timeout", type=int, default=1800)
    args = parser.parse_args()
    output = args.out.resolve()
    if output.is_relative_to(ROOT) or output.exists():
        parser.error("--out must be a new directory outside the checkout")
    if args.command_timeout < 1 or args.command_timeout > 7200:
        parser.error("command timeout must be in 1..7200 seconds")
    source = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    if source != args.expected_sha or git("status", "--porcelain"):
        parser.error("verification requires the exact expected committed, clean candidate")
    system = platform.system().lower()
    if system not in {"linux", "darwin"}:
        parser.error(f"Supervisor host qualification does not support {system}")
    output.mkdir(parents=True)
    env = os.environ.copy()
    target = Path(env.get("CARGO_TARGET_DIR", str(output / "target"))).resolve()
    if target.is_relative_to(ROOT):
        parser.error("CARGO_TARGET_DIR must be outside the source checkout")
    env["CARGO_TARGET_DIR"] = str(target)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("CARGO_BUILD_JOBS", "2")
    env.setdefault("CARGO_PROFILE_DEV_DEBUG", "0")
    env.setdefault("CARGO_PROFILE_TEST_DEBUG", "0")
    # Qualification must not consume the operator's model credentials.
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
        env.pop(name, None)
    manifest = "Cargo.toml"
    tests = [
        "just",
        "test",
        "--locked",
        "-p",
        PACKAGE,
        "--retries",
        "0",
        "--test-threads",
        "2",
    ]
    checks: list[tuple[str, list[str], dict[str, str], tuple[str, ...]]] = [
        ("default-library", [*tests, "--lib"], {}, ()),
        (
            "production-authority-package",
            [
                *tests,
                "--features",
                "production-authority",
                "--success-output",
                "immediate",
            ],
            {},
            (),
        ),
        (
            "implementation-maps",
            [
                "python3",
                "scripts/hepta-implementation-maps.py",
                "verify",
                "--expected-sha",
                source,
            ],
            {},
            (),
        ),
        (
            "format",
            [
                "cargo",
                "fmt",
                "--manifest-path",
                manifest,
                "-p",
                PACKAGE,
                "--",
                "--check",
            ],
            {},
            (),
        ),
        (
            "strict-clippy",
            [
                "cargo",
                "clippy",
                "--manifest-path",
                manifest,
                "--locked",
                "-p",
                PACKAGE,
                "--all-targets",
                "--features",
                "production-authority",
                "--",
                "-D",
                "warnings",
            ],
            {},
            (),
        ),
        (
            "real-agentd-build",
            [
                "cargo",
                "build",
                "--manifest-path",
                manifest,
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--bin",
                "codex-hepta-agentd",
            ],
            {},
            (),
        ),
        (
            "real-agentd-signed-lifecycle",
            [
                *tests,
                "--features",
                "production-authority",
                "--test",
                "production_release_product",
                "--success-output",
                "immediate",
                "external_signer_caller_and_supervisor_recover_without_replay",
            ],
            {"HEPTA_SUPERVISOR_QUAL_AGENTD": str(target / "debug/codex-hepta-agentd")},
            ("real-agentd-build",),
        ),
        (
            "host-fixture-build",
            [
                "cargo",
                "build",
                "--manifest-path",
                manifest,
                "--locked",
                "-p",
                PACKAGE,
                "--features",
                "production-authority",
                "--bins",
                "--example",
                "supervisor_host_qualification",
            ],
            {},
            (),
        ),
    ]
    host_dependencies = ("qualified-artifact-freeze",)
    host_environment: dict[str, str] = {}
    if system == "linux":
        checks.append(
            (
                "io-fault-interposer-build",
                [
                    "cc",
                    "-shared",
                    "-fPIC",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
                    "codex-rs/hepta-supervisor/tests/support/io_fault.c",
                    "-ldl",
                    "-o",
                    str(output / "io-fault.so"),
                ],
                {},
                (),
            )
        )
        host_dependencies = (
            "qualified-artifact-freeze",
            "io-fault-interposer-build",
        )
        host_environment = {
            "HEPTA_SUPERVISOR_QUAL_PRELOAD": str(output / "io-fault.so")
        }
    host_name = f"native-process-host-{system}-{args.host_instances}"
    checks.extend(
        [
            (
                host_name,
                [
                    str(target / "debug/examples/supervisor_host_qualification"),
                    str(target / "debug/hepta-supervisord"),
                    str(output / "physical-host.json"),
                    str(args.host_instances),
                ],
                host_environment,
                host_dependencies,
            ),
            (
                "physical-host-receipt-policy",
                [
                    "python3",
                    "scripts/hepta-supervisor-receipt-gate.py",
                    "--receipt",
                    str(output / "physical-host.json"),
                    "--out",
                    str(output / "physical-host-policy.json"),
                    "--expected-sha",
                    source,
                    "--platform",
                    system,
                    "--instances",
                    str(args.host_instances),
                    "--p99-limit-ms",
                    "1000",
                    "--max-limit-ms",
                    "2000",
                ],
                {},
                (host_name,),
            ),
        ]
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "source_commit": source,
        "source_tree": source_tree,
        "parents": git("show", "-s", "--format=%P", "HEAD").split(),
        "host_platform": system,
        "host_instances": args.host_instances,
        "deployment_qualified": False,
        "independent_acceptance": False,
        "checks": [],
        "status": "running",
    }
    statuses: dict[str, bool] = {}

    def save() -> None:
        staging = output / ".result.tmp"
        staging.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        staging.replace(output / "result.json")

    def record_artifact_freeze() -> None:
        item: dict[str, Any] = {
            "name": "qualified-artifact-freeze",
            "command": ["internal", "freeze-qualified-artifacts"],
            "status": "running",
            "exit_code": None,
        }
        report["checks"].append(item)
        started = time.monotonic()
        if not statuses.get("host-fixture-build", False):
            item.update(status="blocked", error="host fixture build did not pass")
            statuses["qualified-artifact-freeze"] = False
        else:
            try:
                frozen_manifest = freeze_qualified_artifacts(
                    target=target,
                    output=output,
                    source_commit=source,
                    source_tree=source_tree,
                    host_platform=system,
                )
                report["qualified_artifacts"] = frozen_manifest
                item.update(status="passed", exit_code=0)
                statuses["qualified-artifact-freeze"] = True
            except (OSError, ValueError) as error:
                item.update(status="failed", error=str(error), exit_code=1)
                statuses["qualified-artifact-freeze"] = False
        item["elapsed_seconds"] = time.monotonic() - started
        save()
        print(f"qualified-artifact-freeze: {item['status']}", flush=True)

    save()
    for name, command, overrides, dependencies in checks:
        item = {
            "name": name,
            "command": command,
            "status": "running",
            "exit_code": None,
        }
        report["checks"].append(item)
        if any(not statuses.get(dependency, False) for dependency in dependencies):
            item.update(status="blocked", error="prerequisite build did not pass")
            statuses[name] = False
            save()
            if name == "host-fixture-build":
                record_artifact_freeze()
            continue
        save()
        started = time.monotonic()
        try:
            with (output / f"{name}.log").open("xb") as log:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT / "codex-rs" if command[0] == "cargo" else ROOT,
                    env=env | overrides,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    code = process.wait(timeout=args.command_timeout)
                except subprocess.TimeoutExpired:
                    # A deadline miss is a failed qualification even if the
                    # overloaded command later exits successfully. Retain its
                    # eventual exit and fixture-owned cleanup in the receipt.
                    item["deadline_exceeded"] = True
                    save()
                    code = process.wait()
                passed = code == 0 and not item.get("deadline_exceeded", False)
                item.update(exit_code=code, status="passed" if passed else "failed")
                statuses[name] = passed
        except (OSError, subprocess.TimeoutExpired) as error:
            item.update(status="failed", error=str(error))
            statuses[name] = False
        finally:
            item["elapsed_seconds"] = time.monotonic() - started
            save()
        print(f"{name}: {item['status']}", flush=True)
        if name == "host-fixture-build":
            record_artifact_freeze()
    report["source_still_clean"] = (
        git("rev-parse", "HEAD") == source and not git("status", "--porcelain")
    )
    passed = all(statuses.values()) and report["source_still_clean"]
    report["status"] = "passed" if passed else "failed"
    save()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

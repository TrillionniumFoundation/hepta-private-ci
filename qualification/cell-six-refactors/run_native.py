#!/usr/bin/env python3
"""Record scoped native gates against one clean, immutable source commit."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


PACKAGES = (
    "codex-hepta-neuron",
    "codex-hepta-agentd",
    "codex-hepta-infer-worker-host",
    "codex-hepta-infer-core",
)
CHANGED_PACKAGES = PACKAGES[:3]


def file_identity(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("lint", "test", "all"), default="all")
    parser.add_argument("--test-threads", type=int, default=2, choices=range(1, 9))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    workspace = root / "codex-rs"
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "status.json").exists():
        parser.error(
            "evidence directory already exists; retain it and use a new directory"
        )
    status = {
        "schema": "hepta.cell-six-refactors.native-gate.v1",
        "source_sha": args.source_sha,
        "source_tree": None,
        "mode": args.mode,
        "started_unix_ns": time.time_ns(),
        "state": "running",
        "phases": [],
        "packages": list(PACKAGES),
        "whole_workspace_tested": False,
        "qualification_authority": "DENY_ALL",
    }

    def save():
        temporary = output / "status.json.tmp"
        temporary.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / "status.json")

    def git(*command):
        return subprocess.check_output(["git", *command], cwd=root, text=True).strip()

    def source_is_frozen():
        if git("rev-parse", "HEAD") != args.source_sha:
            raise RuntimeError(
                "source commit differs from the requested immutable source"
            )
        changes = git("status", "--porcelain=v1", "--untracked-files=all")
        if changes:
            (output / "source-changes.txt").write_text(changes + "\n", encoding="utf-8")
            with (output / "source-changes.patch").open("wb") as patch:
                subprocess.run(
                    ["git", "diff", "--binary", "HEAD"],
                    cwd=root,
                    stdout=patch,
                    check=True,
                )
            raise RuntimeError(
                "source changed; review and commit before running further gates"
            )

    def run(name, command, environment=None):
        source_is_frozen()
        log = output / f"{name}.log"
        phase = {"name": name, "command": command, "started_unix_ns": time.time_ns()}
        status["phases"].append(phase)
        save()
        print(f"Starting {name}", flush=True)
        with log.open("xb") as stream:
            result = subprocess.run(
                command,
                cwd=workspace,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        phase.update(
            exit_code=result.returncode,
            ended_unix_ns=time.time_ns(),
            log=file_identity(log),
        )
        save()
        source_is_frozen()
        print(f"Finished {name}: {result.returncode}", flush=True)
        return result.returncode

    def package_arguments(packages):
        return [item for package in packages for item in ("-p", package)]

    save()
    result = 1
    try:
        source_is_frozen()
        status["source_tree"] = git("rev-parse", "HEAD^{tree}")
        status["platform"] = list(os.uname())
        status["initial_free_bytes"] = shutil.disk_usage(output).free
        for name, command in (
            ("rustc", ["rustc", "--version", "--verbose"]),
            ("cargo", ["cargo", "--version"]),
            ("nextest", ["cargo", "nextest", "--version"]),
        ):
            status[name] = subprocess.check_output(
                command, cwd=workspace, text=True
            ).strip()
        if args.mode in ("lint", "all"):
            result = run(
                "scoped-fix",
                ["just", "fix", "--locked", *package_arguments(CHANGED_PACKAGES)],
            )
            if result:
                raise RuntimeError("scoped fix failed")
        if args.mode in ("test", "all"):
            result = run(
                "scoped-strict",
                [
                    "cargo",
                    "clippy",
                    "--locked",
                    "--tests",
                    *package_arguments(CHANGED_PACKAGES),
                    "--",
                    "-D",
                    "warnings",
                ],
            )
            if result:
                raise RuntimeError("strict scoped clippy failed")
            helpers = output / "helpers"
            result = run(
                "helpers",
                [
                    sys.executable,
                    str(root / "scripts/hepta_cell_test_helpers.py"),
                    "--output-dir",
                    str(helpers),
                ],
            )
            if result:
                raise RuntimeError("actual Cargo helper builds failed")
            manifest = json.loads((helpers / "manifest.json").read_text())
            if manifest.get("source_sha") != args.source_sha or not manifest.get(
                "complete"
            ):
                raise RuntimeError("helper evidence does not match this source")
            environment = os.environ.copy()
            environment.update(json.loads((helpers / "env.json").read_text()))
            result = run(
                "scoped-test",
                [
                    "just",
                    "test",
                    "--locked",
                    *package_arguments(PACKAGES),
                    "--test-threads",
                    str(args.test_threads),
                ],
                environment,
            )
            target = Path(environment.get("CARGO_TARGET_DIR", workspace / "target"))
            # Nextest's store can remain workspace-relative even when Cargo's
            # build artifacts use CARGO_TARGET_DIR. Require a fresh report from
            # this test invocation, never an earlier report in the shared cache.
            test_started = status["phases"][-1]["started_unix_ns"]
            candidates = {
                (workspace / "target/nextest/local/junit.xml").resolve(),
                (target / "nextest/local/junit.xml").resolve(),
            }
            fresh = [
                path
                for path in sorted(candidates)
                if path.is_file() and path.stat().st_mtime_ns >= test_started
            ]
            status["junit_candidates"] = [
                {"path": str(path), "exists": path.is_file(), "fresh": path in fresh}
                for path in sorted(candidates)
            ]
            if fresh:
                if len({file_identity(path)["sha256"] for path in fresh}) != 1:
                    raise RuntimeError("ambiguous fresh JUnit reports")
                junit = fresh[0]
                copied = output / "junit.xml"
                shutil.copyfile(junit, copied)
                cases = list(ET.parse(copied).iter("testcase"))
                status["junit"] = {
                    **file_identity(copied),
                    "source_path": str(junit),
                    "cases": len(cases),
                    "failures": sum(case.find("failure") is not None for case in cases),
                    "errors": sum(case.find("error") is not None for case in cases),
                    "skipped": sum(case.find("skipped") is not None for case in cases),
                }
            status["helper_artifacts_after_test"] = {
                name: file_identity(Path(artifact["executable"]))
                for name, artifact in manifest["artifacts"].items()
            }
            status["helper_artifacts_unchanged"] = all(
                all(
                    status["helper_artifacts_after_test"][name][key] == artifact[key]
                    for key in ("bytes", "sha256")
                )
                for name, artifact in manifest["artifacts"].items()
            )
            if result:
                raise RuntimeError(
                    "scoped native tests failed; retain full logs and individual failures"
                )
            if not fresh or not status["junit"]["cases"]:
                raise RuntimeError(
                    "successful exit without a fresh nonempty JUnit report"
                )
            if status["junit"]["failures"] or status["junit"]["errors"]:
                raise RuntimeError("successful exit conflicts with JUnit failures")
            if not status["helper_artifacts_unchanged"]:
                raise RuntimeError("helper executable changed during native tests")
        source_is_frozen()
        status["state"] = "passed"
        result = 0
    except Exception as error:
        status.update(state="failed", error=f"{type(error).__name__}: {error}")
        result = result or 1
    finally:
        status.update(
            exit_code=result,
            ended_unix_ns=time.time_ns(),
            final_free_bytes=shutil.disk_usage(output).free,
        )
        save()
    print(
        json.dumps(
            {
                "state": status["state"],
                "exit_code": result,
                "status": str(output / "status.json"),
            }
        ),
        flush=True,
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only qualification of an exact objective source and deterministic merge.

The output directory must be outside the repository. Every executed command has
an exit status and a content digest. Missing or interrupted checks cannot pass.
This report is execution evidence, not independent acceptance or activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time

SHA = re.compile(r"[0-9a-f]{40}\Z")
PACKAGES = (
    "codex-hepta-objective",
    "codex-hepta-learning-ledger",
    "codex-hepta-intelligence",
    "codex-hepta-agentd",
)


def git(root: Path, *args: str, env=None) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, env=env
    ).strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def write_report(out: Path, report: dict) -> None:
    temp = out / ".receipt.json.tmp"
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temp.replace(out / "receipt.json")


def run_command(
    cwd: Path, out: Path, name: str, argv: list[str], timeout: int
) -> dict:
    path = out / f"{name}.log"
    started = time.time_ns()
    mono = time.monotonic_ns()
    status = "completed"
    with path.open("wb") as stream:
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                import signal

                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                stream.write(b"\nqualification command timed out\n")
                code, status = 124, "timed_out"
        except OSError as error:
            stream.write(f"{type(error).__name__}: {error}\n".encode())
            code, status = 127, "unavailable"
    return {
        "name": name,
        "argv": argv,
        "cwd": str(cwd),
        "startedUnixNs": started,
        "elapsedNs": time.monotonic_ns() - mono,
        "status": status,
        "exitCode": code,
        "log": path.name,
        "logSha256": digest(path),
    }


def commands(commit: str, tree: str) -> list[tuple[str, list[str]]]:
    crates = [item for package in PACKAGES for item in ("-p", package)]
    owned_all_target_packages = (PACKAGES[0], PACKAGES[1], PACKAGES[3])
    owned_all_target_crates = [
        item for package in owned_all_target_packages for item in ("-p", package)
    ]
    return [
        ("rust-toolchain", ["rustc", "--version", "--verbose"]),
        ("cargo-toolchain", ["cargo", "--version", "--verbose"]),
        (
            "implementation-map",
            [
                "python3",
                "../scripts/hepta-implementation-maps.py",
                "verify",
                "--module",
                "objective.compiler",
                "--expected-sha",
                commit,
                "--expected-tree",
                tree,
            ],
        ),
        (
            "current-state",
            ["python3", "../scripts/hepta-objective-current-state.py", "verify"],
        ),
        (
            "normative-consistency",
            ["python3", "../scripts/hepta-objective-spec-consistency.py", "verify"],
        ),
        (
            "release-source-truth",
            ["python3", "../scripts/hepta-objective-release-gate.py", "verify-source"],
        ),
        ("format", ["cargo", "fmt", *crates, "--", "--check"]),
        (
            "all-targets",
            ["cargo", "check", "--locked", *crates, "--all-targets"],
        ),
        (
            "objective-default",
            ["cargo", "test", "--locked", "-p", PACKAGES[0]],
        ),
        (
            "objective-compatibility",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                PACKAGES[0],
                "--features",
                "qualification-legacy-compile",
            ],
        ),
        (
            "durable-run-start",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                PACKAGES[1],
                "--lib",
                "run_start",
            ],
        ),
        (
            "publication",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                PACKAGES[2],
                "--lib",
                "objective_run",
            ],
        ),
        (
            "agentd-objective",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                PACKAGES[3],
                "--lib",
                "objective_runtime",
            ],
        ),
        (
            "agentd-checkpoint",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                PACKAGES[3],
                "--lib",
                "objective_run_start_checkpoint",
            ],
        ),
        (
            "agentd-product-e2e",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                PACKAGES[3],
                "--test",
                "objective_product_e2e",
                "--",
                "--nocapture",
            ],
        ),
        (
            "agentd-shutdown-outcomes",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                PACKAGES[3],
                "--test",
                "runtime_shutdown_outcomes",
            ],
        ),
        (
            "agentd-optional-restart",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                PACKAGES[3],
                "--test",
                "optional_module_restart",
            ],
        ),
        (
            "strict-clippy-owned-all-targets",
            [
                "cargo",
                "clippy",
                "--locked",
                *owned_all_target_crates,
                "--all-targets",
                "--no-deps",
                "--",
                "-D",
                "warnings",
            ],
        ),
        (
            "strict-clippy-intelligence-lib",
            [
                "cargo",
                "clippy",
                "--locked",
                "-p",
                PACKAGES[2],
                "--lib",
                "--no-deps",
                "--",
                "-D",
                "warnings",
            ],
        ),
        (
            "strict-clippy-objective-compatibility",
            [
                "cargo",
                "clippy",
                "--locked",
                "-p",
                PACKAGES[0],
                "--all-targets",
                "--features",
                "qualification-legacy-compile",
                "--no-deps",
                "--",
                "-D",
                "warnings",
            ],
        ),
    ]


def expected_command_names() -> set[str]:
    placeholder = "0" * 40
    return {name for name, _ in commands(placeholder, placeholder)}


def validate_identity(root: Path, source: str, base: str, out: Path) -> None:
    if not SHA.fullmatch(source) or not SHA.fullmatch(base):
        raise ValueError("source and merge base must be complete lowercase commit SHAs")
    for commit in (source, base):
        if git(root, "rev-parse", f"{commit}^{{commit}}") != commit:
            raise ValueError("commit identity mismatch")
    if git(root, "rev-parse", "HEAD") != source:
        raise ValueError("checkout is not the requested exact source")
    if git(root, "status", "--porcelain"):
        raise ValueError("qualification requires a clean source checkout")
    if out == root or root in out.parents:
        raise ValueError("evidence output must be outside the source checkout")


def deterministic_merge(root: Path, source: str, base: str) -> tuple[str, str]:
    tree = git(root, "merge-tree", "--write-tree", base, source).splitlines()[0]
    if not SHA.fullmatch(tree):
        raise ValueError("merge-tree did not return one valid tree identity")
    env = os.environ.copy()
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"] = "Hepta immutable qualification"
        env[f"GIT_{role}_EMAIL"] = "qualification@localhost"
        env[f"GIT_{role}_DATE"] = "2000-01-01T00:00:00+00:00"
    message = f"objective qualification merge\nbase {base}\nsource {source}\n"
    commit = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "commit-tree",
            tree,
            "-p",
            base,
            "-p",
            source,
        ],
        input=message,
        text=True,
        env=env,
    ).strip()
    return commit, tree


def complete(receipt: dict) -> bool:
    phases = receipt.get("candidates", [])
    expected = expected_command_names()
    return (
        len(phases) == 2
        and receipt.get("sourceClean") is True
        and {phase.get("kind") for phase in phases}
        == {"source-head", "synthetic-merge"}
        and all(
            phase.get("clean") is True
            and {check.get("name") for check in phase.get("checks", [])} == expected
            and len(phase.get("checks", [])) == len(expected)
            and all(
                check.get("status") == "completed"
                and check.get("exitCode") == 0
                and re.fullmatch(r"[0-9a-f]{64}", check.get("logSha256", ""))
                for check in phase["checks"]
            )
            for phase in phases
        )
        and not receipt.get("errors")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--merge-base", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--command-timeout", type=int, default=1800)
    args = parser.parse_args()
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    out = args.out.resolve()
    validate_identity(root, args.source_commit, args.merge_base, out)
    if args.command_timeout < 1:
        raise ValueError("command timeout must be positive")
    out.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": "hepta.objective.exact-execution.v1",
        "scope": "declared_native_module_checks_not_independent_acceptance",
        "sourceCommit": args.source_commit,
        "sourceTree": git(root, "rev-parse", "HEAD^{tree}"),
        "mergeBase": args.merge_base,
        "mergeBaseTree": git(root, "rev-parse", f"{args.merge_base}^{{tree}}"),
        "workflowCommit": os.environ.get(
            "QUALIFICATION_WORKFLOW_SHA", os.environ.get("GITHUB_SHA")
        ),
        "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"),
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner": {
            "platform": platform.platform(),
            "image": os.environ.get("ImageOS"),
            "imageVersion": os.environ.get("ImageVersion"),
            "python": sys.version,
        },
        "candidates": [],
        "errors": [],
        "sourceClean": False,
        "checksPassed": False,
        "selectedTargetHostAccepted": False,
        "independentAcceptance": False,
        "activated": False,
        "released": False,
    }
    write_report(out, receipt)
    candidates = [("source-head", args.source_commit, receipt["sourceTree"])]
    try:
        merge_commit, merge_tree = deterministic_merge(
            root, args.source_commit, args.merge_base
        )
        candidates.append(("synthetic-merge", merge_commit, merge_tree))
    except (subprocess.CalledProcessError, ValueError) as error:
        receipt["errors"].append(f"synthetic merge unavailable: {error}")
        write_report(out, receipt)
    for kind, commit, tree in candidates:
        phase = {
            "kind": kind,
            "commit": commit,
            "tree": tree,
            "checks": [],
            "clean": False,
        }
        receipt["candidates"].append(phase)
        write_report(out, receipt)
        with tempfile.TemporaryDirectory(prefix="objective-exact-") as temporary:
            worktree = Path(temporary) / "source"
            try:
                git(root, "worktree", "add", "--detach", str(worktree), commit)
                if git(worktree, "rev-parse", "HEAD^{tree}") != tree:
                    raise ValueError("candidate tree identity mismatch")
                phase_out = out / kind
                phase_out.mkdir()
                for name, command in commands(commit, tree):
                    check = run_command(
                        worktree / "codex-rs",
                        phase_out,
                        name,
                        command,
                        args.command_timeout,
                    )
                    phase["checks"].append(check)
                    write_report(out, receipt)
                phase["clean"] = not git(worktree, "status", "--porcelain")
                if not phase["clean"]:
                    (phase_out / "dirty-source.patch").write_text(
                        git(worktree, "diff", "HEAD")
                    )
                    receipt["errors"].append(
                        f"{kind}: source changed during qualification"
                    )
            except (OSError, subprocess.CalledProcessError, ValueError) as error:
                receipt["errors"].append(f"{kind}: {error}")
            finally:
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "worktree",
                        "remove",
                        "--force",
                        str(worktree),
                    ],
                    check=False,
                )
                write_report(out, receipt)
    receipt["sourceClean"] = not git(root, "status", "--porcelain")
    receipt["checksPassed"] = complete(receipt)
    write_report(out, receipt)
    return 0 if receipt["checksPassed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"objective qualification refused: {error}", file=sys.stderr)
        raise SystemExit(2)

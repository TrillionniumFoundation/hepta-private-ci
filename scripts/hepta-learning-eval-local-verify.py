#!/usr/bin/env python3
"""Run the repository-controlled deterministic learning.eval control-plane checks.

This is the canonical offline developer entrypoint for the Python evidence,
workflow, documentation, and status control plane. It does not authenticate a
selected host, execute future-calendar observations, issue independent
acceptance, or authorize activation/release. The heavier Rust, fault, coverage,
exact-head, and ordered-parent merge matrices remain in their dedicated
qualification workflows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Sequence

SCHEMA = "hepta.learning-eval.local-deterministic.v1"
SHA1 = re.compile(r"[0-9a-f]{40}\Z")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def evidence_hash(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("evidenceSha256", None)
    return hashlib.sha256(canonical(unsigned)).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def source_identity(root: Path, expected_commit: str | None = None) -> dict[str, str]:
    commit = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    if SHA1.fullmatch(commit) is None or SHA1.fullmatch(tree) is None:
        raise ValueError("local verification requires full lowercase Git identities")
    if expected_commit is not None and commit != expected_commit:
        raise ValueError("checkout does not match the requested local source commit")
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked source is dirty")
    return {"commit": commit, "tree": tree}


def digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def execute(
    name: str,
    argv: Sequence[str],
    root: Path,
    output: Path,
    *,
    environment: dict[str, str] | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    log = output / f"{name}.log"
    started = utc_now()
    before = time.monotonic()
    merged = os.environ.copy()
    if environment:
        merged.update(environment)
    status = "failed"
    exit_code: int | None = None
    error: str | None = None
    with log.open("wb") as stream:
        stream.write(
            (json.dumps({"argv": list(argv), "cwd": str(root)}) + "\n").encode()
        )
        stream.flush()
        try:
            completed = subprocess.run(
                list(argv),
                cwd=root,
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=merged,
                timeout=timeout,
                check=False,
            )
            exit_code = completed.returncode
            status = "passed" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "timed_out"
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
            stream.write((error + "\n").encode())
    return {
        "name": name,
        "argv": list(argv),
        "startedAt": started,
        "finishedAt": utc_now(),
        "durationSeconds": round(time.monotonic() - before, 6),
        "status": status,
        "exitCode": exit_code,
        "error": error,
        "log": {
            "path": log.name,
            "bytes": log.stat().st_size,
            "sha256": digest_file(log),
        },
    }


def python_sources(root: Path) -> list[str]:
    scripts = root / "scripts"
    candidates = list(scripts.glob("hepta-learning-eval-*.py"))
    candidates.extend(
        [
            scripts / "hepta-nextest-require.py",
            scripts / "test_hepta_nextest_require.py",
        ]
    )
    candidates.extend(scripts.glob("test_hepta_learning_eval*.py"))
    unique = sorted(
        {
            str(path.relative_to(root))
            for path in candidates
            if path.is_file() and not path.is_symlink()
        }
    )
    required = {
        "scripts/hepta-learning-eval-trusted-entry.py",
        "scripts/test_hepta_learning_eval_trusted_entry.py",
        "scripts/hepta-learning-eval-local-verify.py",
        "scripts/test_hepta_learning_eval_local_verify.py",
        "scripts/test_hepta_learning_eval_trusted_report.py",
        "scripts/test_hepta_learning_eval_trusted_report_base.py",
        "scripts/hepta-learning-eval-control-plane-identity.py",
        "scripts/test_hepta_learning_eval_control_plane_identity.py",
        "scripts/test_hepta_learning_eval_status.py",
    }
    missing = sorted(required - set(unique))
    if missing:
        raise ValueError(
            f"local verification source inventory is incomplete: {missing}"
        )
    return unique


def command_inventory(root: Path, output: Path) -> list[tuple[str, list[str]]]:
    python = sys.executable
    sources = python_sources(root)
    return [
        ("python-compile", [python, "-m", "py_compile", *sources]),
        (
            "exact-recorder-tests",
            [python, "scripts/test_hepta_learning_eval_exact.py", "-v"],
        ),
        (
            "nextest-discovery-tests",
            [python, "scripts/test_hepta_nextest_require.py", "-v"],
        ),
        (
            "exact-entry-tests",
            [python, "scripts/test_hepta_learning_eval_exact_entry.py", "-v"],
        ),
        (
            "compatibility-fixture-tests",
            [python, "scripts/test_hepta_learning_eval_compat_fixture.py", "-v"],
        ),
        (
            "evidence-summary-tests",
            [python, "scripts/test_hepta_learning_eval_evidence.py", "-v"],
        ),
        (
            "documentation-contract-tests",
            [python, "scripts/test_hepta_learning_eval_doc_contract.py", "-v"],
        ),
        (
            "control-plane-identity-tests",
            [
                python,
                "scripts/test_hepta_learning_eval_control_plane_identity.py",
                "-v",
            ],
        ),
        (
            "trusted-reporter-tests",
            [python, "scripts/test_hepta_learning_eval_trusted_report.py", "-v"],
        ),
        (
            "source-status-tests",
            [python, "scripts/test_hepta_learning_eval_status.py", "-v"],
        ),
        (
            "source-status",
            [python, "scripts/hepta-learning-eval-status.py", "verify"],
        ),
        (
            "documentation-contract",
            [python, "scripts/hepta-learning-eval-doc-contract.py"],
        ),
        (
            "compatibility-fixture-inventory",
            [
                python,
                "scripts/hepta-learning-eval-compat-fixture.py",
                "--check-only",
                "--evidence",
                str(output / "compatibility-fixture.json"),
            ],
        ),
        (
            "target-host-verifier-self-test",
            [python, "scripts/hepta-learning-eval-target-host.py", "self-test"],
        ),
    ]


def validate_summary(value: dict[str, Any]) -> None:
    if value.get("schema") != SCHEMA:
        raise ValueError("unexpected local deterministic summary schema")
    if value.get("authority") != "DENY_ALL" or value.get("releasePosture") != "NO_GO":
        raise ValueError("local deterministic summary grants authority")
    claims = value.get("claims")
    if not isinstance(claims, dict):
        raise ValueError("local deterministic claims are missing")
    for external in (
        "targetHostQualified",
        "independentAcceptanceIssued",
        "activationAuthorized",
        "releaseAuthorized",
    ):
        if claims.get(external) is not False:
            raise ValueError(
                f"local deterministic run exceeded claim scope: {external}"
            )
    commands = value.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError("local deterministic command inventory is missing")
    passed = all(command.get("status") == "passed" for command in commands)
    if claims.get("localDeterministicVerifiedByThisRun") is not passed:
        raise ValueError("local deterministic claim/result mismatch")
    if value.get("evidenceSha256") != evidence_hash(value):
        raise ValueError("local deterministic evidence digest mismatch")


def build_summary(
    source: dict[str, str],
    commands: list[dict[str, Any]],
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    passed = bool(commands) and all(
        command.get("status") == "passed" for command in commands
    )
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "source": source,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "commands": commands,
        "authority": "DENY_ALL",
        "releasePosture": "NO_GO",
        "claims": {
            "localDeterministicVerifiedByThisRun": passed,
            "exactHeadExecuted": False,
            "orderedParentSyntheticMergeExecuted": False,
            "targetHostQualified": False,
            "independentAcceptanceIssued": False,
            "activationAuthorized": False,
            "releaseAuthorized": False,
        },
    }
    value["evidenceSha256"] = evidence_hash(value)
    validate_summary(value)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    started = utc_now()
    root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    ).resolve()
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        parser.error("local deterministic output must not already exist")
    output.mkdir(parents=True)
    try:
        before = source_identity(root, args.source_commit)
        pycache = output / "pycache"
        pycache.mkdir()
        commands: list[dict[str, Any]] = []
        for name, command in command_inventory(root, output):
            result = execute(
                name,
                command,
                root,
                output,
                environment={"PYTHONPYCACHEPREFIX": str(pycache)},
            )
            commands.append(result)
            print(
                f"{name}: {result['status']} (exit={result['exitCode']})",
                flush=True,
            )
        after = source_identity(root, args.source_commit)
        if after != before:
            raise ValueError("source identity changed during local verification")
        summary = build_summary(before, commands, started, utc_now())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        failure = {
            "name": "local-verifier",
            "status": "failed",
            "exitCode": None,
            "error": f"{type(error).__name__}: {error}",
        }
        commands = locals().get("commands", [])
        commands.append(failure)
        source = locals().get("before", {"commit": "", "tree": ""})
        summary = build_summary(source, commands, started, utc_now())
    path = output / "local-deterministic-summary.json"
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(path)
    return 0 if summary["claims"]["localDeterministicVerifiedByThisRun"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

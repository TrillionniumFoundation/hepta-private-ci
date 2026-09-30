#!/usr/bin/env python3
"""Read-only exact-SHA qualification. Evidence never modifies the tested checkout.

--source-commit HEAD_SHA is the source-head entry point; the existing explicit
--expected-sha/--source-sha/--base-sha/--lane interface remains supported.
Independent execution is not semantic evaluator acceptance or release approval.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hepta.intuition.exact-command-record.v4"
PACKAGES = [
    "-p",
    "codex-hepta-intuition",
    "-p",
    "codex-hepta-intelligence",
    "-p",
    "codex-hepta-agentd",
    "-p",
    "codex-hepta-learning-ledger",
]


def cargo_test(package: str, *args: str) -> list[str]:
    return ["cargo", "test", "--locked", "-p", package, *args]


COMMANDS = [
    (
        "source-state-projection",
        ["python3", "../scripts/intuition_state.py", "--check"],
    ),
    (
        "golden-vectors-python",
        [
            "python3",
            "../scripts/intuition_golden_vectors.py",
            "hepta-intuition/testdata/production_contract_v2.json",
        ],
    ),
    ("fmt", ["cargo", "fmt", *PACKAGES, "--", "--check"]),
    ("check", ["cargo", "check", "--locked", *PACKAGES, "--all-targets"]),
    (
        "clippy",
        [
            "cargo",
            "clippy",
            "--locked",
            *PACKAGES,
            "--all-targets",
            "--no-deps",
            "--",
            "-D",
            "warnings",
        ],
    ),
    ("policy-tests", cargo_test("codex-hepta-intuition")),
    ("qualification-tests", cargo_test("codex-hepta-intelligence")),
    (
        "agentd-policy-tests",
        cargo_test("codex-hepta-agentd", "--lib", "intuition_policy"),
    ),
    (
        "agentd-product-tests",
        cargo_test("codex-hepta-agentd", "--test", "intuition_policy_product"),
    ),
    (
        "agentd-v3-product-tests",
        cargo_test("codex-hepta-agentd", "--test", "intuition_policy_product_v3"),
    ),
    (
        "agentd-commit-boundary-tests",
        cargo_test("codex-hepta-agentd", "--test", "intuition_policy_commit_boundary"),
    ),
    (
        "agentd-serving-runtime-tests",
        cargo_test("codex-hepta-agentd", "--lib", "intuition_policy_serving"),
    ),
    (
        "agentd-canonical-product-tests",
        cargo_test("codex-hepta-agentd", "--lib", "intelligence_product"),
    ),
    (
        "ledger-production-tests",
        cargo_test("codex-hepta-learning-ledger", "production"),
    ),
    (
        "ledger-trust-tests",
        cargo_test("codex-hepta-learning-ledger", "--lib", "trust_distribution"),
    ),
    (
        "kernel-fast-gate",
        [
            "cargo",
            "run",
            "--locked",
            "--release",
            "-p",
            "codex-hepta-intuition",
            "--example",
            "fast_gate",
        ],
    ),
    (
        "authenticated-fast-gate",
        [
            "cargo",
            "run",
            "--locked",
            "--release",
            "-p",
            "codex-hepta-intelligence",
            "--example",
            "intuition_authenticated_fast_gate",
        ],
    ),
    (
        "release-binaries",
        [
            "cargo",
            "build",
            "--locked",
            "--release",
            "-p",
            "codex-hepta-agentd",
            "--bin",
            "codex-hepta-agentd",
            "--message-format=json",
        ],
    ),
]
INDEPENDENT_COMMANDS = [
    (
        "independent-source-state",
        ["python3", "../scripts/intuition_state.py", "--check"],
    ),
    ("independent-policy", cargo_test("codex-hepta-intuition")),
    ("independent-qualification", cargo_test("codex-hepta-intelligence")),
    (
        "independent-product",
        cargo_test("codex-hepta-agentd", "--test", "intuition_policy_product_v3"),
    ),
    (
        "independent-boundary",
        cargo_test("codex-hepta-agentd", "--test", "intuition_policy_commit_boundary"),
    ),
    (
        "independent-serving-runtime",
        cargo_test("codex-hepta-agentd", "--lib", "intuition_policy_serving"),
    ),
    (
        "independent-canonical-product",
        cargo_test("codex-hepta-agentd", "--lib", "intelligence_product"),
    ),
    (
        "independent-ledger",
        cargo_test("codex-hepta-learning-ledger", "production"),
    ),
    (
        "independent-ledger-trust",
        cargo_test("codex-hepta-learning-ledger", "--lib", "trust_distribution"),
    ),
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def external_directory(path: Path) -> Path:
    path = path.resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError("evidence must be outside the tested checkout")
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError("evidence directory must be empty; refusing stale receipts")
    return path


def identity_error(
    head: str, expected: str, source: str, base: str, lane: str
) -> str | None:
    if not all(
        re.fullmatch(r"[0-9a-f]{40}", value) for value in (head, expected, source)
    ):
        return "full_commit_sha_required"
    if head != expected:
        return "checkout_sha_mismatch"
    if lane == "source-head":
        return None if source == head else "source_sha_mismatch"
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        return "merge_base_required"
    parents = git("rev-list", "--parents", "-n", "1", head).split()[1:]
    if len(parents) != 2 or set(parents) != {source, base}:
        return "synthetic_merge_parent_mismatch"
    return None


def terminate_group(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def execute(command: list[str], log: Path, cwd: Path, timeout: int) -> int:
    """Stream logs to disk; terminate the complete compiler subtree on timeout."""
    with log.open("wb") as stream:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as error:
            stream.write((str(error) + "\n").encode())
            return 127
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_group(process)
            stream.write(b"\nqualification command timed out\n")
            return 124
        except KeyboardInterrupt:
            terminate_group(process)
            stream.write(b"\nqualification command interrupted\n")
            return 130


def log_summary(path: Path) -> str:
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 16384))
        return "\n".join(stream.read().decode("utf-8", "replace").splitlines()[-60:])


def nonzero_tests(path: Path) -> bool:
    with path.open(encoding="utf-8", errors="replace") as stream:
        return any(
            re.search(r"test result: ok\. [1-9][0-9]* passed;", line) for line in stream
        )


def release_artifacts(path: Path) -> list[dict[str, str]]:
    artifacts = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            executable = message.get("executable")
            if message.get("reason") != "compiler-artifact" or not executable:
                continue
            binary = Path(executable)
            if "bin" in message.get("target", {}).get("kind", []) and binary.is_file():
                artifacts.append(
                    {"name": message["target"]["name"], "sha256": sha256(binary)}
                )
    return artifacts


def seal(evidence: Path) -> None:
    files = {
        path.name: sha256(path)
        for path in sorted(evidence.iterdir())
        if path.is_file() and path.name != "artifact-manifest.json"
    }
    write_json(
        evidence / "artifact-manifest.json",
        {"schema": "hepta.intuition.artifacts.v1", "sha256": files},
    )


def project(record: dict, evidence: Path) -> None:
    """Generate evidence-local projections; never overwrite development history."""
    source_map = ROOT / "docs/modules/intuition.policy/IMPLEMENTATION_MAP.json"
    mapping = (
        json.loads(source_map.read_text())
        if source_map.is_file()
        else {"module": "intuition.policy"}
    )
    mapping["sourceBase"] = {
        "commit": record["testedSha"],
        "tree": record["testedTree"],
    }
    mapping["sourceBasePurpose"] = (
        "Exact immutable source or synthetic-merge identity for this evidence bundle."
    )
    mapping["qualification"] = record
    mapping["productionImplementation"] = False
    mapping["full_completion_predicate"] = {
        "is_production_implemented": False,
        "happy_path_verified": False,
        "edge_failures_verified": False,
        "has_independent_acceptance_proof": False,
    }
    mapping["claimBoundary"] = {
        **mapping.get("claimBoundary", {}),
        "productionImplementation": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
    write_json(evidence / "IMPLEMENTATION_MAP.json", mapping)

    lines = [
        "# intuition.policy exact execution dossier",
        "",
        f"- Tested commit: `{record['testedSha']}`",
        f"- Tested tree: `{record['testedTree']}`",
        f"- Source commit: `{record['sourceSha']}`",
        f"- Mode/lane: `{record['mode']}/{record['lane']}`",
        (
            f"- Workflow run: `{record['runId']}`; job: `{record['jobId']}`; "
            f"attempt: `{record['runAttempt']}`"
        ),
        f"- Result: `{record['status']}`",
        "",
        (
            "This single execution does not authorize production, independent "
            "semantic acceptance, or release."
        ),
        "",
        "| Command | Exit | Status | Log SHA-256 |",
        "|---|---:|---|---|",
    ]
    for command in record["commands"]:
        lines.append(
            f"| {command['name']} | {command.get('exitCode', 'not returned')} | "
            f"{command['status']} | {command.get('logSha256', 'not available')} |"
        )
    (evidence / "execution-dossier.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit")
    parser.add_argument("--evidence", "--output-dir", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--source-sha")
    parser.add_argument("--base-sha", default="")
    parser.add_argument(
        "--lane", choices=["source-head", "synthetic-merge"], default="source-head"
    )
    parser.add_argument("--independent", action="store_true")
    parser.add_argument("--command-timeout", type=int, default=2400)
    args = parser.parse_args(argv)
    if args.command_timeout < 1:
        parser.error("--command-timeout must be positive")

    source = args.source_commit or args.source_sha
    if not source or (
        args.source_commit and args.source_sha and args.source_commit != args.source_sha
    ):
        parser.error("one consistent source SHA is required")
    expected = args.expected_sha or source
    try:
        evidence = external_directory(
            args.evidence or Path(tempfile.mkdtemp(prefix="intuition-evidence-"))
        )
    except ValueError as error:
        parser.error(str(error))

    head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    record = {
        "schema": SCHEMA,
        "sourceSha": source,
        "baseSha": args.base_sha or None,
        "testedSha": head,
        "testedTree": tree,
        "lane": args.lane,
        "mode": "independent" if args.independent else "qualification",
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "jobId": os.environ.get("GITHUB_JOB"),
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "host": platform.platform(),
        "startedAt": utc(),
        "status": "running",
        "commands": [],
        "independentAcceptance": "not_established",
        "operatorAcceptance": "not_established",
        "promotion": "not_authorized",
    }
    receipt = evidence / "command-record.json"
    write_json(receipt, record)

    initial = git("status", "--porcelain", "--untracked-files=all")
    failure = identity_error(head, expected, source, args.base_sha, args.lane)
    if initial or failure:
        record.update(
            status="failed",
            failure=failure or "initial_worktree_dirty",
            worktree=initial,
            worktreeUnchanged=False,
        )
        write_json(receipt, record)
        project(record, evidence)
        seal(evidence)
        return 1

    toolchain = evidence / "toolchain.txt"
    with toolchain.open("w", encoding="utf-8") as stream:
        for command in (
            ["rustc", "-Vv"],
            ["cargo", "-V"],
            ["uname", "-a"],
            ["lscpu"],
        ):
            stream.write("$ " + " ".join(command) + "\n")
            stream.flush()
            try:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                    check=False,
                )
                stream.write(f"exit_code={completed.returncode}\n")
            except (OSError, subprocess.TimeoutExpired) as error:
                stream.write(f"unavailable: {error}\n")
    record["toolchainLogSha256"] = sha256(toolchain)
    lockfile = ROOT / "codex-rs/Cargo.lock"
    record["cargoLockSha256"] = sha256(lockfile) if lockfile.is_file() else None

    failed = False
    selected_commands = INDEPENDENT_COMMANDS if args.independent else COMMANDS
    for name, command in selected_commands:
        result = {
            "name": name,
            "argv": command,
            "cwd": "codex-rs",
            "startedAt": utc(),
            "status": "running",
        }
        record["commands"].append(result)
        write_json(receipt, record)
        start = time.monotonic()
        log = evidence / (name + ".log")
        print(f"::group::{name}\n$ {' '.join(command)}", flush=True)
        code = execute(command, log, ROOT / "codex-rs", args.command_timeout)
        passed = code == 0
        if command[:2] == ["cargo", "test"]:
            result["nonzeroTests"] = nonzero_tests(log)
            passed = passed and result["nonzeroTests"]
        if name == "release-binaries" and passed:
            result["binaries"] = release_artifacts(log)
            passed = bool(result["binaries"])
        result.update(
            exitCode=code,
            status="passed" if passed else "failed",
            finishedAt=utc(),
            durationSeconds=round(time.monotonic() - start, 6),
            log=log.name,
            logSha256=sha256(log),
            logSummary=log_summary(log),
        )
        failed = failed or not passed
        print(
            result["logSummary"] + f"\nexit_code={code}\n::endgroup::",
            flush=True,
        )
        write_json(receipt, record)
        if code == 130:
            break

    final = git("status", "--porcelain", "--untracked-files=all")
    unchanged = (
        git("rev-parse", "HEAD") == head
        and git("rev-parse", "HEAD^{tree}") == tree
        and not final
    )
    record.update(
        status="passed" if not failed and unchanged else "failed",
        finishedAt=utc(),
        worktreeUnchanged=unchanged,
        finalWorktree=final,
    )
    write_json(receipt, record)
    write_json(
        evidence
        / (
            "independent-report.json"
            if args.independent
            else "qualification-report.json"
        ),
        record,
    )
    project(record, evidence)
    seal(evidence)
    print(
        json.dumps(
            {
                "evidence": str(evidence),
                "sourceSha": source,
                "testedSha": head,
                "status": record["status"],
                "artifactManifestSha256": sha256(evidence / "artifact-manifest.json"),
            }
        )
    )
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())

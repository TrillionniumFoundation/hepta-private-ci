#!/usr/bin/env python3
"""Read-only, commit-bound runtime.fleet qualification; never repairs source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time


class CandidateInvalid(ValueError):
    """The checked-out bytes do not represent the declared candidate."""


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_candidate(root: Path, kind: str, source: str, base: str) -> dict:
    """Check bytes as well as parents; a hand-crafted merge is not evidence."""
    if kind not in ("exact-source", "synthetic-merge"):
        raise CandidateInvalid("unknown qualification kind")
    for name, value in (("source", source), ("base", base)):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise CandidateInvalid(f"{name} must be an immutable full commit SHA")
        if git(root, "rev-parse", f"{value}^{{commit}}") != value:
            raise CandidateInvalid(f"{name} is not a commit")
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise CandidateInvalid("candidate must be clean before and after qualification")
    tested = git(root, "rev-parse", "HEAD")
    tested_tree = git(root, "rev-parse", "HEAD^{tree}")
    source_tree = git(root, "rev-parse", f"{source}^{{tree}}")
    base_tree = git(root, "rev-parse", f"{base}^{{tree}}")
    expected_merge_tree = None
    if kind == "exact-source":
        if tested != source or tested_tree != source_tree:
            raise CandidateInvalid("exact-source checkout does not match the pinned source")
    else:
        if git(root, "show", "-s", "--format=%P", tested).split() != [base, source]:
            raise CandidateInvalid("synthetic merge must have the pinned base/source parents")
        # Creating Git objects is allowed; modifying source/index/refs is not.
        # A conflict makes merge-tree nonzero and cannot be called a pass.
        expected_merge_tree = git(root, "merge-tree", "--write-tree", base, source)
        if tested_tree != expected_merge_tree:
            raise CandidateInvalid("synthetic merge content differs from the deterministic merge tree")
    return {
        "source_commit": source, "source_tree": source_tree,
        "base_commit": base, "base_tree": base_tree,
        "tested_commit": tested, "tested_tree": tested_tree,
        "expected_merge_tree": expected_merge_tree,
    }


def run_logged(argv: list[str], cwd: Path, log: Path, timeout: float = 1800) -> tuple[int, bool]:
    """Terminate the entire POSIX child group on timeout, including rustc."""
    with log.open("wb") as stream:
        try:
            process = subprocess.Popen(
                argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
            )
        except OSError as error:
            stream.write(f"infrastructure_invalid: {error}\n".encode())
            return 127, True
        try:
            return process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait()
            stream.write(b"\ninfrastructure_invalid: command timeout; child group terminated\n")
            return 124, True


def qualification_commands(root: Path) -> list[tuple[str, Path, list[str]]]:
    cargo = root / "codex-rs"
    return [
        ("receipt-regressions", root, [sys.executable, "-B", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_runtime_fleet_qualify.py", "-v"]),
        ("rustc", root, ["rustc", "-Vv"]),
        ("cargo", root, ["cargo", "-V"]),
        ("diff-check", root, ["git", "diff", "--check"]),
        ("fmt", cargo, ["cargo", "fmt", "--all", "--", "--check"]),
        ("fleet-test", cargo, ["cargo", "test", "--locked", "-p", "codex-hepta-fleet", "--all-targets"]),
        ("supervisor-test", cargo, ["cargo", "test", "--locked", "-p", "codex-hepta-supervisor", "--all-targets"]),
        ("supervisor-product-check", cargo, ["cargo", "check", "--locked", "-p", "codex-hepta-supervisor", "--bin", "hepta-supervisord"]),
        ("fleet-clippy", cargo, ["cargo", "clippy", "--locked", "--no-deps", "-p", "codex-hepta-fleet", "--all-targets", "--all-features", "--", "-D", "warnings"]),
        ("supervisor-clippy", cargo, ["cargo", "clippy", "--locked", "--no-deps", "-p", "codex-hepta-supervisor", "--all-targets", "--all-features", "--", "-D", "warnings"]),
        ("clean-tree", root, ["git", "status", "--porcelain=v1", "--untracked-files=all"]),
    ]


def qualify(root: Path, output: Path, kind: str, source: str, base: str) -> int:
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("evidence must be outside the qualified source tree")
    if output.exists() and any(output.iterdir()):
        raise ValueError("evidence directory must be empty; never mix attempts")
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "hepta.runtime-fleet.qualification.v3", "kind": kind,
        "requested_source": source, "requested_base": base,
        "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner_image": os.environ.get("ImageOS"),
        "runner_image_version": os.environ.get("ImageVersion"),
        "platform": platform.platform(), "commands": [], "errors": [],
        "outcome": "incomplete", "passed": False,
        "product_deployment": False, "independent_acceptance": False,
    }
    receipt_path = output / "receipt.json"

    def save() -> None:
        temporary = output / "receipt.json.tmp"
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        temporary.replace(receipt_path)

    save()
    invalid, failed = False, False
    try:
        identity = validate_candidate(root, kind, source, base)
        receipt.update(identity)
        receipt["entry_candidate_validated"] = True
        archive = output / "runtime-fleet-source.tgz"
        # Archive the whole tracked tree: workspace path dependencies are inputs.
        subprocess.run(
            ["git", "archive", "--format=tar.gz", f"--output={archive}", identity["tested_commit"]],
            cwd=root, check=True, timeout=180,
        )
        receipt["source_archive_sha256"] = digest(archive)
        receipt["source_archive_scope"] = "complete_tracked_tree"
        workflow = root / ".github/workflows/runtime-fleet-focused.yml"
        receipt["qualified_workflow_sha256"] = digest(workflow)
        receipt["qualification_script_sha256"] = digest(root / "scripts/runtime_fleet_qualify.py")
        save()
        for name, cwd, argv in qualification_commands(root):
            # Detect checkout or index changes between commands, not just at exit.
            if validate_candidate(root, kind, source, base) != identity:
                raise CandidateInvalid("candidate identity changed during qualification")
            log = output / f"{name}.log"
            start = time.monotonic()
            print(f"::group::{name}: {' '.join(argv)}", flush=True)
            code, infrastructure_invalid = run_logged(argv, cwd, log)
            if name == "clean-tree" and log.read_bytes().strip():
                code = code or 1
            invalid |= infrastructure_invalid
            failed |= code != 0
            receipt["commands"].append({
                "name": name, "argv": argv, "cwd": str(cwd.relative_to(root)),
                "exit_code": code, "duration_seconds": round(time.monotonic() - start, 3),
                "log": log.name, "log_sha256": digest(log),
                "infrastructure_invalid": infrastructure_invalid,
            })
            save()
            with log.open(errors="replace") as stream:
                for line in stream:
                    print(line, end="")
            print(f"::endgroup::\n{name}: exit={code}", flush=True)
        if validate_candidate(root, kind, source, base) != identity:
            raise CandidateInvalid("candidate identity changed at completion")
        receipt["exit_candidate_validated"] = True
        receipt["outcome"] = "infrastructure_invalid" if invalid else "failed" if failed else "passed"
        receipt["passed"] = not failed and not invalid
    except CandidateInvalid as error:
        receipt["outcome"] = "candidate_invalid"
        receipt["errors"].append(str(error))
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        receipt["outcome"] = "infrastructure_invalid"
        receipt["errors"].append(str(error))
    finally:
        save()
        (output / "receipt.sha256").write_text(f"{digest(receipt_path)}  receipt.json\n")
        print(json.dumps(receipt, indent=2, sort_keys=True), flush=True)
    return 0 if receipt["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=("exact-source", "synthetic-merge"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    return qualify(Path(__file__).resolve().parents[1], options.output, options.kind, options.source, options.base)


if __name__ == "__main__":
    sys.exit(main())

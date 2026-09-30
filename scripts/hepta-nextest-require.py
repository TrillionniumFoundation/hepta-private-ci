#!/usr/bin/env python3
"""Discover and run one required nextest filter with fail-closed evidence.

The command refuses to treat a successful build with zero selected tests as a
qualification result. It records the discovery and execution transcript without
issuing target-host, operator, activation, promotion, or release authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Sequence

SCHEMA = "hepta.nextest-required-filter.v1"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def matching_lines(output: str, expected: str) -> list[str]:
    """Return unique nextest-list lines that name the required test/filter."""
    matches: list[str] = []
    seen: set[str] = set()
    for raw in output.splitlines():
        line = ANSI.sub("", raw).strip()
        if expected not in line or line in seen:
            continue
        lowered = line.lower()
        if lowered.startswith(("warning:", "error:", "hint:", "command:")):
            continue
        seen.add(line)
        matches.append(line)
    return matches


def command_base(args: argparse.Namespace, subcommand: str) -> list[str]:
    command = ["cargo", "nextest", subcommand, "--manifest-path", args.manifest_path]
    if args.locked:
        command.append("--locked")
    command.extend(["-p", args.package])
    if args.features:
        command.extend(["--features", args.features])
    if args.all_features:
        command.append("--all-features")
    if args.no_default_features:
        command.append("--no-default-features")
    command.append(args.filter)
    return command


def run_capture(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
    return result


def write_evidence(path: Path | None, value: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--filter", required=True)
    parser.add_argument("--label")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--evidence")
    parser.add_argument("--features")
    parser.add_argument("--all-features", action="store_true")
    parser.add_argument("--no-default-features", action="store_true")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--locked", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)

    cwd = Path(args.cwd).resolve()
    evidence_path = Path(args.evidence).resolve() if args.evidence else None
    list_command = command_base(args, "list")
    run_command = command_base(args, "run")
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "label": args.label or args.filter,
        "manifestPath": args.manifest_path,
        "package": args.package,
        "requiredFilter": args.filter,
        "cwd": str(cwd),
        "authority": "DENY_ALL",
        "claims": {
            "requiredTestDiscovered": False,
            "requiredTestExecuted": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activationAuthorized": False,
            "releaseAuthorized": False,
        },
        "list": {"argv": list_command},
        "run": {"argv": run_command, "status": "not_run"},
    }

    listed = run_capture(list_command, cwd)
    list_output = listed.stdout or ""
    matches = matching_lines(list_output, args.filter)
    value["list"].update({
        "exitCode": listed.returncode,
        "outputBytes": len(list_output.encode("utf-8", errors="replace")),
        "outputSha256": sha256_text(list_output),
        "matchCount": len(matches),
        "matchedLines": matches,
    })
    if listed.returncode != 0:
        value["failure"] = "nextest_list_failed"
        write_evidence(evidence_path, value)
        return listed.returncode or 1
    if not matches:
        value["failure"] = "required_filter_matched_zero_tests"
        write_evidence(evidence_path, value)
        print(
            f"required nextest filter matched zero tests: package={args.package} filter={args.filter}",
            file=sys.stderr,
        )
        return 4

    value["claims"]["requiredTestDiscovered"] = True
    if args.list_only:
        value["run"]["status"] = "list_only"
        write_evidence(evidence_path, value)
        return 0

    executed = run_capture(run_command, cwd)
    run_output = executed.stdout or ""
    value["run"].update({
        "status": "passed" if executed.returncode == 0 else "failed",
        "exitCode": executed.returncode,
        "outputBytes": len(run_output.encode("utf-8", errors="replace")),
        "outputSha256": sha256_text(run_output),
    })
    value["claims"]["requiredTestExecuted"] = executed.returncode == 0
    if executed.returncode != 0:
        value["failure"] = "required_test_execution_failed"
    write_evidence(evidence_path, value)
    return executed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

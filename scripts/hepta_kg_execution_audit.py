#!/usr/bin/env python3
"""Fail-closed, local postflight inventory for the KG execution matrix.

This records observed checks on the checked-out candidate. It neither signs
observations nor grants independent acceptance, target-host qualification or release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}\Z")
SUMMARY = re.compile(
    r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;",
    re.MULTILINE,
)
COMMON = (
    "execution-audit-tests",
    "measurement-tests",
    "budget-tests",
    "measurement-self-test",
    "implementation-maps",
    "formatting",
)
KERNEL = ("kg-kernel", "kg-clippy")
PRODUCT = (
    "prompt-registry",
    "prompt-optimizer",
    "cognitive-owner",
    "delivery-consistency",
    "crash-reopen",
    "history-reopen",
    "agentd-default",
    "agentd-witness",
    "strict-clippy",
)
EXACT = {"crash-reopen", "history-reopen"}
PYTHON_TESTS = {"execution-audit-tests", "measurement-tests", "budget-tests"}
NATIVE = EXACT | {
    "kg-kernel",
    "prompt-registry",
    "prompt-optimizer",
    "cognitive-owner",
    "delivery-consistency",
    "agentd-default",
    "agentd-witness",
}


def required_checks(profile: str, lane: str) -> tuple[str, ...]:
    if profile not in ("kernel", "product") or lane not in (
        "source-head",
        "base-merge",
    ):
        raise ValueError("unknown execution profile/lane")
    checks = COMMON + (KERNEL if profile == "kernel" else PRODUCT)
    if profile == "product" and lane == "source-head":
        checks += ("release-measurement", "hosted-budget")
    return checks


def read_results(text: str, expected: tuple[str, ...]) -> dict[str, int]:
    results: dict[str, int] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] not in expected:
            raise ValueError("unknown check or malformed result row")
        name, code = fields
        if (
            name in results
            or not re.fullmatch(r"0|[1-9][0-9]{0,2}", code)
            or int(code) > 255
        ):
            raise ValueError("duplicate check or invalid exit code")
        results[name] = int(code)
    return results


def native_execution_proved(name: str, text: str) -> bool:
    summaries = SUMMARY.findall(text)
    if not summaries or any(
        state != "ok" or int(failed) != 0
        for state, _, failed, _ in summaries
    ):
        return False
    if name in EXACT:
        return len(summaries) == 1 and summaries[0] == ("ok", "1", "0", "0")
    return any(int(passed) > 0 for _, passed, _, _ in summaries)


def audit(
    directory: Path,
    profile: str,
    lane: str,
    source: str,
    base: str,
    actual_commit: str,
    actual_tree: str,
) -> dict:
    expected = required_checks(profile, lane)
    report = {
        "schema": "hepta.kg-execution-audit.v1",
        "profile": profile,
        "lane": lane,
        "sourceSha": source,
        "baseSha": base,
        "testedCommit": actual_commit,
        "testedTree": actual_tree,
        "checks": {},
        "errors": [],
        "completeAndPassed": False,
        "targetHostQualified": False,
        "independentAcceptance": False,
        "release": False,
    }
    errors = report["errors"]
    if not all(
        SHA.fullmatch(value)
        for value in (source, base, actual_commit, actual_tree)
    ):
        errors.append("invalid literal source/base/commit/tree identity")
    if lane == "source-head" and source != actual_commit:
        errors.append("source-head differs from the selected candidate")
    try:
        identity = (
            directory.joinpath("identity.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        if identity != [
            f"source={source}",
            f"base={base}",
            actual_commit,
            actual_tree,
        ]:
            errors.append("identity.txt differs from checked-out candidate")
    except (OSError, UnicodeError) as exc:
        errors.append(f"identity missing/unreadable: {type(exc).__name__}")
    try:
        results = read_results(
            directory.joinpath("results.tsv").read_text(encoding="utf-8"),
            expected,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"invalid results inventory: {exc}")
        results = {}
    for name in expected:
        entry = {
            "exitCode": results.get(name),
            "logSha256": None,
            "logBytes": None,
            "passed": False,
        }
        report["checks"][name] = entry
        if name not in results:
            errors.append(f"{name}: missing execution result")
            continue
        try:
            digest = hashlib.sha256()
            size = 0
            summaries: list[str] = []
            with directory.joinpath(name + ".log").open("rb") as stream:
                for line in stream:
                    digest.update(line)
                    size += len(line)
                    if line.startswith(
                        (b"test result:", b"Ran ", b"OK", b"FAILED")
                    ):
                        summaries.append(
                            line.decode("utf-8", errors="replace")
                        )
            entry.update(logSha256=digest.hexdigest(), logBytes=size)
            summary_text = "".join(summaries)
            if name in PYTHON_TESTS and (
                not re.search(
                    r"^Ran [1-9][0-9]* tests? in ",
                    summary_text,
                    re.MULTILINE,
                )
                or not re.search(r"^OK$", summary_text, re.MULTILINE)
                or re.search(r"^FAILED", summary_text, re.MULTILINE)
            ):
                errors.append(
                    f"{name}: no complete successful Python test execution"
                )
                continue
            if name in NATIVE and not native_execution_proved(
                name,
                summary_text,
            ):
                errors.append(
                    f"{name}: no complete successful native test execution"
                )
                continue
        except OSError as exc:
            errors.append(
                f"{name}: missing/unreadable log: {type(exc).__name__}"
            )
            continue
        entry["passed"] = results[name] == 0
        if not entry["passed"]:
            errors.append(f"{name}: exit code {results[name]}")
    report["completeAndPassed"] = not errors and all(
        row["passed"] for row in report["checks"].values()
    )
    return report


def git(root: Path, *args: str) -> str:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
    )
    return subprocess.check_output(
        [
            "git",
            "--literal-pathspecs",
            "-c",
            "core.fsmonitor=false",
            *args,
        ],
        cwd=root,
        env=env,
        text=True,
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--profile", choices=("kernel", "product"), required=True)
    parser.add_argument(
        "--lane",
        choices=("source-head", "base-merge"),
        required=True,
    )
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        head, tree = git(root, "rev-parse", "HEAD", "HEAD^{tree}").splitlines()
        report = audit(
            args.directory,
            args.profile,
            args.lane,
            args.source_sha,
            args.base_sha,
            head,
            tree,
        )
        if not SHA.fullmatch(args.source_sha) or not SHA.fullmatch(args.base_sha):
            raise ValueError("invalid source/base identity")
        for ancestor in (args.source_sha, args.base_sha):
            git(root, "merge-base", "--is-ancestor", ancestor, head)
        git(root, "diff", "--exit-code")
        git(root, "diff", "--cached", "--exit-code")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        report = locals().get(
            "report",
            {"schema": "hepta.kg-execution-audit.v1", "errors": []},
        )
        report["completeAndPassed"] = False
        report["errors"].append(
            f"candidate identity/cleanliness check failed: {exc}"
        )
    args.directory.mkdir(parents=True, exist_ok=True)
    temporary = args.directory / "execution-audit.json.tmp"
    temporary.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.directory / "execution-audit.json")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["completeAndPassed"] else 1


if __name__ == "__main__":
    sys.exit(main())

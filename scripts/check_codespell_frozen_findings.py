#!/usr/bin/env python3
"""Run full-tree spelling checks with exact, immutable historical diagnostics.

The raw checker still reports historical findings. This policy accepts only the
registered observations; it does not add ignored words or exclude source files.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


SOURCE_COMMIT = "0acfd9b27db910c180b0d8911f39aea469b7f864"
VERSION = "2.4.3"
POLICY_PATH = "scripts/codespell_frozen_findings.json"
AUTHORIZED_POLICY_SHA256 = (
    "129801b8619a7e349e7091542248e30f6e6df976255631aea1b5f9a45e774071"
)
CONFIGURATION = {".codespellrc", ".codespellignore"}
ABSENT_CONFIGURATION = {"setup.cfg", "pyproject.toml"}
SCAN_ARGUMENTS = [
    "--disable-colors",
    "--count",
    "--ignore-words",
    ".codespellignore",
    "--skip",
    "./.git",
    ".",
]
DIAGNOSTIC = re.compile(r"\./([^:\r\n]+):([1-9][0-9]*): ([^\s]+) ==> ([^\r\n]+)")


class PolicyError(ValueError):
    """The source binding or checker output cannot be verified."""


def require(condition, message):
    if not condition:
        raise PolicyError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def policy_identity(policy):
    return digest(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def exact_keys(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), f"Invalid {label} fields")


def source_path(root, relative):
    require(type(relative) is str and relative, "Invalid source path")
    require(not any(ord(c) < 32 for c in relative), "Control character in source path")
    require(not any(c in relative for c in "\\:"), "Noncanonical source path")
    parts = relative.split("/")
    require(all(part not in {"", ".", ".."} for part in parts), "Unsafe source path")
    current = root
    for part in parts:
        current = current / part
        require(not current.is_symlink(), f"Symlink in frozen source path: {relative}")
    return current


def load_policy(root):
    raw = source_path(root, POLICY_PATH).read_bytes()
    require(len(raw) <= 65536, "Policy exceeds 65536 bytes")
    policy = json.loads(
        raw,
        object_pairs_hook=unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(PolicyError(value)),
    )
    exact_keys(
        policy,
        {
            "schema_version",
            "source_commit",
            "codespell_version",
            "configuration",
            "absent_configuration",
            "files",
        },
        "policy",
    )
    require(
        type(policy["schema_version"]) is int and policy["schema_version"] == 1,
        "Unsupported policy schema",
    )
    require(
        policy["source_commit"] == SOURCE_COMMIT, "Historical source commit changed"
    )
    require(policy["codespell_version"] == VERSION, "Checker version changed")
    require(
        type(policy["absent_configuration"]) is list
        and len(policy["absent_configuration"]) == len(ABSENT_CONFIGURATION)
        and all(type(path) is str for path in policy["absent_configuration"])
        and set(policy["absent_configuration"]) == ABSENT_CONFIGURATION,
        "Unregistered automatic configuration",
    )
    paths, expected = set(), Counter()
    for group in ("configuration", "files"):
        require(type(policy[group]) is list and policy[group], f"Empty {group}")
        for entry in policy[group]:
            keys = {"path", "sha256", "bytes"}
            if group == "files":
                keys.add("findings")
            exact_keys(entry, keys, "file")
            path = entry["path"]
            source_path(root, path)
            require(path not in paths, "Duplicate source path")
            paths.add(path)
            require(
                type(entry["bytes"]) is int and entry["bytes"] > 0, "Invalid byte count"
            )
            require(
                type(entry["sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
                "Invalid file digest",
            )
            if group == "files":
                require(
                    type(entry["findings"]) is list and entry["findings"],
                    "Empty findings",
                )
                for finding in entry["findings"]:
                    exact_keys(
                        finding,
                        {"line", "token_sha256", "diagnostic_sha256"},
                        "finding",
                    )
                    require(
                        type(finding["line"]) is int and finding["line"] > 0,
                        "Invalid line",
                    )
                    token = finding["token_sha256"]
                    require(
                        type(token) is str and re.fullmatch(r"[0-9a-f]{64}", token),
                        "Invalid token digest",
                    )
                    diagnostic = finding["diagnostic_sha256"]
                    require(
                        type(diagnostic) is str
                        and re.fullmatch(r"[0-9a-f]{64}", diagnostic),
                        "Invalid diagnostic digest",
                    )
                    key = (path, finding["line"], token, diagnostic)
                    require(key not in expected, "Duplicate historical finding")
                    expected[key] = 1
    require(
        {entry["path"] for entry in policy["configuration"]} == CONFIGURATION,
        "Spelling configuration coverage changed",
    )
    require(
        policy_identity(policy) == AUTHORIZED_POLICY_SHA256,
        "Authorized historical policy inventory changed",
    )
    return policy, raw, expected


def git(root, *arguments):
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
    )
    require(result.returncode == 0, f"Git verification failed: {' '.join(arguments)}")
    return result.stdout


def verify_checkout(root, policy):
    require(
        Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        == root,
        "Checker must run at the repository root",
    )
    git(root, "merge-base", "--is-ancestor", SOURCE_COMMIT, "HEAD")
    tracked = git(root, "ls-files", "-v", "-z").split(b"\0")
    for row in filter(None, tracked):
        require(
            row[:1].upper() != b"S", "Sparse checkout cannot prove full-tree coverage"
        )
        relative = row[2:].decode("utf-8")
        path = root / relative
        require(
            path.exists() or path.is_symlink(), f"Tracked source is missing: {relative}"
        )
    for relative in policy["absent_configuration"]:
        path = source_path(root, relative)
        require(not path.exists(), f"Unexpected automatic configuration: {relative}")
    for entry in policy["configuration"] + policy["files"]:
        path = source_path(root, entry["path"])
        data = path.read_bytes()
        require(
            len(data) == entry["bytes"] and digest(data) == entry["sha256"],
            f"Frozen source bytes changed: {entry['path']}",
        )
        historical = git(root, "show", f"{SOURCE_COMMIT}:{entry['path']}")
        require(data == historical, f"Historical provenance mismatch: {entry['path']}")
    return len(tracked) - 1


def classify(stdout, stderr, returncode, expected):
    observed = Counter()
    for line in stdout.splitlines():
        match = DIAGNOSTIC.fullmatch(line)
        require(
            match is not None, "Unknown checker output; no diagnostic was suppressed"
        )
        path, line_number, token, _suggestion = match.groups()
        require(
            not any(part in {"", ".", ".."} for part in path.split("/"))
            and "\\" not in path,
            "Noncanonical diagnostic path",
        )
        observed[
            (
                path,
                int(line_number),
                digest(token.encode("utf-8")),
                digest(line.encode("utf-8")),
            )
        ] += 1
    require(re.fullmatch(r"[0-9]+\n", stderr) is not None, "Unknown checker stderr")
    count = sum(observed.values())
    require(int(stderr) == count, "Checker count disagrees with parsed diagnostics")
    require(returncode == (65 if count else 0), "Unexpected checker exit code")
    accepted = observed & expected
    new = observed - expected
    missing = expected - observed
    return {
        "raw_lint_findings": count,
        "frozen_historical_findings": sum(accepted.values()),
        "new_findings": sum(new.values()),
        "missing_frozen_findings": sum(missing.values()),
        "raw_lint_clean": count == 0,
        "policy_passed": observed == expected,
        "raw_exit_code": returncode,
        "raw_stdout_sha256": digest(stdout.encode("utf-8")),
        "raw_stderr_sha256": digest(stderr.encode("utf-8")),
        "diagnostics": [
            {
                "path": path,
                "line": line,
                "token_sha256": token,
                "diagnostic_sha256": diagnostic,
                "count": occurrences,
            }
            for (path, line, token, diagnostic), occurrences in sorted(observed.items())
        ],
    }


def evaluate(root):
    policy, original, expected = load_policy(root)
    tracked = verify_checkout(root, policy)
    version = subprocess.run(
        [sys.executable, "-I", "-m", "codespell_lib", "--version"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    require(
        version.returncode == 0
        and version.stdout.strip() == VERSION
        and not version.stderr,
        "Install the exact registered codespell version",
    )
    result = subprocess.run(
        [sys.executable, "-I", "-m", "codespell_lib", *SCAN_ARGUMENTS],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    verify_checkout(root, policy)
    require(
        source_path(root, POLICY_PATH).read_bytes() == original,
        "Policy changed during scan",
    )
    report = classify(result.stdout, result.stderr, result.returncode, expected)
    report.update(
        {
            "schema_version": 1,
            "source_commit": SOURCE_COMMIT,
            "codespell_version": VERSION,
            "tracked_files_checked": tracked,
            "scan_arguments": SCAN_ARGUMENTS,
            "policy_sha256": digest(original),
            "authorized_policy_sha256": AUTHORIZED_POLICY_SHA256,
            "frozen_files": [
                {k: v for k, v in entry.items() if k != "findings"}
                for entry in policy["files"]
            ],
        }
    )
    if not report["policy_passed"]:
        print(result.stdout, end="", file=sys.stderr)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        help="Write the classification receipt outside the checkout",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report_path = None
    try:
        if args.report:
            require(
                not args.report.resolve().is_relative_to(root),
                "Receipt must be outside the scanned checkout",
            )
            report_path = args.report
        report = evaluate(root)
    except (PolicyError, OSError, UnicodeError, json.JSONDecodeError) as error:
        report = {"schema_version": 1, "policy_passed": False, "error": str(error)}
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(encoded, end="")
    if report_path:
        report_path.write_text(encoded, encoding="utf-8")
    return 0 if report["policy_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Reject candidate changes that can rewrite or replace the reviewed source."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable

if __package__:
    from .hepta_workflow_integrity import (
        _candidate_blob,
        _read_workflow,
        git_environment,
        workflow_violations,
    )
else:
    from hepta_workflow_integrity import (
        _candidate_blob,
        _read_workflow,
        git_environment,
        workflow_violations,
    )

ROOT = pathlib.Path(__file__).resolve().parents[1]

SCANNED_SUFFIXES = {".yml", ".yaml", ".py", ".sh", ".bash", ".zsh", ".ps1"}
SCANNED_PREFIXES = (".github/workflows/", ".github/actions/", "scripts/")
DENIED_PATH_PATTERNS = (
    re.compile(
        r"(^|/)(?:materiali[sz]e|materializer|one[-_]?shot|publish[-_]?repair)(?:[./_-]|$)",
        re.I,
    ),
    re.compile(r"\.part[0-9]+$", re.I),
)
WORKFLOW_ONLY_TEXT_PATTERNS = (
    ("contents-write", re.compile(r"(?mi)^\s*contents\s*:\s*write\s*(?:#.*)?$")),
    (
        "persisted-checkout-credentials",
        re.compile(r"(?mi)^\s*persist-credentials\s*:\s*true\s*(?:#.*)?$"),
    ),
    ("branch-push", re.compile(r"(?mi)\bgit\s+push\b")),
    ("ref-rewrite", re.compile(r"(?mi)\bgit\s+update-ref\b")),
    (
        "self-merge",
        re.compile(r"(?mi)(?:\bgh\s+pr\s+merge\b|\bgit\s+merge\s+--ff-only\s+origin/)"),
    ),
    ("untrusted-privileged-trigger", re.compile(r"(?mi)^\s*pull_request_target\s*:")),
    (
        "workflow-source-commit",
        re.compile(
            r"(?mi)(?:git\s+commit\b|git\s+tag\b).{0,240}(?:git\s+push\b|update-ref\b)"
        ),
    ),
)
EXECUTABLE_TEXT_PATTERNS = (
    (
        "encoded-python-payload",
        re.compile(
            r"(?is)(?:base64\.b64decode|urlsafe_b64decode).{0,240}(?:exec\s*\(|compile\s*\(|zlib\.decompress)"
        ),
    ),
    (
        "encoded-shell-payload",
        re.compile(
            r"(?mi)(?:base64\s+(?:--decode|-d)|openssl\s+base64\s+-d).{0,160}(?:\|\s*(?:sh|bash|python)|>\s*\.github/)"
        ),
    ),
    (
        "remote-pipe-execution",
        re.compile(r"(?mi)(?:curl|wget)\b[^\n]{0,400}\|\s*(?:sh|bash|python(?:3)?)\b"),
    ),
)


@dataclass(frozen=True)
class Violation:
    path: str
    rule: str
    line: int
    excerpt: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "rule": self.rule,
            "line": self.line,
            "excerpt": self.excerpt,
        }


def run_git_raw(*args: str) -> bytes:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "--literal-pathspecs",
            "-c",
            "core.fsmonitor=false",
            *args,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=git_environment(),
    )
    if proc.returncode:
        error = proc.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"git {' '.join(args)} failed: {error}")
    return proc.stdout


def run_git(*args: str) -> str:
    return run_git_raw(*args).decode("utf-8").strip()


def resolve_commit(reference: str) -> str:
    commit = run_git(
        "rev-parse", "--verify", "--end-of-options", f"{reference}^{{commit}}"
    )
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise SystemExit("immutable Git commit required")
    return commit


def changed_paths(base: str, head: str) -> list[str]:
    if not base or not head:
        raise SystemExit("both --base and --head are required")
    base, head = resolve_commit(base), resolve_commit(head)
    raw = run_git_raw(
        "diff", "--name-only", "-z", "--diff-filter=ACMR", f"{base}...{head}", "--"
    )
    try:
        return sorted({path.decode("utf-8") for path in raw.split(b"\0") if path})
    except UnicodeDecodeError as error:
        raise SystemExit(
            "candidate filename is not valid UTF-8; integrity verification refused"
        ) from error


def is_scanned(path: str) -> bool:
    candidate = pathlib.PurePosixPath(path)
    return (
        path.startswith(SCANNED_PREFIXES)
        and candidate.suffix.lower() in SCANNED_SUFFIXES
    )


def is_workflow_code(path: str) -> bool:
    return path.startswith((".github/workflows/", ".github/actions/"))


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def excerpt_for(text: str, line: int) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    value = lines[min(max(line - 1, 0), len(lines) - 1)].strip()
    return value[:240]


def scan_text(path: str, text: str) -> list[Violation]:
    violations: list[Violation] = []
    for pattern in DENIED_PATH_PATTERNS:
        if pattern.search(path):
            violations.append(Violation(path, "denied-candidate-path", 1, path))
            break

    patterns = list(EXECUTABLE_TEXT_PATTERNS)
    if is_workflow_code(path):
        patterns.extend(WORKFLOW_ONLY_TEXT_PATTERNS)

    for name, pattern in patterns:
        for match in pattern.finditer(text):
            line = line_for_offset(text, match.start())
            violations.append(Violation(path, name, line, excerpt_for(text, line)))

    return violations


def scan_path(path: str, text: str, candidate: str | None = None) -> list[Violation]:
    violations = scan_text(path, text)
    if path.startswith(".github/workflows/"):

        def inspect_text(child: str, content: str):
            return [
                (item.path, item.rule, item.line, item.excerpt)
                for item in scan_text(child, content)
            ]

        violations.extend(
            Violation(*item)
            for item in workflow_violations(path, text, ROOT, inspect_text, candidate)
        )
    return violations


def verify(base: str, head: str, output: str | None) -> int:
    base, candidate = resolve_commit(base), resolve_commit(head)
    paths = changed_paths(base, candidate)
    violations: list[Violation] = []
    scanned: list[str] = []
    captured: dict[str, str] = {}
    for path in paths:
        if any(pattern.search(path) for pattern in DENIED_PATH_PATTERNS):
            violations.append(Violation(path, "denied-candidate-path", 1, path))
        if not is_scanned(path):
            continue
        scanned.append(path)
        try:
            text = _read_workflow(ROOT, path)
            _candidate_blob(ROOT, path, text, candidate)
        except (
            OSError,
            UnicodeError,
            ValueError,
            subprocess.CalledProcessError,
        ) as error:
            violations.append(Violation(path, "invalid-candidate-file", 1, str(error)))
            continue
        captured[path] = text
        if path != "scripts/hepta-repository-integrity.py":
            violations.extend(scan_path(path, text, candidate))

    own_path = "scripts/hepta-repository-integrity.py"
    if own_path in captured:
        own_text = captured[own_path]
        forbidden_fragments = (
            ("subprocess.run([", '"git", "push"'),
            ("os.system(", '"git push'),
        )
        for prefix, suffix in forbidden_fragments:
            forbidden = prefix + suffix
            if forbidden in own_text:
                violations.append(Violation(own_path, "self-bypass", 1, forbidden))

    payload = {
        "schema": "hepta.repository-integrity-receipt.v1",
        "base": base,
        "head": candidate,
        "changedPathCount": len(paths),
        "scannedPaths": scanned,
        "violations": [item.as_dict() for item in violations],
        "authorityGranted": False,
        "status": (
            "PASS_HEPTA_REPOSITORY_INTEGRITY"
            if not violations
            else "FAIL_HEPTA_REPOSITORY_INTEGRITY"
        ),
    }
    rendered = json.dumps(payload, sort_keys=True)
    print(rendered)
    if output:
        target = pathlib.Path(output)
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
    return 0 if not violations else 1


def self_test() -> int:
    good = """name: safe
permissions:
  contents: read
jobs:
  check:
    steps:
      - uses: actions/checkout@example
        with:
          persist-credentials: false
"""
    bad_cases = {
        "contents-write": "permissions:\n  contents: write\npersist-credentials: false\n",
        "persisted-checkout-credentials": "permissions:\n  contents: read\npersist-credentials: true\n",
        "branch-push": "permissions:\n  contents: read\npersist-credentials: false\nrun: git push origin HEAD:x\n",
        "untrusted-privileged-trigger": "pull_request_target:\npermissions:\n  contents: read\npersist-credentials: false\n",
        "encoded-python-payload": "permissions:\n  contents: read\npersist-credentials: false\nx = base64.b64decode(v); exec(x)\n",
    }
    assert not scan_path(".github/workflows/good.yml", good)
    for expected, body in bad_cases.items():
        rules = {v.rule for v in scan_path(".github/workflows/bad.yml", body)}
        assert expected in rules, (expected, rules)

    verifier_fixture = (
        "for forbidden in ('contents: write', 'git push', 'update-ref'): pass\n"
    )
    assert not scan_path("scripts/verifier-fixture.py", verifier_fixture)
    assert any(
        violation.rule == "denied-candidate-path"
        for violation in scan_path("scripts/materializer.py", "")
    )
    print(
        json.dumps(
            {"status": "PASS_HEPTA_REPOSITORY_INTEGRITY_SELF_TEST"},
            sort_keys=True,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--base", required=True)
    verify_parser.add_argument("--head", required=True)
    verify_parser.add_argument("--output")
    sub.add_parser("self-test")
    return root


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "self-test":
        return self_test()
    if args.command == "verify":
        return verify(args.base, args.head, args.output)
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())

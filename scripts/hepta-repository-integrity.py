#!/usr/bin/env python3
"""Fail-closed, deletion-aware policy for reviewed repository source.

The verifier evaluates the exact Git objects supplied by CI. It never mutates the
checkout, grants authority, or treats a workflow name as evidence of acceptance.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCANNED_SUFFIXES = {".yml", ".yaml", ".py", ".sh", ".bash", ".zsh", ".ps1"}
SCANNED_PREFIXES = (".github/workflows/", ".github/actions/", "scripts/")
SAFE_COMPATIBILITY_WORKFLOW = ".github/workflows/hepta-gap-closure.yml"
PROTECTED_DELETION = frozenset(
    {
        SAFE_COMPATIBILITY_WORKFLOW,
        ".github/workflows/hepta-repository-integrity.yml",
        "scripts/hepta-gap-closure.py",
        "scripts/hepta-repository-integrity.py",
    }
)
DENIED_PATH_PATTERNS = (
    re.compile(
        r"(^|/)(?:materiali[sz]e|materializer|one[-_]?shot|publish[-_]?repair)(?:[./_-]|$)",
        re.I,
    ),
    re.compile(r"\.part[0-9]+$", re.I),
)
WORKFLOW_PATTERNS = (
    ("contents-write", re.compile(r"(?mi)^\s*contents\s*:\s*write\s*(?:#.*)?$")),
    (
        "persisted-checkout-credentials",
        re.compile(r"(?mi)^\s*persist-credentials\s*:\s*true\s*(?:#.*)?$"),
    ),
    ("branch-push", re.compile(r"(?mi)\bgit\s+push\b")),
    ("ref-rewrite", re.compile(r"(?mi)\bgit\s+update-ref\b")),
    (
        "self-merge",
        re.compile(
            r"(?mi)(?:\bgh\s+pr\s+merge\b|\bgit\s+merge\s+--ff-only\s+origin/)"
        ),
    ),
    ("untrusted-privileged-trigger", re.compile(r"(?mi)^\s*pull_request_target\s*:")),
)
EXECUTABLE_PATTERNS = (
    (
        "encoded-python-payload",
        re.compile(
            r"(?is)(?:base64\.b64decode|urlsafe_b64decode).{0,240}"
            r"(?:exec\s*\(|compile\s*\(|zlib\.decompress)"
        ),
    ),
    (
        "encoded-shell-payload",
        re.compile(
            r"(?mi)(?:base64\s+(?:--decode|-d)|openssl\s+base64\s+-d)"
            r".{0,160}(?:\|\s*(?:sh|bash|python)|>\s*\.github/)"
        ),
    ),
    (
        "remote-pipe-execution",
        re.compile(
            r"(?mi)(?:curl|wget)\b[^\n]{0,400}\|\s*(?:sh|bash|python(?:3)?)\b"
        ),
    ),
)
REQUIRED_WORKFLOW_TOKENS = (
    "permissions:",
    "contents: read",
    "persist-credentials: false",
)


class IntegrityInputError(ValueError):
    """Raised when Git emits a non-canonical change record."""


@dataclass(frozen=True, order=True)
class ChangedPath:
    status: str
    path: str
    previous_path: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "path": self.path,
            "previousPath": self.previous_path,
        }


@dataclass(frozen=True, order=True)
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


def git_bytes(*args: str, check: bool = True) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and process.returncode:
        detail = process.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"git {' '.join(args)} failed: {detail}")
    return process.stdout


def git(*args: str) -> str:
    return git_bytes(*args).decode("utf-8", "strict").strip()


def decode_path(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise IntegrityInputError("non-UTF-8 Git path") from error
    parts = pathlib.PurePosixPath(value).parts
    if (
        not value
        or value.startswith("/")
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or "/".join(parts) != value
        or "\\" in value
        or "\0" in value
    ):
        raise IntegrityInputError("non-canonical Git path")
    return value


def parse_name_status_z(raw: bytes) -> tuple[ChangedPath, ...]:
    fields = raw.split(b"\0")
    if fields and not fields[-1]:
        fields.pop()
    result: list[ChangedPath] = []
    index = 0
    while index < len(fields):
        try:
            status = fields[index].decode("ascii", "strict")
        except UnicodeDecodeError as error:
            raise IntegrityInputError("invalid Git status encoding") from error
        index += 1
        if re.fullmatch(r"(?:[AMTD]|[RC][0-9]{1,3})", status) is None:
            raise IntegrityInputError(f"unsupported Git status: {status!r}")
        width = 2 if status.startswith(("R", "C")) else 1
        if index + width > len(fields):
            raise IntegrityInputError("truncated Git change record")
        if width == 2:
            previous = decode_path(fields[index])
            path = decode_path(fields[index + 1])
            result.append(ChangedPath(status, path, previous))
        else:
            result.append(ChangedPath(status, decode_path(fields[index])))
        index += width
    identity = [(item.status, item.path, item.previous_path) for item in result]
    if len(identity) != len(set(identity)):
        raise IntegrityInputError("duplicate Git change record")
    return tuple(sorted(result))


def changed_entries(base: str, head: str) -> tuple[ChangedPath, ...]:
    if not base or not head:
        raise SystemExit("both --base and --head are required")
    git("cat-file", "-e", f"{base}^{{commit}}")
    git("cat-file", "-e", f"{head}^{{commit}}")
    raw = git_bytes(
        "diff",
        "--name-status",
        "-z",
        "--diff-filter=ACMRTD",
        f"{base}...{head}",
        "--",
    )
    try:
        return parse_name_status_z(raw)
    except IntegrityInputError as error:
        raise SystemExit(f"invalid Git change set: {error}") from error


def is_scanned(path: str) -> bool:
    return path.startswith(SCANNED_PREFIXES) and (
        pathlib.PurePosixPath(path).suffix.lower() in SCANNED_SUFFIXES
    )


def scan_path(path: str, text: str) -> list[Violation]:
    violations: list[Violation] = []
    if any(pattern.search(path) for pattern in DENIED_PATH_PATTERNS):
        violations.append(Violation(path, "denied-candidate-path", 1, path))
    patterns = list(EXECUTABLE_PATTERNS)
    if path.startswith((".github/workflows/", ".github/actions/")):
        patterns.extend(WORKFLOW_PATTERNS)
    lines = text.splitlines()
    for name, pattern in patterns:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            excerpt = lines[line - 1].strip()[:240] if lines else ""
            violations.append(Violation(path, name, line, excerpt))
    if path.startswith(".github/workflows/"):
        for token in REQUIRED_WORKFLOW_TOKENS:
            if token not in text:
                violations.append(
                    Violation(path, "missing-safe-workflow-token", 1, token)
                )
    return violations


def blob_at(commit: str, path: str) -> bytes | None:
    process = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{path}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return process.stdout if process.returncode == 0 else None


def scan_blob(commit: str, path: str) -> list[Violation]:
    raw = blob_at(commit, path)
    if raw is None:
        return [Violation(path, "protected-deletion", 1, "missing at exact head")]
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return [Violation(path, "non-utf8-executable-source", 1, "")]
    return scan_path(path, text)


def verify(base: str, head: str, output: str | None) -> int:
    entries = changed_entries(base, head)
    violations: list[Violation] = []
    scanned: set[str] = set()

    for entry in entries:
        removed = ([entry.path] if entry.status == "D" else []) + (
            [entry.previous_path] if entry.previous_path is not None else []
        )
        for path in removed:
            if path in PROTECTED_DELETION:
                violations.append(Violation(path, "protected-deletion", 1, entry.status))
        if entry.status == "D":
            continue
        if any(pattern.search(entry.path) for pattern in DENIED_PATH_PATTERNS):
            violations.append(
                Violation(entry.path, "denied-candidate-path", 1, entry.path)
            )
        if is_scanned(entry.path) and entry.path != "scripts/hepta-repository-integrity.py":
            scanned.add(entry.path)
            violations.extend(scan_blob(head, entry.path))

    scanned.add(SAFE_COMPATIBILITY_WORKFLOW)
    violations.extend(scan_blob(head, SAFE_COMPATIBILITY_WORKFLOW))
    compatibility = blob_at(head, SAFE_COMPATIBILITY_WORKFLOW)
    if compatibility is not None:
        try:
            text = compatibility.decode("utf-8", "strict")
        except UnicodeDecodeError:
            text = ""
        for token in (
            "Hepta exact source and gap closure (read-only)",
            "identity-receipt",
            "identity-verify",
            "source-head",
            "merge-candidate",
        ):
            if token not in text:
                violations.append(
                    Violation(
                        SAFE_COMPATIBILITY_WORKFLOW,
                        "retired-materializer-contract-drift",
                        1,
                        token,
                    )
                )

    own_path = "scripts/hepta-repository-integrity.py"
    own = blob_at(head, own_path)
    if own is None:
        violations.append(
            Violation(own_path, "protected-deletion", 1, "missing at exact head")
        )
    else:
        try:
            own_text = own.decode("utf-8", "strict")
        except UnicodeDecodeError:
            violations.append(
                Violation(own_path, "non-utf8-executable-source", 1, "")
            )
            own_text = ""
        for token in (
            "--diff-filter=ACMRTD",
            "PROTECTED_DELETION",
            "SAFE_COMPATIBILITY_WORKFLOW",
            "parse_name_status_z",
        ):
            if token not in own_text:
                violations.append(
                    Violation(own_path, "self-policy-regression", 1, token)
                )

    unique = {
        (item.path, item.rule, item.line, item.excerpt): item
        for item in violations
    }
    ordered = sorted(
        unique.values(),
        key=lambda item: (item.path, item.rule, item.line, item.excerpt),
    )
    payload = {
        "schema": "hepta.repository-integrity-receipt.v2",
        "base": base,
        "head": head,
        "changedPathCount": len(entries),
        "changedPaths": [item.as_dict() for item in entries],
        "scannedPaths": sorted(scanned),
        "protectedDeletionSet": sorted(PROTECTED_DELETION),
        "compatibilityWorkflow": SAFE_COMPATIBILITY_WORKFLOW,
        "violations": [item.as_dict() for item in ordered],
        "authorityGranted": False,
        "status": (
            "PASS_HEPTA_REPOSITORY_INTEGRITY"
            if not ordered
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
    return 0 if not ordered else 1


def self_test() -> int:
    good = """name: Hepta exact source and gap closure (read-only)
permissions:
  contents: read
jobs:
  check:
    steps:
      - uses: actions/checkout@example
        with:
          persist-credentials: false
      - run: python3 scripts/hepta-gap-closure.py identity-receipt --kind source-head
      - run: python3 scripts/hepta-gap-closure.py identity-verify --kind merge-candidate
"""
    assert scan_path(".github/workflows/good.yml", good) == []

    cases = {
        "contents-write": "permissions:\n  contents: write\npersist-credentials: false\n",
        "persisted-checkout-credentials": "permissions:\n  contents: read\npersist-credentials: true\n",
        "branch-push": "permissions:\n  contents: read\npersist-credentials: false\nrun: git push origin HEAD:x\n",
        "ref-rewrite": "permissions:\n  contents: read\npersist-credentials: false\nrun: git update-ref refs/heads/x HEAD\n",
        "untrusted-privileged-trigger": "pull_request_target:\npermissions:\n  contents: read\npersist-credentials: false\n",
        "encoded-python-payload": "permissions:\n  contents: read\npersist-credentials: false\nx = base64.b64decode(v); exec(x)\n",
    }
    for expected, body in cases.items():
        rules = {item.rule for item in scan_path(".github/workflows/bad.yml", body)}
        assert expected in rules, (expected, rules)

    parsed = parse_name_status_z(
        b"M\0scripts/check.py\0R100\0scripts/old.py\0scripts/new.py\0D\0scripts/dead.py\0"
    )
    assert parsed == (
        ChangedPath("D", "scripts/dead.py"),
        ChangedPath("M", "scripts/check.py"),
        ChangedPath("R100", "scripts/new.py", "scripts/old.py"),
    )
    for hostile in (
        b"X\0scripts/check.py\0",
        b"M\0../escape.py\0",
        b"R100\0scripts/old.py\0",
        b"M\0scripts/\xff.py\0",
    ):
        try:
            parse_name_status_z(hostile)
        except IntegrityInputError:
            pass
        else:
            raise AssertionError(f"hostile Git record was accepted: {hostile!r}")

    rules = {
        item.rule for item in scan_path("scripts/materializer.py", "")
    }
    assert "denied-candidate-path" in rules
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

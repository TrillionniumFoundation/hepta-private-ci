#!/usr/bin/env python3
"""Fail-closed, deletion-aware policy for reviewed repository source."""
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
PROTECTED_DELETION = frozenset({
    SAFE_COMPATIBILITY_WORKFLOW,
    ".github/workflows/hepta-repository-integrity.yml",
    "scripts/hepta-gap-closure.py",
    "scripts/hepta-repository-integrity.py",
})
DENIED_PATH_PATTERNS = (
    re.compile(r"(^|/)(?:materiali[sz]e|materializer|one[-_]?shot|publish[-_]?repair)(?:[./_-]|$)", re.I),
    re.compile(r"\.part[0-9]+$", re.I),
)
WORKFLOW_PATTERNS = (
    ("contents-write", re.compile(r"(?mi)^\s*contents\s*:\s*write\s*(?:#.*)?$")),
    ("persisted-checkout-credentials", re.compile(r"(?mi)^\s*persist-credentials\s*:\s*true\s*(?:#.*)?$")),
    ("branch-push", re.compile(r"(?mi)\bgit\s+push\b")),
    ("ref-rewrite", re.compile(r"(?mi)\bgit\s+update-ref\b")),
    ("self-merge", re.compile(r"(?mi)(?:\bgh\s+pr\s+merge\b|\bgit\s+merge\s+--ff-only\s+origin/)")),
    ("untrusted-privileged-trigger", re.compile(r"(?mi)^\s*pull_request_target\s*:")),
)
EXECUTABLE_PATTERNS = (
    ("encoded-python-payload", re.compile(r"(?is)(?:base64\.b64decode|urlsafe_b64decode).{0,240}(?:exec\s*\(|compile\s*\(|zlib\.decompress)")),
    ("encoded-shell-payload", re.compile(r"(?mi)(?:base64\s+(?:--decode|-d)|openssl\s+base64\s+-d).{0,160}(?:\|\s*(?:sh|bash|python)|>\s*\.github/)")),
    ("remote-pipe-execution", re.compile(r"(?mi)(?:curl|wget)\b[^\n]{0,400}\|\s*(?:sh|bash|python(?:3)?)\b")),
)
REQUIRED_WORKFLOW_TOKENS = ("permissions:", "contents: read", "persist-credentials: false")


class IntegrityInputError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class ChangedPath:
    status: str
    path: str
    previous_path: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"status": self.status, "path": self.path, "previousPath": self.previous_path}


@dataclass(frozen=True)
class Violation:
    path: str
    rule: str
    line: int
    excerpt: str

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "rule": self.rule, "line": self.line, "excerpt": self.excerpt}


def git_bytes(*args: str, check: bool = True) -> bytes:
    process = subprocess.run(["git", "-C", str(ROOT), *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and process.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {process.stderr.decode('utf-8', 'replace').strip()}")
    return process.stdout


def git(*args: str) -> str:
    return git_bytes(*args).decode("utf-8", "strict").strip()


def decode_path(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise IntegrityInputError("non-UTF-8 Git path") from error
    parts = pathlib.PurePosixPath(value).parts
    if not value or value.startswith("/") or not parts or any(part in {"", ".", ".."} for part in parts) or "/".join(parts) != value:
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
        if not re.fullmatch(r"(?:[AMTD]|[RC][0-9]{1,3})", status):
            raise IntegrityInputError(&"unsupported Git status: {status!r}")
        width = 2 if status.startswith(("R", "C")) else 1
        if index + width > len(fields):
            raise IntegrityInputError("truncated Git change record")
        if width == 2:
            previous, path = decode_path(fields[index]), decode_path(fields[index + 1])
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
    raw = git_bytes("diff", "--name-status", "-z", "--diff-filter=ACMRTD", f"{base}...{head}", "--")
    try:
        return parse_name_status_z(raw)
    except IntegrityInputError as error:
        raise SystemExit(f"invalid Git change set: {error}") from error


def is_scanned(path: str) -> bool:
    return path.startswith(SCANNED_PREFIXES) and pathlib.PurePosixPath(path).suffix.lower() in SCANNED_SUFFIXES


def scan_path(path: str, text: str) -> list[Violation]:
    violations: list[Violation] = []
    if any(pattern.search(path) for pattern in DENIED_PATH_PATTERNS):
        violations.append(Violation(path, "denied-candidate-path", 1, path))
    patterns = list(EXECUTABLE_PATTERNS)
    if path.startswith((".github/workflows/", ".github/actions/")):
        patterns.extend(WORKFLOW_PATTERNS)
    for name, pattern in patterns:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            excerpt = (text.splitlines()[line - 1].strip() if text.splitlines() else "")[:240]
            violations.append(Violation(path, name, line, excerpt))
    if path.startswith(".github/workflows/"):
        for token in REQUIRED_WORKFLOW_TOKENS:
            if token not in text:
                violations.append(Violation(path, "missing-safe-workflow-token", 1, token))
    return violations


def blob_at(commit: str, path: str) -> bytes | None:
    process = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{path}"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return process.stdout if process.returncode == 0 else None


def scan_blob(commit: str, path: str) -> list[Violation]:
    raw = blob_at(head, path)
    if raw is None:
        return [Violation(path, "protected-deletion", 1, "missing at exact head")]
    try:
        return scan_path(path, raw.decode("utf-8", "strict"))
    except UnicodeDecodeError:
        return [Violation(path, "non-utf8-executable-source", 1, "")]


def verify(base: str, head: str, output: str | None) -> int:
    entries = changed_entries(base, head)
    violations: list[Violation] = []
    scanned: set[str] = set()
    for entry in entries:
        deleted = ([entry.path] if entry.status == "D" else []) + ([entry.previous_path] if entry.previous_path else [])
        for path in deleted:
            if path in PROTECTED_DELETION:
                violations.append(Violation(path, "protected-deletion", 1, entry.status))
        if entry.status == "D":
            continue
        if any(pattern.search(entry.path) for pattern in DENIED_PATH_PATTERNS):
            violations.append(Violation(entry.path, "denied-candidate-path", 1, entry.path))
        if is_scanned(entry.path) and entry.path != "scripts/hepta-repository-integrity.py":
            scanned.add(entry.path)
            violations.extend(scan_blob(head, entry.path))

    scanned.add(SAFE_COMPATIBILITY_WORKFLOW)
    violations.extend(scan_blob(head, SAFE_COMPATIBILITY_WORKFLOW))
    compatibility = blob_at(head, SAFE_COMPATIBILITY_WORKFLOW)
    if compatibility is not None:
        text = compatibility.decode("utf-8", "strict")
        for token in ("Hepta exact source and gap closure (read-only)", "identity-receipt", "identity-verify", "source-head", "merge-candidate"):
            if token not in text:
                violations.append(Violation(SAFE_COMPATIBILITY_WORKFLOW, 'retired-materializer-contract-drift', 1, token))

    own_path = "scripts/hepta-repository-integrity.py"
    own = blob_at(head, own_path)
    if own is None:
        violations.append(Violation(own_path, "protected-deletion", 1, "missing at exact head"))
    else:
        own_text = own.decode("utf-8", "strict")
        for token in ("--diff-filter=ACMRTD", "PROTECTED_DELETION", "SAFE_COMPATIBILITY_WORKFLOW", "parse_name_status_z"):
            if token not in own_text:
                violations.append(Violation(own_path, "self-policy-regression", 1, token))

    unique = {(item.path, item.rule, item.line, item.excerpt): item for item in violations}
    ordered = sorted(unique.values(), key=lambda item: (item.path, item.rule, item.line, item.excerpt))
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
        "status": "PASS_HEPTA_REPOSITORY_INTEGRITY" if not ordered else "FAIL_HEPTA_REPOSITORY_INTEGRITY",
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
persist-credentials: false
identity-receipt source-head
identity-verift„	¥±”µ•É”µ…¹‘¥‘…Ñ”(ˆˆˆ(€€€…ÍÍ•ÉÐ¹½ÐÍ…¹}Á…Ñ ¡M}=5AQ%	%1%Qe}]=I-1=\°½½¤(€€€…Í•Ì€ôì(€€€€€€€€‰½¹Ñ•¹ÑÌµÝÉ¥Ñ”ˆè€‰Á•Éµ¥ÍÍ¥½¹Ìéq¸€½¹Ñ•¹ÑÌèÝÉ¥Ñ•q¹Á•ÉÍ¥ÍÐµÉ•‘•¹Ñ¥…±Ìè™…±Í•q¸ˆ°(€€€€€€€€‰Á•ÉÍ¥ÍÑ•µ¡•­½ÕÐµÉ•‘•¹Ñ¥…±Ìˆè€‰Á•Éµ¥ÍÍ¥½¹Ìéq¸€½¹Ñ•¹ÑÌèÉ•…‘q¹Á•ÉÍ¥ÍÐµÉ•‘•¹Ñ¥…±ÌèÑÉÕ•q¸ˆ°(€€€€€€€€‰‰É…¹ µÁÕÍ ˆè€‰Á•Éµ¥ÍÍ¥½¹Ìéq¸€½¹Ñ•¹ÑÌèÉ•…‘q¹Á•ÉÍ¥ÍÐµÉ•‘•¹Ñ¥…±Ìè™…±Í•q¹ÉÕ¸è¥ÐÁÕÍ ½É¥¥¸!éáq¸ˆ°(€€€€€€€€‰Õ¹ÑÉÕÍÑ•µÁÉ¥Ù¥±••µÑÉ¥•Èˆè€‰ÁÕ±±}É•ÅÕ•ÍÑ}Ñ…É•Ðéq¹Á•Éµ¥ÍÍ¥½¹Ìéq¸€½¹Ñ•¹ÑÌèÉ•…‘q¹Á•ÉÍ¥ÍÐµÉ•‘•¹Ñ¥…±Ìè™…±Í•q¸ˆ°(€€€€€€€€‰•¹½‘•µÁåÑ¡½¸µÁ…å±½…ˆè€‰Á•Éµ¥ÍÍ¥½¹Ìéq¸€½¹Ñ•¹ÑÌèÉ•…‘q¹Á•ÉÍ¥ÍÐµÉ•‘•¹Ñ¥…±Ìè™…±Í•q¹à€ô‰…Í”ØÐ¹ˆØÑ‘•½‘”¡Ø¤ì•á•Œ¡à¥q¸ˆ°(€€€ô(€€€™½È•áÁ•Ñ•°‰½‘ä¥¸…Í•Ì¹¥Ñ•µÌ ¤è(€€€€€€€…ÍÍ•ÉÐ•áÁ•Ñ•¥¸í¥Ñ•´¹ÉÕ±”™½È¥Ñ•´¥¸Í…¹}Á…Ñ  ˆ¹¥Ñ¡Õˆ½Ý½É­™±½ÝÌ½‰…¹åµ°ˆ°‰½‘ä¥ô(€€€Á…ÉÍ•€ôÁ…ÉÍ•}¹…µ•}ÍÑ…ÑÕÍ}è¡ˆ‰pÁÍÉ¥ÁÑÌ½¹•Ü¹ÁåpÁpÁÍÉ¥ÁÑÌ½½±¹ÁåqáHÄÀÁpÁÍÉ¥ÁÑÌ½™É½´¹ÁåpÁÍÉ¥ÁÑÌ½Ñ¼¹ÁåpÀˆ¤(€€€…ÍÍ•ÉÐÁ…ÉÍ•€ôô€¡¡…¹•‘A…Ñ  ‰ˆ°€‰ÍÉ¥ÁÑÌ½¹•Ü¹Áäˆ¤°¡…¹•‘A…Ñ  ‰ˆ°€‰ÍÉ¥ÁÑÌ½½±¹Áäˆ¤°¡…¹•‘A…Ñ  ‰HÄÀÀˆ°€‰ÍÉ¥ÁÑÌ½Ñ¼¹Áäˆ°€‰ÍÉ¥ÁÑÌ½™É½´¹Áäˆ¤¤(€€€ÑÉäè(€€€€€€€Á…ÉÍ•}¹…µ•}ÍÑ…ÑÕÍ}è¡ˆ‰5pÁ‰…‘qá™™Á…Ñ¡pÀˆ¤(€€€•á•ÁÐ%¹Ñ•É¥Ñå%¹ÁÕÑÉÉ½Èè(€€€€€€€Á…ÍÌ(€€€•±Í”è(€€€€€€€É…¥Í”ÍÍ•ÉÑ¥½¹ÉÉ½È ‰¹½¸µUQ´àÁ…Ñ …•ÁÑ•ˆ¤(€€€…ÍÍ•ÉÐ…¹ä¡¥Ñ•´¹ÉÕ±”€ôô€‰‘•¹¥•µ…¹‘¥‘…Ñ”µÁ…Ñ ˆ™½È¥Ñ•´¥¸Í…¹}Á…Ñ  ‰ÍÉ¥ÁÑÌ½µ…Ñ•É¥…±¥é•È¹Áäˆ°€ˆˆ¤¤(€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡ì‰ÍÑ…ÑÕÌˆè€‰AMM}!AQ}IA=M%Q=Ie}%9QI%Qe}M1}QMPˆ°€‰‘•±•Ñ¥½¹Ý…É”ˆèQÉÕ”°€‰½µÁ…Ñ¥‰¥±¥Ñå]½É­™±½Ý]É¥Ñ•…Á…‰¥±¥Ñäˆè…±Í•ô°Í½ÉÑ}­•åÌõQÉÕ”¤¤(€€€É•ÑÕÉ¸€À(()‘•˜Á…ÉÍ•È ¤€´ø…ÉÁ…ÉÍ”¹ÉÕµ•¹ÑA…ÉÍ•Èè(€€€É½½Ð€ô…ÉÁ…ÉÍ”¹ÉÕµ•¹ÑA…ÉÍ•È ¤(€€€½µµ…¹‘Ì€ôÉ½½Ð¹…‘‘}ÍÕ‰Á…ÉÍ•ÉÌ¡‘•ÍÐô‰½µµ…¹ˆ°É•ÅÕ¥É•õQÉÕ”¤(€€€Ù•É¥™å}Á…ÉÍ•È€ô½µµ…¹‘Ì¹…‘‘}Á…ÉÍ•È ‰Ù•É¥™äˆ¤(€€€Ù•É¥™å}Á…ÉÍ•È¹…‘‘}…ÉÕµ•¹Ð ˆ´µ‰…Í”ˆ°É•ÅÕ¥É•õQÉÕ”¤(€€€Ù•É¥™å}Á…ÉÍ•È¹…‘‘}…ÉÕµ•¹Ð ˆ´µ¡•…ˆ°É•ÅÕ¥É•õQÉÕ”¤(€€€Ù•É¥™å}Á…ÉÍ•È¹…‘‘}…ÉÕµ•¹Ð ˆ´µ½ÕÑÁÕÐˆ¤(€€€½µµ…¹‘Ì¹…‘‘}Á…ÉÍ•È ‰Í•±˜µÑ•ÍÐˆ¤(€€€É•ÑÕÉ¸É½½Ð(()‘•˜µ…¥¸¡…ÉØè%Ñ•É…‰±•mÍÑÉtð9½¹”€ô9½¹”¤€´ø¥¹Ðè(€€€…ÉÌ€ôÁ…ÉÍ•È ¤¹Á…ÉÍ•}…ÉÌ¡±¥ÍÐ¡…ÉØ¤¥˜…ÉØ¥Ì¹½Ð9½¹”•±Í”9½¹”¤(€€€¥˜…ÉÌ¹½µµ…¹€ôô€‰Í•±˜µÑ•ÍÐˆè(€€€€€€€É•ÑÕÉ¸Í•±™}Ñ•ÍÐ ¤(€€€É•ÑÕÉ¸Ù•É¥™ä¡…ÉÌ¹‰…Í”°…ÉÌ¹¡•…°…ÉÌ¹½ÕÑÁÕÐ¤(()¥˜}}¹…µ•}|€ôô€‰}}µ…¥¹}|ˆè(€€€ÍåÌ¹•á¥Ð¡µ…¥¸ ¤¤(
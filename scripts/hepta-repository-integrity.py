#!/usr/bin/env python3
"""Reject candidate changes that can rewrite or replace the reviewed source."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import stat
import subprocess
import sys
import zlib
from dataclasses import dataclass
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]

FROZEN_RESULTS = "qualification/pft_six_experiments_20261125/results/"
FROZEN_REPORT = FROZEN_RESULTS + "pft2_multihost.json"
FROZEN_REPORT_SHA256 = (
    "10db4af87950b614d174593bfbf5d8b652e785cd7aef54294490d9cbafd83666"
)
FROZEN_ARCHIVES = (
    FROZEN_RESULTS + "pft2_multihost_ai395.json.zlib",
    FROZEN_RESULTS + "pft2_multihost_pocket4.json.zlib",
)
MAX_FROZEN_REPORT_BYTES = 64 * 1024
MAX_FROZEN_PACKED_BYTES = 256 * 1024
MAX_FROZEN_RAW_BYTES = 1024 * 1024

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
REQUIRED_SAFE_WORKFLOW_TOKENS = (
    "permissions:",
    "contents: read",
    "persist-credentials: false",
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


def run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def changed_paths(base: str, head: str) -> list[str]:
    if not base or not head:
        raise SystemExit("both --base and --head are required")
    run_git("cat-file", "-e", f"{base}^{{commit}}")
    run_git("cat-file", "-e", f"{head}^{{commit}}")
    raw = run_git("diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}", "--")
    return sorted({line.strip() for line in raw.splitlines() if line.strip()})


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


def scan_path(path: str, text: str) -> list[Violation]:
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

    if path.startswith(".github/workflows/"):
        for token in REQUIRED_SAFE_WORKFLOW_TOKENS:
            if token not in text:
                violations.append(
                    Violation(path, "missing-safe-workflow-token", 1, token)
                )
    return violations


def verify(base: str, head: str, output: str | None) -> int:
    paths = changed_paths(base, head)
    violations: list[Violation] = []
    scanned: list[str] = []
    for path in paths:
        if any(pattern.search(path) for pattern in DENIED_PATH_PATTERNS):
            violations.append(Violation(path, "denied-candidate-path", 1, path))
        if not is_scanned(path):
            continue
        target = ROOT / path
        if not target.is_file():
            continue
        scanned.append(path)
        text = target.read_text(encoding="utf-8", errors="strict")
        if path != "scripts/hepta-repository-integrity.py":
            violations.extend(scan_path(path, text))

    own_path = "scripts/hepta-repository-integrity.py"
    if own_path in paths:
        own_text = (ROOT / own_path).read_text(encoding="utf-8")
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
        "head": head,
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


def strict_evidence_json(raw: bytes) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate evidence JSON key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("non-finite evidence JSON number")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite evidence JSON number")
        return result

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
        parse_float=finite_float,
    )


def read_frozen_evidence(path: pathlib.Path, limit: int) -> bytes:
    if path.is_symlink():
        raise ValueError("frozen evidence must not be a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("frozen evidence is not a bounded regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("frozen evidence exceeds its byte limit")
    return raw


def unpack_frozen_evidence(packed: bytes) -> bytes:
    if len(packed) > MAX_FROZEN_PACKED_BYTES:
        raise ValueError("compressed evidence exceeds its byte limit")
    decoder = zlib.decompressobj()
    raw = decoder.decompress(packed, MAX_FROZEN_RAW_BYTES + 1)
    if (
        len(raw) > MAX_FROZEN_RAW_BYTES
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise ValueError("evidence must be one complete bounded zlib stream")
    return raw


def spelling_inputs(root: pathlib.Path) -> dict[str, object]:
    """Classify only the two immutable archives in the existing PFT report."""
    observed = set()

    def walk_error(error):
        raise error

    for folder, directories, files in os.walk(
        root, onerror=walk_error, followlinks=False
    ):
        if pathlib.Path(folder) == root:
            directories[:] = [name for name in directories if name != ".git"]
        for name in [*directories, *files]:
            if pathlib.Path(name).suffix.lower() == ".zlib":
                observed.add((pathlib.Path(folder) / name).relative_to(root).as_posix())
    if observed != set(FROZEN_ARCHIVES):
        raise ValueError(
            "missing or unregistered zlib evidence; no spelling exclusions granted"
        )
    for part in (root / FROZEN_REPORT).parents:
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("frozen evidence parent must not be a symbolic link")

    report_raw = read_frozen_evidence(root / FROZEN_REPORT, MAX_FROZEN_REPORT_BYTES)
    if hashlib.sha256(report_raw).hexdigest() != FROZEN_REPORT_SHA256:
        raise ValueError("the frozen evidence registration changed")
    report = strict_evidence_json(report_raw)
    artifacts = report["raw_statistic_artifacts"]
    receipts = report["numerical_host_receipts"]
    if (
        len(artifacts) != 2
        or len(receipts) != 2
        or {FROZEN_RESULTS + item["file"] for item in artifacts} != set(FROZEN_ARCHIVES)
    ):
        raise ValueError("the frozen evidence roster differs")
    checked = []
    for relative in FROZEN_ARCHIVES:
        artifact = next(
            item for item in artifacts if FROZEN_RESULTS + item["file"] == relative
        )
        host = artifact["configured_host"]
        receipt = next(item for item in receipts if item["configured_host"] == host)
        packed = read_frozen_evidence(root / relative, MAX_FROZEN_PACKED_BYTES)
        digest = hashlib.sha256(packed).hexdigest()
        blob = hashlib.sha1(
            b"blob " + str(len(packed)).encode("ascii") + b"\0" + packed
        ).hexdigest()
        if (
            artifact["compression"] != "zlib"
            or len(packed) != artifact["bytes"]
            or len(packed) != receipt["bytes"]
            or digest != artifact["sha256"]
            or digest != receipt["packed_sha256"]
            or blob != artifact["git_blob_sha1"]
        ):
            raise ValueError("the registered compressed evidence identity differs")
        raw = unpack_frozen_evidence(packed)
        if hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
            raise ValueError("the registered uncompressed evidence identity differs")
        original = strict_evidence_json(raw)
        if (
            original["configured_host"] != host
            or original["source_sha256"] != receipt["source_sha256"]
            or original["source_sha256"] != report["source_sha256"]
            or not isinstance(original["records"], list)
            or len(original["records"]) != receipt["records"]
        ):
            raise ValueError("the registered evidence host, source or records differ")
        checked.append(
            {
                "path": relative,
                "bytes": len(packed),
                "sha256": digest,
                "git_blob_sha1": blob,
                "raw_sha256": receipt["raw_sha256"],
            }
        )
    return {
        "schema": "hepta.frozen-evidence-spelling-inputs.v1",
        "status": "PASS_FROZEN_EVIDENCE_SPELLING_INPUTS",
        "registration_sha256": FROZEN_REPORT_SHA256,
        "verified_archives": checked,
        "skip": "./.git," + ",".join("./" + path for path in FROZEN_ARCHIVES),
        "text_policy_changed": False,
        "authorityGranted": False,
    }


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
    spelling_parser = sub.add_parser("spelling-inputs")
    spelling_parser.add_argument("--github-output", type=pathlib.Path)
    sub.add_parser("self-test")
    return root


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "self-test":
        return self_test()
    if args.command == "verify":
        return verify(args.base, args.head, args.output)
    if args.command == "spelling-inputs":
        try:
            payload = spelling_inputs(ROOT)
            if args.github_output:
                with args.github_output.open("a", encoding="utf-8") as output:
                    output.write("skip=" + payload["skip"] + "\n")
        except (OSError, ValueError, zlib.error) as error:
            print(
                json.dumps(
                    {
                        "status": "FAIL_FROZEN_EVIDENCE_SPELLING_INPUTS",
                        "reason": str(error),
                    }
                )
            )
            return 1
        print(json.dumps(payload, sort_keys=True))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())

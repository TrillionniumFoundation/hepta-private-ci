#!/usr/bin/env python3
"""Create exact, non-overlapping GitHub Actions shards from real unittest methods.

This planner is intentionally source-only: it does not import candidate code or
pretend that a syntactically discovered test has passed. Execute with unittest
on a pinned source SHA; missing/failed tests remain failures.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

MAX_PER_COHORT = 250
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _subclass_of_testcase(
    name: str, classes: dict[str, ast.ClassDef], visited: frozenset[str] = frozenset()
) -> bool:
    if name in visited or name not in classes:
        return False
    seen = visited | {name}
    for base in classes[name].bases:
        root = _base_name(base)
        if root in {"TestCase", "IsolatedAsyncioTestCase"}:
            return True
        if _subclass_of_testcase(root, classes, seen):
            return True
    return False


def collect_tests(root: Path) -> list[str]:
    """Discover distinct unittest.TestCase methods, without importing candidate code."""
    scripts = root / "scripts"
    if not scripts.is_dir():
        raise ValueError(f"source tree is missing scripts/: {root}")
    selected: set[str] = set()
    for path in sorted(scripts.rglob("test_*.py")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        if not all(IDENTIFIER_RE.fullmatch(x) for x in relative.with_suffix("").parts):
            raise ValueError(f"invalid test module path: {relative}")
        module = ".".join(relative.with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes = {
            node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
        }
        for cls in classes.values():
            if not _subclass_of_testcase(cls.name, classes):
                continue
            for method in cls.body:
                if (
                    isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and method.name.startswith("test_")
                    and IDENTIFIER_RE.fullmatch(method.name)
                ):
                    selected.add(f"{module}.{cls.name}.{method.name}")
    return sorted(selected)


def plan(test_ids: list[str], cohort: str, per_cohort: int) -> dict:
    if cohort not in {"A", "B"}:
        raise ValueError("cohort must be A or B")
    if (
        not isinstance(per_cohort, int)
        or isinstance(per_cohort, bool)
        or not 1 <= per_cohort <= MAX_PER_COHORT
    ):
        raise ValueError("per_cohort must be an integer from 1 to 250")
    if len(test_ids) != len(set(test_ids)):
        raise ValueError("duplicate test identifiers are forbidden")
    fingerprint = hashlib.sha256("\n".join(test_ids).encode()).hexdigest()
    enough = len(test_ids) >= 2 * per_cohort
    offset = 0 if cohort == "A" else per_cohort
    cases = test_ids[offset : offset + per_cohort] if enough else []
    return {
        "cohort": cohort,
        "per_cohort": per_cohort,
        "available_tests": len(test_ids),
        "full_two_cohort_ready": enough,
        "manifest_sha256": fingerprint,
        "selected_count": len(cases),
        "matrix": {"include": [{"case": case} for case in cases]},
    }


def _git_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--cohort", choices=["A", "B"], required=True)
    parser.add_argument("--per-cohort", type=int, default=250)
    parser.add_argument(
        "--expected-sha", default="", help="Exact checked-out 40-digit source SHA"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Require explicit SHA pin and full two-cohort readiness",
    )
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if args.expected_sha:
            expected = args.expected_sha.lower()
            if not SHA_RE.fullmatch(expected):
                raise ValueError("expected SHA must be a complete 40-hex git commit")
            actual = _git_head(root)
            if actual != expected:
                raise ValueError(
                    f"checked-out SHA {actual} does not match pinned {expected}"
                )
        if args.execute and not args.expected_sha:
            raise ValueError("execution requires --expected-sha (same pin for A and B)")
        result = plan(collect_tests(root), args.cohort, args.per_cohort)
        result["source_sha"] = _git_head(root) if (root / ".git").exists() else None
        if args.execute and not result["full_two_cohort_ready"]:
            raise ValueError(
                f"not enough unique unittest methods: {result['available_tests']} < {2 * args.per_cohort}"
            )
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as out:
                out.write(
                    f"matrix={json.dumps(result['matrix'], separators=(',', ':'))}\n"
                )
                out.write(f"ready={str(result['full_two_cohort_ready']).lower()}\n")
                out.write(f"count={result['selected_count']}\n")
                out.write(f"manifest_sha256={result['manifest_sha256']}\n")
        print(
            json.dumps(
                {k: v for k, v in result.items() if k != "matrix"}, sort_keys=True
            )
        )
        return 0
    except (ValueError, OSError, SyntaxError, subprocess.CalledProcessError) as exc:
        print(f"fleet-plan: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

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
from pathlib import Path
import re
import subprocess
import sys

MAX_PER_COHORT = 250
SUPPORTED_DIRECT_COUNTS = frozenset({8, 16, 32, 50, 64, 128, 250})
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


def plan(
    test_ids: list[str],
    cohort: str,
    per_cohort: int,
    *,
    absolute_offset: bool = False,
    start_index: int = 0,
) -> dict:
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
    if not isinstance(absolute_offset, bool):
        raise ValueError("absolute_offset must be boolean")
    if type(start_index) is not int or start_index < 0:
        raise ValueError("start_index must be a nonnegative integer")
    if absolute_offset:
        if per_cohort not in SUPPORTED_DIRECT_COUNTS:
            raise ValueError(
                "absolute fanout supports only known 8/16/32/50/64/128/250 counts"
            )
        if start_index % per_cohort:
            raise ValueError("start_index must be aligned to per_cohort")
        offset = start_index
    else:
        if start_index != 0:
            raise ValueError("start_index without absolute_offset is ambiguous")
        offset = 0 if cohort == "A" else per_cohort
    fingerprint = hashlib.sha256("\n".join(test_ids).encode()).hexdigest()
    full_two_ready = len(test_ids) >= 2 * per_cohort
    enough = len(test_ids) >= offset + per_cohort and (
        absolute_offset or full_two_ready
    )
    cases = test_ids[offset : offset + per_cohort] if enough else []
    return {
        "cohort": cohort,
        "per_cohort": per_cohort,
        "available_tests": len(test_ids),
        "full_two_cohort_ready": full_two_ready,
        "slice_ready": enough,
        "absolute_offset": absolute_offset,
        "start_index": offset,
        "manifest_sha256": fingerprint,
        "selected_count": len(cases),
        "matrix": {"include": [{"case": case} for case in cases]},
    }


def select_direct_case(result: dict, index: int) -> str:
    """Fail closed when a static direct matrix and source-derived plan disagree."""
    count = result["per_cohort"]
    if count not in SUPPORTED_DIRECT_COUNTS:
        raise ValueError(
            "direct fanout allows only 8,16,32,50,64,128,250 jobs per cohort"
        )
    if not result["slice_ready"]:
        raise ValueError("insufficient real methods for this exact source-bound slice")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < count:
        raise ValueError("direct shard index out of bounds")
    cases = result["matrix"]["include"]
    if len(cases) != count:
        raise ValueError("source plan/matrix length mismatch")
    case = cases[index]["case"]
    if not case or "\n" in case or "\r" in case:
        raise ValueError("unsafe test identifier")
    return case


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
    parser.add_argument("--absolute-offset", action="store_true")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--case-index", type=int, default=None)
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
        result = plan(
            collect_tests(root),
            args.cohort,
            args.per_cohort,
            absolute_offset=args.absolute_offset,
            start_index=args.start_index,
        )
        result["source_sha"] = _git_head(root) if (root / ".git").exists() else None
        if args.execute and not result["slice_ready"]:
            raise ValueError(
                "not enough unique unittest methods for requested source-bound slice"
            )
        if args.case_index is not None:
            if not args.execute:
                raise ValueError("direct shard selection requires --execute")
            result["selected_case"] = select_direct_case(result, args.case_index)
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as out:
                out.write(
                    f"matrix={json.dumps(result['matrix'], separators=(',', ':'))}\n"
                )
                out.write(f"ready={str(result['slice_ready']).lower()}\n")
                out.write(f"count={result['selected_count']}\n")
                out.write(f"manifest_sha256={result['manifest_sha256']}\n")
                if args.case_index is not None:
                    out.write(f"case={result['selected_case']}\n")
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

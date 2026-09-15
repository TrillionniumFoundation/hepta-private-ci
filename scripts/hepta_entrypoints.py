#!/usr/bin/env python3
"""Describe tracked script references without executing code or inferring dead code."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "site-packages",
}
SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".ps1"}
CALLER_SUFFIXES = SCRIPT_SUFFIXES | {".yml", ".yaml"}


def tracked_files(root: Path) -> list[Path]:
    """Use the index, excluding symlinks, environments and untracked artifacts."""
    raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage", "-z"])
    files = set()
    for entry in raw.decode("utf-8").split("\0"):
        if not entry:
            continue
        metadata, relative = entry.split("\t", 1)
        mode, _, stage = metadata.split()
        if stage != "0":
            raise ValueError(
                "resolve index conflicts before generating script navigation"
            )
        path = PurePosixPath(relative)
        if mode not in {"100644", "100755"} or EXCLUDED_PARTS.intersection(path.parts):
            continue
        target = root / relative
        if (
            not target.is_symlink()
            and target.is_file()
            and target.resolve().is_relative_to(root.resolve())
        ):
            files.add(Path(relative))
    return sorted(files)


def is_script(path: Path, text: str) -> bool:
    return path.parts[0] == "scripts" and (
        path.suffix in SCRIPT_SUFFIXES or text.startswith("#!")
    )


def imported_scripts(caller: Path, text: str, scripts: set[Path]) -> set[Path]:
    """Resolve static local imports; dynamic imports remain explicitly unknown."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [(name.name, 0) for name in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            modules = [(base, node.level)]
            modules.extend(
                (f"{base}.{name.name}".strip("."), node.level) for name in node.names
            )
        else:
            continue
        for module, level in modules:
            if not module or "*" in module:
                continue
            parts = module.split(".")
            if level:
                parent = caller.parent
                for _ in range(level - 1):
                    parent = parent.parent
                bases = [parent]
            else:
                bases = [Path(), caller.parent]
            for base in bases:
                target = base.joinpath(*parts)
                for candidate in (target.with_suffix(".py"), target / "__init__.py"):
                    if candidate in scripts and candidate != caller:
                        found.add(candidate)
    return found


def discovery_patterns(text: str) -> list[tuple[Path, str]]:
    """Recognize explicit unittest discovery declarations, not test execution."""
    patterns = []
    for match in re.finditer(
        r"\bunittest\s+discover\b([^\n]*)", text.replace("\\\n", " ")
    ):
        try:
            args = shlex.split(match[1], comments=True)
        except ValueError:
            continue
        start, pattern = None, "test*.py"
        for index, arg in enumerate(args):
            if arg in {
                "-s",
                "--start-directory",
                "-p",
                "--pattern",
            } and index + 1 < len(args):
                if arg in {"-s", "--start-directory"}:
                    start = args[index + 1]
                else:
                    pattern = args[index + 1]
            elif arg.startswith("--start-directory="):
                start = arg.partition("=")[2]
            elif arg.startswith("--pattern="):
                pattern = arg.partition("=")[2]
        # Unknown working directories, interpolations and implicit defaults are
        # not evidence that a particular repository test is discovered.
        if start is not None:
            path = PurePosixPath(start)
            if (
                not path.is_absolute()
                and ".." not in path.parts
                and not re.search(r"[$`{}]", start)
            ):
                patterns.append((Path(start), pattern))
    return patterns


def inventory(root: Path) -> dict[str, object]:
    files = tracked_files(root)
    texts = {}
    for path in files:
        if (
            path.parts[0] == "scripts"
            or path.suffix in CALLER_SUFFIXES
            or path.name in {"justfile", "Makefile", "package.json"}
        ):
            try:
                texts[path] = (root / path).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    scripts = {path for path, text in texts.items() if is_script(path, text)}
    references: dict[Path, set[tuple[str, str]]] = {path: set() for path in scripts}
    for caller, text in texts.items():
        # Navigation documents and generated indexes must not certify themselves.
        if caller.suffix not in CALLER_SUFFIXES and caller.name not in {
            "justfile",
            "Makefile",
            "package.json",
        }:
            continue
        name = caller.as_posix()
        for script in scripts:
            if script != caller and re.search(
                r"(?<![\w.-])" + re.escape(script.as_posix()) + r"(?![\w./-])", text
            ):
                references[script].add((name, "text-reference"))
        if caller.suffix == ".py":
            for script in imported_scripts(caller, text, scripts):
                references[script].add((name, "static-import"))
        for start, pattern in discovery_patterns(text):
            for script in scripts:
                if (
                    script != caller
                    and script.is_relative_to(start)
                    and fnmatch.fnmatchcase(script.name, pattern)
                ):
                    references[script].add((name, "discovery-pattern"))
    rows = []
    for script in sorted(scripts):
        evidence = sorted(references[script])
        rows.append(
            {
                "script": script.as_posix(),
                "status": "referenced" if evidence else "unknown",
                "references": [
                    {"caller": caller, "kind": kind} for caller, kind in evidence
                ],
            }
        )
    return {
        "schema": "hepta.script-entrypoints.v2",
        "scope": "tracked-working-tree-navigation-only",
        "scripts": rows,
    }


def markdown(document: dict[str, object]) -> str:
    lines = [
        "# Tracked script references",
        "",
        "References are navigation evidence, not proof of execution or liveness. Unknown never means safe to delete.",
        "",
        "| Script | Reference state | Declared references |",
        "|---|---|---|",
    ]
    for row in document["scripts"]:
        callers = (
            "; ".join(
                f"`{item['caller']}` ({item['kind']})" for item in row["references"]
            )
            or "Unknown"
        )
        lines.append(f"| `{row['script']}` | {row['status']} | {callers} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    try:
        document = inventory(args.root)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"entrypoint inventory failed: {error}\n")
    print(
        markdown(document)
        if args.format == "markdown"
        else json.dumps(document, indent=2),
        end="" if args.format == "markdown" else "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

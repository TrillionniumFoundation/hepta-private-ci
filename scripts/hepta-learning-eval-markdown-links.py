#!/usr/bin/env python3
"""Fail-closed local Markdown file and heading-anchor validation for learning.eval."""
from __future__ import annotations

import argparse
import html
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Iterable, Iterator
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
EXPLICIT_ID_RE = re.compile(
    r"<(?:a|span)\s+(?:[^>]*?\s)?id=[\"']([^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
REFERENCE_LINK_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(.+?)\s*$")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def markdown_documents(root: Path = ROOT) -> list[Path]:
    documents = sorted((root / "docs/modules/learning.eval").glob("*.md"))
    documents.extend(sorted((root / "codex-rs/hepta-intelligence-eval").glob("*.md")))
    dossier = root / "qualification/module-execution-dossiers/detail/learning.eval.md"
    if dossier.is_file():
        documents.append(dossier)
    return documents


def markdown_lines(path: Path) -> Iterator[tuple[int, str]]:
    fence: str | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.lstrip()
        marker = (
            "```"
            if stripped.startswith("```")
            else "~~~"
            if stripped.startswith("~~~")
            else None
        )
        if marker is not None:
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is None:
            yield number, line


def inline_link_targets(line: str) -> Iterator[str]:
    cursor = 0
    while True:
        open_at = line.find("](", cursor)
        if open_at < 0:
            return
        depth = 1
        index = open_at + 2
        escaped = False
        while index < len(line):
            character = line[index]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    yield line[open_at + 2 : index]
                    cursor = index + 1
                    break
            index += 1
        else:
            return


def link_destination(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith("<"):
        end = raw.find(">")
        if end < 0:
            raise ValueError(f"unterminated angle-bracket destination: {raw!r}")
        return raw[1:end]
    try:
        parts = shlex.split(raw, posix=True)
    except ValueError as error:
        raise ValueError(f"invalid Markdown destination: {raw!r}") from error
    return parts[0] if parts else ""


def github_heading_slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = html.unescape(text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for _, line in markdown_lines(path):
        anchors.update(unquote(value).lower() for value in EXPLICIT_ID_RE.findall(line))
        match = HEADING_RE.match(line)
        if match is None:
            continue
        base = github_heading_slug(match.group(2))
        if not base:
            continue
        ordinal = counts.get(base, 0)
        counts[base] = ordinal + 1
        anchors.add(base if ordinal == 0 else f"{base}-{ordinal}")
    return anchors


def reject_symlink_components(target: Path, root: Path) -> None:
    """Reject every lexical path component before any symlink is dereferenced."""
    relative = target.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(
                f"target path contains symlink {cursor.relative_to(root)}"
            )


def resolve_local_target(
    source: Path, destination: str, root: Path
) -> tuple[Path, str]:
    parsed = urlsplit(destination)
    path_text = unquote(parsed.path)
    anchor = unquote(parsed.fragment).lower()
    if path_text.startswith("/"):
        candidate = root / path_text.lstrip("/")
    elif path_text:
        candidate = source.parent / path_text
    else:
        candidate = source

    # abspath normalizes `.` and `..` without dereferencing symlinks. Checking
    # lexical components before resolve is essential: resolving first would make
    # `is_symlink()` observe the target rather than the link itself.
    target = Path(os.path.abspath(candidate))
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError(f"links outside the repository: {destination}") from error
    reject_symlink_components(target, root)
    return target, anchor


def validate_markdown_links(paths: Iterable[Path], root: Path = ROOT) -> None:
    root = root.resolve(strict=True)
    anchors: dict[Path, set[str]] = {}
    failures: list[str] = []
    sources: set[Path] = set()
    for path in paths:
        if path.is_symlink():
            raise ValueError(
                f"Markdown source is a symlink: {path.relative_to(root)}"
            )
        sources.add(path.resolve(strict=True))

    for source in sorted(sources):
        if source.suffix.lower() not in {".md", ".markdown"}:
            continue
        for line_number, line in markdown_lines(source):
            targets = list(inline_link_targets(line))
            reference = REFERENCE_LINK_RE.match(line)
            if reference is not None:
                targets.append(reference.group(1))
            for raw in targets:
                try:
                    destination = link_destination(raw)
                    if (
                        not destination
                        or destination.startswith("//")
                        or SCHEME_RE.match(destination)
                    ):
                        continue
                    target, anchor = resolve_local_target(source, destination, root)
                    if not target.exists():
                        raise ValueError(f"missing target {target.relative_to(root)}")
                    if not target.is_file() and anchor:
                        raise ValueError(
                            f"anchor target is not a file {target.relative_to(root)}"
                        )
                    if anchor and target.suffix.lower() in {".md", ".markdown"}:
                        known = anchors.setdefault(target, markdown_anchors(target))
                        if anchor not in known:
                            raise ValueError(
                                f"missing anchor #{anchor} in {target.relative_to(root)}"
                            )
                except (OSError, ValueError) as error:
                    failures.append(f"{source.relative_to(root)}:{line_number}: {error}")
    if failures:
        raise ValueError("Markdown link validation failed:\n" + "\n".join(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    try:
        documents = markdown_documents(root)
        if not documents:
            raise ValueError("learning.eval Markdown inventory is empty")
        validate_markdown_links(documents, root)
        print(f"learning.eval Markdown links: PASS ({len(documents)} documents)")
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

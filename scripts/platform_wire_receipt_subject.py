"""Bind a lifecycle report to the selected source, not just mutually agreeing receipts."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate receipt field: {key}")
        result[key] = value
    return result


def read_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("symlinked receipt rejected")
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("receipt exceeds 4 MiB")
    value = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError("receipt must be an object")
    return value


def require_selected_source(root: Path, source: str, expected: str | None) -> None:
    """Git worktrees bind HEAD; detached archives require an explicit subject.

    Explicit archive selection is not provenance authentication. The consumer
    must verify the archive and workflow origin separately. A Git worktree
    cannot override its actual HEAD with a convenient historical receipt SHA.
    """
    if expected is not None and (not isinstance(expected, str) or SHA.fullmatch(expected) is None):
        raise ValueError("expected source must be lowercase 40-hex")
    if not (root / ".git").exists():
        if expected is None:
            raise ValueError("archive evidence requires --expected-source-sha")
        if source != expected:
            raise ValueError("receipt source differs from the selected candidate")
        return
    try:
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            text=True, stderr=subprocess.DEVNULL, timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise ValueError("cannot verify the Git checkout identity") from None
    if SHA.fullmatch(head) is None:
        raise ValueError("Git did not return a valid source identity")
    if expected is not None and expected != head:
        raise ValueError("expected source differs from the current checkout")
    expected = head
    if source != expected:
        raise ValueError("receipt source differs from the selected candidate")

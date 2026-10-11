"""Cross-platform canonical repository paths shared by Lane G owners.

The module is deliberately independent of storage.  It raises the canonical
``EngineeringError`` lazily so it can replace the legacy helpers during package
initialization without a circular import.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
import unicodedata

MAX_PATH_BYTES = 1024
MAX_PATHS = 256
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
_GIT_ADMIN_ALIASES = frozenset({".git", "git~1"})


def _error(code: str) -> None:
    from .control_plane import EngineeringError

    raise EngineeringError(code)


def _bounded_tuple(values: Iterable[str], limit: int, code: str) -> tuple[str, ...]:
    if type(limit) is not int or limit < 0:
        _error("invalid_bound")
    iterator = iter(values)
    result: list[str] = []
    for _ in range(limit + 1):
        try:
            result.append(next(iterator))
        except StopIteration:
            return tuple(result)
    _error(code)


def canonical_repo_path(raw: str) -> str:
    """Return one alias-resistant, platform-independent repository path."""
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _error("invalid_path")
    if raw != unicodedata.normalize("NFC", raw):
        _error("noncanonical_unicode")
    if "\\" in raw or raw.startswith("/") or raw.endswith("/") or "//" in raw:
        _error("invalid_path")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        _error("invalid_path")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        _error("path_limit_exceeded")
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _error("invalid_path")
    for part in parts:
        if part != part.strip() or part.endswith((".", " ")) or ":" in part:
            _error("invalid_path")
        if any(token in part for token in ("*", "?", "[", "]")):
            _error("unsupported_glob")
        folded = unicodedata.normalize("NFC", part).casefold()
        device = folded.split(".", 1)[0]
        if device in _WINDOWS_RESERVED or folded in _GIT_ADMIN_ALIASES:
            _error("invalid_path")
    value = "/".join(parts)
    if value != raw:
        _error("invalid_path")
    return value


def canonical_path_key(raw: str) -> str:
    return unicodedata.normalize("NFC", canonical_repo_path(raw)).casefold()


def canonical_paths(
    values: Iterable[str],
    *,
    limit: int = MAX_PATHS,
) -> tuple[str, ...]:
    raw = _bounded_tuple(values, limit, "path_limit_exceeded")
    normalized = tuple(canonical_repo_path(value) for value in raw)
    aliases: dict[str, str] = {}
    for value in normalized:
        key = canonical_path_key(value)
        previous = aliases.setdefault(key, value)
        if previous != value:
            _error("invalid_path")
    result = tuple(sorted(set(normalized)))
    if not result:
        _error("empty_paths")
    return result


def paths_overlap(left: str, right: str) -> bool:
    a = canonical_path_key(left)
    b = canonical_path_key(right)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def path_sets_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
    return any(paths_overlap(a, b) for a in left for b in right)


def path_is_within(path: str, roots: Sequence[str]) -> bool:
    value = canonical_path_key(path)
    return any(
        value == canonical_path_key(root)
        or value.startswith(canonical_path_key(root) + "/")
        for root in roots
    )

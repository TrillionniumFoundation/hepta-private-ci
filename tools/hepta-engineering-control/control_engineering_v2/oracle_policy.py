"""Non-self-modifiable oracle path policy for autonomous candidates."""

from __future__ import annotations

from pathlib import PurePosixPath

from .control_plane import canonical_repo_path

_ORACLE_SEGMENTS = frozenset(
    {
        ".github",
        "qualification",
        "qa",
        "tests",
        "test",
        "fixtures",
        "goldens",
        "snapshots",
    }
)
_ORACLE_BASENAMES = frozenset(
    {
        "CODEOWNERS",
        "CALLERS.toml",
        "AGENTS.md",
    }
)


def is_oracle_path(value: str) -> bool:
    """Return true for repository paths that may judge the candidate itself.

    The rule is intentionally conservative. Autonomous candidate generation may
    change product source, but test/evaluator/fixture/policy surfaces are owned
    by an independent path and cannot be modified by the candidate under test.
    """
    path = canonical_repo_path(value)
    parts = PurePosixPath(path).parts
    if any(part.casefold() in _ORACLE_SEGMENTS for part in parts):
        return True
    name = parts[-1] if parts else ""
    folded = name.casefold()
    if name in _ORACLE_BASENAMES:
        return True
    if folded.startswith("test_") or folded.startswith("tests_"):
        return True
    if folded.endswith(
        (
            "_test.py",
            "_tests.py",
            "_test.rs",
            "_tests.rs",
            ".snap",
            ".golden",
        )
    ):
        return True
    if "/scripts/" in f"/{path}/" or path.startswith("scripts/"):
        return True
    if path.startswith("docs/security/") or path.startswith("docs/governance/"):
        return True
    if path.startswith("docs/contracts/") or path.startswith("docs/architecture/"):
        return True
    if path.startswith("tools/hepta-engineering-control/"):
        return True
    return False

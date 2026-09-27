#!/usr/bin/env python3
"""Fail closed when runtime.agentd gains an unreviewed RunStart admission path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "codex-rs" / "hepta-agentd" / "src"


@dataclass(frozen=True)
class BoundaryRule:
    token: str
    allowed_paths: frozenset[str]


RULES = (
    BoundaryRule(
        "start_current_run_start_record(",
        frozenset({"state.rs", "run_start_authority.rs"}),
    ),
    BoundaryRule(
        "start_canonical_intelligence(",
        frozenset({"state.rs", "run_start_authority.rs"}),
    ),
    BoundaryRule(
        "start_revalidated_run_start(",
        frozenset({"state.rs", "lane_b_runtime.rs"}),
    ),
    BoundaryRule(
        "RunSnapshot::from_revalidated_run_start(",
        frozenset({"lane_b_runtime.rs"}),
    ),
    BoundaryRule(
        "authentication_is_current(",
        frozenset({"objective_runtime.rs", "run_start_authority.rs", "state.rs"}),
    ),
)


class BoundaryError(ValueError):
    pass


def rust_sources(root: Path = SOURCE_ROOT) -> list[Path]:
    return sorted(path for path in root.rglob("*.rs") if path.is_file())


def relative(path: Path, root: Path = SOURCE_ROOT) -> str:
    return path.relative_to(root).as_posix()


def token_locations(
    token: str, sources: Iterable[Path], root: Path = SOURCE_ROOT
) -> list[tuple[str, int]]:
    locations: list[tuple[str, int]] = []
    for path in sources:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if token in line:
                locations.append((relative(path, root), number))
    return locations


def validate(root: Path = SOURCE_ROOT) -> list[str]:
    sources = rust_sources(root)
    errors: list[str] = []
    for rule in RULES:
        locations = token_locations(rule.token, sources, root)
        if not locations:
            errors.append(f"missing guarded symbol: {rule.token}")
            continue
        for path, line in locations:
            if path not in rule.allowed_paths:
                errors.append(
                    f"unreviewed RunStart authority path {path}:{line}: {rule.token}"
                )

    objective = (root / "objective_runtime.rs").read_text(encoding="utf-8")
    required = (
        "verify_current_run_start(agentd, record)?.admit_compatibility()?",
        "let verified = verify_current_run_start(agentd, &record)?;",
        "verified.admit().await?",
    )
    for marker in required:
        if marker not in objective:
            errors.append(f"objective admission lost sealed witness marker: {marker}")
    for forbidden in (
        "agentd.start_current_run_start_record(&record)",
        "agentd.start_canonical_intelligence(&record)",
    ):
        if forbidden in objective:
            errors.append(f"objective admission regained raw bypass: {forbidden}")

    authority = (root / "run_start_authority.rs").read_text(encoding="utf-8")
    for forbidden in (
        "#[derive(Clone",
        "impl Clone for VerifiedRunStartV1",
        "pub struct VerifiedRunStartV1",
    ):
        if forbidden in authority:
            errors.append(f"sealed witness became forgeable or copyable: {forbidden}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"FAIL_RUNTIME_AGENTD_TRUST_BOUNDARY: {error}", file=sys.stderr)
        return 1
    print("PASS_RUNTIME_AGENTD_TRUST_BOUNDARY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

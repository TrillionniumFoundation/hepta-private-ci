#!/usr/bin/env python3
"""Apply the final scoped native lint repair for the kernel.evidence candidate.

This script changes no qualification, deployment, acceptance, canary, promotion,
or release status. It repairs only the owner-local AuthBus SQLite lint boundary
and three mechanically equivalent method-call closures observed in retained
exact-head diagnostics.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    text = read(path)
    observed = text.count(old)
    if observed != expected:
        raise SystemExit(
            f"{path}: expected {expected} exact matches, observed {observed}: {old[:160]!r}"
        )
    write(path, text.replace(old, new, expected))


def main() -> None:
    replace_exact(
        "codex-rs/hepta-authbus/src/authority_schema.rs",
        "pub(crate) async fn verify_schema(\n",
        """#[expect(
    clippy::disallowed_methods,
    reason = "AuthBus owns this isolated in-memory migration reference and closes it before returning"
)]
pub(crate) async fn verify_schema(
""",
    )
    replace_exact(
        "codex-rs/hepta-authbus/src/authority_store.rs",
        "    pub async fn open(path: &Path) -> Result<Self, AuthBusAuthorityError> {\n",
        """    #[expect(
        clippy::disallowed_methods,
        reason = "AuthBus owns this standalone authoritative SQLite lineage and applies its migration and integrity policy here"
    )]
    pub async fn open(path: &Path) -> Result<Self, AuthBusAuthorityError> {
""",
    )

    closure = ".is_some_and(|database| database.is_unique_violation())"
    method = ".is_some_and(sqlx::error::DatabaseError::is_unique_violation)"
    replace_exact(
        "codex-rs/hepta-authbus/src/authority_store.rs",
        closure,
        method,
    )
    replace_exact(
        "codex-rs/hepta-authbus/src/quota_store.rs",
        closure,
        method,
    )
    replace_exact(
        "codex-rs/hepta-authbus/src/trust_store.rs",
        closure,
        method,
    )


if __name__ == "__main__":
    main()

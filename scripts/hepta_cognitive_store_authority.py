#!/usr/bin/env python3
"""Fail closed when cognitive.store production authority drifts.

This check is intentionally narrow: it protects the repository-controlled
single-ingress invariants without claiming target-host qualification, operator
acceptance, or release. Durable implementation details may remain in
``hepta-memory``; product runtime must enter them through ``cognitive.store``.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FACADE = ROOT / "codex-rs/hepta-cognitive-store/src/lib.rs"
FACADE_CARGO = ROOT / "codex-rs/hepta-cognitive-store/Cargo.toml"
DURABLE_SNAPSHOT = ROOT / "codex-rs/hepta-memory/src/lane_c_snapshot.rs"
STATUS = ROOT / "docs/modules/cognitive.store/STATUS.json"
MIGRATION = ROOT / "docs/modules/cognitive.store/MIGRATION.md"

# These are the product/runtime callsites that can create the Agent-local owner.
# Tests and the persistence engine itself may open fixtures directly.
PRODUCT_OPENERS = (
    ROOT / "codex-rs/hepta-agentd/src/runtime.rs",
    ROOT / "codex-rs/hepta-agentd/src/production_writer_host.rs",
)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def verify() -> list[str]:
    failures: list[str] = []

    facade = text(FACADE)
    for needle in (
        "pub use codex_hepta_memory::CognitiveStore;",
        "pub async fn open_authoritative(",
        "pub struct QualificationSemanticStore",
    ):
        if needle not in facade:
            failures.append(f"cognitive.store facade missing {needle!r}")
    if "pub struct CognitiveStore {" in facade:
        failures.append("in-memory qualification store regained canonical CognitiveStore name")

    cargo = text(FACADE_CARGO)
    if 'codex-hepta-memory = { path = "../hepta-memory" }' not in cargo:
        failures.append("cognitive.store is not bound to the durable SQLite backend")

    for path in PRODUCT_OPENERS:
        source = text(path)
        rel = path.relative_to(ROOT)
        if "CognitiveStore::open(" in source:
            failures.append(f"{rel}: bypasses cognitive.store authoritative opener")
        if "open_authoritative" not in source:
            failures.append(f"{rel}: canonical cognitive.store opener is not used")

    durable = text(DURABLE_SNAPSHOT)
    for needle in (
        "kg_revision_fact_sets",
        "knowledge_facts:",
        "knowledge_fact_frontier",
        "JOIN memory_revisions",
    ):
        if needle not in durable:
            failures.append(f"durable knowledge-fact projection missing {needle!r}")

    if not STATUS.is_file():
        failures.append("cognitive.store STATUS.json is missing")
    else:
        try:
            status = json.loads(text(STATUS))
        except Exception as exc:  # pragma: no cover - diagnostic path
            failures.append(f"cognitive.store STATUS.json invalid: {exc}")
        else:
            if status.get("module") != "cognitive.store":
                failures.append("cognitive.store STATUS.json identity mismatch")
            if status.get("canonicalProductionIngress") != (
                "codex_hepta_cognitive_store::open_authoritative"
            ):
                failures.append("STATUS.json does not name the canonical production ingress")
            if status.get("durableBackend") != "hepta-memory::CognitiveStore/cognitive_1.sqlite3":
                failures.append("STATUS.json durable backend drift")

    if not MIGRATION.is_file():
        failures.append("cognitive.store migration/cutover runbook is missing")

    return failures


def main() -> None:
    failures = verify()
    if failures:
        raise SystemExit("FAIL_COGNITIVE_STORE_AUTHORITY: " + "; ".join(failures))
    print("PASS_COGNITIVE_STORE_AUTHORITY")


if __name__ == "__main__":
    main()

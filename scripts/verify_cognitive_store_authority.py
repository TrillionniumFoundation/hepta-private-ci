#!/usr/bin/env python3
"""Fail closed on product composition that bypasses cognitive.store.

The durable SQLite implementation is intentionally still located in
codex-hepta-memory.  This check prevents that physical placement from becoming
another product authority: canonical runtime/store opens and production-writer
composition must enter through codex-hepta-cognitive-store, while semantic V1/V2
oracles must not appear in product runtime code.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

CANONICAL_COMPOSITION = {
    pathlib.Path("codex-rs/hepta-agentd/src/runtime.rs"),
    pathlib.Path("codex-rs/hepta-agentd/src/production_writer_host.rs"),
}

BACKEND_OPEN_PATTERNS = (
    re.compile(r"codex_hepta_memory::CognitiveStore::open\s*\("),
    re.compile(r"use\s+codex_hepta_memory::CognitiveStore\s*;[\s\S]*?CognitiveStore::open\s*\("),
)

BACKEND_WRITER_PATTERNS = (
    re.compile(r"codex_hepta_memory::ProductionDurableWriter"),
    re.compile(r"use\s+codex_hepta_memory::ProductionDurableWriter\s*;"),
)

ORACLE_PATTERN = re.compile(r"\b(?:AdmittedCognitiveStoreV2|QualificationCognitiveStoreV1)\b")


def read(relative: pathlib.Path) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def main() -> int:
    failures: list[str] = []

    for relative in sorted(CANONICAL_COMPOSITION):
        text = read(relative)
        if "codex_hepta_cognitive_store::CognitiveStore" not in text:
            failures.append(f"{relative}: canonical CognitiveStore facade import missing")
        for pattern in BACKEND_OPEN_PATTERNS + BACKEND_WRITER_PATTERNS:
            if pattern.search(text):
                failures.append(f"{relative}: direct hepta-memory authority bypass")

    # Exact fully-qualified backend opens are never allowed outside the backend
    # crate itself. Test helpers may import the concrete type, but product code
    # must not spell a direct backend open across a crate boundary.
    for path in (ROOT / "codex-rs").rglob("*.rs"):
        relative = path.relative_to(ROOT)
        if str(relative).startswith("codex-rs/hepta-memory/"):
            continue
        text = path.read_text(encoding="utf-8")
        if "codex_hepta_memory::CognitiveStore::open(" in text:
            failures.append(f"{relative}: fully-qualified backend CognitiveStore::open")

        # In-memory semantic stores are qualification oracles, not runtime
        # persistence. Ignore their owner crate and Rust test-only sections.
        if str(relative).startswith("codex-rs/hepta-cognitive-store/"):
            continue
        product_text = text.split("#[cfg(test)]", 1)[0]
        if ORACLE_PATTERN.search(product_text):
            failures.append(f"{relative}: semantic oracle composed into product runtime")

    if failures:
        print("cognitive.store authority verification failed:", file=sys.stderr)
        for failure in sorted(set(failures)):
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("cognitive.store authority verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

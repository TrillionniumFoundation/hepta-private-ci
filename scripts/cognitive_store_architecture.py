#!/usr/bin/env python3
"""Closed-world cognitive.store architecture check.

The check rejects orphan Rust modules, a second product-write facade, raw
durable-store imports in serving code, direct mutation calls outside the
owner/qualification set, and a public default-build writer escape hatch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads(
    (ROOT / "docs/modules/cognitive.store/ARCHITECTURE_BOUNDARY.json").read_text(
        encoding="utf-8"
    )
)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def qualification_path(path: str) -> bool:
    return any(marker in path for marker in POLICY["qualificationMarkers"])


def rust_files() -> list[Path]:
    return sorted((ROOT / "codex-rs").rglob("*.rs"))


def referenced_modules(src: Path) -> set[str]:
    result: set[str] = set()
    for path in src.glob("*.rs"):
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r'#\s*\[\s*path\s*=\s*"([^"]+)"\s*\]', text):
            result.add((path.parent / target).resolve().as_posix())
        for name in re.findall(
            r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;",
            text,
        ):
            flat = path.parent / f"{name}.rs"
            nested = path.parent / name / "mod.rs"
            if flat.exists():
                result.add(flat.resolve().as_posix())
            elif nested.exists():
                result.add(nested.resolve().as_posix())
    return result


def main() -> None:
    failures: list[str] = []
    src = ROOT / POLICY["orphanCheckedRoot"]
    referenced = referenced_modules(src)
    for path in sorted(src.glob("*.rs")):
        if path.name == "lib.rs":
            continue
        if path.resolve().as_posix() not in referenced:
            failures.append(
                f"orphan Rust source is not reachable from the crate root: {rel(path)}"
            )

    forbidden_dead = [
        ROOT / "codex-rs/hepta-cognitive-store/src/production.rs",
        ROOT / "codex-rs/hepta-cognitive-store/src/production_tests.rs",
    ]
    for path in forbidden_dead:
        if path.exists():
            failures.append(f"superseded production facade still exists: {rel(path)}")

    facade = POLICY["canonicalProductWriteFacade"]
    host_path = ROOT / facade["path"]
    host_text = host_path.read_text(encoding="utf-8")
    if f"pub struct {facade['symbol']}" not in host_text:
        failures.append("canonical product-write facade symbol is missing")
    for method in ("remember_with_kg", "correct_with_kg", "forget_with_kg"):
        if f"pub async fn {method}" not in host_text:
            failures.append(f"canonical facade is missing {method}")
    if "pub(crate) fn production_mutation" not in host_text:
        failures.append("sealed mutation capability escapes the Agentd crate")
    if (
        '#[cfg(feature = "qualification-cognitive-write")]\n    pub fn writer'
        not in host_text
    ):
        failures.append("raw writer accessor is not qualification-feature gated")
    if (
        '#[cfg(not(feature = "qualification-cognitive-write"))]\n    pub(crate) fn writer'
        not in host_text
    ):
        failures.append("default-build raw writer accessor is not crate-private")

    allowed_raw = set(POLICY["rawBackendAllowedNonTestPaths"])
    # Match complete Rust identifiers. A substring test would incorrectly
    # classify `CognitiveStoreError` as the mutable `CognitiveStore` type.
    raw_patterns = (
        re.compile(r"\bcodex_hepta_memory::CognitiveStore\b"),
        re.compile(r"\bDurableCognitiveStore\s+as\s+CognitiveStore\b"),
        re.compile(r"\bDurableCognitiveStore::open\b"),
    )
    owner_roots = tuple(POLICY["rawOwnerRoots"])
    mutation_patterns = tuple(
        re.compile(rf"\.\s*{re.escape(name)}\s*\(")
        for name in POLICY["directMutationMethods"]
    )
    for path in rust_files():
        path_s = rel(path)
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in raw_patterns):
            if (
                not path_s.startswith(owner_roots)
                and path_s not in allowed_raw
                and not qualification_path(path_s)
            ):
                failures.append(
                    f"raw mutable cognitive backend imported by product source: {path_s}"
                )
        if any(pattern.search(text) for pattern in mutation_patterns):
            if not path_s.startswith(owner_roots) and not qualification_path(path_s):
                failures.append(
                    f"direct cognitive mutation outside owner/qualification code: {path_s}"
                )

    map_path = ROOT / "docs/modules/cognitive.store/IMPLEMENTATION_MAP.json"
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    callers = mapping.get("productCallers", [])
    canonical = [
        caller
        for caller in callers
        if caller.get("state") == "canonical_production_write_facade"
    ]
    if len(canonical) != 1:
        failures.append(
            "implementation map must contain exactly one canonical production-write facade"
        )
    elif (
        canonical[0].get("sourcePath") != facade["path"]
        or canonical[0].get("nativeSymbol") != facade["symbol"]
    ):
        failures.append(
            "implementation map canonical facade disagrees with architecture policy"
        )

    closure = (
        ROOT / "docs/modules/cognitive.store/PRODUCTION_CLOSURE.md"
    ).read_text(encoding="utf-8")
    if (
        "AgentdProductionWriterHost" not in closure
        or "unique canonical production-write facade" not in closure
    ):
        failures.append("production closure does not state the unique canonical facade")

    if failures:
        raise SystemExit(
            "FAIL_COGNITIVE_STORE_ARCHITECTURE: " + "; ".join(failures)
        )
    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_STORE_ARCHITECTURE",
                "canonicalFacade": facade,
                "orphanRustFiles": 0,
                "rawBackendServingViolations": 0,
                "directMutationViolations": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

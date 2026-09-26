#!/usr/bin/env python3
"""Closed-world architecture checks for the cognitive.store product boundary."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
STORE_ROOT = ROOT / "codex-rs" / "hepta-cognitive-store"
STORE_SRC = STORE_ROOT / "src"
MAP_PATH = ROOT / "docs" / "modules" / "cognitive.store" / "IMPLEMENTATION_MAP.json"
CLOSURE_PATH = ROOT / "docs" / "modules" / "cognitive.store" / "PRODUCTION_CLOSURE.md"

CANONICAL_PRODUCT_HOST = "AgentdProductionWriterHost"
CANONICAL_HOST_PATH = Path("codex-rs/hepta-agentd/src/production_writer_host.rs")

# These roots contain serving/product code. Tests, examples, qualification-only
# adapters and the physical owner are checked by their own package tests and are
# intentionally excluded from the product bypass scan.
PRODUCT_ROOTS = (
    Path("codex-rs/hepta-agentd/src"),
    Path("codex-rs/app-server/src"),
    Path("codex-rs/core/src"),
    Path("codex-rs/model-provider/src"),
    Path("codex-rs/hepta-infer-worker/src"),
    Path("codex-rs/hepta-infer-worker-host/src"),
)

QUALIFICATION_ONLY_NAMES = {
    "qualification_writer.rs",
    "test_support.rs",
}

RAW_OWNER_IMPORT = re.compile(r"codex_hepta_memory::CognitiveStore(?:\b|::)")
DIRECT_MUTATION = re.compile(
    r"\.(?:remember_memory|correct_memory|forget_memory|create_memory|"
    r"revise_memory|append_source|admit_memory_candidate)\s*\("
)


class Invalid(RuntimeError):
    pass


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise Invalid(f"missing required file: {path.relative_to(ROOT)}") from error


def git_head() -> str:
    explicit = os.environ.get("TESTED_SHA") or os.environ.get("GITHUB_SHA")
    if explicit:
        return explicit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def verify_feature_boundary() -> dict[str, object]:
    cargo = read(STORE_ROOT / "Cargo.toml")
    durable = read(STORE_SRC / "durable.rs")
    crate_root = read(STORE_SRC / "lib.rs")

    require(
        "agentd-production-host = []" in cargo,
        "cognitive-store must declare the named Agentd host feature",
    )
    require(
        'qualification-cognitive-write = ["agentd-production-host"]' in cargo,
        "qualification feature must extend the same named host feature",
    )
    require(
        'feature = "agentd-production-host"' in durable
        and "CognitiveStore as DurableCognitiveStore" in durable,
        "raw durable alias must be gated in durable.rs",
    )
    require(
        'feature = "agentd-production-host"' in crate_root
        and "pub use durable::DurableCognitiveStore;" in crate_root,
        "crate root must preserve the raw alias gate",
    )
    require(
        not (STORE_SRC / "production.rs").exists()
        and not (STORE_SRC / "production_tests.rs").exists(),
        "the superseded uncompiled ProductionCognitiveStore façade must be absent",
    )
    return {
        "rawMutableAliasDefaultVisible": False,
        "namedHostFeature": "agentd-production-host",
        "qualificationFeature": "qualification-cognitive-write",
    }


def module_reference_patterns(file: Path) -> tuple[re.Pattern[str], re.Pattern[str]]:
    stem = re.escape(file.stem)
    filename = re.escape(file.name)
    return (
        re.compile(rf"\bmod\s+{stem}\s*;"),
        re.compile(rf"#\s*\[\s*path\s*=\s*\"{filename}\"\s*\]"),
    )


def verify_no_orphan_modules() -> list[str]:
    rust_files = sorted(STORE_SRC.glob("*.rs"))
    corpus = {
        path: path.read_text(encoding="utf-8")
        for path in rust_files
        if path.name != "lib.rs"
    }
    corpus[STORE_SRC / "lib.rs"] = read(STORE_SRC / "lib.rs")
    checked: list[str] = []
    for candidate in rust_files:
        if candidate.name == "lib.rs":
            continue
        mod_pattern, path_pattern = module_reference_patterns(candidate)
        referenced = any(
            source != candidate
            and (mod_pattern.search(text) is not None or path_pattern.search(text) is not None)
            for source, text in corpus.items()
        )
        require(
            referenced,
            f"orphan Rust source is not reachable from the crate graph: "
            f"{candidate.relative_to(ROOT)}",
        )
        checked.append(str(candidate.relative_to(ROOT)))
    return checked


def iter_product_sources() -> Iterable[Path]:
    for relative_root in PRODUCT_ROOTS:
        root = ROOT / relative_root
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.rs")):
            if (
                path.name.endswith("_tests.rs")
                or path.name in QUALIFICATION_ONLY_NAMES
                or "tests" in path.parts
                or "examples" in path.parts
            ):
                continue
            yield path


def verify_no_product_bypass() -> list[str]:
    checked: list[str] = []
    violations: list[str] = []
    for path in iter_product_sources():
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if RAW_OWNER_IMPORT.search(text) and relative != CANONICAL_HOST_PATH:
            violations.append(
                f"{relative}: imports hepta-memory::CognitiveStore outside the canonical host"
            )
        if DIRECT_MUTATION.search(text):
            violations.append(
                f"{relative}: invokes a raw semantic mutation instead of the sealed capability"
            )
        checked.append(str(relative))
    require(not violations, "product cognitive boundary violations:\n- " + "\n- ".join(violations))
    return checked


def verify_machine_mapping() -> dict[str, object]:
    mapping = json.loads(read(MAP_PATH))
    operations = mapping.get("operations")
    require(isinstance(operations, list), "implementation map operations must be a list")
    hosts = [
        row
        for row in operations
        if isinstance(row, dict) and row.get("operation") == "product_writer_host"
    ]
    require(len(hosts) == 1, "implementation map must declare exactly one product writer host")
    host = hosts[0]
    require(
        host.get("nativeSymbol") == CANONICAL_PRODUCT_HOST
        and host.get("sourcePath") == str(CANONICAL_HOST_PATH),
        "implementation map product writer host differs from the canonical Agentd host",
    )
    closure = read(CLOSURE_PATH)
    require(
        CANONICAL_PRODUCT_HOST in closure,
        "production closure must name AgentdProductionWriterHost as the canonical façade",
    )
    require(
        "ProductionCognitiveStore" not in closure,
        "production closure still names the retired façade",
    )
    return {
        "canonicalProductFacade": CANONICAL_PRODUCT_HOST,
        "canonicalProductFacadePath": str(CANONICAL_HOST_PATH),
        "declaredProductWriterHosts": len(hosts),
    }


def verify(output: Path | None) -> dict[str, object]:
    receipt = {
        "schema": "hepta.cognitive-store-boundary-verification.v1",
        "testedSha": git_head(),
        "featureBoundary": verify_feature_boundary(),
        "reachableRustSources": verify_no_orphan_modules(),
        "productSourcesChecked": verify_no_product_bypass(),
        "mapping": verify_machine_mapping(),
        "result": "pass",
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = verify(args.output)
    except (Invalid, json.JSONDecodeError) as error:
        print(f"cognitive.store boundary verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

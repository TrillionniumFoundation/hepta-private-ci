#!/usr/bin/env python3
"""Fail-closed current-state verifier for context.compiler.

The verifier deliberately checks repository facts rather than prose intent:
source ancestry/tree identity, exact source objects, native operation symbols,
product caller symbols and the explicit partial-composition boundary.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json"
CURRENT_PATH = ROOT / "docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md"
HEX40 = re.compile(r"[0-9a-f]{40}")


class Invalid(ValueError):
    pass


def need(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        need(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def git(*args: str) -> str:
    process = subprocess.run(
        ["git", "--literal-pathspecs", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    need(process.returncode == 0, process.stderr.strip() or f"git {' '.join(args)} failed")
    return process.stdout.strip()


def source_contains(path: str, symbol: str) -> None:
    candidate = ROOT / path
    need(candidate.is_file(), f"missing source path: {path}")
    text = candidate.read_text(encoding="utf-8")
    need(re.search(rf"\b{re.escape(symbol)}\b", text) is not None, f"missing symbol {symbol} in {path}")


def main() -> None:
    need(MAP.is_file(), "missing context.compiler implementation map")
    need(CURRENT_PATH.is_file(), "missing current product path document")
    row = json.loads(MAP.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)

    need(row.get("schema") == "hepta.module-implementation-map.v3", "implementation-map schema")
    need(row.get("schemaVersion") == 3, "implementation-map schema version")
    need(row.get("module") == "context.compiler", "implementation-map module")
    need(row.get("workPackageState") == "source_complete_product_integration_in_progress", "work-package state")
    need(row.get("currentProductPath") == "docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md", "current-product-path binding")
    need(row.get("productionImplementation") is False, "production implementation must remain false")

    source_base = row.get("sourceBase")
    need(isinstance(source_base, dict) and set(source_base) == {"commit", "tree"}, "source base")
    commit = source_base.get("commit")
    tree = source_base.get("tree")
    need(isinstance(commit, str) and HEX40.fullmatch(commit) is not None, "source commit")
    need(isinstance(tree, str) and HEX40.fullmatch(tree) is not None, "source tree")
    need(git("rev-parse", f"{commit}^{{tree}}") == tree, "source tree mismatch")
    git("merge-base", "--is-ancestor", commit, "HEAD")

    operations = row.get("operations")
    need(isinstance(operations, list) and operations, "operations")
    by_operation = {entry.get("operation"): entry for entry in operations if isinstance(entry, dict)}
    for operation in (
        "verify_admission_snapshot_v2",
        "verify_admission_snapshot_successor_v2",
        "verify_admission_v2",
        "compile_v2",
        "record_serialization",
        "build_attachment",
        "prepare_delivery_v2",
        "observe_delivery",
    ):
        entry = by_operation.get(operation)
        need(isinstance(entry, dict), f"missing operation: {operation}")
        path = entry.get("sourcePath")
        symbol = entry.get("nativeSymbol")
        need(isinstance(path, str) and isinstance(symbol, str), f"invalid operation mapping: {operation}")
        source_contains(path, symbol)

    need("product_composed" in str(by_operation["compile_v2"].get("state")), "compile_v2 product state")
    need("provisional_codec" in str(by_operation["record_serialization"].get("state")), "serialization trust boundary")
    need("not_effect_bound" in str(by_operation["prepare_delivery_v2"].get("state")), "prepare boundary truth")
    need("not_product_composed" in str(by_operation["observe_delivery"].get("state")), "observe boundary truth")

    callers = row.get("productCallers")
    need(isinstance(callers, list) and callers, "product callers")
    caller_keys = set()
    for caller in callers:
        need(isinstance(caller, dict), "product caller entry")
        path = caller.get("sourcePath")
        symbol = caller.get("nativeSymbol")
        need(isinstance(path, str) and isinstance(symbol, str), "product caller binding")
        source_contains(path, symbol)
        caller_keys.add((path, symbol))
    need(
        ("codex-rs/hepta-agentd/src/prompt_runtime.rs", "AgentdPromptPipelineOwner") in caller_keys,
        "missing AgentdPromptPipelineOwner",
    )
    need(
        ("codex-rs/hepta-agentd/src/prompt_runtime.rs", "compile_and_stage") in caller_keys,
        "missing compile_and_stage caller",
    )

    source_objects = row.get("sourceObjects")
    need(isinstance(source_objects, list) and source_objects, "source objects")
    seen: set[str] = set()
    for entry in source_objects:
        need(isinstance(entry, dict), "source object entry")
        path = entry.get("path")
        object_id = entry.get("object")
        need(isinstance(path, str) and path and path not in seen, "source object path")
        need(isinstance(object_id, str) and HEX40.fullmatch(object_id) is not None, f"source object id: {path}")
        need((ROOT / path).exists(), f"missing source object path: {path}")
        need(git("rev-parse", f"HEAD:{path}") == object_id, f"source object drift: {path}")
        seen.add(path)

    required_objects = {
        "codex-rs/hepta-context-compiler/src/v2.rs",
        "codex-rs/hepta-intelligence/src/prompt_pipeline.rs",
        "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
        "codex-rs/hepta-agentd/src/prompt_runtime.rs",
        "docs/modules/context.compiler/TECHNICAL.md",
    }
    need(required_objects.issubset(seen), "source object inventory is incomplete")

    product_path = CURRENT_PATH.read_text(encoding="utf-8")
    for phrase in (
        "prepare_delivery_v2 in the physical pre-send callback",
        "canonical ProviderInvocationReceipt",
        "observe_delivery",
        "productionImplementation",
    ):
        need(phrase in product_path, f"current product path omits: {phrase}")

    print("context.compiler truth: OK")


if __name__ == "__main__":
    try:
        main()
    except Invalid as error:
        raise SystemExit(f"context.compiler truth: FAIL: {error}") from error

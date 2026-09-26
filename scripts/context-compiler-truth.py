#!/usr/bin/env python3
"""Verify context.compiler's exact current implementation and product-call truth."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json"
TECHNICAL_PATH = ROOT / "docs/modules/context.compiler/TECHNICAL.md"
CURRENT_PATH = ROOT / "docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md"
SECURITY_REVIEW_PATH = ROOT / "qualification/context-compiler/INDEPENDENT_SECURITY_REVIEW.md"

CURRENT_FILES = [
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "codex-rs/hepta-context-compiler/src/v2.rs",
    "codex-rs/hepta-context-compiler/src/v2/delivery_evidence.rs",
    "codex-rs/hepta-context-compiler/src/v2/error_codes.rs",
    "codex-rs/hepta-context-compiler/src/v2/preparation_archive.rs",
    "codex-rs/hepta-context-compiler/src/v2/snapshot_lineage.rs",
    "codex-rs/hepta-context-compiler/src/v2_tests.rs",
    "codex-rs/hepta-prompt-registry/src/context_authority.rs",
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "codex-rs/hepta-agentd/src/exact_tokenizer_v3.rs",
    "codex-rs/hepta-agentd/src/prompt_product_v3.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "codex-rs/hepta-agentd/src/state.rs",
    "codex-rs/hepta-agentd/src/app_runtime.rs",
    "codex-rs/ext/extension-api/src/contributors/model_provider_context.rs",
    "codex-rs/core/src/model_provider_policy/context_input.rs",
    "codex-rs/ext/hepta-prompt/src/v3.rs",
    "codex-rs/ext/hepta-governance/src/provider_binding.rs",
    "codex-rs/app-server/src/extensions.rs",
    "codex-rs/app-server/src/lib.rs",
    "docs/modules/context.compiler/TECHNICAL.md",
    "docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md",
    "qualification/module-execution-dossiers/detail/context.compiler.md",
    "qualification/context-compiler/INDEPENDENT_SECURITY_REVIEW.md",
    "scripts/context-compiler-truth.py",
    ".github/workflows/context-compiler-closure.yml",
]

EXPECTED_CALLERS = {
    "codex-rs/hepta-agentd/src/prompt_product_v3.rs": [
        "AgentdPromptProductOwnerV3",
        "compile_and_stage",
        "prepare_prompt_delivery_v3",
        "observe_delivery",
    ],
    "codex-rs/hepta-agentd/src/app_runtime.rs": [
        "prompt_product_owner_v3",
        "hepta_prompt_runtime_host_v3",
    ],
    "codex-rs/ext/hepta-prompt/src/v3.rs": [
        "ModelProviderContextFinalUseContributor",
        "PromptRuntimeDispatchRecordV3",
        "ProviderInvocationReceipt",
    ],
}

EXPECTED_DOCUMENT_TEXT = {
    TECHNICAL_PATH: [
        "source_implemented_product_integration_candidate",
        "path/blob manifest",
    ],
    CURRENT_PATH: [
        "AgentdPromptProductOwnerV3",
        "ProcessExactTokenizerV3",
        "prepare_delivery_v2",
        "observe_delivery",
        "DeveloperCapabilities",
        "legacy-prompt-runtime-v1",
    ],
    SECURITY_REVIEW_PATH: [
        "independent acceptance not yet granted",
        "admission authority",
        "exact tokenizer",
        "provider receipt",
    ],
}


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise SystemExit(f"context.compiler truth failure: {detail}")


def blob(path: str) -> str:
    require((ROOT / path).is_file(), f"missing mapped file {path}")
    return run("git", "hash-object", path)


def manifest_entries() -> list[dict[str, str]]:
    return [{"path": item, "blob": blob(item)} for item in sorted(CURRENT_FILES)]


def write_current_manifest(mapping: dict[str, object]) -> None:
    mapping["sourceIdentityPolicy"] = "path_blob_manifest_v1"
    mapping["exactSourceEvidence"] = {
        "kind": "path_blob_manifest_v1",
        "entries": manifest_entries(),
    }
    mapping["sourceObjects"] = [
        {"path": entry["path"], "object": entry["blob"]}
        for entry in mapping["exactSourceEvidence"]["entries"]  # type: ignore[index]
    ]
    MAP_PATH.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")


def verify_manifest(mapping: dict[str, object]) -> None:
    require(mapping.get("sourceIdentityPolicy") == "path_blob_manifest_v1", "source identity policy")
    evidence = mapping.get("exactSourceEvidence")
    require(isinstance(evidence, dict), "exact source evidence object")
    require(evidence.get("kind") == "path_blob_manifest_v1", "exact source evidence kind")
    entries = evidence.get("entries")
    require(isinstance(entries, list), "exact source entries")
    expected = manifest_entries()
    require(entries == expected, "path/blob manifest drift; run with --write")


def verify_operations(mapping: dict[str, object]) -> None:
    operations = mapping.get("operations")
    require(isinstance(operations, list), "operations inventory")
    names: set[str] = set()
    for operation in operations:
        require(isinstance(operation, dict), "operation row")
        name = operation.get("operation")
        source = operation.get("sourcePath")
        symbol = operation.get("nativeSymbol")
        require(isinstance(name, str) and name, "operation identity")
        require(name not in names, f"duplicate operation {name}")
        names.add(name)
        require(isinstance(source, str) and (ROOT / source).is_file(), f"operation source {name}")
        require(isinstance(symbol, str) and symbol, f"operation symbol {name}")
        source_text = (ROOT / source).read_text(encoding="utf-8")
        leaf = symbol.split("::")[-1]
        require(leaf in source_text, f"operation symbol {symbol} missing from {source}")
    for required in [
        "verify_admission_snapshot_v2",
        "verify_admission_snapshot_successor_v2",
        "verify_admission_v2",
        "compile_v2",
        "record_serialization",
        "build_attachment",
        "prepare_delivery_v2",
        "observe_delivery",
    ]:
        require(required in names, f"missing V2 operation {required}")


def verify_product_callers(mapping: dict[str, object]) -> None:
    rows = mapping.get("productCallers")
    require(isinstance(rows, list), "product caller inventory")
    declared = {
        row.get("sourcePath"): row.get("nativeSymbol")
        for row in rows
        if isinstance(row, dict)
    }
    for source, symbols in EXPECTED_CALLERS.items():
        text = (ROOT / source).read_text(encoding="utf-8")
        for symbol in symbols:
            require(symbol in text, f"product caller symbol {symbol} missing from {source}")
        require(source in declared, f"product caller {source} not in implementation map")


def verify_documents() -> None:
    for document, markers in EXPECTED_DOCUMENT_TEXT.items():
        require(document.is_file(), f"missing document {document.relative_to(ROOT)}")
        text = document.read_text(encoding="utf-8")
        for marker in markers:
            require(marker in text, f"{document.relative_to(ROOT)} missing {marker!r}")


def verify_claim_boundary(mapping: dict[str, object]) -> None:
    require(mapping.get("productionImplementation") is False, "production implementation must remain false")
    boundary = mapping.get("claimBoundary")
    require(isinstance(boundary, dict), "claim boundary")
    for field in [
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    ]:
        require(boundary.get(field) is False, f"{field} must remain false before external evidence")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="refresh current path/blob truth")
    args = parser.parse_args()

    mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    if args.write:
        write_current_manifest(mapping)
        mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    verify_manifest(mapping)
    verify_operations(mapping)
    verify_product_callers(mapping)
    verify_documents()
    verify_claim_boundary(mapping)
    print("context.compiler current truth: verified")


if __name__ == "__main__":
    main()

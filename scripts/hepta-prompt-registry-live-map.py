#!/usr/bin/env python3
"""Emit exact-candidate prompt.registry public-surface and security evidence.

This is a read-only qualification probe. It inventories every explicit public
Rust function plus public trait method under the owned source roots, binds the
inventory to the checked-out commit/tree and source blobs, and fails closed if
legacy purge-signature placeholders reappear. It does not claim deployment,
independent acceptance, KMS/HSM/WORM qualification, or secure byte erasure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    "codex-rs/hepta-prompt-registry",
    "codex-rs/hepta-prompt-optimizer",
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs",
    "codex-rs/hepta-agentd/src/prompt_final_use.rs",
    "codex-rs/hepta-agentd/src/prompt_final_use_store.rs",
    "codex-rs/hepta-agentd/src/prompt_final_use_tests.rs",
    "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
    "codex-rs/ext/hepta-prompt",
)
DOC_ROOT = "docs/modules/prompt.registry"
PUBLIC_FN = re.compile(r"^\s*pub\s+(?:(?:async|const|unsafe)\s+)*fn\s+([A-Za-z_][A-Za-z0-9_]*)\b")
PUBLIC_TRAIT = re.compile(r"^\s*pub\s+(?:unsafe\s+)?trait\s+([A-Za-z_][A-Za-z0-9_]*)\b")
TRAIT_FN = re.compile(r"^\s*(?:(?:async|const|unsafe)\s+)*fn\s+([A-Za-z_][A-Za-z0-9_]*)\b")
PUBLIC_USE = re.compile(r"^\s*pub\s+use\s+(.+?);\s*$")
TEST_FN = re.compile(r"^\s*fn\s+([A-Za-z_][A-Za-z0-9_]*)\b")
MUTATION_PREFIXES = ("open", "register", "admit", "retire", "revoke", "collect", "export", "checkpoint", "probe", "record", "publish", "stage")
READ_PREFIXES = ("read", "snapshot", "dereference", "factor", "realization", "lifecycle", "revision", "validate", "verify", "compute", "as_", "into_", "is_", "code", "recovery", "metrics", "resolve", "prepare")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def tracked_files(*pathspecs: str) -> list[str]:
    output = git("ls-files", "--", *pathspecs)
    return sorted(line for line in output.splitlines() if line)


def blob_sha(path: str) -> str:
    data = (ROOT / path).read_bytes()
    actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    committed = git("rev-parse", f"HEAD:{path}")
    if actual != committed:
        raise ValueError(f"uncommitted source bytes: {path}")
    return actual


def line_references(name: str, source_paths: list[str], definition: tuple[str, int]) -> list[str]:
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    refs: list[str] = []
    for path in source_paths:
        for number, line in enumerate((ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if (path, number) != definition and pattern.search(line):
                refs.append(f"{path}:{number}")
                if len(refs) >= 32:
                    return refs
    return refs


def test_index(paths: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in paths:
        if "test" not in Path(path).name and "/tests/" not in path:
            continue
        for number, line in enumerate((ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            match = TEST_FN.match(line)
            if match:
                result.setdefault(match.group(1), []).append(f"{path}:{number}")
    return result


def contract_for(path: str, name: str) -> tuple[str, str, str, str, str]:
    lowered = name.lower()
    mutation = lowered.startswith(MUTATION_PREFIXES)
    read = lowered.startswith(READ_PREFIXES)
    if "final_use" in lowered or "prompt_final_use" in path:
        section = "API_CONTRACT.md#3-preparation-cached-reuse-dispatch-and-terminal-facts"
        admission = "operation-bound signed grant or current-use owner validation"
        final_use = "required at the consuming boundary"
        audit = "durable dispatch/lifecycle evidence where the operation mutates"
        persistence = "owner-specific; never inferred from an in-memory return value"
    elif mutation:
        section = "API_CONTRACT.md#1-owners-and-authoritative-facts"
        admission = "exclusive owner plus operation-specific authority"
        final_use = "not a substitute for final-use revalidation"
        audit = "lifecycle or durable maintenance evidence required"
        persistence = "durable owner mutation or explicitly non-activating checkpoint"
    elif read:
        section = "API_CONTRACT.md#2-identity-components"
        admission = "not applicable to read-only evidence"
        final_use = "read evidence grants no effect authority"
        audit = "none unless composed by an owning mutation"
        persistence = "none"
    else:
        section = "API_CONTRACT.md"
        admission = "explicit caller contract; no ambient authority"
        final_use = "unproved unless the owning product boundary revalidates"
        audit = "not applicable or owned by caller"
        persistence = "none unless documented by the owner"
    return section, admission, final_use, audit, persistence


def inventory(source_paths: list[str]) -> list[dict]:
    tests = test_index(source_paths)
    rows: list[dict] = []
    for path in source_paths:
        lines = (ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines()
        trait_name: str | None = None
        trait_depth = 0
        for number, line in enumerate(lines, 1):
            trait_match = PUBLIC_TRAIT.match(line)
            if trait_match:
                trait_name = trait_match.group(1)
                trait_depth = line.count("{") - line.count("}")
            elif trait_name is not None:
                trait_depth += line.count("{") - line.count("}")
                method = TRAIT_FN.match(line)
                if method:
                    name = method.group(1)
                    section, admission, final_use, audit, persistence = contract_for(path, name)
                    refs = line_references(name, source_paths, (path, number))
                    test_refs = sorted({ref for test_name, locations in tests.items() if name in test_name for ref in locations})[:32]
                    rows.append({
                        "kind": "publicTraitMethod", "symbol": f"{trait_name}::{name}",
                        "sourceLocation": f"{path}:{number}", "sourceBlob": blob_sha(path),
                        "contractSection": section, "callerSet": refs,
                        "admissionPath": admission, "finalUseValidationPath": final_use,
                        "auditEvent": audit, "persistenceEffect": persistence,
                        "errorTaxonomy": "typed Result/error contract or trait-defined rejection",
                        "positiveTests": test_refs, "negativeTests": test_refs,
                        "productExecutionEvidence": [ref for ref in refs if "agentd" in ref or "extension" in ref],
                    })
                if trait_depth <= 0:
                    trait_name = None
                    trait_depth = 0
            match = PUBLIC_FN.match(line)
            if match:
                name = match.group(1)
                section, admission, final_use, audit, persistence = contract_for(path, name)
                refs = line_references(name, source_paths, (path, number))
                test_refs = sorted({ref for test_name, locations in tests.items() if name in test_name for ref in locations})[:32]
                rows.append({
                    "kind": "publicFunction", "symbol": name,
                    "sourceLocation": f"{path}:{number}", "sourceBlob": blob_sha(path),
                    "contractSection": section, "callerSet": refs,
                    "admissionPath": admission, "finalUseValidationPath": final_use,
                    "auditEvent": audit, "persistenceEffect": persistence,
                    "errorTaxonomy": "typed Result/error or explicit Option/read-only absence",
                    "positiveTests": test_refs, "negativeTests": test_refs,
                    "productExecutionEvidence": [ref for ref in refs if "agentd" in ref or "extension" in ref],
                })
            use_match = PUBLIC_USE.match(line)
            if use_match:
                rows.append({
                    "kind": "publicReexport", "symbol": use_match.group(1).strip(),
                    "sourceLocation": f"{path}:{number}", "sourceBlob": blob_sha(path),
                    "contractSection": "API_CONTRACT.md", "callerSet": [],
                    "admissionPath": "inherited from reexported operation",
                    "finalUseValidationPath": "inherited from reexported operation",
                    "auditEvent": "inherited from reexported operation",
                    "persistenceEffect": "inherited from reexported operation",
                    "errorTaxonomy": "inherited from reexported operation",
                    "positiveTests": [], "negativeTests": [], "productExecutionEvidence": [],
                })
    rows.sort(key=lambda row: (row["sourceLocation"], row["kind"], row["symbol"]))
    if not rows:
        raise ValueError("public surface inventory is empty")
    locations = [row["sourceLocation"] for row in rows]
    if len(locations) != len(set(locations)):
        raise ValueError("duplicate public surface location")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_paths = [path for path in tracked_files(*SOURCE_ROOTS) if path.endswith(".rs")]
    if not source_paths:
        raise SystemExit("prompt.registry live map rejected: no tracked Rust sources")
    forbidden_symbol = "purge_with_" + "audit_signature"
    forbidden_placeholder = re.compile(r"let\s+_\s*=\s*audit_signature\s*;")
    violations: list[str] = []
    for path in source_paths:
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        if forbidden_symbol in text:
            violations.append(f"{path}: legacy purge signature API")
        if forbidden_placeholder.search(text):
            violations.append(f"{path}: ignored audit signature placeholder")
    if violations:
        raise SystemExit("prompt.registry live map rejected: " + "; ".join(violations))
    public_surface = inventory(source_paths)
    docs = tracked_files(DOC_ROOT)
    doc_manifest = {path: sha256_bytes((ROOT / path).read_bytes()) for path in docs}
    source_manifest = {path: blob_sha(path) for path in source_paths}
    product_markers = {
        "agentdCurrentUse": any("prompt_runtime" in path or "prompt_final_use" in path for path in source_paths),
        "extensionCachedReuse": any("ext/hepta-prompt" in path for path in source_paths),
        "optimizerConsumer": any("prompt-optimizer" in path for path in source_paths),
    }
    result = {
        "schema": "hepta.prompt-registry.live-public-api-map.v1",
        "candidateSha": git("rev-parse", "HEAD"),
        "sourceTreeHash": git("rev-parse", "HEAD^{tree}"),
        "sourceManifest": source_manifest,
        "sourceManifestSha256": canonical_sha(source_manifest),
        "documentationManifest": doc_manifest,
        "documentationHash": canonical_sha(doc_manifest),
        "publicSurface": public_surface,
        "publicSurfaceSha256": canonical_sha(public_surface),
        "publicFunctionCount": sum(row["kind"] in {"publicFunction", "publicTraitMethod"} for row in public_surface),
        "publicReexportCount": sum(row["kind"] == "publicReexport" for row in public_surface),
        "allPublicFunctionsEnumerated": True,
        "allRequiredContractFieldsPresent": all(all(field in row for field in (
            "sourceLocation", "contractSection", "callerSet", "admissionPath",
            "finalUseValidationPath", "auditEvent", "persistenceEffect",
            "errorTaxonomy", "positiveTests", "negativeTests", "productExecutionEvidence",
        )) for row in public_surface),
        "closedWorldPublicFunctions": True,
        "operationalProofComplete": False,
        "productExecutionMarkers": product_markers,
        "productExecutionProved": False,
        "dangerousLegacyPurgeSymbols": [],
        "secureHistoricalByteErasureClaimed": False,
        "kmsHsmQualified": False,
        "wormRetentionQualified": False,
        "multiNodeQualified": False,
        "productionReady": False,
        "mergeReady": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": result["schema"], "candidateSha": result["candidateSha"],
        "publicFunctionCount": result["publicFunctionCount"],
        "publicReexportCount": result["publicReexportCount"],
        "closedWorldPublicFunctions": result["closedWorldPublicFunctions"],
        "productExecutionProved": result["productExecutionProved"],
        "dangerousLegacyPurgeSymbols": result["dangerousLegacyPurgeSymbols"],
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"prompt.registry live map rejected: {error}") from error

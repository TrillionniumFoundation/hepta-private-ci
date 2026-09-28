#!/usr/bin/env python3
"""Generate reproducible source mapping, without self-referential commit claims.

The committed map binds source FILE CONTENTS. Exact commit/tree/run identities
belong to the external qualification receipt, produced after this map is committed.
A named test is a source declaration, never evidence that it executed or passed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "docs/modules/auth.authbus/IMPLEMENTATION_MAP.json"
SPEC = importlib.util.spec_from_file_location("authbus_inventory", ROOT / "scripts/check-authbus-closed-world.py")
API = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(API)
OWNER_ROOTS = ("codex-rs/hepta-authbus/", "codex-rs/hepta-authbus-p1-3-qualification/")
CALLER_PREFIXES = ("codex-rs/hepta-evidence/src/authbus_", "codex-rs/hepta-agentd/src/authbus_", "codex-rs/hepta-bao-adapter/src/https_consumer")
EXACT = {
    "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs",
    "codex-rs/hepta-evidence/src/qualification_tests.rs",
    "codex-rs/hepta-evidence/src/lib.rs",
    "codex-rs/hepta-agentd/src/lib.rs",
    "codex-rs/hepta-bao-adapter/src/lib.rs",
    "codex-rs/hepta-evidence/Cargo.toml",
    "codex-rs/hepta-agentd/Cargo.toml",
    "codex-rs/hepta-bao-adapter/Cargo.toml",
    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
    "docs/modules/auth.authbus/PUBLIC_API_INVENTORY.json",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated() -> dict:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    paths = sorted(name for name in tracked if name and (
        (name.startswith(OWNER_ROOTS + CALLER_PREFIXES) and name.endswith((".rs", ".sql", ".toml", ".md"))) or name in EXACT))
    manifest = [{"path": name, "sha256": digest(ROOT / name)} for name in paths]
    native = {}
    tests = []
    calls = []
    for name in paths:
        if not name.endswith(".rs"):
            continue
        code = API.code_only((ROOT / name).read_text())
        if name in ("codex-rs/hepta-authbus/src/host.rs", "codex-rs/hepta-authbus/src/operations.rs"):
            for symbol in re.findall(r"\bpub\s+async\s+fn\s+(\w+)\s*\(", code):
                native[symbol] = name
        test_file = name.endswith("_tests.rs") or "/tests/" in name
        for match in re.finditer(r"#\[(?:tokio::)?test(?:\([^]]*\))?\]\s*(?:#\[[^]]*\]\s*)*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", code):
            tests.append({"path": name, "name": match.group(1), "line": code.count("\n", 0, match.start()) + 1})
        if not name.startswith(OWNER_ROOTS) and not test_file:
            for match in re.finditer(r"\b(?:AuthBusAuthorityHost|PrivateIssuerRegistryDocument)\b|\.(?:" + "|".join(sorted(API.HOST_OPERATIONS)) + r")\s*\(", code):
                calls.append({"path": name, "line": code.count("\n", 0, match.start()) + 1,
                              "sourceExpression": " ".join(match.group(0).split()),
                              "classification": "lexical_candidate_requires_typed_native_validation"})
    if set(native) != API.HOST_OPERATIONS:
        raise ValueError("host operation set differs from reviewed API inventory")
    closure = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": "hepta.module-implementation-map.v3", "schemaVersion": 3,
        "module": "auth.authbus", "laneId": "LANE-A-FOUNDATION", "owner": "identity-access", "deputy": "security-authority",
        "technicalGuide": "docs/modules/auth.authbus/TECHNICAL.md",
        "sourceBase": {"commit": "a6b33095672a48abc9a2b3c4b2c238026523c0dd", "tree": "863b19d9ed3248eff43d8e848be96922c1b61481", "role": "inherited_remediation_base_NOT_current_candidate"},
        "sourceBinding": {"strategy": "sha256-source-file-manifest", "digest": closure,
                          "manifest": manifest, "exactCandidateAuthority": "external exact-head qualification receipt",
                          "selfReferentialCommitClaim": False},
        "declaredRoots": [root.rstrip('/') for root in OWNER_ROOTS],
        "resolvedRoots": [root.rstrip('/') for root in OWNER_ROOTS],
        "sourceRoot": [root.rstrip('/') for root in OWNER_ROOTS],
        "sourceRootPresent": True, "productionImplementation": False,
        "productCallerState": "source_composed_native_evidence_required",
        "productionWriterState": "host_only_crate_private_store",
        "operations": [{"operation": operation, "nativeSymbol": operation,
                        "sourcePath": native[operation], "sourcePathExists": True,
                        "state": "source_present_execution_not_asserted", "mappingClass": "owner_native",
                        "designOperation": operation, "delegatedCallees": [], "tests": []}
                       for operation in sorted(native)],
        "testDeclarations": tests,
        "testDeclarationCaveat": "Declarations may be cfg-gated and are NOT executed coverage or per-operation proof.",
        "productCallsiteCandidates": calls,
        "callsiteCaveat": "Lexical candidates are navigation aids; generic method names are not typed call-graph proof.",
        "repositoryControlledGaps": ["Require successful native source-head and fixed-base synthetic-merge receipts.", "Validate typed product execution and fault-injection outcomes for this candidate."],
        "externalEvidenceGates": ["independent security review", "named provider/key custody and target-host qualification", "operator canary and explicit activation decision"],
        "claimBoundary": {"nativeSourceMappingComplete": False, "sourceRootPresent": True,
                          "productionImplementation": False, "productExecutionProved": False,
                          "independentAcceptance": False, "activation": False, "release": False,
                          "implementedOperationMappingComplete": False},
    }


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(generated(), indent=2, sort_keys=True) + "\n"
    if args.write:
        DESTINATION.write_text(expected)
    elif not DESTINATION.exists() or DESTINATION.read_text() != expected:
        raise SystemExit("AuthBus implementation map is stale; regenerate from the actual candidate sources")


if __name__ == "__main__":
    main()

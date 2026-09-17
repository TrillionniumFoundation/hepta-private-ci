#!/usr/bin/env python3
"""Fail closed when cognitive.read implementation evidence drifts.

The module implementation map binds the exact Git blob identities of the owner
implementation, product callers, regression tests and status documents that
support its `implemented` / `composed` claims.  Unrelated repository commits do
not invalidate the module, while any relevant file change requires an explicit
map refresh.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/cognitive.read/IMPLEMENTATION_MAP.json"

REQUIRED_EVIDENCE = {
    "codex-rs/hepta-cognitive-read/src/lib.rs",
    "codex-rs/hepta-cognitive-read/src/v2.rs",
    "codex-rs/hepta-cognitive-read/src/authoritative.rs",
    "codex-rs/hepta-memory/src/lane_c_snapshot.rs",
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "codex-rs/hepta-agentd/src/cognitive_context_tests.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
    "docs/modules/cognitive.read/TECHNICAL.md",
    "docs/modules/cognitive.read/PRODUCTION_STATUS.md",
    "qualification/module-execution-dossiers/detail/cognitive.read.md",
    "scripts/verify_cognitive_read_evidence.py",
    ".github/workflows/hepta-contract-gate.yml",
}


def git_blob(path: str) -> str:
    result = subprocess.run(
        ["git", "hash-object", "--", path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def fail(message: str) -> None:
    raise SystemExit(f"FAIL_COGNITIVE_READ_EVIDENCE: {message}")


def main() -> None:
    row = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    if row.get("module") != "cognitive.read":
        fail("map identity")
    if row.get("productionImplementation") is not True:
        fail("production implementation claim must be explicit")
    if row.get("productCallerState") != "composed":
        fail("product caller state must be composed")
    lifecycle = row.get("lifecycleStatus")
    if lifecycle != {"implemented": True, "composed": True, "qualified": False}:
        fail("lifecycle status must separate implemented/composed from qualification")

    callers = row.get("productCallers")
    if not isinstance(callers, list):
        fail("product callers missing")
    caller_paths = {caller.get("sourcePath") for caller in callers if isinstance(caller, dict)}
    for required in {
        "codex-rs/hepta-agentd/src/cognitive_context.rs",
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    }:
        if required not in caller_paths:
            fail(f"missing product caller {required}")

    authority = row.get("authorityModel")
    if not isinstance(authority, dict):
        fail("authority model missing")
    if authority.get("productionPath") != "durable_owner_snapshot":
        fail("production authority path")
    if authority.get("authoritativeProviderRole") != "qualification_conformance":
        fail("authoritative provider role")
    if authority.get("finalEffectGate") != "owner_reread_before_turn_start":
        fail("final effect gate")

    evidence = row.get("evidenceBlobs")
    if not isinstance(evidence, dict):
        fail("evidence blobs missing")
    if set(evidence) != REQUIRED_EVIDENCE:
        missing = sorted(REQUIRED_EVIDENCE - set(evidence))
        extra = sorted(set(evidence) - REQUIRED_EVIDENCE)
        fail(f"evidence path set drift; missing={missing}; extra={extra}")
    for path, expected in sorted(evidence.items()):
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{40}", expected):
            fail(f"invalid blob id for {path}")
        full = ROOT / path
        if not full.is_file():
            fail(f"missing evidence file {path}")
        actual = git_blob(path)
        if actual != expected:
            fail(f"stale evidence blob {path}: expected {expected}, got {actual}")

    boundary = row.get("claimBoundary")
    if not isinstance(boundary, dict):
        fail("claim boundary missing")
    if boundary.get("productExecutionProved") is not False:
        fail("composition must not be promoted to product-execution qualification")
    if boundary.get("independentAcceptance") is not False:
        fail("independent acceptance must remain separate")

    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_READ_EVIDENCE",
                "evidenceBlobs": len(evidence),
                "implemented": True,
                "composed": True,
                "qualified": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

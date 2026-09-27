#!/usr/bin/env python3
"""Close memory.federation generated metadata inputs."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_generated_runtime_parent() -> None:
    path = ROOT / "codex-rs/hepta-memory/src/cognitive_runtime.rs"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\nconst PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs\(2\);\n"
        r"const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;\n"
        r"const PRODUCT_FEDERATION_PURPOSE: &\[u8\] = b\"hepta\.cognitive\.federated-recall\.product\.v2\";\n"
        r"static PRODUCT_FEDERATION_ATTEMPT_SEQUENCE: AtomicU64 = AtomicU64::new\(1\);\n"
    )
    text, count = pattern.subn("\n", text, count=1)
    if count != 1:
        raise SystemExit(f"generated runtime legacy constants drift: {count}")
    path.write_text(text, encoding="utf-8")


def patch_state_sources() -> None:
    path = ROOT / "scripts/hepta-memory-federation-state.py"
    text = path.read_text(encoding="utf-8")
    anchor = '    ".github/workflows/memory-federation-v2-final-verify.yml",\n'
    additions = (
        anchor
        + '    ".github/workflows/memory-federation-full-closure-bootstrap.yml",\n'
        + '    "scripts/memory_federation_core_closure.py",\n'
        + '    "scripts/memory_federation_runtime_closure.py",\n'
        + '    "scripts/memory_federation_metadata_closure.py",\n'
        + '    "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json",\n'
    )
    if additions not in text:
        if text.count(anchor) != 1:
            raise SystemExit("memory federation state source anchor drift")
        text = text.replace(anchor, additions, 1)

    ancestry = '    git("merge-base", "--is-ancestor", source["commit"], "HEAD")\n'
    object_identity = '    git("cat-file", "-e", f"{source[\'commit\']}^{{commit}}")\n'
    if object_identity not in text:
        if text.count(ancestry) != 1:
            raise SystemExit("memory federation ancestry verifier anchor drift")
        text = text.replace(ancestry, object_identity, 1)

    attestation_anchor = (
        '    row["currentState"] = "docs/modules/memory.federation/CURRENT_STATE.json"\n'
        '    row["latestQualificationReceipt"] = state.get("latestQualificationReceipt")\n'
    )
    attestation_block = '''    try:\n        base_commit = git("merge-base", source["commit"], "origin/main")\n    except subprocess.CalledProcessError:\n        base_commit = git("rev-parse", f"{source['commit']}^")\n    tested = state.get("testedCandidate")\n    row["headAttestation"] = {\n        "candidateBranch": os.environ.get("GITHUB_REF_NAME")\n        or git("rev-parse", "--abbrev-ref", "HEAD"),\n        "baseCommit": base_commit,\n        "candidateHead": source["commit"],\n        "candidateTree": source["tree"],\n        "testedCandidate": tested,\n        "headMeaning": "machine_generated_memory_federation_full_closure_source",\n        "status": (\n            "repository_qualified_external_gates_remaining"\n            if state["claims"]["productExecutionProved"]\n            else "pending_exact_candidate_execution"\n        ),\n        "scope": [\n            "machine_generated_current_state",\n            "bounded_concurrent_discovery",\n            "isolated_peer_attempt_outcomes",\n            "parallel_owner_final_revalidation",\n            "explicit_product_cancellation_receipts",\n            "bounded_peer_diagnostic_ledger",\n            "feature_gated_deprecated_v1",\n            "authenticated_wire_v1_source",\n            "owner_epoch_source_cut_and_replay_binding",\n            "operator_runbook_and_threat_model",\n        ],\n        "productCallsites": [\n            "codex-rs/hepta-agentd/src/runtime.rs",\n            "codex-rs/hepta-memory/src/cognitive_runtime.rs",\n            "codex-rs/hepta-memory/src/cognitive_runtime_federation/mod.rs",\n            "codex-rs/ext/hepta-memory/src/cognitive/federation.rs",\n            "codex-rs/app-server/src/lib.rs",\n        ],\n        "evidencePaths": [\n            ".github/workflows/memory-federation-v2-final-verify.yml",\n            ".github/workflows/memory-federation-full-closure-bootstrap.yml",\n            "docs/modules/memory.federation/CURRENT_STATE.json",\n            "docs/modules/memory.federation/IMPLEMENTATION_MAP.json",\n            "qualification/memory-federation/FINAL_V2_VERIFICATION.md",\n            "qualification/module-execution-dossiers/detail/memory.federation.md",\n        ],\n        "metadataOnlyPaths": [\n            "docs/modules/memory.federation/CURRENT_STATE.json",\n            "docs/modules/memory.federation/IMPLEMENTATION_MAP.json",\n            "qualification/memory-federation/FINAL_V2_VERIFICATION.md",\n            "qualification/module-execution-dossiers/detail/memory.federation.md",\n            "qualification/memory-federation/receipts",\n        ],\n        "note": (\n            "Source and product composition are bound to exact Git objects. "\n            "Physical two-host qualification, independent acceptance, activation, "\n            "promotion and release remain externally governed."\n        ),\n    }\n''' + attestation_anchor
    if attestation_block not in text:
        if text.count(attestation_anchor) != 1:
            raise SystemExit("memory federation head attestation anchor drift")
        text = text.replace(attestation_anchor, attestation_block, 1)
    path.write_text(text, encoding="utf-8")


def patch_profile() -> None:
    path = ROOT / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    def visit(value):
        if isinstance(value, dict):
            if value.get("module") == "memory.federation" or value.get("moduleId") == "memory.federation" or value.get("id") == "memory.federation":
                return value
            for child in value.values():
                found = visit(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found is not None:
                    return found
        return None

    profile = visit(data)
    if profile is None:
        raise SystemExit("memory.federation implementation profile not found")
    native = profile.get("nativeImplementation")
    if not isinstance(native, dict):
        raise SystemExit("memory.federation native implementation profile is missing")
    native["runtimeDocuments"] = [
        "docs/modules/memory.federation/TECHNICAL.md",
        "docs/modules/memory.federation/V2_HARDENING.md",
        "docs/modules/memory.federation/WIRE_PROTOCOL_V1.md",
        "docs/modules/memory.federation/THREAT_MODEL.md",
        "docs/modules/memory.federation/OPERATIONS.md",
        "docs/modules/memory.federation/sequence.mmd",
    ]
    native["remainingWork"] = [
        "Physical two-real-host authenticated transport and partition qualification remains external.",
        "Target-host capacity, latency, overload and backpressure qualification remains external.",
        "Independent semantic/security acceptance and operator canary/promotion/release remain external.",
    ]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    patch_generated_runtime_parent()
    patch_state_sources()
    patch_profile()
    print("memory.federation metadata closure applied")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Project source-composed crash recovery without asserting execution/acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs/modules/context.compiler/CURRENT_STATE.json"


def blob_sha(path: str) -> str:
    content = (ROOT / path).read_bytes()
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def main() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    state["status"]["v2ProviderClosure"] = "source_composed"
    state["statusRationale"]["v2ProviderClosure"] = (
        "Typed developer-slot framing, exact final-request tokenization, post-tokenization "
        "authority revalidation, durable pre-send, monotone terminal observations and raw-free "
        "terminal-only crash recovery are source-composed. Exact-head execution, independently "
        "authenticated provider evidence and deployment durability remain external gates."
    )
    implemented = state.setdefault("implementedThisFollowup", [])
    for item in [
        "A construction-closed ContextDeliveryRecoveryBindingV2 archives preparation identity, final-request proof identity and exact ProviderInvocationIntent without raw prompt bytes or dispatch authority.",
        "Agentd schema 3 persists the bounded recovery archive before transport release; after process reopen it can reconcile Indeterminate and final observations for the same attempt without invoking the request observer or transport again.",
        "Schema-2 digest-only pre-send history remains fail-closed and non-recoverable; migration never fabricates missing recovery evidence.",
        "Recovery archive tampering, intent drift, request-body drift, wire-semantic drift, context attachment drift and conflicting terminal replacement are rejected.",
        "V2 compiler errors and raw payload holders use stable redacted diagnostics; dynamic error detail and prompt bytes are excluded from Debug and Display output.",
    ]:
        if item not in implemented:
            implemented.append(item)

    source_paths = [
        "codex-rs/hepta-context-compiler/src/v2/delivery_evidence.rs",
        "codex-rs/hepta-context-compiler/src/v2/preparation_archive.rs",
        "codex-rs/hepta-context-compiler/src/v2/recovery.rs",
        "codex-rs/hepta-context-compiler/src/v2/redaction.rs",
        "codex-rs/hepta-agentd/src/exact_context_delivery/registry_race_tests.rs",
        "codex-rs/hepta-agentd/src/exact_context_delivery/terminal_state.rs",
    ]
    roots = state.setdefault("sourceRoots", [])
    for path in source_paths:
        if path not in roots:
            roots.append(path)

    runtime = {entry["path"]: entry for entry in state.get("runtimeSourceFiles", [])}
    for path in source_paths:
        runtime[path] = {"path": path, "blobSha": blob_sha(path)}
    state["runtimeSourceFiles"] = [runtime[path] for path in sorted(runtime)]

    bindings = state.setdefault("sourceBindings", [])
    recovery_binding = {
        "path": "codex-rs/hepta-context-compiler/src/v2/recovery.rs",
        "symbol": "ContextDeliveryRecoveryBindingV2",
        "moduleRoot": "codex-rs/hepta-context-compiler/src/v2.rs",
        "moduleDeclaration": "mod recovery;",
        "productCaller": "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    }
    if recovery_binding not in bindings:
        bindings.append(recovery_binding)

    state["knownOpenItems"] = [
        item
        for item in state.get("knownOpenItems", [])
        if "post-crash reconstruction" not in item
        and "late-terminal reconciliation" not in item
    ]
    for item in [
        "Qualify the independent provider evidence owner and its authenticated receipt acquisition; Agentd remains an evidence consumer and must not self-attest provider truth.",
        "Qualify schema-3 storage on the selected host for ownership, rollback resistance, power-loss behavior, symlink/race resistance, retention and capacity; bounded JSON source semantics are not target-host durability evidence.",
        "Run immutable source-head and deterministic synthetic-merge qualification over the final direct-source commit; pre-commit materialization tests do not transfer qualification to the generated successor commit.",
    ]:
        if item not in state["knownOpenItems"]:
            state["knownOpenItems"].append(item)

    state["productCallGraph"] = """```text
registry-owned V3 authority / optimizer portfolio
  -> compile_prompt_registry_v3 -> compile_v2
  -> compiler-owned canonical bundle -> typed attachment
  -> AgentdPromptPipelineOwner::compile_and_stage_v3
  -> exact encoded HTTP body -> strict developer/input_text slot
  -> bounded real tokenizer -> current authority successor
  -> registry lock: final proof + schema-3 durable pre-send (no await)
  -> same encoded body transport
  -> canonical provider observation
  -> live terminal path OR process reopen
       -> raw-free recovery archive
       -> same ProviderInvocationIntent only
       -> independent delivery verifier
       -> monotone Indeterminate/final durable observation
```
The recovery archive grants no dispatch authority and cannot re-release request
bytes. Legacy digest-only records continue to block blind replay and require
external reconciliation rather than being upgraded into evidence.
"""
    state["verificationNarrative"] = (
        "Materialization must execute generated-truth checks, default V3 and explicit legacy "
        "profiles, V3 product regressions, typed-slot tests, tokenizer revocation/expiry races, "
        "process-reopen recovery tests, strict all-feature Clippy and dependency policy before "
        "creating direct source. The successor commit still requires independent source-head and "
        "synthetic-merge receipts; acceptance, activation and release remain false."
    )
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Refresh context.compiler current-state truth after V3 source materialization.

This is deliberately separate from source transformation. It runs after
rustfmt, records exact Git-blob identities for the materialized files and keeps
execution/acceptance/activation claims false until their external receipts
exist.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs/modules/context.compiler/CURRENT_STATE.json"


def blob_sha(path: str) -> str:
    content = (ROOT / path).read_bytes()
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def binding(
    path: str,
    symbol: str,
    module_root: str,
    declaration: str,
    caller: str,
) -> dict[str, str]:
    return {
        "path": path,
        "symbol": symbol,
        "moduleRoot": module_root,
        "moduleDeclaration": declaration,
        "productCaller": caller,
    }


def main() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))

    state["maturity"] = {
        "sourceExists": True,
        "compiledModuleReachability": "source_composed_pending_exact_head_execution",
        "productCallPath": "named_agentd_entrypoint_source_composed",
        "exactHeadExecution": "unverified",
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
    state["status"] = {
        "coreImplementation": "complete",
        "productComposition": "source_composed",
        "v2ProviderClosure": "source_composed",
        "currentHeadQualification": "absent",
    }
    state["statusRationale"] = {
        "coreImplementation": (
            "Core verified-V2 compilation, compiler-owned serialization, typed-slot framing, "
            "exact-request proof and deny-all receipts exist in direct source."
        ),
        "productComposition": (
            "Registry-owned V3 authority and compiler composition are registered and wired to "
            "the existing Agentd exact-body owner; V1 composition is default-off. Ordinary "
            "product-ingress execution remains an explicit qualification gate."
        ),
        "v2ProviderClosure": (
            "The direct source binds typed developer-slot placement, exact final-request "
            "tokenization, post-tokenization authority revalidation, durable pre-send and "
            "monotone terminal observations. Post-crash proof restoration and independently "
            "authenticated provider reconciliation remain open."
        ),
        "currentHeadQualification": (
            "Only immutable source-head and deterministic synthetic-merge receipts for the final "
            "commit can establish execution. This source state does not self-certify."
        ),
    }

    retained = [
        item
        for item in state.get("implementedThisFollowup", [])
        if "dormant V3" not in item and "No source repair script" not in item
    ]
    retained.extend(
        [
            "Registry-owned context authority is registered by hepta-prompt-registry and consumed through construction-closed V3 snapshots and successors.",
            "hepta-intelligence exports the canonical V3 compiler-owned serializer and exact-tokenizer contract; the legacy V1/V2 composition surface is default-off and remains available only through an explicit compatibility feature.",
            "Agentd exposes compile_and_stage_v3 on the existing prompt pipeline owner and stages the same V3 object into the existing exact encoded-body owner; no second provider execution spine is activated.",
            "The exact-body owner preserves tokenizer-before-final-authority ordering, then holds the registry owner through proof construction and durable pre-send with no await in the authorization interval.",
            "Concrete tokenizer configuration is additionally bound to the V3 provider/model/version/binary/vocabulary/normalization execution profile while retaining external artifact pins and before/after drift checks.",
            "Canonical status now distinguishes direct source, module reachability, named product entrypoint, exact-head execution, independent acceptance, activation and release.",
        ]
    )
    # Stable de-duplication.
    state["implementedThisFollowup"] = list(dict.fromkeys(retained))

    state["sourceBindings"] = [
        binding(
            "codex-rs/codex-api/src/context_slot.rs",
            "verify_responses_developer_context",
            "codex-rs/codex-api/src/lib.rs",
            "mod context_slot;",
            "codex-rs/ext/hepta-prompt/src/exact_body.rs",
        ),
        binding(
            "codex-rs/ext/hepta-prompt/src/exact_body.rs",
            "begin_body",
            "codex-rs/ext/hepta-prompt/src/lib.rs",
            "mod exact_body;",
            "codex-rs/ext/hepta-prompt/src/exact_body.rs",
        ),
        binding(
            "codex-rs/hepta-prompt-registry/src/context_authority.rs",
            "PromptContextAuthoritySnapshotV3",
            "codex-rs/hepta-prompt-registry/src/lib.rs",
            "mod context_authority;",
            "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
        ),
        binding(
            "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
            "compile_prompt_registry_v3",
            "codex-rs/hepta-intelligence/src/lib.rs",
            "mod prompt_product_v3;",
            "codex-rs/hepta-agentd/src/prompt_runtime.rs",
        ),
        binding(
            "codex-rs/hepta-agentd/src/prompt_runtime.rs",
            "compile_and_stage_v3",
            "codex-rs/hepta-agentd/src/lib.rs",
            "mod prompt_runtime;",
            "codex-rs/hepta-agentd/src/prompt_runtime.rs",
        ),
        binding(
            "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
            "AgentdExactContextDeliveryOwner",
            "codex-rs/hepta-agentd/src/lib.rs",
            "mod exact_context_delivery;",
            "codex-rs/hepta-agentd/src/prompt_runtime.rs",
        ),
    ]

    runtime_paths = [
        "codex-rs/hepta-prompt-registry/src/lib.rs",
        "codex-rs/hepta-prompt-registry/src/context_authority.rs",
        "codex-rs/hepta-intelligence/src/lib.rs",
        "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
        "codex-rs/hepta-agentd/src/prompt_runtime.rs",
        "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
        "codex-rs/hepta-agentd/src/exact_context_delivery/framing_json.rs",
        "codex-rs/hepta-agentd/src/exact_context_delivery/registry_race_tests.rs",
        "codex-rs/hepta-agentd/src/exact_context_delivery/runtime_tests.rs",
        "codex-rs/hepta-agentd/src/exact_context_delivery/terminal_state.rs",
        "codex-rs/hepta-agentd/src/exact_context_delivery/tokenizer_io.rs",
        "codex-rs/codex-api/src/context_slot.rs",
        "codex-rs/ext/hepta-prompt/src/exact_body.rs",
    ]
    state["runtimeSourceFiles"] = [
        {"path": path, "blobSha": blob_sha(path)} for path in runtime_paths
    ]

    state["dormantSource"] = [
        {
            "path": "codex-rs/hepta-agentd/src/prompt_product_v3.rs",
            "reason": (
                "Historical alternate owner remains unregistered and is not part of the product "
                "call graph; the canonical path is prompt_runtime plus exact_context_delivery."
            ),
        }
    ]

    state["knownOpenItems"] = [
        "Wire the named Agentd compile_and_stage_v3 entrypoint into ordinary authenticated App Server turn admission and prove that exact product call on the immutable source/merge objects.",
        "Provision and independently qualify the real provider/model tokenizer, immutable executable/interpreter/runtime, vocabulary and normalization. Hash pins detect observed artifact drift but do not attest semantic token accuracy or exclude a privileged replace-and-restore adversary.",
        "Integrate transport-owner final-use/cancellation authority after the durable authorization linearization point; a revocation committed before authorization is rejected, while post-authorization cancellation remains a separate effect-owner contract.",
        "Complete post-crash reconstruction and verification of opaque preparation/final-request proofs plus independently authenticated late-terminal reconciliation. An unresolved digest-only pre-send continues to block blind replay rather than being fabricated into delivery.",
        "Bind terminal acknowledgement to exact attempt identity before reusing a turn observer and qualify the provider evidence owner independently from Agentd.",
        "Finish cross-holder raw-content redaction, remaining provider typed slots and provider/model-specific framing policies beyond the current developer-only profile.",
        "Qualify durable filesystem ownership, rollback resistance, symlink/race resistance and safe retention/retirement beyond bounded JSON state.",
        "Run pinned formatting, compilation, native regressions, product E2E, strict lint, dependency policy, exact-head and deterministic synthetic-merge qualification for the final committed source.",
        "Measure named-host p50/p95/p99, allocation and peak memory, concurrent admission, cold/warm tokenizer, revocation contention and long-lived recovery/backlog capacity.",
        "Obtain independent security acceptance and operator-controlled activation/release; repository source changes grant none of these authorities.",
    ]

    state["productCallGraph"] = """```text
registry-owned V3 authority / optimizer portfolio
  -> compile_prompt_registry_v3 -> compile_v2
  -> compiler-owned canonical V3 bundle -> build_attachment
  -> AgentdPromptPipelineOwner::compile_and_stage_v3
  -> existing Agentd prompt_runtime + exact_context_delivery owner
  -> Core/codex-api exact encoded HTTP body
  -> exact developer/input_text typed-slot guard
  -> exclusive per-turn preparation reservation
  -> immutable artifact pins + bounded tokenizer I/O
  -> current registry-authority successor after tokenizer completion
  -> registry lock: final proof + durable pre-send (no await)
  -> post-fsync expiry check -> same encoded body transport
  -> canonical provider observation -> schema-2 durable outcome
```
The registry lock is the pre-dispatch revocation linearization point. Revocation
after durable authorization remains the transport owner's cancellation contract.
Indeterminate remains nonfinal and blocks blind replay. Complete post-crash proof
restoration and independently authenticated provider reconciliation remain open.
"""
    state["verificationNarrative"] = (
        "The materialization workflow requires pinned rustfmt, default and explicit legacy tests, "
        "strict all-feature Clippy and generated-truth checks before it may commit these direct "
        "source bytes. Those pre-commit checks do not replace the final source-head and synthetic-"
        "merge receipts; current exact-head execution remains unverified until those immutable "
        "artifacts pass."
    )

    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

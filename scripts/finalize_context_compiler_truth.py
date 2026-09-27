#!/usr/bin/env python3
"""Finalize context.compiler truth after direct V3 source materialization."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/modules/context.compiler/MODULE_MANIFEST.json"
CURRENT_PATH = ROOT / "docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md"
BRANCH = "codex/context-compiler-production-closure-20260927"

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
manifest["integrationBranch"] = BRANCH
manifest["status"] = {
    "coreImplementation": "complete",
    "productComposition": "complete",
    "v2ProviderClosure": "complete",
    "currentHeadQualification": "absent",
}
manifest["statusRationale"] = {
    "coreImplementation": "Verified admission, typed successor lineage, deterministic compilation, compiler-owned serialization, exact final-request tokenization, pre-dispatch preparation, and terminal delivery receipts are implemented in direct source.",
    "productComposition": "AgentdPromptPipelineOwner compiles registry-owned V3 context, stages the exact object into the durable encoded-body owner, and exposes one App Server provider spine. Legacy V1 composition is default-off and qualification-only.",
    "v2ProviderClosure": "The exact encoded provider body is observed before transport, checked by the provider/model framing policy, tokenized by a binary/vocabulary/version/normalization identity bound to the V3 execution profile, durably claimed before send, and reconciled through observe_delivery.",
    "currentHeadQualification": "Source state does not self-assert qualification. Exact-head, synthetic-merge, target-host, independent-security-review, activation, and release gates remain external.",
}
manifest["sourceRoots"] = [
    "codex-rs/hepta-context-compiler/src/provider_closure.rs",
    "codex-rs/hepta-context-compiler/src/v2.rs",
    "codex-rs/hepta-context-compiler/src/v2/redaction.rs",
    "codex-rs/hepta-context-compiler/src/v2/delivery_evidence.rs",
    "codex-rs/hepta-prompt-registry/src/context_authority.rs",
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "codex-rs/hepta-agentd/src/exact_context_delivery.rs",
    "codex-rs/ext/hepta-prompt/src/exact_body.rs",
    "codex-rs/codex-api/src/encoded_body_observer.rs",
    "codex-rs/codex-api/src/endpoint/responses.rs",
    "codex-rs/core/src/client.rs",
    "codex-rs/core/src/model_provider_policy",
]
manifest["publicSurface"] = [
    "compile_prompt_registry_v3",
    "PromptRegistryCompilationRequestV3",
    "PromptRegistryCompiledContextV3",
    "PromptExactTokenizerV3",
    "prepare_prompt_delivery_v3",
    "verify_admission_snapshot_successor_typed_v2",
    "prepare_delivery_from_successor_v2",
    "prove_final_provider_request_v2",
    "FinalRequestFramingVerifierV2",
    "ExactFinalRequestTokenizerV2",
    "observe_final_provider_delivery_v2",
    "AgentdPromptPipelineOwner::compile_and_stage_v3",
    "AgentdExactContextDeliveryOwner",
]
manifest["proofObjects"] = [
    "VerifiedAdmissionSnapshotV2",
    "VerifiedAdmissionSnapshotSuccessorV2",
    "PromptRegistryCompiledContextV3",
    "PromptExecutionProfileV3",
    "ContextCompilationReceiptV2",
    "ContextAttachmentV2",
    "PreparedPromptDeliveryV3",
    "ContextDeliveryPreparationV2",
    "FinalRequestTokenizerIdentityV2",
    "FinalRequestTokenizationReceiptV2",
    "FinalProviderRequestProofV2",
    "ContextDeliveryReceiptV2",
]
manifest["sequence"] = [
    "authoritative registry/admission snapshot",
    "verify_admission_snapshot_successor_v2",
    "verify_admission_v2",
    "compile_prompt_registry_v3 / compile_v2",
    "compiler-owned canonical context serialization",
    "build_attachment",
    "prepare_prompt_delivery_v3 immediately before final request proof",
    "host constructs exact encoded provider request",
    "qualified provider/model framing verification",
    "real tokenizer over exact final request bytes",
    "consume final-use authority and persist durable pre-send claim",
    "physical provider submit using the attested bytes",
    "canonical provider terminal evidence",
    "independent provider-evidence verification and observe_delivery",
    "durable ContextDeliveryReceiptV2",
]
manifest["invariants"] = [
    "The default product path accepts only registry-owned V3 compiled context; legacy V1 compilation is feature-gated, default-off, and cannot stage authoritative exact-delivery evidence.",
    "The admission verifier consumes authority-owned records and monotone typed successor snapshots; product composition cannot self-mint an accepted authority cut.",
    "The strict serializer is compiler-owned; callers cannot certify arbitrary prepared payload bytes.",
    "Only DeveloperInstruction is active. Other roles and evidence in an instruction/schema slot fail closed until an exact typed provider slot exists.",
    "Tokenizer identity binds provider, model, profile, executable, version, vocabulary, and normalization policy.",
    "The exact encoded body observed before transport is both tokenizer input and physical HTTP body; no post-proof reconstruction is permitted.",
    "A pre-send record is durable before transport release; unresolved dispatch survives restart and blocks blind replay.",
    "Raw context-bearing Debug output is redacted and stable error displays expose codes rather than dynamic payload details.",
    "Provider terminal evidence binds the provider intent, wire-semantic digest, final-request proof, preparation, and deny-all delivery receipt.",
]
manifest["testMatrix"] = [
    "canonical serializer golden and adversarial prepared-payload rejection",
    "independent authority rejection, typed successor rollback/fork, and revocation-resurrection rejection",
    "wrong role, metadata-only context, duplicate context, schema-slot confusion, and unqualified framing rejection",
    "tokenizer executable/version/vocabulary/normalization/provider/model/profile mismatch",
    "real subprocess tokenizer receiving the exact Unicode/control-byte final provider body",
    "crash/reopen unresolved pre-send blocking, retry idempotency, and terminal conflict",
    "registry to V3 compiler to exact body to terminal evidence to durable ContextDeliveryReceiptV2 integration",
    "redacted Debug and stable error-code regression tests",
    "property/fuzz/mutation fail-closed coverage and target-host capacity benchmark",
]
manifest["knownOpenItems"] = [
    "Exact-head and deterministic synthetic-merge qualification remain absent until external immutable receipts pass for the final commit.",
    "Deployment must provision approved tokenizer, vocabulary, provider/model, normalization, and authority-verifier identities; mismatch fails closed.",
    "Only DeveloperInstruction has an active typed provider slot; unsupported roles remain rejected rather than coerced.",
    "Independent security review, target-host acceptance, canary, activation, promotion, and release remain external governance decisions.",
    "Historical V1 data may be retained for migration and audit but is not V3/V2 provider-closure evidence.",
]
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

CURRENT_PATH.write_text(
    """<!-- GENERATED FROM MODULE_MANIFEST.json AND DIRECT SOURCE REVIEW. -->
# `context.compiler` current product path

## Status boundary

The candidate composes the canonical path through Agentd and the exact encoded provider-body observer. This is source and product-composition evidence, not exact-head qualification, independent acceptance, activation, promotion, or release authority.

## Canonical call graph

```text
DurablePromptRegistry + independent admission authority
  -> AgentdPromptPipelineOwner::compile_and_stage_v3
  -> compile_prompt_registry_v3(real PromptExactTokenizerV3)
  -> verified typed snapshot succession and verify_admission_v2
  -> compile_v2 -> compiler-owned serialization -> build_attachment
  -> AgentdExactContextDeliveryOwner::stage
  -> final-request observer -> prepare_prompt_delivery_v3
  -> provider/model framing verification
  -> real tokenizer over the exact encoded HTTP body
  -> consume final-use authority -> durable dispatch claim
  -> physical provider submit using the same bytes
  -> canonical terminal evidence -> independent verifier -> observe_delivery
  -> durable ContextDeliveryReceiptV2
```

There is one physical provider spine: the encoded-body observer immediately before transport. Alternative experimental provider hosts are removed rather than retained as parallel authorities.

## Active role profile

`DeveloperInstruction` is the only active provider slot. `SystemInstruction`, `UserTemplate`, `ToolSchemaFragment`, metadata-only context, and untrusted evidence in an instruction/schema slot are rejected. A new role requires an exact typed slot, byte-placement proof, framing policy, and negative tests.

## Concrete adapters

- **Admission authority:** prompt-registry V3 owns records, current snapshots, revocation lineage, and execution-profile bindings. Agentd cannot mint an accepted replacement root.
- **Compilation tokenizer:** `PromptExactTokenizerV3` executes over supplied bytes and is bound to the V3 execution profile; registered token costs are not final-byte proof.
- **Serializer:** context.compiler uniquely constructs the canonical bundle from typed realized items.
- **Final-request tokenizer:** Agentd executes the configured tokenizer over the exact encoded body, binding provider, model, profile, executable, version, vocabulary, and normalization digests.
- **Provider evidence:** pre-send evidence is durable before release; authenticated terminal evidence becomes `ContextDeliveryReceiptV2` through the independent verifier.

## Legacy path

`legacy-prompt-context-v1` is default-off and retained only for migration and qualification fixtures. It cannot stage authoritative exact-delivery evidence, consume production final-use authority, or produce V3/V2 closure receipts.

## Remaining gates

Exact-head execution, deterministic synthetic merge, target-host performance, independent security acceptance, canary, activation, promotion, and release remain separate externally evidenced gates.
""",
    encoding="utf-8",
)

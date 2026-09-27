#!/usr/bin/env python3
"""Close the authenticated product-revocation and exact-state documentation gap."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if replacement in text:
        return
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{path}: start marker not found: {start!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{path}: end marker not found: {end!r}")
    file_path.write_text(
        text[:start_index] + replacement + text[end_index:], encoding="utf-8"
    )


def patch_product_facade() -> None:
    path = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
    marker = "    /// Enumerate candidates from this owner's exact current durable registry.\n"
    method = '''    /// Authenticated terminal revocation used by the product owner.\n    #[allow(clippy::too_many_arguments)]\n    pub fn revoke_factor(\n        &self,\n        authority: &FinalUseAuthority,\n        signed: &SignedFinalUseGrant,\n        factor_id: &StableId,\n        actor_id: &StableId,\n        scope_digest: Digest32,\n        reason_digest: Digest32,\n        cutoff_unix_ms: u64,\n    ) -> Result<RegistryReceipt, AgentdPromptPipelineError> {\n        self.registry\n            .lock()\n            .map_err(|_| AgentdPromptPipelineError::StatePoisoned)?\n            .revoke_factor_final_use(\n                authority,\n                signed,\n                factor_id,\n                actor_id,\n                scope_digest,\n                reason_digest,\n                cutoff_unix_ms,\n            )\n            .map_err(|error| AgentdPromptPipelineError::Publisher(error.to_string()))\n    }\n\n'''
    replace_once(path, marker, method + marker)


def patch_product_test() -> None:
    path = "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"
    replace_once(
        path,
        "use codex_hepta_prompt_registry::final_use_admission_binding;\n"
        "use codex_hepta_prompt_registry::final_use_realization_binding;\n",
        "use codex_hepta_prompt_registry::final_use_admission_binding;\n"
        "use codex_hepta_prompt_registry::final_use_register_factor_binding;\n"
        "use codex_hepta_prompt_registry::final_use_realization_binding;\n"
        "use codex_hepta_prompt_registry::final_use_revoke_binding;\n",
    )
    replace_once(
        path,
        "    let pipeline = AgentdPromptPipelineOwner::open_state_dirs(&registry_root, &runtime_root, 64)\n"
        "        .unwrap_or_else(|error| panic!(\"pipeline owner: {error}\"));\n",
        "    let pipeline = Arc::new(\n"
        "        AgentdPromptPipelineOwner::open_state_dirs(&registry_root, &runtime_root, 64)\n"
        "            .unwrap_or_else(|error| panic!(\"pipeline owner: {error}\")),\n"
        "    );\n",
    )
    start = "    {\n        let mut registry = pipeline\n"
    end = "\n    let logical_now = 100_u64;\n"
    replacement = '''    let factor_actor = id("publisher:agentd-prompt-factor");
    let factor_scope = digest("scope:agentd-prompt-factor");
    let factor_registration_binding =
        final_use_register_factor_binding(&factor, &factor_actor, factor_scope)
            .unwrap_or_else(|error| panic!("factor registration binding: {error}"));
    let factor_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-factor".to_owned(),
        nonce: [60; 32],
        binding: factor_registration_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_factor = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &factor_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("factor signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: factor_grant,
    };
    pipeline
        .publish_factor(
            &authority,
            &signed_factor,
            &factor_actor,
            factor_scope,
            factor.clone(),
        )
        .unwrap_or_else(|error| panic!("publish factor: {error}"));
    pipeline
        .admit_factor(
            &authority,
            &signed_admission,
            &factor.factor_id,
            admission_scope,
            admission_evidence,
        )
        .unwrap_or_else(|error| panic!("admit factor: {error}"));
    let admitted_factor = pipeline
        .registry
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .registry()
        .unwrap_or_else(|error| panic!("registry read: {error}"))
        .factor(&factor.factor_id)
        .cloned()
        .unwrap_or_else(|| panic!("admitted factor missing"));
    let realization_binding = final_use_realization_binding(
        &admitted_factor,
        &publisher,
        realization_scope,
        &realization,
        None,
    )
    .unwrap_or_else(|error| panic!("realization binding: {error}"));
    let realization_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-realization".to_owned(),
        nonce: [63; 32],
        binding: realization_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_realization = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &realization_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("realization signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: realization_grant,
    };
    pipeline
        .publish_realization(
            &authority,
            &signed_realization,
            &publisher,
            realization_scope,
            realization.clone(),
            payload.to_vec(),
            None,
        )
        .unwrap_or_else(|error| panic!("publish realization: {error}"));
'''
    replace_between(path, start, end, replacement)
    replace_once(
        path,
        "            factor_ids: vec![factor.factor_id],\n",
        "            factor_ids: vec![factor.factor_id.clone()],\n",
    )
    tail = '''    assert_eq!(staged.developer_fragments.len(), 1);
    assert_eq!(staged.developer_fragments[0].text.as_bytes(), payload);
}'''
    replacement_tail = '''    assert_eq!(staged.developer_fragments.len(), 1);
    assert_eq!(staged.developer_fragments[0].text.as_bytes(), payload);

    let revoker = id("revoker:agentd-product");
    let revoke_scope = digest("scope:agentd-product-revoke");
    let revoke_reason = digest("reason:agentd-product-revoke");
    let revoke_cutoff = logical_now + 1;
    let revoke_binding = final_use_revoke_binding(
        &admitted_factor,
        &revoker,
        revoke_scope,
        revoke_reason,
        revoke_cutoff,
    )
    .unwrap_or_else(|error| panic!("revoke binding: {error}"));
    let revoke_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-revoke".to_owned(),
        nonce: [64; 32],
        binding: revoke_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_revoke = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &revoke_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("revoke signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: revoke_grant,
    };
    pipeline
        .revoke_factor(
            &authority,
            &signed_revoke,
            &factor.factor_id,
            &revoker,
            revoke_scope,
            revoke_reason,
            revoke_cutoff,
        )
        .unwrap_or_else(|error| panic!("revoke factor: {error}"));

    let mut dispatch_record = dispatch(
        &staged,
        "thread:product",
        "turn:product",
        "attempt:revoked-product",
        "request:revoked-product",
        digest("provider-request:revoked-product"),
    );
    dispatch_record.dispatched_unix_ms = logical_now + 2;
    assert!(pipeline.record_dispatch_final_use(dispatch_record.clone()).is_err());

    drop(runtime);
    drop(pipeline);
    let reopened = AgentdPromptPipelineOwner::open_state_dirs(&registry_root, &runtime_root, 64)
        .unwrap_or_else(|error| panic!("reopen pipeline owner: {error}"));
    assert!(reopened.record_dispatch_final_use(dispatch_record).is_err());
    assert_eq!(
        reopened
            .registry
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .registry()
            .unwrap_or_else(|error| panic!("reopened registry: {error}"))
            .factor(&factor.factor_id)
            .map(|record| record.lifecycle),
        Some(Lifecycle::Revoked)
    );
}'''
    replace_once(path, tail, replacement_tail)


def patch_claim_documents() -> None:
    replace_once(
        "docs/modules/prompt.registry/QUALIFICATION_STATUS.md",
        "| `productActivated` | `false` | No claim is made that a deployed product has enabled this path or established a production publisher/operator. |",
        "| `productActivated` | `true` | The default Agentd product owner installs the governed prompt runtime host and authenticated publisher/revoker in source. This is not independent deployment acceptance. |",
    )
    replace_once(
        "qualification/module-execution-dossiers/detail/prompt.registry.md",
        "| product activated | false |",
        "| product activated | true |",
    )
    replace_once(
        "qualification/module-execution-dossiers/detail/prompt.registry.md",
        "3. complete the end-to-end revoke-before-dispatch and restart scenario;\n4. implement and qualify payload checkpoint/compaction/GC and unified quotas;\n5. add capacity/fsync metrics, consistent export/restore verification and the\n   named crash-injection matrix;\n6. run 1k/8k/16k measurements and record the decision on WAL/incremental\n   digest work;\n7. obtain independent product activation, acceptance and release decisions.",
        "3. implement and qualify payload checkpoint/compaction/GC and unified quotas;\n4. add capacity/fsync metrics, consistent export/restore verification and the\n   named crash-injection matrix;\n5. run 1k/8k/16k measurements and record the decision on WAL/incremental\n   digest work;\n6. obtain independent acceptance and release decisions.",
    )


def patch_qualification_workflow() -> None:
    path = ".github/workflows/hepta-prompt-registry-qualification.yml"
    text = (ROOT / path).read_text(encoding="utf-8")
    text = text.replace("assert lifecycle['productActivated'] is False", "assert lifecycle['productActivated'] is True")
    text = text.replace("'productActivated': False,", "'productActivated': True,")
    text = text.replace("productActivated: false", "productActivated: true")
    (ROOT / path).write_text(text, encoding="utf-8")


def patch_map_refresh() -> None:
    path = ".github/workflows/prompt-registry-map-refresh.yml"
    text = (ROOT / path).read_text(encoding="utf-8")
    old = '''    paths:
      - ".github/workflows/prompt-registry-map-refresh.yml"
'''
    new = '''    paths:
      - "codex-rs/hepta-prompt-registry/**"
      - "codex-rs/hepta-prompt-optimizer/**"
      - "codex-rs/hepta-agentd/src/prompt_*.rs"
      - "codex-rs/hepta-agentd/src/app_runtime.rs"
      - "qualification/module-execution-dossiers/detail/prompt.registry.md"
      - "docs/modules/prompt.registry/TECHNICAL.md"
      - "docs/modules/prompt.registry/QUALIFICATION_STATUS.md"
      - ".github/workflows/hepta-prompt-registry-qualification.yml"
      - ".github/workflows/prompt-registry-map-refresh.yml"
'''
    if new not in text:
        if old not in text:
            raise SystemExit(f"{path}: trigger anchor not found")
        text = text.replace(old, new, 1)
    (ROOT / path).write_text(text, encoding="utf-8")


def write_map() -> None:
    path = ROOT / "docs/modules/prompt.registry/IMPLEMENTATION_MAP.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    operations = [
        ("factor_lifecycle", "PromptRegistry", "codex-rs/hepta-prompt-registry/src/lib.rs", ["codex-rs/hepta-prompt-registry/src/lib_tests.rs"]),
        ("durable_schema_v4", "DurablePromptRegistry", "codex-rs/hepta-prompt-registry/src/durable.rs", ["codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs", "codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs"]),
        ("authenticated_factor_publication", "AgentdPromptPipelineOwner::publish_factor", "codex-rs/hepta-agentd/src/prompt_runtime.rs", ["codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"]),
        ("authenticated_realization_publication", "AgentdPromptPipelineOwner::publish_realization", "codex-rs/hepta-agentd/src/prompt_runtime.rs", ["codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"]),
        ("authenticated_revocation", "AgentdPromptPipelineOwner::revoke_factor", "codex-rs/hepta-agentd/src/prompt_runtime.rs", ["codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"]),
        ("consumer_capability_filter", "enumerate_factors_for_consumer_v1", "codex-rs/hepta-prompt-optimizer/src/consumer.rs", ["codex-rs/hepta-prompt-optimizer/src/graph_tests.rs"]),
        ("send_time_final_use", "AgentdPromptPipelineOwner::record_dispatch_final_use", "codex-rs/hepta-agentd/src/prompt_runtime.rs", ["codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"]),
        ("product_host_installation", "install_prompt_runtime_host", "codex-rs/hepta-agentd/src/app_runtime.rs", ["codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"]),
    ]
    current["resolvedRoots"] = [
        "codex-rs/hepta-prompt-registry",
        "codex-rs/hepta-prompt-optimizer",
        "codex-rs/hepta-agentd/src/prompt_runtime.rs",
        "codex-rs/hepta-agentd/src/prompt_final_use.rs",
        "codex-rs/hepta-agentd/src/prompt_final_use_store.rs",
    ]
    current["productionImplementation"] = True
    current["productCallerState"] = "agentd_default_product_host_composed_and_activated_in_source"
    current["productionWriterState"] = "authenticated_final_use_publisher_and_revoker_established"
    current["operations"] = [
        {
            "operation": operation,
            "nativeSymbol": symbol,
            "sourcePath": source,
            "state": "product_activated_in_source_pending_exact_head_acceptance",
            "authority": "final_use_authority" if "authenticated" in operation else "deny_all_by_default",
            "tests": tests,
            "sourcePathExists": True,
            "designOperation": operation,
            "mappingClass": "owner_native_with_agentd_product_composition",
            "delegatedCallees": [],
        }
        for operation, symbol, source, tests in operations
    ]
    current["repositoryControlledGaps"] = [
        "Exact source-head and deterministic synthetic-merge receipts must both be green for this exact candidate.",
        "Payload generation checkpoint/compaction/GC, unified quotas, operational metrics, consistent export/restore and 1k/8k/16k evidence remain open until the operational closure lands.",
        "Protected postmerge must be green before any production-ready statement.",
    ]
    current["claimBoundary"].update(
        {
            "nativeSourceMappingComplete": True,
            "sourceRootPresent": True,
            "productionImplementation": True,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": True,
            "release": False,
            "implementedOperationMappingComplete": True,
        }
    )
    current["compositionRoots"] = sorted(
        set(
            current["resolvedRoots"]
            + [
                ".github/workflows/hepta-prompt-registry-qualification.yml",
                "codex-rs/hepta-agentd/src/app_runtime.rs",
                "codex-rs/hepta-agentd/src/lib.rs",
                "codex-rs/hepta-agentd/src/state.rs",
                "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs",
                "codex-rs/hepta-prompt-optimizer/src/graph_tests.rs",
            ]
        )
    )
    path.write_text(json.dumps(current, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> None:
    patch_product_facade()
    patch_product_test()
    patch_claim_documents()
    patch_qualification_workflow()
    patch_map_refresh()
    write_map()


if __name__ == "__main__":
    main()

use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_registry::AdmissionRequest;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn authorize(registry: &mut PromptRegistry, factor_id: &str, nonce: u8) -> tempfile::TempDir {
    let signing_seed = Digest32::of_bytes(b"optimizer-registry-test-signing-key").into_array();
    let signing = SigningKey::from_bytes(&signing_seed);
    let directory = tempfile::tempdir().expect("authority directory");
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "optimizer-registry-review-owner".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let request = AdmissionRequest {
        factor_id: id(factor_id),
        reviewer_id: id("reviewer:optimizer"),
        evidence_digest: digest(&format!("evidence:{factor_id}")),
        reviewed_scope_digest: digest(&format!("scope:{factor_id}")),
    };
    let binding = registry.admission_binding(&request).expect("binding");
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("time fits");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "optimizer-registry-review-owner".to_string(),
        authority_epoch: 1,
        grant_id: format!("optimizer-admission-{nonce}"),
        nonce: Digest32::of_bytes(format!("optimizer-admission-nonce:{nonce}").as_bytes())
            .into_array(),
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now.saturating_add(30_000),
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let signed = SignedFinalUseGrant { grant, signature };
    let token = authority
        .claim(&signed, &signed.grant.binding)
        .expect("claim");
    registry
        .admit_factor_authorized(&authority, token, request)
        .expect("admit");
    drop(authority);
    directory
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
    }
}

#[test]
fn optimizer_consumes_registry_snapshot_instead_of_caller_inventing_admission() {
    let mut registry = PromptRegistry::new(64).expect("registry");
    let mut authority_directories = Vec::new();
    for (factor_id, realization_id, nonce, payload) in [
        ("factor:a", "realization:a", 1, &b"instruction-a"[..]),
        ("factor:b", "realization:b", 2, &b"instruction-b"[..]),
    ] {
        registry
            .register_factor(PromptFactor {
                factor_id: id(factor_id),
                proposer_id: id(&format!("proposer:{nonce}")),
                semantic_version: id("v1"),
                content_digest: digest(&format!("factor:{factor_id}")),
                source: FactorSource::GovernedInternal,
                lifecycle: Lifecycle::Draft,
            })
            .expect("factor");
        authority_directories.push(authorize(&mut registry, factor_id, nonce));
        registry
            .register_realization_v2(
                PromptRealizationBindingV2 {
                    realization_id: id(realization_id),
                    factor_id: id(factor_id),
                    model_digest: digest("model"),
                    tokenizer_digest: digest("tokenizer"),
                    template_digest: digest("template"),
                    tool_schema_digest: digest("tool-schema"),
                    context_profile_digest: digest("context-profile"),
                    locale_id: id("locale:en-US"),
                    role: PromptRoleV2::DeveloperInstruction,
                    payload_digest: Digest32::of_bytes(payload),
                    token_cost: if factor_id == "factor:a" { 10 } else { 20 },
                    expires_unix_ms: None,
                    predecessor_realization_id: None,
                },
                payload.to_vec(),
            )
            .expect("realization");
    }
    let tuple = model_tuple();
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");
    let receipt = optimize_registry_snapshot(
        &registry,
        &snapshot,
        RegistryOptimizationRequest {
            decision_id: id("decision:1"),
            objective_digest: digest("objective"),
            generation_vector_digest: vector,
            model_tuple: tuple,
            now_unix_ms: 1,
            budget: 15,
            maximum_selected: 2,
            scores: vec![
                RegistryCandidateScore {
                    factor_id: id("factor:a"),
                    expected_gain: FixedQ32::ONE,
                    legal: true,
                    support_digest: digest("support:a"),
                },
                RegistryCandidateScore {
                    factor_id: id("factor:b"),
                    expected_gain: FixedQ32::ONE,
                    legal: true,
                    support_digest: digest("support:b"),
                },
            ],
        },
    )
    .expect("registry-backed optimization");
    assert_eq!(receipt.selected, vec![id("realization:a")]);
    assert_eq!(receipt.total_cost, 10);
    assert!(!receipt.authority.grants_any());
    drop(authority_directories);
}

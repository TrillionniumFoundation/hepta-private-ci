use super::*;

use std::collections::BTreeSet;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

#[test]
fn unsupported_authority_cannot_admit_or_stage_a_durable_prompt_draft()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let registry_root = temp.path().join("prompt-registry");
    let runtime_root = temp.path().join("prompt-runtime");
    let authority_root = temp.path().join("prompt-authority");
    let pipeline = AgentdPromptPipelineOwner::open_state_dirs(
        &registry_root,
        &runtime_root,
        /*maximum_registry_records*/ 64,
    )?;
    let factor = PromptFactor {
        factor_id: StableId::new("factor:agentd-product")?,
        proposer_id: StableId::new("proposer:agentd-product")?,
        semantic_version: StableId::new("v1")?,
        semantic_purpose: "inspect evidence before mutation".into(),
        authority_class: "registered_prompt_factor".into(),
        eligible_objective_dimensions: vec![StableId::new("dimension:truth")?],
        content_digest: Digest32::of_bytes(b"factor:agentd-product"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    let before = {
        let mut registry = pipeline.registry.lock().map_err(|_| "registry lock")?;
        registry.register_factor(factor.clone())?;
        registry.registry()?.snapshot_digest()
    };
    let authority = FinalUseAuthority::open_state_dir(
        &authority_root,
        "review-authority:agentd-prompt".into(),
        SigningKey::from_bytes(&[61; 32]).verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    );
    assert_eq!(authority.err(), Some(FinalUseError::UnsafeStateDirectory));
    assert!(!authority_root.exists());

    let tuple = PromptModelTupleV2 {
        model_id: StableId::new("model:agentd-product")?,
        model_version: "2026-09-20".into(),
        model_digest: Digest32::of_bytes(b"model"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        template_digest: Digest32::of_bytes(b"template"),
        tool_schema_digest: Digest32::of_bytes(b"tool-schema"),
        context_profile_digest: Digest32::of_bytes(b"context-profile"),
        locale_id: StableId::new("locale:en-US")?,
    };
    let mut request = PromptEnumerationRequestV1 {
        set_id: StableId::new("enumeration:agentd-product")?,
        objective_digest: Digest32::of_bytes(b"objective"),
        state_digest: Digest32::of_bytes(b"state"),
        generation_vector_digest: Digest32::of_bytes(b"generation"),
        model_tuple: tuple,
        now_unix_ms: 100,
        required_factor_ids: Vec::new(),
        maximum_candidates: 8,
        selection_grammar_digest: Digest32::of_bytes(b"grammar"),
    };
    let enumerated = pipeline.enumerate_candidates(request.clone())?;
    assert!(enumerated.candidates.is_empty());
    assert!(!enumerated.receipt.authority.grants_any());
    request.required_factor_ids.push(factor.factor_id.clone());
    assert!(matches!(
        pipeline.enumerate_candidates(request),
        Err(AgentdPromptPipelineError::CandidateSource(_))
    ));
    let runtime = pipeline.runtime_owner();
    assert_eq!(runtime.staged_count()?, 0);
    assert!(
        runtime
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:product".into(),
                turn_id: "turn:product".into(),
                model_context_window: Some(128),
            })?
            .is_none()
    );
    {
        let registry = pipeline.registry.lock().map_err(|_| "registry lock")?;
        assert_eq!(registry.registry()?.snapshot_digest(), before);
        assert_eq!(
            registry.registry()?.factor(&factor.factor_id),
            Some(&factor)
        );
    }
    drop(runtime);
    drop(pipeline);
    let reopened = AgentdPromptPipelineOwner::open_state_dirs(
        &registry_root,
        &runtime_root,
        /*maximum_registry_records*/ 64,
    )?;
    assert_eq!(reopened.runtime_owner().staged_count()?, 0);
    let registry = reopened.registry.lock().map_err(|_| "registry lock")?;
    assert_eq!(registry.registry()?.snapshot_digest(), before);
    assert_eq!(
        registry.registry()?.factor(&factor.factor_id),
        Some(&factor)
    );
    assert!(!authority_root.exists());
    Ok(())
}

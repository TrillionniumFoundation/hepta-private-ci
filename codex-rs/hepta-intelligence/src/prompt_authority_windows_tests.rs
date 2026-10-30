use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistryV2Error;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;

#[test]
fn unsupported_authority_leaves_no_admitted_prompt_or_deliverable_payload()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("registry");
    let authority_root = temp.path().join("authority");
    let mut registry = DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64)?;
    let factor = PromptFactor {
        factor_id: StableId::new("factor:unadmitted")?,
        proposer_id: StableId::new("proposer:1")?,
        semantic_version: StableId::new("v1")?,
        semantic_purpose: "inspect evidence before mutation".into(),
        authority_class: "registered_prompt_factor".into(),
        eligible_objective_dimensions: vec![StableId::new("dimension:truth")?],
        content_digest: Digest32::of_bytes(b"factor:unadmitted"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry.register_factor(factor.clone())?;
    let before = registry.registry()?.snapshot_digest();
    let authority = FinalUseAuthority::open_state_dir(
        &authority_root,
        "review-authority:prompt".into(),
        SigningKey::from_bytes(&[23; 32]).verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    );
    assert_eq!(authority.err(), Some(FinalUseError::UnsafeStateDirectory));
    assert!(!authority_root.exists());

    let tuple = PromptModelTupleV2 {
        model_id: StableId::new("model:test")?,
        model_version: "2026-09-21".into(),
        model_digest: Digest32::of_bytes(b"model"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        template_digest: Digest32::of_bytes(b"template"),
        tool_schema_digest: Digest32::of_bytes(b"tools"),
        context_profile_digest: Digest32::of_bytes(b"context-profile"),
        locale_id: StableId::new("locale:en-US")?,
    };
    let generation = Digest32::of_bytes(b"generation-vector");
    let snapshot = registry.snapshot_v2(generation, &tuple)?;
    let available = registry.read_compatible_v2(
        &snapshot,
        generation,
        &tuple,
        /*now_unix_ms*/ 100,
        vec![],
        /*maximum_results*/ 8,
    )?;
    assert!(available.bindings.is_empty());
    assert!(!available.authority.grants_any());
    assert!(matches!(
        registry.read_compatible_v2(
            &snapshot,
            generation,
            &tuple,
            /*now_unix_ms*/ 100,
            vec![factor.factor_id.clone()],
            /*maximum_results*/ 8,
        ),
        Err(DurableRegistryError::Read(
            PromptRegistryV2Error::RequiredFactorUnavailable
        ))
    ));
    assert!(matches!(
        registry.dereference_realization_v2(
            &StableId::new("realization:unadmitted")?,
            &snapshot,
            generation,
            &tuple,
            /*now_unix_ms*/ 100,
        ),
        Err(DurableRegistryError::Read(
            PromptRegistryV2Error::PayloadUnavailable
        ))
    ));
    assert_eq!(registry.registry()?.snapshot_digest(), before);
    assert_eq!(
        registry.registry()?.factor(&factor.factor_id),
        Some(&factor)
    );
    drop(registry);
    let reopened = DurablePromptRegistry::open_state_dir(&root, /*maximum_records*/ 64)?;
    assert_eq!(reopened.registry()?.snapshot_digest(), before);
    assert_eq!(
        reopened.registry()?.factor(&factor.factor_id),
        Some(&factor)
    );
    assert!(!authority_root.exists());
    Ok(())
}

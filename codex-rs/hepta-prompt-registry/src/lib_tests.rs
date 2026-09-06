use super::*;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn factor(source: FactorSource) -> PromptFactor {
    PromptFactor {
        factor_id: id("factor:1"),
        proposer_id: id("proposer:1"),
        semantic_version: id("v1"),
        content_digest: digest(b"factor"),
        source,
        lifecycle: Lifecycle::Draft,
    }
}

fn registry() -> PromptRegistry {
    let Ok(registry) = PromptRegistry::new(32) else {
        panic!("test registry must initialize");
    };
    registry
}

#[test]
fn external_material_cannot_admit_itself() {
    let mut registry = registry();
    assert!(
        registry
            .register_factor(factor(FactorSource::ExternalUntrusted))
            .is_ok()
    );
    assert_eq!(
        registry.admit_factor(&id("factor:1"), &id("reviewer:1"), digest(b"evidence")),
        Err(Error::ExternalSelfAdmission)
    );
}

#[test]
fn independent_admission_enables_realization_registration() {
    let mut registry = registry();
    assert!(
        registry
            .register_factor(factor(FactorSource::GovernedInternal))
            .is_ok()
    );
    let Ok(receipt) =
        registry.admit_factor(&id("factor:1"), &id("reviewer:1"), digest(b"evidence"))
    else {
        panic!("independent admission must succeed");
    };
    assert!(!receipt.authority.grants_any());

    let realization = PromptRealization {
        realization_id: id("realization:1"),
        factor_id: id("factor:1"),
        model_digest: digest(b"model"),
        tokenizer_digest: digest(b"tokenizer"),
        content_digest: digest(b"realization"),
        active: true,
    };
    assert!(registry.register_realization(realization).is_ok());
}

#[test]
fn proposer_cannot_self_review() {
    let mut registry = registry();
    assert!(
        registry
            .register_factor(factor(FactorSource::GovernedInternal))
            .is_ok()
    );
    assert_eq!(
        registry.admit_factor(&id("factor:1"), &id("proposer:1"), digest(b"evidence")),
        Err(Error::SelfReview)
    );
}

#[test]
fn revocation_cascades_and_is_terminal() {
    let mut registry = registry();
    assert!(
        registry
            .register_factor(factor(FactorSource::GovernedInternal))
            .is_ok()
    );
    assert!(
        registry
            .admit_factor(&id("factor:1"), &id("reviewer:1"), digest(b"evidence"))
            .is_ok()
    );
    let realization = PromptRealization {
        realization_id: id("realization:1"),
        factor_id: id("factor:1"),
        model_digest: digest(b"model"),
        tokenizer_digest: digest(b"tokenizer"),
        content_digest: digest(b"realization"),
        active: true,
    };
    assert!(registry.register_realization(realization).is_ok());
    assert!(registry.revoke_factor(&id("factor:1")).is_ok());
    let Some(record) = registry.realization(&id("realization:1")) else {
        panic!("realization must remain interpretable");
    };
    assert!(!record.active);
    assert_eq!(
        registry.admit_factor(&id("factor:1"), &id("reviewer:2"), digest(b"evidence:2")),
        Err(Error::InvalidTransition)
    );
}

#[test]
fn conflicting_identity_is_rejected() {
    let mut registry = registry();
    let value = factor(FactorSource::GovernedInternal);
    assert!(registry.register_factor(value.clone()).is_ok());
    let mut drifted = value;
    drifted.content_digest = digest(b"drift");
    assert_eq!(
        registry.register_factor(drifted),
        Err(Error::FactorConflict("factor:1".to_string()))
    );
}

#[test]
fn exhausted_revision_keeps_factor_insertion_and_admission_atomic() {
    let mut registry = registry();
    let value = factor(FactorSource::GovernedInternal);
    let Ok(maximum) = Revision::new(u64::MAX) else {
        panic!("maximum revision must be representable");
    };
    registry.revision = maximum;
    let empty = registry.clone();
    assert_eq!(
        registry.register_factor(value.clone()),
        Err(Error::RevisionOverflow)
    );
    assert_eq!(registry, empty);

    registry
        .factors
        .insert(value.factor_id.clone(), value.clone());
    let draft = registry.clone();
    assert_eq!(
        registry.admit_factor(&value.factor_id, &id("reviewer:1"), digest(b"evidence")),
        Err(Error::RevisionOverflow)
    );
    assert_eq!(registry, draft);
    // Identical observations do not allocate a revision, even at exhaustion.
    assert_eq!(
        registry.register_factor(value),
        Ok(draft.receipt(MutationDisposition::Unchanged))
    );
    assert_eq!(registry, draft);
}

#[test]
fn exhausted_revision_preserves_realizations_during_retirement_and_revocation() {
    let mut registry = registry();
    assert!(
        registry
            .register_factor(factor(FactorSource::GovernedInternal))
            .is_ok()
    );
    assert!(
        registry
            .admit_factor(&id("factor:1"), &id("reviewer:1"), digest(b"evidence"))
            .is_ok()
    );
    let realization = PromptRealization {
        realization_id: id("realization:1"),
        factor_id: id("factor:1"),
        model_digest: digest(b"model"),
        tokenizer_digest: digest(b"tokenizer"),
        content_digest: digest(b"realization"),
        active: true,
    };
    let Ok(maximum) = Revision::new(u64::MAX) else {
        panic!("maximum revision must be representable");
    };
    registry.revision = maximum;
    let admitted = registry.clone();
    assert_eq!(
        registry.register_realization(realization.clone()),
        Err(Error::RevisionOverflow)
    );
    assert_eq!(registry, admitted);

    registry
        .realizations
        .insert(realization.realization_id.clone(), realization.clone());
    let active = registry.clone();
    assert_eq!(
        registry.retire_factor(&id("factor:1")),
        Err(Error::RevisionOverflow)
    );
    assert_eq!(registry, active);
    assert_eq!(
        registry.revoke_factor(&id("factor:1")),
        Err(Error::RevisionOverflow)
    );
    assert_eq!(registry, active);
    assert_eq!(
        registry.register_realization(realization),
        Ok(active.receipt(MutationDisposition::Unchanged))
    );
    assert_eq!(registry, active);
}

use super::*;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

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


#[test]
fn signed_admission_persists_scope_evidence_and_grant_lineage() {
    let mut registry = registry();
    let value = factor(FactorSource::GovernedInternal);
    registry
        .register_factor(value.clone())
        .unwrap_or_else(|error| panic!("register factor: {error}"));

    let signing_key = SigningKey::from_bytes(&[7; 32]);
    let authority = AdmissionAuthority::new(
        id("review-authority:1"),
        signing_key.verifying_key().to_bytes(),
    )
    .unwrap_or_else(|error| panic!("authority: {error}"));
    let grant = AdmissionGrantV1 {
        schema_version: 1,
        signer_id: "review-authority:1".to_owned(),
        grant_id: "admission:1".to_owned(),
        binding: AdmissionBindingV1 {
            factor_id: value.factor_id.to_string(),
            factor_content_sha256: value.content_digest.into_array(),
            reviewer_id: "reviewer:1".to_owned(),
            reviewed_scope_sha256: digest(b"scope").into_array(),
            evidence_sha256: digest(b"evidence").into_array(),
        },
        not_before_unix_ms: 10,
        expires_at_unix_ms: 100,
    };
    let signature = signing_key
        .sign(
            &grant
                .signing_bytes()
                .unwrap_or_else(|error| panic!("signing bytes: {error}")),
        )
        .to_bytes()
        .to_vec();
    let signed = SignedAdmissionGrantV1 { grant, signature };
    let verified = authority
        .verify(&signed, &value, 20)
        .unwrap_or_else(|error| panic!("verify admission: {error}"));
    registry
        .admit_factor_verified(verified, 20)
        .unwrap_or_else(|error| panic!("admit verified: {error}"));

    let event = registry
        .lifecycle_events()
        .last()
        .expect("admission lifecycle event");
    assert_eq!(event.kind, LifecycleEventKind::Admitted);
    assert_eq!(event.actor_id, id("reviewer:1"));
    assert_eq!(event.admission_grant_id, Some(id("admission:1")));
    assert_eq!(event.scope_digest, Some(digest(b"scope")));
    assert_eq!(event.evidence_digest, digest(b"evidence"));
    assert_eq!(registry.admission_event_digest(&value.factor_id), Some(event.event_digest));
}

#[test]
fn verified_admission_cannot_be_used_after_expiry() {
    let mut registry = registry();
    let value = factor(FactorSource::GovernedInternal);
    registry
        .register_factor(value.clone())
        .unwrap_or_else(|error| panic!("register factor: {error}"));

    let signing_key = SigningKey::from_bytes(&[8; 32]);
    let authority = AdmissionAuthority::new(
        id("review-authority:2"),
        signing_key.verifying_key().to_bytes(),
    )
    .unwrap_or_else(|error| panic!("authority: {error}"));
    let grant = AdmissionGrantV1 {
        schema_version: 1,
        signer_id: "review-authority:2".to_owned(),
        grant_id: "admission:2".to_owned(),
        binding: AdmissionBindingV1 {
            factor_id: value.factor_id.to_string(),
            factor_content_sha256: value.content_digest.into_array(),
            reviewer_id: "reviewer:2".to_owned(),
            reviewed_scope_sha256: digest(b"scope:2").into_array(),
            evidence_sha256: digest(b"evidence:2").into_array(),
        },
        not_before_unix_ms: 10,
        expires_at_unix_ms: 30,
    };
    let signature = signing_key
        .sign(
            &grant
                .signing_bytes()
                .unwrap_or_else(|error| panic!("signing bytes: {error}")),
        )
        .to_bytes()
        .to_vec();
    let verified = authority
        .verify(&SignedAdmissionGrantV1 { grant, signature }, &value, 20)
        .unwrap_or_else(|error| panic!("verify admission: {error}"));
    assert_eq!(
        registry.admit_factor_verified(verified, 30),
        Err(Error::InvalidTransition)
    );
    assert_eq!(
        registry.factor(&value.factor_id).map(|factor| factor.lifecycle),
        Some(Lifecycle::Draft)
    );
}

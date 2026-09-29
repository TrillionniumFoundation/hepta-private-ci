use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use codex_hepta_prompt_registry::final_use_revoke_binding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("identity: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}


fn test_nonce(label: &str) -> [u8; 32] {
    let value = Digest32::of_bytes(
        format!("hepta.prompt-registry.test-nonce.v1:{label}").as_bytes(),
    );
    *value.as_array()
}

fn sign(grant: FinalUseGrant, key: &SigningKey) -> SignedFinalUseGrant {
    let bytes = grant
        .signing_bytes()
        .unwrap_or_else(|error| panic!("grant: {error}"));
    SignedFinalUseGrant {
        signature: key.sign(&bytes).to_bytes().to_vec(),
        grant,
    }
}

fn fixture(directory: &Path) -> (DurablePromptRegistry, PromptFinalUseLeaseV1) {
    let mut registry = DurablePromptRegistry::open_state_dir(directory, 64)
        .unwrap_or_else(|error| panic!("registry: {error}"));
    let authority_root = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let key = SigningKey::from_bytes(&test_nonce("final-use-signing-key"));
    let authority = FinalUseAuthority::open_state_dir(
        &authority_root.path().join("authority"),
        "review-authority:final-use".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap_or_else(|error| panic!("authority: {error}"));
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_else(|error| panic!("clock: {error}"))
            .as_millis(),
    )
    .unwrap_or_else(|error| panic!("clock bounds: {error}"));
    let factor = PromptFactor {
        factor_id: id("factor:final-use"),
        proposer_id: id("proposer:final-use"),
        semantic_version: id("v1"),
        semantic_purpose: "test governed final use".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:quality")],
        content_digest: digest("semantic-factor"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .unwrap_or_else(|error| panic!("factor: {error}"));
    let scope = digest("scope:final-use");
    let reviewer = id("reviewer:final-use");
    let evidence = digest("review-evidence");
    let binding = final_use_admission_binding(&factor, &reviewer, scope, evidence)
        .unwrap_or_else(|error| panic!("admission binding: {error}"));
    let admission = sign(
        FinalUseGrant {
            schema_version: 1,
            signer_id: "review-authority:final-use".to_owned(),
            authority_epoch: 1,
            grant_id: "grant:admission".to_owned(),
            nonce: test_nonce("final-use-admission"),
            binding,
            not_before_unix_ms: now.saturating_sub(1000),
            expires_at_unix_ms: now + 120_000,
        },
        &key,
    );
    registry
        .admit_factor_final_use(&authority, &admission, &factor.factor_id, scope, evidence)
        .unwrap_or_else(|error| panic!("admission: {error}"));
    let model_tuple = PromptModelTupleV2 {
        model_id: id("model:final-use"),
        model_version: "v1".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
    };
    let payload = b"Verify before mutation.".to_vec();
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:final-use"),
        factor_id: factor.factor_id.clone(),
        model_id: model_tuple.model_id.clone(),
        model_version: model_tuple.model_version.clone(),
        model_digest: model_tuple.model_digest,
        tokenizer_digest: model_tuple.tokenizer_digest,
        template_digest: model_tuple.template_digest,
        tool_schema_digest: model_tuple.tool_schema_digest,
        context_profile_digest: model_tuple.context_profile_digest,
        locale_id: model_tuple.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(&payload),
        token_cost: 4,
        expires_unix_ms: Some(now + 60_000),
    };
    let admitted = registry
        .registry()
        .unwrap_or_else(|error| panic!("registry: {error}"))
        .factor(&factor.factor_id)
        .cloned()
        .unwrap_or_else(|| panic!("admitted factor"));
    let publisher = id("publisher:final-use");
    let binding = final_use_realization_binding(&admitted, &publisher, scope, &realization, None)
        .unwrap_or_else(|error| panic!("publication binding: {error}"));
    let publication = sign(
        FinalUseGrant {
            schema_version: 1,
            signer_id: "review-authority:final-use".to_owned(),
            authority_epoch: 1,
            grant_id: "grant:payload".to_owned(),
            nonce: test_nonce("final-use-realization"),
            binding,
            not_before_unix_ms: now.saturating_sub(1000),
            expires_at_unix_ms: now + 120_000,
        },
        &key,
    );
    registry
        .register_realization_payload_final_use_v2(
            &authority,
            &publication,
            &publisher,
            scope,
            realization.clone(),
            payload,
            None,
        )
        .unwrap_or_else(|error| panic!("publish: {error}"));
    let generation = digest("generation");
    let snapshot = registry
        .snapshot_v2(generation, &model_tuple)
        .unwrap_or_else(|error| panic!("snapshot: {error}"));
    let mut lease = PromptFinalUseLeaseV1 {
        schema_version: 1,
        compilation_id: id("compilation:final-use"),
        context_attachment_digest: digest("attachment"),
        context_payload_digest: digest("compiled-payload"),
        registry_snapshot_digest: snapshot.snapshot_digest,
        generation_vector_digest: generation,
        model_tuple,
        issued_unix_ms: now,
        valid_until_unix_ms: now + 60_000,
        selections: vec![PromptFinalUseSelectionV1 {
            factor_id: factor.factor_id,
            realization_id: realization.realization_id.clone(),
            binding_digest: realization.digest(),
            payload_digest: realization.payload_digest,
        }],
        lease_digest: Digest32::ZERO,
    };
    lease.lease_digest = lease.compute_digest();
    (registry, lease)
}

fn revoke(registry: &mut DurablePromptRegistry, lease: &PromptFinalUseLeaseV1) {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let key = SigningKey::from_bytes(&test_nonce("final-use-revoke-signing-key"));
    let authority = FinalUseAuthority::open_state_dir(
        &temporary.path().join("authority"),
        "revoke-authority:final-use".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap_or_else(|error| panic!("authority: {error}"));
    let factor_id = &lease.selections[0].factor_id;
    let factor = registry
        .registry()
        .unwrap_or_else(|error| panic!("registry: {error}"))
        .factor(factor_id)
        .cloned()
        .unwrap_or_else(|| panic!("factor"));
    let actor = id("operator:revoke");
    let scope = digest("revoke-scope");
    let reason = digest("revoke-reason");
    let cutoff = lease.issued_unix_ms;
    let binding = final_use_revoke_binding(&factor, &actor, scope, reason, cutoff)
        .unwrap_or_else(|error| panic!("revoke binding: {error}"));
    let grant = sign(
        FinalUseGrant {
            schema_version: 1,
            signer_id: "revoke-authority:final-use".to_owned(),
            authority_epoch: 1,
            grant_id: "grant:revoke".to_owned(),
            nonce: test_nonce("final-use-revoke"),
            binding,
            not_before_unix_ms: cutoff.saturating_sub(1000),
            expires_at_unix_ms: cutoff + 120_000,
        },
        &key,
    );
    registry
        .revoke_factor_final_use(&authority, &grant, factor_id, &actor, scope, reason, cutoff)
        .unwrap_or_else(|error| panic!("revoke: {error}"));
}

fn boundary(lease: &PromptFinalUseLeaseV1) -> PromptFinalUseBoundaryV1<'_> {
    PromptFinalUseBoundaryV1 {
        compilation_id: &lease.compilation_id,
        context_attachment_digest: lease.context_attachment_digest,
        context_payload_digest: lease.context_payload_digest,
        now_unix_ms: lease.issued_unix_ms,
    }
}

#[test]
fn final_use_current_boundary_and_payload_are_bound() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let (registry, lease) = fixture(&temporary.path().join("registry"));
    let validator = PromptFinalUseValidator::default();
    assert_eq!(
        validator.validate(&lease, &registry, &boundary(&lease)),
        Ok(())
    );
    let mut changed = boundary(&lease);
    changed.context_payload_digest = digest("changed-payload");
    assert_eq!(
        validator.validate(&lease, &registry, &changed),
        Err(PromptFinalUseLeaseError::BoundaryBindingMismatch)
    );
    assert_eq!(validator.metrics().checked, 2);
    assert_eq!(validator.metrics().rejected, 1);
    assert_eq!(validator.metrics().identity_conflicts, 1);
}

#[test]
fn final_use_revocation_precedes_snapshot_error_and_survives_restart() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let path = temporary.path().join("registry");
    let (mut registry, lease) = fixture(&path);
    revoke(&mut registry, &lease);
    assert_eq!(
        lease.validate_current(&registry, lease.issued_unix_ms),
        Err(PromptFinalUseLeaseError::Revoked)
    );
    drop(registry);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64)
        .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert_eq!(
        lease.validate_current(&reopened, lease.issued_unix_ms),
        Err(PromptFinalUseLeaseError::Revoked)
    );
    let validator = PromptFinalUseValidator::default();
    assert_eq!(
        validator.validate(&lease, &reopened, &boundary(&lease)),
        Err(PromptFinalUseLeaseError::Revoked)
    );
    assert_eq!(validator.metrics().withdrawn, 1);
}

#[test]
fn final_use_expiry_and_generation_drift_fail_closed() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let (registry, lease) = fixture(&temporary.path().join("registry"));
    assert_eq!(
        lease.validate_current(&registry, lease.valid_until_unix_ms),
        Err(PromptFinalUseLeaseError::Expired)
    );
    assert_eq!(
        lease.validate_current(&registry, lease.issued_unix_ms - 1),
        Err(PromptFinalUseLeaseError::Expired)
    );
    let mut changed = lease.clone();
    changed.generation_vector_digest = digest("different-generation");
    changed.lease_digest = changed.compute_digest();
    assert_eq!(
        changed.validate_current(&registry, lease.issued_unix_ms),
        Err(PromptFinalUseLeaseError::RegistrySnapshotChanged)
    );
    let mut changed = lease.clone();
    changed.selections[0].payload_digest = digest("changed-selection-payload");
    changed.lease_digest = changed.compute_digest();
    assert_eq!(
        changed.validate_current(&registry, lease.issued_unix_ms),
        Err(PromptFinalUseLeaseError::SelectionChanged)
    );
}

#[test]
fn final_use_rejects_oversize_and_duplicate_realization_selections() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let (_registry, lease) = fixture(&temporary.path().join("registry"));
    let mut oversized = lease.clone();
    oversized.selections = vec![lease.selections[0].clone(); MAX_FINAL_USE_SELECTIONS + 1];
    assert_eq!(
        oversized.validate_shape(),
        Err(PromptFinalUseLeaseError::InvalidShape)
    );
    let mut duplicate = lease.clone();
    let mut second = duplicate.selections[0].clone();
    second.factor_id = id("factor:other");
    duplicate.selections.push(second);
    duplicate.selections.sort();
    duplicate.lease_digest = duplicate.compute_digest();
    assert_eq!(
        duplicate.validate_shape(),
        Err(PromptFinalUseLeaseError::InvalidShape)
    );
}

#[test]
fn final_use_errors_have_distinct_non_blind_retry_policies_and_redacted_messages() {
    assert_eq!(
        PromptFinalUseLeaseError::Revoked.recovery(),
        PromptFinalUseRecovery::Reject
    );
    assert_eq!(
        PromptFinalUseLeaseError::RegistrySnapshotChanged.recovery(),
        PromptFinalUseRecovery::Recompile
    );
    assert_eq!(
        PromptFinalUseLeaseError::from_registry(DurableRegistryError::StorageFull).recovery(),
        PromptFinalUseRecovery::RelieveCapacity
    );
    assert_eq!(
        PromptFinalUseLeaseError::from_registry(DurableRegistryError::ReopenRequired).recovery(),
        PromptFinalUseRecovery::ReopenAndReconcile
    );
    assert_ne!(
        PromptFinalUseLeaseError::from_registry(DurableRegistryError::ReopenRequired).code(),
        PromptFinalUseLeaseError::from_registry(DurableRegistryError::IndeterminateDurability)
            .code()
    );
    let error = PromptFinalUseLeaseError::Compiled("SECRET_RAW_PROMPT".to_owned());
    assert!(!error.to_string().contains("SECRET_RAW_PROMPT"));
}

#[test]
fn final_use_integrity_error_is_not_a_recompilation_hint() {
    let error = PromptFinalUseLeaseError::from_registry(DurableRegistryError::Read(
        codex_hepta_prompt_registry::PromptRegistryV2Error::PayloadDigestMismatch,
    ));
    assert_eq!(error, PromptFinalUseLeaseError::IntegrityRejected);
    assert_eq!(error.recovery(), PromptFinalUseRecovery::Reject);
}

#[test]
fn final_use_rejects_duplicate_factor_with_distinct_realization_ids() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let (_registry, mut lease) = fixture(&temporary.path().join("registry"));
    let mut other = lease.selections[0].clone();
    other.realization_id = id("realization:other");
    lease.selections.push(other);
    lease.selections.sort();
    lease.lease_digest = lease.compute_digest();
    assert_eq!(
        lease.validate_shape(),
        Err(PromptFinalUseLeaseError::InvalidShape)
    );
}

//! Shared unsigned binding construction. Legacy signing bytes are unchanged.
use super::*;
use crate::signed_intent::SignedSupervisorIntent;
use codex_hepta_fleet::ReleaseBinding;

#[expect(
    clippy::too_many_arguments,
    reason = "each authority binding stays explicit"
)]
pub(super) fn grant(
    signer_id: &str,
    signer_epoch: u64,
    agent_id: &AgentId,
    source_release: impl Into<String>,
    target_release: impl Into<String>,
    transition: H7H89ProductionTransition,
    h7_envelope: &H7SignedArtifactEnvelope,
    expected_control_revision: u64,
    expected_lifecycle_generation: u64,
    authority_epoch: u64,
    issued_at_unix_seconds: u64,
    expires_at_unix_seconds: u64,
) -> Result<H7H89ProductionGrant, ProductionAuthorityError> {
    h7_envelope
        .validate_shape()
        .map_err(|error| ProductionAuthorityError::H7Binding(error.to_string()))?;
    let source_release = source_release.into();
    let target_release = target_release.into();
    validate_release(&source_release)?;
    validate_release(&target_release)?;
    if source_release == target_release {
        return Err(ProductionAuthorityError::Invalid(
            "source and target releases must differ".to_string(),
        ));
    }
    if expected_lifecycle_generation == 0 || authority_epoch == 0 {
        return Err(ProductionAuthorityError::Invalid(
            "lifecycle generation and authority epoch must be non-zero".to_string(),
        ));
    }
    validate_window(issued_at_unix_seconds, expires_at_unix_seconds)?;
    let grant = H7H89ProductionGrant {
        schema_version: SIGNED_AUTHORITY_SCHEMA_VERSION,
        namespace: SIGNED_AUTHORITY_NAMESPACE.to_string(),
        agent_id: agent_id.to_string(),
        source_release,
        target_release,
        transition,
        h7_envelope_sha256: h7_envelope.digest().clone(),
        artifact_sha256: h7_envelope.artifact_digest().clone(),
        expected_control_revision,
        expected_lifecycle_generation,
        authority_epoch,
        signer_id: signer_id.to_string(),
        signer_epoch,
        issued_at_unix_seconds,
        expires_at_unix_seconds,
        production_authority: true,
        external_effects: true,
        operator_acceptance: true,
        promotion: true,
        governance_bypass: false,
        pq_authority: None,
        signature_base64: String::new(),
        grant_sha256: Sha256Digest::for_bytes(b"pending"),
    };
    Ok(grant)
}

#[expect(
    clippy::too_many_arguments,
    reason = "each observed recovery binding stays explicit"
)]
pub(super) fn recovery(
    signer_id: &str,
    signer_epoch: u64,
    agent_id: &AgentId,
    grant_sha256: Sha256Digest,
    intent_sha256: Sha256Digest,
    release_transaction_sha256: Sha256Digest,
    observed_release: impl Into<String>,
    observed_manifest_sha256: Sha256Digest,
    observed_agentd_sha256: Sha256Digest,
    observed_matrixd_sha256: Option<Sha256Digest>,
    outcome: ProductionRecoveryOutcome,
    expected_lifecycle_generation: u64,
    authority_epoch: u64,
    issued_at_unix_seconds: u64,
    expires_at_unix_seconds: u64,
) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
    let observed_release = observed_release.into();
    validate_release(&observed_release)?;
    if expected_lifecycle_generation == 0 || authority_epoch == 0 {
        return Err(ProductionAuthorityError::RecoveryBinding);
    }
    validate_window(issued_at_unix_seconds, expires_at_unix_seconds)?;
    let decision = ProductionRecoveryDecision {
        schema_version: PRODUCTION_RECOVERY_SCHEMA_VERSION,
        namespace: PRODUCTION_RECOVERY_NAMESPACE.to_string(),
        agent_id: agent_id.to_string(),
        grant_sha256,
        intent_sha256,
        release_transaction_sha256,
        observed_release,
        observed_manifest_sha256,
        observed_agentd_sha256,
        observed_matrixd_sha256,
        outcome,
        unknown_observation: None,
        completion_observation: None,
        retained_publication_observation: None,
        expected_lifecycle_generation,
        authority_epoch,
        signer_id: signer_id.to_string(),
        signer_epoch,
        issued_at_unix_seconds,
        expires_at_unix_seconds,
        pq_authority: None,
        signature_base64: String::new(),
        decision_sha256: Sha256Digest::for_bytes(b"pending"),
    };
    Ok(decision)
}

#[expect(
    clippy::too_many_arguments,
    reason = "each Unknown owner fence stays explicit"
)]
pub(super) fn abandon_unknown(
    signer_id: &str,
    signer_epoch: u64,
    intent: &SignedSupervisorIntent,
    source: &ReleaseBinding,
    release_state_generation: u64,
    lifecycle_generation: u64,
    authority_epoch: u64,
    issued_at_unix_seconds: u64,
    expires_at_unix_seconds: u64,
) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
    intent
        .validate()
        .map_err(|error| ProductionAuthorityError::Invalid(error.to_string()))?;
    if source.release_id.as_str() != intent.source_release || !intent.requires_recovery() {
        return Err(ProductionAuthorityError::RecoveryBinding);
    }
    let decision = ProductionRecoveryDecision {
        schema_version: 2,
        namespace: "hepta:production:recovery:abandon-unknown:v2".to_string(),
        agent_id: intent.agent_id.clone(),
        grant_sha256: intent.grant_sha256.clone(),
        intent_sha256: intent.intent_sha256.clone(),
        release_transaction_sha256: absent_release_transaction_digest(),
        observed_release: intent.source_release.clone(),
        observed_manifest_sha256: Sha256Digest::parse(source.manifest_sha256.clone())
            .map_err(|_| ProductionAuthorityError::RecoveryBinding)?,
        observed_agentd_sha256: Sha256Digest::parse(source.agentd_program_sha256.clone())
            .map_err(|_| ProductionAuthorityError::RecoveryBinding)?,
        observed_matrixd_sha256: source
            .matrixd_program_sha256
            .as_ref()
            .map(|value| Sha256Digest::parse(value.clone()))
            .transpose()
            .map_err(|_| ProductionAuthorityError::RecoveryBinding)?,
        outcome: ProductionRecoveryOutcome::AbandonUnknown,
        completion_observation: None,
        retained_publication_observation: None,
        unknown_observation: Some(UnknownRecoveryObservation {
            predecessor: None,
            release_state_generation,
            admission_frontier_sha256: Sha256Digest::parse(
                source.admission_frontier_sha256.clone(),
            )
            .map_err(|_| ProductionAuthorityError::RecoveryBinding)?,
        }),
        expected_lifecycle_generation: lifecycle_generation,
        authority_epoch,
        signer_id: signer_id.to_string(),
        signer_epoch,
        issued_at_unix_seconds,
        expires_at_unix_seconds,
        pq_authority: None,
        signature_base64: String::new(),
        decision_sha256: Sha256Digest::for_bytes(b"pending"),
    };
    Ok(decision)
}

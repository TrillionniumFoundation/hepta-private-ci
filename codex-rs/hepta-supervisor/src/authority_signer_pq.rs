//! Explicit PQ offline ceremony over the existing reviewable request shape.
use super::*;
use crate::H7H89ProductionGrantVerifier;
use crate::H7PqProductionGrantSigner;
use crate::H7PqProductionRecoverySigner;
use crate::ProductionAuthorityPolicyV1;
use crate::ProductionAuthorityRoleV1;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;

pub fn read_pq_signing_policy(path: &Path) -> Result<Vec<u8>, ExternalSignerError> {
    if !path.is_absolute() {
        return Err(ExternalSignerError::KeySource(
            "PQ policy path must be absolute".to_string(),
        ));
    }
    let verifier = H7H89ProductionGrantVerifier::read_pq_policy(path)
        .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
    verifier
        .policy_bytes()
        .map(<[u8]>::to_vec)
        .ok_or_else(|| ExternalSignerError::Grant("explicit PQ policy required".to_string()))
}

#[cfg(unix)]
pub fn load_pq_signing_key_from_path(
    path: &Path,
    expected_key_id: [u8; 32],
) -> Result<PqNativeSigningKey, ExternalSignerError> {
    let seed = key_input::from_path(path)?;
    PqNativeSigningKey::from_owned_seed(seed, expected_key_id).map_err(|_| {
        ExternalSignerError::KeySource("secret does not match the explicit PQ role pin".to_string())
    })
}

// Ordinary process hosting is Unix-only. Until a descriptor-bound Windows
// owner/DACL observation is part of this importer, reject new PQ key imports
// there rather than silently inheriting the legacy permission assumption.
#[cfg(not(unix))]
pub fn load_pq_signing_key_from_path(
    _path: &Path,
    _expected_key_id: [u8; 32],
) -> Result<PqNativeSigningKey, ExternalSignerError> {
    Err(ExternalSignerError::KeySource(
        "PQ key file import requires supported Unix owner permissions".to_string(),
    ))
}

pub fn load_pq_signing_key_from_fd(
    fd: i32,
    expected_key_id: [u8; 32],
) -> Result<PqNativeSigningKey, ExternalSignerError> {
    let seed = key_input::from_fd(fd)?;
    PqNativeSigningKey::from_owned_seed(seed, expected_key_id).map_err(|_| {
        ExternalSignerError::KeySource("secret does not match the explicit PQ role pin".to_string())
    })
}

pub fn pq_signing_role(
    request: &SignRequest,
    policy_bytes: &[u8],
) -> Result<ProductionAuthorityRoleV1, ExternalSignerError> {
    H7H89ProductionGrantVerifier::from_pq_policy_bytes(policy_bytes)
        .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
    let policy: ProductionAuthorityPolicyV1 =
        serde_json::from_slice(policy_bytes).map_err(ExternalSignerError::RequestJson)?;
    let (role, id, epoch) = match request {
        SignRequest::H7Envelope {
            signer_id,
            signer_epoch,
            ..
        } => (policy.artifact, signer_id, signer_epoch),
        SignRequest::ProductionGrant {
            signer_id,
            signer_epoch,
            ..
        } => (policy.grant, signer_id, signer_epoch),
        SignRequest::ProductionRecovery {
            signer_id,
            signer_epoch,
            ..
        }
        | SignRequest::ConfirmUnknownPublication {
            signer_id,
            signer_epoch,
            ..
        }
        | SignRequest::ConfirmCompletionPublication {
            signer_id,
            signer_epoch,
            ..
        }
        | SignRequest::RetryRetainedPublication {
            signer_id,
            signer_epoch,
            ..
        }
        | SignRequest::AbandonUnknown {
            signer_id,
            signer_epoch,
            ..
        } => (policy.recovery, signer_id, signer_epoch),
    };
    if &role.signer_id != id || role.signer_epoch != *epoch {
        return Err(ExternalSignerError::Grant(
            "request signer identity differs from its explicit policy role".to_string(),
        ));
    }
    Ok(role)
}

/// This offline operation proves a signature, not current M15 permission.
/// The ordinary daemon and process owners perform the current-use checks.
pub fn sign_request_pq(
    request: &SignRequest,
    key: PqNativeSigningKey,
    policy_bytes: &[u8],
) -> Result<SignResponse, ExternalSignerError> {
    let role = pq_signing_role(request, policy_bytes)?;
    if role.public_key_id != key.public_key_id()
        || role.public_spki_base64 != STANDARD.encode(key.public_spki())
    {
        return Err(ExternalSignerError::KeySource(
            "secret does not match the explicit PQ role pin".to_string(),
        ));
    }
    match request {
        SignRequest::RetryRetainedPublication {
            intent,
            observed,
            observation,
            observed_transaction_sha256,
            lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
            ..
        } => {
            let signer = H7PqProductionRecoverySigner::new(policy_bytes, key)
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let observed = codex_hepta_fleet::ReleaseBinding {
                release_id: codex_hepta_fleet::ReleaseId::parse(observed.release_id.clone())
                    .map_err(|error| ExternalSignerError::Grant(error.to_string()))?,
                manifest_sha256: observed.manifest_sha256.clone(),
                agentd_program_sha256: observed.agentd_program_sha256.clone(),
                matrixd_program_sha256: observed.matrixd_program_sha256.clone(),
                admission_frontier_sha256: observed.admission_frontier_sha256.clone(),
            };
            let decision = signer
                .sign_retry_retained_publication(
                    intent,
                    &observed,
                    observation,
                    observed_transaction_sha256.clone(),
                    *lifecycle_generation,
                    *authority_epoch,
                    *issued_at_unix_seconds,
                    *expires_at_unix_seconds,
                )
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            Ok(SignResponse::ProductionRecovery { decision })
        }
        SignRequest::ConfirmCompletionPublication {
            intent,
            observed,
            observation,
            observed_transaction_sha256,
            lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
            ..
        } => {
            let signer = H7PqProductionRecoverySigner::new(policy_bytes, key)
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let observed = codex_hepta_fleet::ReleaseBinding {
                release_id: codex_hepta_fleet::ReleaseId::parse(observed.release_id.clone())
                    .map_err(|error| ExternalSignerError::Grant(error.to_string()))?,
                manifest_sha256: observed.manifest_sha256.clone(),
                agentd_program_sha256: observed.agentd_program_sha256.clone(),
                matrixd_program_sha256: observed.matrixd_program_sha256.clone(),
                admission_frontier_sha256: observed.admission_frontier_sha256.clone(),
            };
            let decision = signer
                .sign_confirm_completion_publication(
                    intent,
                    &observed,
                    observation,
                    observed_transaction_sha256.clone(),
                    *lifecycle_generation,
                    *authority_epoch,
                    *issued_at_unix_seconds,
                    *expires_at_unix_seconds,
                )
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            Ok(SignResponse::ProductionRecovery { decision })
        }
        SignRequest::ConfirmUnknownPublication {
            intent,
            source,
            predecessor,
            observed_transaction_sha256,
            release_state_generation,
            lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
            ..
        } => {
            let signer = H7PqProductionRecoverySigner::new(policy_bytes, key)
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let source = codex_hepta_fleet::ReleaseBinding {
                release_id: codex_hepta_fleet::ReleaseId::parse(source.release_id.clone())
                    .map_err(|error| ExternalSignerError::Grant(error.to_string()))?,
                manifest_sha256: source.manifest_sha256.clone(),
                agentd_program_sha256: source.agentd_program_sha256.clone(),
                matrixd_program_sha256: source.matrixd_program_sha256.clone(),
                admission_frontier_sha256: source.admission_frontier_sha256.clone(),
            };
            let decision = signer
                .sign_confirm_unknown_publication(
                    intent,
                    &source,
                    predecessor,
                    observed_transaction_sha256.clone(),
                    *release_state_generation,
                    *lifecycle_generation,
                    *authority_epoch,
                    *issued_at_unix_seconds,
                    *expires_at_unix_seconds,
                )
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            Ok(SignResponse::ProductionRecovery { decision })
        }
        SignRequest::H7Envelope {
            signer_id,
            signer_epoch,
            artifact,
            ope,
            transition,
            expected_runtime_generation,
            predecessor_artifact_sha256,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        } => {
            let signer =
                codex_hepta_memory::H7PqArtifactSigner::new(signer_id.clone(), *signer_epoch, key)
                    .map_err(|error| ExternalSignerError::H7(error.to_string()))?;
            let envelope = signer
                .sign(
                    artifact,
                    ope.as_ref(),
                    *transition,
                    *expected_runtime_generation,
                    predecessor_artifact_sha256.clone(),
                    *issued_at_unix_seconds,
                    *expires_at_unix_seconds,
                )
                .map_err(|error| ExternalSignerError::H7(error.to_string()))?;
            Ok(SignResponse::H7Envelope { envelope })
        }
        SignRequest::ProductionGrant {
            h7_envelope,
            agent_id,
            source_release,
            target_release,
            transition,
            expected_control_revision,
            expected_lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
            ..
        } => {
            let signer = H7PqProductionGrantSigner::new(policy_bytes, key)
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let agent = AgentId::parse(agent_id.clone())
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let grant = signer
                .sign(
                    &agent,
                    source_release.clone(),
                    target_release.clone(),
                    *transition,
                    h7_envelope,
                    *expected_control_revision,
                    *expected_lifecycle_generation,
                    *authority_epoch,
                    *issued_at_unix_seconds,
                    *expires_at_unix_seconds,
                )
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            Ok(SignResponse::ProductionGrant { grant })
        }
        SignRequest::ProductionRecovery {
            agent_id,
            grant_sha256,
            intent_sha256,
            release_transaction_sha256,
            observed_release,
            observed_manifest_sha256,
            observed_agentd_sha256,
            observed_matrixd_sha256,
            outcome,
            expected_lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
            ..
        } => {
            let signer = H7PqProductionRecoverySigner::new(policy_bytes, key)
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let agent = AgentId::parse(agent_id.clone())
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let decision = signer
                .sign_recovery(
                    &agent,
                    grant_sha256.clone(),
                    intent_sha256.clone(),
                    release_transaction_sha256.clone(),
                    observed_release.clone(),
                    observed_manifest_sha256.clone(),
                    observed_agentd_sha256.clone(),
                    observed_matrixd_sha256.clone(),
                    *outcome,
                    *expected_lifecycle_generation,
                    *authority_epoch,
                    *issued_at_unix_seconds,
                    *expires_at_unix_seconds,
                )
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            Ok(SignResponse::ProductionRecovery { decision })
        }
        SignRequest::AbandonUnknown {
            intent,
            source,
            predecessor,
            observed_predecessor_transaction_sha256,
            release_state_generation,
            lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
            ..
        } => {
            let signer = H7PqProductionRecoverySigner::new(policy_bytes, key)
                .map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            let source = codex_hepta_fleet::ReleaseBinding {
                release_id: codex_hepta_fleet::ReleaseId::parse(source.release_id.clone())
                    .map_err(|error| ExternalSignerError::Grant(error.to_string()))?,
                manifest_sha256: source.manifest_sha256.clone(),
                agentd_program_sha256: source.agentd_program_sha256.clone(),
                matrixd_program_sha256: source.matrixd_program_sha256.clone(),
                admission_frontier_sha256: source.admission_frontier_sha256.clone(),
            };
            let decision = match (predecessor, observed_predecessor_transaction_sha256) {
                (None, None) => signer.sign_abandon_unknown(intent, &source, *release_state_generation,
                    *lifecycle_generation, *authority_epoch, *issued_at_unix_seconds, *expires_at_unix_seconds),
                (Some(predecessor), Some(transaction)) => signer.sign_abandon_unknown_after_predecessor(intent, &source,
                    predecessor, transaction.clone(), *release_state_generation, *lifecycle_generation, *authority_epoch,
                    *issued_at_unix_seconds, *expires_at_unix_seconds),
                _ => return Err(ExternalSignerError::Grant("PQ predecessor and its actual transaction observation must be supplied together".to_string())),
            }.map_err(|error| ExternalSignerError::Grant(error.to_string()))?;
            Ok(SignResponse::ProductionRecovery { decision })
        }
    }
}

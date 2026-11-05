//! Shared bounded artifact/OPE fields before a detached signature is applied.

use super::H7_SIGNED_ARTIFACT_NAMESPACE;
use super::H7_SIGNED_ARTIFACT_SCHEMA_VERSION;
use super::H7_SIGNED_ARTIFACT_SIGNATURE_ALGORITHM;
use super::H7_SIGNED_ARTIFACT_SIGNATURE_DOMAIN;
use super::H7SignedArtifactEnvelope;
use super::H7SignedArtifactError;
use super::H7SignedArtifactTransition;
use super::validate_window;
use crate::h7_feedback::H7OfflineEvaluation;
use crate::h7_runtime::H7Artifact;
use codex_hepta_contracts::Sha256Digest;

#[allow(clippy::too_many_arguments)]
pub(super) fn artifact_envelope(
    signer_id: &str,
    signer_epoch: u64,
    artifact: &H7Artifact,
    ope: Option<&H7OfflineEvaluation>,
    transition: H7SignedArtifactTransition,
    expected_runtime_generation: u64,
    predecessor_artifact_sha256: Option<Sha256Digest>,
    issued_at_unix_seconds: u64,
    expires_at_unix_seconds: u64,
) -> Result<H7SignedArtifactEnvelope, H7SignedArtifactError> {
    artifact
        .validate()
        .map_err(|error| H7SignedArtifactError::Runtime(error.to_string()))?;
    if let Some(ope) = ope {
        ope.validate()
            .map_err(|error| H7SignedArtifactError::Feedback(error.to_string()))?;
    }
    validate_window(issued_at_unix_seconds, expires_at_unix_seconds)?;
    if expected_runtime_generation > u64::MAX - 1 {
        return Err(H7SignedArtifactError::Invalid(
            "runtime generation is outside the bounded range".to_string(),
        ));
    }
    if matches!(transition, H7SignedArtifactTransition::Rollback)
        && predecessor_artifact_sha256.is_none()
    {
        return Err(H7SignedArtifactError::PredecessorRequired);
    }
    Ok(H7SignedArtifactEnvelope {
        schema_version: H7_SIGNED_ARTIFACT_SCHEMA_VERSION,
        namespace: H7_SIGNED_ARTIFACT_NAMESPACE.to_string(),
        signature_domain: H7_SIGNED_ARTIFACT_SIGNATURE_DOMAIN.to_string(),
        signature_algorithm: H7_SIGNED_ARTIFACT_SIGNATURE_ALGORITHM.to_string(),
        artifact_id: artifact.artifact_id.clone(),
        artifact_sha256: artifact.body_sha256.clone(),
        trajectory_sha256: artifact.trajectory_sha256.clone(),
        evaluation_sha256: artifact.evaluation_sha256.clone(),
        ope_evaluation_sha256: ope.map(|evaluation| evaluation.evaluation_digest.clone()),
        signer_id: signer_id.to_string(),
        signer_epoch,
        issued_at_unix_seconds,
        expires_at_unix_seconds,
        transition,
        expected_runtime_generation,
        predecessor_artifact_sha256,
        qualification_only: true,
        production_authority: false,
        external_effects: false,
        promotion_eligible: false,
        signature_base64: String::new(),
        envelope_sha256: Sha256Digest::for_bytes(b"pending"),
    })
}

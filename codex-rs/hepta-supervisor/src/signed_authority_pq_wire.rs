//! Versioned pure ML-DSA messages; legacy Ed25519 bytes stay in their old branch.
use super::*;
pub(super) const GRANT_NAMESPACE: &str = "hepta:production:authority:ml-dsa65:v2";
pub(super) const RECOVERY_NAMESPACE: &str = "hepta:production:recovery:ml-dsa65:v3";

pub(super) fn grant_shape(grant: &H7H89ProductionGrant) -> bool {
    match &grant.pq_authority {
        None => {
            grant.schema_version == SIGNED_AUTHORITY_SCHEMA_VERSION
                && grant.namespace == SIGNED_AUTHORITY_NAMESPACE
        }
        Some(binding) => {
            grant.schema_version == 2
                && grant.namespace == GRANT_NAMESPACE
                && valid_binding(binding)
        }
    }
}

pub(super) fn recovery_shape(decision: &ProductionRecoveryDecision, unknown: bool) -> bool {
    let Some(binding) = &decision.pq_authority else {
        return unknown_recovery::valid_namespace(decision, unknown);
    };
    if decision.schema_version != 3
        || decision.namespace != RECOVERY_NAMESPACE
        || !valid_binding(binding)
    {
        return false;
    }
    let Ok(agent) = AgentId::parse(decision.agent_id.clone()) else {
        return false;
    };
    match decision.outcome {
        ProductionRecoveryOutcome::RetryRetainedPublication => {
            decision.unknown_observation.is_none()
                && decision.completion_observation.is_none()
                && decision
                    .retained_publication_observation
                    .as_ref()
                    .is_some_and(|observed| observed.valid_for(&agent))
        }
        ProductionRecoveryOutcome::ConfirmCommittedPublication
        | ProductionRecoveryOutcome::ConfirmRolledBackPublication => {
            decision.unknown_observation.is_none()
                && decision.retained_publication_observation.is_none()
                && decision
                    .completion_observation
                    .as_ref()
                    .is_some_and(|observed| observed.valid_for(&agent))
        }
        ProductionRecoveryOutcome::AbandonUnknown
        | ProductionRecoveryOutcome::ConfirmUnknownPublication => {
            decision.completion_observation.is_none()
                && decision.retained_publication_observation.is_none()
                && decision
                    .unknown_observation
                    .as_ref()
                    .is_some_and(|observed| {
                        observed.release_state_generation > 0
                            && (decision.outcome
                                != ProductionRecoveryOutcome::ConfirmUnknownPublication
                                || observed.predecessor.is_some())
                            && match &observed.predecessor {
                                Some(predecessor) => predecessor.valid_for(&agent),
                                None => {
                                    decision.release_transaction_sha256
                                        == absent_release_transaction_digest()
                                }
                            }
                            && Sha256Digest::parse(observed.admission_frontier_sha256.as_str())
                                .is_ok()
                    })
        }
        ProductionRecoveryOutcome::Committed | ProductionRecoveryOutcome::RolledBack => {
            decision.unknown_observation.is_none()
                && decision.completion_observation.is_none()
                && decision.retained_publication_observation.is_none()
        }
    }
}

fn valid_binding(binding: &PqAuthorityBinding) -> bool {
    Sha256Digest::parse(binding.policy_sha256.as_str()).is_ok()
}

fn frame_message(message: &mut Vec<u8>, field: &[u8]) {
    message.extend_from_slice(&(field.len() as u64).to_be_bytes());
    message.extend_from_slice(field);
}

fn binding_message(message: &mut Vec<u8>, binding: Option<&PqAuthorityBinding>) {
    if let Some(binding) = binding {
        frame_message(message, binding.policy_sha256.as_str().as_bytes());
        frame_message(message, &binding.signer_public_key_id);
    }
}

pub(super) fn grant_message(grant: &H7H89ProductionGrant) -> Vec<u8> {
    let mut message = Vec::new();
    for field in [
        b"hepta-supervisor:production-authority:ml-dsa65:v2".as_slice(),
        grant.namespace.as_bytes(),
        grant.agent_id.as_bytes(),
        grant.source_release.as_bytes(),
        grant.target_release.as_bytes(),
        grant.transition.as_str().as_bytes(),
        grant.h7_envelope_sha256.as_str().as_bytes(),
        grant.artifact_sha256.as_str().as_bytes(),
        grant.signer_id.as_bytes(),
    ] {
        frame_message(&mut message, field);
    }
    frame_message(&mut message, &grant.schema_version.to_be_bytes());
    for field in [
        grant.expected_control_revision,
        grant.expected_lifecycle_generation,
        grant.authority_epoch,
        grant.signer_epoch,
        grant.issued_at_unix_seconds,
        grant.expires_at_unix_seconds,
    ] {
        frame_message(&mut message, &field.to_be_bytes());
    }
    for field in [
        grant.production_authority,
        grant.external_effects,
        grant.operator_acceptance,
        grant.promotion,
        grant.governance_bypass,
    ] {
        frame_message(&mut message, &[u8::from(field)]);
    }
    binding_message(&mut message, grant.pq_authority.as_ref());
    message
}

pub(super) fn recovery_message(decision: &ProductionRecoveryDecision) -> Vec<u8> {
    let mut message = Vec::new();
    for field in [
        b"hepta-supervisor:production-recovery:ml-dsa65:v3".as_slice(),
        decision.namespace.as_bytes(),
        decision.agent_id.as_bytes(),
        decision.grant_sha256.as_str().as_bytes(),
        decision.intent_sha256.as_str().as_bytes(),
        decision.release_transaction_sha256.as_str().as_bytes(),
        decision.observed_release.as_bytes(),
        decision.observed_manifest_sha256.as_str().as_bytes(),
        decision.observed_agentd_sha256.as_str().as_bytes(),
        decision.outcome.as_str().as_bytes(),
        decision.signer_id.as_bytes(),
    ] {
        frame_message(&mut message, field);
    }
    frame_message(&mut message, &decision.schema_version.to_be_bytes());
    match &decision.observed_matrixd_sha256 {
        Some(digest) => {
            frame_message(&mut message, &[1]);
            frame_message(&mut message, digest.as_str().as_bytes());
        }
        None => frame_message(&mut message, &[0]),
    }
    match &decision.unknown_observation {
        Some(observed) => {
            frame_message(&mut message, &[1]);
            frame_message(
                &mut message,
                &observed.release_state_generation.to_be_bytes(),
            );
            frame_message(
                &mut message,
                observed.admission_frontier_sha256.as_str().as_bytes(),
            );
            match &observed.predecessor {
                Some(predecessor) => {
                    frame_message(&mut message, &[1]);
                    frame_message(&mut message, &predecessor.schema_version.to_be_bytes());
                    frame_message(&mut message, &predecessor.anchor_generation.to_be_bytes());
                    frame_message(&mut message, predecessor.anchor_sha256.as_str().as_bytes());
                }
                None => frame_message(&mut message, &[0]),
            }
        }
        None => frame_message(&mut message, &[0]),
    }
    match &decision.completion_observation {
        Some(observed) => {
            frame_message(&mut message, &[1]);
            frame_message(
                &mut message,
                b"hepta-supervisor:completion-publication-observation:v1",
            );
            frame_message(&mut message, &observed.schema_version.to_be_bytes());
            frame_message(
                &mut message,
                &observed.predecessor.schema_version.to_be_bytes(),
            );
            frame_message(
                &mut message,
                &observed.predecessor.anchor_generation.to_be_bytes(),
            );
            for digest in [
                &observed.predecessor.anchor_sha256,
                &observed.pending_publication_sha256,
                &observed.release_state_sha256,
                &observed.admission_frontier_sha256,
            ] {
                frame_message(&mut message, digest.as_str().as_bytes());
            }
            frame_message(
                &mut message,
                &observed.release_state_generation.to_be_bytes(),
            );
        }
        None => frame_message(&mut message, &[0]),
    }
    match &decision.retained_publication_observation {
        Some(observed) => {
            frame_message(&mut message, &[1]);
            frame_message(
                &mut message,
                b"hepta-supervisor:retained-publication-observation:v1",
            );
            frame_message(&mut message, &observed.schema_version.to_be_bytes());
            frame_message(
                &mut message,
                &observed.predecessor.schema_version.to_be_bytes(),
            );
            frame_message(
                &mut message,
                &observed.predecessor.anchor_generation.to_be_bytes(),
            );
            for digest in [
                &observed.predecessor.anchor_sha256,
                &observed.original_pending_sha256,
                &observed.replacement_pending_sha256,
                &observed.retained_state_sha256,
                &observed.replacement_anchor_sha256,
                &observed.release_state_sha256,
                &observed.admission_frontier_sha256,
            ] {
                frame_message(&mut message, digest.as_str().as_bytes());
            }
            frame_message(
                &mut message,
                &observed.release_state_generation.to_be_bytes(),
            );
        }
        None => frame_message(&mut message, &[0]),
    }
    for field in [
        decision.expected_lifecycle_generation,
        decision.authority_epoch,
        decision.signer_epoch,
        decision.issued_at_unix_seconds,
        decision.expires_at_unix_seconds,
    ] {
        frame_message(&mut message, &field.to_be_bytes());
    }
    binding_message(&mut message, decision.pq_authority.as_ref());
    message
}

pub(super) fn signature_encoding(encoded: &str, pq: bool) -> bool {
    let size = if pq {
        codex_hepta_contracts::pq_auth::ML_DSA_65_SIGNATURE_BYTES
    } else {
        64
    };
    if encoded.len() != size.div_ceil(3) * 4 {
        return false;
    }
    STANDARD
        .decode(encoded)
        .is_ok_and(|bytes| bytes.len() == size && STANDARD.encode(bytes) == encoded)
}

//! Pure validation and transition rules for the original protected head.

use super::*;

pub(super) fn request_sequence(value: &str) -> Option<(u64, u64)> {
    if value.len() != 32
        || !value
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
    {
        return None;
    }
    let epoch = u64::from_str_radix(&value[..16], 16).ok()?;
    let sequence = u64::from_str_radix(&value[16..], 16).ok()?;
    (epoch != 0 && sequence != 0).then_some((epoch, sequence))
}

pub(super) fn token_for(
    head: &CognitiveCheckpointHead,
) -> Result<CognitiveCheckpointToken, AuthorityTrustError> {
    let mut bytes = b"hepta:root:cognitive-checkpoint-head:v1\0".to_vec();
    bytes.extend_from_slice(
        &serde_json::to_vec(head).map_err(|_| AuthorityTrustError::Unavailable)?,
    );
    Ok(CognitiveCheckpointToken {
        publisher_epoch: head.publisher_epoch,
        counter: head.counter,
        head_sha256: Sha256Digest::for_bytes(&bytes),
    })
}

pub(super) fn response(
    request: &CognitiveCheckpointRequest,
    status: CognitiveCheckpointStatus,
    reason: Option<CognitiveCheckpointReason>,
) -> CognitiveCheckpointResponse {
    CognitiveCheckpointResponse {
        schema_version: 1,
        request_id: request.request_id.clone(),
        status,
        reason,
        token: None,
        head: None,
    }
}

pub(super) fn validate_registration(
    value: &HostCognitiveCheckpointRegistration,
) -> Result<(), AuthorityTrustError> {
    let writer = &value.writer_binding;
    let peer = &value.peer_lifetime;
    if value.publisher_epoch == 0
        || writer.lease_id.is_empty()
        || writer.lease_id.len() > 256
        || writer.generation == 0
        || writer.authority_epoch == 0
        || writer.owner_epoch == 0
        || writer.expires_at_unix_seconds == 0
        || writer.expires_at_unix_seconds.checked_mul(1000).is_none()
        || peer.uid == 0
        || peer.pid == 0
        || peer.pid > i32::MAX as u32
        || peer.boot_id.is_empty()
        || peer.process_start_ticks == 0
    {
        return Err(AuthorityTrustError::Invalid);
    }
    Ok(())
}

pub(super) fn validate_cut(
    registration: &HostCognitiveCheckpointRegistration,
    cut: &CognitiveRecoveryAnchor,
) -> Result<(), AuthorityTrustError> {
    if cut.profile != "hepta:cognitive:exact-current-cut:v1"
        || cut.owner_agent_id != registration.owner_agent_id
    {
        return Err(AuthorityTrustError::Invalid);
    }
    Ok(())
}

pub(super) fn validate_proposal(
    registration: &HostCognitiveCheckpointRegistration,
    proposal: &CognitiveCheckpointProposal,
) -> Result<(), AuthorityTrustError> {
    validate_cut(registration, &proposal.cut)?;
    let fence = &proposal.writer_fence;
    if fence.owner_agent_id != registration.owner_agent_id {
        return Err(AuthorityTrustError::Invalid);
    }
    let observed = CognitiveCheckpointWriterBinding {
        lease_id: fence.lease_id.clone(),
        generation: fence.generation,
        authority_epoch: fence.authority_epoch,
        owner_epoch: fence.owner_epoch,
        authority_grant_digest: fence.authority_grant_digest.clone(),
        fencing_token_digest: fence.fencing_token_digest.clone(),
        expires_at_unix_seconds: fence.expires_at_unix_seconds,
    };
    if observed != registration.writer_binding {
        return Err(AuthorityTrustError::Invalid);
    }
    Ok(())
}

pub(super) fn validate_head(
    registration: &HostCognitiveCheckpointRegistration,
    head: &CognitiveCheckpointHead,
) -> Result<(), AuthorityTrustError> {
    if head.schema_version != 1
        || head.owner_agent_id != registration.owner_agent_id
        || head.publisher_epoch != registration.publisher_epoch
        || head.writer_binding != registration.writer_binding
        || head.peer_lifetime != registration.peer_lifetime
        || head.counter > head.last_mutation_sequence
    {
        return Err(AuthorityTrustError::Invalid);
    }
    validate_cut(registration, &head.last_current)?;
    match (&head.last_request, head.counter) {
        (None, 0)
            if head.last_mutation_sequence == 0
                && head.phase == CognitiveCheckpointPhase::Current => {}
        (Some(last), counter)
            if counter > 0
                && request_sequence(&last.request_id)
                    == Some((head.publisher_epoch, head.last_mutation_sequence))
                && last.predecessor_token.publisher_epoch == head.publisher_epoch
                && last.predecessor_token.counter.checked_add(1) == Some(counter) => {}
        _ => return Err(AuthorityTrustError::Invalid),
    }
    match (&head.proposal, head.phase) {
        (
            None,
            CognitiveCheckpointPhase::Current
            | CognitiveCheckpointPhase::Dirty
            | CognitiveCheckpointPhase::Fenced,
        ) => {}
        (
            Some(proposal),
            CognitiveCheckpointPhase::Publishing | CognitiveCheckpointPhase::Fenced,
        ) => {
            validate_proposal(
                registration,
                &CognitiveCheckpointProposal {
                    cut: proposal.cut.clone(),
                    writer_fence: proposal.writer_fence.clone(),
                },
            )?;
        }
        _ => return Err(AuthorityTrustError::Invalid),
    }
    Ok(())
}

pub(super) fn advance(
    registration: &HostCognitiveCheckpointRegistration,
    current: &CognitiveCheckpointHead,
    request: &CognitiveCheckpointRequest,
    digest: Sha256Digest,
    predecessor: CognitiveCheckpointToken,
    sequence: u64,
) -> Result<CognitiveCheckpointHead, CognitiveCheckpointReason> {
    let mut next = current.clone();
    match (request.command, current.phase, request.proposal.as_ref()) {
        (CognitiveCheckpointCommand::BeginWrites, CognitiveCheckpointPhase::Current, None) => {
            next.phase = CognitiveCheckpointPhase::Dirty;
            next.proposal = None;
        }
        (
            CognitiveCheckpointCommand::PreparePublication,
            CognitiveCheckpointPhase::Dirty,
            Some(proposal),
        ) => {
            validate_proposal(registration, proposal)
                .map_err(|_| CognitiveCheckpointReason::AuthorityDenied)?;
            next.phase = CognitiveCheckpointPhase::Publishing;
            next.proposal = Some(CognitiveCheckpointRetainedProposal {
                request_id: request.request_id.clone(),
                cut: proposal.cut.clone(),
                writer_fence: proposal.writer_fence.clone(),
            });
        }
        (
            CognitiveCheckpointCommand::CommitPublication,
            CognitiveCheckpointPhase::Publishing,
            None,
        ) => {
            next.last_current = current
                .proposal
                .as_ref()
                .ok_or(CognitiveCheckpointReason::Invalid)?
                .cut
                .clone();
            next.phase = CognitiveCheckpointPhase::Current;
            next.proposal = None;
        }
        (CognitiveCheckpointCommand::FencePublisher, phase, None)
            if phase != CognitiveCheckpointPhase::Fenced =>
        {
            next.phase = CognitiveCheckpointPhase::Fenced;
        }
        _ => return Err(CognitiveCheckpointReason::Invalid),
    }
    next.counter = current
        .counter
        .checked_add(1)
        .ok_or(CognitiveCheckpointReason::StalePublisher)?;
    next.last_mutation_sequence = sequence;
    next.last_request = Some(CognitiveCheckpointRetainedRequest {
        request_id: request.request_id.clone(),
        request_sha256: digest,
        command: request.command,
        predecessor_token: predecessor,
    });
    Ok(next)
}

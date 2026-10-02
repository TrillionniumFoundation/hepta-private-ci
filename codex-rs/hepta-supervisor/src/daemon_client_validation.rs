//! Response association is a client integrity check, never mutation authority.
//! A queued acceptance does not prove successful release completion.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::ReleaseId;

use super::SupervisordControlFence;
use super::SupervisordMethod;
use super::SupervisordPayload;
use super::SupervisordRequest;
use super::SupervisordResponse;
use crate::H7H89ProductionGrant;
use crate::H7H89ProductionTransition;
use crate::ProductionMutationReceipt;
use crate::ProductionMutationState;
use crate::ProductionMutationStatus;
use crate::ProductionRecoveryOutcome;
use crate::SupervisorError;
use crate::daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use crate::daemon_protocol::SupervisordMutation;
use crate::robrix_protocol::validate_agent_status;
use crate::robrix_protocol::validate_health;
use crate::robrix_protocol::validate_roster;
use crate::robrix_protocol::validate_safe_code;
use crate::robrix_protocol::validate_safe_message;

pub(super) fn decode_response(bytes: &[u8]) -> Result<SupervisordResponse, SupervisorError> {
    // Serde errors may quote a hostile variant or field name from the frame.
    serde_json::from_slice(bytes).map_err(|_| invalid("returned invalid response JSON"))
}

pub(super) fn validate_response(
    request: &SupervisordRequest,
    response: &SupervisordResponse,
) -> Result<(), SupervisorError> {
    request
        .validate()
        .map_err(|_| invalid("invalid outstanding request"))?;
    if response.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION
        || response.request_id != request.request_id
    {
        return Err(invalid("response identity does not match request"));
    }
    if let SupervisordPayload::Error {
        code,
        message,
        actual,
    } = &response.payload
    {
        validate_safe_code(code).map_err(|_| invalid("returned an unsafe error code"))?;
        validate_safe_message(message).map_err(|_| invalid("returned an unsafe error message"))?;
        if let Some(actual) = actual {
            validate_agent_status(actual)
                .map_err(|_| invalid("returned an invalid Agent status"))?;
            if selected_agent(&request.method).is_some_and(|agent| agent != &actual.agent_id) {
                return Err(invalid("error Agent does not match request"));
            }
        }
        return Ok(());
    }
    match (&request.method, &response.payload) {
        (SupervisordMethod::Health, SupervisordPayload::Health(health)) => {
            validate_health(health).map_err(|_| invalid("returned invalid health"))
        }
        (SupervisordMethod::Roster { limit }, SupervisordPayload::Roster { agents }) => {
            validate_roster(agents).map_err(|_| invalid("returned an invalid roster"))?;
            if agents.len() > usize::from(*limit) {
                return Err(invalid("roster exceeds requested limit"));
            }
            Ok(())
        }
        (SupervisordMethod::Snapshot { agent_id }, SupervisordPayload::Agent(status)) => {
            validate_agent_status(status)
                .map_err(|_| invalid("returned an invalid Agent status"))?;
            if &status.agent_id != agent_id {
                return Err(invalid("response Agent does not match request"));
            }
            Ok(())
        }
        (
            SupervisordMethod::ReleaseSelection { agent_id },
            SupervisordPayload::ReleaseSelection { selection },
        ) => {
            if let Some(selection) = selection {
                selection
                    .validate()
                    .map_err(|_| invalid("returned an invalid release selection"))?;
                if selection.agent_id != agent_id.as_str()
                    || ReleaseId::parse(selection.source_release.clone()).is_err()
                    || ReleaseId::parse(selection.target_release.clone()).is_err()
                    || selection
                        .rollback_predecessor
                        .as_ref()
                        .is_some_and(|release| ReleaseId::parse(release.clone()).is_err())
                    || selection
                        .grant_sha256
                        .as_ref()
                        .is_some_and(|digest| Sha256Digest::parse(digest.as_str()).is_err())
                    || selection
                        .source_binding
                        .as_ref()
                        .is_some_and(|binding| binding.release_id != selection.source_release)
                    || selection
                        .target_binding
                        .as_ref()
                        .is_some_and(|binding| binding.release_id != selection.target_release)
                {
                    return Err(invalid("release selection does not match request"));
                }
            }
            Ok(())
        }
        (
            SupervisordMethod::ProductionMutationStatus { agent_id },
            SupervisordPayload::ProductionMutationStatus { state },
        ) => {
            if let Some(state) = state {
                validate_state(state, agent_id)?;
            }
            Ok(())
        }
        (
            SupervisordMethod::ResolveProductionRecovery { fence, decision },
            SupervisordPayload::ProductionMutationStatus { state: Some(state) },
        ) => {
            validate_state(state, &fence.agent_id)?;
            let (status, release_matches) = match (state.receipt.transition, decision.outcome) {
                (H7H89ProductionTransition::Upgrade, ProductionRecoveryOutcome::Committed) => (
                    ProductionMutationStatus::Committed,
                    decision.observed_release == state.receipt.target_release,
                ),
                (H7H89ProductionTransition::Upgrade, ProductionRecoveryOutcome::RolledBack) => (
                    ProductionMutationStatus::RolledBack,
                    decision.observed_release == state.receipt.source_release,
                ),
                (H7H89ProductionTransition::Rollback, ProductionRecoveryOutcome::RolledBack) => (
                    ProductionMutationStatus::RolledBack,
                    // Explicit rollback success selects its target; failure
                    // restores its source. The server checks the exact durable
                    // current/previous/generation frontier for either case.
                    decision.observed_release == state.receipt.source_release
                        || decision.observed_release == state.receipt.target_release,
                ),
                (H7H89ProductionTransition::Rollback, ProductionRecoveryOutcome::Committed) => {
                    return Err(invalid("invalid explicit rollback recovery outcome"));
                }
            };
            if state.receipt.grant_sha256 != decision.grant_sha256
                || decision.agent_id != fence.agent_id.as_str()
                || decision.expected_lifecycle_generation != fence.lifecycle_generation
                // with_status publishes a different terminal witness. The
                // response omits the original epoch/generation context, so
                // this client cannot authenticate a pre/post hash relation.
                || state.intent_sha256 == decision.intent_sha256
                || state.receipt.status != status
                || !release_matches
                || state.release_transaction_sha256.is_none()
            {
                return Err(invalid("recovery response does not match decision"));
            }
            Ok(())
        }
        (
            method,
            SupervisordPayload::MutationAccepted {
                operation,
                accepted_state_digest,
                agent,
                production_receipt,
            },
        ) => {
            let Some((fence, expected, grant)) = mutation_context(method) else {
                return Err(invalid("payload type does not match request"));
            };
            validate_agent_status(agent)
                .map_err(|_| invalid("returned an invalid Agent status"))?;
            if *operation != expected
                || accepted_state_digest != &fence.state_digest
                || agent.agent_id != fence.agent_id
                || agent.control_fence.supervisor_epoch != fence.supervisor_epoch
            {
                return Err(invalid("mutation acceptance does not match request"));
            }
            match (grant, production_receipt) {
                (None, None) => Ok(()),
                (Some(grant), Some(receipt)) => {
                    validate_receipt(receipt, &fence.agent_id)?;
                    let transition = match expected {
                        SupervisordMutation::Upgrade => H7H89ProductionTransition::Upgrade,
                        SupervisordMutation::Rollback => H7H89ProductionTransition::Rollback,
                        _ => return Err(invalid("invalid signed mutation context")),
                    };
                    if receipt.grant_sha256 != *grant.digest()
                        || receipt.transition != transition
                        || receipt.transition != grant.transition
                        || receipt.agent_id != grant.agent_id
                        || grant.expected_lifecycle_generation != fence.lifecycle_generation
                        || receipt.source_release != grant.source_release
                        || receipt.target_release != grant.target_release
                        || Some(receipt.control_revision)
                            != grant.expected_control_revision.checked_add(1)
                        || receipt.status != ProductionMutationStatus::Queued
                    {
                        return Err(invalid("signed receipt does not match grant"));
                    }
                    Ok(())
                }
                _ => Err(invalid("mutation receipt presence does not match request")),
            }
        }
        _ => Err(invalid("payload type does not match request")),
    }
}

fn validate_receipt(
    receipt: &ProductionMutationReceipt,
    agent_id: &AgentId,
) -> Result<(), SupervisorError> {
    if receipt.agent_id != agent_id.as_str()
        || Sha256Digest::parse(receipt.grant_sha256.as_str()).is_err()
        || receipt.source_release == receipt.target_release
        || ReleaseId::parse(receipt.source_release.clone()).is_err()
        || ReleaseId::parse(receipt.target_release.clone()).is_err()
        || receipt.control_revision == 0
        || !receipt.production_authority
        || !receipt.external_effects
        || !receipt.operator_acceptance
        || !receipt.promotion
    {
        return Err(invalid("returned an invalid production receipt"));
    }
    Ok(())
}

fn validate_state(
    state: &ProductionMutationState,
    agent_id: &AgentId,
) -> Result<(), SupervisorError> {
    validate_receipt(&state.receipt, agent_id)?;
    if Sha256Digest::parse(state.intent_sha256.as_str()).is_err()
        || state
            .release_transaction_sha256
            .as_ref()
            .is_some_and(|digest| Sha256Digest::parse(digest.as_str()).is_err())
    {
        return Err(invalid("returned invalid production state digests"));
    }
    Ok(())
}

fn selected_agent(method: &SupervisordMethod) -> Option<&AgentId> {
    match method {
        SupervisordMethod::Health | SupervisordMethod::Roster { .. } => None,
        SupervisordMethod::Snapshot { agent_id }
        | SupervisordMethod::ReleaseSelection { agent_id }
        | SupervisordMethod::ProductionMutationStatus { agent_id } => Some(agent_id),
        SupervisordMethod::Start { fence, .. }
        | SupervisordMethod::Drain { fence }
        | SupervisordMethod::Stop { fence }
        | SupervisordMethod::Kill { fence }
        | SupervisordMethod::Restart { fence }
        | SupervisordMethod::Upgrade { fence, .. }
        | SupervisordMethod::Rollback { fence }
        | SupervisordMethod::SignedUpgrade { fence, .. }
        | SupervisordMethod::SignedRollback { fence, .. }
        | SupervisordMethod::ResolveProductionRecovery { fence, .. } => Some(&fence.agent_id),
    }
}

fn mutation_context(
    method: &SupervisordMethod,
) -> Option<(
    &SupervisordControlFence,
    SupervisordMutation,
    Option<&H7H89ProductionGrant>,
)> {
    match method {
        SupervisordMethod::Start { fence, .. } => Some((fence, SupervisordMutation::Start, None)),
        SupervisordMethod::Drain { fence } => Some((fence, SupervisordMutation::Drain, None)),
        SupervisordMethod::Stop { fence } => Some((fence, SupervisordMutation::Stop, None)),
        SupervisordMethod::Kill { fence } => Some((fence, SupervisordMutation::Kill, None)),
        SupervisordMethod::Restart { fence } => Some((fence, SupervisordMutation::Restart, None)),
        SupervisordMethod::Upgrade { fence, .. } => {
            Some((fence, SupervisordMutation::Upgrade, None))
        }
        SupervisordMethod::Rollback { fence } => Some((fence, SupervisordMutation::Rollback, None)),
        SupervisordMethod::SignedUpgrade { fence, grant, .. } => {
            Some((fence, SupervisordMutation::Upgrade, Some(grant)))
        }
        SupervisordMethod::SignedRollback { fence, grant, .. } => {
            Some((fence, SupervisordMutation::Rollback, Some(grant)))
        }
        SupervisordMethod::Health
        | SupervisordMethod::Roster { .. }
        | SupervisordMethod::Snapshot { .. }
        | SupervisordMethod::ReleaseSelection { .. }
        | SupervisordMethod::ProductionMutationStatus { .. }
        | SupervisordMethod::ResolveProductionRecovery { .. } => None,
    }
}

fn invalid(reason: &'static str) -> SupervisorError {
    SupervisorError::Invalid(format!("supervisord {reason}"))
}

#[cfg(test)]
#[path = "daemon_client_validation_tests.rs"]
mod tests;

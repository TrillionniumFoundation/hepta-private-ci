//! Ordinary lifecycle mutation admission and durable outcome reconciliation.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::AgentId;

use crate::AgentRelease;
use crate::ProcessDriver;
use crate::SupervisorError;
use crate::daemon_protocol::ControlStateDigest;
use crate::daemon_protocol::SupervisordControlFence;
use crate::daemon_protocol::SupervisordMutation;
use crate::daemon_protocol::SupervisordPayload;

use super::DaemonState;
use super::agent_status_locked;
use super::control_fence_matches;
use super::error_payload;
use super::safe_rejection;

use crate::mutation_journal_slots as journal;

pub(super) async fn handle_mutation<D: ProcessDriver>(
    state: Arc<DaemonState<D>>,
    request_id: u64,
    operation: SupervisordMutation,
    fence: SupervisordControlFence,
    target: Option<AgentRelease>,
) -> SupervisordPayload {
    let agent_id = fence.agent_id.clone();
    let accepted_state_digest = fence.state_digest.clone();
    let mut supervisor = state.supervisor.lock().await;
    let actual = match agent_status_locked(&state, &supervisor, &agent_id) {
        Ok(actual) => actual,
        Err(error) => {
            return safe_rejection(error, /*actual*/ None, /*mutation_started*/ false);
        }
    };
    if !control_fence_matches(&fence, &actual.control_fence) {
        return error_payload(
            "stale_control_fence",
            "selected Agent changed; refresh before retry",
            Some(actual),
        );
    }
    match supervisor.production_recovery_required(&agent_id) {
        Ok(true) if operation != SupervisordMutation::Kill => {
            return error_payload(
                "signed_intent_recovery_required",
                "this Agent has a quarantined production mutation; only status, recovery, or emergency kill is allowed",
                Some(actual),
            );
        }
        Ok(_) => {}
        Err(error) => {
            return safe_rejection(error, Some(actual), /*mutation_started*/ false);
        }
    }
    if state.recovery_observation_blocked_for(&agent_id) && operation != SupervisordMutation::Kill {
        return error_payload(
            "recovery_observation_required",
            "this Agent has an owner-bound recovery observation that requires reconciliation; only status, reconciliation, or emergency kill is allowed",
            Some(actual),
        );
    }
    if state.production_grant_verifier.is_some()
        && matches!(
            operation,
            SupervisordMutation::Upgrade | SupervisordMutation::Rollback
        )
    {
        return error_payload(
            "signed_release_authority_required",
            "production mode requires SignedUpgrade or SignedRollback for release transitions",
            Some(actual),
        );
    }

    let prepared = match (operation, target) {
        (SupervisordMutation::Start, Some(target)) => PreparedMutation::Start(target),
        (SupervisordMutation::Drain, None) => PreparedMutation::Drain,
        (SupervisordMutation::Stop, None) => PreparedMutation::Stop,
        (SupervisordMutation::Kill, None) => PreparedMutation::Kill,
        (SupervisordMutation::Restart, None) => PreparedMutation::Restart,
        (SupervisordMutation::Upgrade, Some(target)) => PreparedMutation::Upgrade(target),
        (SupervisordMutation::Rollback, None) => PreparedMutation::Rollback,
        (SupervisordMutation::Start | SupervisordMutation::Upgrade, None) => {
            return error_payload(
                "invalid_frame",
                "request is not valid supervisord control JSON",
                Some(actual),
            );
        }
        (
            SupervisordMutation::Drain
            | SupervisordMutation::Stop
            | SupervisordMutation::Kill
            | SupervisordMutation::Restart
            | SupervisordMutation::Rollback,
            Some(_),
        ) => {
            return error_payload(
                "invalid_frame",
                "request is not valid supervisord control JSON",
                Some(actual),
            );
        }
    };

    let preflight = match &prepared {
        PreparedMutation::Start(_) => supervisor.preflight_start(&agent_id),
        PreparedMutation::Drain => supervisor.preflight_drain(&agent_id),
        PreparedMutation::Stop => supervisor
            .ensure_recovery_unblocked(&agent_id)
            .and_then(|()| supervisor.preflight_stop_or_kill(&agent_id)),
        PreparedMutation::Kill => supervisor.preflight_stop_or_kill(&agent_id),
        PreparedMutation::Restart => supervisor.preflight_restart(&agent_id),
        PreparedMutation::Upgrade(target) => supervisor.preflight_upgrade(&agent_id, target),
        PreparedMutation::Rollback => supervisor.preflight_rollback(&agent_id),
    };
    if let Err(error) = preflight {
        let refreshed = agent_status_locked(&state, &supervisor, &agent_id).ok();
        return safe_rejection(
            error,
            refreshed.or(Some(actual)),
            /*mutation_started*/ false,
        );
    }

    let next_revision = match supervisor.next_control_revision(&agent_id) {
        Ok(revision) => revision,
        Err(error) => return safe_rejection(error, Some(actual), /*mutation_started*/ false),
    };

    let run_root = match agent_run_root(&state, &agent_id) {
        Ok(run_root) => run_root,
        Err(error) => {
            return safe_rejection(error, Some(actual), /*mutation_started*/ false);
        }
    };
    let run_root = match journal::admission_root(&run_root, operation) {
        Ok(root) => root,
        Err(error) => {
            return safe_rejection(
                SupervisorError::Invalid(error.to_string()),
                Some(actual),
                /*mutation_started*/ false,
            );
        }
    };
    let durable = match crate::prepare_mutation(
        &run_root,
        request_id,
        &agent_id,
        state.supervisor_epoch.as_str(),
        operation,
        accepted_state_digest.as_str(),
        next_revision,
    ) {
        Ok(status) => status,
        Err(error) => {
            if !matches!(error, crate::MutationJournalError::IdentityConflict) {
                let _ = state.block_recovery_observation(agent_id.clone());
            }
            return error_payload(
                "mutation_journal_rejected",
                &format!("ordinary mutation was not admitted: {error}"),
                Some(actual),
            );
        }
    };
    match durable.phase {
        crate::DurableMutationPhaseV1::Prepared => {}
        crate::DurableMutationPhaseV1::Committed => {
            return error_payload(
                "mutation_already_committed",
                "this request already committed; query OrdinaryMutationStatus instead of replaying it",
                Some(actual),
            );
        }
        crate::DurableMutationPhaseV1::NoEffect => {
            return error_payload(
                "mutation_resolved_without_effect",
                "the original request was resolved before spawn; choose a new request ID",
                Some(actual),
            );
        }
        crate::DurableMutationPhaseV1::EffectStarted
        | crate::DurableMutationPhaseV1::Ambiguous
        | crate::DurableMutationPhaseV1::RequiresOperator => {
            let _ = state.block_recovery_observation(agent_id.clone());
            return error_payload(
                "mutation_reconciliation_required",
                "this request crossed the effect boundary; query or reconcile its durable status instead of replaying it",
                Some(actual),
            );
        }
    }
    let durable = match crate::mark_mutation_effect_started(&run_root, &durable.idempotency_key) {
        Ok(status) => status,
        Err(error) => {
            let _ = state.block_recovery_observation(agent_id.clone());
            return error_payload(
                "mutation_journal_rejected",
                &format!("ordinary mutation effect boundary was not persisted: {error}"),
                Some(actual),
            );
        }
    };
    if let Err(error) = supervisor.set_control_revision(&agent_id, next_revision) {
        let _ = state.block_recovery_observation(agent_id.clone());
        let observed = agent_status_locked(&state, &supervisor, &agent_id)
            .ok()
            .map(|status| status.control_fence.state_digest);
        let _ = crate::mark_mutation_ambiguous(
            &run_root,
            &durable.idempotency_key,
            observed.as_ref().map(ControlStateDigest::as_str),
            "control revision persistence failed after the durable effect boundary",
        );
        return safe_rejection(error, Some(actual), /*mutation_started*/ true);
    }

    let mutation = match prepared {
        PreparedMutation::Start(target) => {
            supervisor.start_release(&agent_id, target, Instant::now())
        }
        PreparedMutation::Drain => supervisor.drain(&agent_id, Instant::now()),
        PreparedMutation::Stop => supervisor.stop(&agent_id, Instant::now()),
        PreparedMutation::Kill => supervisor.kill(&agent_id),
        PreparedMutation::Restart => supervisor.restart(&agent_id, Instant::now()),
        PreparedMutation::Upgrade(target) => supervisor.upgrade(&agent_id, target, Instant::now()),
        PreparedMutation::Rollback => supervisor.rollback(&agent_id, Instant::now()),
    };
    let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
    if let Err(error) = mutation {
        let _ = state.block_recovery_observation(agent_id.clone());
        let _ = crate::mark_mutation_ambiguous(
            &run_root,
            &durable.idempotency_key,
            post.as_ref()
                .map(|status| status.control_fence.state_digest.as_str()),
            &format!(
                "driver returned an error after effect_started for request {request_id}: {error}"
            ),
        );
        return error_payload(
            "operation_indeterminate",
            "operation crossed the durable effect boundary; query OrdinaryMutationStatus before any retry",
            post,
        );
    }
    let Some(agent) = post else {
        let _ = state.block_recovery_observation(agent_id.clone());
        let _ = crate::mark_mutation_ambiguous(
            &run_root,
            &durable.idempotency_key,
            None,
            "operation completed but the post-state projection was unavailable",
        );
        return error_payload(
            "operation_indeterminate",
            "operation crossed the durable effect boundary; query OrdinaryMutationStatus before any retry",
            /*actual*/ None,
        );
    };
    if let Err(error) = crate::commit_mutation(
        &run_root,
        &durable.idempotency_key,
        next_revision,
        next_revision,
        agent.control_fence.state_digest.as_str(),
    ) {
        let _ = state.block_recovery_observation(agent_id.clone());
        let _ = crate::mark_mutation_ambiguous(
            &run_root,
            &durable.idempotency_key,
            Some(agent.control_fence.state_digest.as_str()),
            &format!(
                "effect completed but durable commit publication failed for request {request_id}: {error}"
            ),
        );
        return error_payload(
            "operation_indeterminate",
            "effect completed but its durable result is ambiguous; query OrdinaryMutationStatus",
            Some(agent),
        );
    }
    SupervisordPayload::MutationAccepted {
        operation,
        accepted_state_digest,
        agent,
        production_receipt: None,
    }
}

enum PreparedMutation {
    Start(AgentRelease),
    Drain,
    Stop,
    Kill,
    Restart,
    Upgrade(AgentRelease),
    Rollback,
}

fn agent_run_root<D: ProcessDriver>(
    state: &DaemonState<D>,
    agent_id: &AgentId,
) -> Result<PathBuf, SupervisorError> {
    state
        .registry
        .load()?
        .agent(agent_id)
        .map(|record| record.layout.owner_run_root().to_path_buf())
        .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))
}

pub(super) fn ordinary_mutation_status<D: ProcessDriver>(
    state: &DaemonState<D>,
    agent_id: &AgentId,
    mutation_request_id: u64,
) -> SupervisordPayload {
    let run_root = match agent_run_root(state, agent_id) {
        Ok(run_root) => run_root,
        Err(error) => {
            return safe_rejection(error, /*actual*/ None, /*mutation_started*/ false);
        }
    };
    match journal::lookup(&run_root, mutation_request_id) {
        Ok(status) => SupervisordPayload::OrdinaryMutationStatus {
            status: status
                .map(|owned| owned.status)
                .filter(|status| status.agent_id == *agent_id),
        },
        Err(error) => safe_rejection(
            SupervisorError::Invalid(error.to_string()),
            /*actual*/ None,
            /*mutation_started*/ false,
        ),
    }
}

pub(super) async fn reconcile_ordinary_mutation<D: ProcessDriver>(
    state: Arc<DaemonState<D>>,
    fence: SupervisordControlFence,
    mutation_request_id: u64,
) -> SupervisordPayload {
    let agent_id = fence.agent_id.clone();
    let mut supervisor = state.supervisor.lock().await;
    let actual = match agent_status_locked(&state, &supervisor, &agent_id) {
        Ok(actual) => actual,
        Err(error) => {
            return safe_rejection(error, /*actual*/ None, /*mutation_started*/ false);
        }
    };
    if !control_fence_matches(&fence, &actual.control_fence) {
        return error_payload(
            "stale_control_fence",
            "selected Agent changed; refresh before reconciliation",
            Some(actual),
        );
    }
    let run_root = match agent_run_root(&state, &agent_id) {
        Ok(run_root) => run_root,
        Err(error) => {
            return safe_rejection(error, Some(actual), /*mutation_started*/ false);
        }
    };
    let Some(owned) = (match journal::lookup(&run_root, mutation_request_id) {
        Ok(status) => status,
        Err(error) => {
            return safe_rejection(
                SupervisorError::Invalid(error.to_string()),
                Some(actual),
                /*mutation_started*/ false,
            );
        }
    }) else {
        return SupervisordPayload::OrdinaryMutationStatus { status: None };
    };
    let journal::OwnedStatus {
        root: run_root,
        status,
    } = owned;
    if status.agent_id != agent_id || status.request_id != mutation_request_id {
        return SupervisordPayload::OrdinaryMutationStatus { status: None };
    }
    match super::no_effect::reconcile(&state, &mut supervisor, &run_root, &status, &actual) {
        Ok(Some(status)) => {
            return SupervisordPayload::OrdinaryMutationStatus {
                status: Some(status),
            };
        }
        Ok(None) => {}
        Err(error) => return safe_rejection(error, Some(actual), /*mutation_started*/ false),
    }
    if !status.phase.terminal() {
        let _ = state.block_recovery_observation(agent_id.clone());
    }
    let reconciled = match status.phase {
        crate::DurableMutationPhaseV1::Prepared
        | crate::DurableMutationPhaseV1::Committed
        | crate::DurableMutationPhaseV1::NoEffect
        | crate::DurableMutationPhaseV1::RequiresOperator => Ok(status),
        crate::DurableMutationPhaseV1::EffectStarted | crate::DurableMutationPhaseV1::Ambiguous => {
            let ambiguous = crate::mark_mutation_ambiguous(
                &run_root,
                &status.idempotency_key,
                Some(actual.control_fence.state_digest.as_str()),
                "owner reconciliation could not prove whether the effect completed",
            );
            ambiguous.and_then(|ambiguous| {
                crate::require_mutation_operator(
                    &run_root,
                    &ambiguous.idempotency_key,
                    "automatic replay is forbidden after effect_started; inspect the exact process, lineage, exit witness, and recovery observation",
                )
            })
        }
    };
    match reconciled {
        Ok(status) => SupervisordPayload::OrdinaryMutationStatus {
            status: Some(status),
        },
        Err(error) => safe_rejection(
            SupervisorError::Invalid(error.to_string()),
            Some(actual),
            /*mutation_started*/ true,
        ),
    }
}

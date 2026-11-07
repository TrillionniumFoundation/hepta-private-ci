//! Signed mutation admission and bounded recovery projections.
use super::*;

pub(super) enum RecoveryResponseFormat {
    Inline,
    PagedV1,
}

pub(super) async fn handle_recovery_resolution<D: ProcessDriver>(
    state: Arc<DaemonState<D>>,
    fence: SupervisordControlFence,
    decision: ProductionRecoveryDecision,
) -> SupervisordPayload {
    handle_recovery_resolution_with_format(state, fence, decision, RecoveryResponseFormat::Inline)
        .await
}

pub(super) fn mutation_page_locked<D: ProcessDriver>(
    state: &DaemonState<D>,
    supervisor: &Supervisor<D>,
    agent_id: &AgentId,
    cursor: Option<&crate::daemon_protocol::ProductionMutationCursorV1>,
) -> Result<crate::daemon_protocol::ProductionMutationPageV1, SupervisorError> {
    let fence = agent_status_locked(state, supervisor, agent_id)?.control_fence;
    let observation = supervisor.production_mutation_state(agent_id)?;
    crate::daemon_protocol::production_mutation_page(observation, fence, cursor)
}

pub(super) async fn handle_recovery_resolution_with_format<D: ProcessDriver>(
    state: Arc<DaemonState<D>>,
    fence: SupervisordControlFence,
    decision: ProductionRecoveryDecision,
    format: RecoveryResponseFormat,
) -> SupervisordPayload {
    if !PRODUCTION_AUTHORITY_FEATURE_ENABLED {
        return error_payload(
            "production_authority_unavailable",
            "signed production recovery is disabled in this build",
            /*actual*/ None,
        );
    }
    let Some(verifier) = state.production_grant_verifier.clone() else {
        return error_payload(
            "production_authority_unavailable",
            "signed production recovery requires an externally pinned verifier",
            /*actual*/ None,
        );
    };
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
            "selected Agent changed; refresh before recovery",
            Some(actual),
        );
    }
    if matches!(format, RecoveryResponseFormat::Inline) {
        let current = match supervisor.production_mutation_state(&agent_id) {
            Ok(current) => current,
            Err(error) => {
                return safe_rejection(error, Some(actual), /*mutation_started*/ false);
            }
        };
        let encoded = serde_json::to_vec(&current).map(|bytes| bytes.len());
        let decision_bytes = serde_json::to_vec(&decision).map(|bytes| bytes.len());
        let bounded_reply =
            encoded
                .ok()
                .zip(decision_bytes.ok())
                .is_some_and(|(current, decision)| {
                    current.saturating_add(decision).saturating_add(4096) <= 60 * 1024
                });
        if verifier.policy_sha256().is_some()
            || decision.pq_authority.is_some()
            || current.as_ref().is_some_and(|state| {
                state
                    .unknown_effects
                    .iter()
                    .any(|entry| entry.decision.pq_authority.is_some())
            })
            || !bounded_reply
        {
            return error_payload(
                "production_mutation_page_required",
                "use resolve_production_recovery_page_v1 for this retained history",
                Some(actual),
            );
        }
    }
    let authority_epoch = authority_epoch_for_supervisor_epoch(state.supervisor_epoch.as_str());
    if let Err(error) = supervisor.resolve_production_recovery(
        &agent_id,
        &decision,
        &verifier,
        authority_epoch,
        qualification_seconds_now(&state.registry),
    ) {
        let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
        return safe_rejection(
            error,
            post.or(Some(actual)),
            /*mutation_started*/ false,
        );
    }
    match format {
        RecoveryResponseFormat::Inline => match supervisor.production_mutation_state(&agent_id) {
            Ok(state) => SupervisordPayload::ProductionMutationStatus { state },
            Err(error) => safe_rejection(error, Some(actual), /*mutation_started*/ true),
        },
        RecoveryResponseFormat::PagedV1 => {
            match mutation_page_locked(&state, &supervisor, &agent_id, /*cursor*/ None) {
                Ok(page) => SupervisordPayload::ProductionMutationStatusPageV1 { page },
                Err(error) => safe_rejection(error, Some(actual), /*mutation_started*/ true),
            }
        }
    }
}

pub(super) async fn handle_signed_mutation<D: ProcessDriver>(
    state: Arc<DaemonState<D>>,
    transition: H7H89ProductionTransition,
    fence: SupervisordControlFence,
    grant: H7H89ProductionGrant,
    h7_envelope: codex_hepta_memory::H7SignedArtifactEnvelope,
) -> SupervisordPayload {
    if !PRODUCTION_AUTHORITY_FEATURE_ENABLED {
        return error_payload(
            "production_authority_unavailable",
            "signed production mutations are disabled in this build",
            /*actual*/ None,
        );
    }
    let Some(verifier) = state.production_grant_verifier.clone() else {
        return error_payload(
            "production_authority_unavailable",
            "signed production mutations require an externally pinned verifier",
            /*actual*/ None,
        );
    };
    if grant.transition != transition {
        return error_payload(
            "production_authority_rejected",
            "signed operation transition does not match the requested RPC method",
            /*actual*/ None,
        );
    }
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
        Ok(true) => {
            return error_payload(
                "signed_intent_recovery_required",
                "resolve the quarantined production mutation before admitting another signed transition",
                Some(actual),
            );
        }
        Ok(false) => {}
        Err(error) => {
            return safe_rejection(error, Some(actual), /*mutation_started*/ false);
        }
    }
    let authority_epoch = authority_epoch_for_supervisor_epoch(state.supervisor_epoch.as_str());
    let receipt = match supervisor.apply_production_grant(
        &agent_id,
        &grant,
        &h7_envelope,
        &verifier,
        authority_epoch,
        qualification_seconds_now(&state.registry),
        Instant::now(),
    ) {
        Ok(receipt) => receipt,
        Err(error) => {
            let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
            return safe_rejection(
                error,
                post.or(Some(actual)),
                /*mutation_started*/ false,
            );
        }
    };
    let post = agent_status_locked(&state, &supervisor, &agent_id).ok();
    let Some(agent) = post else {
        return error_payload(
            "operation_indeterminate",
            "signed operation outcome is indeterminate; refresh before retry",
            /*actual*/ None,
        );
    };
    SupervisordPayload::MutationAccepted {
        operation: match transition {
            H7H89ProductionTransition::Upgrade => SupervisordMutation::Upgrade,
            H7H89ProductionTransition::Rollback => SupervisordMutation::Rollback,
        },
        accepted_state_digest,
        agent,
        production_receipt: Some(receipt),
    }
}

fn qualification_seconds_now(registry: &FleetRegistry) -> u64 {
    // Ordinary admission obtains time only from the fresh publication owner.
    if !registry.is_release_qualification() {
        return 0;
    }
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0)
}

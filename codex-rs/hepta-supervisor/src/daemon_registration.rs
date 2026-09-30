use std::sync::Arc;

use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ReleaseId;

use super::DaemonState;
use super::agent_status_locked;
use super::control_fence_matches;
use super::error_payload;
use super::safe_rejection;
use crate::ProcessDriver;
use crate::SupervisordControlFence;
use crate::SupervisordPayload;

pub(super) async fn register<D: ProcessDriver>(
    state: Arc<DaemonState<D>>,
    manifest: AgentManifest,
) -> SupervisordPayload {
    let agent_id = manifest.agent_id.clone();
    let mut supervisor = state.supervisor.lock().await;
    if let Err(error) = supervisor.register_agent(manifest) {
        return configuration_rejection(error, /*actual*/ None);
    }
    match agent_status_locked(&state, &supervisor, &agent_id) {
        Ok(agent) => SupervisordPayload::AgentRegistered { agent },
        Err(error) => safe_rejection(error, /*actual*/ None, /*mutation_started*/ true),
    }
}

pub(super) async fn allow<D: ProcessDriver>(
    state: Arc<DaemonState<D>>,
    fence: SupervisordControlFence,
    release_id: ReleaseId,
) -> SupervisordPayload {
    let supervisor = state.supervisor.lock().await;
    let actual = match agent_status_locked(&state, &supervisor, &fence.agent_id) {
        Ok(actual) => actual,
        Err(error) => {
            return safe_rejection(error, /*actual*/ None, /*mutation_started*/ false);
        }
    };
    if !control_fence_matches(&fence, &actual.control_fence) {
        return error_payload(
            "stale_control_fence",
            "selected Agent changed; refresh before configuration",
            Some(actual),
        );
    }
    if state.recovery_observation_blocked_for(&fence.agent_id) {
        return error_payload(
            "recovery_observation_required",
            "configuration cannot replace unresolved recovery evidence",
            Some(actual),
        );
    }
    if let Err(error) = supervisor.ensure_configuration_ready(&fence.agent_id) {
        return configuration_rejection(error, Some(actual));
    }
    match state.registry.allow_release(&fence.agent_id, &release_id) {
        Ok(()) => match agent_status_locked(&state, &supervisor, &fence.agent_id) {
            Ok(agent) => SupervisordPayload::InstalledReleaseAllowed { agent },
            Err(error) => safe_rejection(error, Some(actual), /*mutation_started*/ true),
        },
        Err(error) => configuration_rejection(error.into(), Some(actual)),
    }
}

pub(super) async fn retire<D: ProcessDriver>(
    state: Arc<DaemonState<D>>,
    fence: SupervisordControlFence,
) -> SupervisordPayload {
    let mut supervisor = state.supervisor.lock().await;
    let actual = match agent_status_locked(&state, &supervisor, &fence.agent_id) {
        Ok(actual) => actual,
        Err(error) => {
            return safe_rejection(error, /*actual*/ None, /*mutation_started*/ false);
        }
    };
    if !control_fence_matches(&fence, &actual.control_fence) {
        return error_payload(
            "stale_control_fence",
            "selected Agent changed; refresh before retirement",
            Some(actual),
        );
    }
    if state.recovery_observation_blocked_for(&fence.agent_id) {
        return error_payload(
            "recovery_observation_required",
            "retirement cannot archive unresolved recovery evidence",
            Some(actual),
        );
    }
    match supervisor.retire_agent(&fence.agent_id) {
        Ok(archived_root) => SupervisordPayload::AgentRetired {
            agent_id: fence.agent_id,
            archived_root,
        },
        Err(error) => configuration_rejection(error, Some(actual)),
    }
}

fn configuration_rejection(
    error: crate::SupervisorError,
    actual: Option<crate::SupervisordAgentStatus>,
) -> SupervisordPayload {
    if let crate::SupervisorError::Invalid(message) = &error {
        return error_payload("configuration_not_ready", message, actual);
    }
    // Known admission failures have no effect. A storage error can occur after
    // canonical atomic publication, so never claim definite rejection for it.
    let mutation_started = matches!(
        &error,
        crate::SupervisorError::Io(_)
            | crate::SupervisorError::Registry(codex_hepta_fleet::FleetRegistryError::Io(_))
    );
    safe_rejection(error, actual, mutation_started)
}

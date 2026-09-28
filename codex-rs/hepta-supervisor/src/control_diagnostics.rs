//! Read-only operational diagnostics derived from the existing supervisor owner state.
//!
//! These values do not grant lifecycle authority and are never mutation inputs.
//! They intentionally report capability gaps without exposing command arguments,
//! environment variables, workspace paths or raw process-driver messages.

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentSupervisorSnapshot;
use crate::ControlRuntimePhase;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlProgress {
    Idle,
    Starting,
    AwaitingHealth,
    Running,
    Draining,
    Stopping,
    Killing,
    FinalizingExit,
    RestartQueued,
    ReleaseTransition,
    RecoveryRequired,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlBlocker {
    TargetIdentityChanged,
    AwaitingProcessExit,
    RestartBackoff,
    RestartBudgetExhausted,
    ReleaseTransitionInProgress,
    PersistenceUncertain,
    RecoveryQuarantined,
    ControlStateUnavailable,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EnforcementLevel {
    Enforced,
    DeclaredOnly,
    Unsupported,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceEnforcementStatus {
    pub operation_timeout: EnforcementLevel,
    pub memory_limit: EnforcementLevel,
    pub subprocess_limit: EnforcementLevel,
    pub network_policy: EnforcementLevel,
}

impl ResourceEnforcementStatus {
    fn native() -> Self {
        Self {
            operation_timeout: EnforcementLevel::Enforced,
            memory_limit: EnforcementLevel::DeclaredOnly,
            subprocess_limit: EnforcementLevel::DeclaredOnly,
            network_policy: EnforcementLevel::DeclaredOnly,
        }
    }

    pub fn has_declared_only_limits(&self) -> bool {
        matches!(self.memory_limit, EnforcementLevel::DeclaredOnly)
            || matches!(self.subprocess_limit, EnforcementLevel::DeclaredOnly)
            || matches!(self.network_policy, EnforcementLevel::DeclaredOnly)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlDiagnosticsSnapshot {
    pub agent_id: AgentId,
    /// Owner-local request identity. The complete control fence remains the
    /// only mutation CAS and must be refreshed after a daemon restart.
    pub operation_id: Option<String>,
    pub operation_revision: u64,
    pub target_spawn_generation: Option<u64>,
    pub target_runtime_generation: Option<u64>,
    pub progress: ControlProgress,
    pub blocker: Option<ControlBlocker>,
    pub can_accept_new_mutation: bool,
    pub recovery_required: bool,
    pub persistence_uncertain: bool,
    pub release_change_pending: bool,
    pub restart_pending: bool,
    pub runtime_fenced: bool,
    pub resource_enforcement: ResourceEnforcementStatus,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorOperationalSummary {
    pub registered_agents: u64,
    pub blocked_agents: u64,
    pub target_identity_changed: u64,
    pub awaiting_process_exit: u64,
    pub restart_backoff: u64,
    pub restart_budget_exhausted: u64,
    pub release_transition_in_progress: u64,
    pub persistence_uncertain: u64,
    pub recovery_quarantined: u64,
    pub control_state_unavailable: u64,
    pub resource_enforcement_gaps: u64,
}

impl<D: ProcessDriver> Supervisor<D> {
    pub fn control_diagnostics(
        &self,
        agent_id: &AgentId,
    ) -> Result<ControlDiagnosticsSnapshot, SupervisorError> {
        let fleet = self.registry.load()?;
        let record = fleet
            .agent(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        self.control_diagnostics_for_lifecycle(agent_id, record.lifecycle.lifecycle)
    }

    pub fn operational_summary(&self) -> Result<SupervisorOperationalSummary, SupervisorError> {
        // Load the Fleet projection once. A periodic operational snapshot must
        // not amplify one read into N registry scans for a 256-Agent roster.
        let fleet = self.registry.load()?;
        let mut summary = SupervisorOperationalSummary {
            registered_agents: u64::try_from(fleet.agents.len()).unwrap_or(u64::MAX),
            ..SupervisorOperationalSummary::default()
        };
        for (agent_id, record) in &fleet.agents {
            let diagnostic = match self
                .control_diagnostics_for_lifecycle(agent_id, record.lifecycle.lifecycle)
            {
                Ok(diagnostic) => diagnostic,
                Err(_) => {
                    summary.blocked_agents = summary.blocked_agents.saturating_add(1);
                    summary.control_state_unavailable =
                        summary.control_state_unavailable.saturating_add(1);
                    continue;
                }
            };
            if diagnostic.resource_enforcement.has_declared_only_limits() {
                summary.resource_enforcement_gaps =
                    summary.resource_enforcement_gaps.saturating_add(1);
            }
            let Some(blocker) = diagnostic.blocker else {
                continue;
            };
            summary.blocked_agents = summary.blocked_agents.saturating_add(1);
            match blocker {
                ControlBlocker::TargetIdentityChanged => {
                    summary.target_identity_changed =
                        summary.target_identity_changed.saturating_add(1);
                }
                ControlBlocker::AwaitingProcessExit => {
                    summary.awaiting_process_exit = summary.awaiting_process_exit.saturating_add(1);
                }
                ControlBlocker::RestartBackoff => {
                    summary.restart_backoff = summary.restart_backoff.saturating_add(1);
                }
                ControlBlocker::RestartBudgetExhausted => {
                    summary.restart_budget_exhausted =
                        summary.restart_budget_exhausted.saturating_add(1);
                }
                ControlBlocker::ReleaseTransitionInProgress => {
                    summary.release_transition_in_progress =
                        summary.release_transition_in_progress.saturating_add(1);
                }
                ControlBlocker::PersistenceUncertain => {
                    summary.persistence_uncertain = summary.persistence_uncertain.saturating_add(1);
                }
                ControlBlocker::RecoveryQuarantined => {
                    summary.recovery_quarantined = summary.recovery_quarantined.saturating_add(1);
                }
                ControlBlocker::ControlStateUnavailable => {
                    summary.control_state_unavailable =
                        summary.control_state_unavailable.saturating_add(1);
                }
            }
        }
        Ok(summary)
    }

    fn control_diagnostics_for_lifecycle(
        &self,
        agent_id: &AgentId,
        lifecycle: AgentLifecycle,
    ) -> Result<ControlDiagnosticsSnapshot, SupervisorError> {
        let snapshot = self
            .snapshot(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        let recovery_required = self.production_recovery_required(agent_id)?;
        Ok(derive(
            agent_id.clone(),
            lifecycle,
            snapshot,
            recovery_required,
            self.config.restart_max_attempts,
        ))
    }
}

fn derive(
    agent_id: AgentId,
    lifecycle: AgentLifecycle,
    snapshot: AgentSupervisorSnapshot,
    recovery_required: bool,
    restart_max_attempts: u32,
) -> ControlDiagnosticsSnapshot {
    let effect_in_flight = snapshot.release_change_pending
        || snapshot.restart_pending
        || matches!(
            snapshot.runtime_phase,
            Some(
                ControlRuntimePhase::Draining
                    | ControlRuntimePhase::Stopping
                    | ControlRuntimePhase::Killing
            )
        );
    let recent_recovery_fault = snapshot.events.iter().rev().take(8).any(|event| {
        matches!(
            event.kind,
            SupervisorEventKind::OrphanRejected | SupervisorEventKind::MatrixOrphanRejected
        )
    });
    let latest_driver_fault = snapshot
        .events
        .last()
        .is_some_and(|event| matches!(event.kind, SupervisorEventKind::DriverFault(_)));
    let persistence_uncertain = snapshot.runtime_fenced
        || recent_recovery_fault
        || (latest_driver_fault && effect_in_flight);
    let restart_exhausted = snapshot.restart_attempt >= restart_max_attempts
        || snapshot.matrix.restart_attempt >= restart_max_attempts
        || snapshot.events.iter().rev().take(8).any(|event| {
            matches!(
                event.kind,
                SupervisorEventKind::RestartBudgetExhausted { .. }
                    | SupervisorEventKind::MatrixRestartBudgetExhausted { .. }
            )
        });

    let progress = if recovery_required {
        ControlProgress::RecoveryRequired
    } else if snapshot.release_change_pending {
        ControlProgress::ReleaseTransition
    } else if snapshot.restart_pending {
        ControlProgress::RestartQueued
    } else if snapshot.active && snapshot.runtime_phase.is_none() {
        ControlProgress::FinalizingExit
    } else {
        match snapshot.runtime_phase {
            Some(ControlRuntimePhase::AwaitingHealth) => ControlProgress::AwaitingHealth,
            Some(ControlRuntimePhase::Running) => ControlProgress::Running,
            Some(ControlRuntimePhase::Draining) => ControlProgress::Draining,
            Some(ControlRuntimePhase::Stopping) => ControlProgress::Stopping,
            Some(ControlRuntimePhase::Killing) => ControlProgress::Killing,
            None if lifecycle == AgentLifecycle::Starting => ControlProgress::Starting,
            None => ControlProgress::Idle,
        }
    };

    let blocker = if recovery_required {
        Some(ControlBlocker::RecoveryQuarantined)
    } else if snapshot.runtime_fenced
        || snapshot
            .events
            .iter()
            .rev()
            .take(8)
            .any(|event| matches!(event.kind, SupervisorEventKind::GenerationFenced { .. }))
    {
        Some(ControlBlocker::TargetIdentityChanged)
    } else if persistence_uncertain {
        Some(ControlBlocker::PersistenceUncertain)
    } else if snapshot.release_change_pending {
        Some(ControlBlocker::ReleaseTransitionInProgress)
    } else if restart_exhausted {
        Some(ControlBlocker::RestartBudgetExhausted)
    } else if snapshot.restart_pending {
        Some(ControlBlocker::RestartBackoff)
    } else if matches!(
        snapshot.runtime_phase,
        Some(
            ControlRuntimePhase::Draining
                | ControlRuntimePhase::Stopping
                | ControlRuntimePhase::Killing
        )
    ) {
        Some(ControlBlocker::AwaitingProcessExit)
    } else if matches!(
        lifecycle,
        AgentLifecycle::Starting | AgentLifecycle::Running | AgentLifecycle::Draining
    ) && !snapshot.active
    {
        Some(ControlBlocker::ControlStateUnavailable)
    } else {
        None
    };

    let operation_id = (snapshot.control_revision > 0)
        .then(|| format!("{}:{}", agent_id, snapshot.control_revision));
    ControlDiagnosticsSnapshot {
        agent_id,
        operation_id,
        operation_revision: snapshot.control_revision,
        target_spawn_generation: snapshot.spawn_generation,
        target_runtime_generation: snapshot.runtime_generation,
        progress,
        blocker,
        can_accept_new_mutation: blocker.is_none(),
        recovery_required,
        persistence_uncertain,
        release_change_pending: snapshot.release_change_pending,
        restart_pending: snapshot.restart_pending,
        runtime_fenced: snapshot.runtime_fenced,
        resource_enforcement: ResourceEnforcementStatus::native(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::MatrixSupervisorSnapshot;
    use crate::SupervisorEvent;

    fn snapshot() -> AgentSupervisorSnapshot {
        AgentSupervisorSnapshot {
            active: true,
            healthy: true,
            runtime_generation: Some(7),
            spawn_generation: Some(6),
            process_system_id: Some(41),
            active_release: Some("release-a".to_string()),
            previous_release: None,
            release_change_pending: false,
            matrix: MatrixSupervisorSnapshot {
                configured: false,
                active: false,
                healthy: false,
                degraded: false,
                process_system_id: None,
                attached_agent_generation: None,
                binding_revision: None,
                restart_attempt: 0,
                last_error: None,
            },
            events: Vec::new(),
            logs: Vec::new(),
            control_revision: 9,
            restart_pending: false,
            restart_attempt: 0,
            release_state_generation: 1,
            runtime_phase: Some(ControlRuntimePhase::Running),
            runtime_release: Some("release-a".to_string()),
            runtime_incarnation: Some("incarnation-a".to_string()),
            runtime_fenced: false,
            release_change: None,
            has_last_command: true,
        }
    }

    fn agent() -> AgentId {
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent")
    }

    #[test]
    fn recovery_quarantine_dominates_retryable_runtime_state() {
        let diagnostic = derive(agent(), AgentLifecycle::Running, snapshot(), true, 5);
        assert_eq!(diagnostic.progress, ControlProgress::RecoveryRequired);
        assert_eq!(
            diagnostic.blocker,
            Some(ControlBlocker::RecoveryQuarantined)
        );
        assert!(!diagnostic.can_accept_new_mutation);
    }

    #[test]
    fn generation_fence_is_reported_without_raw_driver_message() {
        let mut state = snapshot();
        state.runtime_fenced = true;
        state.events.push(SupervisorEvent {
            generation: 7,
            kind: SupervisorEventKind::GenerationFenced {
                runtime: 7,
                registry: 8,
            },
        });
        let diagnostic = derive(agent(), AgentLifecycle::Running, state, false, 5);
        assert_eq!(
            diagnostic.blocker,
            Some(ControlBlocker::TargetIdentityChanged)
        );
        assert_eq!(diagnostic.operation_revision, 9);
        assert_eq!(
            diagnostic.operation_id.as_deref(),
            Some("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12:9")
        );
        assert_eq!(diagnostic.target_spawn_generation, Some(6));
    }

    #[test]
    fn resource_capability_gaps_are_explicit_but_not_a_lifecycle_blocker() {
        let diagnostic = derive(agent(), AgentLifecycle::Running, snapshot(), false, 5);
        assert!(diagnostic.can_accept_new_mutation);
        assert!(diagnostic.resource_enforcement.has_declared_only_limits());
        assert_eq!(
            diagnostic.resource_enforcement.operation_timeout,
            EnforcementLevel::Enforced
        );
    }

    #[test]
    fn historical_driver_fault_without_inflight_effect_is_not_persistence_uncertain() {
        let mut state = snapshot();
        state.events.push(SupervisorEvent {
            generation: 7,
            kind: SupervisorEventKind::DriverFault("redacted".to_string()),
        });
        let diagnostic = derive(agent(), AgentLifecycle::Running, state, false, 5);
        assert!(!diagnostic.persistence_uncertain);
        assert_eq!(diagnostic.blocker, None);
    }
}

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;

use super::Supervisor;
use crate::ProcessDriver;
use crate::SupervisorError;
use crate::daemon_protocol::SupervisordSignedIntent;
use crate::daemon_protocol::SupervisordSignedIntentResolution;
use crate::daemon_protocol::SupervisordSignedIntentStatus;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;

impl<D: ProcessDriver> Supervisor<D> {
    /// Any unresolved externally-authorized mutation freezes every ordinary
    /// lifecycle mutation in the daemon and in direct library callers.
    /// Read-only status/inspection and the explicit recovery ceremony remain
    /// available.
    pub(crate) fn has_unresolved_signed_intents(&self) -> bool {
        !self.recovery_blocked.is_empty()
            || self.slots.values().any(|slot| {
                slot.signed_intent
                    .as_ref()
                    .is_some_and(|intent| intent.status.is_unresolved())
            })
    }

    pub(crate) fn ensure_mutations_unfrozen(&self) -> Result<(), SupervisorError> {
        if let Some(agent_id) = self.recovery_blocked.iter().next() {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        if let Some((agent_id, _)) = self.slots.iter().find(|(_, slot)| {
            slot.signed_intent
                .as_ref()
                .is_some_and(|intent| intent.status.is_unresolved())
        }) {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        Ok(())
    }

    pub(crate) fn inspect_signed_intent(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<SupervisordSignedIntent>, SupervisorError> {
        let record = self.record(agent_id)?;
        read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .map(intent_view)
            .transpose()
    }

    /// Resolve an ambiguous signed mutation without causing a new external
    /// effect. The process and process leases must already be gone. The
    /// operator binds the exact durable intent digest and can only acknowledge
    /// whichever release identity is already committed in FleetRegistry.
    pub(crate) fn resolve_signed_intent(
        &mut self,
        agent_id: &AgentId,
        expected_intent_sha256: &Sha256Digest,
        resolution: SupervisordSignedIntentResolution,
    ) -> Result<SupervisordSignedIntent, SupervisorError> {
        let result = self.with_slot(agent_id, |supervisor, slot| {
            let record = supervisor.record(agent_id)?;
            let intent = read_intent(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .ok_or_else(|| {
                    SupervisorError::Invalid(format!(
                        "agent {agent_id} has no durable signed supervisor intent"
                    ))
                })?;
            if intent.agent_id != agent_id.to_string() {
                return Err(SupervisorError::Invalid(
                    "signed supervisor intent agent binding mismatch".to_string(),
                ));
            }
            if intent.status.is_terminal() {
                return Err(SupervisorError::Invalid(
                    "signed supervisor intent is already terminal".to_string(),
                ));
            }
            if &intent.intent_sha256 != expected_intent_sha256 {
                return Err(SupervisorError::Invalid(
                    "signed supervisor intent changed; inspect before recovery".to_string(),
                ));
            }
            if slot.runtime.is_some()
                || slot.matrix.runtime.is_some()
                || slot.release_change.is_some()
                || slot.restart_pending
                || slot.deferred_agent_action.is_some()
            {
                return Err(SupervisorError::Invalid(
                    "signed intent recovery requires all process activity to be quiescent"
                        .to_string(),
                ));
            }
            if read_lease(record.layout.run_root())?.is_some() {
                return Err(SupervisorError::UnresolvedLease(agent_id.clone()));
            }
            if read_matrix_lease(record.layout.matrixd_process_lease())?.is_some() {
                return Err(SupervisorError::Invalid(
                    "signed intent recovery requires the Matrix process lease to be cleared"
                        .to_string(),
                ));
            }

            // Validate the requested terminal fact before performing even a
            // lifecycle cleanup transition. A stale/wrong recovery request is
            // therefore a pure rejection rather than a partial mutation.
            let source = ReleaseId::parse(intent.source_release.clone())?;
            let target = ReleaseId::parse(intent.target_release.clone())?;
            let current = record.release_state.current.as_ref().ok_or_else(|| {
                SupervisorError::Invalid(
                    "signed intent recovery requires an explicit current release".to_string(),
                )
            })?;
            let terminal_status = match resolution {
                SupervisordSignedIntentResolution::ReconcileSource if current == &source => {
                    SignedIntentStatus::ReconciledSource
                }
                SupervisordSignedIntentResolution::AcceptTarget if current == &target => {
                    SignedIntentStatus::Committed
                }
                SupervisordSignedIntentResolution::ReconcileSource => {
                    return Err(SupervisorError::Invalid(format!(
                        "cannot reconcile source {}; durable current release is {current}",
                        source.as_str()
                    )));
                }
                SupervisordSignedIntentResolution::AcceptTarget => {
                    return Err(SupervisorError::Invalid(format!(
                        "cannot accept target {}; durable current release is {current}",
                        target.as_str()
                    )));
                }
            };

            // Recovery may have fenced and killed an adopted child after the
            // registry already advertised a live lifecycle. Once the exact
            // child/lease is absent, move only to the normal terminal failure
            // state; never invent successful process readiness.
            let lifecycle_record = match record.lifecycle.lifecycle {
                AgentLifecycle::Starting | AgentLifecycle::Running => Some(
                    supervisor.registry.compare_and_transition(
                        agent_id,
                        record.lifecycle.generation,
                        AgentLifecycle::Failed,
                    )?,
                ),
                AgentLifecycle::Draining => Some(supervisor.registry.compare_and_transition(
                    agent_id,
                    record.lifecycle.generation,
                    AgentLifecycle::Stopped,
                )?),
                AgentLifecycle::Failed | AgentLifecycle::Stopped => None,
            };
            if let Some(next) = lifecycle_record {
                slot.event(
                    next.generation,
                    crate::SupervisorEventKind::Lifecycle(next.lifecycle),
                );
            }

            let record = supervisor.record(agent_id)?;
            let terminal = intent
                .with_status(terminal_status)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &terminal)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(terminal.clone());
            slot.reset_automatic_restart_policy();
            slot.matrix.reset_restart_policy();
            supervisor.restore_release_state(agent_id, slot, &record)?;
            intent_view(terminal)
        });
        if result.is_ok() {
            self.recovery_blocked.remove(agent_id);
        }
        result
    }
}

pub(crate) fn intent_view(
    intent: SignedSupervisorIntent,
) -> Result<SupervisordSignedIntent, SupervisorError> {
    let status = match intent.status {
        SignedIntentStatus::Prepared => SupervisordSignedIntentStatus::Prepared,
        SignedIntentStatus::Queued => SupervisordSignedIntentStatus::Queued,
        SignedIntentStatus::Committed => SupervisordSignedIntentStatus::Committed,
        SignedIntentStatus::RecoveryRequired => SupervisordSignedIntentStatus::RecoveryRequired,
        SignedIntentStatus::ReconciledSource => SupervisordSignedIntentStatus::ReconciledSource,
    };
    Ok(SupervisordSignedIntent {
        grant_sha256: intent.grant_sha256,
        agent_id: AgentId::parse(intent.agent_id)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
        transition: intent.transition,
        source_release: ReleaseId::parse(intent.source_release)?,
        target_release: ReleaseId::parse(intent.target_release)?,
        expected_control_revision: intent.expected_control_revision,
        expected_lifecycle_generation: intent.expected_lifecycle_generation,
        authority_epoch: intent.authority_epoch,
        status,
        intent_sha256: intent.intent_sha256,
    })
}

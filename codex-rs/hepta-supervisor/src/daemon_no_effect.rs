//! Reconcile only a native proof of never crossing physical spawn admission.
use std::path::Path;

use super::DaemonState;
use crate::DurableMutationPhaseV1;
use crate::DurableMutationStatusV1;
use crate::ProcessDriver;
use crate::RecoveryReplayDecisionV1;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisordAgentStatus;
use crate::SupervisordMutation;

pub(super) fn reconcile<D: ProcessDriver>(
    state: &DaemonState<D>,
    supervisor: &mut Supervisor<D>,
    run_root: &Path,
    status: &DurableMutationStatusV1,
    actual: &SupervisordAgentStatus,
) -> Result<Option<DurableMutationStatusV1>, SupervisorError> {
    if status.operation != SupervisordMutation::Start
        || status.phase == DurableMutationPhaseV1::Committed
        || actual.active
        || actual.matrix.active
        || actual.process_id.is_some()
        || actual.matrix.process_id.is_some()
        || actual.current_release.is_some()
        || actual.release_change_pending
        || supervisor.production_recovery_required(&status.agent_id)?
        || crate::lease::read_lease(run_root)?.is_some()
        || crate::read_process_exit_witness(run_root)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .is_some()
        || crate::read_mutation_status(run_root)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .as_ref()
            != Some(status)
    {
        return Ok(None);
    }
    let Some(proof) = supervisor
        .driver
        .prove_never_spawned(&status.agent_id)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
    else {
        return Ok(None);
    };
    let resolved = crate::mutation_journal::resolve_before_spawn(
        run_root,
        &status.idempotency_key,
        actual.control_fence.state_digest.as_str(),
        &proof,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let snapshot = supervisor
        .snapshot(&status.agent_id)
        .ok_or_else(|| SupervisorError::UnknownAgent(status.agent_id.clone()))?;
    let observation = crate::publish_production_recovery_observation(
        run_root,
        &status.agent_id,
        state.supervisor_epoch.as_str(),
        actual.lifecycle,
        actual.lifecycle_generation,
        &snapshot,
        state
            .production_grant_verifier
            .as_ref()
            .map(|_| super::authority_epoch_for_supervisor_epoch(state.supervisor_epoch.as_str())),
        None,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    if crate::replay_production_recovery_observation(&observation)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        == RecoveryReplayDecisionV1::Clean
    {
        state
            .recovery_observation_blocked
            .write()
            .map_err(|_| SupervisorError::Invalid("recovery block set unavailable".into()))?
            .remove(&status.agent_id);
    }
    Ok(Some(resolved))
}

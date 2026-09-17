use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use serde::Serialize;

use crate::AdoptSpec;
use crate::Adoption;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::ProcessDriver;
use crate::SupervisorError;
use crate::lease::MatrixProcessLease;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use crate::lease::remove_lease;
use crate::lease::remove_matrix_lease;
use crate::lease::validate_lease;
use crate::runtime::driver_error;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SignedRecoveryResolution {
    Commit,
    Abort,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SignedRecoveryFenceOutcome {
    NoLease,
    KillRequested,
    LeaseCleared,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SignedRecoverySnapshot {
    pub agent_id: AgentId,
    pub lifecycle: AgentLifecycle,
    pub lifecycle_generation: u64,
    pub release_state_generation: u64,
    pub current_release: Option<ReleaseId>,
    pub previous_release: Option<ReleaseId>,
    pub main_process_lease_present: bool,
    pub matrix_process_lease_present: bool,
    pub intent: SignedSupervisorIntent,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SignedRecoveryFenceReport {
    pub main: SignedRecoveryFenceOutcome,
    pub matrix: SignedRecoveryFenceOutcome,
    pub snapshot: SignedRecoverySnapshot,
}

pub fn inspect_signed_recovery(
    registry: &FleetRegistry,
    agent_id: &AgentId,
) -> Result<SignedRecoverySnapshot, SupervisorError> {
    let record = registry.load_agent(agent_id)?;
    let intent = require_intent(&record.layout, agent_id)?;
    Ok(SignedRecoverySnapshot {
        agent_id: agent_id.clone(),
        lifecycle: record.lifecycle.lifecycle,
        lifecycle_generation: record.lifecycle.generation,
        release_state_generation: record.release_state.generation,
        current_release: record.release_state.current,
        previous_release: record.release_state.previous,
        main_process_lease_present: read_lease(record.layout.run_root())?.is_some(),
        matrix_process_lease_present: read_matrix_lease(record.layout.matrixd_process_lease())?
            .is_some(),
        intent,
    })
}

/// Fence both generation-bound child processes for one unresolved signed intent.
///
/// If exact adoption finds a live process, this function sends a kill request but
/// deliberately retains the lease. Re-run the operation after the process exits;
/// only an exact `Missing` observation is allowed to remove the corresponding
/// lease. A rejected adoption fails closed without changing either lease.
pub fn fence_signed_recovery<D: ProcessDriver>(
    registry: &FleetRegistry,
    driver: &mut D,
    agent_id: &AgentId,
) -> Result<SignedRecoveryFenceReport, SupervisorError> {
    let record = registry.load_agent(agent_id)?;
    let intent = require_intent(&record.layout, agent_id)?;
    ensure_unresolved(&intent)?;

    let main_lease = read_lease(record.layout.run_root())?;
    if let Some(lease) = main_lease.as_ref() {
        validate_lease(
            lease,
            agent_id,
            record.lifecycle.generation,
            record.lifecycle.lifecycle,
        )?;
    }
    let matrix_lease = read_matrix_lease(record.layout.matrixd_process_lease())?;
    if let Some(lease) = matrix_lease.as_ref()
        && &lease.agent_id != agent_id
    {
        return Err(SupervisorError::Invalid(format!(
            "Matrix process lease belongs to {} rather than {agent_id}",
            lease.agent_id
        )));
    }

    let main_adoption = match main_lease.as_ref() {
        Some(lease) => Some(
            driver
                .adopt(&main_adopt_spec(&record, lease))
                .map_err(|error| driver_error(agent_id, error))?,
        ),
        None => None,
    };
    let matrix_adoption = match matrix_lease.as_ref() {
        Some(lease) => Some(
            driver
                .adopt_matrixd(&matrix_adopt_spec(&record, lease))
                .map_err(|error| driver_error(agent_id, error))?,
        ),
        None => None,
    };

    // Adoption rejection means the durable identity cannot be proven. Refuse
    // before sending a kill to either child so the ceremony remains fail closed.
    if matches!(main_adoption, Some(Adoption::Rejected))
        || matches!(matrix_adoption, Some(Adoption::Rejected))
    {
        return Err(SupervisorError::Invalid(format!(
            "signed recovery cannot prove the exact child identity for {agent_id}"
        )));
    }

    let main = apply_main_fence(agent_id, &record, main_lease, main_adoption)?;
    let matrix = apply_matrix_fence(agent_id, &record, matrix_lease, matrix_adoption)?;

    // If no main-process lease remains, close any live lifecycle projection to
    // an explicit non-running state. This advances the normal FleetRegistry CAS
    // generation and becomes part of the evidence the operator must acknowledge.
    if read_lease(record.layout.run_root())?.is_none() {
        reconcile_lifecycle_without_process(registry, agent_id)?;
    }

    Ok(SignedRecoveryFenceReport {
        main,
        matrix,
        snapshot: inspect_signed_recovery(registry, agent_id)?,
    })
}

#[expect(
    clippy::too_many_arguments,
    reason = "break-glass recovery keeps every operator witness explicit"
)]
pub fn resolve_signed_recovery(
    registry: &FleetRegistry,
    agent_id: &AgentId,
    expected_grant_sha256: &Sha256Digest,
    expected_control_revision: u64,
    expected_lifecycle_generation: u64,
    expected_release_state_generation: u64,
    expected_authority_epoch: u64,
    resolution: SignedRecoveryResolution,
) -> Result<SignedRecoverySnapshot, SupervisorError> {
    let record = registry.load_agent(agent_id)?;
    let intent = require_intent(&record.layout, agent_id)?;

    let desired_status = match resolution {
        SignedRecoveryResolution::Commit => SignedIntentStatus::Committed,
        SignedRecoveryResolution::Abort => SignedIntentStatus::Aborted,
    };
    if intent.status == desired_status {
        return inspect_signed_recovery(registry, agent_id);
    }
    ensure_unresolved(&intent)?;

    if &intent.grant_sha256 != expected_grant_sha256
        || intent.expected_control_revision != expected_control_revision
        || intent.expected_lifecycle_generation > expected_lifecycle_generation
        || intent.authority_epoch != expected_authority_epoch
        || record.lifecycle.generation != expected_lifecycle_generation
        || record.release_state.generation != expected_release_state_generation
    {
        return Err(SupervisorError::Invalid(
            "signed recovery witnesses do not match durable state".to_string(),
        ));
    }
    if read_lease(record.layout.run_root())?.is_some()
        || read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
    {
        return Err(SupervisorError::Invalid(
            "signed recovery requires both exact process leases to be cleared".to_string(),
        ));
    }
    if !matches!(
        record.lifecycle.lifecycle,
        AgentLifecycle::Failed | AgentLifecycle::Stopped
    ) {
        return Err(SupervisorError::Invalid(
            "signed recovery requires a non-live lifecycle after fencing".to_string(),
        ));
    }

    let current = record
        .release_state
        .current
        .as_ref()
        .map(ReleaseId::as_str)
        .ok_or_else(|| {
            SupervisorError::Invalid(
                "signed recovery requires an exact current release witness".to_string(),
            )
        })?;
    let expected_release = match resolution {
        SignedRecoveryResolution::Commit => intent.target_release.as_str(),
        SignedRecoveryResolution::Abort => intent.source_release.as_str(),
    };
    if current != expected_release {
        return Err(SupervisorError::Invalid(format!(
            "signed recovery {:?} requires current release {expected_release}, found {current}",
            resolution
        )));
    }

    let terminal = intent
        .with_status(desired_status)
        .map_err(signed_intent_error)?;
    write_intent(record.layout.run_root(), &terminal).map_err(signed_intent_error)?;
    inspect_signed_recovery(registry, agent_id)
}

fn main_adopt_spec(
    record: &codex_hepta_fleet::AgentRecord,
    lease: &ProcessLease,
) -> AdoptSpec {
    AdoptSpec {
        agent_id: record.manifest.agent_id.clone(),
        registry_generation: record.lifecycle.generation,
        spawn_generation: lease.spawn_generation,
        workspace: record.manifest.workspace.as_path().to_path_buf(),
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        identity: lease.identity.clone(),
    }
}

fn matrix_adopt_spec(
    record: &codex_hepta_fleet::AgentRecord,
    lease: &MatrixProcessLease,
) -> MatrixAdoptSpec {
    MatrixAdoptSpec {
        agent_id: record.manifest.agent_id.clone(),
        agent_generation: lease.attached_agent_generation,
        binding_revision: lease.binding_revision,
        binding_digest: lease.binding_digest.clone(),
        release_id: lease.release_id.clone(),
        process_incarnation: lease.process_incarnation.clone(),
        plane_epoch: lease.plane_epoch,
        control_socket: record.layout.matrixd_control_socket().to_path_buf(),
        identity: lease.identity.clone(),
    }
}

fn apply_main_fence<P: ManagedProcess>(
    agent_id: &AgentId,
    record: &codex_hepta_fleet::AgentRecord,
    lease: Option<ProcessLease>,
    adoption: Option<Adoption<P>>,
) -> Result<SignedRecoveryFenceOutcome, SupervisorError> {
    match (lease, adoption) {
        (None, None) => Ok(SignedRecoveryFenceOutcome::NoLease),
        (Some(lease), Some(Adoption::Missing)) => {
            remove_lease(record.layout.run_root(), &lease)?;
            Ok(SignedRecoveryFenceOutcome::LeaseCleared)
        }
        (Some(_), Some(Adoption::Adopted(mut process))) => {
            process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            Ok(SignedRecoveryFenceOutcome::KillRequested)
        }
        (_, Some(Adoption::Rejected)) => unreachable!("rejected adoption is checked before effects"),
        _ => Err(SupervisorError::Invalid(
            "signed recovery main adoption state is inconsistent".to_string(),
        )),
    }
}

fn apply_matrix_fence<P: ManagedProcess>(
    agent_id: &AgentId,
    record: &codex_hepta_fleet::AgentRecord,
    lease: Option<MatrixProcessLease>,
    adoption: Option<Adoption<P>>,
) -> Result<SignedRecoveryFenceOutcome, SupervisorError> {
    match (lease, adoption) {
        (None, None) => Ok(SignedRecoveryFenceOutcome::NoLease),
        (Some(lease), Some(Adoption::Missing)) => {
            remove_matrix_lease(record.layout.matrixd_process_lease(), &lease)?;
            Ok(SignedRecoveryFenceOutcome::LeaseCleared)
        }
        (Some(_), Some(Adoption::Adopted(mut process))) => {
            process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            Ok(SignedRecoveryFenceOutcome::KillRequested)
        }
        (_, Some(Adoption::Rejected)) => unreachable!("rejected adoption is checked before effects"),
        _ => Err(SupervisorError::Invalid(
            "signed recovery Matrix adoption state is inconsistent".to_string(),
        )),
    }
}

fn reconcile_lifecycle_without_process(
    registry: &FleetRegistry,
    agent_id: &AgentId,
) -> Result<(), SupervisorError> {
    let record = registry.load_agent(agent_id)?;
    let target = match record.lifecycle.lifecycle {
        AgentLifecycle::Starting | AgentLifecycle::Running => Some(AgentLifecycle::Failed),
        AgentLifecycle::Draining => Some(AgentLifecycle::Stopped),
        AgentLifecycle::Failed | AgentLifecycle::Stopped => None,
    };
    if let Some(target) = target {
        registry.compare_and_transition(agent_id, record.lifecycle.generation, target)?;
    }
    Ok(())
}

fn require_intent(
    layout: &codex_hepta_paths::HeptaAgentLayout,
    agent_id: &AgentId,
) -> Result<SignedSupervisorIntent, SupervisorError> {
    let intent = read_intent(layout.run_root())
        .map_err(signed_intent_error)?
        .ok_or_else(|| {
            SupervisorError::Invalid(format!(
                "agent {agent_id} has no signed supervisor intent to recover"
            ))
        })?;
    if intent.agent_id != agent_id.to_string() {
        return Err(SupervisorError::Invalid(format!(
            "signed supervisor intent identity {} does not match {agent_id}",
            intent.agent_id
        )));
    }
    Ok(intent)
}

fn ensure_unresolved(intent: &SignedSupervisorIntent) -> Result<(), SupervisorError> {
    if matches!(
        intent.status,
        SignedIntentStatus::Prepared
            | SignedIntentStatus::Queued
            | SignedIntentStatus::RecoveryRequired
    ) {
        Ok(())
    } else {
        Err(SupervisorError::Invalid(format!(
            "signed supervisor intent is already terminal: {:?}",
            intent.status
        )))
    }
}

fn signed_intent_error(error: crate::signed_intent::SignedIntentError) -> SupervisorError {
    SupervisorError::Invalid(format!("signed intent recovery: {error}"))
}

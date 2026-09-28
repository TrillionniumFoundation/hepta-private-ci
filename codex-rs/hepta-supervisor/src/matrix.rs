use std::io::ErrorKind;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::matrix_binding_digest;

use crate::Adoption;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::lease::MATRIX_PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::MatrixProcessLease;
use crate::lease::read_matrix_lease;
use crate::lease::remove_matrix_lease;
use crate::lease::write_matrix_lease;
use crate::restart_journal::unix_millis_now;
use crate::restart_policy::RestartSchedule;
use crate::restart_policy::clear_restart_budget;
use crate::restart_policy::schedule_restart;
use crate::runtime::AgentSlot;
use crate::runtime::DeferredAgentAction;
use crate::runtime::DeferredAgentActionKind;
use crate::runtime::MatrixRuntime;
use crate::runtime::MatrixRuntimePhase;
use crate::runtime::bounded_message;
use crate::runtime::deadline;
use crate::runtime::driver_error;

#[path = "matrix_lease_removal.rs"]
mod lease_removal;
#[path = "matrix_tick.rs"]
mod tick;
pub(crate) use lease_removal::MatrixProcessLeaseRemoval;

const MAX_MATRIX_BINDING_BYTES: u64 = 65_536;
static MATRIX_INCARNATION_SEQUENCE: AtomicU64 = AtomicU64::new(1);

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn start_matrix_companion(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) {
        let Some(release) = slot.active_release.clone() else {
            slot.matrix.configured = false;
            reset_matrix_restart_budget(slot);
            return;
        };
        let Some(command) = release.matrixd_command().cloned() else {
            slot.matrix.configured = false;
            slot.matrix.degraded = false;
            slot.matrix.last_error = None;
            reset_matrix_restart_budget(slot);
            let _ = self.persist_restart_budget(agent_id, slot);
            return;
        };
        slot.matrix.configured = true;
        if slot.matrix.runtime.is_some() || slot.matrix.restart_exhausted {
            return;
        }
        let Some(agent_runtime) = slot.runtime.as_ref() else {
            return;
        };
        if !agent_runtime.healthy
            || !matches!(agent_runtime.phase, crate::runtime::RuntimePhase::Running)
        {
            return;
        }
        // Matrixd connects to agentd with the generation used to spawn that
        // process. The registry's Running lifecycle generation is the next
        // value and must not be passed as the agentd protocol fence.
        let attached_agent_generation = agent_runtime.spawn_generation;
        let record = match self.record(agent_id) {
            Ok(record) => record,
            Err(error) => {
                self.degrade_matrix(
                    agent_id,
                    slot,
                    attached_agent_generation,
                    error.to_string(),
                    now,
                );
                return;
            }
        };
        let binding = match load_binding(&record, agent_id) {
            Ok(Some(binding)) => binding,
            Ok(None) => {
                self.degrade_matrix(
                    agent_id,
                    slot,
                    attached_agent_generation,
                    "Matrix release is configured but public binding is absent".to_string(),
                    now,
                );
                return;
            }
            Err(error) => {
                self.degrade_matrix(
                    agent_id,
                    slot,
                    attached_agent_generation,
                    error.to_string(),
                    now,
                );
                return;
            }
        };
        let binding_digest = match matrix_binding_digest(&binding) {
            Ok(digest) => digest,
            Err(error) => {
                self.degrade_matrix(
                    agent_id,
                    slot,
                    attached_agent_generation,
                    error.to_string(),
                    now,
                );
                return;
            }
        };
        let (process_incarnation, plane_epoch) =
            match next_matrix_incarnation(agent_id, attached_agent_generation, &binding_digest) {
                Ok(identity) => identity,
                Err(error) => {
                    self.degrade_matrix(
                        agent_id,
                        slot,
                        attached_agent_generation,
                        error.to_string(),
                        now,
                    );
                    return;
                }
            };
        match read_matrix_lease(record.layout.matrixd_process_lease()) {
            Ok(None) => {}
            Ok(Some(_)) => {
                self.degrade_matrix(
                    agent_id,
                    slot,
                    attached_agent_generation,
                    "unresolved Matrix process lease".to_string(),
                    now,
                );
                return;
            }
            Err(error) => {
                self.degrade_matrix(
                    agent_id,
                    slot,
                    attached_agent_generation,
                    error.to_string(),
                    now,
                );
                return;
            }
        }
        let spec = MatrixSpawnSpec {
            agent_id: agent_id.clone(),
            agent_generation: attached_agent_generation,
            binding_revision: binding.revision,
            binding_digest: binding_digest.clone(),
            release_id: release.release_id().clone(),
            process_incarnation: process_incarnation.clone(),
            plane_epoch,
            fleet_root: self.registry.layout().fleet_root().as_path().to_path_buf(),
            workspace: record.manifest.workspace.as_path().to_path_buf(),
            matrix_root: record.layout.matrix_root().to_path_buf(),
            control_socket: record.layout.matrixd_control_socket().to_path_buf(),
            agentd_control_socket: record.layout.agentd_control_socket().to_path_buf(),
            logs_root: record.layout.logs_root().to_path_buf(),
            command,
        };
        // No fallible deadline conversion is allowed after acquiring a child.
        let health_deadline = match deadline(now, self.config.health_timeout) {
            Ok(value) => value,
            Err(error) => {
                self.degrade_matrix(
                    agent_id,
                    slot,
                    attached_agent_generation,
                    error.to_string(),
                    now,
                );
                return;
            }
        };
        let spawned = match self.driver.spawn_matrixd(&spec) {
            Ok(spawned) => spawned,
            Err(error) => {
                self.degrade_matrix(
                    agent_id,
                    slot,
                    attached_agent_generation,
                    driver_error(agent_id, error).to_string(),
                    now,
                );
                return;
            }
        };
        let lease = MatrixProcessLease {
            schema_version: MATRIX_PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: agent_id.clone(),
            attached_agent_generation,
            release_id: release.release_id().clone(),
            binding_revision: binding.revision,
            binding_digest: binding_digest.clone(),
            process_incarnation: process_incarnation.clone(),
            plane_epoch,
            identity: spawned.identity.clone(),
        };
        // Own the exact child before publishing its lease.
        slot.matrix.runtime = Some(MatrixRuntime {
            process: spawned.process,
            identity: spawned.identity,
            attached_agent_generation,
            release_id: lease.release_id.clone(),
            binding_revision: binding.revision,
            binding_digest,
            process_incarnation,
            plane_epoch,
            phase: MatrixRuntimePhase::AwaitingHealth {
                deadline: health_deadline,
            },
            healthy: false,
            fenced: false,
        });
        slot.event(
            attached_agent_generation,
            SupervisorEventKind::MatrixSpawned,
        );
        let _ = self.publish_owned_matrix_launch(
            agent_id,
            slot,
            record.layout.matrixd_process_lease(),
            &lease,
            now,
        );
    }

    fn publish_owned_matrix_launch(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        path: &std::path::Path,
        lease: &MatrixProcessLease,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if let Err(error) = write_matrix_lease(path, lease) {
            slot.matrix.exit_lease_removal = Some(
                MatrixProcessLeaseRemoval::for_failed_publication(path, lease),
            );
            if let Some(runtime) = slot.matrix.runtime.as_mut() {
                runtime.healthy = false;
                runtime.fenced = true;
                runtime.phase = MatrixRuntimePhase::Stopping { deadline: now };
            }
            // Attempt termination before any fallible restart-budget I/O.
            if let Err(signal) = self.kill_matrix_now(agent_id, slot) {
                slot.event(
                    lease.attached_agent_generation,
                    SupervisorEventKind::DriverFault(bounded_message(signal.to_string())),
                );
            }
            self.degrade_matrix(
                agent_id,
                slot,
                lease.attached_agent_generation,
                error.to_string(),
                now,
            );
            return Err(error);
        }
        slot.matrix.retry_at = None;
        slot.matrix.restart_exhausted = false;
        Ok(())
    }

    pub(crate) fn recover_matrix_companion(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.matrix.runtime.is_some() {
            return Err(SupervisorError::AlreadyActive(agent_id.clone()));
        }
        let Some(lease) = read_matrix_lease(record.layout.matrixd_process_lease())? else {
            return Ok(());
        };
        if lease.agent_id != *agent_id {
            return Err(SupervisorError::CorruptLease(format!(
                "Matrix lease identity differs from agent {agent_id}"
            )));
        }
        let binding = load_binding(record, agent_id)?.ok_or_else(|| {
            SupervisorError::CorruptLease(
                "Matrix lease exists without a public binding".to_string(),
            )
        })?;
        if binding.revision != lease.binding_revision {
            return Err(SupervisorError::CorruptLease(
                "Matrix lease binding revision is stale".to_string(),
            ));
        }
        let binding_digest = matrix_binding_digest(&binding)
            .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
        if binding_digest != lease.binding_digest {
            return Err(SupervisorError::CorruptLease(
                "Matrix lease binding digest is stale".to_string(),
            ));
        }
        let Some(release) = slot.active_release.as_ref() else {
            return Err(SupervisorError::CorruptLease(
                "Matrix lease exists without an active release".to_string(),
            ));
        };
        if release.release_id() != &lease.release_id || release.matrixd_command().is_none() {
            return Err(SupervisorError::CorruptLease(
                "Matrix lease release is not the active companion bundle".to_string(),
            ));
        }
        let agent_is_exact = slot.runtime.as_ref().is_some_and(|runtime| {
            runtime.spawn_generation == lease.attached_agent_generation
                && runtime.generation == record.lifecycle.generation
                && record.lifecycle.lifecycle == AgentLifecycle::Running
                && !runtime.fenced
                && runtime.release_id == lease.release_id
        });
        let health_deadline = deadline(now, self.config.health_timeout)?;
        let spec = MatrixAdoptSpec {
            agent_id: agent_id.clone(),
            agent_generation: lease.attached_agent_generation,
            binding_revision: lease.binding_revision,
            binding_digest: lease.binding_digest.clone(),
            release_id: lease.release_id.clone(),
            process_incarnation: lease.process_incarnation.clone(),
            plane_epoch: lease.plane_epoch,
            control_socket: record.layout.matrixd_control_socket().to_path_buf(),
            identity: lease.identity.clone(),
        };
        match self
            .driver
            .adopt_matrixd(&spec)
            .map_err(|error| driver_error(agent_id, error))?
        {
            Adoption::Adopted(process) if agent_is_exact => {
                slot.matrix.configured = true;
                slot.matrix.runtime = Some(MatrixRuntime {
                    process,
                    identity: lease.identity,
                    attached_agent_generation: lease.attached_agent_generation,
                    release_id: lease.release_id,
                    binding_revision: lease.binding_revision,
                    binding_digest: lease.binding_digest,
                    process_incarnation: lease.process_incarnation,
                    plane_epoch: lease.plane_epoch,
                    phase: MatrixRuntimePhase::AwaitingHealth {
                        deadline: health_deadline,
                    },
                    healthy: false,
                    fenced: false,
                });
                slot.matrix.degraded = false;
                slot.matrix.restart_exhausted = false;
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::MatrixOrphanAdopted,
                );
            }
            Adoption::Adopted(process) => {
                // Serving eligibility is not ownership. Retain the proven
                // process and its lease until terminal observation and cleanup.
                slot.matrix.configured = true;
                slot.matrix.runtime = Some(MatrixRuntime {
                    process,
                    identity: lease.identity,
                    attached_agent_generation: lease.attached_agent_generation,
                    release_id: lease.release_id,
                    binding_revision: lease.binding_revision,
                    binding_digest: lease.binding_digest,
                    process_incarnation: lease.process_incarnation,
                    plane_epoch: lease.plane_epoch,
                    phase: MatrixRuntimePhase::Stopping { deadline: now },
                    healthy: false,
                    fenced: true,
                });
                let termination = self.kill_matrix_now(agent_id, slot);
                self.degrade_matrix(
                    agent_id,
                    slot,
                    record.lifecycle.generation,
                    "Matrix orphan was attached to a non-running agent generation".to_string(),
                    now,
                );
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::MatrixOrphanRejected,
                );
                termination?;
            }
            Adoption::Missing => {
                remove_matrix_lease(record.layout.matrixd_process_lease(), &lease)?;
                self.degrade_matrix(
                    agent_id,
                    slot,
                    record.lifecycle.generation,
                    "Matrix companion orphan is missing".to_string(),
                    now,
                );
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::MatrixOrphanMissing,
                );
            }
            Adoption::Rejected => {
                remove_matrix_lease(record.layout.matrixd_process_lease(), &lease)?;
                self.degrade_matrix(
                    agent_id,
                    slot,
                    record.lifecycle.generation,
                    "Matrix companion orphan failed exact adoption".to_string(),
                    now,
                );
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::MatrixOrphanRejected,
                );
            }
        }
        Ok(())
    }

    pub(crate) fn defer_agent_action_for_matrix(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        action: DeferredAgentActionKind,
        now: Instant,
    ) -> Result<bool, SupervisorError> {
        let spawn_generation = slot
            .runtime
            .as_ref()
            .map(|runtime| runtime.spawn_generation)
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
        let Some(runtime) = slot.matrix.runtime.as_mut() else {
            return Ok(false);
        };
        let kind = match (slot.deferred_agent_action, action) {
            (Some(existing), next) if existing.spawn_generation == spawn_generation => {
                match (existing.kind, next) {
                    (DeferredAgentActionKind::Stop, _) | (_, DeferredAgentActionKind::Stop) => {
                        DeferredAgentActionKind::Stop
                    }
                    _ => DeferredAgentActionKind::Drain,
                }
            }
            (_, next) => next,
        };
        slot.deferred_agent_action = Some(DeferredAgentAction {
            kind,
            spawn_generation,
        });
        let mut event_generation = None;
        if !matches!(
            runtime.phase,
            MatrixRuntimePhase::Stopping { .. } | MatrixRuntimePhase::Killing
        ) {
            let stop_deadline = deadline(now, self.config.stop_grace)?;
            runtime
                .process
                .request_stop()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.phase = MatrixRuntimePhase::Stopping {
                deadline: stop_deadline,
            };
            event_generation = Some(runtime.attached_agent_generation);
        }
        if let Some(generation) = event_generation {
            slot.event(generation, SupervisorEventKind::MatrixStopRequested);
        }
        Ok(true)
    }

    pub(crate) fn kill_matrix_now(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let Some(runtime) = slot.matrix.runtime.as_mut() else {
            return Ok(());
        };
        runtime.healthy = false;
        runtime.fenced = true;
        let mut event_generation = None;
        if !matches!(runtime.phase, MatrixRuntimePhase::Killing) {
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.phase = MatrixRuntimePhase::Killing;
            event_generation = Some(runtime.attached_agent_generation);
        }
        if let Some(generation) = event_generation {
            slot.event(generation, SupervisorEventKind::MatrixKillRequested);
        }
        Ok(())
    }

    fn degrade_matrix(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
        message: String,
        now: Instant,
    ) {
        let message = bounded_message(message);
        slot.matrix.degraded = true;
        slot.matrix.last_error = Some(message.clone());
        slot.event(generation, SupervisorEventKind::MatrixDegraded(message));
        let wall_now = match unix_millis_now() {
            Ok(wall_now) => wall_now,
            Err(error) => {
                let message = bounded_message(format!(
                    "Matrix restart budget could not read wall clock: {error}"
                ));
                slot.matrix.retry_at = None;
                slot.matrix.restart_exhausted = true;
                slot.matrix.last_error = Some(message.clone());
                slot.event(generation, SupervisorEventKind::MatrixDegraded(message));
                return;
            }
        };
        match schedule_restart(
            &mut slot.matrix.restart_attempt,
            &mut slot.matrix.restart_window_started_at,
            now,
        ) {
            RestartSchedule::Retry { attempt, retry_at } => {
                if attempt == 1 || slot.matrix.restart_window_started_unix_millis.is_none() {
                    slot.matrix.restart_window_started_unix_millis = Some(wall_now);
                }
                slot.matrix.retry_at = Some(retry_at);
                slot.matrix.restart_exhausted = false;
            }
            RestartSchedule::Exhausted { attempts } => {
                slot.matrix.retry_at = None;
                slot.matrix.restart_exhausted = true;
                slot.event(
                    generation,
                    SupervisorEventKind::MatrixRestartBudgetExhausted { attempts },
                );
            }
        }
        if let Err(error) = self.persist_restart_budget(agent_id, slot) {
            let message = bounded_message(format!(
                "Matrix restart budget could not be persisted: {error}"
            ));
            slot.matrix.retry_at = None;
            slot.matrix.restart_exhausted = true;
            slot.matrix.last_error = Some(message.clone());
            slot.event(generation, SupervisorEventKind::MatrixDegraded(message));
        }
    }
}

fn reset_matrix_restart_budget<P>(slot: &mut AgentSlot<P>) {
    clear_restart_budget(
        &mut slot.matrix.restart_attempt,
        &mut slot.matrix.restart_window_started_at,
    );
    slot.matrix.restart_window_started_unix_millis = None;
    slot.matrix.retry_at = None;
    slot.matrix.restart_after_exit = false;
    slot.matrix.restart_exhausted = false;
}

fn load_binding(
    record: &AgentRecord,
    agent_id: &AgentId,
) -> Result<Option<MatrixBindingV1>, SupervisorError> {
    let path = record.layout.matrix_public_binding();
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_MATRIX_BINDING_BYTES
    {
        return Err(SupervisorError::Invalid(format!(
            "Matrix public binding is not a bounded regular file: {}",
            path.display()
        )));
    }
    let binding: MatrixBindingV1 = serde_json::from_slice(&std::fs::read(path)?)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    binding
        .validate()
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    if binding.agent_id != *agent_id {
        return Err(SupervisorError::Invalid(format!(
            "Matrix public binding belongs to {} instead of {agent_id}",
            binding.agent_id
        )));
    }
    Ok(Some(binding))
}

fn next_matrix_incarnation(
    agent_id: &AgentId,
    agent_generation: u64,
    binding_digest: &Sha256Digest,
) -> Result<(String, u64), SupervisorError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let sequence = MATRIX_INCARNATION_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let plane_epoch = u64::try_from(elapsed.as_micros())
        .unwrap_or(u64::MAX)
        .wrapping_add(sequence)
        .max(1);
    let material = serde_json::to_vec(&(
        "hepta.matrix.process-incarnation.v1",
        agent_id.as_str(),
        agent_generation,
        binding_digest.as_str(),
        elapsed.as_nanos().to_string(),
        sequence,
        std::process::id(),
    ))
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    Ok((
        format!("matrixd-{}", Sha256Digest::for_bytes(&material).as_str()),
        plane_epoch,
    ))
}

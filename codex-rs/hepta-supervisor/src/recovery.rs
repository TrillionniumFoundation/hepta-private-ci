use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetAllocationHolderStateV1;
use codex_hepta_fleet::FleetResourceVectorV1;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::AgentRelease;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::SpawnSpec;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::lease::FleetAllocationProcessBinding;
use crate::lease::LEGACY_PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::remove_lease;
use crate::lease::validate_lease;
use crate::lease::write_lease;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;
use crate::runtime::is_live_lifecycle;
use crate::runtime::unix_ms_now;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn restore_release_state(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        slot.release_state_generation = record.release_state.generation;
        slot.active_release = record
            .release_state
            .current
            .as_ref()
            .map(|release_id| self.registry.resolve_release(agent_id, release_id))
            .transpose()?
            .map(AgentRelease::try_from)
            .transpose()?;
        slot.previous_release = record
            .release_state
            .previous
            .as_ref()
            .map(|release_id| self.registry.resolve_release(agent_id, release_id))
            .transpose()?
            .map(AgentRelease::try_from)
            .transpose()?;
        slot.last_command = slot
            .active_release
            .as_ref()
            .map(|release| release.command().clone());
        Ok(())
    }

    pub(crate) fn start_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        command: AgentCommand,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.start_release_slot(agent_id, slot, AgentRelease::unversioned(command)?, now)
    }

    pub(crate) fn start_release_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        release: AgentRelease,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.start_release_slot_with_allocation(
            agent_id,
            slot,
            release,
            None,
            unix_ms_now()?,
            now,
        )
    }

    pub(crate) fn prepare_fleet_allocation_binding(
        &self,
        agent_id: &AgentId,
        allocation_id: &str,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationProcessBinding, SupervisorError> {
        let store = self.allocation_store.as_ref().ok_or_else(|| {
            SupervisorError::Invalid(
                "supervisor has no durable fleet allocation store".to_string(),
            )
        })?;
        let record = self.record(agent_id)?;
        let required = FleetResourceVectorV1::from(&record.manifest.resources);
        let grant = store.validate_runtime_grant(
            allocation_id,
            agent_id,
            required,
            now_unix_ms,
        )?;
        Ok(FleetAllocationProcessBinding {
            allocation_id: grant.allocation_id,
            lease_generation: grant.lease_generation,
            authority_epoch: grant.authority_epoch,
            plan_sha256: grant.plan_sha256,
        })
    }

    pub(crate) fn start_release_slot_with_allocation(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        release: AgentRelease,
        fleet_allocation: Option<FleetAllocationProcessBinding>,
        now_unix_ms: u64,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if let Some(binding) = fleet_allocation.as_ref() {
            self.validate_fleet_allocation_binding(agent_id, binding, now_unix_ms)?;
        }
        let health_deadline = deadline(now, self.config.health_timeout)?;
        if slot.runtime.is_some() {
            return Err(SupervisorError::AlreadyActive(agent_id.clone()));
        }
        let record = self.record(agent_id)?;
        if read_lease(record.layout.run_root())?.is_some() {
            return Err(SupervisorError::UnresolvedLease(agent_id.clone()));
        }
        if !matches!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Stopped | AgentLifecycle::Failed
        ) {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} cannot start from {:?}",
                record.lifecycle.lifecycle
            )));
        }
        let starting = self.registry.compare_and_transition(
            agent_id,
            record.lifecycle.generation,
            AgentLifecycle::Starting,
        )?;
        slot.event(
            starting.generation,
            SupervisorEventKind::Lifecycle(AgentLifecycle::Starting),
        );
        let spec = SpawnSpec {
            agent_id: agent_id.clone(),
            generation: starting.generation,
            fleet_root: self.registry.layout().fleet_root().as_path().to_path_buf(),
            workspace: record.manifest.workspace.as_path().to_path_buf(),
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            logs_root: record.layout.logs_root().to_path_buf(),
            command: release.command().clone(),
        };
        let mut spawned = match self.driver.spawn(&spec) {
            Ok(spawned) => spawned,
            Err(error) => {
                self.transition_without_runtime(
                    agent_id,
                    slot,
                    starting.generation,
                    AgentLifecycle::Failed,
                )?;
                return Err(driver_error(agent_id, error));
            }
        };
        let lease = ProcessLease {
            schema_version: if fleet_allocation.is_some() {
                PROCESS_LEASE_SCHEMA_VERSION
            } else {
                LEGACY_PROCESS_LEASE_SCHEMA_VERSION
            },
            agent_id: agent_id.clone(),
            spawn_generation: starting.generation,
            release_id: release.release_id().clone(),
            identity: spawned.identity.clone(),
            fleet_allocation: fleet_allocation.clone(),
        };
        if let Err(error) = write_lease(record.layout.run_root(), &lease) {
            let _ = spawned.process.kill();
            self.transition_without_runtime(
                agent_id,
                slot,
                starting.generation,
                AgentLifecycle::Failed,
            )?;
            return Err(error);
        }
        slot.last_command = Some(release.command().clone());
        slot.active_release = Some(release);
        slot.runtime = Some(AgentRuntime {
            process: spawned.process,
            identity: spawned.identity,
            spawn_generation: starting.generation,
            release_id: lease.release_id,
            fleet_allocation: fleet_allocation.clone(),
            generation: starting.generation,
            phase: RuntimePhase::AwaitingHealth {
                deadline: health_deadline,
            },
            healthy: false,
            fenced: false,
        });
        slot.event(starting.generation, SupervisorEventKind::Spawned);
        if let Some(binding) = fleet_allocation.as_ref() {
            let store = self.allocation_store.as_ref().ok_or_else(|| {
                SupervisorError::Invalid(
                    "allocation-bound runtime lost its durable fleet owner".to_string(),
                )
            })?;
            store.reconcile_holder_current(
                &binding.allocation_id,
                binding.lease_generation,
                FleetAllocationHolderStateV1::Held,
                now_unix_ms,
            )?;
        }
        Ok(())
    }

    pub(crate) fn recover_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let Some(lease) = read_lease(record.layout.run_root())? else {
            if is_live_lifecycle(record.lifecycle.lifecycle) {
                let generation = self.transition_without_runtime(
                    agent_id,
                    slot,
                    record.lifecycle.generation,
                    AgentLifecycle::Failed,
                )?;
                slot.event(generation, SupervisorEventKind::OrphanMissing);
            }
            self.recover_matrix_companion(agent_id, slot, record, now)?;
            return Ok(());
        };
        validate_lease(
            &lease,
            agent_id,
            record.lifecycle.generation,
            record.lifecycle.lifecycle,
        )?;
        if lease.release_id.as_str() != "unversioned" {
            let needs_resolution = slot
                .active_release
                .as_ref()
                .is_none_or(|active| active.release_id() != &lease.release_id);
            if needs_resolution {
                let leased = AgentRelease::try_from(
                    self.registry.resolve_release(agent_id, &lease.release_id)?,
                )?;
                slot.previous_release = slot.active_release.take();
                slot.last_command = Some(leased.command().clone());
                slot.active_release = Some(leased);
            }
        }
        let spec = AdoptSpec {
            agent_id: agent_id.clone(),
            registry_generation: record.lifecycle.generation,
            spawn_generation: lease.spawn_generation,
            workspace: record.manifest.workspace.as_path().to_path_buf(),
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            identity: lease.identity.clone(),
        };
        match self
            .driver
            .adopt(&spec)
            .map_err(|error| driver_error(agent_id, error))?
        {
            Adoption::Adopted(mut process) => {
                let phase = match record.lifecycle.lifecycle {
                    AgentLifecycle::Starting => RuntimePhase::AwaitingHealth {
                        deadline: deadline(now, self.config.health_timeout)?,
                    },
                    AgentLifecycle::Running => RuntimePhase::Running,
                    AgentLifecycle::Draining => RuntimePhase::Draining {
                        deadline: deadline(now, self.config.drain_timeout)?,
                    },
                    AgentLifecycle::Failed => {
                        process
                            .request_stop()
                            .map_err(|error| driver_error(agent_id, error))?;
                        RuntimePhase::Stopping {
                            deadline: deadline(now, self.config.stop_grace)?,
                        }
                    }
                    AgentLifecycle::Stopped => {
                        process
                            .kill()
                            .map_err(|error| driver_error(agent_id, error))?;
                        RuntimePhase::Killing
                    }
                };
                let fleet_allocation = lease.fleet_allocation.clone();
                slot.runtime = Some(AgentRuntime {
                    process,
                    identity: lease.identity,
                    spawn_generation: lease.spawn_generation,
                    release_id: lease.release_id,
                    fleet_allocation: fleet_allocation.clone(),
                    generation: record.lifecycle.generation,
                    phase,
                    healthy: false,
                    fenced: false,
                });
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::OrphanAdopted,
                );
                if let Some(binding) = fleet_allocation.as_ref() {
                    if let Err(error) =
                        self.validate_fleet_allocation_binding(agent_id, binding, unix_ms_now()?)
                    {
                        if let Some(runtime) = slot.runtime.as_mut() {
                            let _ = runtime.process.kill();
                            runtime.fenced = true;
                            runtime.phase = RuntimePhase::Killing;
                        }
                        return Err(error);
                    }
                    let store = self.allocation_store.as_ref().ok_or_else(|| {
                        SupervisorError::Invalid(
                            "allocation-bound recovered runtime has no durable fleet owner"
                                .to_string(),
                        )
                    })?;
                    store.reconcile_holder_current(
                        &binding.allocation_id,
                        binding.lease_generation,
                        FleetAllocationHolderStateV1::Held,
                        unix_ms_now()?,
                    )?;
                }
                if record.lifecycle.lifecycle == AgentLifecycle::Running {
                    // A daemon can die after committing the Running lifecycle but before
                    // appending the matching release-state revision. The lease and exact
                    // agentd handshake prove the live release; close that crash window now.
                    self.persist_release_state(agent_id, slot)?;
                }
            }
            Adoption::Missing => {
                if let Some(binding) = lease.fleet_allocation.as_ref() {
                    let store = self.allocation_store.as_ref().ok_or_else(|| {
                        SupervisorError::Invalid(
                            "allocation-bound missing runtime has no durable fleet owner".to_string(),
                        )
                    })?;
                    store.reconcile_holder_current(
                        &binding.allocation_id,
                        binding.lease_generation,
                        FleetAllocationHolderStateV1::Released,
                        unix_ms_now()?,
                    )?;
                }
                remove_lease(record.layout.run_root(), &lease)?;
                let generation = if is_live_lifecycle(record.lifecycle.lifecycle) {
                    self.transition_without_runtime(
                        agent_id,
                        slot,
                        record.lifecycle.generation,
                        AgentLifecycle::Failed,
                    )?
                } else {
                    record.lifecycle.generation
                };
                slot.event(generation, SupervisorEventKind::OrphanMissing);
            }
            Adoption::Rejected => {
                if let Some(binding) = lease.fleet_allocation.as_ref() {
                    let store = self.allocation_store.as_ref().ok_or_else(|| {
                        SupervisorError::Invalid(
                            "allocation-bound rejected runtime has no durable fleet owner".to_string(),
                        )
                    })?;
                    store.reconcile_holder_current(
                        &binding.allocation_id,
                        binding.lease_generation,
                        FleetAllocationHolderStateV1::Unknown,
                        unix_ms_now()?,
                    )?;
                }
                remove_lease(record.layout.run_root(), &lease)?;
                let generation = if is_live_lifecycle(record.lifecycle.lifecycle) {
                    self.transition_without_runtime(
                        agent_id,
                        slot,
                        record.lifecycle.generation,
                        AgentLifecycle::Failed,
                    )?
                } else {
                    record.lifecycle.generation
                };
                slot.event(generation, SupervisorEventKind::OrphanRejected);
            }
        }
        self.recover_matrix_companion(agent_id, slot, record, now)?;
        Ok(())
    }

    pub(crate) fn validate_fleet_allocation_binding(
        &self,
        agent_id: &AgentId,
        binding: &FleetAllocationProcessBinding,
        now_unix_ms: u64,
    ) -> Result<(), SupervisorError> {
        let store = self.allocation_store.as_ref().ok_or_else(|| {
            SupervisorError::Invalid(
                "allocation-bound runtime has no durable fleet owner".to_string(),
            )
        })?;
        let record = self.record(agent_id)?;
        let required = FleetResourceVectorV1::from(&record.manifest.resources);
        let grant = store.validate_runtime_grant(
            &binding.allocation_id,
            agent_id,
            required,
            now_unix_ms,
        )?;
        if grant.lease_generation != binding.lease_generation
            || grant.authority_epoch != binding.authority_epoch
            || grant.plan_sha256 != binding.plan_sha256
        {
            return Err(SupervisorError::Invalid(
                "runtime fleet allocation fence no longer matches durable grant".to_string(),
            ));
        }
        Ok(())
    }
}

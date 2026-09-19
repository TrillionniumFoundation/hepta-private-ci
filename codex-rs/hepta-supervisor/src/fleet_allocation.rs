use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_fleet::FleetAllocationGrantV1;
use codex_hepta_fleet::FleetAllocationStore;
use codex_hepta_fleet::FleetConsumptionDispositionV1;
use codex_hepta_fleet::FleetConsumptionObservationV1;
use codex_hepta_fleet::FleetHostObservationV1;
use codex_hepta_fleet::FleetPlacementRequestV1;
use codex_hepta_fleet::FleetPreparedAllocationV1;

use crate::AgentRelease;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;

impl<D: ProcessDriver> Supervisor<D> {
    pub fn admit_fleet_host_observation(
        &self,
        observation: FleetHostObservationV1,
    ) -> Result<(), SupervisorError> {
        FleetAllocationStore::open(&self.registry)
            .and_then(|store| store.admit_host(observation).map(|_| ()))
            .map_err(allocation_error)
    }

    pub fn prepare_fleet_allocation(
        &self,
        principal_id: &str,
        authority_epoch: u64,
        requests: &[FleetPlacementRequestV1],
        lease_lifetime_ms: u64,
        now_unix_ms: u64,
    ) -> Result<FleetPreparedAllocationV1, SupervisorError> {
        FleetAllocationStore::open(&self.registry)
            .and_then(|store| {
                store.prepare_allocation(
                    principal_id,
                    authority_epoch,
                    requests,
                    lease_lifetime_ms,
                    now_unix_ms,
                )
            })
            .map_err(allocation_error)
    }

    pub fn commit_fleet_allocation(
        &self,
        authority: &FinalUseAuthority,
        token: VerifiedUseToken,
        prepared: &FleetPreparedAllocationV1,
        now_unix_ms: u64,
    ) -> Result<Vec<FleetAllocationGrantV1>, SupervisorError> {
        FleetAllocationStore::open(&self.registry)
            .and_then(|store| store.commit_prepared(authority, token, prepared, now_unix_ms))
            .map_err(allocation_error)
    }

    pub fn start_allocated(
        &mut self,
        agent_id: &AgentId,
        allocation_id: &str,
        lease_generation: u64,
        release: AgentRelease,
        now_unix_ms: u64,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        {
            let store = FleetAllocationStore::open(&self.registry).map_err(allocation_error)?;
            store
                .require_active_grant(agent_id, allocation_id, lease_generation, now_unix_ms)
                .map_err(allocation_error)?;
        }
        // The unique physical spawn seam revalidates the same durable grant
        // immediately before spawning and records Holding after the process exists.
        self.start_release(agent_id, release, now)
    }

    pub(crate) fn start_release_consuming_allocation_if_present(
        &mut self,
        agent_id: &AgentId,
        release: AgentRelease,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        // start_release_slot is the single physical spawn seam and performs the
        // allocation lookup/freshness check for every caller, including internal
        // restart/upgrade/rollback paths.
        self.start_release(agent_id, release, now)
    }

    pub(crate) fn current_fleet_allocation_for_start(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<FleetAllocationGrantV1>, SupervisorError> {
        let store = FleetAllocationStore::open(&self.registry).map_err(allocation_error)?;
        let Some(grant) = store
            .active_grant_for_agent(agent_id)
            .map_err(allocation_error)?
        else {
            return Ok(None);
        };
        let now_unix_ms = system_unix_ms()?;
        store
            .require_active_grant(
                agent_id,
                &grant.allocation_id,
                grant.lease_generation,
                now_unix_ms,
            )
            .map(Some)
            .map_err(allocation_error)
    }

    pub(crate) fn observe_fleet_allocation_holding(
        &self,
        agent_id: &AgentId,
        admitted: &FleetAllocationGrantV1,
    ) -> Result<(), SupervisorError> {
        let store = FleetAllocationStore::open(&self.registry).map_err(allocation_error)?;
        let observed_at_unix_ms = system_unix_ms()?;
        let holding = FleetConsumptionObservationV1 {
            allocation_id: admitted.allocation_id.clone(),
            lease_generation: admitted.lease_generation,
            host_generation: admitted.host_generation,
            observed_at_unix_ms,
            observer_id: "runtime.supervisor.spawn".to_string(),
            disposition: FleetConsumptionDispositionV1::Holding,
        };
        if let Err(error) = store.reconcile_consumption(holding) {
            if let Ok(Some(current)) = store.active_grant_for_agent(agent_id) {
                let _ = store.reconcile_consumption(FleetConsumptionObservationV1 {
                    allocation_id: current.allocation_id,
                    lease_generation: current.lease_generation,
                    host_generation: current.host_generation,
                    observed_at_unix_ms,
                    observer_id: "runtime.supervisor.spawn".to_string(),
                    disposition: FleetConsumptionDispositionV1::Indeterminate,
                });
            }
            return Err(allocation_error(error));
        }
        Ok(())
    }

    pub(crate) fn reconcile_fleet_allocation_after_recovery(
        &self,
        agent_id: &AgentId,
        runtime_active: bool,
    ) -> Result<(), SupervisorError> {
        let store = FleetAllocationStore::open(&self.registry).map_err(allocation_error)?;
        let Some(grant) = store
            .active_grant_for_agent(agent_id)
            .map_err(allocation_error)?
        else {
            return Ok(());
        };
        let disposition = if runtime_active {
            FleetConsumptionDispositionV1::Holding
        } else {
            FleetConsumptionDispositionV1::Indeterminate
        };
        store
            .reconcile_consumption(FleetConsumptionObservationV1 {
                allocation_id: grant.allocation_id,
                lease_generation: grant.lease_generation,
                host_generation: grant.host_generation,
                observed_at_unix_ms: system_unix_ms()?,
                observer_id: "runtime.supervisor.recovery".to_string(),
                disposition,
            })
            .map(|_| ())
            .map_err(allocation_error)
    }

    pub(crate) fn release_fleet_allocation_after_exit(
        &self,
        agent_id: &AgentId,
    ) -> Result<(), SupervisorError> {
        let store = FleetAllocationStore::open(&self.registry).map_err(allocation_error)?;
        let Some(grant) = store
            .active_grant_for_agent(agent_id)
            .map_err(allocation_error)?
        else {
            return Ok(());
        };
        store
            .reconcile_consumption(FleetConsumptionObservationV1 {
                allocation_id: grant.allocation_id,
                lease_generation: grant.lease_generation,
                host_generation: grant.host_generation,
                observed_at_unix_ms: system_unix_ms()?,
                observer_id: "runtime.supervisor.exit".to_string(),
                disposition: FleetConsumptionDispositionV1::Released,
            })
            .map(|_| ())
            .map_err(allocation_error)
    }
}

fn system_unix_ms() -> Result<u64, SupervisorError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| SupervisorError::Invalid("system clock precedes Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| SupervisorError::Invalid("system clock exceeds u64 milliseconds".to_string()))
}

fn allocation_error(error: impl std::fmt::Display) -> SupervisorError {
    SupervisorError::Invalid(format!("fleet allocation: {error}"))
}

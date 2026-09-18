use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use thiserror::Error;

use crate::CapacityObservationError;
use crate::CapacityObservationRequestV1;
use crate::FleetAllocationGrantReadV1;
use crate::FleetAllocationStateV1;
use crate::FleetAllocationStore;
use crate::FleetAllocationStoreError;
use crate::FleetCapacityObserver;
use crate::FleetPlacementError;
use crate::FleetPlacementHostV1;
use crate::FleetPlacementRequestV1;
use crate::FleetRegistry;
use crate::FleetResourceVectorV1;
use crate::LocalCapacityPolicyV1;
use crate::LocalSystemCapacityObserver;
use crate::ObservedFleetCapacityV1;
use crate::ResourceBudget;
use crate::calculate_fleet_placement_v1;
use crate::lease_ledger::AllocationGrant;
use crate::lease_ledger::Error as LeaseError;
use crate::lease_ledger::FLEET_LEASE_LEDGER_SCHEMA_VERSION;
use crate::lease_ledger::HostObservation;
use crate::lease_ledger::LeaseDisposition;
use crate::lease_ledger::LeaseLedger;
use crate::lease_ledger::LeaseOutcome;

pub const DEFAULT_RUNTIME_LEASE_TTL_MS: u64 = 20_000;
pub const DEFAULT_RUNTIME_LEASE_RENEW_MARGIN_MS: u64 = 5_000;
pub const DEFAULT_RUNTIME_GRANT_RETENTION_MS: u64 = 300_000;

pub struct FleetRuntimeAllocator {
    store: FleetAllocationStore,
    observer: Box<dyn FleetCapacityObserver>,
    writer_epoch: u64,
    host_id: String,
    failure_domain_id: String,
    lease_ttl_ms: u64,
    renew_margin_ms: u64,
    retention_ms: u64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct FleetMaintenanceReport {
    pub missing_principals: Vec<String>,
    pub renewed: usize,
    pub revoked: usize,
    pub pruned: usize,
}

#[derive(Debug, Error)]
pub enum FleetRuntimeAllocatorError {
    #[error(transparent)]
    Store(#[from] FleetAllocationStoreError),
    #[error(transparent)]
    Capacity(#[from] CapacityObservationError),
    #[error("fleet lease operation failed: {0}")]
    Lease(#[from] LeaseError),
    #[error(transparent)]
    Placement(#[from] FleetPlacementError),
    #[error("fleet allocator binding is invalid: {0}")]
    Invalid(String),
    #[error("fleet allocator canonical encoding failed: {0}")]
    Json(#[from] serde_json::Error),
}

impl FleetRuntimeAllocator {
    pub fn open_local(
        registry: &FleetRegistry,
        writer_epoch: u64,
        now_ms: u64,
        policy: LocalCapacityPolicyV1,
    ) -> Result<Self, FleetRuntimeAllocatorError> {
        let observer = Box::new(LocalSystemCapacityObserver::new(policy)?);
        Self::open_with_observer(registry, writer_epoch, now_ms, observer)
    }

    pub fn open_with_observer(
        registry: &FleetRegistry,
        writer_epoch: u64,
        now_ms: u64,
        observer: Box<dyn FleetCapacityObserver>,
    ) -> Result<Self, FleetRuntimeAllocatorError> {
        if writer_epoch == 0 {
            return Err(FleetRuntimeAllocatorError::Invalid(
                "writer epoch must be non-zero".to_string(),
            ));
        }
        let root_identity = registry
            .layout()
            .fleet_root()
            .as_path()
            .to_string_lossy();
        let root_digest = Sha256Digest::for_bytes(root_identity.as_bytes());
        let host_id = format!("local:{}", &root_digest.as_str()[..32]);
        let failure_domain_id = format!("local:{}", &root_digest.as_str()[32..48]);

        let mut store =
            FleetAllocationStore::open_or_initialize(registry.layout().state_root(), writer_epoch, now_ms)?;
        let mut ledger = store.current().ledger.clone();
        let fenced = ledger.fence_authority_epoch(writer_epoch, now_ms)?;
        if store.current().writer_epoch != writer_epoch || fenced > 0 {
            let revision = store.current().revision;
            store.commit(revision, writer_epoch, now_ms, ledger)?;
        }

        let mut allocator = Self {
            store,
            observer,
            writer_epoch,
            host_id,
            failure_domain_id,
            lease_ttl_ms: DEFAULT_RUNTIME_LEASE_TTL_MS,
            renew_margin_ms: DEFAULT_RUNTIME_LEASE_RENEW_MARGIN_MS,
            retention_ms: DEFAULT_RUNTIME_GRANT_RETENTION_MS,
        };
        allocator.ensure_fresh_capacity(now_ms)?;
        Ok(allocator)
    }

    pub fn state(&self) -> &FleetAllocationStateV1 {
        self.store.current()
    }

    pub fn writer_epoch(&self) -> u64 {
        self.writer_epoch
    }

    pub fn read_grants(&self, now_ms: u64) -> FleetAllocationGrantReadV1 {
        FleetAllocationGrantReadV1::from_state(self.store.current(), self.writer_epoch, now_ms)
    }

    pub fn reserve_agent_start(
        &mut self,
        agent_id: &AgentId,
        budget: &ResourceBudget,
        lifecycle_generation: u64,
        release_id: &str,
        control_state_digest: &str,
        now_ms: u64,
    ) -> Result<AllocationGrant, FleetRuntimeAllocatorError> {
        if lifecycle_generation == 0 {
            return Err(FleetRuntimeAllocatorError::Invalid(
                "runtime start lifecycle generation must be non-zero".to_string(),
            ));
        }
        validate_digest(control_state_digest)?;
        let release_id = crate::ReleaseId::parse(release_id.to_string())
            .map_err(|error| FleetRuntimeAllocatorError::Invalid(error.to_string()))?;
        self.ensure_fresh_capacity(now_ms)?;

        let principal_id = agent_id.to_string();
        let mut ledger = self.store.current().ledger.clone();
        ledger.revoke_principal(&principal_id, now_ms)?;
        let host = ledger
            .host(&self.host_id)
            .cloned()
            .ok_or_else(|| FleetRuntimeAllocatorError::Invalid("local host is absent".to_string()))?;
        let available = ledger.available_resources(&self.host_id, now_ms)?;
        let resources = FleetResourceVectorV1::from(budget);
        let request_id = format!("runtime.start:{agent_id}:{lifecycle_generation}");
        let placement = calculate_fleet_placement_v1(
            &[FleetPlacementHostV1 {
                observation: observed_capacity_from_host(&host)?,
                available,
            }],
            &[FleetPlacementRequestV1 {
                request_id: request_id.clone(),
                agent_id: agent_id.clone(),
                weight: 1,
                minimum: resources,
                desired: resources,
            }],
        )?;
        let assignment = placement
            .assignments
            .first()
            .ok_or_else(|| FleetRuntimeAllocatorError::Invalid("empty placement result".to_string()))?;
        if assignment.resources != resources {
            return Err(FleetRuntimeAllocatorError::Invalid(
                "runtime start must receive its full manifest budget".to_string(),
            ));
        }

        let expires_at_ms = now_ms
            .checked_add(self.lease_ttl_ms)
            .ok_or_else(|| FleetRuntimeAllocatorError::Invalid("lease expiry overflow".to_string()))?
            .min(host.valid_until_ms);
        if expires_at_ms <= now_ms {
            return Err(FleetRuntimeAllocatorError::Lease(LeaseError::StaleHost));
        }
        let semantic_digest = grant_digest(
            &request_id,
            &principal_id,
            &host,
            self.writer_epoch,
            lifecycle_generation,
            release_id.as_str(),
            control_state_digest,
            resources,
        )?;
        let next_state_revision = self
            .store
            .current()
            .revision
            .checked_add(1)
            .ok_or_else(|| FleetRuntimeAllocatorError::Invalid("allocation revision overflow".to_string()))?;
        let allocation_id = format!(
            "runtime:{agent_id}:{lifecycle_generation}:{}:{next_state_revision}",
            self.writer_epoch
        );
        let grant = AllocationGrant {
            schema_version: FLEET_LEASE_LEDGER_SCHEMA_VERSION,
            allocation_id: allocation_id.clone(),
            request_id,
            principal_id,
            host_id: assignment.host_id.clone(),
            failure_domain_id: assignment.failure_domain_id.clone(),
            host_generation: host.generation,
            host_observation_revision: host.observation_revision,
            authority_epoch: self.writer_epoch,
            lease_generation: 1,
            predecessor_lease_generation: None,
            issued_at_ms: now_ms,
            expires_at_ms,
            resources: assignment.resources,
            semantic_digest,
            revoked: false,
            revoked_at_ms: None,
        };
        ledger.issue(now_ms, grant)?;
        ledger.prune_inactive(now_ms, self.retention_ms)?;
        self.commit_ledger(now_ms, ledger)?;
        self.store
            .current()
            .ledger
            .get(&allocation_id)
            .cloned()
            .ok_or_else(|| {
                FleetRuntimeAllocatorError::Invalid(
                    "committed allocation grant cannot be reloaded".to_string(),
                )
            })
    }

    pub fn release_agent(
        &mut self,
        agent_id: &AgentId,
        now_ms: u64,
    ) -> Result<usize, FleetRuntimeAllocatorError> {
        let mut ledger = self.store.current().ledger.clone();
        let revoked = ledger.revoke_principal(agent_id.as_str(), now_ms)?;
        let pruned = ledger.prune_inactive(now_ms, self.retention_ms)?;
        if revoked > 0 || pruned > 0 {
            self.commit_ledger(now_ms, ledger)?;
        }
        Ok(revoked)
    }

    pub fn maintain(
        &mut self,
        active_principals: &[String],
        now_ms: u64,
    ) -> Result<FleetMaintenanceReport, FleetRuntimeAllocatorError> {
        self.ensure_fresh_capacity(now_ms)?;
        let active: BTreeSet<_> = active_principals.iter().map(String::as_str).collect();
        let mut ledger = self.store.current().ledger.clone();
        let mut report = FleetMaintenanceReport::default();
        let current_grants: Vec<_> = ledger
            .grants()
            .filter(|grant| {
                !grant.revoked
                    && grant.expires_at_ms > now_ms
                    && grant.authority_epoch == self.writer_epoch
            })
            .cloned()
            .collect();

        for grant in current_grants {
            if !active.contains(grant.principal_id.as_str()) {
                report.revoked += ledger.revoke_principal(&grant.principal_id, now_ms)?;
                continue;
            }
            let renew_at = now_ms
                .checked_add(self.renew_margin_ms)
                .ok_or_else(|| FleetRuntimeAllocatorError::Invalid("renewal time overflow".to_string()))?;
            if grant.expires_at_ms <= renew_at {
                let host = ledger
                    .host(&grant.host_id)
                    .ok_or(LeaseError::HostNotFound)?;
                let expires_at_ms = now_ms
                    .checked_add(self.lease_ttl_ms)
                    .ok_or_else(|| FleetRuntimeAllocatorError::Invalid("lease expiry overflow".to_string()))?
                    .min(host.valid_until_ms);
                let receipt = ledger.renew_or_revoke(
                    now_ms,
                    &grant.allocation_id,
                    grant.lease_generation,
                    grant.authority_epoch,
                    &grant.semantic_digest,
                    LeaseDisposition::Renew { expires_at_ms },
                )?;
                if receipt.outcome == LeaseOutcome::Renewed {
                    report.renewed += 1;
                }
            }
        }

        for principal in &active {
            let present = ledger
                .grant_for_principal(principal, now_ms)
                .is_some_and(|grant| grant.authority_epoch == self.writer_epoch);
            if !present {
                report.missing_principals.push((*principal).to_string());
            }
        }
        report.missing_principals.sort();

        report.pruned = ledger.prune_inactive(now_ms, self.retention_ms)?;
        let host = ledger
            .host(&self.host_id)
            .ok_or(LeaseError::HostNotFound)?;
        let committed = ledger.committed_resources(&self.host_id, now_ms)?;
        if !committed.fits(host.capacity) {
            return Err(FleetRuntimeAllocatorError::Lease(LeaseError::CapacityExceeded));
        }
        if report.renewed > 0 || report.revoked > 0 || report.pruned > 0 {
            self.commit_ledger(now_ms, ledger)?;
        }
        Ok(report)
    }

    fn ensure_fresh_capacity(&mut self, now_ms: u64) -> Result<(), FleetRuntimeAllocatorError> {
        let required_until = now_ms
            .checked_add(self.lease_ttl_ms)
            .and_then(|value| value.checked_add(self.renew_margin_ms))
            .ok_or_else(|| {
                FleetRuntimeAllocatorError::Invalid("capacity freshness overflow".to_string())
            })?;
        if self
            .store
            .current()
            .ledger
            .host(&self.host_id)
            .is_some_and(|host| {
                host.generation == self.writer_epoch && host.valid_until_ms >= required_until
            })
        {
            return Ok(());
        }

        let observation_revision = self
            .store
            .current()
            .ledger
            .host(&self.host_id)
            .filter(|host| host.generation == self.writer_epoch)
            .map(|host| host.observation_revision)
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| {
                FleetRuntimeAllocatorError::Invalid(
                    "capacity observation revision overflow".to_string(),
                )
            })?;
        let observed = self.observer.observe(&CapacityObservationRequestV1 {
            host_id: self.host_id.clone(),
            failure_domain_id: self.failure_domain_id.clone(),
            host_generation: self.writer_epoch,
            observation_revision,
            now_ms,
        })?;
        observed.validate(now_ms)?;
        if observed.host_id != self.host_id
            || observed.failure_domain_id != self.failure_domain_id
            || observed.host_generation != self.writer_epoch
            || observed.observation_revision != observation_revision
        {
            return Err(FleetRuntimeAllocatorError::Invalid(
                "capacity observer changed the requested identity".to_string(),
            ));
        }

        let mut ledger = self.store.current().ledger.clone();
        ledger.admit_host(HostObservation {
            schema_version: FLEET_LEASE_LEDGER_SCHEMA_VERSION,
            host_id: observed.host_id,
            failure_domain_id: observed.failure_domain_id,
            generation: observed.host_generation,
            observation_revision: observed.observation_revision,
            observed_at_ms: observed.observed_at_ms,
            valid_until_ms: observed.valid_until_ms,
            capacity: observed.capacity,
            semantic_digest: observed.observation_digest.as_str().to_string(),
        })?;
        self.commit_ledger(now_ms, ledger)?;
        Ok(())
    }

    fn commit_ledger(
        &mut self,
        now_ms: u64,
        ledger: LeaseLedger,
    ) -> Result<(), FleetRuntimeAllocatorError> {
        let revision = self.store.current().revision;
        self.store
            .commit(revision, self.writer_epoch, now_ms, ledger)?;
        Ok(())
    }
}

fn observed_capacity_from_host(
    host: &HostObservation,
) -> Result<ObservedFleetCapacityV1, FleetRuntimeAllocatorError> {
    let observed = ObservedFleetCapacityV1::new(
        host.host_id.clone(),
        host.failure_domain_id.clone(),
        host.generation,
        host.observation_revision,
        host.observed_at_ms,
        host.valid_until_ms,
        host.capacity,
    )?;
    if observed.observation_digest.as_str() != host.semantic_digest {
        return Err(FleetRuntimeAllocatorError::Invalid(
            "stored capacity observation digest mismatch".to_string(),
        ));
    }
    Ok(observed)
}

fn grant_digest(
    request_id: &str,
    principal_id: &str,
    host: &HostObservation,
    authority_epoch: u64,
    lifecycle_generation: u64,
    release_id: &str,
    control_state_digest: &str,
    resources: FleetResourceVectorV1,
) -> Result<String, FleetRuntimeAllocatorError> {
    #[derive(Serialize)]
    struct DigestInput<'a> {
        domain: &'static str,
        request_id: &'a str,
        principal_id: &'a str,
        host_id: &'a str,
        failure_domain_id: &'a str,
        host_generation: u64,
        host_observation_revision: u64,
        host_observation_digest: &'a str,
        authority_epoch: u64,
        lifecycle_generation: u64,
        release_id: &'a str,
        control_state_digest: &'a str,
        resources: FleetResourceVectorV1,
    }

    let bytes = serde_json::to_vec(&DigestInput {
        domain: "hepta.runtime-fleet.runtime-grant.v1",
        request_id,
        principal_id,
        host_id: &host.host_id,
        failure_domain_id: &host.failure_domain_id,
        host_generation: host.generation,
        host_observation_revision: host.observation_revision,
        host_observation_digest: &host.semantic_digest,
        authority_epoch,
        lifecycle_generation,
        release_id,
        control_state_digest,
        resources,
    })?;
    Ok(Sha256Digest::for_bytes(&bytes).as_str().to_string())
}

fn validate_digest(value: &str) -> Result<(), FleetRuntimeAllocatorError> {
    Sha256Digest::parse(value.to_string())
        .map(|_| ())
        .map_err(FleetRuntimeAllocatorError::Invalid)
}

#[cfg(test)]
#[path = "runtime_allocator_tests.rs"]
mod tests;

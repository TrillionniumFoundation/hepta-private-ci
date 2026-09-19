use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::VerifiedUseToken;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::FleetPlacementRequestV1;
use crate::FleetRegistry;
use crate::FleetResourceVectorV1;
use crate::LocalAllocationError;
use crate::LocalHostCapacityCandidateV1;
use crate::place_and_allocate_v1;

pub const FLEET_ALLOCATION_STORE_SCHEMA_VERSION: u32 = 1;
pub const FLEET_ALLOCATION_GRANT_SCHEMA_VERSION: u32 = 1;
pub const FLEET_HOST_OBSERVATION_SCHEMA_VERSION: u32 = 1;
const MAX_HOSTS: usize = 256;
const MAX_ACTIVE_GRANTS: usize = 16_384;
const MAX_TERMINAL_GRANTS: usize = 16_384;
const MAX_SNAPSHOT_BYTES: u64 = 16 * 1024 * 1024;
const SNAPSHOT_RETAIN: u64 = 3;
const STORE_DIRECTORY: &str = "fleet-allocation-v1";
const LOCK_FILE: &str = "writer.lock";
const SNAPSHOT_PREFIX: &str = "snapshot-";
const SNAPSHOT_SUFFIX: &str = ".json";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetCapacityObservationSourceV1 {
    LocalKernel,
    EnrolledHostAdapter,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetHostObservationV1 {
    pub schema_version: u32,
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
    pub revision: u64,
    pub observed_at_unix_ms: u64,
    pub valid_until_unix_ms: u64,
    pub source: FleetCapacityObservationSourceV1,
    pub capacity: FleetResourceVectorV1,
    pub observation_sha256: Sha256Digest,
}

impl FleetHostObservationV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        host_id: String,
        failure_domain_id: String,
        generation: u64,
        revision: u64,
        observed_at_unix_ms: u64,
        valid_until_unix_ms: u64,
        source: FleetCapacityObservationSourceV1,
        capacity: FleetResourceVectorV1,
    ) -> Result<Self, FleetAllocationStoreError> {
        let mut value = Self {
            schema_version: FLEET_HOST_OBSERVATION_SCHEMA_VERSION,
            host_id,
            failure_domain_id,
            generation,
            revision,
            observed_at_unix_ms,
            valid_until_unix_ms,
            source,
            capacity,
            observation_sha256: Sha256Digest::for_bytes(b"uninitialized"),
        };
        value.observation_sha256 = value.compute_digest()?;
        value.validate()?;
        Ok(value)
    }

    fn validate(&self) -> Result<(), FleetAllocationStoreError> {
        if self.schema_version != FLEET_HOST_OBSERVATION_SCHEMA_VERSION
            || !identifier(&self.host_id)
            || !identifier(&self.failure_domain_id)
            || self.generation == 0
            || self.revision == 0
            || self.observed_at_unix_ms >= self.valid_until_unix_ms
            || self.capacity.is_zero()
            || self.compute_digest()? != self.observation_sha256
        {
            return Err(FleetAllocationStoreError::InvalidHostObservation);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, FleetAllocationStoreError> {
        #[derive(Serialize)]
        struct Input<'a> {
            domain: &'static str,
            schema_version: u32,
            host_id: &'a str,
            failure_domain_id: &'a str,
            generation: u64,
            revision: u64,
            observed_at_unix_ms: u64,
            valid_until_unix_ms: u64,
            source: FleetCapacityObservationSourceV1,
            capacity: FleetResourceVectorV1,
        }
        digest_json(&Input {
            domain: "hepta.runtime-fleet.host-observation.v1",
            schema_version: self.schema_version,
            host_id: &self.host_id,
            failure_domain_id: &self.failure_domain_id,
            generation: self.generation,
            revision: self.revision,
            observed_at_unix_ms: self.observed_at_unix_ms,
            valid_until_unix_ms: self.valid_until_unix_ms,
            source: self.source,
            capacity: self.capacity,
        })
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetHolderDispositionV1 {
    Pending,
    Holding,
    Released,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetAllocationGrantV1 {
    pub schema_version: u32,
    pub allocation_id: String,
    pub request_id: String,
    pub principal_id: String,
    pub agent_id: AgentId,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub host_observation_revision: u64,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub predecessor_allocation_id: Option<String>,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub resources: FleetResourceVectorV1,
    pub revoked: bool,
    pub holder: FleetHolderDispositionV1,
    pub semantic_digest: Sha256Digest,
}

impl FleetAllocationGrantV1 {
    fn validate(&self) -> Result<(), FleetAllocationStoreError> {
        if self.schema_version != FLEET_ALLOCATION_GRANT_SCHEMA_VERSION
            || !identifier(&self.allocation_id)
            || !identifier(&self.request_id)
            || !identifier(&self.principal_id)
            || !identifier(&self.host_id)
            || !identifier(&self.failure_domain_id)
            || self.host_generation == 0
            || self.host_observation_revision == 0
            || self.authority_epoch == 0
            || self.lease_generation == 0
            || self.issued_at_unix_ms >= self.expires_at_unix_ms
            || self.resources.is_zero()
            || self
                .predecessor_allocation_id
                .as_ref()
                .is_some_and(|id| !identifier(id))
            || self.compute_digest()? != self.semantic_digest
        {
            return Err(FleetAllocationStoreError::InvalidGrant);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, FleetAllocationStoreError> {
        #[derive(Serialize)]
        struct Input<'a> {
            domain: &'static str,
            schema_version: u32,
            allocation_id: &'a str,
            request_id: &'a str,
            principal_id: &'a str,
            agent_id: &'a AgentId,
            host_id: &'a str,
            failure_domain_id: &'a str,
            host_generation: u64,
            host_observation_revision: u64,
            authority_epoch: u64,
            lease_generation: u64,
            predecessor_allocation_id: &'a Option<String>,
            issued_at_unix_ms: u64,
            expires_at_unix_ms: u64,
            resources: FleetResourceVectorV1,
        }
        digest_json(&Input {
            domain: "hepta.runtime-fleet.allocation-grant.v1",
            schema_version: self.schema_version,
            allocation_id: &self.allocation_id,
            request_id: &self.request_id,
            principal_id: &self.principal_id,
            agent_id: &self.agent_id,
            host_id: &self.host_id,
            failure_domain_id: &self.failure_domain_id,
            host_generation: self.host_generation,
            host_observation_revision: self.host_observation_revision,
            authority_epoch: self.authority_epoch,
            lease_generation: self.lease_generation,
            predecessor_allocation_id: &self.predecessor_allocation_id,
            issued_at_unix_ms: self.issued_at_unix_ms,
            expires_at_unix_ms: self.expires_at_unix_ms,
            resources: self.resources,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPreparedAllocationV1 {
    pub store_revision: u64,
    pub principal_id: String,
    pub authority_epoch: u64,
    pub prepared_at_unix_ms: u64,
    pub plan_sha256: Sha256Digest,
    pub final_use_binding: FinalUseBinding,
    pub grants: Vec<FleetAllocationGrantV1>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetConsumptionDispositionV1 {
    Holding,
    Released,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetConsumptionObservationV1 {
    pub allocation_id: String,
    pub lease_generation: u64,
    pub host_generation: u64,
    pub observed_at_unix_ms: u64,
    pub observer_id: String,
    pub disposition: FleetConsumptionDispositionV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetAllocationStoreSnapshotV1 {
    pub schema_version: u32,
    pub revision: u64,
    pub hosts: BTreeMap<String, FleetHostObservationV1>,
    pub grants: BTreeMap<String, FleetAllocationGrantV1>,
    pub terminal_grants: BTreeMap<String, FleetAllocationGrantV1>,
    pub terminal_frontier: u64,
}

impl FleetAllocationStoreSnapshotV1 {
    fn empty() -> Self {
        Self {
            schema_version: FLEET_ALLOCATION_STORE_SCHEMA_VERSION,
            revision: 0,
            hosts: BTreeMap::new(),
            grants: BTreeMap::new(),
            terminal_grants: BTreeMap::new(),
            terminal_frontier: 0,
        }
    }

    fn validate(&self) -> Result<(), FleetAllocationStoreError> {
        if self.schema_version != FLEET_ALLOCATION_STORE_SCHEMA_VERSION
            || self.hosts.len() > MAX_HOSTS
            || self.grants.len() > MAX_ACTIVE_GRANTS
            || self.terminal_grants.len() > MAX_TERMINAL_GRANTS
        {
            return Err(FleetAllocationStoreError::CorruptStore);
        }
        let mut agents = BTreeMap::<AgentId, String>::new();
        for (id, host) in &self.hosts {
            host.validate()?;
            if id != &host.host_id {
                return Err(FleetAllocationStoreError::CorruptStore);
            }
        }
        for (id, grant) in &self.grants {
            grant.validate()?;
            if id != &grant.allocation_id || grant.holder == FleetHolderDispositionV1::Released {
                return Err(FleetAllocationStoreError::CorruptStore);
            }
            if agents
                .insert(grant.agent_id.clone(), grant.allocation_id.clone())
                .is_some()
            {
                return Err(FleetAllocationStoreError::CorruptStore);
            }
            let host = self
                .hosts
                .get(&grant.host_id)
                .ok_or(FleetAllocationStoreError::CorruptStore)?;
            if host.generation != grant.host_generation
                || host.revision < grant.host_observation_revision
                || host.failure_domain_id != grant.failure_domain_id
            {
                return Err(FleetAllocationStoreError::CorruptStore);
            }
        }
        for (id, grant) in &self.terminal_grants {
            grant.validate()?;
            if id != &grant.allocation_id || grant.holder != FleetHolderDispositionV1::Released {
                return Err(FleetAllocationStoreError::CorruptStore);
            }
        }
        for host in self.hosts.values() {
            let committed = committed_resources(self, &host.host_id)?;
            if !committed.fits_within(host.capacity) {
                return Err(FleetAllocationStoreError::CorruptStore);
            }
        }
        Ok(())
    }
}

pub struct FleetAllocationStore {
    root: PathBuf,
    registry: FleetRegistry,
    _lock: File,
}

impl FleetAllocationStore {
    pub fn open(registry: &FleetRegistry) -> Result<Self, FleetAllocationStoreError> {
        let root = registry.layout().state_root().join(STORE_DIRECTORY);
        prepare_store_root(&root)?;
        let lock = open_writer_lock(&root)?;
        lock.try_lock()
            .map_err(|_| FleetAllocationStoreError::WriterBusy)?;
        cleanup_incomplete_snapshots(&root)?;
        let store = Self {
            root,
            registry: registry.clone(),
            _lock: lock,
        };
        if store.latest_revision()?.is_none() {
            store.write_snapshot(&FleetAllocationStoreSnapshotV1::empty())?;
        }
        store.load()?;
        Ok(store)
    }

    pub fn load(
        &self,
    ) -> Result<FleetAllocationStoreSnapshotV1, FleetAllocationStoreError> {
        let revision = self
            .latest_revision()?
            .ok_or(FleetAllocationStoreError::CorruptStore)?;
        let path = self.snapshot_path(revision);
        let metadata = fs::symlink_metadata(&path)?;
        if !metadata.file_type().is_file()
            || metadata.file_type().is_symlink()
            || metadata.len() > MAX_SNAPSHOT_BYTES
        {
            return Err(FleetAllocationStoreError::CorruptStore);
        }
        let bytes = fs::read(path)?;
        let state: FleetAllocationStoreSnapshotV1 =
            serde_json::from_slice(&bytes).map_err(|_| FleetAllocationStoreError::CorruptStore)?;
        if state.revision != revision {
            return Err(FleetAllocationStoreError::CorruptStore);
        }
        state.validate()?;
        Ok(state)
    }

    pub fn admit_host(
        &self,
        observation: FleetHostObservationV1,
    ) -> Result<FleetAllocationStoreSnapshotV1, FleetAllocationStoreError> {
        observation.validate()?;
        let mut state = self.load()?;
        match state.hosts.get(&observation.host_id) {
            None => {
                if state.hosts.len() >= MAX_HOSTS || observation.revision != 1 {
                    return Err(FleetAllocationStoreError::HostCapacityExceeded);
                }
            }
            Some(current) if observation == *current => return Ok(state),
            Some(current) if observation.generation == current.generation => {
                if observation.revision != current.revision.saturating_add(1)
                    || observation.failure_domain_id != current.failure_domain_id
                    || observation.observed_at_unix_ms < current.observed_at_unix_ms
                {
                    return Err(FleetAllocationStoreError::StaleHostObservation);
                }
                let committed = committed_resources(&state, &observation.host_id)?;
                if !committed.fits_within(observation.capacity) {
                    return Err(FleetAllocationStoreError::CapacityExceeded);
                }
            }
            Some(current) => {
                if observation.generation != current.generation.saturating_add(1)
                    || observation.revision != 1
                    || state
                        .grants
                        .values()
                        .any(|grant| grant.host_id == observation.host_id)
                {
                    return Err(FleetAllocationStoreError::StaleHostObservation);
                }
            }
        }
        state
            .hosts
            .insert(observation.host_id.clone(), observation);
        self.commit_state(state)
    }

    pub fn prepare_allocation(
        &self,
        principal_id: &str,
        authority_epoch: u64,
        requests: &[FleetPlacementRequestV1],
        lease_lifetime_ms: u64,
        now_unix_ms: u64,
    ) -> Result<FleetPreparedAllocationV1, FleetAllocationStoreError> {
        if !identifier(principal_id)
            || authority_epoch == 0
            || lease_lifetime_ms == 0
            || lease_lifetime_ms > 300_000
        {
            return Err(FleetAllocationStoreError::InvalidRequest);
        }
        let expires_at_unix_ms = now_unix_ms
            .checked_add(lease_lifetime_ms)
            .ok_or(FleetAllocationStoreError::ArithmeticOverflow)?;
        let state = self.load()?;
        let roster = self
            .registry
            .load()
            .map_err(|error| FleetAllocationStoreError::Registry(error.to_string()))?;

        for request in requests {
            let record = roster
                .agent(&request.agent_id)
                .ok_or_else(|| FleetAllocationStoreError::UnknownAgent(request.agent_id.clone()))?;
            let manifest_budget = FleetResourceVectorV1::from_manifest_budget(&record.manifest.resources);
            if !request.minimum.fits_within(manifest_budget)
                || !request.desired.fits_within(manifest_budget)
            {
                return Err(FleetAllocationStoreError::AgentBudgetExceeded(
                    request.agent_id.clone(),
                ));
            }
            if state
                .grants
                .values()
                .any(|grant| grant.agent_id == request.agent_id)
            {
                return Err(FleetAllocationStoreError::Conflict);
            }
        }

        let mut candidates = Vec::new();
        for host in state.hosts.values() {
            if now_unix_ms < host.observed_at_unix_ms
                || now_unix_ms >= host.valid_until_unix_ms
                || expires_at_unix_ms > host.valid_until_unix_ms
                || host_is_quarantined(&state, &host.host_id, now_unix_ms)
            {
                continue;
            }
            let committed = committed_resources(&state, &host.host_id)?;
            let available = host
                .capacity
                .checked_sub(committed)
                .ok_or(FleetAllocationStoreError::CorruptStore)?;
            if available.is_zero() {
                continue;
            }
            candidates.push(LocalHostCapacityCandidateV1 {
                host_id: host.host_id.clone(),
                failure_domain_id: host.failure_domain_id.clone(),
                caller_supplied_allocatable: available,
            });
        }

        let plan = place_and_allocate_v1(&candidates, requests)?;
        let mut grants = Vec::with_capacity(plan.assignments.len());
        for assignment in &plan.assignments {
            let host = state
                .hosts
                .get(&assignment.host_id)
                .ok_or(FleetAllocationStoreError::StaleHostObservation)?;
            let predecessor = latest_terminal_for_agent(&state, &assignment.agent_id)
                .map(|grant| grant.allocation_id.clone());
            let mut grant = FleetAllocationGrantV1 {
                schema_version: FLEET_ALLOCATION_GRANT_SCHEMA_VERSION,
                allocation_id: assignment.allocation_id.clone(),
                request_id: assignment.request_id.clone(),
                principal_id: principal_id.to_string(),
                agent_id: assignment.agent_id.clone(),
                host_id: assignment.host_id.clone(),
                failure_domain_id: assignment.failure_domain_id.clone(),
                host_generation: host.generation,
                host_observation_revision: host.revision,
                authority_epoch,
                lease_generation: 1,
                predecessor_allocation_id: predecessor,
                issued_at_unix_ms: now_unix_ms,
                expires_at_unix_ms,
                resources: assignment.resources,
                revoked: false,
                holder: FleetHolderDispositionV1::Pending,
                semantic_digest: Sha256Digest::for_bytes(b"uninitialized"),
            };
            grant.semantic_digest = grant.compute_digest()?;
            grant.validate()?;
            grants.push(grant);
        }
        let final_use_binding =
            allocation_final_use_binding(principal_id, authority_epoch, state.revision, requests, &grants)?;
        Ok(FleetPreparedAllocationV1 {
            store_revision: state.revision,
            principal_id: principal_id.to_string(),
            authority_epoch,
            prepared_at_unix_ms: now_unix_ms,
            plan_sha256: plan.plan_sha256,
            final_use_binding,
            grants,
        })
    }

    pub fn commit_prepared(
        &self,
        authority: &FinalUseAuthority,
        token: VerifiedUseToken,
        prepared: &FleetPreparedAllocationV1,
        now_unix_ms: u64,
    ) -> Result<Vec<FleetAllocationGrantV1>, FleetAllocationStoreError> {
        if token.authority_epoch() != prepared.authority_epoch {
            return Err(FleetAllocationStoreError::AuthorityEpochMismatch);
        }
        authority
            .with_verified_use(token, &prepared.final_use_binding, || {
                self.commit_prepared_inner(prepared, now_unix_ms)
            })
            .map_err(FleetAllocationStoreError::Authority)?
    }

    pub fn active_grant_for_agent(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<FleetAllocationGrantV1>, FleetAllocationStoreError> {
        let state = self.load()?;
        let mut found = state
            .grants
            .values()
            .filter(|grant| &grant.agent_id == agent_id);
        let first = found.next().cloned();
        if found.next().is_some() {
            return Err(FleetAllocationStoreError::CorruptStore);
        }
        Ok(first)
    }

    pub fn require_active_grant(
        &self,
        agent_id: &AgentId,
        allocation_id: &str,
        lease_generation: u64,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationGrantV1, FleetAllocationStoreError> {
        let state = self.load()?;
        let grant = state
            .grants
            .get(allocation_id)
            .cloned()
            .ok_or(FleetAllocationStoreError::AllocationNotFound)?;
        if &grant.agent_id != agent_id
            || grant.lease_generation != lease_generation
            || grant.revoked
            || grant.expires_at_unix_ms <= now_unix_ms
            || grant.holder == FleetHolderDispositionV1::Indeterminate
            || grant.holder == FleetHolderDispositionV1::Released
        {
            return Err(FleetAllocationStoreError::GrantNotUsable);
        }
        let host = state
            .hosts
            .get(&grant.host_id)
            .ok_or(FleetAllocationStoreError::StaleHostObservation)?;
        if host.generation != grant.host_generation
            || host.revision < grant.host_observation_revision
            || now_unix_ms >= host.valid_until_unix_ms
        {
            return Err(FleetAllocationStoreError::StaleHostObservation);
        }
        Ok(grant)
    }

    pub fn reconcile_consumption(
        &self,
        observation: FleetConsumptionObservationV1,
    ) -> Result<FleetAllocationGrantV1, FleetAllocationStoreError> {
        if !identifier(&observation.allocation_id)
            || !identifier(&observation.observer_id)
            || observation.lease_generation == 0
            || observation.host_generation == 0
        {
            return Err(FleetAllocationStoreError::InvalidObservation);
        }
        let mut state = self.load()?;
        let mut grant = state
            .grants
            .get(&observation.allocation_id)
            .cloned()
            .ok_or(FleetAllocationStoreError::AllocationNotFound)?;
        if grant.lease_generation != observation.lease_generation
            || grant.host_generation != observation.host_generation
            || observation.observed_at_unix_ms < grant.issued_at_unix_ms
        {
            return Err(FleetAllocationStoreError::StaleLease);
        }

        match observation.disposition {
            FleetConsumptionDispositionV1::Holding => {
                if grant.revoked || grant.expires_at_unix_ms <= observation.observed_at_unix_ms {
                    return Err(FleetAllocationStoreError::GrantNotUsable);
                }
                grant.holder = FleetHolderDispositionV1::Holding;
                state
                    .grants
                    .insert(grant.allocation_id.clone(), grant.clone());
            }
            FleetConsumptionDispositionV1::Indeterminate => {
                grant.holder = FleetHolderDispositionV1::Indeterminate;
                state
                    .grants
                    .insert(grant.allocation_id.clone(), grant.clone());
            }
            FleetConsumptionDispositionV1::Released => {
                state.grants.remove(&grant.allocation_id);
                grant.holder = FleetHolderDispositionV1::Released;
                compact_terminal(&mut state);
                state
                    .terminal_grants
                    .insert(grant.allocation_id.clone(), grant.clone());
                state.terminal_frontier = state
                    .terminal_frontier
                    .checked_add(1)
                    .ok_or(FleetAllocationStoreError::ArithmeticOverflow)?;
            }
        }
        self.commit_state(state)?;
        Ok(grant)
    }

    pub fn revoke(
        &self,
        allocation_id: &str,
        expected_lease_generation: u64,
    ) -> Result<FleetAllocationGrantV1, FleetAllocationStoreError> {
        let mut state = self.load()?;
        let grant = state
            .grants
            .get_mut(allocation_id)
            .ok_or(FleetAllocationStoreError::AllocationNotFound)?;
        if grant.lease_generation != expected_lease_generation {
            return Err(FleetAllocationStoreError::StaleLease);
        }
        if grant.revoked {
            return Ok(grant.clone());
        }
        grant.revoked = true;
        grant.lease_generation = grant
            .lease_generation
            .checked_add(1)
            .ok_or(FleetAllocationStoreError::ArithmeticOverflow)?;
        grant.semantic_digest = grant.compute_digest()?;
        let result = grant.clone();
        self.commit_state(state)?;
        Ok(result)
    }

    pub fn renew_verified(
        &self,
        authority: &FinalUseAuthority,
        token: VerifiedUseToken,
        allocation_id: &str,
        expected_lease_generation: u64,
        new_expires_at_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationGrantV1, FleetAllocationStoreError> {
        let state = self.load()?;
        let current = state
            .grants
            .get(allocation_id)
            .cloned()
            .ok_or(FleetAllocationStoreError::AllocationNotFound)?;
        if token.authority_epoch() != current.authority_epoch {
            return Err(FleetAllocationStoreError::AuthorityEpochMismatch);
        }
        let binding = lease_renewal_binding(&current, new_expires_at_unix_ms)?;
        authority
            .with_verified_use(token, &binding, || {
                self.renew_inner(
                    allocation_id,
                    expected_lease_generation,
                    new_expires_at_unix_ms,
                    now_unix_ms,
                )
            })
            .map_err(FleetAllocationStoreError::Authority)?
    }

    fn commit_prepared_inner(
        &self,
        prepared: &FleetPreparedAllocationV1,
        now_unix_ms: u64,
    ) -> Result<Vec<FleetAllocationGrantV1>, FleetAllocationStoreError> {
        let mut state = self.load()?;
        if state.revision != prepared.store_revision {
            return Err(FleetAllocationStoreError::StaleStoreRevision);
        }
        if prepared.grants.is_empty()
            || state.grants.len().saturating_add(prepared.grants.len()) > MAX_ACTIVE_GRANTS
        {
            return Err(FleetAllocationStoreError::GrantCapacityExceeded);
        }

        let mut additions: BTreeMap<String, FleetResourceVectorV1> = BTreeMap::new();
        for grant in &prepared.grants {
            grant.validate()?;
            if grant.principal_id != prepared.principal_id
                || grant.authority_epoch != prepared.authority_epoch
                || grant.issued_at_unix_ms > now_unix_ms
                || grant.expires_at_unix_ms <= now_unix_ms
                || state.grants.contains_key(&grant.allocation_id)
                || state.terminal_grants.contains_key(&grant.allocation_id)
                || state.grants.values().any(|row| row.agent_id == grant.agent_id)
            {
                return Err(FleetAllocationStoreError::Conflict);
            }
            let host = state
                .hosts
                .get(&grant.host_id)
                .ok_or(FleetAllocationStoreError::StaleHostObservation)?;
            if host.generation != grant.host_generation
                || host.revision != grant.host_observation_revision
                || host.valid_until_unix_ms < grant.expires_at_unix_ms
                || host_is_quarantined(&state, &grant.host_id, now_unix_ms)
            {
                return Err(FleetAllocationStoreError::StaleHostObservation);
            }
            let entry = additions.entry(grant.host_id.clone()).or_default();
            *entry = entry
                .checked_add(grant.resources)
                .ok_or(FleetAllocationStoreError::ArithmeticOverflow)?;
        }

        for (host_id, added) in additions {
            let host = state
                .hosts
                .get(&host_id)
                .ok_or(FleetAllocationStoreError::StaleHostObservation)?;
            let committed = committed_resources(&state, &host_id)?;
            let total = committed
                .checked_add(added)
                .ok_or(FleetAllocationStoreError::ArithmeticOverflow)?;
            if !total.fits_within(host.capacity) {
                return Err(FleetAllocationStoreError::CapacityExceeded);
            }
        }

        for grant in &prepared.grants {
            state
                .grants
                .insert(grant.allocation_id.clone(), grant.clone());
        }
        self.commit_state(state)?;
        Ok(prepared.grants.clone())
    }

    fn renew_inner(
        &self,
        allocation_id: &str,
        expected_lease_generation: u64,
        new_expires_at_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationGrantV1, FleetAllocationStoreError> {
        let mut state = self.load()?;
        let current = state
            .grants
            .get(allocation_id)
            .cloned()
            .ok_or(FleetAllocationStoreError::AllocationNotFound)?;
        if current.lease_generation != expected_lease_generation {
            return Err(FleetAllocationStoreError::StaleLease);
        }
        if current.revoked
            || current.holder == FleetHolderDispositionV1::Indeterminate
            || current.expires_at_unix_ms <= now_unix_ms
            || new_expires_at_unix_ms <= now_unix_ms
        {
            return Err(FleetAllocationStoreError::GrantNotUsable);
        }
        let host = state
            .hosts
            .get(&current.host_id)
            .ok_or(FleetAllocationStoreError::StaleHostObservation)?;
        if host.generation != current.host_generation
            || host.revision < current.host_observation_revision
            || new_expires_at_unix_ms > host.valid_until_unix_ms
        {
            return Err(FleetAllocationStoreError::StaleHostObservation);
        }
        let grant = state
            .grants
            .get_mut(allocation_id)
            .ok_or(FleetAllocationStoreError::AllocationNotFound)?;
        grant.expires_at_unix_ms = new_expires_at_unix_ms;
        grant.lease_generation = grant
            .lease_generation
            .checked_add(1)
            .ok_or(FleetAllocationStoreError::ArithmeticOverflow)?;
        grant.semantic_digest = grant.compute_digest()?;
        let result = grant.clone();
        self.commit_state(state)?;
        Ok(result)
    }

    fn commit_state(
        &self,
        mut state: FleetAllocationStoreSnapshotV1,
    ) -> Result<FleetAllocationStoreSnapshotV1, FleetAllocationStoreError> {
        state.revision = state
            .revision
            .checked_add(1)
            .ok_or(FleetAllocationStoreError::ArithmeticOverflow)?;
        state.validate()?;
        self.write_snapshot(&state)?;
        self.prune_snapshots(state.revision)?;
        Ok(state)
    }

    fn write_snapshot(
        &self,
        state: &FleetAllocationStoreSnapshotV1,
    ) -> Result<(), FleetAllocationStoreError> {
        let final_path = self.snapshot_path(state.revision);
        let next_path = final_path.with_extension("json.next");
        if next_path.exists() || final_path.exists() {
            return Err(FleetAllocationStoreError::ConcurrentWrite);
        }
        let bytes = serde_json::to_vec(state).map_err(|_| FleetAllocationStoreError::Encode)?;
        if bytes.len() as u64 > MAX_SNAPSHOT_BYTES {
            return Err(FleetAllocationStoreError::GrantCapacityExceeded);
        }
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&next_path)?;
        file.write_all(&bytes)?;
        file.write_all(b"\n")?;
        file.sync_all()?;
        fs::rename(&next_path, &final_path)?;
        sync_dir(&self.root)?;
        Ok(())
    }

    fn latest_revision(&self) -> Result<Option<u64>, FleetAllocationStoreError> {
        let mut latest = None;
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let ty = entry.file_type()?;
            if ty.is_symlink() {
                return Err(FleetAllocationStoreError::UnsafeStorePath);
            }
            if !ty.is_file() {
                continue;
            }
            let name = entry.file_name();
            let Some(name) = name.to_str() else {
                return Err(FleetAllocationStoreError::UnsafeStorePath);
            };
            let Some(value) = name
                .strip_prefix(SNAPSHOT_PREFIX)
                .and_then(|value| value.strip_suffix(SNAPSHOT_SUFFIX))
            else {
                continue;
            };
            if value.len() != 20 || !value.bytes().all(|byte| byte.is_ascii_digit()) {
                return Err(FleetAllocationStoreError::CorruptStore);
            }
            let revision = value
                .parse::<u64>()
                .map_err(|_| FleetAllocationStoreError::CorruptStore)?;
            latest = Some(latest.map_or(revision, |current: u64| current.max(revision)));
        }
        Ok(latest)
    }

    fn prune_snapshots(&self, current_revision: u64) -> Result<(), FleetAllocationStoreError> {
        if current_revision <= SNAPSHOT_RETAIN {
            return Ok(());
        }
        let before = current_revision - SNAPSHOT_RETAIN;
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let name = entry.file_name();
            let Some(name) = name.to_str() else {
                continue;
            };
            let Some(value) = name
                .strip_prefix(SNAPSHOT_PREFIX)
                .and_then(|value| value.strip_suffix(SNAPSHOT_SUFFIX))
            else {
                continue;
            };
            let Ok(revision) = value.parse::<u64>() else {
                continue;
            };
            if revision < before {
                fs::remove_file(entry.path())?;
            }
        }
        sync_dir(&self.root)?;
        Ok(())
    }

    fn snapshot_path(&self, revision: u64) -> PathBuf {
        self.root
            .join(format!("{SNAPSHOT_PREFIX}{revision:020}{SNAPSHOT_SUFFIX}"))
    }
}

fn prepare_store_root(root: &Path) -> Result<(), FleetAllocationStoreError> {
    match fs::symlink_metadata(root) {
        Ok(metadata) if metadata.file_type().is_dir() && !metadata.file_type().is_symlink() => {}
        Ok(_) => return Err(FleetAllocationStoreError::UnsafeStorePath),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            #[cfg(unix)]
            {
                use std::os::unix::fs::DirBuilderExt;
                fs::DirBuilder::new().mode(0o700).create(root)?;
            }
            #[cfg(not(unix))]
            fs::create_dir(root)?;
        }
        Err(error) => return Err(error.into()),
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let metadata = fs::metadata(root)?;
        if metadata.mode() & 0o077 != 0 {
            return Err(FleetAllocationStoreError::UnsafeStorePath);
        }
    }
    Ok(())
}

fn open_writer_lock(root: &Path) -> Result<File, FleetAllocationStoreError> {
    let path = root.join(LOCK_FILE);
    #[cfg(unix)]
    let file = {
        use std::os::unix::fs::OpenOptionsExt;
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .mode(0o600)
            .open(path)?
    };
    #[cfg(not(unix))]
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(path)?;
    if !file.metadata()?.is_file() {
        return Err(FleetAllocationStoreError::UnsafeStorePath);
    }
    Ok(file)
}

fn cleanup_incomplete_snapshots(root: &Path) -> Result<(), FleetAllocationStoreError> {
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let ty = entry.file_type()?;
        if ty.is_symlink() {
            return Err(FleetAllocationStoreError::UnsafeStorePath);
        }
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            return Err(FleetAllocationStoreError::UnsafeStorePath);
        };
        if name.starts_with(SNAPSHOT_PREFIX) && name.ends_with(".json.next") {
            if !ty.is_file() {
                return Err(FleetAllocationStoreError::UnsafeStorePath);
            }
            fs::remove_file(entry.path())?;
        }
    }
    sync_dir(root)?;
    Ok(())
}

fn committed_resources(
    state: &FleetAllocationStoreSnapshotV1,
    host_id: &str,
) -> Result<FleetResourceVectorV1, FleetAllocationStoreError> {
    state
        .grants
        .values()
        .filter(|grant| grant.host_id == host_id)
        .try_fold(FleetResourceVectorV1::default(), |sum, grant| {
            sum.checked_add(grant.resources)
                .ok_or(FleetAllocationStoreError::ArithmeticOverflow)
        })
}

fn host_is_quarantined(
    state: &FleetAllocationStoreSnapshotV1,
    host_id: &str,
    now_unix_ms: u64,
) -> bool {
    state.grants.values().any(|grant| {
        grant.host_id == host_id
            && (grant.revoked
                || grant.expires_at_unix_ms <= now_unix_ms
                || grant.holder == FleetHolderDispositionV1::Indeterminate)
    })
}

fn latest_terminal_for_agent<'a>(
    state: &'a FleetAllocationStoreSnapshotV1,
    agent_id: &AgentId,
) -> Option<&'a FleetAllocationGrantV1> {
    state
        .terminal_grants
        .values()
        .filter(|grant| &grant.agent_id == agent_id)
        .max_by(|left, right| {
            left.issued_at_unix_ms
                .cmp(&right.issued_at_unix_ms)
                .then_with(|| left.allocation_id.cmp(&right.allocation_id))
        })
}

fn compact_terminal(state: &mut FleetAllocationStoreSnapshotV1) {
    while state.terminal_grants.len() >= MAX_TERMINAL_GRANTS {
        let Some(oldest) = state
            .terminal_grants
            .values()
            .min_by(|left, right| {
                left.issued_at_unix_ms
                    .cmp(&right.issued_at_unix_ms)
                    .then_with(|| left.allocation_id.cmp(&right.allocation_id))
            })
            .map(|grant| grant.allocation_id.clone())
        else {
            break;
        };
        state.terminal_grants.remove(&oldest);
    }
}

fn allocation_final_use_binding(
    principal_id: &str,
    authority_epoch: u64,
    store_revision: u64,
    requests: &[FleetPlacementRequestV1],
    grants: &[FleetAllocationGrantV1],
) -> Result<FinalUseBinding, FleetAllocationStoreError> {
    #[derive(Serialize)]
    struct RequestInput<'a> {
        domain: &'static str,
        principal_id: &'a str,
        authority_epoch: u64,
        requests: &'a [FleetPlacementRequestV1],
    }
    #[derive(Serialize)]
    struct ScopeInput {
        domain: &'static str,
        store_revision: u64,
    }
    Ok(FinalUseBinding {
        subject_id: principal_id.to_string(),
        destination_id: "runtime.fleet/fleet_allocation_grantV1".to_string(),
        request_sha256: digest_array(&RequestInput {
            domain: "hepta.runtime-fleet.allocation-request.v1",
            principal_id,
            authority_epoch,
            requests,
        })?,
        scope_sha256: digest_array(&ScopeInput {
            domain: "hepta.runtime-fleet.allocation-scope.v1",
            store_revision,
        })?,
        payload_sha256: digest_array(grants)?,
    })
}

pub fn lease_renewal_binding(
    grant: &FleetAllocationGrantV1,
    new_expires_at_unix_ms: u64,
) -> Result<FinalUseBinding, FleetAllocationStoreError> {
    #[derive(Serialize)]
    struct Renewal<'a> {
        domain: &'static str,
        allocation_id: &'a str,
        lease_generation: u64,
        semantic_digest: &'a Sha256Digest,
        new_expires_at_unix_ms: u64,
    }
    let payload = Renewal {
        domain: "hepta.runtime-fleet.lease-renewal.v1",
        allocation_id: &grant.allocation_id,
        lease_generation: grant.lease_generation,
        semantic_digest: &grant.semantic_digest,
        new_expires_at_unix_ms,
    };
    let digest = digest_array(&payload)?;
    Ok(FinalUseBinding {
        subject_id: grant.principal_id.clone(),
        destination_id: "runtime.fleet/renew_allocation_leaseV1".to_string(),
        request_sha256: digest,
        scope_sha256: digest_array(&grant.semantic_digest)?,
        payload_sha256: digest,
    })
}

fn digest_json(value: &impl Serialize) -> Result<Sha256Digest, FleetAllocationStoreError> {
    let bytes = serde_json::to_vec(value).map_err(|_| FleetAllocationStoreError::Encode)?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn digest_array<T: Serialize + ?Sized>(
    value: &T,
) -> Result<[u8; 32], FleetAllocationStoreError> {
    let bytes = serde_json::to_vec(value).map_err(|_| FleetAllocationStoreError::Encode)?;
    Ok(Sha256::digest(bytes).into())
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
}

#[cfg(unix)]
fn sync_dir(path: &Path) -> Result<(), FleetAllocationStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_dir(_path: &Path) -> Result<(), FleetAllocationStoreError> {
    Ok(())
}

#[derive(Debug, Error)]
pub enum FleetAllocationStoreError {
    #[error("fleet allocation store I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("fleet allocation store encoding failed")]
    Encode,
    #[error("fleet allocation store is corrupt")]
    CorruptStore,
    #[error("fleet allocation store path is unsafe")]
    UnsafeStorePath,
    #[error("fleet allocation writer is already active")]
    WriterBusy,
    #[error("concurrent fleet allocation write detected")]
    ConcurrentWrite,
    #[error("invalid fleet host observation")]
    InvalidHostObservation,
    #[error("stale fleet host observation")]
    StaleHostObservation,
    #[error("fleet host capacity exceeded")]
    HostCapacityExceeded,
    #[error("invalid fleet allocation request")]
    InvalidRequest,
    #[error("invalid fleet allocation grant")]
    InvalidGrant,
    #[error("fleet allocation conflict")]
    Conflict,
    #[error("fleet allocation capacity exceeded")]
    CapacityExceeded,
    #[error("fleet allocation grant capacity exceeded")]
    GrantCapacityExceeded,
    #[error("fleet allocation was not found")]
    AllocationNotFound,
    #[error("fleet allocation grant is not usable")]
    GrantNotUsable,
    #[error("stale fleet allocation lease")]
    StaleLease,
    #[error("stale fleet allocation store revision")]
    StaleStoreRevision,
    #[error("fleet final-use authority epoch does not match the prepared grant")]
    AuthorityEpochMismatch,
    #[error("invalid fleet consumption observation")]
    InvalidObservation,
    #[error("unknown fleet allocation agent {0}")]
    UnknownAgent(AgentId),
    #[error("fleet allocation exceeds registered agent budget {0}")]
    AgentBudgetExceeded(AgentId),
    #[error("fleet registry access failed: {0}")]
    Registry(String),
    #[error("fleet allocation arithmetic overflow")]
    ArithmeticOverflow,
    #[error("fleet placement: {0}")]
    Placement(#[from] LocalAllocationError),
    #[error("fleet final-use authority: {0}")]
    Authority(#[from] FinalUseError),
}

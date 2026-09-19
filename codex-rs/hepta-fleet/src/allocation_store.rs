use std::collections::BTreeMap;
#[cfg(unix)]
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_paths::HeptaFleetRoot;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::FleetAllocationPlanV1;
use crate::FleetHostCapacityObservationV1;
use crate::FleetPlacementError;
use crate::FleetPlacementHostV1;
use crate::FleetPlacementPolicyV1;
use crate::FleetPlacementRequestV1;
use crate::FleetRegistry;
use crate::FleetResourceVectorV1;
use crate::VerifiedFleetHostCapacityObservationV1;
use crate::calculate_fleet_placement_v1;

pub const FLEET_ALLOCATION_STORE_SCHEMA_VERSION: u32 = 1;
pub const MAX_DURABLE_FLEET_GRANTS: usize = 16_384;

const STORE_DIRECTORY: &str = "fleet-allocations-v1";
const STATE_PREFIX: &str = "state-";
const STATE_SUFFIX: &str = ".json";
const MAX_STATE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_IDENTIFIER_BYTES: usize = 128;
static STAGING_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetAllocationHolderStateV1 {
    Unclaimed,
    Held,
    Unknown,
    Released,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetAllocationGrantV1 {
    pub schema_version: u32,
    pub allocation_id: String,
    pub request_id: String,
    pub agent_id: AgentId,
    pub principal_id: String,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub expires_at_unix_ms: u64,
    pub resources: FleetResourceVectorV1,
    pub plan_sha256: Sha256Digest,
    pub authority_grant_id: String,
    pub revoked: bool,
    pub holder_state: FleetAllocationHolderStateV1,
    pub updated_at_unix_ms: u64,
}

impl FleetAllocationGrantV1 {
    pub fn is_capacity_committed(&self, now_unix_ms: u64) -> bool {
        !self.revoked
            && self.expires_at_unix_ms > now_unix_ms
            && self.holder_state != FleetAllocationHolderStateV1::Released
    }

    pub fn state_sha256(&self) -> Result<Sha256Digest, FleetAllocationStoreError> {
        digest_json(b"hepta.runtime-fleet.allocation-grant.v1\0", self)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetAllocationSnapshotV1 {
    pub generation: u64,
    pub state_sha256: Sha256Digest,
    pub hosts: BTreeMap<String, FleetHostCapacityObservationV1>,
    pub grants: BTreeMap<String, FleetAllocationGrantV1>,
}

impl FleetAllocationSnapshotV1 {
    pub fn grant(&self, allocation_id: &str) -> Option<&FleetAllocationGrantV1> {
        self.grants.get(allocation_id)
    }

    pub fn active_grants_for_agent(
        &self,
        agent_id: &AgentId,
        now_unix_ms: u64,
    ) -> Vec<&FleetAllocationGrantV1> {
        self.grants
            .values()
            .filter(|grant| {
                &grant.agent_id == agent_id && grant.is_capacity_committed(now_unix_ms)
            })
            .collect()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetAllocationCommitReceiptV1 {
    pub generation: u64,
    pub state_sha256: Sha256Digest,
    pub allocations: Vec<FleetAllocationGrantV1>,
    pub changed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetAllocationMutationReceiptV1 {
    pub generation: u64,
    pub state_sha256: Sha256Digest,
    pub grant: FleetAllocationGrantV1,
    pub changed: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredFleetAllocationStateV1 {
    schema_version: u32,
    generation: u64,
    hosts: BTreeMap<String, FleetHostCapacityObservationV1>,
    grants: BTreeMap<String, FleetAllocationGrantV1>,
    state_sha256: Sha256Digest,
}

#[derive(Serialize)]
struct StoredFleetAllocationContentV1<'a> {
    schema_version: u32,
    generation: u64,
    hosts: &'a BTreeMap<String, FleetHostCapacityObservationV1>,
    grants: &'a BTreeMap<String, FleetAllocationGrantV1>,
}

impl StoredFleetAllocationStateV1 {
    fn empty() -> Result<Self, FleetAllocationStoreError> {
        Self::new(0, BTreeMap::new(), BTreeMap::new())
    }

    fn new(
        generation: u64,
        hosts: BTreeMap<String, FleetHostCapacityObservationV1>,
        grants: BTreeMap<String, FleetAllocationGrantV1>,
    ) -> Result<Self, FleetAllocationStoreError> {
        let state_sha256 = digest_json(
            b"hepta.runtime-fleet.allocation-store-state.v1\0",
            &StoredFleetAllocationContentV1 {
                schema_version: FLEET_ALLOCATION_STORE_SCHEMA_VERSION,
                generation,
                hosts: &hosts,
                grants: &grants,
            },
        )?;
        Ok(Self {
            schema_version: FLEET_ALLOCATION_STORE_SCHEMA_VERSION,
            generation,
            hosts,
            grants,
            state_sha256,
        })
    }

    fn validate(&self) -> Result<(), FleetAllocationStoreError> {
        if self.schema_version != FLEET_ALLOCATION_STORE_SCHEMA_VERSION {
            return Err(FleetAllocationStoreError::Corrupt(
                "unsupported allocation-store schema".to_string(),
            ));
        }
        if self.hosts.len() > crate::MAX_LOCAL_HOST_CANDIDATES
            || self.grants.len() > MAX_DURABLE_FLEET_GRANTS
        {
            return Err(FleetAllocationStoreError::Corrupt(
                "allocation-store cardinality exceeds the bounded schema".to_string(),
            ));
        }
        for (host_id, host) in &self.hosts {
            host.validate()?;
            if host_id != &host.host_id {
                return Err(FleetAllocationStoreError::Corrupt(
                    "capacity observation key does not match host identity".to_string(),
                ));
            }
        }
        for (allocation_id, grant) in &self.grants {
            validate_grant(grant)?;
            if allocation_id != &grant.allocation_id {
                return Err(FleetAllocationStoreError::Corrupt(
                    "allocation grant key does not match allocation identity".to_string(),
                ));
            }
        }
        let expected = Self::new(
            self.generation,
            self.hosts.clone(),
            self.grants.clone(),
        )?
        .state_sha256;
        if expected != self.state_sha256 {
            return Err(FleetAllocationStoreError::Corrupt(
                "allocation-store state digest mismatch".to_string(),
            ));
        }
        Ok(())
    }

    fn snapshot(&self) -> FleetAllocationSnapshotV1 {
        FleetAllocationSnapshotV1 {
            generation: self.generation,
            state_sha256: self.state_sha256.clone(),
            hosts: self.hosts.clone(),
            grants: self.grants.clone(),
        }
    }
}

/// Supervisor-owned durable allocation authority.
///
/// Every mutation publishes one complete immutable generation. The next state
/// file is installed with create-only hard-link CAS, so concurrent writers
/// cannot both publish the same generation. Temporary files are never read as
/// authority; crash recovery selects the highest contiguous valid generation.
#[derive(Clone, Debug)]
pub struct FleetAllocationStore {
    root: PathBuf,
    registry: FleetRegistry,
}

impl FleetAllocationStore {
    pub fn initialize(registry: &FleetRegistry) -> Result<Self, FleetAllocationStoreError> {
        let root = registry.layout().state_root().join(STORE_DIRECTORY);
        std::fs::create_dir_all(&root)?;
        validate_physical_directory(&root)?;
        let store = Self {
            root,
            registry: registry.clone(),
        };
        if store.latest_state_path()?.is_none() {
            store.publish_initial_state()?;
        }
        store.load_state()?;
        Ok(store)
    }

    pub fn open_existing(registry: &FleetRegistry) -> Result<Self, FleetAllocationStoreError> {
        let root = registry.layout().state_root().join(STORE_DIRECTORY);
        validate_physical_directory(&root)?;
        let store = Self {
            root,
            registry: registry.clone(),
        };
        store.load_state()?;
        Ok(store)
    }

    pub fn open_or_initialize(
        registry: &FleetRegistry,
    ) -> Result<Self, FleetAllocationStoreError> {
        let root = registry.layout().state_root().join(STORE_DIRECTORY);
        match std::fs::symlink_metadata(&root) {
            Ok(_) => Self::open_existing(registry),
            Err(error) if error.kind() == ErrorKind::NotFound => Self::initialize(registry),
            Err(error) => Err(error.into()),
        }
    }

    pub fn open_for_fleet_root(
        fleet_root: HeptaFleetRoot,
    ) -> Result<Self, FleetAllocationStoreError> {
        let registry = FleetRegistry::open_existing(fleet_root)?;
        Self::open_or_initialize(&registry)
    }

    pub fn exists(registry: &FleetRegistry) -> bool {
        registry.layout().state_root().join(STORE_DIRECTORY).is_dir()
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn snapshot(&self) -> Result<FleetAllocationSnapshotV1, FleetAllocationStoreError> {
        self.load_state().map(|state| state.snapshot())
    }

    pub fn record_capacity(
        &self,
        expected_generation: u64,
        verified: VerifiedFleetHostCapacityObservationV1,
    ) -> Result<FleetAllocationSnapshotV1, FleetAllocationStoreError> {
        let observation = verified.into_observation();
        let current = self.load_state()?;
        require_generation(&current, expected_generation)?;
        if let Some(previous) = current.hosts.get(&observation.host_id) {
            if observation.host_generation < previous.host_generation {
                return Err(FleetAllocationStoreError::StaleHostGeneration {
                    host_id: observation.host_id,
                    current: previous.host_generation,
                    proposed: observation.host_generation,
                });
            }
            if observation.host_generation == previous.host_generation {
                if &observation == previous {
                    return Ok(current.snapshot());
                }
                return Err(FleetAllocationStoreError::Conflict(
                    "capacity observation reuses a host generation with different semantics"
                        .to_string(),
                ));
            }
            if observation.authority_epoch < previous.authority_epoch {
                return Err(FleetAllocationStoreError::StaleAuthorityEpoch);
            }
        }
        let mut hosts = current.hosts;
        hosts.insert(observation.host_id.clone(), observation);
        self.publish_next(current.generation, hosts, current.grants)
            .map(|state| state.snapshot())
    }

    pub fn calculate_plan(
        &self,
        requests: &[FleetPlacementRequestV1],
        policy: &FleetPlacementPolicyV1,
        now_unix_ms: u64,
    ) -> Result<(u64, FleetAllocationPlanV1), FleetAllocationStoreError> {
        policy.validate()?;
        for request in requests {
            let record = self.registry.load_agent(&request.agent_id)?;
            let ceiling = FleetResourceVectorV1::from(&record.manifest.resources);
            if !request.minimum.fits(ceiling) || !request.desired.fits(ceiling) {
                return Err(FleetAllocationStoreError::AgentBudgetExceeded(
                    request.agent_id.clone(),
                ));
            }
        }
        let state = self.load_state()?;
        let mut hosts = Vec::new();
        for observation in state.hosts.values() {
            if observation.authority_epoch != policy.authority_epoch
                || now_unix_ms < observation.observed_at_unix_ms
                || now_unix_ms >= observation.valid_until_unix_ms
            {
                continue;
            }
            let committed = committed_resources(
                &state.grants,
                &observation.host_id,
                now_unix_ms,
            )?;
            let Some(available) = observation.capacity.checked_sub(committed) else {
                return Err(FleetAllocationStoreError::Corrupt(format!(
                    "committed allocations exceed observed capacity on {}",
                    observation.host_id
                )));
            };
            hosts.push(FleetPlacementHostV1 {
                observation: observation.clone(),
                available,
            });
        }
        let plan = calculate_fleet_placement_v1(&hosts, requests, policy, now_unix_ms)?;
        Ok((state.generation, plan))
    }

    /// Revalidates a signed kernel final-use grant immediately around the
    /// durable fleet commit. The nonce is deliberately not refunded on any
    /// later CAS or storage failure; an uncertain caller must reconcile before
    /// obtaining a new independently signed grant.
    pub fn commit_plan_with_authority(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        destination_id: &str,
        expected_generation: u64,
        plan: &FleetAllocationPlanV1,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationCommitReceiptV1, FleetAllocationStoreError> {
        plan.validate()?;
        if signed.grant.authority_epoch != plan.authority_epoch {
            return Err(FleetAllocationStoreError::StaleAuthorityEpoch);
        }
        let binding = plan.final_use_binding(destination_id)?;
        let token = authority.claim(signed, &binding)?;
        authority
            .with_verified_use(token, &binding, || {
                self.commit_plan(
                    expected_generation,
                    plan,
                    &signed.grant.grant_id,
                    now_unix_ms,
                )
            })
            .map_err(FleetAllocationStoreError::Authority)?
    }

    pub fn validate_runtime_grant(
        &self,
        allocation_id: &str,
        agent_id: &AgentId,
        required: FleetResourceVectorV1,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationGrantV1, FleetAllocationStoreError> {
        validate_identifier(allocation_id, "allocation_id")?;
        let state = self.load_state()?;
        let grant = state
            .grants
            .get(allocation_id)
            .ok_or_else(|| FleetAllocationStoreError::UnknownAllocation(allocation_id.to_string()))?;
        if &grant.agent_id != agent_id {
            return Err(FleetAllocationStoreError::Conflict(
                "allocation grant is bound to another Agent".to_string(),
            ));
        }
        if grant.revoked
            || grant.holder_state == FleetAllocationHolderStateV1::Released
            || grant.expires_at_unix_ms <= now_unix_ms
            || !required.fits(grant.resources)
        {
            return Err(FleetAllocationStoreError::GrantNotLive);
        }
        let host = state
            .hosts
            .get(&grant.host_id)
            .ok_or_else(|| FleetAllocationStoreError::UnknownHost(grant.host_id.clone()))?;
        if host.host_generation != grant.host_generation
            || host.failure_domain_id != grant.failure_domain_id
            || host.authority_epoch != grant.authority_epoch
            || now_unix_ms < host.observed_at_unix_ms
            || now_unix_ms >= host.valid_until_unix_ms
        {
            return Err(FleetAllocationStoreError::StaleHostGeneration {
                host_id: grant.host_id.clone(),
                current: host.host_generation,
                proposed: grant.host_generation,
            });
        }
        Ok(grant.clone())
    }

    pub fn renew(
        &self,
        expected_generation: u64,
        allocation_id: &str,
        expected_lease_generation: u64,
        expires_at_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationMutationReceiptV1, FleetAllocationStoreError> {
        let current = self.load_state()?;
        require_generation(&current, expected_generation)?;
        let existing = current
            .grants
            .get(allocation_id)
            .cloned()
            .ok_or_else(|| FleetAllocationStoreError::UnknownAllocation(allocation_id.to_string()))?;
        if existing.lease_generation != expected_lease_generation {
            return Err(FleetAllocationStoreError::StaleLease {
                current: existing.lease_generation,
                proposed: expected_lease_generation,
            });
        }
        if existing.revoked
            || existing.holder_state == FleetAllocationHolderStateV1::Released
        {
            return Err(FleetAllocationStoreError::GrantNotLive);
        }
        let host = current
            .hosts
            .get(&existing.host_id)
            .ok_or_else(|| FleetAllocationStoreError::UnknownHost(existing.host_id.clone()))?;
        if host.host_generation != existing.host_generation
            || host.authority_epoch != existing.authority_epoch
            || now_unix_ms >= host.valid_until_unix_ms
            || expires_at_unix_ms <= now_unix_ms
            || expires_at_unix_ms > host.valid_until_unix_ms
        {
            return Err(FleetAllocationStoreError::GrantNotLive);
        }
        if existing.expires_at_unix_ms == expires_at_unix_ms {
            return Ok(FleetAllocationMutationReceiptV1 {
                generation: current.generation,
                state_sha256: current.state_sha256,
                grant: existing,
                changed: false,
            });
        }
        let mut grants = current.grants;
        let grant = grants
            .get_mut(allocation_id)
            .ok_or_else(|| FleetAllocationStoreError::UnknownAllocation(allocation_id.to_string()))?;
        grant.expires_at_unix_ms = expires_at_unix_ms;
        grant.lease_generation = grant
            .lease_generation
            .checked_add(1)
            .ok_or(FleetAllocationStoreError::ArithmeticInvariant)?;
        grant.updated_at_unix_ms = now_unix_ms;
        let grant = grant.clone();
        let next = self.publish_next(current.generation, current.hosts, grants)?;
        Ok(FleetAllocationMutationReceiptV1 {
            generation: next.generation,
            state_sha256: next.state_sha256,
            grant,
            changed: true,
        })
    }

    pub fn revoke(
        &self,
        expected_generation: u64,
        allocation_id: &str,
        expected_lease_generation: u64,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationMutationReceiptV1, FleetAllocationStoreError> {
        let current = self.load_state()?;
        require_generation(&current, expected_generation)?;
        let existing = current
            .grants
            .get(allocation_id)
            .cloned()
            .ok_or_else(|| FleetAllocationStoreError::UnknownAllocation(allocation_id.to_string()))?;
        if existing.lease_generation != expected_lease_generation {
            return Err(FleetAllocationStoreError::StaleLease {
                current: existing.lease_generation,
                proposed: expected_lease_generation,
            });
        }
        if existing.revoked {
            return Ok(FleetAllocationMutationReceiptV1 {
                generation: current.generation,
                state_sha256: current.state_sha256,
                grant: existing,
                changed: false,
            });
        }
        let mut grants = current.grants;
        let grant = grants
            .get_mut(allocation_id)
            .ok_or_else(|| FleetAllocationStoreError::UnknownAllocation(allocation_id.to_string()))?;
        grant.revoked = true;
        grant.lease_generation = grant
            .lease_generation
            .checked_add(1)
            .ok_or(FleetAllocationStoreError::ArithmeticInvariant)?;
        grant.updated_at_unix_ms = now_unix_ms;
        let grant = grant.clone();
        let next = self.publish_next(current.generation, current.hosts, grants)?;
        Ok(FleetAllocationMutationReceiptV1 {
            generation: next.generation,
            state_sha256: next.state_sha256,
            grant,
            changed: true,
        })
    }

    pub fn reconcile_holder(
        &self,
        expected_generation: u64,
        allocation_id: &str,
        expected_lease_generation: u64,
        holder_state: FleetAllocationHolderStateV1,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationMutationReceiptV1, FleetAllocationStoreError> {
        let current = self.load_state()?;
        require_generation(&current, expected_generation)?;
        let existing = current
            .grants
            .get(allocation_id)
            .cloned()
            .ok_or_else(|| FleetAllocationStoreError::UnknownAllocation(allocation_id.to_string()))?;
        if existing.lease_generation != expected_lease_generation {
            return Err(FleetAllocationStoreError::StaleLease {
                current: existing.lease_generation,
                proposed: expected_lease_generation,
            });
        }
        if existing.holder_state == holder_state {
            return Ok(FleetAllocationMutationReceiptV1 {
                generation: current.generation,
                state_sha256: current.state_sha256,
                grant: existing,
                changed: false,
            });
        }
        if !valid_holder_transition(existing.holder_state, holder_state) {
            return Err(FleetAllocationStoreError::InvalidHolderTransition {
                current: existing.holder_state,
                proposed: holder_state,
            });
        }
        let mut grants = current.grants;
        let grant = grants
            .get_mut(allocation_id)
            .ok_or_else(|| FleetAllocationStoreError::UnknownAllocation(allocation_id.to_string()))?;
        grant.holder_state = holder_state;
        grant.updated_at_unix_ms = now_unix_ms;
        let grant = grant.clone();
        let next = self.publish_next(current.generation, current.hosts, grants)?;
        Ok(FleetAllocationMutationReceiptV1 {
            generation: next.generation,
            state_sha256: next.state_sha256,
            grant,
            changed: true,
        })
    }

    pub fn garbage_collect(
        &self,
        expected_generation: u64,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationSnapshotV1, FleetAllocationStoreError> {
        let current = self.load_state()?;
        require_generation(&current, expected_generation)?;
        let grant_count = current.grants.len();
        let host_count = current.hosts.len();
        let mut grants = current.grants.clone();
        grants.retain(|_, grant| {
            !((grant.revoked || grant.expires_at_unix_ms <= now_unix_ms)
                && grant.holder_state == FleetAllocationHolderStateV1::Released)
        });
        let mut hosts = current.hosts.clone();
        hosts.retain(|host_id, host| {
            host.valid_until_unix_ms > now_unix_ms
                || grants.values().any(|grant| &grant.host_id == host_id)
        });
        if grants.len() == grant_count && hosts.len() == host_count {
            return Ok(current.snapshot());
        }
        let next = self.publish_next(current.generation, hosts, grants)?;
        Ok(next.snapshot())
    }

    /// Retain only the newest immutable state generations. The newest state is
    /// never removed and remains independently self-validating.
    pub fn prune_snapshots(&self, keep: usize) -> Result<usize, FleetAllocationStoreError> {
        if keep == 0 {
            return Err(FleetAllocationStoreError::InvalidRetention);
        }
        let mut generations = list_state_generations(&self.root)?;
        if generations.len() <= keep {
            return Ok(0);
        }
        generations.sort_unstable();
        let delete_count = generations.len() - keep;
        let mut deleted = 0;
        for generation in generations.into_iter().take(delete_count) {
            std::fs::remove_file(state_path(&self.root, generation))?;
            deleted += 1;
        }
        sync_directory(&self.root)?;
        Ok(deleted)
    }

    fn commit_plan(
        &self,
        expected_generation: u64,
        plan: &FleetAllocationPlanV1,
        authority_grant_id: &str,
        now_unix_ms: u64,
    ) -> Result<FleetAllocationCommitReceiptV1, FleetAllocationStoreError> {
        validate_identifier(authority_grant_id, "authority_grant_id")?;
        let current = self.load_state()?;
        require_generation(&current, expected_generation)?;

        let allocation_ids = plan
            .shares
            .iter()
            .map(|share| allocation_id(&plan.plan_sha256, &share.request_id))
            .collect::<Vec<_>>();
        let existing = allocation_ids
            .iter()
            .map(|id| current.grants.get(id))
            .collect::<Vec<_>>();
        if existing.iter().all(|grant| grant.is_some()) {
            let allocations = existing
                .into_iter()
                .flatten()
                .cloned()
                .collect::<Vec<_>>();
            if allocations.iter().all(|grant| {
                grant.plan_sha256 == plan.plan_sha256
                    && grant.principal_id == plan.principal_id
                    && grant.authority_epoch == plan.authority_epoch
            }) {
                return Ok(FleetAllocationCommitReceiptV1 {
                    generation: current.generation,
                    state_sha256: current.state_sha256,
                    allocations,
                    changed: false,
                });
            }
            return Err(FleetAllocationStoreError::Conflict(
                "allocation identity already exists with different semantics".to_string(),
            ));
        }
        if existing.iter().any(|grant| grant.is_some()) {
            return Err(FleetAllocationStoreError::Conflict(
                "allocation plan is only partially present in durable state".to_string(),
            ));
        }
        if current.grants.len().saturating_add(plan.shares.len()) > MAX_DURABLE_FLEET_GRANTS {
            return Err(FleetAllocationStoreError::CapacityExceeded);
        }

        let mut planned_by_host: BTreeMap<String, FleetResourceVectorV1> = BTreeMap::new();
        for share in &plan.shares {
            let record = self.registry.load_agent(&share.agent_id)?;
            let ceiling = FleetResourceVectorV1::from(&record.manifest.resources);
            if !share.resources.fits(ceiling) {
                return Err(FleetAllocationStoreError::AgentBudgetExceeded(
                    share.agent_id.clone(),
                ));
            }
            let host = current
                .hosts
                .get(&share.host_id)
                .ok_or_else(|| FleetAllocationStoreError::UnknownHost(share.host_id.clone()))?;
            if host.failure_domain_id != share.failure_domain_id
                || host.host_generation != share.host_generation
                || host.authority_epoch != plan.authority_epoch
                || now_unix_ms < host.observed_at_unix_ms
                || now_unix_ms >= host.valid_until_unix_ms
                || share.expires_at_unix_ms <= now_unix_ms
                || share.expires_at_unix_ms > host.valid_until_unix_ms
            {
                return Err(FleetAllocationStoreError::GrantNotLive);
            }
            let entry = planned_by_host
                .entry(share.host_id.clone())
                .or_default();
            *entry = entry
                .checked_add(share.resources)
                .ok_or(FleetAllocationStoreError::ArithmeticInvariant)?;
        }
        for (host_id, planned) in &planned_by_host {
            let host = current
                .hosts
                .get(host_id)
                .ok_or_else(|| FleetAllocationStoreError::UnknownHost(host_id.clone()))?;
            let committed = committed_resources(&current.grants, host_id, now_unix_ms)?;
            let total = committed
                .checked_add(*planned)
                .ok_or(FleetAllocationStoreError::ArithmeticInvariant)?;
            if !total.fits(host.capacity) {
                return Err(FleetAllocationStoreError::CapacityExceeded);
            }
        }

        let mut grants = current.grants;
        let mut allocations = Vec::with_capacity(plan.shares.len());
        for (share, allocation_id) in plan.shares.iter().zip(allocation_ids) {
            let grant = FleetAllocationGrantV1 {
                schema_version: FLEET_ALLOCATION_STORE_SCHEMA_VERSION,
                allocation_id: allocation_id.clone(),
                request_id: share.request_id.clone(),
                agent_id: share.agent_id.clone(),
                principal_id: share.principal_id.clone(),
                host_id: share.host_id.clone(),
                failure_domain_id: share.failure_domain_id.clone(),
                host_generation: share.host_generation,
                authority_epoch: plan.authority_epoch,
                lease_generation: 1,
                expires_at_unix_ms: share.expires_at_unix_ms,
                resources: share.resources,
                plan_sha256: plan.plan_sha256.clone(),
                authority_grant_id: authority_grant_id.to_string(),
                revoked: false,
                holder_state: FleetAllocationHolderStateV1::Unclaimed,
                updated_at_unix_ms: now_unix_ms,
            };
            validate_grant(&grant)?;
            grants.insert(allocation_id, grant.clone());
            allocations.push(grant);
        }
        let next = self.publish_next(current.generation, current.hosts, grants)?;
        Ok(FleetAllocationCommitReceiptV1 {
            generation: next.generation,
            state_sha256: next.state_sha256,
            allocations,
            changed: true,
        })
    }

    fn publish_initial_state(&self) -> Result<(), FleetAllocationStoreError> {
        let initial = StoredFleetAllocationStateV1::empty()?;
        let final_path = state_path(&self.root, 0);
        if final_path.exists() {
            return Ok(());
        }
        publish_create_only(&self.root, &final_path, &initial)?;
        Ok(())
    }

    fn publish_next(
        &self,
        expected_generation: u64,
        hosts: BTreeMap<String, FleetHostCapacityObservationV1>,
        grants: BTreeMap<String, FleetAllocationGrantV1>,
    ) -> Result<StoredFleetAllocationStateV1, FleetAllocationStoreError> {
        let next_generation = expected_generation
            .checked_add(1)
            .ok_or(FleetAllocationStoreError::ArithmeticInvariant)?;
        let next = StoredFleetAllocationStateV1::new(next_generation, hosts, grants)?;
        next.validate()?;
        let final_path = state_path(&self.root, next_generation);
        match publish_create_only(&self.root, &final_path, &next) {
            Ok(()) => Ok(next),
            Err(FleetAllocationStoreError::Io(error))
                if error.kind() == ErrorKind::AlreadyExists =>
            {
                let actual = self.load_state()?.generation;
                Err(FleetAllocationStoreError::StaleGeneration {
                    expected: expected_generation,
                    current: actual,
                })
            }
            Err(error) => Err(error),
        }
    }

    fn load_state(&self) -> Result<StoredFleetAllocationStateV1, FleetAllocationStoreError> {
        validate_physical_directory(&self.root)?;
        let generations = list_state_generations(&self.root)?;
        if generations.is_empty() {
            return Err(FleetAllocationStoreError::Corrupt(
                "allocation-store state is missing".to_string(),
            ));
        }
        for pair in generations.windows(2) {
            if pair[1] != pair[0].saturating_add(1) {
                return Err(FleetAllocationStoreError::Corrupt(
                    "retained allocation-store generations are not contiguous".to_string(),
                ));
            }
        }
        let latest = *generations
            .last()
            .ok_or_else(|| FleetAllocationStoreError::Corrupt(
                "allocation-store state is missing".to_string(),
            ))?;
        read_state(&state_path(&self.root, latest))
    }

    fn latest_state_path(&self) -> Result<Option<PathBuf>, FleetAllocationStoreError> {
        Ok(list_state_generations(&self.root)?
            .into_iter()
            .max()
            .map(|generation| state_path(&self.root, generation)))
    }
}

fn committed_resources(
    grants: &BTreeMap<String, FleetAllocationGrantV1>,
    host_id: &str,
    now_unix_ms: u64,
) -> Result<FleetResourceVectorV1, FleetAllocationStoreError> {
    grants
        .values()
        .filter(|grant| grant.host_id == host_id && grant.is_capacity_committed(now_unix_ms))
        .try_fold(FleetResourceVectorV1::default(), |sum, grant| {
            sum.checked_add(grant.resources)
                .ok_or(FleetAllocationStoreError::ArithmeticInvariant)
        })
}

fn valid_holder_transition(
    current: FleetAllocationHolderStateV1,
    proposed: FleetAllocationHolderStateV1,
) -> bool {
    matches!(
        (current, proposed),
        (FleetAllocationHolderStateV1::Unclaimed, FleetAllocationHolderStateV1::Held)
            | (FleetAllocationHolderStateV1::Unclaimed, FleetAllocationHolderStateV1::Unknown)
            | (FleetAllocationHolderStateV1::Unclaimed, FleetAllocationHolderStateV1::Released)
            | (FleetAllocationHolderStateV1::Held, FleetAllocationHolderStateV1::Unknown)
            | (FleetAllocationHolderStateV1::Held, FleetAllocationHolderStateV1::Released)
            | (FleetAllocationHolderStateV1::Unknown, FleetAllocationHolderStateV1::Held)
            | (FleetAllocationHolderStateV1::Unknown, FleetAllocationHolderStateV1::Released)
    )
}

fn allocation_id(plan_sha256: &Sha256Digest, request_id: &str) -> String {
    let mut bytes = b"hepta.runtime-fleet.allocation-id.v1\0".to_vec();
    bytes.extend_from_slice(plan_sha256.as_str().as_bytes());
    bytes.extend_from_slice(request_id.as_bytes());
    format!("allocation:{}", Sha256Digest::for_bytes(&bytes).as_str())
}

fn require_generation(
    state: &StoredFleetAllocationStateV1,
    expected: u64,
) -> Result<(), FleetAllocationStoreError> {
    if state.generation != expected {
        return Err(FleetAllocationStoreError::StaleGeneration {
            expected,
            current: state.generation,
        });
    }
    Ok(())
}

fn validate_grant(grant: &FleetAllocationGrantV1) -> Result<(), FleetAllocationStoreError> {
    if grant.schema_version != FLEET_ALLOCATION_STORE_SCHEMA_VERSION
        || grant.host_generation == 0
        || grant.authority_epoch == 0
        || grant.lease_generation == 0
        || grant.expires_at_unix_ms == 0
        || grant.resources.is_zero()
    {
        return Err(FleetAllocationStoreError::Corrupt(
            "allocation grant has invalid bounded fields".to_string(),
        ));
    }
    for (value, label) in [
        (&grant.allocation_id, "allocation_id"),
        (&grant.request_id, "request_id"),
        (&grant.principal_id, "principal_id"),
        (&grant.host_id, "host_id"),
        (&grant.failure_domain_id, "failure_domain_id"),
        (&grant.authority_grant_id, "authority_grant_id"),
    ] {
        validate_identifier(value, label)?;
    }
    Ok(())
}

fn validate_identifier(
    value: &str,
    label: &'static str,
) -> Result<(), FleetAllocationStoreError> {
    if value.is_empty()
        || value.len() > MAX_IDENTIFIER_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
    {
        return Err(FleetAllocationStoreError::InvalidIdentifier(label));
    }
    Ok(())
}

fn list_state_generations(root: &Path) -> Result<Vec<u64>, FleetAllocationStoreError> {
    let mut generations = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            return Err(FleetAllocationStoreError::Corrupt(
                "allocation-store filename is not UTF-8".to_string(),
            ));
        };
        if name.starts_with('.') {
            continue;
        }
        let Some(value) = name
            .strip_prefix(STATE_PREFIX)
            .and_then(|value| value.strip_suffix(STATE_SUFFIX))
        else {
            return Err(FleetAllocationStoreError::Corrupt(format!(
                "unexpected allocation-store file {name:?}"
            )));
        };
        if value.len() != 20 || !value.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err(FleetAllocationStoreError::Corrupt(format!(
                "invalid allocation-store generation {name:?}"
            )));
        }
        let generation = value.parse::<u64>().map_err(|_| {
            FleetAllocationStoreError::Corrupt("invalid allocation-store generation".to_string())
        })?;
        generations.push(generation);
    }
    generations.sort_unstable();
    generations.dedup();
    Ok(generations)
}

fn state_path(root: &Path, generation: u64) -> PathBuf {
    root.join(format!("{STATE_PREFIX}{generation:020}{STATE_SUFFIX}"))
}

fn read_state(path: &Path) -> Result<StoredFleetAllocationStateV1, FleetAllocationStoreError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_STATE_BYTES
    {
        return Err(FleetAllocationStoreError::Corrupt(format!(
            "allocation-store state has unsafe type or size: {}",
            path.display()
        )));
    }
    let state: StoredFleetAllocationStateV1 = serde_json::from_slice(&std::fs::read(path)?)
        .map_err(|error| FleetAllocationStoreError::Corrupt(error.to_string()))?;
    state.validate()?;
    Ok(state)
}

fn publish_create_only<T: Serialize>(
    root: &Path,
    final_path: &Path,
    value: &T,
) -> Result<(), FleetAllocationStoreError> {
    let mut bytes = serde_json::to_vec(value)
        .map_err(|error| FleetAllocationStoreError::Encoding(error.to_string()))?;
    bytes.push(b'\n');
    let byte_len = u64::try_from(bytes.len())
        .map_err(|_| FleetAllocationStoreError::CapacityExceeded)?;
    if byte_len > MAX_STATE_BYTES {
        return Err(FleetAllocationStoreError::CapacityExceeded);
    }
    let temp_path = root.join(format!(
        ".allocation-state-{}-{}.tmp",
        std::process::id(),
        STAGING_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    match std::fs::hard_link(&temp_path, final_path) {
        Ok(()) => {}
        Err(error) => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(error.into());
        }
    }
    let _ = std::fs::remove_file(&temp_path);
    sync_directory(root)
}

fn validate_physical_directory(path: &Path) -> Result<(), FleetAllocationStoreError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(FleetAllocationStoreError::Corrupt(format!(
            "allocation-store root is not a physical directory: {}",
            path.display()
        )));
    }
    Ok(())
}

fn digest_json<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<Sha256Digest, FleetAllocationStoreError> {
    let encoded =
        serde_json::to_vec(value).map_err(|error| FleetAllocationStoreError::Encoding(error.to_string()))?;
    let mut bytes = Vec::with_capacity(domain.len() + encoded.len());
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(&encoded);
    Ok(Sha256Digest::for_bytes(&bytes))
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), FleetAllocationStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), FleetAllocationStoreError> {
    Ok(())
}

#[derive(Debug, Error)]
pub enum FleetAllocationStoreError {
    #[error("invalid fleet allocation identifier: {0}")]
    InvalidIdentifier(&'static str),
    #[error("corrupt fleet allocation state: {0}")]
    Corrupt(String),
    #[error("fleet allocation conflict: {0}")]
    Conflict(String),
    #[error("stale allocation-store generation: expected {expected}, current {current}")]
    StaleGeneration { expected: u64, current: u64 },
    #[error("stale host generation for {host_id}: current {current}, proposed {proposed}")]
    StaleHostGeneration {
        host_id: String,
        current: u64,
        proposed: u64,
    },
    #[error("stale fleet authority epoch")]
    StaleAuthorityEpoch,
    #[error("unknown fleet host: {0}")]
    UnknownHost(String),
    #[error("unknown fleet allocation: {0}")]
    UnknownAllocation(String),
    #[error("fleet request exceeds registered Agent resource budget: {0}")]
    AgentBudgetExceeded(AgentId),
    #[error("fleet allocation lease generation is stale: current {current}, proposed {proposed}")]
    StaleLease { current: u64, proposed: u64 },
    #[error("fleet allocation grant is not live")]
    GrantNotLive,
    #[error("fleet allocation capacity exceeded")]
    CapacityExceeded,
    #[error("fleet allocation arithmetic invariant failed")]
    ArithmeticInvariant,
    #[error("invalid fleet allocation holder transition: {current:?} -> {proposed:?}")]
    InvalidHolderTransition {
        current: FleetAllocationHolderStateV1,
        proposed: FleetAllocationHolderStateV1,
    },
    #[error("fleet allocation retention must keep at least one state")]
    InvalidRetention,
    #[error("fleet allocation encoding failed: {0}")]
    Encoding(String),
    #[error(transparent)]
    Placement(#[from] FleetPlacementError),
    #[error(transparent)]
    Authority(#[from] FinalUseError),
    #[error(transparent)]
    Registry(#[from] crate::FleetRegistryError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

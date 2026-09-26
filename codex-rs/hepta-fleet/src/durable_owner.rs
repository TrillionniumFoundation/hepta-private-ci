//! Supervisor-owned durable allocation state.
//!
//! Every committed generation is a self-contained, checksummed snapshot. The
//! existing supervisor state root and one exclusive file lock are the only
//! writer boundary; no second service or allocation writer is introduced.

use crate::AllocationGrant;
use crate::CapacityObservationError;
use crate::FleetAuthorityError;
use crate::FleetAuthorityPort;
use crate::FleetCapacityObserverV1;
use crate::FleetClock;
use crate::FleetClockError;
use crate::FleetRevocationSnapshotV1;
use crate::FleetRevocationSnapshotError;
use crate::GrantUseWitnessV1;
use crate::HostObservation;
use crate::LeaseDisposition;
use crate::LeaseLedger;
use crate::LeaseLedgerSnapshot;
use crate::LeaseOutcome;
use crate::LeaseReceipt;
use crate::ResourceVectorV1;
use crate::TrustedCapacityObservationV1;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

pub const DURABLE_FLEET_STATE_SCHEMA_VERSION: u32 = 1;
pub const MAX_DURABLE_OPERATION_RECEIPTS: usize = 16_384;
const DURABLE_FLEET_DIRECTORY: &str = "fleet-allocation-v1";
const DURABLE_FLEET_LOCK: &str = "owner.lock";
const STATE_FILE_PREFIX: &str = "generation-";
const STATE_FILE_SUFFIX: &str = ".json";
const RETAINED_STATE_GENERATIONS: usize = 8;
static STATE_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[cfg(test)]
const FAILPOINT_NONE: u8 = 0;
#[cfg(test)]
const FAILPOINT_AFTER_STATE_LINK: u8 = 1;

#[cfg(test)]
thread_local! {
    static DURABLE_OWNER_FAILPOINT: std::cell::Cell<u8> = const {
        std::cell::Cell::new(FAILPOINT_NONE)
    };
}

#[cfg(test)]
pub(crate) fn fail_next_commit_after_state_link() {
    DURABLE_OWNER_FAILPOINT.with(|current| current.set(FAILPOINT_AFTER_STATE_LINK));
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetHostRecordV1 {
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FleetOperationKindV1 {
    CapacityObservation,
    Issue,
    Renew,
    Revoke,
    ExpiryReconciliation,
    RevocationSnapshot,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetOperationReceiptV1 {
    pub operation_id: String,
    pub operation_kind: FleetOperationKindV1,
    pub operation_digest: String,
    pub committed_generation: u64,
    pub committed_at_ms: u64,
    pub lease_receipt: Option<LeaseReceipt>,
    pub authority_witness: Option<VerifiedUseTokenWitnessV1>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DurableFleetStateV1 {
    pub schema_version: u32,
    pub generation: u64,
    pub previous_state_sha256: String,
    pub fleet_hosts: BTreeMap<String, FleetHostRecordV1>,
    pub fleet_capacity_observations: BTreeMap<String, TrustedCapacityObservationV1>,
    pub fleet_grants: LeaseLedgerSnapshot,
    pub fleet_resource_totals: BTreeMap<String, ResourceVectorV1>,
    pub fleet_revocation_frontier: Option<FleetRevocationSnapshotV1>,
    pub workspace_reservations_sha256: String,
    pub fleet_operation_receipts: VecDeque<FleetOperationReceiptV1>,
    pub compacted_operation_receipts: u64,
    pub compacted_operation_receipts_sha256: String,
    pub content_sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableFleetMutationReceiptV1 {
    pub generation: u64,
    pub state_sha256: String,
    pub operation: FleetOperationReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableFleetIssueReceiptV1 {
    pub generation: u64,
    pub state_sha256: String,
    pub lease: LeaseReceipt,
    pub authority_witness: VerifiedUseTokenWitnessV1,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct FleetResultCountersV1 {
    pub success: u64,
    pub rejected: u64,
    pub indeterminate: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetOperationalMetricsV1 {
    pub fleet_active_grants: u64,
    pub fleet_expired_uncollected_grants: u64,
    pub fleet_revoked_uncompacted_grants: u64,
    pub fleet_reserved_resource: BTreeMap<String, ResourceVectorV1>,
    pub fleet_observed_capacity: BTreeMap<String, ResourceVectorV1>,
    pub fleet_stale_hosts: u64,
    pub fleet_grant_issue_total: FleetResultCountersV1,
    pub fleet_grant_renew_total: FleetResultCountersV1,
    pub fleet_grant_revoke_total: FleetResultCountersV1,
    pub fleet_revocation_lag_ms: Option<u64>,
    pub fleet_registry_conflict_total: u64,
    pub fleet_indeterminate_commit_total: u64,
    pub fleet_staging_debris: u64,
    pub fleet_compaction_backlog: u64,
}

#[derive(Clone, Copy, Debug, Default)]
struct RuntimeCounters {
    issue: FleetResultCountersV1,
    renew: FleetResultCountersV1,
    revoke: FleetResultCountersV1,
    registry_conflicts: u64,
    indeterminate_commits: u64,
}

pub struct DurableFleetOwner {
    root: PathBuf,
    supervisor_state_root: PathBuf,
    clock: Arc<dyn FleetClock>,
    state: DurableFleetStateV1,
    counters: RuntimeCounters,
}

impl fmt::Debug for DurableFleetOwner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableFleetOwner")
            .field("root", &self.root)
            .field("generation", &self.state.generation)
            .finish()
    }
}

impl DurableFleetOwner {
    pub fn open_supervisor_state_root(
        supervisor_state_root: impl Into<PathBuf>,
        clock: Arc<dyn FleetClock>,
    ) -> Result<Self, DurableFleetError> {
        let supervisor_state_root = supervisor_state_root.into();
        validate_physical_directory(&supervisor_state_root)?;
        let root = supervisor_state_root.join(DURABLE_FLEET_DIRECTORY);
        create_private_directory_all(&root)?;
        validate_physical_directory(&root)?;
        let _guard = OwnerLock::acquire(&root.join(DURABLE_FLEET_LOCK))?;
        let workspace_reservations_sha256 =
            workspace_reservation_file_digest(&supervisor_state_root)?;
        let state = match load_latest_state(&root)? {
            Some(state) => state,
            None => {
                let mut state = initial_state(workspace_reservations_sha256);
                state.content_sha256 = state_digest(&state)?;
                publish_state(&root, &state).map_err(|error| error.into_durable("initialize"))?;
                state
            }
        };
        validate_state(&state, Arc::clone(&clock))?;
        Ok(Self {
            root,
            supervisor_state_root,
            clock,
            state,
            counters: RuntimeCounters::default(),
        })
    }

    pub fn state(&self) -> &DurableFleetStateV1 {
        &self.state
    }

    pub fn refresh_capacity<O: FleetCapacityObserverV1>(
        &mut self,
        operation_id: &str,
        observer: &O,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let now_ms = self.clock.now_unix_ms()?;
        let observation = observer.observe(now_ms)?;
        observation.validate()?;
        let digest = operation_digest(
            b"capacity-observation",
            &(operation_id, &observation),
        )?;
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        if let Some(receipt) = self.existing_operation(operation_id, &digest)? {
            return self.mutation_receipt(receipt);
        }
        let mut ledger = LeaseLedger::from_snapshot(
            Arc::clone(&self.clock),
            self.state.fleet_grants.clone(),
        )?;
        let host = observation.host_observation()?;
        ledger.admit_host(host)?;
        let mut candidate = self.state.clone();
        candidate.fleet_hosts.insert(
            observation.host_id.clone(),
            FleetHostRecordV1 {
                host_id: observation.host_id.clone(),
                failure_domain_id: observation.failure_domain_id.clone(),
                generation: observation.host_generation,
            },
        );
        candidate
            .fleet_capacity_observations
            .insert(observation.host_id.clone(), observation);
        candidate.fleet_grants = ledger.snapshot();
        candidate.fleet_resource_totals = ledger.metrics()?.reserved_by_host;
        let operation = FleetOperationReceiptV1 {
            operation_id: operation_id.to_string(),
            operation_kind: FleetOperationKindV1::CapacityObservation,
            operation_digest: digest,
            committed_generation: next_generation(candidate.generation)?,
            committed_at_ms: now_ms,
            lease_receipt: None,
            authority_witness: None,
        };
        append_operation(&mut candidate, operation.clone())?;
        self.commit(candidate, operation)
    }

    pub fn issue_with_authority(
        &mut self,
        operation_id: &str,
        authority: &FleetAuthorityPort,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: AllocationGrant,
    ) -> Result<DurableFleetIssueReceiptV1, DurableFleetError> {
        let digest = operation_digest(
            b"issue",
            &(
                operation_id,
                lease_id,
                expected_lease_revision,
                &grant,
            ),
        )?;
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        if let Some(operation) = self.existing_operation(operation_id, &digest)? {
            return issue_receipt_from_operation(&self.state, operation);
        }
        let mut ledger = LeaseLedger::from_snapshot(
            Arc::clone(&self.clock),
            self.state.fleet_grants.clone(),
        )?;
        let issue = authority.issue_with_witness(
            &mut ledger,
            lease_id,
            expected_lease_revision,
            grant,
        );
        let (lease, witness) = match issue {
            Ok(value) => value,
            Err(error) => {
                self.counters.issue.rejected = self.counters.issue.rejected.saturating_add(1);
                return Err(error.into());
            }
        };
        witness
            .validate()
            .map_err(|_| DurableFleetError::InvalidAuthorityWitness)?;
        let now_ms = self.clock.now_unix_ms()?;
        let mut candidate = self.state.clone();
        candidate.fleet_grants = ledger.snapshot();
        candidate.fleet_resource_totals = ledger.metrics()?.reserved_by_host;
        let operation = FleetOperationReceiptV1 {
            operation_id: operation_id.to_string(),
            operation_kind: FleetOperationKindV1::Issue,
            operation_digest: digest,
            committed_generation: next_generation(candidate.generation)?,
            committed_at_ms: now_ms,
            lease_receipt: Some(lease.clone()),
            authority_witness: Some(witness.clone()),
        };
        append_operation(&mut candidate, operation.clone())?;
        match self.commit(candidate, operation) {
            Ok(receipt) => {
                self.counters.issue.success = self.counters.issue.success.saturating_add(1);
                Ok(DurableFleetIssueReceiptV1 {
                    generation: receipt.generation,
                    state_sha256: receipt.state_sha256,
                    lease,
                    authority_witness: witness,
                })
            }
            Err(error) => {
                if matches!(error, DurableFleetError::IndeterminateCommit { .. }) {
                    self.counters.issue.indeterminate =
                        self.counters.issue.indeterminate.saturating_add(1);
                    self.counters.indeterminate_commits =
                        self.counters.indeterminate_commits.saturating_add(1);
                }
                Err(error)
            }
        }
    }

    pub fn renew_or_revoke(
        &mut self,
        operation_id: &str,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let disposition_digest = match disposition {
            LeaseDisposition::Renew { expires_at_ms } => {
                format!("renew:{expires_at_ms}")
            }
            LeaseDisposition::Revoke => "revoke".to_string(),
        };
        let digest = operation_digest(
            b"renew-or-revoke",
            &(
                operation_id,
                allocation_id,
                expected_lease_generation,
                authority_epoch,
                semantic_digest,
                &disposition_digest,
            ),
        )?;
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        if let Some(receipt) = self.existing_operation(operation_id, &digest)? {
            return self.mutation_receipt(receipt);
        }
        let mut ledger = LeaseLedger::from_snapshot(
            Arc::clone(&self.clock),
            self.state.fleet_grants.clone(),
        )?;
        let lease = ledger.renew_or_revoke(
            allocation_id,
            expected_lease_generation,
            authority_epoch,
            semantic_digest,
            disposition,
        );
        let lease = match lease {
            Ok(value) => value,
            Err(error) => {
                let counters = if disposition_digest == "revoke" {
                    &mut self.counters.revoke
                } else {
                    &mut self.counters.renew
                };
                counters.rejected = counters.rejected.saturating_add(1);
                return Err(error.into());
            }
        };
        let kind = if lease.outcome == LeaseOutcome::Revoked {
            FleetOperationKindV1::Revoke
        } else {
            FleetOperationKindV1::Renew
        };
        let now_ms = self.clock.now_unix_ms()?;
        let mut candidate = self.state.clone();
        candidate.fleet_grants = ledger.snapshot();
        candidate.fleet_resource_totals = ledger.metrics()?.reserved_by_host;
        let operation = FleetOperationReceiptV1 {
            operation_id: operation_id.to_string(),
            operation_kind: kind,
            operation_digest: digest,
            committed_generation: next_generation(candidate.generation)?,
            committed_at_ms: now_ms,
            lease_receipt: Some(lease),
            authority_witness: None,
        };
        append_operation(&mut candidate, operation.clone())?;
        let result = self.commit(candidate, operation);
        let counters = if kind == FleetOperationKindV1::Revoke {
            &mut self.counters.revoke
        } else {
            &mut self.counters.renew
        };
        match &result {
            Ok(_) => counters.success = counters.success.saturating_add(1),
            Err(DurableFleetError::IndeterminateCommit { .. }) => {
                counters.indeterminate = counters.indeterminate.saturating_add(1);
                self.counters.indeterminate_commits =
                    self.counters.indeterminate_commits.saturating_add(1);
            }
            Err(_) => counters.rejected = counters.rejected.saturating_add(1),
        }
        result
    }

    pub fn reconcile_expired(
        &mut self,
        operation_id: &str,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let now_ms = self.clock.now_unix_ms()?;
        let digest = operation_digest(b"expiry-reconciliation", &(operation_id, now_ms))?;
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        if let Some(receipt) = self.existing_operation(operation_id, &digest)? {
            return self.mutation_receipt(receipt);
        }
        let mut ledger = LeaseLedger::from_snapshot(
            Arc::clone(&self.clock),
            self.state.fleet_grants.clone(),
        )?;
        ledger.collect_expired()?;
        let mut candidate = self.state.clone();
        candidate.fleet_grants = ledger.snapshot();
        candidate.fleet_resource_totals = ledger.metrics()?.reserved_by_host;
        let operation = FleetOperationReceiptV1 {
            operation_id: operation_id.to_string(),
            operation_kind: FleetOperationKindV1::ExpiryReconciliation,
            operation_digest: digest,
            committed_generation: next_generation(candidate.generation)?,
            committed_at_ms: now_ms,
            lease_receipt: None,
            authority_witness: None,
        };
        append_operation(&mut candidate, operation.clone())?;
        self.commit(candidate, operation)
    }

    pub fn persist_revocation_snapshot(
        &mut self,
        operation_id: &str,
        snapshot: FleetRevocationSnapshotV1,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        snapshot.validate_shape()?;
        let digest = operation_digest(b"revocation-snapshot", &(operation_id, &snapshot))?;
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        if let Some(receipt) = self.existing_operation(operation_id, &digest)? {
            return self.mutation_receipt(receipt);
        }
        let now_ms = self.clock.now_unix_ms()?;
        let mut candidate = self.state.clone();
        candidate.fleet_revocation_frontier = Some(snapshot);
        let operation = FleetOperationReceiptV1 {
            operation_id: operation_id.to_string(),
            operation_kind: FleetOperationKindV1::RevocationSnapshot,
            operation_digest: digest,
            committed_generation: next_generation(candidate.generation)?,
            committed_at_ms: now_ms,
            lease_receipt: None,
            authority_witness: None,
        };
        append_operation(&mut candidate, operation.clone())?;
        self.commit(candidate, operation)
    }

    pub fn verify_final_use(
        &mut self,
        allocation_id: &str,
        expected_lease_generation: u64,
        expected_host_id: &str,
        expected_host_generation: u64,
        semantic_digest: &str,
    ) -> Result<GrantUseWitnessV1, DurableFleetError> {
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        let ledger = LeaseLedger::from_snapshot(
            Arc::clone(&self.clock),
            self.state.fleet_grants.clone(),
        )?;
        FleetAuthorityPort::verify_final_use(
            &ledger,
            allocation_id,
            expected_lease_generation,
            expected_host_id,
            expected_host_generation,
            semantic_digest,
        )
        .map_err(Into::into)
    }

    pub fn metrics(&mut self) -> Result<FleetOperationalMetricsV1, DurableFleetError> {
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        let now_ms = self.clock.now_unix_ms()?;
        let ledger = LeaseLedger::from_snapshot(
            Arc::clone(&self.clock),
            self.state.fleet_grants.clone(),
        )?;
        let ledger_metrics = ledger.metrics()?;
        let observed_capacity = self
            .state
            .fleet_capacity_observations
            .iter()
            .map(|(host_id, observation)| (host_id.clone(), observation.capacity))
            .collect();
        let stale_hosts = self
            .state
            .fleet_capacity_observations
            .values()
            .filter(|observation| observation.valid_until_ms <= now_ms)
            .count();
        let revocation_lag = self
            .state
            .fleet_revocation_frontier
            .as_ref()
            .and_then(|snapshot| snapshot.current_update.as_ref())
            .map(|update| now_ms.saturating_sub(update.update.issued_at_unix_ms));
        Ok(FleetOperationalMetricsV1 {
            fleet_active_grants: usize_to_u64(ledger_metrics.active_grants)?,
            fleet_expired_uncollected_grants: usize_to_u64(
                ledger_metrics.expired_uncollected_grants,
            )?,
            fleet_revoked_uncompacted_grants: usize_to_u64(
                ledger_metrics.revoked_uncompacted_grants,
            )?,
            fleet_reserved_resource: ledger_metrics.reserved_by_host,
            fleet_observed_capacity: observed_capacity,
            fleet_stale_hosts: usize_to_u64(stale_hosts)?,
            fleet_grant_issue_total: self.counters.issue,
            fleet_grant_renew_total: self.counters.renew,
            fleet_grant_revoke_total: self.counters.revoke,
            fleet_revocation_lag_ms: revocation_lag,
            fleet_registry_conflict_total: self.counters.registry_conflicts,
            fleet_indeterminate_commit_total: self.counters.indeterminate_commits,
            fleet_staging_debris: staging_debris(&self.supervisor_state_root)?,
            fleet_compaction_backlog: generation_backlog(&self.root)?,
        })
    }

    pub fn note_registry_conflict(&mut self) {
        self.counters.registry_conflicts = self.counters.registry_conflicts.saturating_add(1);
    }

    pub fn note_indeterminate_commit(&mut self) {
        self.counters.indeterminate_commits =
            self.counters.indeterminate_commits.saturating_add(1);
    }

    fn reload(&mut self) -> Result<(), DurableFleetError> {
        let state = load_latest_state(&self.root)?.ok_or(DurableFleetError::MissingState)?;
        validate_state(&state, Arc::clone(&self.clock))?;
        self.state = state;
        Ok(())
    }

    fn existing_operation(
        &self,
        operation_id: &str,
        operation_digest: &str,
    ) -> Result<Option<FleetOperationReceiptV1>, DurableFleetError> {
        validate_operation_id(operation_id)?;
        match self
            .state
            .fleet_operation_receipts
            .iter()
            .find(|receipt| receipt.operation_id == operation_id)
        {
            Some(receipt) if receipt.operation_digest == operation_digest => {
                Ok(Some(receipt.clone()))
            }
            Some(_) => Err(DurableFleetError::OperationConflict(
                operation_id.to_string(),
            )),
            None => Ok(None),
        }
    }

    fn mutation_receipt(
        &self,
        operation: FleetOperationReceiptV1,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        Ok(DurableFleetMutationReceiptV1 {
            generation: operation.committed_generation,
            state_sha256: self.state.content_sha256.clone(),
            operation,
        })
    }

    fn commit(
        &mut self,
        mut candidate: DurableFleetStateV1,
        operation: FleetOperationReceiptV1,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        candidate.generation = next_generation(self.state.generation)?;
        candidate.previous_state_sha256 = self.state.content_sha256.clone();
        candidate.workspace_reservations_sha256 =
            workspace_reservation_file_digest(&self.supervisor_state_root)?;
        candidate.content_sha256.clear();
        candidate.content_sha256 = state_digest(&candidate)?;
        validate_state(&candidate, Arc::clone(&self.clock))?;
        match publish_state(&self.root, &candidate) {
            Ok(()) => {}
            Err(error) => {
                if error.published {
                    return Err(DurableFleetError::IndeterminateCommit {
                        operation_id: operation.operation_id,
                        generation: candidate.generation,
                        detail: error.source.to_string(),
                    });
                }
                return Err(error.source.into());
            }
        }
        self.state = candidate;
        let _ = compact_generation_files(&self.root);
        Ok(DurableFleetMutationReceiptV1 {
            generation: self.state.generation,
            state_sha256: self.state.content_sha256.clone(),
            operation,
        })
    }
}

fn initial_state(workspace_reservations_sha256: String) -> DurableFleetStateV1 {
    let ledger = LeaseLedger::new();
    DurableFleetStateV1 {
        schema_version: DURABLE_FLEET_STATE_SCHEMA_VERSION,
        generation: 0,
        previous_state_sha256: state_anchor_digest(),
        fleet_hosts: BTreeMap::new(),
        fleet_capacity_observations: BTreeMap::new(),
        fleet_grants: ledger.snapshot(),
        fleet_resource_totals: BTreeMap::new(),
        fleet_revocation_frontier: None,
        workspace_reservations_sha256,
        fleet_operation_receipts: VecDeque::new(),
        compacted_operation_receipts: 0,
        compacted_operation_receipts_sha256: operation_anchor_digest(),
        content_sha256: String::new(),
    }
}

fn validate_state(
    state: &DurableFleetStateV1,
    clock: Arc<dyn FleetClock>,
) -> Result<(), DurableFleetError> {
    if state.schema_version != DURABLE_FLEET_STATE_SCHEMA_VERSION
        || state.fleet_operation_receipts.len() > MAX_DURABLE_OPERATION_RECEIPTS
        || !valid_digest(&state.previous_state_sha256)
        || !valid_digest(&state.workspace_reservations_sha256)
        || !valid_digest(&state.compacted_operation_receipts_sha256)
        || state.content_sha256 != state_digest(state)?
    {
        return Err(DurableFleetError::CorruptState);
    }
    let mut operation_ids = BTreeSet::new();
    for receipt in &state.fleet_operation_receipts {
        validate_operation_id(&receipt.operation_id)?;
        if !valid_digest(&receipt.operation_digest)
            || receipt.committed_generation == 0
            || receipt.committed_generation > state.generation
            || !operation_ids.insert(receipt.operation_id.as_str())
        {
            return Err(DurableFleetError::CorruptState);
        }
        if let Some(witness) = &receipt.authority_witness {
            witness
                .validate()
                .map_err(|_| DurableFleetError::CorruptState)?;
        }
    }
    if let Some(snapshot) = &state.fleet_revocation_frontier {
        snapshot.validate_shape()?;
    }
    let ledger = LeaseLedger::from_snapshot(clock, state.fleet_grants.clone())?;
    if ledger.metrics()?.reserved_by_host != state.fleet_resource_totals {
        return Err(DurableFleetError::CorruptState);
    }
    if state.fleet_hosts.len() != state.fleet_capacity_observations.len()
        || state.fleet_hosts.len() != state.fleet_grants.hosts.len()
    {
        return Err(DurableFleetError::CorruptState);
    }
    for (host_id, observation) in &state.fleet_capacity_observations {
        observation.validate()?;
        let host = state
            .fleet_hosts
            .get(host_id)
            .ok_or(DurableFleetError::CorruptState)?;
        let ledger_host = state
            .fleet_grants
            .hosts
            .get(host_id)
            .ok_or(DurableFleetError::CorruptState)?;
        if host.host_id != observation.host_id
            || host.failure_domain_id != observation.failure_domain_id
            || host.generation != observation.host_generation
            || ledger_host != &observation.host_observation()?
        {
            return Err(DurableFleetError::CorruptState);
        }
    }
    Ok(())
}

fn append_operation(
    state: &mut DurableFleetStateV1,
    operation: FleetOperationReceiptV1,
) -> Result<(), DurableFleetError> {
    state.fleet_operation_receipts.push_back(operation);
    while state.fleet_operation_receipts.len() > MAX_DURABLE_OPERATION_RECEIPTS {
        let removed = state
            .fleet_operation_receipts
            .pop_front()
            .ok_or(DurableFleetError::CorruptState)?;
        let encoded = serde_json::to_vec(&removed)?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.fleet.operation-receipt-chain.v1\0");
        digest.update(state.compacted_operation_receipts_sha256.as_bytes());
        digest.update(encoded);
        state.compacted_operation_receipts_sha256 = format!("{:x}", digest.finalize());
        state.compacted_operation_receipts = state
            .compacted_operation_receipts
            .checked_add(1)
            .ok_or(DurableFleetError::ArithmeticOverflow)?;
    }
    Ok(())
}

fn issue_receipt_from_operation(
    state: &DurableFleetStateV1,
    operation: FleetOperationReceiptV1,
) -> Result<DurableFleetIssueReceiptV1, DurableFleetError> {
    let lease = operation
        .lease_receipt
        .ok_or(DurableFleetError::CorruptState)?;
    let authority_witness = operation
        .authority_witness
        .ok_or(DurableFleetError::CorruptState)?;
    Ok(DurableFleetIssueReceiptV1 {
        generation: operation.committed_generation,
        state_sha256: state.content_sha256.clone(),
        lease,
        authority_witness,
    })
}

fn operation_digest<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<String, DurableFleetError> {
    let encoded = serde_json::to_vec(value)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.operation.v1\0");
    digest.update(domain);
    digest.update([0]);
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}

fn state_digest(state: &DurableFleetStateV1) -> Result<String, DurableFleetError> {
    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    let encoded = serde_json::to_vec(&candidate)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.durable-state.v1\0");
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}

fn state_anchor_digest() -> String {
    format!("{:x}", Sha256::digest(b"hepta.runtime.fleet.state-anchor.v1"))
}

fn operation_anchor_digest() -> String {
    format!(
        "{:x}",
        Sha256::digest(b"hepta.runtime.fleet.operation-anchor.v1")
    )
}

fn workspace_reservation_file_digest(
    supervisor_state_root: &Path,
) -> Result<String, DurableFleetError> {
    let path = supervisor_state_root.join("workspace-reservations-v1.json");
    match std::fs::read(path) {
        Ok(bytes) => Ok(format!("{:x}", Sha256::digest(bytes))),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(format!(
            "{:x}",
            Sha256::digest(b"hepta.runtime.fleet.no-workspace-reservations.v1")
        )),
        Err(error) => Err(error.into()),
    }
}

fn publish_state(root: &Path, state: &DurableFleetStateV1) -> Result<(), PublishStateError> {
    let final_path = state_path(root, state.generation);
    let temp_path = root.join(format!(
        ".state-{}-{}-{}.tmp",
        state.generation,
        std::process::id(),
        STATE_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut encoded = serde_json::to_vec(state).map_err(PublishStateError::before_encode)?;
    encoded.push(b'\n');
    let before = (|| -> Result<(), std::io::Error> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)?;
        file.write_all(&encoded)?;
        file.sync_all()?;
        std::fs::hard_link(&temp_path, &final_path)?;
        let _ = std::fs::remove_file(&temp_path);
        Ok(())
    })();
    if let Err(source) = before {
        let _ = std::fs::remove_file(&temp_path);
        return Err(PublishStateError {
            published: final_path.exists(),
            source,
        });
    }
    if let Err(source) = fail_after_state_link().and_then(|()| sync_directory(root)) {
        return Err(PublishStateError {
            published: true,
            source,
        });
    }
    Ok(())
}

fn load_latest_state(root: &Path) -> Result<Option<DurableFleetStateV1>, DurableFleetError> {
    let mut generations = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            return Err(DurableFleetError::CorruptState);
        };
        if let Some(generation) = parse_state_generation(&name)? {
            generations.push((generation, entry.path()));
        }
    }
    generations.sort_unstable_by_key(|(generation, _)| *generation);
    let mut previous: Option<DurableFleetStateV1> = None;
    for (generation, path) in generations {
        let metadata = std::fs::symlink_metadata(&path)?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(DurableFleetError::CorruptState);
        }
        let state: DurableFleetStateV1 = serde_json::from_slice(&std::fs::read(path)?)?;
        if state.generation != generation || state.content_sha256 != state_digest(&state)? {
            return Err(DurableFleetError::CorruptState);
        }
        if let Some(earlier) = &previous {
            if state.generation != earlier.generation + 1
                || state.previous_state_sha256 != earlier.content_sha256
            {
                return Err(DurableFleetError::CorruptState);
            }
        }
        previous = Some(state);
    }
    Ok(previous)
}

fn compact_generation_files(root: &Path) -> Result<(), DurableFleetError> {
    let mut generations = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            return Err(DurableFleetError::CorruptState);
        };
        if let Some(generation) = parse_state_generation(&name)? {
            generations.push((generation, entry.path()));
        }
    }
    generations.sort_unstable_by_key(|(generation, _)| *generation);
    let remove = generations.len().saturating_sub(RETAINED_STATE_GENERATIONS);
    for (_, path) in generations.into_iter().take(remove) {
        std::fs::remove_file(path)?;
    }
    if remove > 0 {
        sync_directory(root)?;
    }
    Ok(())
}

fn generation_backlog(root: &Path) -> Result<u64, DurableFleetError> {
    let count = std::fs::read_dir(root)?
        .filter_map(Result::ok)
        .filter(|entry| {
            entry
                .file_name()
                .to_str()
                .is_some_and(|name| name.starts_with(STATE_FILE_PREFIX))
        })
        .count()
        .saturating_sub(RETAINED_STATE_GENERATIONS);
    usize_to_u64(count)
}

fn staging_debris(supervisor_state_root: &Path) -> Result<u64, DurableFleetError> {
    let Some(fleet_root) = supervisor_state_root.parent() else {
        return Err(DurableFleetError::InvalidPath);
    };
    let agents_root = fleet_root.join("agents");
    match std::fs::read_dir(agents_root) {
        Ok(entries) => usize_to_u64(
            entries
                .filter_map(Result::ok)
                .filter(|entry| {
                    entry
                        .file_name()
                        .to_str()
                        .is_some_and(|name| name.starts_with(".staging-"))
                })
                .count(),
        ),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(0),
        Err(error) => Err(error.into()),
    }
}

fn parse_state_generation(name: &str) -> Result<Option<u64>, DurableFleetError> {
    if !name.starts_with(STATE_FILE_PREFIX) {
        return Ok(None);
    }
    let value = name
        .strip_prefix(STATE_FILE_PREFIX)
        .and_then(|value| value.strip_suffix(STATE_FILE_SUFFIX))
        .filter(|value| value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit()))
        .ok_or(DurableFleetError::CorruptState)?;
    value
        .parse::<u64>()
        .map(Some)
        .map_err(|_| DurableFleetError::CorruptState)
}

fn state_path(root: &Path, generation: u64) -> PathBuf {
    root.join(format!(
        "{STATE_FILE_PREFIX}{generation:020}{STATE_FILE_SUFFIX}"
    ))
}

fn next_generation(generation: u64) -> Result<u64, DurableFleetError> {
    generation
        .checked_add(1)
        .ok_or(DurableFleetError::ArithmeticOverflow)
}

fn validate_operation_id(value: &str) -> Result<(), DurableFleetError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(DurableFleetError::InvalidOperationId);
    }
    Ok(())
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn usize_to_u64(value: usize) -> Result<u64, DurableFleetError> {
    u64::try_from(value).map_err(|_| DurableFleetError::ArithmeticOverflow)
}

struct OwnerLock {
    _file: File,
}

impl OwnerLock {
    fn acquire(path: &Path) -> Result<Self, DurableFleetError> {
        let file = open_private_lock_file(path)?;
        file.lock()?;
        Ok(Self { _file: file })
    }
}

struct PublishStateError {
    published: bool,
    source: std::io::Error,
}

impl PublishStateError {
    fn before_encode(error: serde_json::Error) -> Self {
        Self {
            published: false,
            source: std::io::Error::new(ErrorKind::InvalidData, error),
        }
    }

    fn into_durable(self, operation_id: &str) -> DurableFleetError {
        if self.published {
            DurableFleetError::IndeterminateCommit {
                operation_id: operation_id.to_string(),
                generation: 0,
                detail: self.source.to_string(),
            }
        } else {
            self.source.into()
        }
    }
}

#[derive(Debug)]
pub enum DurableFleetError {
    InvalidPath,
    InvalidOperationId,
    InvalidAuthorityWitness,
    MissingState,
    CorruptState,
    ArithmeticOverflow,
    OperationConflict(String),
    IndeterminateCommit {
        operation_id: String,
        generation: u64,
        detail: String,
    },
    Clock(FleetClockError),
    Capacity(CapacityObservationError),
    Ledger(crate::lease_ledger::Error),
    Authority(FleetAuthorityError),
    Revocation(FleetRevocationSnapshotError),
    Json(serde_json::Error),
    Io(std::io::Error),
}

impl fmt::Display for DurableFleetError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for DurableFleetError {}

impl From<FleetClockError> for DurableFleetError {
    fn from(value: FleetClockError) -> Self {
        Self::Clock(value)
    }
}

impl From<CapacityObservationError> for DurableFleetError {
    fn from(value: CapacityObservationError) -> Self {
        Self::Capacity(value)
    }
}

impl From<crate::lease_ledger::Error> for DurableFleetError {
    fn from(value: crate::lease_ledger::Error) -> Self {
        Self::Ledger(value)
    }
}

impl From<FleetAuthorityError> for DurableFleetError {
    fn from(value: FleetAuthorityError) -> Self {
        Self::Authority(value)
    }
}

impl From<FleetRevocationSnapshotError> for DurableFleetError {
    fn from(value: FleetRevocationSnapshotError) -> Self {
        Self::Revocation(value)
    }
}

impl From<serde_json::Error> for DurableFleetError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

impl From<std::io::Error> for DurableFleetError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

#[cfg(unix)]
fn create_private_directory_all(path: &Path) -> Result<(), DurableFleetError> {
    use std::os::unix::fs::PermissionsExt;

    std::fs::create_dir_all(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    Ok(())
}

#[cfg(not(unix))]
fn create_private_directory_all(path: &Path) -> Result<(), DurableFleetError> {
    std::fs::create_dir_all(path)?;
    Ok(())
}

fn validate_physical_directory(path: &Path) -> Result<(), DurableFleetError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(DurableFleetError::InvalidPath);
    }
    Ok(())
}

#[cfg(unix)]
fn open_private_lock_file(path: &Path) -> Result<File, DurableFleetError> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(file)
}

#[cfg(not(unix))]
fn open_private_lock_file(path: &Path) -> Result<File, DurableFleetError> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .map_err(Into::into)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> std::io::Result<()> {
    File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> std::io::Result<()> {
    Ok(())
}

fn fail_after_state_link() -> std::io::Result<()> {
    #[cfg(test)]
    {
        let triggered = DURABLE_OWNER_FAILPOINT.with(|current| {
            if current.get() == FAILPOINT_AFTER_STATE_LINK {
                current.set(FAILPOINT_NONE);
                true
            } else {
                false
            }
        });
        if triggered {
            return Err(std::io::Error::other(
                "injected failure after durable state link",
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "durable_owner_tests.rs"]
mod tests;

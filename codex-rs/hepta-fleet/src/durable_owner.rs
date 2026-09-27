//! Preflight wrapper for the supervisor-owned durable Fleet state.
//!
//! `durable_owner_frontier.rs` owns the immutable-generation and monotonic
//! frontier implementation. This outer layer performs a non-mutating structural
//! preflight before that implementation may initialize state. In particular, a
//! surviving frontier with every generation deleted is corruption and must not
//! be "repaired" by creating a new generation zero.

#[path = "durable_owner_frontier.rs"]
mod frontier;

pub use frontier::DURABLE_FLEET_STATE_SCHEMA_VERSION;
pub use frontier::DurableFleetError;
pub use frontier::DurableFleetIssueReceiptV1;
pub use frontier::DurableFleetMutationReceiptV1;
pub use frontier::DurableFleetStateV1;
pub use frontier::FleetHostRecordV1;
pub use frontier::FleetOperationKindV1;
pub use frontier::FleetOperationReceiptV1;
pub use frontier::FleetOperationalMetricsV1;
pub use frontier::FleetResultCountersV1;
pub use frontier::MAX_DURABLE_OPERATION_RECEIPTS;

#[cfg(test)]
pub(crate) use frontier::fail_next_commit_after_state_link;

use crate::AllocationGrant;
use crate::FleetAuthorityPort;
use crate::FleetCapacityObserverV1;
use crate::FleetClock;
use crate::FleetRevocationSnapshotV1;
use crate::GrantUseWitnessV1;
use crate::LeaseDisposition;
use std::fmt;
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

const DURABLE_FLEET_DIRECTORY: &str = "fleet-allocation-v1";
const STATE_FILE_PREFIX: &str = "generation-";
const STATE_FILE_SUFFIX: &str = ".json";
const LATEST_FRONTIER_FILE: &str = "latest-frontier-v1.json";

pub struct DurableFleetOwner {
    inner: frontier::DurableFleetOwner,
}

impl fmt::Debug for DurableFleetOwner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableFleetOwner")
            .field("generation", &self.inner.state().generation)
            .finish()
    }
}

impl DurableFleetOwner {
    pub fn open_supervisor_state_root(
        supervisor_state_root: impl Into<PathBuf>,
        clock: Arc<dyn FleetClock>,
    ) -> Result<Self, DurableFleetError> {
        let supervisor_state_root = supervisor_state_root.into();
        preflight_existing_frontier(&supervisor_state_root)?;
        let inner = frontier::DurableFleetOwner::open_supervisor_state_root(
            supervisor_state_root,
            clock,
        )?;
        Ok(Self { inner })
    }

    pub fn state(&self) -> &DurableFleetStateV1 {
        self.inner.state()
    }

    pub fn refresh_capacity<O: FleetCapacityObserverV1>(
        &mut self,
        operation_id: &str,
        observer: &O,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        self.inner.refresh_capacity(operation_id, observer)
    }

    pub fn issue_with_authority(
        &mut self,
        operation_id: &str,
        authority: &FleetAuthorityPort,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: AllocationGrant,
    ) -> Result<DurableFleetIssueReceiptV1, DurableFleetError> {
        self.inner.issue_with_authority(
            operation_id,
            authority,
            lease_id,
            expected_lease_revision,
            grant,
        )
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
        self.inner.renew_or_revoke(
            operation_id,
            allocation_id,
            expected_lease_generation,
            authority_epoch,
            semantic_digest,
            disposition,
        )
    }

    pub fn reconcile_expired(
        &mut self,
        operation_id: &str,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        self.inner.reconcile_expired(operation_id)
    }

    pub fn persist_revocation_snapshot(
        &mut self,
        operation_id: &str,
        snapshot: FleetRevocationSnapshotV1,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        self.inner
            .persist_revocation_snapshot(operation_id, snapshot)
    }

    pub fn verify_final_use(
        &mut self,
        allocation_id: &str,
        expected_lease_generation: u64,
        expected_host_id: &str,
        expected_host_generation: u64,
        semantic_digest: &str,
    ) -> Result<GrantUseWitnessV1, DurableFleetError> {
        self.inner.verify_final_use(
            allocation_id,
            expected_lease_generation,
            expected_host_id,
            expected_host_generation,
            semantic_digest,
        )
    }

    pub fn metrics(&mut self) -> Result<FleetOperationalMetricsV1, DurableFleetError> {
        self.inner.metrics()
    }

    pub fn note_registry_conflict(&mut self) {
        self.inner.note_registry_conflict();
    }

    pub fn note_indeterminate_commit(&mut self) {
        self.inner.note_indeterminate_commit();
    }
}

fn preflight_existing_frontier(supervisor_state_root: &Path) -> Result<(), DurableFleetError> {
    let owner_root = supervisor_state_root.join(DURABLE_FLEET_DIRECTORY);
    let owner_metadata = match std::fs::symlink_metadata(&owner_root) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    if !owner_metadata.file_type().is_dir() || owner_metadata.file_type().is_symlink() {
        return Err(DurableFleetError::CorruptState);
    }

    let frontier_path = owner_root.join(LATEST_FRONTIER_FILE);
    let frontier_metadata = match std::fs::symlink_metadata(&frontier_path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.into()),
    };
    if !frontier_metadata.file_type().is_file() || frontier_metadata.file_type().is_symlink() {
        return Err(DurableFleetError::CorruptState);
    }

    let mut generation_found = false;
    for entry in std::fs::read_dir(&owner_root)? {
        let entry = entry?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            return Err(DurableFleetError::CorruptState);
        };
        if !is_generation_name(&name) {
            continue;
        }
        let metadata = std::fs::symlink_metadata(entry.path())?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(DurableFleetError::CorruptState);
        }
        generation_found = true;
    }
    if !generation_found {
        return Err(DurableFleetError::CorruptState);
    }
    Ok(())
}

fn is_generation_name(name: &str) -> bool {
    name.strip_prefix(STATE_FILE_PREFIX)
        .and_then(|value| value.strip_suffix(STATE_FILE_SUFFIX))
        .is_some_and(|value| {
            value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit())
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SystemFleetClock;

    #[test]
    fn surviving_frontier_without_generations_fails_without_reinitializing() {
        let directory = tempfile::tempdir().expect("tempdir");
        let state_root = directory.path().join("state");
        std::fs::create_dir(&state_root).expect("state root");
        let owner = DurableFleetOwner::open_supervisor_state_root(
            &state_root,
            Arc::new(SystemFleetClock),
        )
        .expect("initial owner");
        assert_eq!(owner.state().generation, 0);
        drop(owner);

        let owner_root = state_root.join(DURABLE_FLEET_DIRECTORY);
        let generation_zero = owner_root.join(format!(
            "{STATE_FILE_PREFIX}{:020}{STATE_FILE_SUFFIX}",
            0
        ));
        std::fs::remove_file(&generation_zero).expect("delete generation zero");

        assert!(matches!(
            DurableFleetOwner::open_supervisor_state_root(
                &state_root,
                Arc::new(SystemFleetClock),
            ),
            Err(DurableFleetError::CorruptState)
        ));
        assert!(
            !generation_zero.exists(),
            "preflight failure must not recreate generation zero"
        );
    }
}

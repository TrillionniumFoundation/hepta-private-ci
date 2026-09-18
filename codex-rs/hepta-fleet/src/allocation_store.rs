use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::FleetRegistry;
use crate::lease_ledger::{AllocationGrant, Error as LeaseError, HostObservation, LeaseDisposition, LeaseLedger, LeaseReceipt};

const STORE_SCHEMA_VERSION: u32 = 1;
const MAX_STORE_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Debug, Error)]
pub enum FleetAllocationStoreError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Lease(#[from] LeaseError),
    #[error("unsupported fleet allocation store schema {0}")]
    Schema(u32),
    #[error("fleet allocation store exceeds byte limit")]
    Oversize,
    #[error("fleet allocation store is fenced after an uncertain durable write")]
    Fenced,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Snapshot {
    schema_version: u32,
    revision: u64,
    ledger: LeaseLedger,
}

#[derive(Debug)]
pub struct FleetAllocationStore {
    path: PathBuf,
    snapshot: Snapshot,
    failed: bool,
}

impl FleetAllocationStore {
    pub fn open_for_registry(registry: &FleetRegistry) -> Result<Self, FleetAllocationStoreError> {
        Self::open(registry.layout().state_root().join("fleet-allocations.v1.json"))
    }

    pub fn open(path: impl Into<PathBuf>) -> Result<Self, FleetAllocationStoreError> {
        let path = path.into();
        if !path.exists() {
            return Ok(Self {
                path,
                snapshot: Snapshot {
                    schema_version: STORE_SCHEMA_VERSION,
                    revision: 0,
                    ledger: LeaseLedger::new(),
                },
                failed: false,
            });
        }
        let metadata = fs::metadata(&path)?;
        if metadata.len() > MAX_STORE_BYTES {
            return Err(FleetAllocationStoreError::Oversize);
        }
        let bytes = fs::read(&path)?;
        let snapshot: Snapshot = serde_json::from_slice(&bytes)?;
        if snapshot.schema_version != STORE_SCHEMA_VERSION {
            return Err(FleetAllocationStoreError::Schema(snapshot.schema_version));
        }
        Ok(Self {
            path,
            snapshot,
            failed: false,
        })
    }

    pub fn revision(&self) -> u64 { self.snapshot.revision }
    pub fn ledger(&self) -> &LeaseLedger { &self.snapshot.ledger }

    pub fn admit_host(&mut self, observation: HostObservation) -> Result<(), FleetAllocationStoreError> {
        self.commit(|ledger| ledger.admit_host(observation))
    }

    pub fn issue_batch(&mut self, now_ms: u64, grants: Vec<AllocationGrant>) -> Result<Vec<LeaseReceipt>, FleetAllocationStoreError> {
        self.commit(|ledger| ledger.issue_batch(now_ms, grants))
    }

    pub fn renew_or_revoke(
        &mut self,
        now_ms: u64,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<LeaseReceipt, FleetAllocationStoreError> {
        self.commit(|ledger| ledger.renew_or_revoke(
            now_ms,
            allocation_id,
            expected_lease_generation,
            authority_epoch,
            semantic_digest,
            disposition,
        ))
    }

    pub fn prune_expired(&mut self, now_ms: u64) -> Result<usize, FleetAllocationStoreError> {
        self.commit(|ledger| Ok(ledger.prune_expired(now_ms)))
    }

    fn commit<T>(
        &mut self,
        operation: impl FnOnce(&mut LeaseLedger) -> Result<T, LeaseError>,
    ) -> Result<T, FleetAllocationStoreError> {
        if self.failed {
            return Err(FleetAllocationStoreError::Fenced);
        }
        let mut next = self.snapshot.clone();
        let output = operation(&mut next.ledger)?;
        next.revision = next
            .revision
            .checked_add(1)
            .ok_or(LeaseError::ArithmeticOverflow)?;
        if let Err(error) = self.persist(&next) {
            self.failed = true;
            return Err(error);
        }
        self.snapshot = next;
        Ok(output)
    }

    fn persist(&self, snapshot: &Snapshot) -> Result<(), FleetAllocationStoreError> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let encoded = serde_json::to_vec(snapshot)?;
        if encoded.len() as u64 > MAX_STORE_BYTES {
            return Err(FleetAllocationStoreError::Oversize);
        }
        let tmp = self.path.with_extension("tmp");
        let mut file = File::create(&tmp)?;
        file.write_all(&encoded)?;
        file.sync_all()?;
        fs::rename(&tmp, &self.path)?;
        sync_parent(&self.path)?;
        Ok(())
    }
}

#[cfg(unix)]
fn sync_parent(path: &Path) -> Result<(), std::io::Error> {
    if let Some(parent) = path.parent() {
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent(_path: &Path) -> Result<(), std::io::Error> { Ok(()) }

#[cfg(test)]
mod tests {
    use super::*;
    use crate::FleetResourceVectorV1;

    fn host() -> HostObservation {
        HostObservation {
            host_id: "host-a".into(),
            failure_domain_id: "rack-a".into(),
            generation: 1,
            observed_at_ms: 10,
            valid_until_ms: 1000,
            capacity: FleetResourceVectorV1 {
                concurrent_turns: 4,
                memory_mib: 4096,
                tool_processes: 4,
                turn_queue_slots: 8,
            },
        }
    }

    #[test]
    fn durable_store_reopens_committed_host() {
        let temp = tempfile::tempdir().expect("temp");
        let path = temp.path().join("allocations.json");
        let mut store = FleetAllocationStore::open(&path).expect("open");
        store.admit_host(host()).expect("admit");
        assert_eq!(store.revision(), 1);
        drop(store);
        let reopened = FleetAllocationStore::open(path).expect("reopen");
        assert_eq!(reopened.revision(), 1);
        assert_eq!(reopened.ledger().hosts().count(), 1);
    }

    #[test]
    fn persistence_failure_fences_writer_until_reopen() {
        let temp = tempfile::tempdir().expect("temp");
        let path = temp.path().join("allocations.json");
        let mut store = FleetAllocationStore::open(&path).expect("open");
        std::fs::create_dir(path.with_extension("tmp")).expect("block temp file");
        assert!(matches!(
            store.admit_host(host()),
            Err(FleetAllocationStoreError::Io(_))
        ));
        assert!(matches!(
            store.admit_host(host()),
            Err(FleetAllocationStoreError::Fenced)
        ));
    }

}

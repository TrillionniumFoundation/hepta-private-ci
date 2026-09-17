use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[cfg(unix)]
use std::fs::File;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::FleetRegistry;
use crate::lease_ledger::AllocationGrant;
use crate::lease_ledger::Error as LeaseError;
use crate::lease_ledger::HostObservation;
use crate::lease_ledger::LeaseDisposition;
use crate::lease_ledger::LeaseLedger;
use crate::lease_ledger::LeaseLedgerStateV1;
use crate::lease_ledger::LeaseReceipt;

const STORE_DIRECTORY: &str = "fleet-allocations-v1";
const SNAPSHOT_PREFIX: &str = "generation-";
const SNAPSHOT_SUFFIX: &str = ".json";
const STORE_SCHEMA_VERSION: u32 = 1;
const MAX_STORE_GENERATIONS: usize = 64;
const MAX_SNAPSHOT_BYTES: u64 = 32 * 1024 * 1024;
static STAGING_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Error)]
pub enum FleetAllocationStoreError {
    #[error("fleet allocation store I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("fleet allocation store is corrupt: {0}")]
    Corrupt(String),
    #[error("fleet allocation generation is stale: expected {expected}, current {current}")]
    StaleGeneration { expected: u64, current: u64 },
    #[error("fleet allocation generation overflow")]
    GenerationOverflow,
    #[error(transparent)]
    Lease(#[from] LeaseError),
}

#[derive(Clone, Debug)]
pub struct FleetAllocationSnapshot {
    generation: u64,
    ledger: LeaseLedger,
}

impl FleetAllocationSnapshot {
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    pub fn grant(&self, allocation_id: &str) -> Option<&AllocationGrant> {
        self.ledger.get(allocation_id)
    }

    pub(crate) fn ledger(&self) -> &LeaseLedger {
        &self.ledger
    }
}

#[derive(Clone, Debug)]
pub struct FleetAllocationStore {
    root: PathBuf,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableStateV1 {
    schema_version: u32,
    generation: u64,
    ledger: LeaseLedgerStateV1,
}

impl FleetAllocationStore {
    pub fn open_or_initialize(state_root: &Path) -> Result<Self, FleetAllocationStoreError> {
        validate_physical_directory(state_root)?;
        let root = state_root.join(STORE_DIRECTORY);
        match std::fs::create_dir(&root) {
            Ok(()) => sync_directory(state_root)?,
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                validate_physical_directory(&root)?;
            }
            Err(error) => return Err(error.into()),
        }
        let store = Self { root };
        if store.snapshot_generations()?.is_empty() {
            store.publish_initial()?;
        }
        store.prune_history(MAX_STORE_GENERATIONS)?;
        Ok(store)
    }

    pub fn load(&self, now_ms: u64) -> Result<FleetAllocationSnapshot, FleetAllocationStoreError> {
        let generation = self
            .snapshot_generations()?
            .into_iter()
            .max()
            .ok_or_else(|| FleetAllocationStoreError::Corrupt("allocation state is missing".into()))?;
        let path = snapshot_path(&self.root, generation);
        let contents = read_regular_file_bounded(&path)?;
        let state: DurableStateV1 = serde_json::from_slice(&contents).map_err(|error| {
            FleetAllocationStoreError::Corrupt(format!(
                "invalid allocation generation {generation}: {error}"
            ))
        })?;
        if state.schema_version != STORE_SCHEMA_VERSION || state.generation != generation {
            return Err(FleetAllocationStoreError::Corrupt(format!(
                "allocation state does not match generation {generation}"
            )));
        }
        let ledger = LeaseLedger::restore_state(state.ledger, now_ms)?;
        Ok(FleetAllocationSnapshot { generation, ledger })
    }

    pub fn admit_host(
        &self,
        expected_generation: u64,
        now_ms: u64,
        observation: HostObservation,
    ) -> Result<u64, FleetAllocationStoreError> {
        let (generation, ()) = self.mutate(expected_generation, now_ms, |ledger| {
            ledger.admit_host(observation)
        })?;
        Ok(generation)
    }

    pub fn issue(
        &self,
        expected_generation: u64,
        now_ms: u64,
        grant: AllocationGrant,
    ) -> Result<(u64, LeaseReceipt), FleetAllocationStoreError> {
        self.mutate(expected_generation, now_ms, |ledger| ledger.issue(now_ms, grant))
    }

    pub fn renew_or_revoke(
        &self,
        expected_generation: u64,
        now_ms: u64,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<(u64, LeaseReceipt), FleetAllocationStoreError> {
        self.mutate(expected_generation, now_ms, |ledger| {
            ledger.renew_or_revoke(
                now_ms,
                allocation_id,
                expected_lease_generation,
                authority_epoch,
                semantic_digest,
                disposition,
            )
        })
    }

    pub(crate) fn commit_ledger(
        &self,
        expected_generation: u64,
        now_ms: u64,
        ledger: LeaseLedger,
    ) -> Result<u64, FleetAllocationStoreError> {
        ledger.validate_recovered(now_ms)?;
        let current = self.load(now_ms)?;
        if current.generation != expected_generation {
            return Err(FleetAllocationStoreError::StaleGeneration {
                expected: expected_generation,
                current: current.generation,
            });
        }
        let generation = expected_generation
            .checked_add(1)
            .ok_or(FleetAllocationStoreError::GenerationOverflow)?;
        self.publish(generation, &ledger)?;
        Ok(generation)
    }

    fn mutate<T>(
        &self,
        expected_generation: u64,
        now_ms: u64,
        mutate: impl FnOnce(&mut LeaseLedger) -> Result<T, LeaseError>,
    ) -> Result<(u64, T), FleetAllocationStoreError> {
        let snapshot = self.load(now_ms)?;
        if snapshot.generation != expected_generation {
            return Err(FleetAllocationStoreError::StaleGeneration {
                expected: expected_generation,
                current: snapshot.generation,
            });
        }
        let mut next = snapshot.ledger;
        let value = mutate(&mut next)?;
        next.validate_recovered(now_ms)?;
        let generation = expected_generation
            .checked_add(1)
            .ok_or(FleetAllocationStoreError::GenerationOverflow)?;
        self.publish(generation, &next)?;
        Ok((generation, value))
    }

    fn publish_initial(&self) -> Result<(), FleetAllocationStoreError> {
        match self.publish(/*generation*/ 0, &LeaseLedger::new()) {
            Ok(()) => Ok(()),
            Err(FleetAllocationStoreError::StaleGeneration {
                expected: 0,
                current: 0,
            }) => Ok(()),
            Err(error) => Err(error),
        }
    }

    fn publish(
        &self,
        generation: u64,
        ledger: &LeaseLedger,
    ) -> Result<(), FleetAllocationStoreError> {
        self.prune_history(MAX_STORE_GENERATIONS.saturating_sub(1).max(1))?;
        let state = DurableStateV1 {
            schema_version: STORE_SCHEMA_VERSION,
            generation,
            ledger: ledger.snapshot_state(),
        };
        let mut bytes = serde_json::to_vec(&state).map_err(|error| {
            FleetAllocationStoreError::Corrupt(format!("encode allocation state: {error}"))
        })?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_SNAPSHOT_BYTES {
            return Err(FleetAllocationStoreError::Corrupt(
                "allocation state exceeds durable size bound".into(),
            ));
        }
        let final_path = snapshot_path(&self.root, generation);
        let temp_path = self.root.join(format!(
            ".{SNAPSHOT_PREFIX}{generation:020}-{}-{}.tmp",
            std::process::id(),
            STAGING_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        write_new_file(&temp_path, &bytes)?;
        match std::fs::hard_link(&temp_path, &final_path) {
            Ok(()) => {}
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                let _ = std::fs::remove_file(&temp_path);
                return Err(FleetAllocationStoreError::StaleGeneration {
                    expected: generation.saturating_sub(1),
                    current: generation,
                });
            }
            Err(error) => {
                let _ = std::fs::remove_file(&temp_path);
                return Err(error.into());
            }
        }
        let _ = std::fs::remove_file(temp_path);
        sync_directory(&self.root)?;
        Ok(())
    }

    fn snapshot_generations(&self) -> Result<Vec<u64>, FleetAllocationStoreError> {
        let mut generations = Vec::new();
        for entry in std::fs::read_dir(&self.root)? {
            let entry = entry?;
            let file_name = entry.file_name();
            let name = file_name.to_str().ok_or_else(|| {
                FleetAllocationStoreError::Corrupt(
                    "allocation snapshot filename is not UTF-8".into(),
                )
            })?;
            if name.starts_with('.') {
                continue;
            }
            let generation = parse_snapshot_generation(name)?;
            validate_regular_file(&entry.path())?;
            generations.push(generation);
        }
        generations.sort_unstable();
        if generations.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(FleetAllocationStoreError::Corrupt(
                "duplicate allocation generation".into(),
            ));
        }
        Ok(generations)
    }

    fn prune_history(&self, retain: usize) -> Result<(), FleetAllocationStoreError> {
        let generations = self.snapshot_generations()?;
        let remove_count = generations.len().saturating_sub(retain.max(1));
        if remove_count == 0 {
            return Ok(());
        }
        for generation in generations.into_iter().take(remove_count) {
            std::fs::remove_file(snapshot_path(&self.root, generation))?;
        }
        sync_directory(&self.root)
    }
}

impl FleetRegistry {
    /// Opens the supervisor-owned durable allocation/lease state beside the
    /// existing Fleet registry. This does not install a second fleet writer.
    pub fn allocation_store(&self) -> Result<FleetAllocationStore, FleetAllocationStoreError> {
        FleetAllocationStore::open_or_initialize(self.layout().state_root())
    }
}

fn parse_snapshot_generation(name: &str) -> Result<u64, FleetAllocationStoreError> {
    let value = name
        .strip_prefix(SNAPSHOT_PREFIX)
        .and_then(|value| value.strip_suffix(SNAPSHOT_SUFFIX))
        .filter(|value| value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit()))
        .ok_or_else(|| {
            FleetAllocationStoreError::Corrupt(format!("invalid allocation snapshot name {name:?}"))
        })?;
    value.parse().map_err(|_| {
        FleetAllocationStoreError::Corrupt(format!("invalid allocation generation {value}"))
    })
}

fn snapshot_path(root: &Path, generation: u64) -> PathBuf {
    root.join(format!(
        "{SNAPSHOT_PREFIX}{generation:020}{SNAPSHOT_SUFFIX}"
    ))
}

fn write_new_file(path: &Path, contents: &[u8]) -> Result<(), FleetAllocationStoreError> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(contents)?;
    file.sync_all()?;
    Ok(())
}

fn read_regular_file_bounded(path: &Path) -> Result<Vec<u8>, FleetAllocationStoreError> {
    let metadata = validate_regular_file(path)?;
    if metadata.len() > MAX_SNAPSHOT_BYTES {
        return Err(FleetAllocationStoreError::Corrupt(format!(
            "allocation snapshot exceeds size bound: {}",
            path.display()
        )));
    }
    std::fs::read(path).map_err(Into::into)
}

fn validate_regular_file(path: &Path) -> Result<std::fs::Metadata, FleetAllocationStoreError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(FleetAllocationStoreError::Corrupt(format!(
            "allocation state path is not a regular file: {}",
            path.display()
        )));
    }
    Ok(metadata)
}

fn validate_physical_directory(path: &Path) -> Result<(), FleetAllocationStoreError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(FleetAllocationStoreError::Corrupt(format!(
            "allocation state path is not a physical directory: {}",
            path.display()
        )));
    }
    Ok(())
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

#[cfg(test)]
#[path = "allocation_store_tests.rs"]
mod tests;

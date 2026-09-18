use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::lease_ledger::LeaseLedger;

pub const FLEET_ALLOCATION_STORE_SCHEMA_VERSION: u32 = 1;
const STATE_DIRECTORY: &str = "fleet-allocation";
const STATE_PREFIX: &str = "allocation-state-";
const STATE_SUFFIX: &str = ".json";
const MAX_STATE_BYTES: u64 = 8 * 1024 * 1024;
const RETAIN_STATE_GENERATIONS: usize = 32;
static STAGING_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetAllocationStateV1 {
    pub schema_version: u32,
    pub revision: u64,
    pub predecessor_revision: Option<u64>,
    pub writer_epoch: u64,
    pub committed_at_ms: u64,
    pub ledger: LeaseLedger,
    pub state_digest: Sha256Digest,
}

impl FleetAllocationStateV1 {
    fn build(
        revision: u64,
        predecessor_revision: Option<u64>,
        writer_epoch: u64,
        committed_at_ms: u64,
        ledger: LeaseLedger,
    ) -> Result<Self, FleetAllocationStoreError> {
        if revision == 0 || writer_epoch == 0 {
            return Err(FleetAllocationStoreError::InvalidState(
                "revision and writer epoch must be non-zero".to_string(),
            ));
        }
        let state_digest = digest_state(
            revision,
            predecessor_revision,
            writer_epoch,
            committed_at_ms,
            &ledger,
        )?;
        Ok(Self {
            schema_version: FLEET_ALLOCATION_STORE_SCHEMA_VERSION,
            revision,
            predecessor_revision,
            writer_epoch,
            committed_at_ms,
            ledger,
            state_digest,
        })
    }

    fn validate(&self) -> Result<(), FleetAllocationStoreError> {
        if self.schema_version != FLEET_ALLOCATION_STORE_SCHEMA_VERSION
            || self.revision == 0
            || self.writer_epoch == 0
            || self.predecessor_revision.is_some_and(|value| value >= self.revision)
        {
            return Err(FleetAllocationStoreError::InvalidState(
                "invalid allocation state identity".to_string(),
            ));
        }
        let expected = digest_state(
            self.revision,
            self.predecessor_revision,
            self.writer_epoch,
            self.committed_at_ms,
            &self.ledger,
        )?;
        if expected != self.state_digest {
            return Err(FleetAllocationStoreError::DigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct FleetAllocationStore {
    root: PathBuf,
    current: FleetAllocationStateV1,
}

impl FleetAllocationStore {
    pub fn open_or_initialize(
        fleet_state_root: &Path,
        writer_epoch: u64,
        now_ms: u64,
    ) -> Result<Self, FleetAllocationStoreError> {
        if writer_epoch == 0 {
            return Err(FleetAllocationStoreError::InvalidState(
                "writer epoch must be non-zero".to_string(),
            ));
        }
        validate_directory(fleet_state_root)?;
        let root = fleet_state_root.join(STATE_DIRECTORY);
        match std::fs::create_dir(&root) {
            Ok(()) => sync_directory(fleet_state_root)?,
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error.into()),
        }
        validate_directory(&root)?;
        if let Some(current) = load_latest(&root)? {
            return Ok(Self { root, current });
        }

        let current = FleetAllocationStateV1::build(
            1,
            None,
            writer_epoch,
            now_ms,
            LeaseLedger::new(),
        )?;
        publish_state(&root, &current)?;
        Ok(Self { root, current })
    }

    pub fn current(&self) -> &FleetAllocationStateV1 {
        &self.current
    }

    pub fn commit(
        &mut self,
        expected_revision: u64,
        writer_epoch: u64,
        now_ms: u64,
        ledger: LeaseLedger,
    ) -> Result<&FleetAllocationStateV1, FleetAllocationStoreError> {
        if self.current.revision != expected_revision {
            return Err(FleetAllocationStoreError::StaleRevision {
                expected: expected_revision,
                current: self.current.revision,
            });
        }
        let revision = expected_revision
            .checked_add(1)
            .ok_or_else(|| FleetAllocationStoreError::InvalidState("revision overflow".to_string()))?;
        let next = FleetAllocationStateV1::build(
            revision,
            Some(expected_revision),
            writer_epoch,
            now_ms,
            ledger,
        )?;
        publish_state(&self.root, &next)?;
        self.current = next;
        prune_history(&self.root)?;
        Ok(&self.current)
    }

    pub fn reload(&mut self) -> Result<&FleetAllocationStateV1, FleetAllocationStoreError> {
        let current = load_latest(&self.root)?.ok_or_else(|| {
            FleetAllocationStoreError::InvalidState(
                "allocation state disappeared after initialization".to_string(),
            )
        })?;
        self.current = current;
        Ok(&self.current)
    }
}

#[derive(Debug, Error)]
pub enum FleetAllocationStoreError {
    #[error("allocation state I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("allocation state encoding failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("invalid durable allocation state: {0}")]
    InvalidState(String),
    #[error("durable allocation state digest mismatch")]
    DigestMismatch,
    #[error("stale durable allocation revision: expected {expected}, current {current}")]
    StaleRevision { expected: u64, current: u64 },
    #[error("durable allocation revision already exists")]
    RevisionConflict,
}

fn digest_state(
    revision: u64,
    predecessor_revision: Option<u64>,
    writer_epoch: u64,
    committed_at_ms: u64,
    ledger: &LeaseLedger,
) -> Result<Sha256Digest, FleetAllocationStoreError> {
    let canonical = serde_json::to_vec(&(
        "hepta.runtime-fleet.allocation-state.v1",
        revision,
        predecessor_revision,
        writer_epoch,
        committed_at_ms,
        ledger,
    ))?;
    Ok(Sha256Digest::for_bytes(&canonical))
}

fn load_latest(root: &Path) -> Result<Option<FleetAllocationStateV1>, FleetAllocationStoreError> {
    let mut revisions = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let name = entry
            .file_name()
            .to_str()
            .ok_or_else(|| {
                FleetAllocationStoreError::InvalidState(
                    "allocation state filename is not UTF-8".to_string(),
                )
            })?
            .to_string();
        if name.starts_with('.') {
            continue;
        }
        let Some(revision) = parse_revision(&name)? else {
            return Err(FleetAllocationStoreError::InvalidState(format!(
                "unexpected allocation state entry {name:?}"
            )));
        };
        revisions.push((revision, entry.path()));
    }
    revisions.sort_by_key(|(revision, _)| *revision);
    let Some((revision, path)) = revisions.last() else {
        return Ok(None);
    };
    let state = read_state(path)?;
    if state.revision != *revision {
        return Err(FleetAllocationStoreError::InvalidState(
            "allocation state revision differs from filename".to_string(),
        ));
    }
    state.validate()?;
    if revisions.len() >= 2 {
        let prior_revision = revisions[revisions.len() - 2].0;
        if state.predecessor_revision != Some(prior_revision) {
            return Err(FleetAllocationStoreError::InvalidState(
                "latest allocation state predecessor is not contiguous".to_string(),
            ));
        }
    } else if state.revision == 1 && state.predecessor_revision.is_some() {
        return Err(FleetAllocationStoreError::InvalidState(
            "initial allocation state has a predecessor".to_string(),
        ));
    }
    Ok(Some(state))
}

fn read_state(path: &Path) -> Result<FleetAllocationStateV1, FleetAllocationStoreError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_STATE_BYTES
    {
        return Err(FleetAllocationStoreError::InvalidState(format!(
            "allocation state path is not an admissible bounded regular file: {}",
            path.display()
        )));
    }
    let mut bytes = Vec::with_capacity(usize::try_from(metadata.len()).unwrap_or(0));
    File::open(path)?
        .take(MAX_STATE_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_STATE_BYTES {
        return Err(FleetAllocationStoreError::InvalidState(
            "allocation state exceeds byte bound".to_string(),
        ));
    }
    serde_json::from_slice(&bytes).map_err(Into::into)
}

fn publish_state(
    root: &Path,
    state: &FleetAllocationStateV1,
) -> Result<(), FleetAllocationStoreError> {
    let mut bytes = serde_json::to_vec(state)?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_STATE_BYTES {
        return Err(FleetAllocationStoreError::InvalidState(
            "allocation state exceeds byte bound".to_string(),
        ));
    }

    let final_path = state_path(root, state.revision);
    let temp_path = root.join(format!(
        ".allocation-state-{}-{}-{}.tmp",
        state.revision,
        std::process::id(),
        STAGING_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    let publish = std::fs::hard_link(&temp_path, &final_path);
    let _ = std::fs::remove_file(&temp_path);
    match publish {
        Ok(()) => {
            sync_directory(root)?;
            Ok(())
        }
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            Err(FleetAllocationStoreError::RevisionConflict)
        }
        Err(error) => Err(error.into()),
    }
}

fn prune_history(root: &Path) -> Result<(), FleetAllocationStoreError> {
    let mut revisions = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        if let Some(revision) = parse_revision(&name)? {
            revisions.push((revision, entry.path()));
        }
    }
    revisions.sort_by_key(|(revision, _)| *revision);
    let remove_count = revisions.len().saturating_sub(RETAIN_STATE_GENERATIONS);
    for (_, path) in revisions.into_iter().take(remove_count) {
        std::fs::remove_file(path)?;
    }
    if remove_count > 0 {
        sync_directory(root)?;
    }
    Ok(())
}

fn parse_revision(name: &str) -> Result<Option<u64>, FleetAllocationStoreError> {
    let Some(raw) = name
        .strip_prefix(STATE_PREFIX)
        .and_then(|value| value.strip_suffix(STATE_SUFFIX))
    else {
        return Ok(None);
    };
    if raw.len() != 20 || !raw.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(FleetAllocationStoreError::InvalidState(format!(
            "invalid allocation state filename {name:?}"
        )));
    }
    raw.parse()
        .map(Some)
        .map_err(|_| FleetAllocationStoreError::InvalidState("invalid state revision".to_string()))
}

fn state_path(root: &Path, revision: u64) -> PathBuf {
    root.join(format!("{STATE_PREFIX}{revision:020}{STATE_SUFFIX}"))
}

fn validate_directory(path: &Path) -> Result<(), FleetAllocationStoreError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(FleetAllocationStoreError::InvalidState(format!(
            "allocation store parent is not a physical directory: {}",
            path.display()
        )));
    }
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), FleetAllocationStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn store_reopens_exact_committed_generation() {
        let temp = tempfile::tempdir().expect("temp");
        let state_root = temp.path().join("state");
        std::fs::create_dir(&state_root).expect("state root");
        let mut store =
            FleetAllocationStore::open_or_initialize(&state_root, 7, 100).expect("store");
        assert_eq!(store.current().revision, 1);
        let expected = store.current().state_digest.clone();
        let revision = store.current().revision;
        store
            .commit(revision, 7, 200, LeaseLedger::new())
            .expect("commit");
        drop(store);

        let reopened =
            FleetAllocationStore::open_or_initialize(&state_root, 8, 300).expect("reopen");
        assert_eq!(reopened.current().revision, 2);
        assert_ne!(reopened.current().state_digest, expected);
        assert_eq!(reopened.current().writer_epoch, 7);
    }

    #[test]
    fn stale_revision_cannot_overwrite_a_committed_generation() {
        let temp = tempfile::tempdir().expect("temp");
        let state_root = temp.path().join("state");
        std::fs::create_dir(&state_root).expect("state root");
        let mut store =
            FleetAllocationStore::open_or_initialize(&state_root, 7, 100).expect("store");
        store
            .commit(1, 7, 200, LeaseLedger::new())
            .expect("commit");
        assert!(matches!(
            store.commit(1, 7, 300, LeaseLedger::new()),
            Err(FleetAllocationStoreError::StaleRevision {
                expected: 1,
                current: 2
            })
        ));
    }

    #[test]
    fn tampered_latest_generation_fails_reopen() {
        let temp = tempfile::tempdir().expect("temp");
        let state_root = temp.path().join("state");
        std::fs::create_dir(&state_root).expect("state root");
        let mut store =
            FleetAllocationStore::open_or_initialize(&state_root, 7, 100).expect("store");
        store
            .commit(1, 7, 200, LeaseLedger::new())
            .expect("commit");
        let path = state_path(&state_root.join(STATE_DIRECTORY), 2);
        let mut bytes = std::fs::read(&path).expect("read");
        let index = bytes
            .iter()
            .position(|byte| *byte == b'7')
            .expect("writer epoch byte");
        bytes[index] = b'8';
        std::fs::write(path, bytes).expect("tamper");
        assert!(FleetAllocationStore::open_or_initialize(&state_root, 9, 300).is_err());
    }
}

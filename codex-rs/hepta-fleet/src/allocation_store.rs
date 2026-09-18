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
const MAX_STATE_FILES_ON_OPEN: usize = RETAIN_STATE_GENERATIONS + 1;
static STAGING_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetAllocationStateV1 {
    pub schema_version: u32,
    pub revision: u64,
    pub predecessor_revision: Option<u64>,
    pub predecessor_state_digest: Option<Sha256Digest>,
    pub writer_epoch: u64,
    pub committed_at_ms: u64,
    pub ledger: LeaseLedger,
    pub state_digest: Sha256Digest,
}

impl FleetAllocationStateV1 {
    fn build(
        revision: u64,
        predecessor_revision: Option<u64>,
        predecessor_state_digest: Option<Sha256Digest>,
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
            predecessor_state_digest.as_ref(),
            writer_epoch,
            committed_at_ms,
            &ledger,
        )?;
        Ok(Self {
            schema_version: FLEET_ALLOCATION_STORE_SCHEMA_VERSION,
            revision,
            predecessor_revision,
            predecessor_state_digest,
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
            || (self.revision > 1
                && self.predecessor_revision != Some(self.revision - 1))
            || (self.revision == 1
                && (self.predecessor_revision.is_some()
                    || self.predecessor_state_digest.is_some()))
            || (self.revision > 1
                && (self.predecessor_revision.is_none()
                    || self.predecessor_state_digest.is_none()))
        {
            return Err(FleetAllocationStoreError::InvalidState(
                "invalid allocation state identity".to_string(),
            ));
        }
        let expected = digest_state(
            self.revision,
            self.predecessor_revision,
            self.predecessor_state_digest.as_ref(),
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
            // A previous commit may have succeeded while post-commit retention
            // maintenance failed. Reopen repairs that bounded maintenance
            // before admitting another writer generation.
            prune_history(&root)?;
            return Ok(Self { root, current });
        }

        let current = FleetAllocationStateV1::build(
            1,
            None,
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
        // A post-publication cleanup error from the previous mutation was
        // deliberately non-ambiguous. Repair it before publishing another
        // generation so repeated cleanup failure cannot grow state without
        // bound.
        prune_history(&self.root)?;
        if self.current.revision != expected_revision {
            return Err(FleetAllocationStoreError::StaleRevision {
                expected: expected_revision,
                current: self.current.revision,
            });
        }
        let revision = expected_revision
            .checked_add(1)
            .ok_or_else(|| FleetAllocationStoreError::InvalidState("revision overflow".to_string()))?;
        let predecessor_state_digest = self.current.state_digest.clone();
        let next = FleetAllocationStateV1::build(
            revision,
            Some(expected_revision),
            Some(predecessor_state_digest),
            writer_epoch,
            now_ms,
            ledger,
        )?;
        publish_state(&self.root, &next)?;
        self.current = next;
        // Publication above is the linearization point. Retention is
        // maintenance only: a cleanup failure must never make a committed
        // generation look like a failed/unknown mutation to its caller.
        let _ = prune_history(&self.root);
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
    predecessor_state_digest: Option<&Sha256Digest>,
    writer_epoch: u64,
    committed_at_ms: u64,
    ledger: &LeaseLedger,
) -> Result<Sha256Digest, FleetAllocationStoreError> {
    let canonical = serde_json::to_vec(&(
        "hepta.runtime-fleet.allocation-state.v1",
        revision,
        predecessor_revision,
        predecessor_state_digest,
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
        if revisions.len() > MAX_STATE_FILES_ON_OPEN {
            return Err(FleetAllocationStoreError::InvalidState(
                "allocation state file count exceeds recovery bound".to_string(),
            ));
        }
    }
    revisions.sort_by_key(|(revision, _)| *revision);
    if revisions.is_empty() {
        return Ok(None);
    }

    // Validate every retained generation, not only the head. The newest
    // generation binds its predecessor digest, so a modified or deleted
    // retained predecessor must fail reopen instead of silently becoming
    // unverifiable history.
    let mut states = Vec::with_capacity(revisions.len());
    for (revision, path) in &revisions {
        let state = read_state(path)?;
        if state.revision != *revision {
            return Err(FleetAllocationStoreError::InvalidState(
                "allocation state revision differs from filename".to_string(),
            ));
        }
        state.validate()?;
        states.push(state);
    }
    for pair in states.windows(2) {
        let predecessor = &pair[0];
        let current = &pair[1];
        if current.predecessor_revision != Some(predecessor.revision)
            || current.predecessor_state_digest.as_ref() != Some(&predecessor.state_digest)
        {
            return Err(FleetAllocationStoreError::InvalidState(
                "allocation state predecessor lineage mismatch".to_string(),
            ));
        }
    }
    Ok(states.pop())
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
#[path = "allocation_store_tests.rs"]
mod tests;

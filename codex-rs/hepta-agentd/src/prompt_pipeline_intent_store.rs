//! Durable coordinator intent for the staged-context/final-use-lease boundary.
//!
//! Runtime attachments and final-use leases remain owned by their existing stores.
//! This bounded sidecar records only the composition transition needed to recover
//! a crash between those two durable publications. It grants no prompt, model or
//! provider authority and never substitutes for either owner.

use std::collections::BTreeMap;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::prompt_final_use_store::PromptFinalUseKeyV1;

const STORE_SCHEMA: u32 = 1;
const STATE_FILE: &str = "prompt-pipeline-intents.json";
const NEXT_FILE: &str = "prompt-pipeline-intents.next";
const LOCK_FILE: &str = "prompt-pipeline-intents.lock";
const MAX_INTENTS: usize = 256;
const MAX_STATE_BYTES: u64 = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum PromptPipelineIntentPhase {
    Preparing,
    RuntimeStaged,
    LeaseCommitted,
    Ready,
    Aborting,
    Quarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PromptPipelineIntentV1 {
    pub key: PromptFinalUseKeyV1,
    pub operation_id: StableId,
    pub context_attachment_digest: Digest32,
    pub lease_digest: Digest32,
    pub phase: PromptPipelineIntentPhase,
}

impl PromptPipelineIntentV1 {
    pub(crate) fn new(
        key: PromptFinalUseKeyV1,
        operation_id: StableId,
        context_attachment_digest: Digest32,
        lease_digest: Digest32,
    ) -> Result<Self, PromptPipelineIntentStoreError> {
        let value = Self {
            key,
            operation_id,
            context_attachment_digest,
            lease_digest,
            phase: PromptPipelineIntentPhase::Preparing,
        };
        value.validate()?;
        Ok(value)
    }

    fn validate(&self) -> Result<(), PromptPipelineIntentStoreError> {
        if self.context_attachment_digest.is_zero() || self.lease_digest.is_zero() {
            return Err(PromptPipelineIntentStoreError::Corrupt);
        }
        PromptFinalUseKeyV1::new(&self.key.thread_id, &self.key.turn_id)
            .map_err(|_| PromptPipelineIntentStoreError::Corrupt)?;
        StableId::new(self.operation_id.to_string())
            .map_err(|_| PromptPipelineIntentStoreError::Corrupt)?;
        Ok(())
    }

    fn same_identity(&self, other: &Self) -> bool {
        self.key == other.key
            && self.operation_id == other.operation_id
            && self.context_attachment_digest == other.context_attachment_digest
            && self.lease_digest == other.lease_digest
    }
}

pub(crate) struct PromptPipelineIntentStore {
    root: PathBuf,
    _lock: File,
    intents: Mutex<BTreeMap<PromptFinalUseKeyV1, PromptPipelineIntentV1>>,
    poisoned: AtomicBool,
}

impl fmt::Debug for PromptPipelineIntentStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let count = self.intents.lock().map(|intents| intents.len()).unwrap_or(0);
        formatter
            .debug_struct("PromptPipelineIntentStore")
            .field("intent_count", &count)
            .field("requires_reopen", &self.poisoned.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}

impl PromptPipelineIntentStore {
    pub(crate) fn open(directory: &Path) -> Result<Self, PromptPipelineIntentStoreError> {
        prepare_directory(directory)?;
        let lock_path = directory.join(LOCK_FILE);
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|_| PromptPipelineIntentStoreError::Unavailable)?;
        set_private_file_permissions(&lock_path)?;
        lock.try_lock()
            .map_err(|_| PromptPipelineIntentStoreError::StateLocked)?;
        let intents = read_state(directory)?;
        Ok(Self {
            root: directory.to_path_buf(),
            _lock: lock,
            intents: Mutex::new(intents),
            poisoned: AtomicBool::new(false),
        })
    }

    pub(crate) fn begin(
        &self,
        intent: PromptPipelineIntentV1,
    ) -> Result<(), PromptPipelineIntentStoreError> {
        intent.validate()?;
        self.commit(|intents| {
            if let Some(existing) = intents.get(&intent.key) {
                return if existing == &intent {
                    Ok(())
                } else {
                    Err(PromptPipelineIntentStoreError::Conflict)
                };
            }
            if intents.len() >= MAX_INTENTS {
                return Err(PromptPipelineIntentStoreError::CapacityExceeded);
            }
            intents.insert(intent.key.clone(), intent);
            Ok(())
        })
    }

    pub(crate) fn advance(
        &self,
        key: &PromptFinalUseKeyV1,
        operation_id: &StableId,
        lease_digest: Digest32,
        next_phase: PromptPipelineIntentPhase,
    ) -> Result<(), PromptPipelineIntentStoreError> {
        self.commit(|intents| {
            let intent = intents
                .get_mut(key)
                .ok_or(PromptPipelineIntentStoreError::Missing)?;
            if &intent.operation_id != operation_id || intent.lease_digest != lease_digest {
                return Err(PromptPipelineIntentStoreError::Conflict);
            }
            if !transition_allowed(intent.phase, next_phase) {
                return Err(PromptPipelineIntentStoreError::InvalidTransition);
            }
            intent.phase = next_phase;
            Ok(())
        })
    }

    pub(crate) fn remove(
        &self,
        key: &PromptFinalUseKeyV1,
        operation_id: &StableId,
        lease_digest: Digest32,
    ) -> Result<bool, PromptPipelineIntentStoreError> {
        self.commit(|intents| {
            let Some(intent) = intents.get(key) else {
                return Ok(false);
            };
            if &intent.operation_id != operation_id || intent.lease_digest != lease_digest {
                return Err(PromptPipelineIntentStoreError::Conflict);
            }
            Ok(intents.remove(key).is_some())
        })
    }

    pub(crate) fn get(
        &self,
        key: &PromptFinalUseKeyV1,
    ) -> Result<Option<PromptPipelineIntentV1>, PromptPipelineIntentStoreError> {
        self.ensure_available()?;
        Ok(self
            .intents
            .lock()
            .map_err(|_| PromptPipelineIntentStoreError::StatePoisoned)?
            .get(key)
            .cloned())
    }

    pub(crate) fn entries(
        &self,
    ) -> Result<Vec<PromptPipelineIntentV1>, PromptPipelineIntentStoreError> {
        self.ensure_available()?;
        Ok(self
            .intents
            .lock()
            .map_err(|_| PromptPipelineIntentStoreError::StatePoisoned)?
            .values()
            .cloned()
            .collect())
    }

    #[must_use]
    pub(crate) fn requires_reopen(&self) -> bool {
        self.poisoned.load(Ordering::Acquire)
    }

    fn ensure_available(&self) -> Result<(), PromptPipelineIntentStoreError> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(PromptPipelineIntentStoreError::ReopenRequired);
        }
        Ok(())
    }

    fn commit<T>(
        &self,
        mutation: impl FnOnce(
            &mut BTreeMap<PromptFinalUseKeyV1, PromptPipelineIntentV1>,
        ) -> Result<T, PromptPipelineIntentStoreError>,
    ) -> Result<T, PromptPipelineIntentStoreError> {
        self.ensure_available()?;
        let mut current = self
            .intents
            .lock()
            .map_err(|_| PromptPipelineIntentStoreError::StatePoisoned)?;
        let mut next = current.clone();
        let result = mutation(&mut next)?;
        if next != *current {
            match persist_state(&self.root, &next) {
                Ok(()) => *current = next,
                Err(PromptPipelineIntentStoreError::IndeterminateDurability) => {
                    self.poisoned.store(true, Ordering::Release);
                    return Err(PromptPipelineIntentStoreError::IndeterminateDurability);
                }
                Err(error) => return Err(error),
            }
        }
        Ok(result)
    }
}

fn transition_allowed(
    current: PromptPipelineIntentPhase,
    next: PromptPipelineIntentPhase,
) -> bool {
    if current == next {
        return true;
    }
    match current {
        PromptPipelineIntentPhase::Preparing => matches!(
            next,
            PromptPipelineIntentPhase::RuntimeStaged
                | PromptPipelineIntentPhase::LeaseCommitted
                | PromptPipelineIntentPhase::Ready
                | PromptPipelineIntentPhase::Aborting
                | PromptPipelineIntentPhase::Quarantined
        ),
        PromptPipelineIntentPhase::RuntimeStaged => matches!(
            next,
            PromptPipelineIntentPhase::LeaseCommitted
                | PromptPipelineIntentPhase::Ready
                | PromptPipelineIntentPhase::Aborting
                | PromptPipelineIntentPhase::Quarantined
        ),
        PromptPipelineIntentPhase::LeaseCommitted => matches!(
            next,
            PromptPipelineIntentPhase::Ready
                | PromptPipelineIntentPhase::Aborting
                | PromptPipelineIntentPhase::Quarantined
        ),
        PromptPipelineIntentPhase::Ready => matches!(
            next,
            PromptPipelineIntentPhase::Aborting
                | PromptPipelineIntentPhase::Quarantined
        ),
        PromptPipelineIntentPhase::Aborting => {
            next == PromptPipelineIntentPhase::Quarantined
        }
        PromptPipelineIntentPhase::Quarantined => false,
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredState {
    schema: u32,
    intents: Vec<StoredIntent>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredIntent {
    thread_id: String,
    turn_id: String,
    operation_id: String,
    context_attachment_digest: [u8; 32],
    lease_digest: [u8; 32],
    phase: PromptPipelineIntentPhase,
}

fn read_state(
    directory: &Path,
) -> Result<BTreeMap<PromptFinalUseKeyV1, PromptPipelineIntentV1>, PromptPipelineIntentStoreError> {
    let path = directory.join(STATE_FILE);
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let mut bytes = Vec::new();
    File::open(&path)
        .map_err(|_| PromptPipelineIntentStoreError::Unavailable)?
        .take(MAX_STATE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| PromptPipelineIntentStoreError::Unavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
        return Err(PromptPipelineIntentStoreError::Corrupt);
    }
    let stored: StoredState =
        serde_json::from_slice(&bytes).map_err(|_| PromptPipelineIntentStoreError::Corrupt)?;
    if stored.schema != STORE_SCHEMA || stored.intents.len() > MAX_INTENTS {
        return Err(PromptPipelineIntentStoreError::Corrupt);
    }
    let mut intents = BTreeMap::new();
    for stored in stored.intents {
        let key = PromptFinalUseKeyV1::new(&stored.thread_id, &stored.turn_id)
            .map_err(|_| PromptPipelineIntentStoreError::Corrupt)?;
        let intent = PromptPipelineIntentV1 {
            key: key.clone(),
            operation_id: StableId::new(stored.operation_id)
                .map_err(|_| PromptPipelineIntentStoreError::Corrupt)?,
            context_attachment_digest: Digest32::from_array(stored.context_attachment_digest),
            lease_digest: Digest32::from_array(stored.lease_digest),
            phase: stored.phase,
        };
        intent.validate()?;
        if intents.insert(key, intent).is_some() {
            return Err(PromptPipelineIntentStoreError::Corrupt);
        }
    }
    Ok(intents)
}

fn persist_state(
    directory: &Path,
    intents: &BTreeMap<PromptFinalUseKeyV1, PromptPipelineIntentV1>,
) -> Result<(), PromptPipelineIntentStoreError> {
    let stored = StoredState {
        schema: STORE_SCHEMA,
        intents: intents
            .values()
            .map(|intent| StoredIntent {
                thread_id: intent.key.thread_id.clone(),
                turn_id: intent.key.turn_id.clone(),
                operation_id: intent.operation_id.to_string(),
                context_attachment_digest: intent.context_attachment_digest.into_array(),
                lease_digest: intent.lease_digest.into_array(),
                phase: intent.phase,
            })
            .collect(),
    };
    let bytes = serde_json::to_vec(&stored)
        .map_err(|_| PromptPipelineIntentStoreError::Unavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
        return Err(PromptPipelineIntentStoreError::CapacityExceeded);
    }
    let next_path = directory.join(NEXT_FILE);
    let mut next = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&next_path)
        .map_err(|_| PromptPipelineIntentStoreError::Unavailable)?;
    set_private_file_permissions(&next_path)?;
    next.write_all(&bytes)
        .and_then(|()| next.sync_all())
        .map_err(|_| PromptPipelineIntentStoreError::Unavailable)?;
    std::fs::rename(&next_path, directory.join(STATE_FILE))
        .map_err(|_| PromptPipelineIntentStoreError::Unavailable)?;
    sync_directory(directory)
}

fn prepare_directory(path: &Path) -> Result<(), PromptPipelineIntentStoreError> {
    if let Err(error) = std::fs::create_dir(path)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(PromptPipelineIntentStoreError::Unavailable);
    }
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| PromptPipelineIntentStoreError::Unavailable)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(PromptPipelineIntentStoreError::Corrupt);
    }
    set_private_directory_permissions(path)
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &Path) -> Result<(), PromptPipelineIntentStoreError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|_| PromptPipelineIntentStoreError::Unavailable)
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &Path) -> Result<(), PromptPipelineIntentStoreError> {
    Ok(())
}

#[cfg(unix)]
fn set_private_file_permissions(path: &Path) -> Result<(), PromptPipelineIntentStoreError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .map_err(|_| PromptPipelineIntentStoreError::Unavailable)
}

#[cfg(not(unix))]
fn set_private_file_permissions(_path: &Path) -> Result<(), PromptPipelineIntentStoreError> {
    Ok(())
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), PromptPipelineIntentStoreError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| PromptPipelineIntentStoreError::IndeterminateDurability)
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), PromptPipelineIntentStoreError> {
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum PromptPipelineIntentStoreError {
    Missing,
    Conflict,
    InvalidTransition,
    CapacityExceeded,
    Corrupt,
    StateLocked,
    StatePoisoned,
    Unavailable,
    IndeterminateDurability,
    ReopenRequired,
}

impl fmt::Display for PromptPipelineIntentStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PromptPipelineIntentStoreError {}

#[cfg(test)]
mod tests {
    use super::PromptPipelineIntentPhase;
    use super::PromptPipelineIntentStore;
    use super::PromptPipelineIntentStoreError;
    use super::PromptPipelineIntentV1;
    use crate::prompt_final_use_store::PromptFinalUseKeyV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    #[test]
    fn intent_survives_reopen_and_enforces_identity() -> Result<(), Box<dyn std::error::Error>> {
        let directory = tempfile::tempdir()?;
        let key = PromptFinalUseKeyV1::new("thread:intent", "turn:intent")?;
        let operation_id = StableId::new("compilation:intent".to_owned())?;
        let lease_digest = Digest32::of_bytes(b"lease:intent");
        let intent = PromptPipelineIntentV1::new(
            key.clone(),
            operation_id.clone(),
            Digest32::of_bytes(b"attachment:intent"),
            lease_digest,
        )?;
        {
            let store = PromptPipelineIntentStore::open(directory.path())?;
            store.begin(intent.clone())?;
            store.advance(
                &key,
                &operation_id,
                lease_digest,
                PromptPipelineIntentPhase::RuntimeStaged,
            )?;
        }
        let store = PromptPipelineIntentStore::open(directory.path())?;
        let reopened = store
            .get(&key)?
            .ok_or(PromptPipelineIntentStoreError::Missing)?;
        assert_eq!(reopened.phase, PromptPipelineIntentPhase::RuntimeStaged);
        assert_eq!(reopened, PromptPipelineIntentV1 { phase: PromptPipelineIntentPhase::RuntimeStaged, ..intent });
        assert_eq!(
            store.advance(
                &key,
                &StableId::new("compilation:other".to_owned())?,
                lease_digest,
                PromptPipelineIntentPhase::Ready,
            ),
            Err(PromptPipelineIntentStoreError::Conflict)
        );
        Ok(())
    }

    #[test]
    fn intent_transition_is_monotonic_and_removal_is_idempotent(
    ) -> Result<(), Box<dyn std::error::Error>> {
        let directory = tempfile::tempdir()?;
        let store = PromptPipelineIntentStore::open(directory.path())?;
        let key = PromptFinalUseKeyV1::new("thread:transition", "turn:transition")?;
        let operation_id = StableId::new("compilation:transition".to_owned())?;
        let lease_digest = Digest32::of_bytes(b"lease:transition");
        store.begin(PromptPipelineIntentV1::new(
            key.clone(),
            operation_id.clone(),
            Digest32::of_bytes(b"attachment:transition"),
            lease_digest,
        )?)?;
        store.advance(
            &key,
            &operation_id,
            lease_digest,
            PromptPipelineIntentPhase::RuntimeStaged,
        )?;
        store.advance(
            &key,
            &operation_id,
            lease_digest,
            PromptPipelineIntentPhase::LeaseCommitted,
        )?;
        store.advance(
            &key,
            &operation_id,
            lease_digest,
            PromptPipelineIntentPhase::Ready,
        )?;
        assert_eq!(
            store.advance(
                &key,
                &operation_id,
                lease_digest,
                PromptPipelineIntentPhase::Preparing,
            ),
            Err(PromptPipelineIntentStoreError::InvalidTransition)
        );
        assert!(store.remove(&key, &operation_id, lease_digest)?);
        assert!(!store.remove(&key, &operation_id, lease_digest)?);
        Ok(())
    }
}

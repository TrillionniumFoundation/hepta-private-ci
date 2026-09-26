//! Durable store for send-time prompt final-use leases.
//!
//! The store is deliberately separate from prompt bytes and provider records.
//! A staged attachment without a matching lease is harmless: the composed
//! Agentd host refuses to expose or dispatch it. Publication is clone/persist/
//! swap, and directory-sync uncertainty poisons the owner until reopen.

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

use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::prompt_final_use::PROMPT_FINAL_USE_LEASE_SCHEMA;
use crate::prompt_final_use::PromptFinalUseLeaseV1;
use crate::prompt_final_use::PromptFinalUseSelectionV1;

const STORE_SCHEMA: u32 = 1;
const STATE_FILE: &str = "prompt-final-use.json";
const NEXT_FILE: &str = "prompt-final-use.next";
const LOCK_FILE: &str = "prompt-final-use.lock";
const MAX_LEASES: usize = 256;
const MAX_STATE_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct PromptFinalUseKeyV1 {
    pub thread_id: String,
    pub turn_id: String,
}

impl PromptFinalUseKeyV1 {
    pub fn new(thread_id: &str, turn_id: &str) -> Result<Self, PromptFinalUseStoreError> {
        if thread_id.is_empty()
            || thread_id.len() > 256
            || thread_id.as_bytes().contains(&0)
            || turn_id.is_empty()
            || turn_id.len() > 256
            || turn_id.as_bytes().contains(&0)
        {
            return Err(PromptFinalUseStoreError::InvalidKey);
        }
        Ok(Self {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        })
    }
}

pub struct PromptFinalUseLeaseStore {
    root: PathBuf,
    _lock: File,
    leases: Mutex<BTreeMap<PromptFinalUseKeyV1, PromptFinalUseLeaseV1>>,
    poisoned: AtomicBool,
}

impl fmt::Debug for PromptFinalUseLeaseStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let count = self.leases.lock().map(|leases| leases.len()).unwrap_or(0);
        formatter
            .debug_struct("PromptFinalUseLeaseStore")
            .field("lease_count", &count)
            .field("requires_reopen", &self.poisoned.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}

impl PromptFinalUseLeaseStore {
    pub fn open(directory: &Path) -> Result<Self, PromptFinalUseStoreError> {
        prepare_directory(directory)?;
        let lock_path = directory.join(LOCK_FILE);
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|_| PromptFinalUseStoreError::Unavailable)?;
        set_private_file_permissions(&lock_path)?;
        lock.try_lock()
            .map_err(|_| PromptFinalUseStoreError::StateLocked)?;
        let leases = read_state(directory)?;
        Ok(Self {
            root: directory.to_path_buf(),
            _lock: lock,
            leases: Mutex::new(leases),
            poisoned: AtomicBool::new(false),
        })
    }

    pub fn get(
        &self,
        key: &PromptFinalUseKeyV1,
    ) -> Result<Option<PromptFinalUseLeaseV1>, PromptFinalUseStoreError> {
        self.ensure_available()?;
        Ok(self
            .leases
            .lock()
            .map_err(|_| PromptFinalUseStoreError::StatePoisoned)?
            .get(key)
            .cloned())
    }

    pub fn put(
        &self,
        key: PromptFinalUseKeyV1,
        lease: PromptFinalUseLeaseV1,
    ) -> Result<(), PromptFinalUseStoreError> {
        lease
            .validate_shape()
            .map_err(|_| PromptFinalUseStoreError::Corrupt)?;
        self.commit(|leases| {
            if let Some(existing) = leases.get(&key) {
                return if existing == &lease {
                    Ok(())
                } else {
                    Err(PromptFinalUseStoreError::Conflict)
                };
            }
            if leases.len() >= MAX_LEASES {
                return Err(PromptFinalUseStoreError::CapacityExceeded);
            }
            leases.insert(key, lease);
            Ok(())
        })
    }

    pub fn remove(
        &self,
        key: &PromptFinalUseKeyV1,
    ) -> Result<bool, PromptFinalUseStoreError> {
        self.commit(|leases| Ok(leases.remove(key).is_some()))
    }

    pub fn retain(
        &self,
        mut keep: impl FnMut(&PromptFinalUseKeyV1, &PromptFinalUseLeaseV1) -> bool,
    ) -> Result<usize, PromptFinalUseStoreError> {
        self.commit(|leases| {
            let before = leases.len();
            leases.retain(|key, lease| keep(key, lease));
            Ok(before.saturating_sub(leases.len()))
        })
    }

    pub fn count(&self) -> Result<usize, PromptFinalUseStoreError> {
        self.ensure_available()?;
        Ok(self
            .leases
            .lock()
            .map_err(|_| PromptFinalUseStoreError::StatePoisoned)?
            .len())
    }

    #[must_use]
    pub fn requires_reopen(&self) -> bool {
        self.poisoned.load(Ordering::Acquire)
    }

    fn ensure_available(&self) -> Result<(), PromptFinalUseStoreError> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(PromptFinalUseStoreError::ReopenRequired);
        }
        Ok(())
    }

    fn commit<T>(
        &self,
        mutation: impl FnOnce(
            &mut BTreeMap<PromptFinalUseKeyV1, PromptFinalUseLeaseV1>,
        ) -> Result<T, PromptFinalUseStoreError>,
    ) -> Result<T, PromptFinalUseStoreError> {
        self.ensure_available()?;
        let mut current = self
            .leases
            .lock()
            .map_err(|_| PromptFinalUseStoreError::StatePoisoned)?;
        let mut next = current.clone();
        let result = mutation(&mut next)?;
        if next != *current {
            match persist_state(&self.root, &next) {
                Ok(()) => *current = next,
                Err(PromptFinalUseStoreError::IndeterminateDurability) => {
                    self.poisoned.store(true, Ordering::Release);
                    return Err(PromptFinalUseStoreError::IndeterminateDurability);
                }
                Err(error) => return Err(error),
            }
        }
        Ok(result)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredState {
    schema: u32,
    leases: Vec<StoredLeaseEntry>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredLeaseEntry {
    thread_id: String,
    turn_id: String,
    lease: StoredLease,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredLease {
    schema_version: u32,
    compilation_id: String,
    context_attachment_digest: [u8; 32],
    context_payload_digest: [u8; 32],
    registry_snapshot_digest: [u8; 32],
    generation_vector_digest: [u8; 32],
    model_tuple: StoredModelTuple,
    issued_unix_ms: u64,
    valid_until_unix_ms: u64,
    selections: Vec<StoredSelection>,
    lease_digest: [u8; 32],
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredModelTuple {
    model_id: String,
    model_version: String,
    model_digest: [u8; 32],
    tokenizer_digest: [u8; 32],
    template_digest: [u8; 32],
    tool_schema_digest: [u8; 32],
    context_profile_digest: [u8; 32],
    locale_id: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredSelection {
    factor_id: String,
    realization_id: String,
    binding_digest: [u8; 32],
    payload_digest: [u8; 32],
}

fn read_state(
    directory: &Path,
) -> Result<BTreeMap<PromptFinalUseKeyV1, PromptFinalUseLeaseV1>, PromptFinalUseStoreError> {
    let path = directory.join(STATE_FILE);
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let mut bytes = Vec::new();
    File::open(&path)
        .map_err(|_| PromptFinalUseStoreError::Unavailable)?
        .take(MAX_STATE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| PromptFinalUseStoreError::Unavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
        return Err(PromptFinalUseStoreError::Corrupt);
    }
    let stored: StoredState =
        serde_json::from_slice(&bytes).map_err(|_| PromptFinalUseStoreError::Corrupt)?;
    if stored.schema != STORE_SCHEMA || stored.leases.len() > MAX_LEASES {
        return Err(PromptFinalUseStoreError::Corrupt);
    }
    let mut leases = BTreeMap::new();
    for entry in stored.leases {
        let key = PromptFinalUseKeyV1::new(&entry.thread_id, &entry.turn_id)
            .map_err(|_| PromptFinalUseStoreError::Corrupt)?;
        let lease = restore_lease(entry.lease)?;
        if leases.insert(key, lease).is_some() {
            return Err(PromptFinalUseStoreError::Corrupt);
        }
    }
    Ok(leases)
}

fn persist_state(
    directory: &Path,
    leases: &BTreeMap<PromptFinalUseKeyV1, PromptFinalUseLeaseV1>,
) -> Result<(), PromptFinalUseStoreError> {
    let stored = StoredState {
        schema: STORE_SCHEMA,
        leases: leases
            .iter()
            .map(|(key, lease)| StoredLeaseEntry {
                thread_id: key.thread_id.clone(),
                turn_id: key.turn_id.clone(),
                lease: stored_lease(lease),
            })
            .collect(),
    };
    let bytes = serde_json::to_vec(&stored).map_err(|_| PromptFinalUseStoreError::Unavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
        return Err(PromptFinalUseStoreError::CapacityExceeded);
    }
    let next_path = directory.join(NEXT_FILE);
    let mut next = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&next_path)
        .map_err(|_| PromptFinalUseStoreError::Unavailable)?;
    set_private_file_permissions(&next_path)?;
    next.write_all(&bytes)
        .and_then(|()| next.sync_all())
        .map_err(|_| PromptFinalUseStoreError::Unavailable)?;
    std::fs::rename(&next_path, directory.join(STATE_FILE))
        .map_err(|_| PromptFinalUseStoreError::Unavailable)?;
    sync_directory(directory)
}

fn stored_lease(lease: &PromptFinalUseLeaseV1) -> StoredLease {
    StoredLease {
        schema_version: lease.schema_version,
        compilation_id: lease.compilation_id.to_string(),
        context_attachment_digest: lease.context_attachment_digest.into_array(),
        context_payload_digest: lease.context_payload_digest.into_array(),
        registry_snapshot_digest: lease.registry_snapshot_digest.into_array(),
        generation_vector_digest: lease.generation_vector_digest.into_array(),
        model_tuple: StoredModelTuple {
            model_id: lease.model_tuple.model_id.to_string(),
            model_version: lease.model_tuple.model_version.clone(),
            model_digest: lease.model_tuple.model_digest.into_array(),
            tokenizer_digest: lease.model_tuple.tokenizer_digest.into_array(),
            template_digest: lease.model_tuple.template_digest.into_array(),
            tool_schema_digest: lease.model_tuple.tool_schema_digest.into_array(),
            context_profile_digest: lease.model_tuple.context_profile_digest.into_array(),
            locale_id: lease.model_tuple.locale_id.to_string(),
        },
        issued_unix_ms: lease.issued_unix_ms,
        valid_until_unix_ms: lease.valid_until_unix_ms,
        selections: lease
            .selections
            .iter()
            .map(|selection| StoredSelection {
                factor_id: selection.factor_id.to_string(),
                realization_id: selection.realization_id.to_string(),
                binding_digest: selection.binding_digest.into_array(),
                payload_digest: selection.payload_digest.into_array(),
            })
            .collect(),
        lease_digest: lease.lease_digest.into_array(),
    }
}

fn restore_lease(stored: StoredLease) -> Result<PromptFinalUseLeaseV1, PromptFinalUseStoreError> {
    if stored.schema_version != PROMPT_FINAL_USE_LEASE_SCHEMA {
        return Err(PromptFinalUseStoreError::Corrupt);
    }
    let lease = PromptFinalUseLeaseV1 {
        schema_version: stored.schema_version,
        compilation_id: parse_id(stored.compilation_id)?,
        context_attachment_digest: Digest32::from_array(stored.context_attachment_digest),
        context_payload_digest: Digest32::from_array(stored.context_payload_digest),
        registry_snapshot_digest: Digest32::from_array(stored.registry_snapshot_digest),
        generation_vector_digest: Digest32::from_array(stored.generation_vector_digest),
        model_tuple: PromptModelTupleV2 {
            model_id: parse_id(stored.model_tuple.model_id)?,
            model_version: stored.model_tuple.model_version,
            model_digest: Digest32::from_array(stored.model_tuple.model_digest),
            tokenizer_digest: Digest32::from_array(stored.model_tuple.tokenizer_digest),
            template_digest: Digest32::from_array(stored.model_tuple.template_digest),
            tool_schema_digest: Digest32::from_array(stored.model_tuple.tool_schema_digest),
            context_profile_digest: Digest32::from_array(
                stored.model_tuple.context_profile_digest,
            ),
            locale_id: parse_id(stored.model_tuple.locale_id)?,
        },
        issued_unix_ms: stored.issued_unix_ms,
        valid_until_unix_ms: stored.valid_until_unix_ms,
        selections: stored
            .selections
            .into_iter()
            .map(|selection| {
                Ok(PromptFinalUseSelectionV1 {
                    factor_id: parse_id(selection.factor_id)?,
                    realization_id: parse_id(selection.realization_id)?,
                    binding_digest: Digest32::from_array(selection.binding_digest),
                    payload_digest: Digest32::from_array(selection.payload_digest),
                })
            })
            .collect::<Result<Vec<_>, PromptFinalUseStoreError>>()?,
        lease_digest: Digest32::from_array(stored.lease_digest),
    };
    lease
        .validate_shape()
        .map_err(|_| PromptFinalUseStoreError::Corrupt)?;
    Ok(lease)
}

fn parse_id(value: String) -> Result<StableId, PromptFinalUseStoreError> {
    StableId::new(value).map_err(|_| PromptFinalUseStoreError::Corrupt)
}

fn prepare_directory(path: &Path) -> Result<(), PromptFinalUseStoreError> {
    if let Err(error) = std::fs::create_dir(path)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(PromptFinalUseStoreError::Unavailable);
    }
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| PromptFinalUseStoreError::Unavailable)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(PromptFinalUseStoreError::Corrupt);
    }
    set_private_directory_permissions(path)
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &Path) -> Result<(), PromptFinalUseStoreError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|_| PromptFinalUseStoreError::Unavailable)
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &Path) -> Result<(), PromptFinalUseStoreError> {
    Ok(())
}

#[cfg(unix)]
fn set_private_file_permissions(path: &Path) -> Result<(), PromptFinalUseStoreError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .map_err(|_| PromptFinalUseStoreError::Unavailable)
}

#[cfg(not(unix))]
fn set_private_file_permissions(_path: &Path) -> Result<(), PromptFinalUseStoreError> {
    Ok(())
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), PromptFinalUseStoreError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| PromptFinalUseStoreError::IndeterminateDurability)
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), PromptFinalUseStoreError> {
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptFinalUseStoreError {
    InvalidKey,
    Conflict,
    CapacityExceeded,
    Corrupt,
    StateLocked,
    StatePoisoned,
    Unavailable,
    IndeterminateDurability,
    ReopenRequired,
}

impl fmt::Display for PromptFinalUseStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PromptFinalUseStoreError {}

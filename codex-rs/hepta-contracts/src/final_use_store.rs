//! Persistent nonce/revocation owner. OS locks are released on process death.
use super::FinalUseError;
use super::FinalUseRevocations;
use super::MAX_CLAIMS;
use super::State;
use super::valid_head;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;

#[path = "final_use_journal.rs"]
mod journal;

use journal::Journal;
use journal::Recovery;

const METADATA_FILE: &str = "authority.json";
const METADATA_NEXT_FILE: &str = "authority.next";
const MAX_METADATA_BYTES: u64 = 8 * 1024 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredV1 {
    schema: u32,
    signer_id: String,
    verifying_key: [u8; 32],
    state: State,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredV2 {
    schema: u32,
    signer_id: String,
    verifying_key: [u8; 32],
    head: FinalUseRevocations,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum StoredAny {
    V2(StoredV2),
    V1(StoredV1),
}

pub(super) struct Store {
    root: File,
    signer_id: String,
    verifying_key: [u8; 32],
    lock: File,
    journal: Mutex<Option<Journal>>,
}

impl Store {
    pub(super) fn open(
        root: &Path,
        signer_id: &str,
        verifying_key: [u8; 32],
        initial: FinalUseRevocations,
    ) -> Result<(Self, State), FinalUseError> {
        let root = prepare_directory(root)?;
        let initialized = entry_exists(&root, "authority.lock")?;
        if !initialized && entry_exists(&root, METADATA_FILE)? {
            return Err(FinalUseError::InvalidTrust);
        }
        let lock = open_private(&root, "authority.lock", Access::Create)?;
        lock.try_lock().map_err(|_| FinalUseError::StateLocked)?;
        let store = Self {
            root,
            signer_id: signer_id.to_owned(),
            verifying_key,
            lock,
            journal: Mutex::new(None),
        };
        if !entry_exists(&store.root, METADATA_FILE)? {
            // Once initialized, absence is data loss, never permission to reset
            // the replay registry. An interrupted first start also fails closed.
            if initialized {
                return Err(FinalUseError::InvalidTrust);
            }
            let state = State {
                head: initial,
                used_nonces: BTreeSet::new(),
                failed: false,
            };
            store.reset_nonce_log(state.head.authority_epoch, &state.used_nonces)?;
            store.persist_head(&state.head)?;
            return Ok((store, state));
        }

        let stored = read_metadata(&store.root)?;
        let mut state = match stored {
            StoredAny::V1(legacy) => {
                if legacy.schema != 1
                    || legacy.signer_id != signer_id
                    || legacy.verifying_key != verifying_key
                    || !valid_head(&legacy.state.head)
                    || legacy.state.used_nonces.len() > MAX_CLAIMS
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                let mut state = legacy.state;
                state.failed = false;
                reconcile_initial(&mut state, initial)?;
                // Migration is ordered so authority.json remains a complete V1
                // recovery anchor until the nonce snapshot is durable. Once V3
                // metadata is published, a missing/corrupt nonce log fails closed.
                store.reset_nonce_log(state.head.authority_epoch, &state.used_nonces)?;
                store.persist_head(&state.head)?;
                state
            }
            StoredAny::V2(metadata) => {
                if !matches!(metadata.schema, 2 | 3)
                    || metadata.signer_id != signer_id
                    || metadata.verifying_key != verifying_key
                    || !valid_head(&metadata.head)
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                let recovery = if metadata.schema == 3 {
                    Recovery::Anchored
                } else {
                    Recovery::Legacy
                };
                let (journal, used_nonces) =
                    Journal::open(&store.root, metadata.head.authority_epoch, recovery)?;
                *store
                    .journal
                    .lock()
                    .map_err(|_| FinalUseError::Unavailable)? = Some(journal);
                let mut state = State {
                    head: metadata.head,
                    used_nonces,
                    failed: false,
                };
                let previous_epoch = state.head.authority_epoch;
                let advanced = reconcile_initial(&mut state, initial)?;
                if advanced || metadata.schema == 2 {
                    store.persist_head(&state.head)?;
                }
                if state.head.authority_epoch > previous_epoch {
                    store.reset_nonce_log(state.head.authority_epoch, &state.used_nonces)?;
                }
                state
            }
        };
        state.failed = false;
        Ok((store, state))
    }

    /// Persist a monotonic revocation head. Same-epoch updates rewrite only the
    /// bounded metadata object. Epoch changes additionally rotate the nonce log.
    pub(super) fn persist_revocations(
        &self,
        previous_epoch: u64,
        state: &State,
    ) -> Result<(), FinalUseError> {
        self.ensure_live()?;
        self.persist_head(&state.head)?;
        if state.head.authority_epoch > previous_epoch {
            self.reset_nonce_log(state.head.authority_epoch, &state.used_nonces)?;
        }
        Ok(())
    }

    /// Append exactly one durable claim. The caller holds the in-process state
    /// mutex and the store holds an OS owner lock, so there is one append writer.
    pub(super) fn persist_claim(
        &self,
        authority_epoch: u64,
        nonce: [u8; 32],
    ) -> Result<(), FinalUseError> {
        self.ensure_live()?;
        self.journal
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?
            .as_mut()
            .ok_or(FinalUseError::InvalidTrust)?
            .append(&self.root, authority_epoch, nonce)
    }

    pub(super) fn ensure_live(&self) -> Result<(), FinalUseError> {
        let lock = open_private(&self.root, "authority.lock", Access::Read)?;
        if !same_file(&self.lock, &lock)? {
            return Err(FinalUseError::InvalidTrust);
        }
        self.journal
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?
            .as_ref()
            .ok_or(FinalUseError::InvalidTrust)?
            .ensure_live(&self.root)
    }

    fn persist_head(&self, head: &FinalUseRevocations) -> Result<(), FinalUseError> {
        let stored = StoredV2 {
            schema: 3,
            signer_id: self.signer_id.clone(),
            verifying_key: self.verifying_key,
            head: head.clone(),
        };
        let bytes = serde_json::to_vec(&stored).map_err(|_| FinalUseError::Unavailable)?;
        let mut file = open_private(&self.root, METADATA_NEXT_FILE, Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)?;
        replace_entry(&self.root, METADATA_NEXT_FILE, METADATA_FILE)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }

    fn reset_nonce_log(
        &self,
        authority_epoch: u64,
        nonces: &BTreeSet<[u8; 32]>,
    ) -> Result<(), FinalUseError> {
        let journal = Journal::reset(&self.root, authority_epoch, nonces)?;
        *self
            .journal
            .lock()
            .map_err(|_| FinalUseError::Unavailable)? = Some(journal);
        Ok(())
    }
}

/// Apply the trusted startup head using the same monotonic rules as V1. The
/// return value says whether durable metadata must be advanced.
fn reconcile_initial(
    state: &mut State,
    initial: FinalUseRevocations,
) -> Result<bool, FinalUseError> {
    if initial.authority_epoch >= state.head.authority_epoch
        && initial.revision > state.head.revision
        && (initial.authority_epoch > state.head.authority_epoch
            || initial
                .revoked_grant_ids
                .is_superset(&state.head.revoked_grant_ids))
    {
        if initial.authority_epoch > state.head.authority_epoch {
            state.used_nonces.clear();
        }
        state.head = initial;
        Ok(true)
    } else if state.head.authority_epoch < initial.authority_epoch
        || state.head.revision < initial.revision
        || (state.head.authority_epoch == initial.authority_epoch
            && !state
                .head
                .revoked_grant_ids
                .is_superset(&initial.revoked_grant_ids))
    {
        Err(FinalUseError::InvalidTrust)
    } else {
        Ok(false)
    }
}

fn read_metadata(directory: &File) -> Result<StoredAny, FinalUseError> {
    let mut bytes = Vec::new();
    open_private(directory, METADATA_FILE, Access::Read)?
        .take(MAX_METADATA_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| FinalUseError::Unavailable)?;
    if bytes.len() as u64 > MAX_METADATA_BYTES {
        return Err(FinalUseError::InvalidTrust);
    }
    serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)
}

enum Access {
    Read,
    Write,
    Create,
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, FinalUseError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;
    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(FinalUseError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| FinalUseError::UnsafeStateDirectory)?
    .into();
    let metadata = directory
        .metadata()
        .map_err(|_| FinalUseError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(FinalUseError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(unix)]
fn open_private(directory: &File, name: &str, access: Access) -> Result<File, FinalUseError> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::os::unix::fs::MetadataExt;
    let flags = match access {
        Access::Read => OFlags::RDONLY,
        Access::Write => OFlags::RDWR,
        Access::Create => OFlags::RDWR | OFlags::CREATE,
    } | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(directory, name, flags, Mode::RUSR | Mode::WUSR)
        .map_err(|_| FinalUseError::Unavailable)?
        .into();
    let metadata = file.metadata().map_err(|_| FinalUseError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(FinalUseError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(not(unix))]
fn prepare_directory(_root: &Path) -> Result<File, FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}
#[cfg(not(unix))]
fn open_private(_directory: &File, _name: &str, _access: Access) -> Result<File, FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, FinalUseError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(FinalUseError::Unavailable),
    }
}

#[cfg(unix)]
fn replace_entry(directory: &File, from: &str, to: &str) -> Result<(), FinalUseError> {
    rustix::fs::renameat(directory, from, directory, to).map_err(|_| FinalUseError::Unavailable)
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}
#[cfg(not(unix))]
fn replace_entry(_directory: &File, _from: &str, _to: &str) -> Result<(), FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}

#[cfg(unix)]
fn same_file(left: &File, right: &File) -> Result<bool, FinalUseError> {
    use std::os::unix::fs::MetadataExt;
    let left = left.metadata().map_err(|_| FinalUseError::Unavailable)?;
    let right = right.metadata().map_err(|_| FinalUseError::Unavailable)?;
    Ok(left.dev() == right.dev() && left.ino() == right.ino())
}

#[cfg(not(unix))]
fn same_file(_left: &File, _right: &File) -> Result<bool, FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}

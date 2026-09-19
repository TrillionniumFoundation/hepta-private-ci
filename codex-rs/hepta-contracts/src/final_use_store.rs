//! Persistent nonce/revocation owner. OS locks are released on process death.
//!
//! Schema 2 separates the small authority head snapshot from an append-only
//! claim journal. A claim therefore performs O(1) durable append I/O instead of
//! serializing and rewriting the complete nonce set.

use super::FinalUseError;
use super::FinalUseRevocations;
use super::MAX_CLAIMS;
use super::State;
use super::valid_head;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom, Write};
use std::path::Path;
use std::sync::Mutex;

const CURRENT_SCHEMA: u32 = 2;
const CLAIM_SCHEMA: u32 = 1;
const LEGACY_MAX_CLAIMS: usize = 16_384;
const MAX_AUTHORITY_BYTES: u64 = 2 * 1024 * 1024;
const MAX_CLAIM_JOURNAL_BYTES: u64 = 256 * 1024 * 1024;

#[derive(Deserialize)]
struct StoredEnvelope {
    schema: u32,
}

#[derive(Deserialize)]
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

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ClaimEntry {
    schema: u32,
    authority_epoch: u64,
    nonce: [u8; 32],
}

pub(super) struct Store {
    root: File,
    signer_id: String,
    verifying_key: [u8; 32],
    claims: Mutex<File>,
    _lock: File,
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
        let lock = open_private(&root, "authority.lock", Access::Create)?;
        lock.try_lock().map_err(|_| FinalUseError::StateLocked)?;
        let claims = open_private(&root, "claims.log", Access::Create)?;
        let store = Self {
            root,
            signer_id: signer_id.to_owned(),
            verifying_key,
            claims: Mutex::new(claims),
            _lock: lock,
        };

        let has_state = entry_exists(&store.root, "authority.json")?;
        let mut state = if has_state {
            store.load_state(signer_id, verifying_key)?
        } else {
            // Once initialization began, missing authority state is data loss,
            // never permission to reset the replay registry.
            if initialized {
                return Err(FinalUseError::InvalidTrust);
            }
            let state = State {
                head: initial.clone(),
                used_nonces: BTreeSet::new(),
                failed: false,
            };
            store.persist_head(&initial)?;
            state
        };

        if initial.authority_epoch >= state.head.authority_epoch
            && initial.revision > state.head.revision
            && (initial.authority_epoch > state.head.authority_epoch
                || initial
                    .revoked_grant_ids
                    .is_superset(&state.head.revoked_grant_ids))
        {
            let epoch_changed = initial.authority_epoch > state.head.authority_epoch;
            state.head = initial;
            if epoch_changed {
                state.used_nonces.clear();
            }
            // Persist the stronger head before dropping old-epoch journal
            // entries. A crash can therefore retain extra stale claims, but
            // never lose replay protection for the still-authoritative epoch.
            store.persist_head(&state.head)?;
            if epoch_changed {
                store.compact_claims()?;
            }
        } else if state.head.authority_epoch < initial.authority_epoch
            || state.head.revision < initial.revision
            || (state.head.authority_epoch == initial.authority_epoch
                && !state
                    .head
                    .revoked_grant_ids
                    .is_superset(&initial.revoked_grant_ids))
        {
            return Err(FinalUseError::InvalidTrust);
        }

        Ok((store, state))
    }

    fn load_state(
        &self,
        signer_id: &str,
        verifying_key: [u8; 32],
    ) -> Result<State, FinalUseError> {
        let mut bytes = Vec::new();
        open_private(&self.root, "authority.json", Access::Read)?
            .take(MAX_AUTHORITY_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| FinalUseError::Unavailable)?;
        if bytes.len() as u64 > MAX_AUTHORITY_BYTES {
            return Err(FinalUseError::InvalidTrust);
        }
        let envelope: StoredEnvelope =
            serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;

        let mut state = match envelope.schema {
            1 => {
                let stored: StoredV1 =
                    serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                if stored.schema != 1
                    || stored.signer_id != signer_id
                    || stored.verifying_key != verifying_key
                    || !valid_head(&stored.state.head)
                    || stored.state.used_nonces.len() > LEGACY_MAX_CLAIMS
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                stored.state
            }
            CURRENT_SCHEMA => {
                let stored: StoredV2 =
                    serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                if stored.signer_id != signer_id
                    || stored.verifying_key != verifying_key
                    || !valid_head(&stored.head)
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                State {
                    head: stored.head,
                    used_nonces: BTreeSet::new(),
                    failed: false,
                }
            }
            _ => return Err(FinalUseError::InvalidTrust),
        };

        let journal_claims = self.load_claims(state.head.authority_epoch)?;
        if state.used_nonces.len().saturating_add(journal_claims.len()) > MAX_CLAIMS {
            return Err(FinalUseError::InvalidTrust);
        }
        state.used_nonces.extend(journal_claims);

        if envelope.schema == 1 {
            // Migration is monotonic: journal claims first, then replace the
            // old complete JSON snapshot with the small schema-2 head.
            for nonce in &state.used_nonces {
                self.append_claim_entry(state.head.authority_epoch, *nonce)?;
            }
            self.persist_head(&state.head)?;
        }

        Ok(state)
    }

    fn load_claims(&self, authority_epoch: u64) -> Result<BTreeSet<[u8; 32]>, FinalUseError> {
        let file = self
            .claims
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?
            .try_clone()
            .map_err(|_| FinalUseError::Unavailable)?;
        let metadata = file.metadata().map_err(|_| FinalUseError::Unavailable)?;
        if metadata.len() > MAX_CLAIM_JOURNAL_BYTES {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut claims = BTreeSet::new();
        for line in BufReader::new(file).lines() {
            let line = line.map_err(|_| FinalUseError::InvalidTrust)?;
            if line.is_empty() {
                continue;
            }
            let entry: ClaimEntry =
                serde_json::from_str(&line).map_err(|_| FinalUseError::InvalidTrust)?;
            if entry.schema != CLAIM_SCHEMA || entry.authority_epoch == 0 || entry.nonce == [0; 32] {
                return Err(FinalUseError::InvalidTrust);
            }
            if entry.authority_epoch == authority_epoch {
                claims.insert(entry.nonce);
                if claims.len() > MAX_CLAIMS {
                    return Err(FinalUseError::InvalidTrust);
                }
            }
        }
        Ok(claims)
    }

    pub(super) fn persist_claim(
        &self,
        authority_epoch: u64,
        nonce: [u8; 32],
    ) -> Result<(), FinalUseError> {
        self.append_claim_entry(authority_epoch, nonce)
    }

    fn append_claim_entry(
        &self,
        authority_epoch: u64,
        nonce: [u8; 32],
    ) -> Result<(), FinalUseError> {
        let entry = ClaimEntry {
            schema: CLAIM_SCHEMA,
            authority_epoch,
            nonce,
        };
        let mut bytes = serde_json::to_vec(&entry).map_err(|_| FinalUseError::Unavailable)?;
        bytes.push(b'\n');
        let mut file = self
            .claims
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        let current = file.metadata().map_err(|_| FinalUseError::Unavailable)?.len();
        if current.saturating_add(bytes.len() as u64) > MAX_CLAIM_JOURNAL_BYTES {
            return Err(FinalUseError::CapacityExceeded);
        }
        file.seek(SeekFrom::End(0))
            .and_then(|_| file.write_all(&bytes))
            .and_then(|_| file.sync_data())
            .map_err(|_| FinalUseError::Unavailable)
    }

    pub(super) fn persist_head(&self, head: &FinalUseRevocations) -> Result<(), FinalUseError> {
        let stored = StoredV2 {
            schema: CURRENT_SCHEMA,
            signer_id: self.signer_id.clone(),
            verifying_key: self.verifying_key,
            head: head.clone(),
        };
        let bytes = serde_json::to_vec(&stored).map_err(|_| FinalUseError::Unavailable)?;
        let mut file = open_private(&self.root, "authority.next", Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)?;
        replace_state(&self.root)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }

    pub(super) fn compact_claims(&self) -> Result<(), FinalUseError> {
        let mut file = self
            .claims
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        file.seek(SeekFrom::Start(0))
            .and_then(|_| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)
    }
}

enum Access {
    Read,
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
fn replace_state(directory: &File) -> Result<(), FinalUseError> {
    rustix::fs::renameat(directory, "authority.next", directory, "authority.json")
        .map_err(|_| FinalUseError::Unavailable)
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}
#[cfg(not(unix))]
fn replace_state(_directory: &File) -> Result<(), FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}

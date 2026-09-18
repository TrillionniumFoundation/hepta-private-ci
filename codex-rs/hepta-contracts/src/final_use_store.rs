//! Persistent nonce/revocation owner. OS locks are released on process death.
//!
//! Schema 2 separates the compact revocation-head snapshot from an append-only
//! fixed-width nonce journal. A claim therefore performs O(1) durable I/O
//! instead of rewriting the complete replay set.

use super::FinalUseError;
use super::FinalUseRevocations;
use super::MAX_REVOKED_GRANTS;
use super::State;
use super::valid_head;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

const STATE_SCHEMA_V1: u32 = 1;
const STATE_SCHEMA_V2: u32 = 2;
const MAX_HEAD_BYTES: u64 = 8 * 1024 * 1024;
const CLAIM_BYTES: usize = 32;

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

pub(super) struct Store {
    root: File,
    signer_id: String,
    verifying_key: [u8; 32],
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
        let store = Self {
            root,
            signer_id: signer_id.to_owned(),
            verifying_key,
            _lock: lock,
        };
        let has_state = entry_exists(&store.root, "authority.json")?;
        let mut state = if has_state {
            store.load_state()?
        } else {
            // Once initialization has started, missing durable state is data
            // loss, never permission to reset the replay registry.
            if initialized {
                return Err(FinalUseError::InvalidTrust);
            }
            let state = State {
                head: initial.clone(),
                used_nonces: BTreeSet::new(),
                failed: false,
            };
            store.persist_head(&state.head)?;
            store.reset_claims()?;
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
            // Persist the stronger head before clearing old-epoch claims. A
            // crash between these operations leaves harmless extra denials,
            // never an empty registry under an old epoch.
            store.persist_head(&initial)?;
            if epoch_changed {
                store.reset_claims()?;
                state.used_nonces.clear();
            }
            state.head = initial;
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

    fn load_state(&self) -> Result<State, FinalUseError> {
        let bytes = read_bounded(&self.root, "authority.json", MAX_HEAD_BYTES)?;
        let value: serde_json::Value =
            serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
        let schema = value
            .get("schema")
            .and_then(serde_json::Value::as_u64)
            .ok_or(FinalUseError::InvalidTrust)?;
        match schema {
            value if value == u64::from(STATE_SCHEMA_V1) => self.load_and_migrate_v1(&bytes),
            value if value == u64::from(STATE_SCHEMA_V2) => {
                let stored: StoredV2 =
                    serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                if stored.schema != STATE_SCHEMA_V2
                    || stored.signer_id != self.signer_id
                    || stored.verifying_key != self.verifying_key
                    || !valid_head(&stored.head)
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                Ok(State {
                    head: stored.head,
                    used_nonces: self.load_claims()?,
                    failed: false,
                })
            }
            _ => Err(FinalUseError::InvalidTrust),
        }
    }

    fn load_and_migrate_v1(&self, bytes: &[u8]) -> Result<State, FinalUseError> {
        let stored: StoredV1 =
            serde_json::from_slice(bytes).map_err(|_| FinalUseError::InvalidTrust)?;
        if stored.schema != STATE_SCHEMA_V1
            || stored.signer_id != self.signer_id
            || stored.verifying_key != self.verifying_key
            || !valid_head(&stored.state.head)
            || stored.state.used_nonces.len() > MAX_REVOKED_GRANTS
            || stored.state.used_nonces.contains(&[0; CLAIM_BYTES])
        {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut state = stored.state;
        state.failed = false;
        // Journal first, then publish schema 2. A crash before the head rename
        // leaves schema 1 authoritative and migration is safely repeatable.
        self.replace_claims(&state.used_nonces)?;
        self.persist_head(&state.head)?;
        Ok(state)
    }

    fn load_claims(&self) -> Result<BTreeSet<[u8; CLAIM_BYTES]>, FinalUseError> {
        if !entry_exists(&self.root, "authority.claims")? {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut file = open_private(&self.root, "authority.claims", Access::Read)?;
        let length = file
            .metadata()
            .map_err(|_| FinalUseError::Unavailable)?
            .len();
        if length % CLAIM_BYTES as u64 != 0 {
            return Err(FinalUseError::InvalidTrust);
        }
        let count = length / CLAIM_BYTES as u64;
        let capacity = usize::try_from(count).map_err(|_| FinalUseError::InvalidTrust)?;
        let mut claims = BTreeSet::new();
        for _ in 0..capacity {
            let mut nonce = [0; CLAIM_BYTES];
            file.read_exact(&mut nonce)
                .map_err(|_| FinalUseError::InvalidTrust)?;
            if nonce == [0; CLAIM_BYTES] || !claims.insert(nonce) {
                return Err(FinalUseError::InvalidTrust);
            }
        }
        Ok(claims)
    }

    /// O(1) durable replay claim. A partial append is intentionally fatal:
    /// the live authority fences itself and a restart rejects the malformed
    /// journal instead of guessing whether the nonce was committed.
    pub(super) fn append_claim(&self, nonce: &[u8; CLAIM_BYTES]) -> Result<(), FinalUseError> {
        if *nonce == [0; CLAIM_BYTES] {
            return Err(FinalUseError::InvalidGrant);
        }
        let mut file = open_private(&self.root, "authority.claims", Access::Append)?;
        file.write_all(nonce)
            .and_then(|()| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)
    }

    /// Persist only the bounded revocation/trust snapshot.
    pub(super) fn persist_head(&self, head: &FinalUseRevocations) -> Result<(), FinalUseError> {
        if !valid_head(head) {
            return Err(FinalUseError::InvalidTrust);
        }
        let stored = StoredV2 {
            schema: STATE_SCHEMA_V2,
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

    /// Clear claims only after a strictly newer authority epoch is durable.
    pub(super) fn reset_claims(&self) -> Result<(), FinalUseError> {
        let file = open_private(&self.root, "authority.claims", Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        file.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }

    fn replace_claims(
        &self,
        claims: &BTreeSet<[u8; CLAIM_BYTES]>,
    ) -> Result<(), FinalUseError> {
        let mut file = open_private(&self.root, "authority.claims", Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        for nonce in claims {
            file.write_all(nonce)
                .map_err(|_| FinalUseError::Unavailable)?;
        }
        file.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }
}

fn read_bounded(directory: &File, name: &str, maximum: u64) -> Result<Vec<u8>, FinalUseError> {
    let mut bytes = Vec::new();
    open_private(directory, name, Access::Read)?
        .take(maximum + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| FinalUseError::Unavailable)?;
    if bytes.len() as u64 > maximum {
        return Err(FinalUseError::InvalidTrust);
    }
    Ok(bytes)
}

enum Access {
    Read,
    Create,
    Append,
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
        Access::Append => OFlags::WRONLY | OFlags::APPEND,
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

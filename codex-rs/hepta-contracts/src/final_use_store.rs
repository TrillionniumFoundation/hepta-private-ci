//! Persistent nonce/revocation owner. OS locks are released on process death.
use super::FinalUseError;
use super::FinalUseRevocations;
use super::State;
use super::valid_head;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

const STATE_MAX_BYTES: u64 = 8 * 1024 * 1024;
const CLAIM_RECORD_BYTES: u64 = 40;
// Roughly 26 million fixed-size claims. This is a corruption/resource guard,
// not an authority-epoch cardinality contract; unlike the old JSON snapshot,
// normal epochs are not capped at 16,384 uses.
const CLAIM_JOURNAL_MAX_BYTES: u64 = 1024 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredV1 {
    schema: u32,
    signer_id: String,
    verifying_key: [u8; 32],
    state: LegacyState,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LegacyState {
    head: FinalUseRevocations,
    used_nonces: BTreeSet<[u8; 32]>,
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
    claims: File,
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
        let claims = open_private(&root, "authority.claims", Access::Append)?;
        let store = Self {
            root,
            signer_id: signer_id.to_owned(),
            verifying_key,
            _lock: lock,
            claims,
        };
        let has_state = entry_exists(&store.root, "authority.json")?;
        let mut state = if has_state {
            store.load_state(initial)?
        } else {
            // Once initialized, absence is data loss, never permission to
            // reset the replay registry. An interrupted first start also
            // fails closed and needs explicit owner recovery.
            if initialized {
                return Err(FinalUseError::InvalidTrust);
            }
            let state = State {
                head: initial,
                used_nonces: Default::default(),
                failed: false,
            };
            store.persist(&state)?;
            state
        };

        state.used_nonces = load_claims(&store.root, state.head.authority_epoch)?;
        Ok((store, state))
    }

    fn load_state(&self, initial: FinalUseRevocations) -> Result<State, FinalUseError> {
        let mut bytes = Vec::new();
        open_private(&self.root, "authority.json", Access::Read)?
            .take(STATE_MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| FinalUseError::Unavailable)?;
        if bytes.len() as u64 > STATE_MAX_BYTES {
            return Err(FinalUseError::InvalidTrust);
        }
        let value: serde_json::Value =
            serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
        let schema = value
            .get("schema")
            .and_then(serde_json::Value::as_u64)
            .ok_or(FinalUseError::InvalidTrust)?;

        let (mut state, legacy_claims) = match schema {
            1 => {
                let stored: StoredV1 =
                    serde_json::from_value(value).map_err(|_| FinalUseError::InvalidTrust)?;
                if stored.schema != 1
                    || stored.signer_id != self.signer_id
                    || stored.verifying_key != self.verifying_key
                    || !valid_head(&stored.state.head)
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                (
                    State {
                        head: stored.state.head,
                        used_nonces: Default::default(),
                        failed: false,
                    },
                    Some(stored.state.used_nonces),
                )
            }
            2 => {
                let stored: StoredV2 =
                    serde_json::from_value(value).map_err(|_| FinalUseError::InvalidTrust)?;
                if stored.schema != 2
                    || stored.signer_id != self.signer_id
                    || stored.verifying_key != self.verifying_key
                    || !valid_head(&stored.head)
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                (
                    State {
                        head: stored.head,
                        used_nonces: Default::default(),
                        failed: false,
                    },
                    None,
                )
            }
            _ => return Err(FinalUseError::InvalidTrust),
        };

        let mut journal_claims = load_claims(&self.root, state.head.authority_epoch)?;
        if let Some(legacy_claims) = legacy_claims {
            // Migrate V1 snapshot claims before replacing the state metadata.
            // Re-running after a crash is safe because only missing claims are
            // appended and replay loading deduplicates exact records.
            for nonce in legacy_claims {
                if !journal_claims.contains(&nonce) {
                    self.persist_claim(state.head.authority_epoch, nonce)?;
                    journal_claims.insert(nonce);
                }
            }
            state.used_nonces = journal_claims.clone();
            self.persist(&state)?;
        }

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
            self.persist(&state)?;
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
        Ok(state)
    }

    /// Persist only trust/revocation metadata. Replay claims have their own
    /// fixed-record fsync journal and do not make this write grow with traffic.
    pub(super) fn persist(&self, state: &State) -> Result<(), FinalUseError> {
        let stored = StoredV2 {
            schema: 2,
            signer_id: self.signer_id.clone(),
            verifying_key: self.verifying_key,
            head: state.head.clone(),
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

    pub(super) fn persist_claim(
        &self,
        authority_epoch: u64,
        nonce: [u8; 32],
    ) -> Result<(), FinalUseError> {
        if authority_epoch == 0 || nonce == [0; 32] {
            return Err(FinalUseError::InvalidTrust);
        }
        let length = self
            .claims
            .metadata()
            .map_err(|_| FinalUseError::Unavailable)?
            .len();
        if length > CLAIM_JOURNAL_MAX_BYTES.saturating_sub(CLAIM_RECORD_BYTES) {
            return Err(FinalUseError::Unavailable);
        }
        let mut record = [0_u8; CLAIM_RECORD_BYTES as usize];
        record[..8].copy_from_slice(&authority_epoch.to_be_bytes());
        record[8..].copy_from_slice(&nonce);
        (&self.claims)
            .write_all(&record)
            .and_then(|()| self.claims.sync_data())
            .map_err(|_| FinalUseError::Unavailable)
    }
}

fn load_claims(directory: &File, current_epoch: u64) -> Result<BTreeSet<[u8; 32]>, FinalUseError> {
    if !entry_exists(directory, "authority.claims")? {
        return Ok(BTreeSet::new());
    }
    let mut file = open_private(directory, "authority.claims", Access::Read)?;
    let length = file
        .metadata()
        .map_err(|_| FinalUseError::Unavailable)?
        .len();
    if length > CLAIM_JOURNAL_MAX_BYTES || length % CLAIM_RECORD_BYTES != 0 {
        return Err(FinalUseError::InvalidTrust);
    }
    let mut claims = BTreeSet::new();
    let mut record = [0_u8; CLAIM_RECORD_BYTES as usize];
    for _ in 0..(length / CLAIM_RECORD_BYTES) {
        file.read_exact(&mut record)
            .map_err(|_| FinalUseError::InvalidTrust)?;
        let mut epoch_bytes = [0_u8; 8];
        epoch_bytes.copy_from_slice(&record[..8]);
        let epoch = u64::from_be_bytes(epoch_bytes);
        let mut nonce = [0_u8; 32];
        nonce.copy_from_slice(&record[8..]);
        if epoch == 0 || nonce == [0; 32] || epoch > current_epoch {
            // Future-epoch records are evidence of rollback or corruption.
            return Err(FinalUseError::InvalidTrust);
        }
        if epoch == current_epoch {
            claims.insert(nonce);
        }
    }
    Ok(claims)
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
        Access::Append => OFlags::WRONLY | OFlags::CREATE | OFlags::APPEND,
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

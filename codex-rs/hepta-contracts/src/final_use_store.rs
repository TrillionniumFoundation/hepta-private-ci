//! Persistent nonce/revocation owner. OS locks are released on process death.
//!
//! The compact authority snapshot is checkpointed only for trust/revocation
//! updates. Hot-path nonce claims use an append-only, fsynced fixed-record
//! journal so one claim is O(1) durable I/O instead of an O(N) JSON rewrite.
use super::FinalUseError;
use super::FinalUseRevocations;
use super::State;
use super::valid_head;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

const CLAIM_RECORD_BYTES: usize = 40;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Stored {
    schema: u32,
    signer_id: String,
    verifying_key: [u8; 32],
    state: State,
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
            let mut bytes = Vec::new();
            open_private(&store.root, "authority.json", Access::Read)?
                .take(8 * 1024 * 1024 + 1)
                .read_to_end(&mut bytes)
                .map_err(|_| FinalUseError::Unavailable)?;
            if bytes.len() > 8 * 1024 * 1024 {
                return Err(FinalUseError::InvalidTrust);
            }
            let stored: Stored =
                serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
            if stored.schema != 1
                || stored.signer_id != signer_id
                || stored.verifying_key != verifying_key
                || !valid_head(&stored.state.head)
            {
                return Err(FinalUseError::InvalidTrust);
            }
            stored.state
        } else {
            // Once initialized, absence is data loss, never permission to
            // reset the replay registry. An interrupted first start also
            // fails closed and needs explicit owner recovery.
            if initialized {
                return Err(FinalUseError::InvalidTrust);
            }
            State {
                head: initial.clone(),
                used_nonces: Default::default(),
                failed: false,
            }
        };

        // Replay claims before any snapshot advancement. A checkpoint written
        // below may compact the journal only after those durable claims have
        // been merged into the snapshot.
        store.replay_claims(&mut state)?;

        if has_state {
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
                store.persist(&state)?;
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
        } else {
            store.persist(&state)?;
        }
        Ok((store, state))
    }

    /// Durably burn one nonce. The record is fixed-size so append cost does not
    /// grow with the number of claims. A successful append is never refunded.
    pub(super) fn append_claim(
        &self,
        authority_epoch: u64,
        nonce: [u8; 32],
    ) -> Result<(), FinalUseError> {
        if authority_epoch == 0 || nonce == [0; 32] {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut file = open_private(&self.root, "claims.log", Access::Append)?;
        file.write_all(&authority_epoch.to_be_bytes())
            .and_then(|()| file.write_all(&nonce))
            .and_then(|()| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)
    }

    /// Checkpoint the complete in-memory replay set together with the current
    /// revocation head. Only after the snapshot rename and parent fsync succeed
    /// may the append journal be truncated.
    pub(super) fn persist(&self, state: &State) -> Result<(), FinalUseError> {
        let stored = Stored {
            schema: 1,
            signer_id: self.signer_id.clone(),
            verifying_key: self.verifying_key,
            state: state.clone(),
        };
        let bytes = serde_json::to_vec(&stored).map_err(|_| FinalUseError::Unavailable)?;
        let mut file = open_private(&self.root, "authority.next", Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)?;
        replace_state(&self.root)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        self.reset_claim_log()
    }

    fn replay_claims(&self, state: &mut State) -> Result<(), FinalUseError> {
        let mut file = open_private(&self.root, "claims.log", Access::Create)?;
        let mut record = [0_u8; CLAIM_RECORD_BYTES];
        loop {
            let mut offset = 0;
            while offset < CLAIM_RECORD_BYTES {
                match file.read(&mut record[offset..]) {
                    Ok(0) if offset == 0 => return Ok(()),
                    Ok(0) => return Err(FinalUseError::InvalidTrust),
                    Ok(read) => offset += read,
                    Err(_) => return Err(FinalUseError::Unavailable),
                }
            }
            let epoch = u64::from_be_bytes(
                record[..8]
                    .try_into()
                    .map_err(|_| FinalUseError::InvalidTrust)?,
            );
            let nonce: [u8; 32] = record[8..]
                .try_into()
                .map_err(|_| FinalUseError::InvalidTrust)?;
            if epoch == 0 || nonce == [0; 32] || epoch > state.head.authority_epoch {
                return Err(FinalUseError::InvalidTrust);
            }
            if epoch == state.head.authority_epoch {
                state.used_nonces.insert(nonce);
            }
        }
    }

    fn reset_claim_log(&self) -> Result<(), FinalUseError> {
        let file = open_private(&self.root, "claims.log", Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        file.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }
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

//! Persistent nonce/revocation owner. OS locks are released on process death.
use super::FinalUseError;
use super::FinalUseRevocations;
use super::MAX_CLAIMS;
use super::State;
use super::valid_head;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

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
    issuer_trust_sha256: [u8; 32],
    state: State,
}

#[derive(Clone, Copy)]
enum StoreTrust {
    SingleKey([u8; 32]),
    IssuerKeyRing([u8; 32]),
}

pub(super) struct Store {
    root: File,
    signer_id: String,
    trust: StoreTrust,
    _lock: File,
}

impl Store {
    pub(super) fn open(
        root: &Path,
        signer_id: &str,
        verifying_key: [u8; 32],
        initial: FinalUseRevocations,
    ) -> Result<(Self, State), FinalUseError> {
        Self::open_inner(
            root,
            signer_id,
            StoreTrust::SingleKey(verifying_key),
            initial,
            true,
        )
    }

    pub(super) fn open_exact(
        root: &Path,
        signer_id: &str,
        verifying_key: [u8; 32],
        initial: FinalUseRevocations,
    ) -> Result<(Self, State), FinalUseError> {
        Self::open_inner(
            root,
            signer_id,
            StoreTrust::SingleKey(verifying_key),
            initial,
            false,
        )
    }

    pub(super) fn open_key_ring_exact(
        root: &Path,
        signer_id: &str,
        issuer_trust_sha256: [u8; 32],
        initial: FinalUseRevocations,
    ) -> Result<(Self, State), FinalUseError> {
        Self::open_inner(
            root,
            signer_id,
            StoreTrust::IssuerKeyRing(issuer_trust_sha256),
            initial,
            false,
        )
    }

    fn open_inner(
        root: &Path,
        signer_id: &str,
        trust: StoreTrust,
        initial: FinalUseRevocations,
        allow_startup_head_advance: bool,
    ) -> Result<(Self, State), FinalUseError> {
        let root = prepare_directory(root)?;
        let initialized = entry_exists(&root, "authority.lock")?;
        let lock = open_private(&root, "authority.lock", Access::Create)?;
        lock.try_lock().map_err(|_| FinalUseError::StateLocked)?;
        let store = Self {
            root,
            signer_id: signer_id.to_owned(),
            trust,
            _lock: lock,
        };
        let has_state = entry_exists(&store.root, "authority.json")?;
        let state = if has_state {
            let mut bytes = Vec::new();
            open_private(&store.root, "authority.json", Access::Read)?
                .take(8 * 1024 * 1024 + 1)
                .read_to_end(&mut bytes)
                .map_err(|_| FinalUseError::Unavailable)?;
            if bytes.len() > 8 * 1024 * 1024 {
                return Err(FinalUseError::InvalidTrust);
            }
            let value: serde_json::Value =
                serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
            let schema = value
                .get("schema")
                .and_then(serde_json::Value::as_u64)
                .ok_or(FinalUseError::InvalidTrust)?;
            let mut state = match (trust, schema) {
                (StoreTrust::SingleKey(verifying_key), 1) => {
                    let stored: StoredV1 =
                        serde_json::from_value(value).map_err(|_| FinalUseError::InvalidTrust)?;
                    if stored.signer_id != signer_id || stored.verifying_key != verifying_key {
                        return Err(FinalUseError::InvalidTrust);
                    }
                    stored.state
                }
                (StoreTrust::IssuerKeyRing(issuer_trust_sha256), 2) => {
                    let stored: StoredV2 =
                        serde_json::from_value(value).map_err(|_| FinalUseError::InvalidTrust)?;
                    if stored.signer_id != signer_id
                        || stored.issuer_trust_sha256 != issuer_trust_sha256
                    {
                        return Err(FinalUseError::InvalidTrust);
                    }
                    stored.state
                }
                _ => return Err(FinalUseError::InvalidTrust),
            };
            if !valid_head(&state.head) || state.used_nonces.len() > MAX_CLAIMS {
                return Err(FinalUseError::InvalidTrust);
            }
            if allow_startup_head_advance {
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
            } else if state.head != initial {
                return Err(FinalUseError::InvalidTrust);
            }
            state
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
        Ok((store, state))
    }

    pub(super) fn persist(&self, state: &State) -> Result<(), FinalUseError> {
        let bytes = match self.trust {
            StoreTrust::SingleKey(verifying_key) => serde_json::to_vec(&StoredV1 {
                schema: 1,
                signer_id: self.signer_id.clone(),
                verifying_key,
                state: state.clone(),
            }),
            StoreTrust::IssuerKeyRing(issuer_trust_sha256) => serde_json::to_vec(&StoredV2 {
                schema: 2,
                signer_id: self.signer_id.clone(),
                issuer_trust_sha256,
                state: state.clone(),
            }),
        }
        .map_err(|_| FinalUseError::Unavailable)?;
        let mut file = open_private(&self.root, "authority.next", Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)?;
        replace_state(&self.root)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
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

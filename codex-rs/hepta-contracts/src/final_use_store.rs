//! Persistent nonce/revocation owner. OS locks are released on process death.
use super::FinalUseError;
use super::FinalUseRevocations;
use super::MAX_CLAIMS;
use super::State;
use super::nonce_log;
use super::valid_head;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredSingleKey {
    schema: u32,
    signer_id: String,
    verifying_key: [u8; 32],
    state: State,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredKeyRing {
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
    log_length: AtomicU64,
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
            log_length: AtomicU64::new(0),
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
                (StoreTrust::SingleKey(verifying_key), 1 | 3) => {
                    let stored: StoredSingleKey =
                        serde_json::from_value(value).map_err(|_| FinalUseError::InvalidTrust)?;
                    if !matches!(stored.schema, 1 | 3)
                        || stored.signer_id != signer_id
                        || stored.verifying_key != verifying_key
                    {
                        return Err(FinalUseError::InvalidTrust);
                    }
                    stored.state
                }
                (StoreTrust::IssuerKeyRing(issuer_trust_sha256), 2 | 4) => {
                    let stored: StoredKeyRing =
                        serde_json::from_value(value).map_err(|_| FinalUseError::InvalidTrust)?;
                    if !matches!(stored.schema, 2 | 4)
                        || stored.signer_id != signer_id
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
            let mut checkpoint_needed = schema <= 2;
            if schema >= 3 {
                // The schema commits to the journal's existence. Missing data
                // is corruption, not a legacy store that may be bootstrapped.
                let mut bytes = Vec::new();
                open_private(&store.root, "authority.nonces", Access::Read)?
                    .take((nonce_log::MAX_LOG_BYTES + nonce_log::RECORD_BYTES) as u64)
                    .read_to_end(&mut bytes)
                    .map_err(|_| FinalUseError::Unavailable)?;
                nonce_log::replay(&bytes, &mut state, store.nonce_trust_digest())?;
                checkpoint_needed = !bytes.is_empty();
            } else {
                store.prepare_nonce_log()?;
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
                    checkpoint_needed = true;
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
            if checkpoint_needed {
                store.persist(&state)?;
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
            store.prepare_nonce_log()?;
            store.persist(&state)?;
            state
        };
        Ok((store, state))
    }

    pub(super) fn persist(&self, state: &State) -> Result<(), FinalUseError> {
        let bytes = match self.trust {
            StoreTrust::SingleKey(verifying_key) => serde_json::to_vec(&StoredSingleKey {
                schema: 3,
                signer_id: self.signer_id.clone(),
                verifying_key,
                state: state.clone(),
            }),
            StoreTrust::IssuerKeyRing(issuer_trust_sha256) => serde_json::to_vec(&StoredKeyRing {
                schema: 4,
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
        self.root
            .sync_all()
            .map_err(|_| FinalUseError::Unavailable)?;
        // Never discard deltas before their replacement checkpoint AND its
        // directory entry are durable. Replaying the old log is idempotent if
        // a crash lands between that barrier and this truncation.
        let log = open_private(&self.root, "authority.nonces", Access::Append)?;
        log.set_len(0)
            .and_then(|()| log.sync_all())
            .map_err(|_| FinalUseError::Unavailable)?;
        self.log_length.store(0, Ordering::Relaxed);
        Ok(())
    }

    /// Claim writes append one fixed-size record; head changes checkpoint the
    /// complete state. The caller holds the authority mutex and advances its
    /// independent frontier first, preserving the existing fail-stop ordering.
    pub(super) fn persist_update(&self, old: &State, next: &State) -> Result<(), FinalUseError> {
        if old.head != next.head {
            return self.persist(next);
        }
        if next.used_nonces.len() != old.used_nonces.len() + 1
            || !next.used_nonces.is_superset(&old.used_nonces)
        {
            return Err(FinalUseError::InvalidTrust);
        }
        let nonce = next
            .used_nonces
            .difference(&old.used_nonces)
            .next()
            .copied()
            .ok_or(FinalUseError::InvalidTrust)?;
        let record = nonce_log::encode(next, nonce, self.nonce_trust_digest());
        let mut log = open_private(&self.root, "authority.nonces", Access::Append)?;
        let length = log
            .metadata()
            .map_err(|_| FinalUseError::Unavailable)?
            .len();
        if length != self.log_length.load(Ordering::Relaxed)
            || length % nonce_log::RECORD_BYTES as u64 != 0
            || length >= nonce_log::MAX_LOG_BYTES as u64
        {
            return Err(FinalUseError::InvalidTrust);
        }
        log.write_all(&record)
            .and_then(|()| log.sync_all())
            .map_err(|_| FinalUseError::Unavailable)?;
        self.log_length
            .store(length + nonce_log::RECORD_BYTES as u64, Ordering::Relaxed);
        Ok(())
    }

    fn prepare_nonce_log(&self) -> Result<(), FinalUseError> {
        let log = open_private(&self.root, "authority.nonces", Access::Create)?;
        // Nonempty deltas under a legacy checkpoint suggest a partial restore;
        // do not erase them or silently reclassify that store as fresh.
        if log
            .metadata()
            .map_err(|_| FinalUseError::Unavailable)?
            .len()
            != 0
        {
            return Err(FinalUseError::InvalidTrust);
        }
        log.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }

    fn nonce_trust_digest(&self) -> [u8; 32] {
        let mut hash = Sha256::new();
        hash.update(b"hepta.kernel.authority.nonce-owner.v1\0");
        hash.update((self.signer_id.len() as u64).to_le_bytes());
        hash.update(self.signer_id.as_bytes());
        match self.trust {
            StoreTrust::SingleKey(key) => {
                hash.update([1]);
                hash.update(key);
            }
            StoreTrust::IssuerKeyRing(digest) => {
                hash.update([2]);
                hash.update(digest);
            }
        }
        hash.finalize().into()
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
        Access::Append => OFlags::RDWR | OFlags::APPEND,
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

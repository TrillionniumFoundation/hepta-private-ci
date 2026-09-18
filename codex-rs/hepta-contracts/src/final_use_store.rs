//! Persistent nonce/revocation owner.
//!
//! The authority head is a small atomic snapshot. Claims are appended to a
//! checksummed journal so the hot path never rewrites the complete replay set.
//! The lock is acquired only for a mutation/final-use fence; multiple authority
//! processes may therefore share one qualified POSIX state directory.

use super::FinalUseError;
use super::FinalUseRevocations;
use super::State;
use super::valid_head;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;

const MAX_STATE_BYTES: u64 = 8 * 1024 * 1024;
const CLAIM_MAGIC: &[u8; 4] = b"HFC2";
const CLAIM_RECORD_BYTES: usize = 4 + 8 + 32 + 32;

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

#[derive(Deserialize)]
struct StoredSchema {
    schema: u32,
}

pub(super) struct Store {
    root: File,
    signer_id: String,
    verifying_key: [u8; 32],
}

impl Store {
    pub(super) fn open(
        root: &Path,
        signer_id: &str,
        verifying_key: [u8; 32],
        initial: FinalUseRevocations,
    ) -> Result<(Self, State), FinalUseError> {
        let root = prepare_directory(root)?;
        let store = Self {
            root,
            signer_id: signer_id.to_owned(),
            verifying_key,
        };
        // Atomically create the durable initialization marker or open the
        // existing one, then take the same exclusive fence used by mutations.
        // O_EXCL removes the race where two first-openers both observed absence
        // before either created the marker.
        let (_guard, created_marker) = store.lock_initialization()?;
        let has_state = entry_exists(&store.root, "authority.json")?;
        if created_marker && has_state {
            // State without its original lock inode cannot be reopened safely:
            // another process may still hold the unlinked inode.
            return Err(FinalUseError::InvalidTrust);
        }
        let mut state = if has_state {
            store.load_or_migrate()?
        } else {
            // Once initialization has begun, absence of the snapshot is data
            // loss (or an interrupted first initialization), never permission
            // to reset replay state.
            if !created_marker {
                return Err(FinalUseError::InvalidTrust);
            }
            let state = State {
                head: initial.clone(),
                used_nonces: Default::default(),
                failed: false,
                claim_log_bytes: 0,
            };
            store.persist_head(&state.head)?;
            store.initialize_claim_log()?;
            state
        };

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
            store.persist_head(&state.head)?;
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

    /// Acquire the cross-process serialization/final-use fence. Once the
    /// store exists, the lock inode is part of the durable schema and is never
    /// recreated implicitly: a missing lock file fails closed instead of
    /// allowing two generations to lock different inodes.
    pub(super) fn lock_mutation(&self) -> Result<File, FinalUseError> {
        let file = open_private(&self.root, "authority.lock", Access::ReadWrite)?;
        file.lock().map_err(|_| FinalUseError::Unavailable)?;
        Ok(file)
    }

    fn lock_initialization(&self) -> Result<(File, bool), FinalUseError> {
        let (file, created) = create_or_open_lock(&self.root, "authority.lock")?;
        file.lock().map_err(|_| FinalUseError::Unavailable)?;
        Ok((file, created))
    }

    /// Incrementally refresh the small head plus only journal records appended
    /// since this owner last synchronized. Callers hold the mutation lock.
    pub(super) fn refresh(&self, cached: &State) -> Result<State, FinalUseError> {
        let head = self.load_head_v2()?;
        let mut next = cached.clone();
        if next.head.authority_epoch != head.authority_epoch {
            next.used_nonces.clear();
        }
        next.head = head;
        let (claims, end) =
            self.load_claims_from(next.claim_log_bytes, next.head.authority_epoch)?;
        next.used_nonces.extend(claims);
        next.claim_log_bytes = end;
        next.failed = false;
        Ok(next)
    }

    /// Persist only the small authority/revocation head.
    pub(super) fn persist_head(&self, head: &FinalUseRevocations) -> Result<(), FinalUseError> {
        let stored = StoredV2 {
            schema: 2,
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
        replace_entry(&self.root, "authority.next", "authority.json")?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }

    /// Append and sync one replay claim. A partial or corrupt record causes the
    /// next open/refresh to fail closed instead of silently forgetting a nonce.
    pub(super) fn append_claim(
        &self,
        authority_epoch: u64,
        nonce: [u8; 32],
        expected_offset: u64,
    ) -> Result<u64, FinalUseError> {
        let record = claim_record(authority_epoch, nonce);
        let mut file = open_private(&self.root, "claims.log", Access::Create)?;
        let end = file
            .seek(SeekFrom::End(0))
            .map_err(|_| FinalUseError::Unavailable)?;
        if end != expected_offset {
            return Err(FinalUseError::InvalidTrust);
        }
        file.write_all(&record)
            .and_then(|()| file.sync_data())
            .map_err(|_| FinalUseError::Unavailable)?;
        end.checked_add(CLAIM_RECORD_BYTES as u64)
            .ok_or(FinalUseError::Unavailable)
    }

    fn initialize_claim_log(&self) -> Result<(), FinalUseError> {
        if entry_exists(&self.root, "claims.log")? {
            return Err(FinalUseError::InvalidTrust);
        }
        let file = open_private(&self.root, "claims.log", Access::Create)?;
        file.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }

    fn load_or_migrate(&self) -> Result<State, FinalUseError> {
        let bytes = read_bounded(&self.root, "authority.json")?;
        let schema: StoredSchema =
            serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
        match schema.schema {
            1 => {
                let stored: StoredV1 =
                    serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                if stored.schema != 1
                    || stored.signer_id != self.signer_id
                    || stored.verifying_key != self.verifying_key
                    || !valid_head(&stored.state.head)
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                // Migration is deliberately ordered journal-first, snapshot
                // second. A crash between them merely repeats an idempotent
                // union on the next open; it never drops an old claim.
                let mut claims = if entry_exists(&self.root, "claims.log")? {
                    self.load_claims_from(0, stored.state.head.authority_epoch)?.0
                } else {
                    BTreeSet::new()
                };
                claims.extend(stored.state.used_nonces.iter().copied());
                let end = self.replace_claims(stored.state.head.authority_epoch, &claims)?;
                self.persist_head(&stored.state.head)?;
                Ok(State {
                    head: stored.state.head,
                    used_nonces: claims,
                    failed: false,
                    claim_log_bytes: end,
                })
            }
            2 => {
                let stored: StoredV2 =
                    serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                if stored.schema != 2
                    || stored.signer_id != self.signer_id
                    || stored.verifying_key != self.verifying_key
                    || !valid_head(&stored.head)
                {
                    return Err(FinalUseError::InvalidTrust);
                }
                let (claims, end) = self.load_claims_from(0, stored.head.authority_epoch)?;
                Ok(State {
                    head: stored.head,
                    used_nonces: claims,
                    failed: false,
                    claim_log_bytes: end,
                })
            }
            _ => Err(FinalUseError::InvalidTrust),
        }
    }

    fn load_head_v2(&self) -> Result<FinalUseRevocations, FinalUseError> {
        let bytes = read_bounded(&self.root, "authority.json")?;
        let stored: StoredV2 =
            serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
        if stored.schema != 2
            || stored.signer_id != self.signer_id
            || stored.verifying_key != self.verifying_key
            || !valid_head(&stored.head)
        {
            return Err(FinalUseError::InvalidTrust);
        }
        Ok(stored.head)
    }

    fn load_claims_from(
        &self,
        start: u64,
        current_epoch: u64,
    ) -> Result<(BTreeSet<[u8; 32]>, u64), FinalUseError> {
        if start % CLAIM_RECORD_BYTES as u64 != 0 {
            return Err(FinalUseError::InvalidTrust);
        }
        if !entry_exists(&self.root, "claims.log")? {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut file = open_private(&self.root, "claims.log", Access::Read)?;
        let length = file
            .metadata()
            .map_err(|_| FinalUseError::Unavailable)?
            .len();
        if start > length || length % CLAIM_RECORD_BYTES as u64 != 0 {
            return Err(FinalUseError::InvalidTrust);
        }
        file.seek(SeekFrom::Start(start))
            .map_err(|_| FinalUseError::Unavailable)?;
        let mut claims = BTreeSet::new();
        let mut offset = start;
        while offset < length {
            let mut record = [0u8; CLAIM_RECORD_BYTES];
            file.read_exact(&mut record)
                .map_err(|_| FinalUseError::InvalidTrust)?;
            let (epoch, nonce) = parse_claim_record(&record)?;
            if epoch == current_epoch {
                claims.insert(nonce);
            }
            offset = offset
                .checked_add(CLAIM_RECORD_BYTES as u64)
                .ok_or(FinalUseError::InvalidTrust)?;
        }
        Ok((claims, offset))
    }

    fn replace_claims(
        &self,
        authority_epoch: u64,
        claims: &BTreeSet<[u8; 32]>,
    ) -> Result<u64, FinalUseError> {
        let mut file = open_private(&self.root, "claims.next", Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        for nonce in claims {
            file.write_all(&claim_record(authority_epoch, *nonce))
                .map_err(|_| FinalUseError::Unavailable)?;
        }
        file.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        let length = file
            .metadata()
            .map_err(|_| FinalUseError::Unavailable)?
            .len();
        replace_entry(&self.root, "claims.next", "claims.log")?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        Ok(length)
    }
}

fn claim_record(authority_epoch: u64, nonce: [u8; 32]) -> [u8; CLAIM_RECORD_BYTES] {
    let mut record = [0u8; CLAIM_RECORD_BYTES];
    record[..4].copy_from_slice(CLAIM_MAGIC);
    record[4..12].copy_from_slice(&authority_epoch.to_be_bytes());
    record[12..44].copy_from_slice(&nonce);
    let checksum = Sha256::digest(&record[..44]);
    record[44..].copy_from_slice(&checksum);
    record
}

fn parse_claim_record(
    record: &[u8; CLAIM_RECORD_BYTES],
) -> Result<(u64, [u8; 32]), FinalUseError> {
    if &record[..4] != CLAIM_MAGIC {
        return Err(FinalUseError::InvalidTrust);
    }
    let mut epoch_bytes = [0u8; 8];
    epoch_bytes.copy_from_slice(&record[4..12]);
    let epoch = u64::from_be_bytes(epoch_bytes);
    if epoch == 0 {
        return Err(FinalUseError::InvalidTrust);
    }
    let expected = Sha256::digest(&record[..44]);
    if expected.as_slice() != &record[44..] {
        return Err(FinalUseError::InvalidTrust);
    }
    let mut nonce = [0u8; 32];
    nonce.copy_from_slice(&record[12..44]);
    if nonce == [0; 32] {
        return Err(FinalUseError::InvalidTrust);
    }
    Ok((epoch, nonce))
}

fn read_bounded(directory: &File, name: &str) -> Result<Vec<u8>, FinalUseError> {
    let mut bytes = Vec::new();
    open_private(directory, name, Access::Read)?
        .take(MAX_STATE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| FinalUseError::Unavailable)?;
    if bytes.len() as u64 > MAX_STATE_BYTES {
        return Err(FinalUseError::InvalidTrust);
    }
    Ok(bytes)
}

enum Access {
    Read,
    ReadWrite,
    Create,
}

#[cfg(unix)]
fn create_or_open_lock(
    directory: &File,
    name: &str,
) -> Result<(File, bool), FinalUseError> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::os::unix::fs::MetadataExt;

    let flags = OFlags::RDWR
        | OFlags::CREATE
        | OFlags::EXCL
        | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let (file, created): (File, bool) = match rustix::fs::openat(
        directory,
        name,
        flags,
        Mode::RUSR | Mode::WUSR,
    ) {
        Ok(fd) => (fd.into(), true),
        Err(rustix::io::Errno::EXIST) => (
            open_private(directory, name, Access::ReadWrite)?,
            false,
        ),
        Err(_) => return Err(FinalUseError::Unavailable),
    };
    let metadata = file.metadata().map_err(|_| FinalUseError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(FinalUseError::UnsafeStateDirectory);
    }
    if created {
        file.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        directory.sync_all().map_err(|_| FinalUseError::Unavailable)?;
    }
    Ok((file, created))
}

#[cfg(not(unix))]
fn create_or_open_lock(
    _directory: &File,
    _name: &str,
) -> Result<(File, bool), FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
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
        Access::ReadWrite => OFlags::RDWR,
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

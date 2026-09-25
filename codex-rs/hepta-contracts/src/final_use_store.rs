//! Persistent nonce/revocation owner. OS locks are released on process death.
//!
//! Revocation/trust state is a small atomic snapshot. Replay claims use a
//! fixed-width append-only journal so the dispatch hot path does not rewrite an
//! ever-growing JSON set.

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
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;

const STATE_SCHEMA_V1: u32 = 1;
const STATE_SCHEMA_V2: u32 = 2;
const STATE_SCHEMA_V3: u32 = 3;
const CLAIM_FRAME_BYTES: usize = 8 + 32;

#[derive(Deserialize)]
struct StoredHeader {
    schema: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredV1 {
    schema: u32,
    signer_id: String,
    verifying_key: [u8; 32],
    state: State,
}

// Schema 2 was independently used by the key-ring snapshot and the
// single-key journal. Distinct fields make both legacy formats unambiguous.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredV2 {
    schema: u32,
    signer_id: String,
    issuer_trust_sha256: [u8; 32],
    state: State,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredJournalV2 {
    schema: u32,
    signer_id: String,
    verifying_key: [u8; 32],
    head: FinalUseRevocations,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredV3 {
    schema: u32,
    signer_id: String,
    trust: StoreTrust,
    head: FinalUseRevocations,
}

#[derive(Clone, Copy, Deserialize, Eq, PartialEq, Serialize)]
enum StoreTrust {
    SingleKey([u8; 32]),
    IssuerKeyRing([u8; 32]),
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum StartupHeadPolicy {
    Advance,
    Exact,
    Recover,
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
            StartupHeadPolicy::Advance,
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
            StartupHeadPolicy::Exact,
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
            StartupHeadPolicy::Exact,
        )
    }

    pub(super) fn open_key_ring_recovered(
        root: &Path,
        signer_id: &str,
        issuer_trust_sha256: [u8; 32],
        initial: FinalUseRevocations,
    ) -> Result<(Self, State), FinalUseError> {
        // Existing state is never advanced from the bootstrap hint. The caller
        // must compare its complete frontier with the independent backend.
        Self::open_inner(
            root,
            signer_id,
            StoreTrust::IssuerKeyRing(issuer_trust_sha256),
            initial,
            StartupHeadPolicy::Recover,
        )
    }

    fn open_inner(
        root: &Path,
        signer_id: &str,
        trust: StoreTrust,
        initial: FinalUseRevocations,
        startup_head_policy: StartupHeadPolicy,
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
        let mut state = if has_state {
            let bytes = read_bounded(&store.root, "authority.json", 8 * 1024 * 1024)?;
            let header: StoredHeader =
                serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
            let (mut state, legacy_snapshot) = match (trust, header.schema) {
                (StoreTrust::SingleKey(verifying_key), STATE_SCHEMA_V1) => {
                    let stored: StoredV1 =
                        serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                    if stored.signer_id != signer_id || stored.verifying_key != verifying_key {
                        return Err(FinalUseError::InvalidTrust);
                    }
                    (stored.state, true)
                }
                (StoreTrust::IssuerKeyRing(issuer_trust_sha256), STATE_SCHEMA_V2) => {
                    let stored: StoredV2 =
                        serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                    if stored.schema != STATE_SCHEMA_V2
                        || stored.signer_id != signer_id
                        || stored.issuer_trust_sha256 != issuer_trust_sha256
                    {
                        return Err(FinalUseError::InvalidTrust);
                    }
                    (stored.state, true)
                }
                (StoreTrust::SingleKey(verifying_key), STATE_SCHEMA_V2) => {
                    let stored: StoredJournalV2 =
                        serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                    if stored.schema != STATE_SCHEMA_V2
                        || stored.signer_id != signer_id
                        || stored.verifying_key != verifying_key
                    {
                        return Err(FinalUseError::InvalidTrust);
                    }
                    (
                        State {
                            used_nonces: store.read_claims(stored.head.authority_epoch)?,
                            head: stored.head,
                            failed: false,
                        },
                        false,
                    )
                }
                (_, STATE_SCHEMA_V3) => {
                    let stored: StoredV3 =
                        serde_json::from_slice(&bytes).map_err(|_| FinalUseError::InvalidTrust)?;
                    if stored.signer_id != signer_id || stored.trust != trust {
                        return Err(FinalUseError::InvalidTrust);
                    }
                    (
                        State {
                            used_nonces: store.read_claims(stored.head.authority_epoch)?,
                            head: stored.head,
                            failed: false,
                        },
                        false,
                    )
                }
                _ => return Err(FinalUseError::InvalidTrust),
            };
            if !valid_head(&state.head) || state.used_nonces.len() > MAX_CLAIMS {
                return Err(FinalUseError::InvalidTrust);
            }
            state.failed = false;
            if header.schema != STATE_SCHEMA_V3 {
                // Publish a complete legacy nonce set before its journal-based
                // snapshot. Retrying an interrupted migration is idempotent.
                if legacy_snapshot {
                    store.replace_claims(state.head.authority_epoch, &state.used_nonces)?;
                }
                store.persist_snapshot(&state.head)?;
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
                head: initial.clone(),
                used_nonces: Default::default(),
                failed: false,
            };
            store.replace_claims(initial.authority_epoch, &state.used_nonces)?;
            store.persist_snapshot(&initial)?;
            state
        };

        if startup_head_policy == StartupHeadPolicy::Advance {
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
        } else if startup_head_policy == StartupHeadPolicy::Exact && state.head != initial {
            return Err(FinalUseError::InvalidTrust);
        }

        Ok((store, state))
    }

    /// Persist a revocation/epoch transition. This path is not the per-claim
    /// hot path, so it may compact the claim journal to the current epoch.
    pub(super) fn persist(&self, state: &State) -> Result<(), FinalUseError> {
        self.persist_snapshot(&state.head)?;
        self.replace_claims(state.head.authority_epoch, &state.used_nonces)
    }

    /// Durably burn one nonce. The fixed frame makes claim persistence O(1)
    /// in the number of prior claims.
    pub(super) fn append_claim(
        &self,
        authority_epoch: u64,
        nonce: [u8; 32],
    ) -> Result<(), FinalUseError> {
        if authority_epoch == 0 || nonce == [0; 32] {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut file = open_private(&self.root, "authority.claims", Access::Write)?;
        file.seek(SeekFrom::End(0))
            .map_err(|_| FinalUseError::Unavailable)?;
        file.write_all(&authority_epoch.to_be_bytes())
            .and_then(|()| file.write_all(&nonce))
            .and_then(|()| file.sync_all())
            .map_err(|_| FinalUseError::Unavailable)
    }

    fn persist_snapshot(&self, head: &FinalUseRevocations) -> Result<(), FinalUseError> {
        let stored = StoredV3 {
            schema: STATE_SCHEMA_V3,
            signer_id: self.signer_id.clone(),
            trust: self.trust,
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

    fn read_claims(&self, authority_epoch: u64) -> Result<BTreeSet<[u8; 32]>, FinalUseError> {
        if !entry_exists(&self.root, "authority.claims")? {
            return Err(FinalUseError::InvalidTrust);
        }
        let maximum = MAX_CLAIMS
            .checked_mul(CLAIM_FRAME_BYTES)
            .and_then(|value| value.checked_add(CLAIM_FRAME_BYTES))
            .ok_or(FinalUseError::InvalidTrust)?;
        let bytes = read_bounded(&self.root, "authority.claims", maximum)?;
        if bytes.len() % CLAIM_FRAME_BYTES != 0 {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut claims = BTreeSet::new();
        for frame in bytes.chunks_exact(CLAIM_FRAME_BYTES) {
            let mut epoch_bytes = [0u8; 8];
            epoch_bytes.copy_from_slice(&frame[..8]);
            let epoch = u64::from_be_bytes(epoch_bytes);
            if epoch == 0 || epoch > authority_epoch {
                return Err(FinalUseError::InvalidTrust);
            }
            if epoch == authority_epoch {
                let mut nonce = [0u8; 32];
                nonce.copy_from_slice(&frame[8..]);
                if nonce == [0; 32] || !claims.insert(nonce) {
                    return Err(FinalUseError::InvalidTrust);
                }
            }
        }
        if claims.len() > MAX_CLAIMS {
            return Err(FinalUseError::InvalidTrust);
        }
        Ok(claims)
    }

    fn replace_claims(
        &self,
        authority_epoch: u64,
        claims: &BTreeSet<[u8; 32]>,
    ) -> Result<(), FinalUseError> {
        if authority_epoch == 0 || claims.len() > MAX_CLAIMS {
            return Err(FinalUseError::InvalidTrust);
        }
        let mut file = open_private(&self.root, "authority.claims.next", Access::Create)?;
        file.set_len(0).map_err(|_| FinalUseError::Unavailable)?;
        for nonce in claims {
            if *nonce == [0; 32] {
                return Err(FinalUseError::InvalidTrust);
            }
            file.write_all(&authority_epoch.to_be_bytes())
                .and_then(|()| file.write_all(nonce))
                .map_err(|_| FinalUseError::Unavailable)?;
        }
        file.sync_all().map_err(|_| FinalUseError::Unavailable)?;
        replace_claims(&self.root)?;
        self.root.sync_all().map_err(|_| FinalUseError::Unavailable)
    }
}

fn read_bounded(directory: &File, name: &str, maximum: usize) -> Result<Vec<u8>, FinalUseError> {
    let mut bytes = Vec::new();
    open_private(directory, name, Access::Read)?
        .take(u64::try_from(maximum).map_err(|_| FinalUseError::InvalidTrust)? + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| FinalUseError::Unavailable)?;
    if bytes.len() > maximum {
        return Err(FinalUseError::InvalidTrust);
    }
    Ok(bytes)
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
fn replace_state(directory: &File) -> Result<(), FinalUseError> {
    rustix::fs::renameat(directory, "authority.next", directory, "authority.json")
        .map_err(|_| FinalUseError::Unavailable)
}

#[cfg(unix)]
fn replace_claims(directory: &File) -> Result<(), FinalUseError> {
    rustix::fs::renameat(
        directory,
        "authority.claims.next",
        directory,
        "authority.claims",
    )
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
#[cfg(not(unix))]
fn replace_claims(_directory: &File) -> Result<(), FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}

#[cfg(all(test, unix))]
#[path = "final_use_store_tests.rs"]
mod tests;

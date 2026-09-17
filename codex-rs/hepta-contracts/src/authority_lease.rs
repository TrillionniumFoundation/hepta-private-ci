//! Durable capability lease owner for `kernel.authority`.
//!
//! This is the native owner for the documented `authority_lease` and
//! `capability_revocation` domains.  It deliberately does not perform effects.
//! A host supplies an externally protected authority frontier and trusted time;
//! stale frontiers, stale revisions, expired leases and revoked leases fail
//! closed.

use std::collections::BTreeMap;
use std::fmt;
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};

const SCHEMA_VERSION: u32 = 1;
const MAX_LEASES: usize = 16_384;
const MAX_STATE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_LEASE_LIFETIME_MS: u64 = 86_400_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityFrontier {
    pub authority_epoch: u64,
    pub revision: u64,
}

impl AuthorityFrontier {
    fn valid(self) -> bool {
        self.authority_epoch > 0 && self.revision > 0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityLease {
    pub schema_version: u32,
    pub lease_id: String,
    pub principal_id: String,
    pub operation_class: String,
    pub destination_id: String,
    pub scope_sha256: [u8; 32],
    pub payload_sha256: [u8; 32],
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub authority_epoch: u64,
    pub revision: u64,
    pub signer_id: String,
}

impl AuthorityLease {
    pub fn validate(&self) -> Result<(), AuthorityLeaseError> {
        if self.schema_version != SCHEMA_VERSION
            || !identifier(&self.lease_id)
            || !identifier(&self.principal_id)
            || !identifier(&self.operation_class)
            || !identifier(&self.destination_id)
            || !identifier(&self.signer_id)
            || self.scope_sha256 == [0; 32]
            || self.payload_sha256 == [0; 32]
            || self.authority_epoch == 0
            || self.revision == 0
            || self.expires_at_unix_ms <= self.issued_at_unix_ms
            || self.expires_at_unix_ms - self.issued_at_unix_ms > MAX_LEASE_LIFETIME_MS
        {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityRevocation {
    pub schema_version: u32,
    pub lease_id: String,
    pub authority_epoch: u64,
    pub revision: u64,
    pub reason_sha256: [u8; 32],
    pub revoked_at_unix_ms: u64,
}

impl CapabilityRevocation {
    fn validate(&self) -> Result<(), AuthorityLeaseError> {
        if self.schema_version != SCHEMA_VERSION
            || !identifier(&self.lease_id)
            || self.authority_epoch == 0
            || self.revision == 0
            || self.reason_sha256 == [0; 32]
            || self.revoked_at_unix_ms == 0
        {
            return Err(AuthorityLeaseError::InvalidRevocation);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityLeaseRead {
    pub lease: AuthorityLease,
    pub revocation: Option<CapabilityRevocation>,
    pub frontier: AuthorityFrontier,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct State {
    frontier: AuthorityFrontier,
    leases: BTreeMap<String, AuthorityLease>,
    revocations: BTreeMap<String, CapabilityRevocation>,
    #[serde(skip)]
    failed: bool,
}

struct Inner {
    state: Mutex<State>,
    store: Store,
}

#[derive(Clone)]
pub struct AuthorityLeaseRegistry(Arc<Inner>);

impl fmt::Debug for AuthorityLeaseRegistry {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("AuthorityLeaseRegistry([PINNED OWNER STATE])")
    }
}

/// Opaque proof that one current lease matched the exact final-use binding.
/// It is intentionally neither cloneable nor serializable.
pub struct LeaseVerifiedUse {
    owner: Arc<Inner>,
    lease: AuthorityLease,
}

impl fmt::Debug for LeaseVerifiedUse {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("LeaseVerifiedUse([REDACTED])")
    }
}

impl AuthorityLeaseRegistry {
    /// Open the only authoritative local writer. `trusted_frontier` must come
    /// from an external anti-rollback owner; a stale frontier is rejected.
    pub fn open_state_dir(
        directory: &Path,
        trusted_frontier: AuthorityFrontier,
    ) -> Result<Self, AuthorityLeaseError> {
        if !trusted_frontier.valid() {
            return Err(AuthorityLeaseError::InvalidFrontier);
        }
        let (store, state) = Store::open(directory, trusted_frontier)?;
        Ok(Self(Arc::new(Inner {
            state: Mutex::new(state),
            store,
        })))
    }

    pub fn frontier(&self) -> Result<AuthorityFrontier, AuthorityLeaseError> {
        let state = self.lock_state()?;
        Ok(state.frontier)
    }

    /// Owner-only lease creation. Reusing an existing lease id is always a
    /// conflict; callers must create a new identity instead of mutating meaning.
    pub fn issue_lease(
        &self,
        lease: AuthorityLease,
        expected_frontier_revision: u64,
    ) -> Result<AuthorityFrontier, AuthorityLeaseError> {
        lease.validate()?;
        let mut state = self.lock_state()?;
        if state.frontier.revision != expected_frontier_revision {
            return Err(AuthorityLeaseError::RevisionConflict);
        }
        if lease.authority_epoch != state.frontier.authority_epoch {
            return Err(AuthorityLeaseError::EpochMismatch);
        }
        if state.leases.contains_key(&lease.lease_id) {
            return Err(AuthorityLeaseError::LeaseAlreadyExists);
        }
        if state.leases.len() >= MAX_LEASES {
            return Err(AuthorityLeaseError::CapacityExceeded);
        }
        let next_revision = state
            .frontier
            .revision
            .checked_add(1)
            .ok_or(AuthorityLeaseError::CapacityExceeded)?;
        if lease.revision != next_revision {
            return Err(AuthorityLeaseError::RevisionConflict);
        }
        let mut next = state.clone();
        next.frontier.revision = next_revision;
        next.leases.insert(lease.lease_id.clone(), lease);
        self.persist_or_fence(&mut state, next)
    }

    pub fn read_lease(&self, lease_id: &str) -> Result<Option<AuthorityLeaseRead>, AuthorityLeaseError> {
        if !identifier(lease_id) {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        let state = self.lock_state()?;
        Ok(state.leases.get(lease_id).cloned().map(|lease| AuthorityLeaseRead {
            revocation: state.revocations.get(lease_id).cloned(),
            lease,
            frontier: state.frontier,
        }))
    }

    /// Owner CAS revocation. A revocation is immutable and monotonically
    /// advances the authoritative frontier.
    pub fn revoke(
        &self,
        lease_id: &str,
        expected_lease_revision: u64,
        expected_frontier_revision: u64,
        reason_sha256: [u8; 32],
        revoked_at_unix_ms: u64,
    ) -> Result<CapabilityRevocation, AuthorityLeaseError> {
        if !identifier(lease_id) || reason_sha256 == [0; 32] || revoked_at_unix_ms == 0 {
            return Err(AuthorityLeaseError::InvalidRevocation);
        }
        let mut state = self.lock_state()?;
        if state.frontier.revision != expected_frontier_revision {
            return Err(AuthorityLeaseError::RevisionConflict);
        }
        let lease = state
            .leases
            .get(lease_id)
            .ok_or(AuthorityLeaseError::LeaseNotFound)?;
        if lease.revision != expected_lease_revision {
            return Err(AuthorityLeaseError::RevisionConflict);
        }
        if state.revocations.contains_key(lease_id) {
            return Err(AuthorityLeaseError::AlreadyRevoked);
        }
        let revision = state
            .frontier
            .revision
            .checked_add(1)
            .ok_or(AuthorityLeaseError::CapacityExceeded)?;
        let revocation = CapabilityRevocation {
            schema_version: SCHEMA_VERSION,
            lease_id: lease_id.to_owned(),
            authority_epoch: state.frontier.authority_epoch,
            revision,
            reason_sha256,
            revoked_at_unix_ms,
        };
        revocation.validate()?;
        let mut next = state.clone();
        next.frontier.revision = revision;
        next.revocations
            .insert(lease_id.to_owned(), revocation.clone());
        self.persist_or_fence(&mut state, next)?;
        Ok(revocation)
    }

    /// Verify one exact lease using host-supplied trusted time. The returned
    /// token only proves admission; final consumers must call `with_verified_use`.
    #[allow(clippy::too_many_arguments)]
    pub fn verify_use(
        &self,
        lease_id: &str,
        principal_id: &str,
        operation_class: &str,
        scope_sha256: [u8; 32],
        payload_sha256: [u8; 32],
        destination_id: &str,
        authority_epoch: u64,
        now_unix_ms: u64,
    ) -> Result<LeaseVerifiedUse, AuthorityLeaseError> {
        let state = self.lock_state()?;
        let lease = state
            .leases
            .get(lease_id)
            .ok_or(AuthorityLeaseError::LeaseNotFound)?;
        validate_live_lease(
            lease,
            state.revocations.get(lease_id),
            state.frontier,
            principal_id,
            operation_class,
            scope_sha256,
            payload_sha256,
            destination_id,
            authority_epoch,
            now_unix_ms,
        )?;
        Ok(LeaseVerifiedUse {
            owner: Arc::clone(&self.0),
            lease: lease.clone(),
        })
    }

    /// Re-check the authoritative state immediately before the effect boundary.
    /// `now_unix_ms` is sampled by the trusted host after any asynchronous work.
    pub fn with_verified_use<T>(
        &self,
        token: LeaseVerifiedUse,
        now_unix_ms: u64,
        consumer: impl FnOnce(&AuthorityLease) -> T,
    ) -> Result<T, AuthorityLeaseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) {
            return Err(AuthorityLeaseError::OwnerMismatch);
        }
        let state = self.lock_state()?;
        let lease = state
            .leases
            .get(&token.lease.lease_id)
            .ok_or(AuthorityLeaseError::LeaseNotFound)?;
        if lease != &token.lease {
            return Err(AuthorityLeaseError::RevisionConflict);
        }
        validate_live_lease(
            lease,
            state.revocations.get(&lease.lease_id),
            state.frontier,
            &lease.principal_id,
            &lease.operation_class,
            lease.scope_sha256,
            lease.payload_sha256,
            &lease.destination_id,
            lease.authority_epoch,
            now_unix_ms,
        )?;
        Ok(consumer(lease))
    }

    /// Advance to an externally authenticated epoch/frontier after recovery or
    /// coordinated rollover. Epoch decreases and revision rollback are denied.
    pub fn advance_trusted_frontier(
        &self,
        trusted_frontier: AuthorityFrontier,
    ) -> Result<AuthorityFrontier, AuthorityLeaseError> {
        if !trusted_frontier.valid() {
            return Err(AuthorityLeaseError::InvalidFrontier);
        }
        let mut state = self.lock_state()?;
        if trusted_frontier.authority_epoch < state.frontier.authority_epoch
            || (trusted_frontier.authority_epoch == state.frontier.authority_epoch
                && trusted_frontier.revision <= state.frontier.revision)
        {
            return Err(AuthorityLeaseError::StaleFrontier);
        }
        let mut next = state.clone();
        if trusted_frontier.authority_epoch > state.frontier.authority_epoch {
            next.leases.clear();
            next.revocations.clear();
        }
        next.frontier = trusted_frontier;
        self.persist_or_fence(&mut state, next)
    }

    fn lock_state(&self) -> Result<std::sync::MutexGuard<'_, State>, AuthorityLeaseError> {
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        if state.failed {
            return Err(AuthorityLeaseError::Unavailable);
        }
        Ok(state)
    }

    fn persist_or_fence(
        &self,
        state: &mut std::sync::MutexGuard<'_, State>,
        next: State,
    ) -> Result<AuthorityFrontier, AuthorityLeaseError> {
        if self.0.store.persist(&next).is_err() {
            state.failed = true;
            return Err(AuthorityLeaseError::Unavailable);
        }
        let frontier = next.frontier;
        **state = next;
        Ok(frontier)
    }
}

#[allow(clippy::too_many_arguments)]
fn validate_live_lease(
    lease: &AuthorityLease,
    revocation: Option<&CapabilityRevocation>,
    frontier: AuthorityFrontier,
    principal_id: &str,
    operation_class: &str,
    scope_sha256: [u8; 32],
    payload_sha256: [u8; 32],
    destination_id: &str,
    authority_epoch: u64,
    now_unix_ms: u64,
) -> Result<(), AuthorityLeaseError> {
    lease.validate()?;
    if authority_epoch != frontier.authority_epoch || lease.authority_epoch != frontier.authority_epoch {
        return Err(AuthorityLeaseError::EpochMismatch);
    }
    if revocation.is_some() {
        return Err(AuthorityLeaseError::Revoked);
    }
    if lease.principal_id != principal_id
        || lease.operation_class != operation_class
        || lease.scope_sha256 != scope_sha256
        || lease.payload_sha256 != payload_sha256
        || lease.destination_id != destination_id
    {
        return Err(AuthorityLeaseError::BindingMismatch);
    }
    if now_unix_ms < lease.issued_at_unix_ms {
        return Err(AuthorityLeaseError::NotYetValid);
    }
    if now_unix_ms >= lease.expires_at_unix_ms {
        return Err(AuthorityLeaseError::Expired);
    }
    Ok(())
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityLeaseError {
    InvalidFrontier,
    StaleFrontier,
    InvalidLease,
    InvalidRevocation,
    LeaseAlreadyExists,
    LeaseNotFound,
    AlreadyRevoked,
    RevisionConflict,
    EpochMismatch,
    BindingMismatch,
    Revoked,
    NotYetValid,
    Expired,
    OwnerMismatch,
    CapacityExceeded,
    UnsafeStateDirectory,
    StateLocked,
    Unavailable,
}

impl fmt::Display for AuthorityLeaseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for AuthorityLeaseError {}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Stored {
    schema: u32,
    state: State,
}

struct Store {
    root: File,
    _lock: File,
}

impl Store {
    fn open(root: &Path, trusted_frontier: AuthorityFrontier) -> Result<(Self, State), AuthorityLeaseError> {
        let root = prepare_directory(root)?;
        let initialized = entry_exists(&root, "authority-leases.lock")?;
        let lock = open_private(&root, "authority-leases.lock", Access::Create)?;
        lock.try_lock().map_err(|_| AuthorityLeaseError::StateLocked)?;
        let store = Self { root, _lock: lock };
        let has_state = entry_exists(&store.root, "authority-leases.json")?;
        let state = if has_state {
            let mut bytes = Vec::new();
            open_private(&store.root, "authority-leases.json", Access::Read)?
                .take(MAX_STATE_BYTES + 1)
                .read_to_end(&mut bytes)
                .map_err(|_| AuthorityLeaseError::Unavailable)?;
            if bytes.len() as u64 > MAX_STATE_BYTES {
                return Err(AuthorityLeaseError::InvalidFrontier);
            }
            let stored: Stored = serde_json::from_slice(&bytes)
                .map_err(|_| AuthorityLeaseError::InvalidFrontier)?;
            if stored.schema != SCHEMA_VERSION
                || !stored.state.frontier.valid()
                || stored.state.leases.len() > MAX_LEASES
                || stored.state.revocations.len() > MAX_LEASES
            {
                return Err(AuthorityLeaseError::InvalidFrontier);
            }
            for lease in stored.state.leases.values() {
                lease.validate()?;
            }
            for revocation in stored.state.revocations.values() {
                revocation.validate()?;
            }
            let mut state = stored.state;
            if trusted_frontier.authority_epoch < state.frontier.authority_epoch
                || (trusted_frontier.authority_epoch == state.frontier.authority_epoch
                    && trusted_frontier.revision < state.frontier.revision)
            {
                return Err(AuthorityLeaseError::StaleFrontier);
            }
            if trusted_frontier.authority_epoch > state.frontier.authority_epoch {
                state.leases.clear();
                state.revocations.clear();
                state.frontier = trusted_frontier;
                store.persist(&state)?;
            } else if trusted_frontier.revision > state.frontier.revision {
                state.frontier = trusted_frontier;
                store.persist(&state)?;
            }
            state.failed = false;
            state
        } else {
            if initialized {
                return Err(AuthorityLeaseError::InvalidFrontier);
            }
            let state = State {
                frontier: trusted_frontier,
                leases: BTreeMap::new(),
                revocations: BTreeMap::new(),
                failed: false,
            };
            store.persist(&state)?;
            state
        };
        Ok((store, state))
    }

    fn persist(&self, state: &State) -> Result<(), AuthorityLeaseError> {
        let bytes = serde_json::to_vec(&Stored {
            schema: SCHEMA_VERSION,
            state: state.clone(),
        })
        .map_err(|_| AuthorityLeaseError::Unavailable)?;
        if bytes.len() as u64 > MAX_STATE_BYTES {
            return Err(AuthorityLeaseError::CapacityExceeded);
        }
        let mut file = open_private(&self.root, "authority-leases.next", Access::Create)?;
        file.set_len(0).map_err(|_| AuthorityLeaseError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        replace_state(&self.root)?;
        self.root.sync_all().map_err(|_| AuthorityLeaseError::Unavailable)
    }
}

enum Access {
    Read,
    Create,
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, AuthorityLeaseError> {
    use std::os::unix::fs::{DirBuilderExt, MetadataExt};
    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(AuthorityLeaseError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| AuthorityLeaseError::UnsafeStateDirectory)?
    .into();
    let metadata = directory.metadata().map_err(|_| AuthorityLeaseError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(AuthorityLeaseError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(unix)]
fn open_private(directory: &File, name: &str, access: Access) -> Result<File, AuthorityLeaseError> {
    use std::os::unix::fs::MetadataExt;
    let flags = match access {
        Access::Read => rustix::fs::OFlags::RDONLY,
        Access::Create => rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE,
    } | rustix::fs::OFlags::NOFOLLOW
        | rustix::fs::OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(
        directory,
        name,
        flags,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .map_err(|_| AuthorityLeaseError::Unavailable)?
    .into();
    let metadata = file.metadata().map_err(|_| AuthorityLeaseError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(AuthorityLeaseError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, AuthorityLeaseError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(AuthorityLeaseError::Unavailable),
    }
}

#[cfg(unix)]
fn replace_state(directory: &File) -> Result<(), AuthorityLeaseError> {
    rustix::fs::renameat(
        directory,
        "authority-leases.next",
        directory,
        "authority-leases.json",
    )
    .map_err(|_| AuthorityLeaseError::Unavailable)
}

#[cfg(not(unix))]
fn prepare_directory(_root: &Path) -> Result<File, AuthorityLeaseError> {
    Err(AuthorityLeaseError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn open_private(_directory: &File, _name: &str, _access: Access) -> Result<File, AuthorityLeaseError> {
    Err(AuthorityLeaseError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, AuthorityLeaseError> {
    Err(AuthorityLeaseError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn replace_state(_directory: &File) -> Result<(), AuthorityLeaseError> {
    Err(AuthorityLeaseError::UnsafeStateDirectory)
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn registry() -> (AuthorityLeaseRegistry, tempfile::TempDir) {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let registry = AuthorityLeaseRegistry::open_state_dir(
            directory.path(),
            AuthorityFrontier {
                authority_epoch: 7,
                revision: 1,
            },
        )
        .unwrap();
        (registry, directory)
    }

    fn lease(revision: u64) -> AuthorityLease {
        AuthorityLease {
            schema_version: 1,
            lease_id: "lease-one".into(),
            principal_id: "agent-one".into(),
            operation_class: "provider.read".into(),
            destination_id: "provider:heptabao".into(),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
            issued_at_unix_ms: 1_000,
            expires_at_unix_ms: 10_000,
            authority_epoch: 7,
            revision,
            signer_id: "security-owner".into(),
        }
    }

    #[test]
    fn lease_issue_verify_revoke_is_cas_and_fail_closed() {
        let (registry, _directory) = registry();
        assert_eq!(
            registry.issue_lease(lease(2), 1),
            Ok(AuthorityFrontier {
                authority_epoch: 7,
                revision: 2
            })
        );
        let token = registry
            .verify_use(
                "lease-one",
                "agent-one",
                "provider.read",
                [1; 32],
                [2; 32],
                "provider:heptabao",
                7,
                2_000,
            )
            .unwrap();
        let revocation = registry
            .revoke("lease-one", 2, 2, [9; 32], 2_500)
            .unwrap();
        assert_eq!(revocation.revision, 3);
        assert_eq!(
            registry.with_verified_use(token, 3_000, |_| ()),
            Err(AuthorityLeaseError::Revoked)
        );
        assert_eq!(
            registry.revoke("lease-one", 2, 2, [8; 32], 3_000),
            Err(AuthorityLeaseError::RevisionConflict)
        );
    }

    #[test]
    fn persisted_frontier_prevents_stale_restore_configuration() {
        let (registry, directory) = registry();
        registry.issue_lease(lease(2), 1).unwrap();
        registry.revoke("lease-one", 2, 2, [9; 32], 2_500).unwrap();
        drop(registry);
        assert_eq!(
            AuthorityLeaseRegistry::open_state_dir(
                directory.path(),
                AuthorityFrontier {
                    authority_epoch: 7,
                    revision: 2,
                },
            )
            .unwrap_err(),
            AuthorityLeaseError::StaleFrontier
        );
        let reopened = AuthorityLeaseRegistry::open_state_dir(
            directory.path(),
            AuthorityFrontier {
                authority_epoch: 7,
                revision: 3,
            },
        )
        .unwrap();
        assert!(reopened.read_lease("lease-one").unwrap().unwrap().revocation.is_some());
    }

    #[test]
    fn epoch_rollover_fences_and_clears_previous_epoch_records() {
        let (registry, _directory) = registry();
        registry.issue_lease(lease(2), 1).unwrap();
        registry
            .advance_trusted_frontier(AuthorityFrontier {
                authority_epoch: 8,
                revision: 1,
            })
            .unwrap();
        assert!(registry.read_lease("lease-one").unwrap().is_none());
    }
}

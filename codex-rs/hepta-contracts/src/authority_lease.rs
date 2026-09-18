//! Durable capability leases and revocations owned by `kernel.authority`.
//!
//! This module is intentionally separate from the narrower final-use grant
//! verifier.  It implements the authoritative `authority_lease` and
//! `capability_revocation` domains described by the module contract: owner-CAS
//! lease mutation, durable revocation, anti-rollback frontier checks and an
//! opaque verified-use token that is consumed at one final boundary.

use crate::AuthorityClock;
use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use crate::SystemAuthorityClock;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeMap;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;

const LEASE_SCHEMA_VERSION: u32 = 1;
const STORE_SCHEMA_VERSION: u32 = 1;
pub const MAX_AUTHORITY_LEASES: usize = 16_384;
pub const MAX_CAPABILITY_REVOCATIONS: usize = 16_384;
pub const MAX_AUTHORITY_LEASE_LIFETIME_MS: u64 = 86_400_000;
pub const MAX_AUTHORITY_PRUNE_BATCH: usize = 1_024;
pub const MAX_AUTHORITY_STORE_BYTES: usize = 64 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityLeaseBinding {
    pub principal_id: String,
    pub operation_class: String,
    pub destination_id: String,
    pub scope_sha256: [u8; 32],
    pub payload_sha256: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityLease {
    pub schema_version: u32,
    pub lease_id: String,
    pub authority_epoch: u64,
    pub revision: u64,
    pub binding: AuthorityLeaseBinding,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityRevocation {
    pub schema_version: u32,
    pub lease_id: String,
    pub authority_epoch: u64,
    pub lease_revision: u64,
    pub store_revision: u64,
    pub reason_sha256: [u8; 32],
    pub revoked_at_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityLeaseFrontier {
    pub authority_epoch: u64,
    pub store_revision: u64,
    pub state_sha256: [u8; 32],
}

impl AuthorityLeaseFrontier {
    pub fn for_empty_epoch(authority_epoch: u64) -> Result<Self, AuthorityLeaseError> {
        if authority_epoch == 0 {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        Ok(frontier_for_state(&State {
            authority_epoch,
            store_revision: 1,
            leases: BTreeMap::new(),
            revocations: BTreeMap::new(),
            failed: false,
        }))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AuthorityCapacity {
    pub leases: usize,
    pub revocations: usize,
    pub max_leases: usize,
    pub max_revocations: usize,
}

impl AuthorityCapacity {
    pub fn remaining_leases(self) -> usize {
        self.max_leases.saturating_sub(self.leases)
    }

    pub fn remaining_revocations(self) -> usize {
        self.max_revocations.saturating_sub(self.revocations)
    }

    pub fn rollover_required_with_reserve(self, reserve: usize) -> bool {
        self.remaining_leases() <= reserve || self.remaining_revocations() <= reserve
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityLeaseReadV1 {
    pub lease: AuthorityLease,
    pub store_revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityRevocationReadV1 {
    pub revocation: CapabilityRevocation,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RevocationReceipt {
    pub lease_id: String,
    pub authority_epoch: u64,
    pub previous_lease_revision: u64,
    pub lease_revision: u64,
    pub store_revision: u64,
    pub reason_sha256: [u8; 32],
    pub revoked_at_unix_ms: u64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct State {
    authority_epoch: u64,
    store_revision: u64,
    leases: BTreeMap<String, AuthorityLease>,
    revocations: BTreeMap<String, CapabilityRevocation>,
    #[serde(skip)]
    failed: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Stored {
    schema_version: u32,
    owner_id: String,
    state: State,
}

struct Store {
    root: File,
    owner_id: String,
    _lock: File,
}

struct Inner {
    owner_id: String,
    state: Mutex<State>,
    store: Store,
    clock: Arc<dyn AuthorityClock>,
    frontier_store: Option<Arc<dyn AuthorityFrontierStore<AuthorityLeaseFrontier>>>,
}

/// Non-cloneable administrative authority. Mutation authority is intentionally
/// not transferable through a cheap handle clone.
pub struct AuthorityLeaseRegistry(Arc<Inner>);

/// Cloneable least-authority read/verification handle. It cannot create,
/// replace, revoke, prune or advance leases.
#[derive(Clone)]
pub struct AuthorityLeaseVerifier(Arc<Inner>);

impl fmt::Debug for AuthorityLeaseRegistry {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("AuthorityLeaseRegistry([PINNED OWNER STATE])")
    }
}

impl fmt::Debug for AuthorityLeaseVerifier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("AuthorityLeaseVerifier([READ/VERIFY ONLY])")
    }
}

/// Opaque, non-cloneable and non-serializable proof of one current lease.
/// It is owner-bound and must be consumed at the final adapter boundary.
pub struct LeaseVerifiedUseToken {
    owner: Arc<Inner>,
    lease: AuthorityLease,
}

impl fmt::Debug for LeaseVerifiedUseToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("LeaseVerifiedUseToken([REDACTED])")
    }
}

impl AuthorityLease {
    pub fn validate(&self) -> Result<(), AuthorityLeaseError> {
        if self.schema_version != LEASE_SCHEMA_VERSION
            || !identifier(&self.lease_id)
            || self.authority_epoch == 0
            || self.revision == 0
            || !binding_valid(&self.binding)
            || self.issued_at_unix_ms == 0
            || self.expires_at_unix_ms <= self.issued_at_unix_ms
            || self.expires_at_unix_ms - self.issued_at_unix_ms
                > MAX_AUTHORITY_LEASE_LIFETIME_MS
        {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        Ok(())
    }
}

impl AuthorityLeaseRegistry {
    /// Open the owner store. `trusted_frontier` is a protected host input from
    /// outside this filesystem.  A persisted state behind it is rejected as a
    /// rollback.  A missing store cannot be recreated above the genesis
    /// frontier, so deleting/restoring the local directory does not silently
    /// reset authority when the host preserves its frontier.
    pub fn open_state_dir(
        directory: &Path,
        owner_id: String,
        trusted_frontier: AuthorityLeaseFrontier,
    ) -> Result<Self, AuthorityLeaseError> {
        if !identifier(&owner_id)
            || trusted_frontier.authority_epoch == 0
            || trusted_frontier.store_revision == 0
            || trusted_frontier.state_sha256 == [0; 32]
        {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        let (store, state) = Store::open(directory, &owner_id, trusted_frontier)?;
        Ok(Self(Arc::new(Inner {
            owner_id,
            state: Mutex::new(state),
            store,
            clock: Arc::new(SystemAuthorityClock),
            frontier_store: None,
        })))
    }

    /// Production constructor. The externally durable frontier is loaded and
    /// must exactly match local state. Every subsequent mutation advances that
    /// frontier with CAS before committing the local state, so restoring an old
    /// local snapshot is detected on reopen.
    pub fn open_state_dir_with_frontier_store(
        directory: &Path,
        owner_id: String,
        frontier_store: Arc<dyn AuthorityFrontierStore<AuthorityLeaseFrontier>>,
    ) -> Result<Self, AuthorityLeaseError> {
        Self::open_state_dir_with_trust(
            directory,
            owner_id,
            Arc::new(SystemAuthorityClock),
            frontier_store,
        )
    }

    pub fn open_state_dir_with_clock(
        directory: &Path,
        owner_id: String,
        trusted_frontier: AuthorityLeaseFrontier,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityLeaseError> {
        if !identifier(&owner_id)
            || trusted_frontier.authority_epoch == 0
            || trusted_frontier.store_revision == 0
            || trusted_frontier.state_sha256 == [0; 32]
        {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (store, state) = Store::open(directory, &owner_id, trusted_frontier)?;
        Ok(Self(Arc::new(Inner {
            owner_id,
            state: Mutex::new(state),
            store,
            clock,
            frontier_store: None,
        })))
    }

    pub fn open_state_dir_with_trust(
        directory: &Path,
        owner_id: String,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<AuthorityLeaseFrontier>>,
    ) -> Result<Self, AuthorityLeaseError> {
        if !identifier(&owner_id) {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let trusted_frontier = frontier_store
            .load(&owner_id)
            .map_err(map_trust_error)?;
        if trusted_frontier.authority_epoch == 0
            || trusted_frontier.store_revision == 0
            || trusted_frontier.state_sha256 == [0; 32]
        {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        let (store, state) = Store::open(directory, &owner_id, trusted_frontier)?;
        let observed = frontier_for_state(&state);
        if observed != trusted_frontier {
            return Err(AuthorityLeaseError::AntiRollbackViolation);
        }
        Ok(Self(Arc::new(Inner {
            owner_id,
            state: Mutex::new(state),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }

    pub fn verifier(&self) -> AuthorityLeaseVerifier {
        AuthorityLeaseVerifier(Arc::clone(&self.0))
    }

    pub fn owner_id(&self) -> &str {
        &self.0.owner_id
    }

    pub fn frontier(&self) -> Result<AuthorityLeaseFrontier, AuthorityLeaseError> {
        let state = self.lock_state()?;
        Ok(frontier_for_state(&state))
    }

    pub fn capacity(&self) -> Result<AuthorityCapacity, AuthorityLeaseError> {
        let state = self.lock_state()?;
        Ok(AuthorityCapacity {
            leases: state.leases.len(),
            revocations: state.revocations.len(),
            max_leases: MAX_AUTHORITY_LEASES,
            max_revocations: MAX_CAPABILITY_REVOCATIONS,
        })
    }

    /// Create or replace one lease using owner CAS. New leases use
    /// `expected_revision == 0` and `lease.revision == 1`. Replacements must
    /// advance the existing lease revision by exactly one. Revoked lease IDs
    /// cannot be resurrected inside the same authority epoch.
    pub fn put_lease(
        &self,
        lease: AuthorityLease,
        expected_revision: u64,
    ) -> Result<AuthorityLeaseReadV1, AuthorityLeaseError> {
        lease.validate()?;
        let mut state = self.lock_state()?;
        if lease.authority_epoch != state.authority_epoch {
            return Err(AuthorityLeaseError::EpochMismatch);
        }
        if state.revocations.contains_key(&lease.lease_id) {
            return Err(AuthorityLeaseError::Revoked);
        }
        match state.leases.get(&lease.lease_id) {
            None => {
                if expected_revision != 0 || lease.revision != 1 {
                    return Err(AuthorityLeaseError::RevisionMismatch);
                }
                if state.leases.len() >= MAX_AUTHORITY_LEASES {
                    return Err(AuthorityLeaseError::CapacityExceeded);
                }
            }
            Some(current) => {
                if current == &lease {
                    return Ok(AuthorityLeaseReadV1 {
                        lease,
                        store_revision: state.store_revision,
                    });
                }
                if current.revision != expected_revision
                    || lease.revision != expected_revision.saturating_add(1)
                {
                    return Err(AuthorityLeaseError::RevisionMismatch);
                }
            }
        }
        let mut next = state.clone();
        next.store_revision = next_revision(next.store_revision)?;
        next.leases.insert(lease.lease_id.clone(), lease.clone());
        self.persist_or_fence(&mut state, next)?;
        Ok(AuthorityLeaseReadV1 {
            lease,
            store_revision: state.store_revision,
        })
    }

    pub fn read_lease(
        &self,
        lease_id: &str,
    ) -> Result<Option<AuthorityLeaseReadV1>, AuthorityLeaseError> {
        if !identifier(lease_id) {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        let state = self.lock_state()?;
        Ok(state.leases.get(lease_id).cloned().map(|lease| AuthorityLeaseReadV1 {
            lease,
            store_revision: state.store_revision,
        }))
    }

    pub fn read_revocation(
        &self,
        lease_id: &str,
    ) -> Result<Option<CapabilityRevocationReadV1>, AuthorityLeaseError> {
        if !identifier(lease_id) {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        let state = self.lock_state()?;
        Ok(state
            .revocations
            .get(lease_id)
            .cloned()
            .map(|revocation| CapabilityRevocationReadV1 { revocation }))
    }

    /// Owner-only durable revoke. The lease revision is CAS-checked and then
    /// advanced. Revocation is immutable for the remainder of the epoch.
    pub fn revoke(
        &self,
        lease_id: &str,
        expected_revision: u64,
        reason_sha256: [u8; 32],
    ) -> Result<RevocationReceipt, AuthorityLeaseError> {
        if !identifier(lease_id) || reason_sha256 == [0; 32] {
            return Err(AuthorityLeaseError::InvalidRevocation);
        }
        let revoked_at_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        if revoked_at_unix_ms == 0 {
            return Err(AuthorityLeaseError::InvalidRevocation);
        }
        let mut state = self.lock_state()?;
        if let Some(existing) = state.revocations.get(lease_id) {
            if existing.lease_revision == expected_revision.saturating_add(1)
                && existing.reason_sha256 == reason_sha256
            {
                return Ok(receipt(existing, expected_revision));
            }
            return Err(AuthorityLeaseError::Revoked);
        }
        if state.revocations.len() >= MAX_CAPABILITY_REVOCATIONS {
            return Err(AuthorityLeaseError::CapacityExceeded);
        }
        let current = state
            .leases
            .get(lease_id)
            .cloned()
            .ok_or(AuthorityLeaseError::LeaseNotFound)?;
        if current.revision != expected_revision {
            return Err(AuthorityLeaseError::RevisionMismatch);
        }
        let lease_revision = next_revision(current.revision)?;
        let mut next = state.clone();
        next.store_revision = next_revision(next.store_revision)?;
        let mut revoked_lease = current;
        revoked_lease.revision = lease_revision;
        next.leases.insert(lease_id.to_owned(), revoked_lease);
        let revocation = CapabilityRevocation {
            schema_version: LEASE_SCHEMA_VERSION,
            lease_id: lease_id.to_owned(),
            authority_epoch: next.authority_epoch,
            lease_revision,
            store_revision: next.store_revision,
            reason_sha256,
            revoked_at_unix_ms,
        };
        next.revocations
            .insert(lease_id.to_owned(), revocation.clone());
        self.persist_or_fence(&mut state, next)?;
        Ok(receipt(&revocation, expected_revision))
    }

    /// Remove expired, unrevoked leases in a bounded online batch. Revocation
    /// tombstones are never garbage-collected inside an epoch. A stale token is
    /// still rejected because final verification requires the exact current
    /// lease record to remain present.
    pub fn prune_expired_leases(
        &self,
        max_to_prune: usize,
    ) -> Result<usize, AuthorityLeaseError> {
        if max_to_prune == 0 || max_to_prune > MAX_AUTHORITY_PRUNE_BATCH {
            return Err(AuthorityLeaseError::InvalidPrune);
        }
        let now_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let mut state = self.lock_state()?;
        let expired: Vec<String> = state
            .leases
            .iter()
            .filter(|(id, lease)| {
                lease.expires_at_unix_ms <= now_unix_ms && !state.revocations.contains_key(*id)
            })
            .take(max_to_prune)
            .map(|(id, _)| id.clone())
            .collect();
        if expired.is_empty() {
            return Ok(0);
        }
        let mut next = state.clone();
        for lease_id in &expired {
            next.leases.remove(lease_id);
        }
        next.store_revision = next_revision(next.store_revision)?;
        self.persist_or_fence(&mut state, next)?;
        Ok(expired.len())
    }

    /// Advance to a fresh authority epoch. This is the bounded rollover path
    /// when lease/revocation capacity is approaching exhaustion. Old leases and
    /// revocations are fenced by the new epoch and removed only as part of the
    /// same durable transition.
    pub fn advance_epoch(
        &self,
        expected_store_revision: u64,
        new_authority_epoch: u64,
    ) -> Result<AuthorityLeaseFrontier, AuthorityLeaseError> {
        let mut state = self.lock_state()?;
        if state.store_revision != expected_store_revision
            || new_authority_epoch <= state.authority_epoch
        {
            return Err(AuthorityLeaseError::RevisionMismatch);
        }
        let mut next = state.clone();
        next.authority_epoch = new_authority_epoch;
        next.store_revision = next_revision(next.store_revision)?;
        next.leases.clear();
        next.revocations.clear();
        self.persist_or_fence(&mut state, next)?;
        Ok(frontier_for_state(&state))
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
    ) -> Result<(), AuthorityLeaseError> {
        if let Some(frontier_store) = &self.0.frontier_store {
            let expected = frontier_for_state(state);
            let advanced = frontier_for_state(&next);
            if let Err(error) =
                frontier_store.compare_and_set(&self.0.owner_id, &expected, &advanced)
            {
                state.failed = true;
                return Err(map_trust_error(error));
            }
        }
        if self.0.store.persist(&next).is_err() {
            state.failed = true;
            return Err(AuthorityLeaseError::Unavailable);
        }
        **state = next;
        Ok(())
    }
}

impl AuthorityLeaseVerifier {
    pub fn owner_id(&self) -> &str {
        &self.0.owner_id
    }

    pub fn frontier(&self) -> Result<AuthorityLeaseFrontier, AuthorityLeaseError> {
        let state = self.lock_state()?;
        Ok(frontier_for_state(&state))
    }

    pub fn capacity(&self) -> Result<AuthorityCapacity, AuthorityLeaseError> {
        let state = self.lock_state()?;
        Ok(AuthorityCapacity {
            leases: state.leases.len(),
            revocations: state.revocations.len(),
            max_leases: MAX_AUTHORITY_LEASES,
            max_revocations: MAX_CAPABILITY_REVOCATIONS,
        })
    }

    pub fn read_lease(
        &self,
        lease_id: &str,
    ) -> Result<Option<AuthorityLeaseReadV1>, AuthorityLeaseError> {
        if !identifier(lease_id) {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        let state = self.lock_state()?;
        Ok(state.leases.get(lease_id).cloned().map(|lease| AuthorityLeaseReadV1 {
            lease,
            store_revision: state.store_revision,
        }))
    }

    pub fn read_revocation(
        &self,
        lease_id: &str,
    ) -> Result<Option<CapabilityRevocationReadV1>, AuthorityLeaseError> {
        if !identifier(lease_id) {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        let state = self.lock_state()?;
        Ok(state
            .revocations
            .get(lease_id)
            .cloned()
            .map(|revocation| CapabilityRevocationReadV1 { revocation }))
    }

    pub fn verify_use(
        &self,
        lease_id: &str,
        expected_revision: u64,
        expected: &AuthorityLeaseBinding,
    ) -> Result<LeaseVerifiedUseToken, AuthorityLeaseError> {
        let now_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let state = self.lock_state()?;
        let lease = state
            .leases
            .get(lease_id)
            .ok_or(AuthorityLeaseError::LeaseNotFound)?;
        validate_live(lease, &state, expected_revision, expected, now_unix_ms)?;
        Ok(LeaseVerifiedUseToken {
            owner: Arc::clone(&self.0),
            lease: lease.clone(),
        })
    }

    /// Final verification is the consumer-entry linearization point. The lock
    /// is released before already-selected bounded consumer code executes.
    pub fn with_verified_use<T>(
        &self,
        token: LeaseVerifiedUseToken,
        expected: &AuthorityLeaseBinding,
        consumer: impl FnOnce() -> T,
    ) -> Result<T, AuthorityLeaseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) || &token.lease.binding != expected {
            return Err(AuthorityLeaseError::BindingMismatch);
        }
        let now_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let state = self.lock_state()?;
        validate_live(
            &token.lease,
            &state,
            token.lease.revision,
            expected,
            now_unix_ms,
        )?;
        drop(state);
        Ok(consumer())
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
}

fn receipt(revocation: &CapabilityRevocation, previous: u64) -> RevocationReceipt {
    RevocationReceipt {
        lease_id: revocation.lease_id.clone(),
        authority_epoch: revocation.authority_epoch,
        previous_lease_revision: previous,
        lease_revision: revocation.lease_revision,
        store_revision: revocation.store_revision,
        reason_sha256: revocation.reason_sha256,
        revoked_at_unix_ms: revocation.revoked_at_unix_ms,
    }
}

fn map_trust_error(error: AuthorityTrustError) -> AuthorityLeaseError {
    match error {
        AuthorityTrustError::Invalid => AuthorityLeaseError::InvalidTrust,
        AuthorityTrustError::Conflict => AuthorityLeaseError::AntiRollbackViolation,
        AuthorityTrustError::Unavailable => AuthorityLeaseError::Unavailable,
    }
}

fn validate_live(
    lease: &AuthorityLease,
    state: &State,
    expected_revision: u64,
    expected: &AuthorityLeaseBinding,
    now_unix_ms: u64,
) -> Result<(), AuthorityLeaseError> {
    if lease.authority_epoch != state.authority_epoch {
        return Err(AuthorityLeaseError::EpochMismatch);
    }
    if lease.revision != expected_revision {
        return Err(AuthorityLeaseError::RevisionMismatch);
    }
    if &lease.binding != expected {
        return Err(AuthorityLeaseError::BindingMismatch);
    }
    if state.revocations.contains_key(&lease.lease_id) {
        return Err(AuthorityLeaseError::Revoked);
    }
    let current = state
        .leases
        .get(&lease.lease_id)
        .ok_or(AuthorityLeaseError::LeaseNotFound)?;
    if current != lease || current.revision != expected_revision {
        return Err(AuthorityLeaseError::RevisionMismatch);
    }
    if now_unix_ms < lease.issued_at_unix_ms {
        return Err(AuthorityLeaseError::NotYetValid);
    }
    if now_unix_ms >= lease.expires_at_unix_ms {
        return Err(AuthorityLeaseError::Expired);
    }
    Ok(())
}

fn binding_valid(binding: &AuthorityLeaseBinding) -> bool {
    identifier(&binding.principal_id)
        && identifier(&binding.operation_class)
        && identifier(&binding.destination_id)
        && binding.scope_sha256 != [0; 32]
        && binding.payload_sha256 != [0; 32]
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
}

fn next_revision(value: u64) -> Result<u64, AuthorityLeaseError> {
    value
        .checked_add(1)
        .ok_or(AuthorityLeaseError::RevisionOverflow)
}

impl Store {
    fn open(
        root: &Path,
        owner_id: &str,
        trusted_frontier: AuthorityLeaseFrontier,
    ) -> Result<(Self, State), AuthorityLeaseError> {
        let root = prepare_directory(root)?;
        let initialized = entry_exists(&root, "authority-leases.lock")?;
        let lock = open_private(&root, "authority-leases.lock", Access::Create)?;
        lock.try_lock()
            .map_err(|_| AuthorityLeaseError::StateLocked)?;
        let store = Self {
            root,
            owner_id: owner_id.to_owned(),
            _lock: lock,
        };
        let has_state = entry_exists(&store.root, "authority-leases.json")?;
        let state = if has_state {
            let mut bytes = Vec::new();
            open_private(&store.root, "authority-leases.json", Access::Read)?
                .take((MAX_AUTHORITY_STORE_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
                .map_err(|_| AuthorityLeaseError::Unavailable)?;
            if bytes.len() > MAX_AUTHORITY_STORE_BYTES {
                return Err(AuthorityLeaseError::InvalidTrust);
            }
            let stored: Stored = serde_json::from_slice(&bytes)
                .map_err(|_| AuthorityLeaseError::InvalidTrust)?;
            if stored.schema_version != STORE_SCHEMA_VERSION
                || stored.owner_id != owner_id
                || !state_valid(&stored.state)
            {
                return Err(AuthorityLeaseError::InvalidTrust);
            }
            let persisted = frontier_for_state(&stored.state);
            if frontier_conflicts(persisted, trusted_frontier) {
                return Err(AuthorityLeaseError::AntiRollbackViolation);
            }
            stored.state
        } else {
            if initialized || trusted_frontier.store_revision != 1 {
                return Err(AuthorityLeaseError::AntiRollbackViolation);
            }
            let state = State {
                authority_epoch: trusted_frontier.authority_epoch,
                store_revision: trusted_frontier.store_revision,
                leases: BTreeMap::new(),
                revocations: BTreeMap::new(),
                failed: false,
            };
            if frontier_for_state(&state) != trusted_frontier {
                return Err(AuthorityLeaseError::AntiRollbackViolation);
            }
            store.persist(&state)?;
            state
        };
        Ok((store, state))
    }

    fn persist(&self, state: &State) -> Result<(), AuthorityLeaseError> {
        let stored = Stored {
            schema_version: STORE_SCHEMA_VERSION,
            owner_id: self.owner_id.clone(),
            state: state.clone(),
        };
        let bytes = serde_json::to_vec(&stored).map_err(|_| AuthorityLeaseError::Unavailable)?;
        let mut file = open_private(&self.root, "authority-leases.next", Access::Create)?;
        file.set_len(0)
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        replace_state(&self.root)?;
        self.root
            .sync_all()
            .map_err(|_| AuthorityLeaseError::Unavailable)
    }
}

fn frontier_conflicts(
    persisted: AuthorityLeaseFrontier,
    trusted: AuthorityLeaseFrontier,
) -> bool {
    persisted.authority_epoch < trusted.authority_epoch
        || (persisted.authority_epoch == trusted.authority_epoch
            && persisted.store_revision < trusted.store_revision)
        || (persisted.authority_epoch == trusted.authority_epoch
            && persisted.store_revision == trusted.store_revision
            && persisted.state_sha256 != trusted.state_sha256)
}

fn frontier_for_state(state: &State) -> AuthorityLeaseFrontier {
    let mut hash = Sha256::new();
    hash.update(b"hepta.kernel.authority.lease-frontier.v1\0");
    hash.update(state.authority_epoch.to_le_bytes());
    hash.update(state.store_revision.to_le_bytes());
    hash.update((state.leases.len() as u64).to_le_bytes());
    for (lease_id, lease) in &state.leases {
        hash_text(&mut hash, lease_id);
        hash.update(lease.schema_version.to_le_bytes());
        hash_text(&mut hash, &lease.lease_id);
        hash.update(lease.authority_epoch.to_le_bytes());
        hash.update(lease.revision.to_le_bytes());
        hash_text(&mut hash, &lease.binding.principal_id);
        hash_text(&mut hash, &lease.binding.operation_class);
        hash_text(&mut hash, &lease.binding.destination_id);
        hash.update(lease.binding.scope_sha256);
        hash.update(lease.binding.payload_sha256);
        hash.update(lease.issued_at_unix_ms.to_le_bytes());
        hash.update(lease.expires_at_unix_ms.to_le_bytes());
    }
    hash.update((state.revocations.len() as u64).to_le_bytes());
    for (lease_id, revocation) in &state.revocations {
        hash_text(&mut hash, lease_id);
        hash.update(revocation.schema_version.to_le_bytes());
        hash_text(&mut hash, &revocation.lease_id);
        hash.update(revocation.authority_epoch.to_le_bytes());
        hash.update(revocation.lease_revision.to_le_bytes());
        hash.update(revocation.store_revision.to_le_bytes());
        hash.update(revocation.reason_sha256);
        hash.update(revocation.revoked_at_unix_ms.to_le_bytes());
    }
    AuthorityLeaseFrontier {
        authority_epoch: state.authority_epoch,
        store_revision: state.store_revision,
        state_sha256: hash.finalize().into(),
    }
}

fn hash_text(hash: &mut Sha256, value: &str) {
    hash.update((value.len() as u64).to_le_bytes());
    hash.update(value.as_bytes());
}

fn state_valid(state: &State) -> bool {
    state.authority_epoch > 0
        && state.store_revision > 0
        && state.leases.len() <= MAX_AUTHORITY_LEASES
        && state.revocations.len() <= MAX_CAPABILITY_REVOCATIONS
        && state.leases.iter().all(|(id, lease)| {
            id == &lease.lease_id
                && lease.validate().is_ok()
                && lease.authority_epoch == state.authority_epoch
        })
        && state.revocations.iter().all(|(id, revoke)| {
            id == &revoke.lease_id
                && revoke.schema_version == LEASE_SCHEMA_VERSION
                && revoke.authority_epoch == state.authority_epoch
                && revoke.lease_revision > 1
                && revoke.store_revision <= state.store_revision
                && revoke.reason_sha256 != [0; 32]
                && revoke.revoked_at_unix_ms > 0
        })
}

enum Access {
    Read,
    Create,
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, AuthorityLeaseError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;
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
    let metadata = directory
        .metadata()
        .map_err(|_| AuthorityLeaseError::Unavailable)?;
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
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::os::unix::fs::MetadataExt;
    let flags = match access {
        Access::Read => OFlags::RDONLY,
        Access::Create => OFlags::RDWR | OFlags::CREATE,
    } | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(directory, name, flags, Mode::RUSR | Mode::WUSR)
        .map_err(|_| AuthorityLeaseError::Unavailable)?
        .into();
    let metadata = file
        .metadata()
        .map_err(|_| AuthorityLeaseError::Unavailable)?;
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
fn open_private(
    _directory: &File,
    _name: &str,
    _access: Access,
) -> Result<File, AuthorityLeaseError> {
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityLeaseError {
    InvalidLease,
    InvalidRevocation,
    InvalidPrune,
    InvalidTrust,
    BindingMismatch,
    EpochMismatch,
    RevisionMismatch,
    LeaseNotFound,
    Revoked,
    NotYetValid,
    Expired,
    CapacityExceeded,
    RevisionOverflow,
    AntiRollbackViolation,
    Unavailable,
    UnsafeStateDirectory,
    StateLocked,
}

impl fmt::Display for AuthorityLeaseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for AuthorityLeaseError {}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use std::sync::Mutex;
    use std::sync::mpsc;
    use std::time::Duration;

    #[derive(Debug)]
    struct FixedClock(u64);

    impl AuthorityClock for FixedClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(self.0)
        }
    }

    #[derive(Debug)]
    struct MemoryFrontierStore(Mutex<AuthorityLeaseFrontier>);

    impl AuthorityFrontierStore<AuthorityLeaseFrontier> for MemoryFrontierStore {
        fn load(&self, _owner_id: &str) -> Result<AuthorityLeaseFrontier, AuthorityTrustError> {
            self.0
                .lock()
                .map(|frontier| *frontier)
                .map_err(|_| AuthorityTrustError::Unavailable)
        }

        fn compare_and_set(
            &self,
            _owner_id: &str,
            expected: &AuthorityLeaseFrontier,
            next: &AuthorityLeaseFrontier,
        ) -> Result<(), AuthorityTrustError> {
            let mut current = self
                .0
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            if *current != *expected {
                return Err(AuthorityTrustError::Conflict);
            }
            *current = *next;
            Ok(())
        }
    }

    fn fixture() -> (AuthorityLeaseRegistry, tempfile::TempDir) {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .unwrap();
        let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
            directory.path(),
            "security-authority".into(),
            AuthorityLeaseFrontier::for_empty_epoch(7).unwrap(),
            Arc::new(FixedClock(2_000)),
        )
        .unwrap();
        (registry, directory)
    }

    fn binding() -> AuthorityLeaseBinding {
        AuthorityLeaseBinding {
            principal_id: "agent-one".into(),
            operation_class: "provider.read".into(),
            destination_id: "provider:heptabao".into(),
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        }
    }

    fn lease() -> AuthorityLease {
        AuthorityLease {
            schema_version: LEASE_SCHEMA_VERSION,
            lease_id: "lease-one".into(),
            authority_epoch: 7,
            revision: 1,
            binding: binding(),
            issued_at_unix_ms: 1_000,
            expires_at_unix_ms: 30_000,
        }
    }

    #[test]
    fn lease_is_durable_verified_and_cas_revoked() {
        let (registry, directory) = fixture();
        registry.put_lease(lease(), 0).unwrap();
        let verifier = registry.verifier();
        let token = verifier
            .verify_use("lease-one", 1, &binding())
            .unwrap();
        assert_eq!(
            verifier.with_verified_use(token, &binding(), || 7),
            Ok(7)
        );
        let receipt = registry
            .revoke("lease-one", 1, [9; 32])
            .unwrap();
        assert_eq!(receipt.lease_revision, 2);
        assert_eq!(
            verifier.verify_use("lease-one", 2, &binding()).unwrap_err(),
            AuthorityLeaseError::Revoked
        );
        let frontier = registry.frontier().unwrap();
        drop(registry);
        let reopened = AuthorityLeaseRegistry::open_state_dir(
            directory.path(),
            "security-authority".into(),
            frontier,
        )
        .unwrap();
        assert!(reopened.read_revocation("lease-one").unwrap().is_some());
    }

    #[test]
    fn verified_use_releases_owner_lock_before_consumer_code() {
        let (registry, _directory) = fixture();
        registry.put_lease(lease(), 0).unwrap();
        let verifier = registry.verifier();
        let token = verifier
            .verify_use("lease-one", 1, &binding())
            .unwrap();
        let (tx, rx) = mpsc::channel();
        let expected = binding();
        std::thread::spawn(move || {
            let result = verifier.with_verified_use(token, &expected, || {
                registry.revoke("lease-one", 1, [8; 32]).unwrap();
                7
            });
            let _ = tx.send(result);
        });
        assert_eq!(
            rx.recv_timeout(Duration::from_secs(2))
                .expect("lease consumer remained blocked on the owner mutex"),
            Ok(7)
        );
    }

    #[test]
    fn stale_cas_and_binding_drift_fail_closed() {
        let (registry, _directory) = fixture();
        registry.put_lease(lease(), 0).unwrap();
        let mut replacement = lease();
        replacement.revision = 2;
        assert_eq!(
            registry.put_lease(replacement.clone(), 99).unwrap_err(),
            AuthorityLeaseError::RevisionMismatch
        );
        let mut wrong = binding();
        wrong.payload_sha256 = [4; 32];
        assert_eq!(
            registry
                .verifier()
                .verify_use("lease-one", 1, &wrong)
                .unwrap_err(),
            AuthorityLeaseError::BindingMismatch
        );
    }

    #[test]
    fn token_is_invalidated_by_lease_replacement() {
        let (registry, _directory) = fixture();
        registry.put_lease(lease(), 0).unwrap();
        let verifier = registry.verifier();
        let token = verifier
            .verify_use("lease-one", 1, &binding())
            .unwrap();
        let mut replacement = lease();
        replacement.revision = 2;
        replacement.expires_at_unix_ms = 40_000;
        registry.put_lease(replacement, 1).unwrap();
        assert_eq!(
            verifier
                .with_verified_use(token, &binding(), || ())
                .unwrap_err(),
            AuthorityLeaseError::RevisionMismatch
        );
    }

    #[test]
    fn revoke_retry_reuses_server_owned_timestamp() {
        let (registry, _directory) = fixture();
        registry.put_lease(lease(), 0).unwrap();
        let first = registry.revoke("lease-one", 1, [9; 32]).unwrap();
        let retry = registry.revoke("lease-one", 1, [9; 32]).unwrap();
        assert_eq!(first, retry);
        assert_eq!(first.revoked_at_unix_ms, 2_000);
        assert_eq!(
            registry
                .revoke("lease-one", 1, [10; 32])
                .unwrap_err(),
            AuthorityLeaseError::Revoked
        );
    }

    #[test]
    fn bounded_prune_reclaims_only_expired_unrevoked_leases() {
        let (registry, _directory) = fixture();
        let mut expired = lease();
        expired.expires_at_unix_ms = 1_500;
        registry.put_lease(expired, 0).unwrap();
        assert_eq!(registry.prune_expired_leases(1), Ok(1));
        assert!(registry
            .verifier()
            .read_lease("lease-one")
            .unwrap()
            .is_none());
        assert_eq!(registry.capacity().unwrap().leases, 0);
    }

    #[test]
    fn maximum_declared_state_shape_fits_restart_read_envelope() {
        let max_id = |prefix: &str, index: usize| {
            let base = format!("{prefix}{index:05}");
            format!("{base}{}", "x".repeat(128 - base.len()))
        };
        let mut state = State {
            authority_epoch: 7,
            store_revision: (MAX_AUTHORITY_LEASES + MAX_CAPABILITY_REVOCATIONS + 1) as u64,
            leases: BTreeMap::new(),
            revocations: BTreeMap::new(),
            failed: false,
        };
        for index in 0..MAX_AUTHORITY_LEASES {
            let lease_id = max_id("l", index);
            state.leases.insert(
                lease_id.clone(),
                AuthorityLease {
                    schema_version: LEASE_SCHEMA_VERSION,
                    lease_id,
                    authority_epoch: 7,
                    revision: 1,
                    binding: AuthorityLeaseBinding {
                        principal_id: max_id("p", index),
                        operation_class: max_id("o", index),
                        destination_id: max_id("d", index),
                        scope_sha256: [255; 32],
                        payload_sha256: [255; 32],
                    },
                    issued_at_unix_ms: 1,
                    expires_at_unix_ms: MAX_AUTHORITY_LEASE_LIFETIME_MS + 1,
                },
            );
        }
        for index in 0..MAX_CAPABILITY_REVOCATIONS {
            let lease_id = max_id("r", index);
            state.revocations.insert(
                lease_id.clone(),
                CapabilityRevocation {
                    schema_version: LEASE_SCHEMA_VERSION,
                    lease_id,
                    authority_epoch: 7,
                    lease_revision: 2,
                    store_revision: state.store_revision,
                    reason_sha256: [255; 32],
                    revoked_at_unix_ms: 1,
                },
            );
        }
        let stored = Stored {
            schema_version: STORE_SCHEMA_VERSION,
            owner_id: "security-authority".into(),
            state,
        };
        let bytes = serde_json::to_vec(&stored).unwrap();
        assert!(
            bytes.len() <= MAX_AUTHORITY_STORE_BYTES,
            "declared maximum state serialized to {} bytes, above {} byte restart ceiling",
            bytes.len(),
            MAX_AUTHORITY_STORE_BYTES
        );
    }

    #[test]
    fn production_frontier_cas_detects_restored_local_snapshot() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .unwrap();
        let frontier_store = Arc::new(MemoryFrontierStore(Mutex::new(
            AuthorityLeaseFrontier::for_empty_epoch(7).unwrap(),
        )));
        let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
            directory.path(),
            "security-authority".into(),
            Arc::new(FixedClock(2_000)),
            frontier_store.clone(),
        )
        .unwrap();
        let initial = std::fs::read(directory.path().join("authority-leases.json")).unwrap();
        registry.put_lease(lease(), 0).unwrap();
        assert_eq!(
            frontier_store.load("security-authority").unwrap(),
            registry.frontier().unwrap()
        );
        drop(registry);
        std::fs::write(directory.path().join("authority-leases.json"), initial).unwrap();
        assert_eq!(
            AuthorityLeaseRegistry::open_state_dir_with_trust(
                directory.path(),
                "security-authority".into(),
                Arc::new(FixedClock(2_000)),
                frontier_store,
            )
            .unwrap_err(),
            AuthorityLeaseError::AntiRollbackViolation
        );
    }

    #[test]
    fn external_frontier_ahead_after_local_commit_failure_fences_reopen() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .unwrap();
        let frontier_store = Arc::new(MemoryFrontierStore(Mutex::new(
            AuthorityLeaseFrontier::for_empty_epoch(7).unwrap(),
        )));
        let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
            directory.path(),
            "security-authority".into(),
            Arc::new(FixedClock(2_000)),
            frontier_store.clone(),
        )
        .unwrap();

        std::fs::create_dir(directory.path().join("authority-leases.next")).unwrap();
        assert_eq!(
            registry.put_lease(lease(), 0).unwrap_err(),
            AuthorityLeaseError::Unavailable
        );
        assert_eq!(
            registry.capacity().unwrap_err(),
            AuthorityLeaseError::Unavailable
        );
        let external = frontier_store.load("security-authority").unwrap();
        assert_eq!(external.store_revision, 2);

        std::fs::remove_dir(directory.path().join("authority-leases.next")).unwrap();
        drop(registry);
        assert_eq!(
            AuthorityLeaseRegistry::open_state_dir_with_trust(
                directory.path(),
                "security-authority".into(),
                Arc::new(FixedClock(2_000)),
                frontier_store,
            )
            .unwrap_err(),
            AuthorityLeaseError::AntiRollbackViolation
        );
    }

    #[test]
    fn external_frontier_detects_old_snapshot_and_missing_store_reset() {
        let (registry, directory) = fixture();
        registry.put_lease(lease(), 0).unwrap();
        let frontier = registry.frontier().unwrap();
        drop(registry);
        let bytes = std::fs::read(directory.path().join("authority-leases.json")).unwrap();
        let old = AuthorityLeaseFrontier {
            authority_epoch: frontier.authority_epoch,
            store_revision: frontier.store_revision + 1,
        };
        assert_eq!(
            AuthorityLeaseRegistry::open_state_dir(
                directory.path(),
                "security-authority".into(),
                old,
            )
            .unwrap_err(),
            AuthorityLeaseError::AntiRollbackViolation
        );
        std::fs::write(directory.path().join("authority-leases.json"), bytes).unwrap();
        std::fs::remove_file(directory.path().join("authority-leases.json")).unwrap();
        assert_eq!(
            AuthorityLeaseRegistry::open_state_dir(
                directory.path(),
                "security-authority".into(),
                frontier,
            )
            .unwrap_err(),
            AuthorityLeaseError::AntiRollbackViolation
        );
    }

    #[test]
    fn epoch_rollover_is_durable_and_clears_bounded_history() {
        let (registry, _directory) = fixture();
        registry.put_lease(lease(), 0).unwrap();
        let before = registry.frontier().unwrap();
        let after = registry
            .advance_epoch(before.store_revision, 8)
            .unwrap();
        assert_eq!(after.authority_epoch, 8);
        assert!(registry.read_lease("lease-one").unwrap().is_none());
        assert_eq!(registry.capacity().unwrap().leases, 0);
    }
}

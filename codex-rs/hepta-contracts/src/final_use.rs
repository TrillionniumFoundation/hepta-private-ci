//! Kernel-owned final-use admission. Trust and revocation heads come from the
//! host, never from request metadata. This verifier contains no signing key.

use std::collections::BTreeSet;
use std::fmt;
use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use crate::AuthorityClock;
use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use crate::SystemAuthorityClock;
use crate::VerifiedUseBoundaryV1;
use crate::VerifiedUseTokenWitnessV1;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

#[path = "final_use_store.rs"]
mod store;

const MAX_CLAIMS: usize = 1_048_576;
const MAX_REVOKED_GRANTS: usize = 16_384;
const MAX_LIFETIME_MS: u64 = 300_000;
const MAX_ISSUER_TRUST_KEYS: usize = 8;

/// Source-visible markers consumed by the closed-world B4 caller proof.
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_CLAIM: &str = "claim_final_use";
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DELIVERY: &str = "deliver_final_use";
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DELIVERY_WITNESS: &str =
    "deliver_final_use_with_witness";
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DISPATCH: &str = "dispatch_final_use";
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DISPATCH_WITNESS: &str =
    "dispatch_final_use_with_witness";

/// Exact operation identity signed by the authority owner. Digests must bind
/// destination instance, resource, operation, payload and consumer identity.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseBinding {
    pub subject_id: String,
    pub destination_id: String,
    pub request_sha256: [u8; 32],
    pub scope_sha256: [u8; 32],
    pub payload_sha256: [u8; 32],
}

/// Unsigned proposal. Possessing or editing this value grants no authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseGrant {
    pub schema_version: u32,
    pub signer_id: String,
    pub authority_epoch: u64,
    pub grant_id: String,
    pub nonce: [u8; 32],
    pub binding: FinalUseBinding,
    pub not_before_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl FinalUseGrant {
    /// Canonical signing input for an independently operated issuer.
    pub fn signing_bytes(&self) -> Result<Vec<u8>, FinalUseError> {
        if self.schema_version != 1
            || self.authority_epoch == 0
            || !identifier(&self.signer_id)
            || !identifier(&self.grant_id)
            || !identifier(&self.binding.subject_id)
            || !identifier(&self.binding.destination_id)
            || self.nonce == [0; 32]
            || self.binding.request_sha256 == [0; 32]
            || self.binding.scope_sha256 == [0; 32]
            || self.binding.payload_sha256 == [0; 32]
            || self.expires_at_unix_ms <= self.not_before_unix_ms
            || self.expires_at_unix_ms - self.not_before_unix_ms > MAX_LIFETIME_MS
        {
            return Err(FinalUseError::InvalidGrant);
        }
        let mut bytes = b"hepta.kernel.authority.final-use.v1\0".to_vec();
        bytes.extend(serde_json::to_vec(self).map_err(|_| FinalUseError::InvalidGrant)?);
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedFinalUseGrant {
    pub grant: FinalUseGrant,
    pub signature: Vec<u8>,
}

/// One issuer key generation accepted only in its inclusive authority-epoch
/// window. Key ids are configuration/audit identities and are not request authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalUseIssuerTrustKey {
    pub key_id: String,
    pub verifying_key: [u8; 32],
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
}

#[derive(Clone)]
struct PinnedIssuerKey {
    key_id: String,
    key: VerifyingKey,
    not_before_authority_epoch: u64,
    not_after_authority_epoch: u64,
}

fn pin_issuer_keys(
    mut keys: Vec<FinalUseIssuerTrustKey>,
) -> Result<(Vec<PinnedIssuerKey>, [u8; 32]), FinalUseError> {
    if keys.is_empty() || keys.len() > MAX_ISSUER_TRUST_KEYS {
        return Err(FinalUseError::InvalidTrust);
    }
    keys.sort_by(|left, right| left.key_id.cmp(&right.key_id));
    let mut ids = BTreeSet::new();
    let mut public_keys = BTreeSet::new();
    let mut digest = Sha256::new();
    digest.update(b"hepta.kernel.authority.final-use-issuer-trust.v1\0");
    let mut pinned = Vec::with_capacity(keys.len());
    for candidate in keys {
        let key = VerifyingKey::from_bytes(&candidate.verifying_key)
            .map_err(|_| FinalUseError::InvalidTrust)?;
        if !identifier(&candidate.key_id)
            || key.is_weak()
            || candidate.not_before_authority_epoch == 0
            || candidate.not_after_authority_epoch < candidate.not_before_authority_epoch
            || !ids.insert(candidate.key_id.clone())
            || !public_keys.insert(candidate.verifying_key)
        {
            return Err(FinalUseError::InvalidTrust);
        }
        digest.update((candidate.key_id.len() as u64).to_le_bytes());
        digest.update(candidate.key_id.as_bytes());
        digest.update(candidate.verifying_key);
        digest.update(candidate.not_before_authority_epoch.to_le_bytes());
        digest.update(candidate.not_after_authority_epoch.to_le_bytes());
        pinned.push(PinnedIssuerKey {
            key_id: candidate.key_id,
            key,
            not_before_authority_epoch: candidate.not_before_authority_epoch,
            not_after_authority_epoch: candidate.not_after_authority_epoch,
        });
    }
    Ok((pinned, digest.finalize().into()))
}

/// Trusted host update. Increasing revision is mandatory; epoch changes fence
/// every earlier grant. The authority persists the head and claimed nonces.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseRevocations {
    pub authority_epoch: u64,
    pub revision: u64,
    pub revoked_grant_ids: BTreeSet<String>,
}

/// Externally durable anti-rollback frontier for one exact local authority
/// state. The digest covers committed/pending heads and all claimed nonces.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseFrontier {
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub state_sha256: [u8; 32],
}

impl FinalUseFrontier {
    pub fn for_initial_head(head: &FinalUseRevocations) -> Result<Self, FinalUseError> {
        if !valid_head(head) {
            return Err(FinalUseError::InvalidTrust);
        }
        Ok(frontier_for_state(&State {
            head: head.clone(),
            used_nonces: BTreeSet::new(),
            pending_revocations: None,
            failed: false,
        }))
    }
}

/// Read-only capacity/frontier snapshot; observability is not rollover authority.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FinalUseCapacity {
    pub authority_epoch: u64,
    pub revision: u64,
    pub used_nonces: usize,
    pub revoked_grants: usize,
    pub max_claims: usize,
    pub max_revocations: usize,
}

impl FinalUseCapacity {
    pub fn remaining_claims(self) -> usize {
        self.max_claims.saturating_sub(self.used_nonces)
    }

    pub fn remaining_revocations(self) -> usize {
        self.max_revocations.saturating_sub(self.revoked_grants)
    }

    /// Hosts choose a safety margin according to their deployment/fanout SLA.
    pub fn rollover_required_with_reserve(self, reserve: usize) -> bool {
        self.remaining_claims() <= reserve || self.remaining_revocations() <= reserve
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct State {
    head: FinalUseRevocations,
    used_nonces: BTreeSet<[u8; 32]>,
    #[serde(default)]
    pending_revocations: Option<FinalUseRevocations>,
    #[serde(skip)]
    failed: bool,
}

struct Inner {
    signer_id: String,
    issuer_keys: Vec<PinnedIssuerKey>,
    state: Mutex<State>,
    active_dispatches: AtomicUsize,
    store: store::Store,
    clock: Arc<dyn AuthorityClock>,
    frontier_store: Option<Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>>,
}

/// Clones share the same revocation/nonce owner; there is no permissive default.
#[derive(Clone)]
pub struct FinalUseAuthority(Arc<Inner>);

impl fmt::Debug for FinalUseAuthority {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("FinalUseAuthority([PINNED TRUST])")
    }
}

/// Unforgeable, non-cloneable and non-serializable signature-verified claim.
pub struct VerifiedUseToken {
    owner: Arc<Inner>,
    grant: FinalUseGrant,
    claimed_head: FinalUseRevocations,
    claimed_head_sha256: [u8; 32],
    witness_sha256: [u8; 32],
}

impl fmt::Debug for VerifiedUseToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("VerifiedUseToken([REDACTED])")
    }
}

/// Non-constructible evidence of asynchronous effect entry. Later revocation
/// cannot prove an entered external effect stopped or authorize its replay.
pub struct EnteredUseToken {
    _owner: Arc<Inner>,
    binding: FinalUseBinding,
    witness_sha256: [u8; 32],
}

impl fmt::Debug for EnteredUseToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("EnteredUseToken([REDACTED])")
    }
}

impl EnteredUseToken {
    pub fn matches(&self, expected: &FinalUseBinding) -> bool {
        &self.binding == expected
    }

    pub const fn witness_sha256(&self) -> [u8; 32] {
        self.witness_sha256
    }
}

impl VerifiedUseToken {
    pub const fn witness_sha256(&self) -> [u8; 32] {
        self.witness_sha256
    }

    pub const fn claimed_authority_epoch(&self) -> u64 {
        self.claimed_head.authority_epoch
    }

    pub const fn claimed_revocation_revision(&self) -> u64 {
        self.claimed_head.revision
    }

    pub const fn claimed_revocation_head_sha256(&self) -> [u8; 32] {
        self.claimed_head_sha256
    }

    /// Consume the token at the final asynchronous entry under the owner lock.
    pub fn enter(self, expected: &FinalUseBinding) -> Result<EnteredUseToken, FinalUseError> {
        if &self.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let state = self.owner.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if state.pending_revocations.is_some() {
            return Err(FinalUseError::RevocationPending);
        }
        validate_live_clock(&self.grant, &state.head, self.owner.clock.as_ref())?;
        if state.head != self.claimed_head {
            return Err(FinalUseError::StaleRevocationHead);
        }
        let entered = EnteredUseToken {
            _owner: Arc::clone(&self.owner),
            binding: self.grant.binding,
            witness_sha256: self.witness_sha256,
        };
        drop(state);
        Ok(entered)
    }
}

impl FinalUseAuthority {
    /// Compatibility only: system time and no external rollback oracle.
    pub fn open_state_dir(
        directory: &std::path::Path,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
    ) -> Result<Self, FinalUseError> {
        Self::open_state_dir_with_clock(directory, signer_id, verifying_key, head, Arc::new(SystemAuthorityClock))
    }

    /// Clock-injected qualification/compatibility construction, without a frontier.
    pub fn open_state_dir_with_clock(
        directory: &std::path::Path,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, FinalUseError> {
        let key = VerifyingKey::from_bytes(&verifying_key).map_err(|_| FinalUseError::InvalidTrust)?;
        if !identifier(&signer_id) || key.is_weak() || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (store, state) = store::Store::open(directory, &signer_id, verifying_key, head)?;
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys: vec![PinnedIssuerKey {
                key_id: "single-key".into(),
                key,
                not_before_authority_epoch: 1,
                not_after_authority_epoch: u64::MAX,
            }],
            state: Mutex::new(state),
            active_dispatches: AtomicUsize::new(0),
            store,
            clock,
            frontier_store: None,
        })))
    }

    /// Single-key external-trust constructor. The frontier must match exactly.
    pub fn open_state_dir_with_trust(
        directory: &std::path::Path,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        let key = VerifyingKey::from_bytes(&verifying_key).map_err(|_| FinalUseError::InvalidTrust)?;
        if !identifier(&signer_id) || key.is_weak() || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (store, state) = store::Store::open_exact(directory, &signer_id, verifying_key, head)?;
        let observed = frontier_for_state(&state);
        let trusted = frontier_store.load(&signer_id).map_err(map_trust_error)?;
        if trusted != observed {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys: vec![PinnedIssuerKey {
                key_id: "single-key".into(),
                key,
                not_before_authority_epoch: 1,
                not_after_authority_epoch: u64::MAX,
            }],
            state: Mutex::new(state),
            active_dispatches: AtomicUsize::new(0),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }

    /// Bounded issuer key ring, protected time, and an exact external frontier.
    /// V4 pins the trust family; concrete production components need qualification.
    pub fn open_state_dir_with_issuer_keys(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        Self::open_key_ring_with_trust(directory, signer_id, issuer_keys, head, clock, frontier_store, false)
    }

    /// An authenticated head may finish a frontier-first transition but cannot
    /// advance, invent, or reset the independently stored external frontier.
    pub fn recover_state_dir_with_issuer_keys(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        Self::open_key_ring_with_trust(directory, signer_id, issuer_keys, head, clock, frontier_store, true)
    }

    fn open_key_ring_with_trust(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
        recover_persisted_head: bool,
    ) -> Result<Self, FinalUseError> {
        if !identifier(&signer_id) || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (issuer_keys, issuer_trust_sha256) = pin_issuer_keys(issuer_keys)?;
        let (store, mut state) = if recover_persisted_head {
            store::Store::open_key_ring_recovered(directory, &signer_id, issuer_trust_sha256, head.clone())?
        } else {
            store::Store::open_key_ring_exact(directory, &signer_id, issuer_trust_sha256, head.clone())?
        };
        let trusted = frontier_store.load(&signer_id).map_err(map_trust_error)?;
        if trusted != frontier_for_state(&state) {
            if !recover_persisted_head {
                return Err(FinalUseError::AntiRollbackViolation);
            }
            recover_local_state_from_trusted_frontier(&store, &mut state, &head, trusted)?;
        }
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys,
            state: Mutex::new(state),
            active_dispatches: AtomicUsize::new(0),
            store,
            clock,
            frontier_store: Some(frontier_store),
        })))
    }

    pub fn issuer_key_ids(&self) -> Vec<&str> {
        self.0.issuer_keys.iter().map(|candidate| candidate.key_id.as_str()).collect()
    }

    pub fn frontier(&self) -> Result<FinalUseFrontier, FinalUseError> {
        let state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        Ok(frontier_for_state(&state))
    }

    /// Coherent observability only; it does not create rollover authority.
    pub fn capacity(&self) -> Result<FinalUseCapacity, FinalUseError> {
        let state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        Ok(FinalUseCapacity {
            authority_epoch: state.head.authority_epoch,
            revision: state.head.revision,
            used_nonces: state.used_nonces.len(),
            revoked_grants: state.head.revoked_grant_ids.len(),
            max_claims: MAX_CLAIMS,
            max_revocations: MAX_REVOKED_GRANTS,
        })
    }

    /// The durable head is not a fresh feed or independent rollback oracle.
    pub fn revocation_head(&self) -> Result<FinalUseRevocations, FinalUseError> {
        let state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        Ok(state.head.clone())
    }

    /// Trusted-host only. Pending and committed heads never weaken in an epoch.
    pub fn update_revocations(&self, head: FinalUseRevocations) -> Result<(), FinalUseError> {
        let mut state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if !head_advances(&state.head, &head) {
            return Err(FinalUseError::StaleRevocationHead);
        }
        if let Some(previous) = state.pending_revocations.as_ref()
            && previous != &head
            && !head_advances(previous, &head)
        {
            return Err(FinalUseError::StaleRevocationHead);
        }
        if state.pending_revocations.as_ref() != Some(&head) {
            let mut pending = state.clone();
            pending.pending_revocations = Some(head.clone());
            self.persist_or_fence(&mut state, pending)?;
        }
        if self.0.active_dispatches.load(Ordering::Acquire) != 0 {
            return Err(FinalUseError::DispatchInProgress);
        }
        let mut committed = state.clone();
        if head.authority_epoch > committed.head.authority_epoch {
            committed.used_nonces.clear();
        }
        committed.head = head;
        committed.pending_revocations = None;
        self.persist_or_fence(&mut state, committed)
    }

    /// Durably consume one nonce. Failed/uncertain effects never refund it.
    pub fn claim(
        &self,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
    ) -> Result<VerifiedUseToken, FinalUseError> {
        let input = signed.grant.signing_bytes()?;
        if signed.grant.signer_id != self.0.signer_id || &signed.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let signature = Signature::from_slice(&signed.signature).map_err(|_| FinalUseError::InvalidSignature)?;
        let verified = self.0.issuer_keys.iter().any(|candidate| {
            signed.grant.authority_epoch >= candidate.not_before_authority_epoch
                && signed.grant.authority_epoch <= candidate.not_after_authority_epoch
                && candidate.key.verify_strict(&input, &signature).is_ok()
        });
        if !verified {
            return Err(FinalUseError::InvalidSignature);
        }
        let mut state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if state.pending_revocations.is_some() {
            return Err(FinalUseError::RevocationPending);
        }
        validate_live_clock(&signed.grant, &state.head, self.0.clock.as_ref())?;
        if state.used_nonces.contains(&signed.grant.nonce) {
            return Err(FinalUseError::AlreadyClaimed);
        }
        if state.used_nonces.len() >= MAX_CLAIMS {
            return Err(FinalUseError::CapacityExceeded);
        }
        // Preserve external-frontier-first ordering and fence every uncertain write.
        let expected_frontier = self.0.frontier_store.as_ref().map(|_| frontier_for_state(&state));
        state.used_nonces.insert(signed.grant.nonce);
        if let (Some(frontier_store), Some(expected_frontier)) = (&self.0.frontier_store, expected_frontier)
            && let Err(error) = frontier_store.compare_and_set(&self.0.signer_id, &expected_frontier, &frontier_for_state(&state))
        {
            state.failed = true;
            return Err(map_trust_error(error));
        }
        if self.0.store.append_claim(state.head.authority_epoch, signed.grant.nonce).is_err() {
            state.failed = true;
            return Err(FinalUseError::Unavailable);
        }
        // Persistence may outlast validity. Sample the complete interval again;
        // expiry or trust loss leaves this nonce durably consumed.
        validate_live_clock(&signed.grant, &state.head, self.0.clock.as_ref())?;
        let claimed_head = state.head.clone();
        let claimed_head_bytes = serde_json::to_vec(&claimed_head).map_err(|_| FinalUseError::InvalidTrust)?;
        let mut head_witness = b"hepta.kernel.authority.revocation-head.v1\0".to_vec();
        head_witness.extend_from_slice(&claimed_head_bytes);
        let claimed_head_sha256 = Sha256::digest(&head_witness).into();
        let mut witness = b"hepta.kernel.authority.final-use-witness.v2\0".to_vec();
        witness.extend_from_slice(&input);
        witness.extend_from_slice(&signed.signature);
        witness.extend_from_slice(&claimed_head_bytes);
        let witness_sha256 = Sha256::digest(&witness).into();
        Ok(VerifiedUseToken {
            owner: Arc::clone(&self.0),
            grant: signed.grant.clone(),
            claimed_head,
            claimed_head_sha256,
            witness_sha256,
        })
    }

    /// Entry is not remote completion; later revocation cannot authorize replay.
    pub fn enter_verified_use(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
    ) -> Result<EnteredUseToken, FinalUseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) {
            return Err(FinalUseError::BindingMismatch);
        }
        token.enter(expected)
    }

    /// Consumer-entry linearization releases the owner mutex before user code.
    pub fn with_verified_use<T>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        consumer: impl FnOnce() -> T,
    ) -> Result<T, FinalUseError> {
        let _witness = self.validate_token_live_witness(&token, expected, VerifiedUseBoundaryV1::ConsumerEntry)?;
        Ok(consumer())
    }

    /// Active-effect fencing without holding the mutex across provider work.
    pub fn with_verified_effect<T>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        consumer: impl FnOnce() -> T,
    ) -> Result<T, FinalUseError> {
        let (guard, _witness) = self.enter_verified_effect(token, expected)?;
        let result = consumer();
        drop(guard);
        Ok(result)
    }

    /// An async effect retains its active fence until completion/unwind/drop.
    pub async fn with_verified_use_async<T, F>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        consumer: impl FnOnce() -> F,
    ) -> Result<T, FinalUseError>
    where
        F: Future<Output = T>,
    {
        let (guard, _witness) = self.enter_verified_effect(token, expected)?;
        let result = consumer().await;
        drop(guard);
        Ok(result)
    }

    /// Expose non-authorizing entry evidence before the owner contacts a provider.
    pub async fn with_verified_use_async_with_witness<T, F>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        consumer: impl FnOnce(VerifiedUseTokenWitnessV1) -> F,
    ) -> Result<(T, VerifiedUseTokenWitnessV1), FinalUseError>
    where
        F: Future<Output = T>,
    {
        let (guard, witness) = self.enter_verified_effect(token, expected)?;
        let result = consumer(witness.clone()).await;
        drop(guard);
        Ok((result, witness))
    }

    fn enter_verified_effect(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
    ) -> Result<(ActiveDispatchGuard, VerifiedUseTokenWitnessV1), FinalUseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) || &token.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if state.pending_revocations.is_some() {
            return Err(FinalUseError::RevocationPending);
        }
        let now_unix_ms = validate_live_clock(&token.grant, &state.head, self.0.clock.as_ref())?;
        let witness = VerifiedUseTokenWitnessV1::final_use(
            self.0.signer_id.clone(), token.grant.grant_id, state.head.authority_epoch,
            state.head.revision, now_unix_ms, VerifiedUseBoundaryV1::DispatchEntry,
            final_use_binding_witness_sha256(expected)?,
        );
        self.0.active_dispatches.fetch_add(1, Ordering::AcqRel);
        drop(state);
        Ok((ActiveDispatchGuard { owner: Arc::clone(&self.0) }, witness))
    }

    /// Hold the mutex only across a bounded local irreversible transition.
    /// Network waits, terminal waits, loops and arbitrary user code are forbidden.
    pub fn with_dispatch_boundary<T>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        dispatch_boundary: impl FnOnce() -> T,
    ) -> Result<T, FinalUseError> {
        let (result, _witness) = self.with_dispatch_boundary_witness(token, expected, |_| dispatch_boundary())?;
        Ok(result)
    }

    fn validate_token_live_witness(
        &self,
        token: &VerifiedUseToken,
        expected: &FinalUseBinding,
        boundary: VerifiedUseBoundaryV1,
    ) -> Result<VerifiedUseTokenWitnessV1, FinalUseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) || &token.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if state.pending_revocations.is_some() {
            return Err(FinalUseError::RevocationPending);
        }
        let now_unix_ms = validate_live_clock(&token.grant, &state.head, self.0.clock.as_ref())?;
        Ok(VerifiedUseTokenWitnessV1::final_use(
            self.0.signer_id.clone(), token.grant.grant_id.clone(), state.head.authority_epoch,
            state.head.revision, now_unix_ms, boundary, final_use_binding_witness_sha256(expected)?,
        ))
    }

    fn with_dispatch_boundary_witness<T>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        dispatch_boundary: impl FnOnce(&VerifiedUseTokenWitnessV1) -> T,
    ) -> Result<(T, VerifiedUseTokenWitnessV1), FinalUseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) || &token.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if state.pending_revocations.is_some() {
            return Err(FinalUseError::RevocationPending);
        }
        let now_unix_ms = validate_live_clock(&token.grant, &state.head, self.0.clock.as_ref())?;
        let witness = VerifiedUseTokenWitnessV1::final_use(
            self.0.signer_id.clone(), token.grant.grant_id, state.head.authority_epoch,
            state.head.revision, now_unix_ms, VerifiedUseBoundaryV1::DispatchEntry,
            final_use_binding_witness_sha256(expected)?,
        );
        let result = dispatch_boundary(&witness);
        drop(state);
        Ok((result, witness))
    }

    fn persist_or_fence(
        &self,
        state: &mut std::sync::MutexGuard<'_, State>,
        next: State,
    ) -> Result<(), FinalUseError> {
        if let Some(frontier_store) = &self.0.frontier_store {
            let expected = frontier_for_state(state);
            let advanced = frontier_for_state(&next);
            if let Err(error) = frontier_store.compare_and_set(&self.0.signer_id, &expected, &advanced) {
                state.failed = true;
                return Err(map_trust_error(error));
            }
        }
        if self.0.store.persist(&next).is_err() {
            state.failed = true;
            return Err(FinalUseError::Unavailable);
        }
        **state = next;
        Ok(())
    }
}

struct ActiveDispatchGuard {
    owner: Arc<Inner>,
}

impl Drop for ActiveDispatchGuard {
    fn drop(&mut self) {
        let previous = self.owner.active_dispatches.fetch_sub(1, Ordering::AcqRel);
        debug_assert!(previous != 0, "final-use dispatch fence underflow");
    }
}

/// Canonical closed-world signed admission boundary.
pub fn claim_final_use(
    authority: &FinalUseAuthority,
    signed: &SignedFinalUseGrant,
    expected: &FinalUseBinding,
) -> Result<VerifiedUseToken, FinalUseError> {
    let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_CLAIM;
    authority.claim(signed, expected)
}

/// Canonical synchronous consumer-entry boundary.
pub fn deliver_final_use<T>(
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    expected: &FinalUseBinding,
    consumer: impl FnOnce() -> T,
) -> Result<T, FinalUseError> {
    let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DELIVERY;
    authority.with_verified_use(token, expected, consumer)
}

/// Consumer entry plus a non-authorizing witness.
pub fn deliver_final_use_with_witness<T>(
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    expected: &FinalUseBinding,
    consumer: impl FnOnce() -> T,
) -> Result<(T, VerifiedUseTokenWitnessV1), FinalUseError> {
    let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DELIVERY_WITNESS;
    let witness = authority.validate_token_live_witness(&token, expected, VerifiedUseBoundaryV1::ConsumerEntry)?;
    Ok((consumer(), witness))
}

/// Canonical bounded local irreversible transition under the owner mutex.
pub fn dispatch_final_use<T>(
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    expected: &FinalUseBinding,
    dispatch_boundary: impl FnOnce() -> T,
) -> Result<T, FinalUseError> {
    let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DISPATCH;
    authority.with_dispatch_boundary(token, expected, dispatch_boundary)
}

/// Bounded local dispatch plus a non-authorizing witness.
pub fn dispatch_final_use_with_witness<T>(
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    expected: &FinalUseBinding,
    dispatch_boundary: impl FnOnce(&VerifiedUseTokenWitnessV1) -> T,
) -> Result<(T, VerifiedUseTokenWitnessV1), FinalUseError> {
    let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DISPATCH_WITNESS;
    authority.with_dispatch_boundary_witness(token, expected, dispatch_boundary)
}

fn final_use_binding_witness_sha256(binding: &FinalUseBinding) -> Result<[u8; 32], FinalUseError> {
    let encoded = serde_json::to_vec(binding).map_err(|_| FinalUseError::InvalidGrant)?;
    let mut hash = Sha256::new();
    hash.update(b"hepta.kernel.authority.verified-use-binding.final-use.v1\0");
    hash.update(encoded);
    Ok(hash.finalize().into())
}

fn valid_head(head: &FinalUseRevocations) -> bool {
    head.authority_epoch > 0
        && head.revision > 0
        && head.revoked_grant_ids.len() <= MAX_REVOKED_GRANTS
        && head.revoked_grant_ids.iter().all(|id| identifier(id))
}

fn head_advances(current: &FinalUseRevocations, next: &FinalUseRevocations) -> bool {
    valid_head(next)
        && next.authority_epoch >= current.authority_epoch
        && next.revision > current.revision
        && (next.authority_epoch > current.authority_epoch || next.revoked_grant_ids.is_superset(&current.revoked_grant_ids))
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.bytes().all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
}

fn validate_live(
    grant: &FinalUseGrant,
    head: &FinalUseRevocations,
    now_unix_ms: u64,
) -> Result<(), FinalUseError> {
    if grant.authority_epoch != head.authority_epoch {
        return Err(FinalUseError::EpochMismatch);
    }
    if head.revoked_grant_ids.contains(&grant.grant_id) {
        return Err(FinalUseError::Revoked);
    }
    if now_unix_ms < grant.not_before_unix_ms {
        return Err(FinalUseError::NotYetValid);
    }
    if now_unix_ms >= grant.expires_at_unix_ms {
        return Err(FinalUseError::Expired);
    }
    Ok(())
}

/// One owner-lock-scoped sample must place the *entire* possible time interval
/// within the signed half-open window. Arithmetic overflow is rejection.
fn validate_live_clock(
    grant: &FinalUseGrant,
    head: &FinalUseRevocations,
    clock: &dyn AuthorityClock,
) -> Result<u64, FinalUseError> {
    let (now, uncertainty) = clock.now_with_uncertainty().map_err(map_trust_error)?;
    if uncertainty > crate::authority_trust::MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS {
        return Err(FinalUseError::InvalidTrust);
    }
    validate_live(grant, head, now)?;
    let earliest = now.checked_sub(uncertainty).ok_or(FinalUseError::NotYetValid)?;
    let latest = now.checked_add(uncertainty).ok_or(FinalUseError::Expired)?;
    validate_live(grant, head, earliest)?;
    validate_live(grant, head, latest)?;
    Ok(now)
}

fn hash_revocation_head(hash: &mut Sha256, head: &FinalUseRevocations) {
    hash.update(head.authority_epoch.to_le_bytes());
    hash.update(head.revision.to_le_bytes());
    hash.update((head.revoked_grant_ids.len() as u64).to_le_bytes());
    for grant_id in &head.revoked_grant_ids {
        hash.update((grant_id.len() as u64).to_le_bytes());
        hash.update(grant_id.as_bytes());
    }
}

fn frontier_for_state(state: &State) -> FinalUseFrontier {
    let mut hash = Sha256::new();
    hash.update(b"hepta.kernel.authority.final-use-frontier.v2\0");
    hash.update(b"committed\0");
    hash_revocation_head(&mut hash, &state.head);
    if let Some(pending) = &state.pending_revocations {
        hash.update(b"pending\x01");
        hash_revocation_head(&mut hash, pending);
    } else {
        hash.update(b"pending\0");
    }
    hash.update((state.used_nonces.len() as u64).to_le_bytes());
    for nonce in &state.used_nonces {
        hash.update(nonce);
    }
    let effective = state.pending_revocations.as_ref().unwrap_or(&state.head);
    FinalUseFrontier {
        authority_epoch: effective.authority_epoch,
        revocation_revision: effective.revision,
        state_sha256: hash.finalize().into(),
    }
}

fn recover_local_state_from_trusted_frontier(
    store: &store::Store,
    state: &mut State,
    authenticated_head: &FinalUseRevocations,
    trusted: FinalUseFrontier,
) -> Result<(), FinalUseError> {
    if state.pending_revocations.is_none() && head_advances(&state.head, authenticated_head) {
        let mut pending = state.clone();
        pending.pending_revocations = Some(authenticated_head.clone());
        if frontier_for_state(&pending) == trusted {
            store.persist(&pending)?;
            *state = pending;
            return Ok(());
        }
    }
    if let Some(pending_head) = state.pending_revocations.clone() {
        let mut committed = state.clone();
        if pending_head.authority_epoch > committed.head.authority_epoch {
            committed.used_nonces.clear();
        }
        committed.head = pending_head;
        committed.pending_revocations = None;
        if frontier_for_state(&committed) == trusted {
            store.persist(&committed)?;
            *state = committed;
            return Ok(());
        }
    }
    Err(FinalUseError::AntiRollbackViolation)
}

fn map_trust_error(error: AuthorityTrustError) -> FinalUseError {
    match error {
        AuthorityTrustError::Invalid => FinalUseError::InvalidTrust,
        AuthorityTrustError::Conflict => FinalUseError::AntiRollbackViolation,
        AuthorityTrustError::Unavailable => FinalUseError::Unavailable,
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FinalUseError {
    InvalidGrant,
    InvalidTrust,
    AntiRollbackViolation,
    InvalidSignature,
    BindingMismatch,
    EpochMismatch,
    StaleRevocationHead,
    Revoked,
    NotYetValid,
    Expired,
    AlreadyClaimed,
    CapacityExceeded,
    DispatchInProgress,
    RevocationPending,
    Unavailable,
    UnsafeStateDirectory,
    StateLocked,
}

impl fmt::Display for FinalUseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for FinalUseError {}

#[cfg(all(test, unix))]
#[path = "final_use_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "final_use_time_tests.rs"]
mod time_tests;

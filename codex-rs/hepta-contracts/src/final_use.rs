//! Kernel-owned final-use admission. Trust and revocation heads come from the
//! host, never from request metadata. This verifier contains no signing key.

use std::collections::BTreeSet;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;

use crate::AuthorityClock;
use crate::AuthorityFrontierStore;
use crate::AuthorityReplayClaim;
use crate::AuthorityReplayEpochAdvance;
use crate::AuthorityReplayError;
use crate::AuthorityReplayStore;
use crate::AuthorityTrustError;
use crate::SystemAuthorityClock;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

#[path = "final_use_store.rs"]
mod store;

const MAX_LOCAL_CLAIMS: usize = 16_384;
const MAX_REVOCATIONS: usize = 16_384;
const MAX_LIFETIME_MS: u64 = 300_000;
const MAX_ISSUER_TRUST_KEYS: usize = 8;

/// Source-visible markers consumed by the closed-world B4 caller proof.
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_CLAIM: &str = "claim_final_use";
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DELIVERY: &str = "deliver_final_use";
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DISPATCH: &str = "dispatch_final_use";

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
/// window. Key ids are configuration/audit identities and are not request
/// authority.
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
/// state. The digest covers the complete revocation head and claimed nonce set.
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
            failed: false,
        }))
    }

    /// Provisioning frontier for an authority whose replay truth is held by an
    /// external atomic replay store rather than the local JSON snapshot.
    pub fn for_external_replay_head(head: &FinalUseRevocations) -> Result<Self, FinalUseError> {
        if !valid_head(head) {
            return Err(FinalUseError::InvalidTrust);
        }
        Ok(frontier_for_external_replay_state(&State {
            head: head.clone(),
            used_nonces: BTreeSet::new(),
            failed: false,
        }))
    }
}

/// Read-only capacity/frontier snapshot for host alerting and epoch rollover.
/// This is observability only: it grants no authority and does not mutate state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FinalUseCapacity {
    pub authority_epoch: u64,
    pub revision: u64,
    pub used_nonces: usize,
    pub revoked_grants: usize,
    pub max_claims: usize,
    pub max_revocations: usize,
    pub external_replay: bool,
}

impl FinalUseCapacity {
    pub fn remaining_claims(self) -> usize {
        self.max_claims.saturating_sub(self.used_nonces)
    }

    pub fn remaining_revocations(self) -> usize {
        self.max_revocations.saturating_sub(self.revoked_grants)
    }

    /// Hosts can reserve a bounded safety margin before requesting a signed
    /// epoch-transition head. The caller chooses the reserve according to its
    /// deployment/fanout SLA; this method itself is not rollover authority.
    pub fn rollover_required_with_reserve(self, reserve: usize) -> bool {
        (!self.external_replay && self.remaining_claims() <= reserve)
            || self.remaining_revocations() <= reserve
    }

    pub fn claims_are_externally_owned(self) -> bool {
        self.external_replay
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct State {
    head: FinalUseRevocations,
    used_nonces: BTreeSet<[u8; 32]>,
    #[serde(skip)]
    failed: bool,
}

struct Inner {
    signer_id: String,
    issuer_keys: Vec<PinnedIssuerKey>,
    state: Mutex<State>,
    store: store::Store,
    clock: Arc<dyn AuthorityClock>,
    frontier_store: Option<Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>>,
    replay_store: Option<Arc<dyn AuthorityReplayStore>>,
}

/// Host-configured authority owner. Clone shares the same revocation and
/// single-use registry; there is deliberately no permissive default.
#[derive(Clone)]
pub struct FinalUseAuthority(Arc<Inner>);

impl fmt::Debug for FinalUseAuthority {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("FinalUseAuthority([PINNED TRUST])")
    }
}

/// An unforgeable, non-cloneable claim issued only after signature verification.
/// Ownership passes to one effect adapter. It is not serializable.
pub struct VerifiedUseToken {
    owner: Arc<Inner>,
    grant: FinalUseGrant,
}

impl fmt::Debug for VerifiedUseToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("VerifiedUseToken([REDACTED])")
    }
}

impl FinalUseAuthority {
    /// Compatibility constructor using the process system clock and no
    /// external rollback oracle. Product compositions must prefer
    /// open_state_dir_with_trust.
    pub fn open_state_dir(
        directory: &std::path::Path,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
    ) -> Result<Self, FinalUseError> {
        Self::open_state_dir_with_clock(
            directory,
            signer_id,
            verifying_key,
            head,
            Arc::new(SystemAuthorityClock),
        )
    }

    /// Clock-injected constructor for qualification and hosts that have an
    /// independently protected time source but no external rollback oracle.
    pub fn open_state_dir_with_clock(
        directory: &std::path::Path,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, FinalUseError> {
        let key =
            VerifyingKey::from_bytes(&verifying_key).map_err(|_| FinalUseError::InvalidTrust)?;
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
            store,
            clock,
            frontier_store: None,
            replay_store: None,
        })))
    }

    /// Production constructor: trusted time plus an externally durable CAS
    /// frontier. The external frontier must exactly match local state on open.
    /// Every mutation advances it before the corresponding local fsync/rename.
    pub fn open_state_dir_with_trust(
        directory: &std::path::Path,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        let key =
            VerifyingKey::from_bytes(&verifying_key).map_err(|_| FinalUseError::InvalidTrust)?;
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
            store,
            clock,
            frontier_store: Some(frontier_store),
            replay_store: None,
        })))
    }

    /// Production constructor with a bounded issuer key ring. The complete
    /// trust-set digest is pinned in durable store schema V2. V1 single-key
    /// state is not silently migrated into this trust model.
    pub fn open_state_dir_with_issuer_keys(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, FinalUseError> {
        if !identifier(&signer_id) || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        let (issuer_keys, issuer_trust_sha256) = pin_issuer_keys(issuer_keys)?;
        let (store, state) = store::Store::open_key_ring_exact(
            directory,
            &signer_id,
            issuer_trust_sha256,
            head,
        )?;
        let observed = frontier_for_state(&state);
        let trusted = frontier_store.load(&signer_id).map_err(map_trust_error)?;
        if trusted != observed {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys,
            state: Mutex::new(state),
            store,
            clock,
            frontier_store: Some(frontier_store),
            replay_store: None,
        })))
    }

    /// Production constructor with trusted time, rollback frontier and an
    /// externally durable atomic replay store. Each replica uses its own
    /// private local state directory while all replicas for signer_id share
    /// the same replay owner. The replay store must be explicitly provisioned
    /// to the exact starting epoch before this constructor is called.
    pub fn open_state_dir_with_trust_and_replay(
        directory: &std::path::Path,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
        replay_store: Arc<dyn AuthorityReplayStore>,
    ) -> Result<Self, FinalUseError> {
        let key =
            VerifyingKey::from_bytes(&verifying_key).map_err(|_| FinalUseError::InvalidTrust)?;
        if !identifier(&signer_id) || key.is_weak() || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        if replay_store
            .current_epoch(&signer_id)
            .map_err(map_replay_error)?
            != head.authority_epoch
        {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        let (store, state) = store::Store::open_exact(directory, &signer_id, verifying_key, head)?;
        if !state.used_nonces.is_empty() {
            return Err(FinalUseError::InvalidTrust);
        }
        let observed = frontier_for_external_replay_state(&state);
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
            store,
            clock,
            frontier_store: Some(frontier_store),
            replay_store: Some(replay_store),
        })))
    }

    /// Key-ring variant of open_state_dir_with_trust_and_replay.
    pub fn open_state_dir_with_issuer_keys_and_replay(
        directory: &std::path::Path,
        signer_id: String,
        issuer_keys: Vec<FinalUseIssuerTrustKey>,
        head: FinalUseRevocations,
        clock: Arc<dyn AuthorityClock>,
        frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
        replay_store: Arc<dyn AuthorityReplayStore>,
    ) -> Result<Self, FinalUseError> {
        if !identifier(&signer_id) || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        clock.now_unix_ms().map_err(map_trust_error)?;
        if replay_store
            .current_epoch(&signer_id)
            .map_err(map_replay_error)?
            != head.authority_epoch
        {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        let (issuer_keys, issuer_trust_sha256) = pin_issuer_keys(issuer_keys)?;
        let (store, state) = store::Store::open_key_ring_exact(
            directory,
            &signer_id,
            issuer_trust_sha256,
            head,
        )?;
        if !state.used_nonces.is_empty() {
            return Err(FinalUseError::InvalidTrust);
        }
        let observed = frontier_for_external_replay_state(&state);
        let trusted = frontier_store.load(&signer_id).map_err(map_trust_error)?;
        if trusted != observed {
            return Err(FinalUseError::AntiRollbackViolation);
        }
        Ok(Self(Arc::new(Inner {
            signer_id,
            issuer_keys,
            state: Mutex::new(state),
            store,
            clock,
            frontier_store: Some(frontier_store),
            replay_store: Some(replay_store),
        })))
    }

    pub fn issuer_key_ids(&self) -> Vec<&str> {
        self.0
            .issuer_keys
            .iter()
            .map(|candidate| candidate.key_id.as_str())
            .collect()
    }

    pub fn frontier(&self) -> Result<FinalUseFrontier, FinalUseError> {
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        Ok(if self.0.replay_store.is_some() {
            frontier_for_external_replay_state(&state)
        } else {
            frontier_for_state(&state)
        })
    }

    /// Return a coherent read-only snapshot that lets the trusted host alert
    /// before either bounded registry reaches fail-closed capacity. An epoch
    /// transition is still accepted only through `update_revocations` (or the
    /// independently authenticated revocation-feed wrapper).
    pub fn capacity(&self) -> Result<FinalUseCapacity, FinalUseError> {
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let (used_nonces, max_claims, external_replay) =
            if let Some(replay_store) = &self.0.replay_store {
                let count = replay_store
                    .claimed_count(&self.0.signer_id, state.head.authority_epoch)
                    .map_err(map_replay_error)?;
                (
                    usize::try_from(count).map_err(|_| FinalUseError::Unavailable)?,
                    usize::MAX,
                    true,
                )
            } else {
                (state.used_nonces.len(), MAX_LOCAL_CLAIMS, false)
            };
        Ok(FinalUseCapacity {
            authority_epoch: state.head.authority_epoch,
            revision: state.head.revision,
            used_nonces,
            revoked_grants: state.head.revoked_grant_ids.len(),
            max_claims,
            max_revocations: MAX_REVOCATIONS,
            external_replay,
        })
    }

    /// Called only by the trusted host, not from a provider response or grant.
    /// Revocations are monotonic within an epoch and are never silently dropped.
    pub fn update_revocations(&self, head: FinalUseRevocations) -> Result<(), FinalUseError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        if !valid_head(&head)
            || head.authority_epoch < state.head.authority_epoch
            || head.revision <= state.head.revision
            || (head.authority_epoch == state.head.authority_epoch
                && !head
                    .revoked_grant_ids
                    .is_superset(&state.head.revoked_grant_ids))
        {
            return Err(FinalUseError::StaleRevocationHead);
        }
        let mut next = state.clone();
        if head.authority_epoch > next.head.authority_epoch {
            if let Some(replay_store) = &self.0.replay_store {
                match replay_store
                    .advance_epoch(
                        &self.0.signer_id,
                        next.head.authority_epoch,
                        head.authority_epoch,
                    )
                    .map_err(map_replay_error)
                {
                    Ok(AuthorityReplayEpochAdvance::Advanced)
                    | Ok(AuthorityReplayEpochAdvance::AlreadyAtTarget) => {}
                    Err(error) => {
                        state.failed = true;
                        return Err(error);
                    }
                }
            }
            next.used_nonces.clear();
        }
        next.head = head;
        self.persist_or_fence(&mut state, next)
    }

    /// Atomically validate and claim one nonce immediately before dispatch.
    /// A failed or uncertain dispatch does not refund the nonce: retry needs a
    /// new owner-signed grant, after the caller has reconciled any unknown effect.
    pub fn claim(
        &self,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
    ) -> Result<VerifiedUseToken, FinalUseError> {
        let input = signed.grant.signing_bytes()?;
        if signed.grant.signer_id != self.0.signer_id || &signed.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| FinalUseError::InvalidSignature)?;
        let verified = self.0.issuer_keys.iter().any(|candidate| {
            signed.grant.authority_epoch >= candidate.not_before_authority_epoch
                && signed.grant.authority_epoch <= candidate.not_after_authority_epoch
                && candidate.key.verify_strict(&input, &signature).is_ok()
        });
        if !verified {
            return Err(FinalUseError::InvalidSignature);
        }
        if let Some(replay_store) = &self.0.replay_store {
            let before = {
                let state = self
                    .0
                    .state
                    .lock()
                    .map_err(|_| FinalUseError::Unavailable)?;
                if state.failed {
                    return Err(FinalUseError::Unavailable);
                }
                validate_live(&signed.grant, &state.head, self.now_unix_ms()?)?;
                frontier_for_external_replay_state(&state)
            };
            let frontier_store = self
                .0
                .frontier_store
                .as_ref()
                .ok_or(FinalUseError::InvalidTrust)?;
            if frontier_store
                .load(&self.0.signer_id)
                .map_err(map_trust_error)?
                != before
            {
                return Err(FinalUseError::AntiRollbackViolation);
            }

            match replay_store
                .claim(
                    &self.0.signer_id,
                    signed.grant.authority_epoch,
                    signed.grant.nonce,
                )
                .map_err(map_replay_error)?
            {
                AuthorityReplayClaim::Claimed => {}
                AuthorityReplayClaim::AlreadyClaimed => {
                    return Err(FinalUseError::AlreadyClaimed);
                }
            }

            // The external claim is intentionally not refunded. Recheck both
            // local authority and the shared head frontier after its durable
            // I/O. A different replica that advanced same-epoch revocations
            // therefore fences this stale replica before dispatch.
            let after = {
                let state = self
                    .0
                    .state
                    .lock()
                    .map_err(|_| FinalUseError::Unavailable)?;
                if state.failed {
                    return Err(FinalUseError::Unavailable);
                }
                validate_live(&signed.grant, &state.head, self.now_unix_ms()?)?;
                frontier_for_external_replay_state(&state)
            };
            if frontier_store
                .load(&self.0.signer_id)
                .map_err(map_trust_error)?
                != after
            {
                return Err(FinalUseError::AntiRollbackViolation);
            }
            return Ok(VerifiedUseToken {
                owner: Arc::clone(&self.0),
                grant: signed.grant.clone(),
            });
        }

        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let now_unix_ms = self.now_unix_ms()?;
        validate_live(&signed.grant, &state.head, now_unix_ms)?;
        if state.used_nonces.contains(&signed.grant.nonce) {
            return Err(FinalUseError::AlreadyClaimed);
        }
        if state.used_nonces.len() >= MAX_LOCAL_CLAIMS {
            return Err(FinalUseError::CapacityExceeded);
        }
        let mut next = state.clone();
        next.used_nonces.insert(signed.grant.nonce);
        self.persist_or_fence(&mut state, next)?;
        // Compatibility persistence can outlast a short grant. Never admit a
        // dispatch using time sampled before that I/O.
        validate_live(&signed.grant, &state.head, self.now_unix_ms()?)?;
        Ok(VerifiedUseToken {
            owner: Arc::clone(&self.0),
            grant: signed.grant.clone(),
        })
    }

    /// Revalidate live authority after asynchronous work and linearize final
    /// consumer entry. The mutex is released before running user code: a slow,
    /// panicking or re-entrant callback cannot block future revocation updates.
    /// A revocation that commits after this validation is ordered after entry
    /// and cannot retroactively cancel an already-entered synchronous effect.
    pub fn with_verified_use<T>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        consumer: impl FnOnce() -> T,
    ) -> Result<T, FinalUseError> {
        self.validate_token_live(&token, expected)?;
        Ok(consumer())
    }

    /// Revalidate live authority and hold the revocation linearization fence
    /// only while the caller crosses its local irreversible dispatch boundary.
    ///
    /// The callback must synchronously publish durable intent and/or cross the
    /// already-selected local adapter/worker boundary, then return immediately.
    /// It must not wait for remote execution, provider terminality,
    /// reconciliation, or arbitrary user code. Revocation updates that start
    /// after this validation are ordered after the local dispatch boundary.
    pub fn with_dispatch_boundary<T>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        dispatch_boundary: impl FnOnce() -> T,
    ) -> Result<T, FinalUseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) || &token.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        validate_live(&token.grant, &state.head, self.now_unix_ms()?)?;
        let result = dispatch_boundary();
        drop(state);
        Ok(result)
    }

    fn validate_token_live(
        &self,
        token: &VerifiedUseToken,
        expected: &FinalUseBinding,
    ) -> Result<(), FinalUseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) || &token.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        validate_live(&token.grant, &state.head, self.now_unix_ms()?)
    }

    fn now_unix_ms(&self) -> Result<u64, FinalUseError> {
        self.0.clock.now_unix_ms().map_err(map_trust_error)
    }

    fn persist_or_fence(
        &self,
        state: &mut std::sync::MutexGuard<'_, State>,
        next: State,
    ) -> Result<(), FinalUseError> {
        if let Some(frontier_store) = &self.0.frontier_store {
            let expected = if self.0.replay_store.is_some() {
                frontier_for_external_replay_state(state)
            } else {
                frontier_for_state(state)
            };
            let advanced = if self.0.replay_store.is_some() {
                frontier_for_external_replay_state(&next)
            } else {
                frontier_for_state(&next)
            };
            if let Err(error) =
                frontier_store.compare_and_set(&self.0.signer_id, &expected, &advanced)
            {
                // Active replicas may race to apply the same authenticated
                // head. Treat an already-advanced exact target as idempotent;
                // any different frontier remains fail-closed.
                let already = matches!(error, AuthorityTrustError::Conflict)
                    && frontier_store
                        .load(&self.0.signer_id)
                        .map(|observed| observed == advanced)
                        .unwrap_or(false);
                if !already {
                    state.failed = true;
                    return Err(map_trust_error(error));
                }
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

/// Closed-world B4 entrypoint for signed final-use admission. Product adapters
/// call this free function rather than inventing alternate admission paths.
pub fn claim_final_use(
    authority: &FinalUseAuthority,
    signed: &SignedFinalUseGrant,
    expected: &FinalUseBinding,
) -> Result<VerifiedUseToken, FinalUseError> {
    let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_CLAIM;
    authority.claim(signed, expected)
}

/// Closed-world B4 entrypoint for the final synchronous effect boundary.
pub fn deliver_final_use<T>(
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    expected: &FinalUseBinding,
    consumer: impl FnOnce() -> T,
) -> Result<T, FinalUseError> {
    let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DELIVERY;
    authority.with_verified_use(token, expected, consumer)
}

/// Closed-world B4 entrypoint for a bounded local irreversible dispatch fence.
/// Unlike deliver_final_use, this keeps the authority mutex across only the
/// short local boundary supplied by the caller.
pub fn dispatch_final_use<T>(
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    expected: &FinalUseBinding,
    dispatch_boundary: impl FnOnce() -> T,
) -> Result<T, FinalUseError> {
    let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_DISPATCH;
    authority.with_dispatch_boundary(token, expected, dispatch_boundary)
}

fn valid_head(head: &FinalUseRevocations) -> bool {
    head.authority_epoch > 0
        && head.revision > 0
        && head.revoked_grant_ids.len() <= MAX_REVOCATIONS
        && head.revoked_grant_ids.iter().all(|id| identifier(id))
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
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

fn frontier_for_state(state: &State) -> FinalUseFrontier {
    let mut hash = Sha256::new();
    hash.update(b"hepta.kernel.authority.final-use-frontier.v1\0");
    hash.update(state.head.authority_epoch.to_le_bytes());
    hash.update(state.head.revision.to_le_bytes());
    hash.update((state.head.revoked_grant_ids.len() as u64).to_le_bytes());
    for grant_id in &state.head.revoked_grant_ids {
        hash.update((grant_id.len() as u64).to_le_bytes());
        hash.update(grant_id.as_bytes());
    }
    hash.update((state.used_nonces.len() as u64).to_le_bytes());
    for nonce in &state.used_nonces {
        hash.update(nonce);
    }
    FinalUseFrontier {
        authority_epoch: state.head.authority_epoch,
        revocation_revision: state.head.revision,
        state_sha256: hash.finalize().into(),
    }
}

fn frontier_for_external_replay_state(state: &State) -> FinalUseFrontier {
    let mut hash = Sha256::new();
    hash.update(b"hepta.kernel.authority.final-use-frontier.external-replay.v1\0");
    hash.update(state.head.authority_epoch.to_le_bytes());
    hash.update(state.head.revision.to_le_bytes());
    hash.update((state.head.revoked_grant_ids.len() as u64).to_le_bytes());
    for grant_id in &state.head.revoked_grant_ids {
        hash.update((grant_id.len() as u64).to_le_bytes());
        hash.update(grant_id.as_bytes());
    }
    FinalUseFrontier {
        authority_epoch: state.head.authority_epoch,
        revocation_revision: state.head.revision,
        state_sha256: hash.finalize().into(),
    }
}

fn map_replay_error(error: AuthorityReplayError) -> FinalUseError {
    match error {
        AuthorityReplayError::Invalid => FinalUseError::InvalidTrust,
        AuthorityReplayError::Conflict => FinalUseError::AntiRollbackViolation,
        AuthorityReplayError::EpochMismatch => FinalUseError::EpochMismatch,
        AuthorityReplayError::Unavailable => FinalUseError::Unavailable,
    }
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

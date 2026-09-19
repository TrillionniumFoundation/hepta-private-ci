//! Kernel-owned final-use admission. Trust and revocation heads come from the
//! host, never from request metadata. This verifier contains no signing key.

use std::collections::BTreeSet;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

#[path = "final_use_store.rs"]
mod store;

const MAX_REVOCATIONS: usize = 16_384;
const MAX_LIFETIME_MS: u64 = 300_000;

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

/// Trusted host update. Increasing revision is mandatory; epoch changes fence
/// every earlier grant. The authority persists the head and claimed nonces.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseRevocations {
    pub authority_epoch: u64,
    pub revision: u64,
    pub revoked_grant_ids: BTreeSet<String>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct State {
    head: FinalUseRevocations,
    used_nonces: BTreeSet<[u8; 32]>,
    #[serde(skip)]
    failed: bool,
    #[serde(skip)]
    claim_log_bytes: u64,
}

struct Inner {
    signer_id: String,
    key: VerifyingKey,
    state: Mutex<State>,
    store: store::Store,
}

/// Host-configured authority owner. Clones share the in-process cache; separate
/// processes may safely open the same qualified state directory because every
/// mutation and final-use callback is fenced by the same OS lock.
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
    pub fn open_state_dir(
        directory: &std::path::Path,
        signer_id: String,
        verifying_key: [u8; 32],
        head: FinalUseRevocations,
    ) -> Result<Self, FinalUseError> {
        let key =
            VerifyingKey::from_bytes(&verifying_key).map_err(|_| FinalUseError::InvalidTrust)?;
        if !identifier(&signer_id) || key.is_weak() || !valid_head(&head) {
            return Err(FinalUseError::InvalidTrust);
        }
        let (store, state) = store::Store::open(directory, &signer_id, verifying_key, head)?;
        Ok(Self(Arc::new(Inner {
            signer_id,
            key,
            state: Mutex::new(state),
            store,
        })))
    }

    /// Called only by the trusted host, not from a provider response or grant.
    /// Revocations are monotonic within an epoch and are never silently dropped.
    ///
    /// The cross-process lock is held from disk refresh through durable head
    /// publication, so two active owners sharing one state directory cannot
    /// race a revocation update or claim against stale local state.
    pub fn update_revocations(&self, head: FinalUseRevocations) -> Result<(), FinalUseError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let _guard = self
            .0
            .store
            .lock_mutation()
            .inspect_err(|_| state.failed = true)?;
        let current = self
            .0
            .store
            .refresh(&state)
            .inspect_err(|_| state.failed = true)?;
        if !valid_head(&head)
            || head.authority_epoch < current.head.authority_epoch
            || head.revision <= current.head.revision
            || (head.authority_epoch == current.head.authority_epoch
                && !head
                    .revoked_grant_ids
                    .is_superset(&current.head.revoked_grant_ids))
        {
            *state = current;
            return Err(FinalUseError::StaleRevocationHead);
        }
        let mut next = current;
        if head.authority_epoch > next.head.authority_epoch {
            next.used_nonces.clear();
        }
        next.head = head;
        if self.0.store.persist_head(&next.head).is_err() {
            state.failed = true;
            return Err(FinalUseError::Unavailable);
        }
        *state = next;
        Ok(())
    }

    /// Atomically validate and claim one nonce immediately before dispatch.
    /// A failed or uncertain dispatch does not refund the nonce: retry needs a
    /// new owner-signed grant, after the caller has reconciled any unknown effect.
    ///
    /// Claims are appended to a checksummed journal. There is no fixed
    /// per-epoch claim count; storage exhaustion or corruption fails closed.
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
        self.0
            .key
            .verify_strict(&input, &signature)
            .map_err(|_| FinalUseError::InvalidSignature)?;

        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let _guard = self
            .0
            .store
            .lock_mutation()
            .inspect_err(|_| state.failed = true)?;
        let mut current = self
            .0
            .store
            .refresh(&state)
            .inspect_err(|_| state.failed = true)?;
        validate_live(&signed.grant, &current.head)?;
        if current.used_nonces.contains(&signed.grant.nonce) {
            *state = current;
            return Err(FinalUseError::AlreadyClaimed);
        }
        let next_offset = match self.0.store.append_claim(
            signed.grant.authority_epoch,
            signed.grant.nonce,
            current.claim_log_bytes,
        ) {
            Ok(offset) => offset,
            Err(_) => {
                state.failed = true;
                return Err(FinalUseError::Unavailable);
            }
        };
        current.claim_log_bytes = next_offset;
        current.used_nonces.insert(signed.grant.nonce);
        // Persistence can outlast a short grant. Never admit a dispatch using
        // the time sampled before that I/O; its nonce stays consumed on expiry.
        let live = validate_live(&signed.grant, &current.head);
        *state = current;
        live?;
        Ok(VerifiedUseToken {
            owner: Arc::clone(&self.0),
            grant: signed.grant.clone(),
        })
    }

    /// Revalidate live authority after asynchronous work and before releasing a
    /// secret to its consumer. The consumer runs under both the in-process and
    /// cross-process revocation fence, so a successful revocation update cannot
    /// race between this check and callback entry.
    pub fn with_verified_use<T>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        consumer: impl FnOnce() -> T,
    ) -> Result<T, FinalUseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) || &token.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let _guard = self
            .0
            .store
            .lock_mutation()
            .inspect_err(|_| state.failed = true)?;
        let current = self
            .0
            .store
            .refresh(&state)
            .inspect_err(|_| state.failed = true)?;
        validate_live(&token.grant, &current.head)?;
        *state = current;
        let result = consumer();
        Ok(result)
    }
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

fn validate_live(grant: &FinalUseGrant, head: &FinalUseRevocations) -> Result<(), FinalUseError> {
    if grant.authority_epoch != head.authority_epoch {
        return Err(FinalUseError::EpochMismatch);
    }
    if head.revoked_grant_ids.contains(&grant.grant_id) {
        return Err(FinalUseError::Revoked);
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| FinalUseError::Unavailable)?
        .as_millis();
    if now < u128::from(grant.not_before_unix_ms) {
        return Err(FinalUseError::NotYetValid);
    }
    if now >= u128::from(grant.expires_at_unix_ms) {
        return Err(FinalUseError::Expired);
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FinalUseError {
    InvalidGrant,
    InvalidTrust,
    InvalidSignature,
    BindingMismatch,
    EpochMismatch,
    StaleRevocationHead,
    Revoked,
    NotYetValid,
    Expired,
    AlreadyClaimed,
    /// Retained for wire/source compatibility with older callers. The
    /// append-only replay journal no longer emits this for ordinary claims.
    CapacityExceeded,
    Unavailable,
    UnsafeStateDirectory,
    /// Retained for source compatibility. Shared-state owners now serialize
    /// individual mutations instead of rejecting concurrent process opens.
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

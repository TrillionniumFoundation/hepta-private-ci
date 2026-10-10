//! Independently signed, short-lived NDU read receipt and live frontier check.
//!
//! NDU snapshots and final-use grants are distinct authorities. A digest passed
//! by a caller is never evidence of an NDU read. Production composition must
//! pin an independent NDU owner key, protected time and a control-owned current
//! scope frontier; no synthetic or permit-all default exists.

use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_types::{Digest32, NduSnapshotRefV1, StableId};
use ed25519_dalek::{Signature, VerifyingKey};

const MAX_READ_VALIDITY_MS: u64 = 30_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduReadVerificationErrorV1 {
    UntrustedOwner,
    InvalidKey,
    InvalidReceipt,
    Expired,
    ClockUnavailable,
    FrontierUnavailable,
    StaleFrontier,
    Signature,
}

impl fmt::Display for NduReadVerificationErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for NduReadVerificationErrorV1 {}

/// Provided by the authoritative Control scope owner, never by Cognitive.
pub trait NduReadFrontierPortV1: fmt::Debug + Send + Sync {
    fn latest(&self, scope: &StableId) -> Result<NduSnapshotRefV1, NduReadVerificationErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedNduSnapshotReadV1 {
    pub snapshot: NduSnapshotRefV1,
    pub read_id: StableId,
    pub read_receipt_digest: Digest32,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub signature: [u8; 64],
}

impl SignedNduSnapshotReadV1 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, NduReadVerificationErrorV1> {
        let snapshot = self.snapshot.semantic_digest()
            .map_err(|_| NduReadVerificationErrorV1::InvalidReceipt)?;
        if self.read_receipt_digest.is_zero()
            || self.issued_at_unix_ms == 0
            || self.expires_at_unix_ms <= self.issued_at_unix_ms
            || self.expires_at_unix_ms - self.issued_at_unix_ms > MAX_READ_VALIDITY_MS
        {
            return Err(NduReadVerificationErrorV1::InvalidReceipt);
        }
        let mut bytes = b"hepta.ndu.signed-snapshot-read.v1".to_vec();
        let id = self.read_id.as_str().as_bytes();
        bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(snapshot.as_array());
        bytes.extend_from_slice(self.read_receipt_digest.as_array());
        bytes.extend_from_slice(&self.issued_at_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_unix_ms.to_be_bytes());
        Ok(bytes)
    }
}

pub struct NduReadVerifierV1 {
    trusted_owner_id: StableId,
    trusted_key: VerifyingKey,
    clock: Arc<dyn AuthorityClock>,
    frontier: Arc<dyn NduReadFrontierPortV1>,
}

impl fmt::Debug for NduReadVerifierV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("NduReadVerifierV1")
            .field("trusted_owner_id", &self.trusted_owner_id)
            .finish_non_exhaustive()
    }
}

impl NduReadVerifierV1 {
    pub fn new(
        owner: StableId,
        verifying_key: [u8; 32],
        clock: Arc<dyn AuthorityClock>,
        frontier: Arc<dyn NduReadFrontierPortV1>,
    ) -> Result<Self, NduReadVerificationErrorV1> {
        let key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| NduReadVerificationErrorV1::InvalidKey)?;
        if key.is_weak() {
            return Err(NduReadVerificationErrorV1::InvalidKey);
        }
        clock.now_unix_ms().map_err(|_| NduReadVerificationErrorV1::ClockUnavailable)?;
        Ok(Self {
            trusted_owner_id: owner,
            trusted_key: key,
            clock,
            frontier,
        })
    }

    /// Exact signed read + bounded trusted time + current live Control scope.
    /// The returned digest binds this exact signed packet into final-use grants.
    pub fn verify(
        &self,
        signed: &SignedNduSnapshotReadV1,
    ) -> Result<Digest32, NduReadVerificationErrorV1> {
        if signed.snapshot.owner_id != self.trusted_owner_id {
            return Err(NduReadVerificationErrorV1::UntrustedOwner);
        }
        let now = self.clock.now_unix_ms()
            .map_err(|_| NduReadVerificationErrorV1::ClockUnavailable)?;
        if now < signed.issued_at_unix_ms || now >= signed.expires_at_unix_ms {
            return Err(NduReadVerificationErrorV1::Expired);
        }
        let signed_bytes = signed.signing_bytes()?;
        self.trusted_key.verify_strict(
            &signed_bytes,
            &Signature::from_bytes(&signed.signature),
        ).map_err(|_| NduReadVerificationErrorV1::Signature)?;
        let current = self.frontier.latest(&signed.snapshot.scope_id)?;
        if current != signed.snapshot {
            return Err(NduReadVerificationErrorV1::StaleFrontier);
        }
        let mut exact = b"hepta.ndu.verified-read-packet.v1".to_vec();
        exact.extend_from_slice(&(signed_bytes.len() as u64).to_be_bytes());
        exact.extend_from_slice(&signed_bytes);
        exact.extend_from_slice(&signed.signature);
        Ok(Digest32::of_bytes(&exact))
    }
}

#[cfg(test)]
#[path = "neuron_ndu_read_tests.rs"]
mod tests;

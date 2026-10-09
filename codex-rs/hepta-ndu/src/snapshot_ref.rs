//! Read-only content-addressed NDU projection reference. This is not a
//! capability, a grant or a selected projection owner.

use codex_hepta_types::{Digest32, Generation, StableId};

const MAX_NDU_SNAPSHOT_BYTES: u64 = 8 * 1024 * 1024;
const MAX_LOCATOR_BYTES: usize = 512;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduSnapshotRefErrorV1 {
    EmptyIdentity,
    InvalidEpoch,
    InvalidSize,
    InvalidLocator,
    PayloadMismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSnapshotRefV1 {
    pub subject_id: StableId,
    pub objective_digest: Digest32,
    pub owner_generation: Generation,
    pub authority_epoch: u64,
    pub fence_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub policy_digest: Digest32,
    pub snapshot_digest: Digest32,
    /// Opaque CAS reference. No path is opened or trust inferred here.
    pub cas_locator: String,
    pub payload_bytes: u64,
}

impl NduSnapshotRefV1 {
    pub fn validate(&self) -> Result<(), NduSnapshotRefErrorV1> {
        if [
            self.objective_digest,
            self.fence_digest,
            self.revocation_frontier_digest,
            self.policy_digest,
            self.snapshot_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
        {
            return Err(NduSnapshotRefErrorV1::EmptyIdentity);
        }
        if self.authority_epoch == 0 {
            return Err(NduSnapshotRefErrorV1::InvalidEpoch);
        }
        if self.payload_bytes == 0 || self.payload_bytes > MAX_NDU_SNAPSHOT_BYTES {
            return Err(NduSnapshotRefErrorV1::InvalidSize);
        }
        if self.cas_locator.is_empty()
            || self.cas_locator.len() > MAX_LOCATOR_BYTES
            || !self.cas_locator.is_ascii()
            || self.cas_locator.chars().any(char::is_whitespace)
        {
            return Err(NduSnapshotRefErrorV1::InvalidLocator);
        }
        Ok(())
    }

    pub fn binding_digest(&self) -> Result<Digest32, NduSnapshotRefErrorV1> {
        self.validate()?;
        let mut bytes = b"hepta.ndu.snapshot-ref.v1".to_vec();
        let id = self.subject_id.as_str().as_bytes();
        bytes.extend_from_slice(&(id.len() as u32).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(self.objective_digest.as_array());
        bytes.extend_from_slice(&self.owner_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        for digest in [
            self.fence_digest,
            self.revocation_frontier_digest,
            self.policy_digest,
            self.snapshot_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        let locator = self.cas_locator.as_bytes();
        bytes.extend_from_slice(&(locator.len() as u32).to_be_bytes());
        bytes.extend_from_slice(locator);
        bytes.extend_from_slice(&self.payload_bytes.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }

    /// Call with the bytes returned by the authenticated CAS owner; do not
    /// assume the locator alone authenticates content or revocation state.
    pub fn verify_payload(&self, payload: &[u8]) -> Result<(), NduSnapshotRefErrorV1> {
        self.validate()?;
        if payload.len() as u64 != self.payload_bytes
            || Digest32::of_bytes(payload) != self.snapshot_digest
        {
            return Err(NduSnapshotRefErrorV1::PayloadMismatch);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "snapshot_ref_tests.rs"]
mod tests;

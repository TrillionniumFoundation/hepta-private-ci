//! Neutral canonical digest-only NDU snapshot reference, shared by NDU and neuron.
//!
//! This reference does not contain projection or policy bytes and is never
//! itself evidence of an admitted owner signature or grant.

use codex_hepta_types::{Digest32, Generation, StableId};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSnapshotRefV1 {
    pub scope_id: StableId,
    pub owner_id: StableId,
    pub generation: Generation,
    pub route_fence: u64,
    pub revocation_epoch: u64,
    pub policy_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub projection_head_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduSnapshotRefErrorV1 {
    InvalidFence,
    EmptyDigest,
    Encoding,
}

impl NduSnapshotRefV1 {
    pub fn validate(&self) -> Result<(), NduSnapshotRefErrorV1> {
        if self.route_fence == 0 || self.revocation_epoch == 0 {
            return Err(NduSnapshotRefErrorV1::InvalidFence);
        }
        if self.policy_digest.is_zero()
            || self.snapshot_digest.is_zero()
            || self.projection_head_digest.is_zero()
        {
            return Err(NduSnapshotRefErrorV1::EmptyDigest);
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Result<Digest32, NduSnapshotRefErrorV1> {
        self.validate()?;
        let mut bytes = b"hepta.ndu.snapshot-ref.v1".to_vec();
        push_id(&mut bytes, &self.scope_id)?;
        push_id(&mut bytes, &self.owner_id)?;
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.route_fence.to_be_bytes());
        bytes.extend_from_slice(&self.revocation_epoch.to_be_bytes());
        for digest in [
            self.policy_digest,
            self.snapshot_digest,
            self.projection_head_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), NduSnapshotRefErrorV1> {
    let value = id.as_str().as_bytes();
    let size = u32::try_from(value.len()).map_err(|_| NduSnapshotRefErrorV1::Encoding)?;
    bytes.extend_from_slice(&size.to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

#[cfg(test)]
#[path = "ndu_snapshot_ref_tests.rs"]
mod tests;

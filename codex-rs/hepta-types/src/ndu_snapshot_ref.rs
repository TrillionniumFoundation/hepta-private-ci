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
mod tests {
    use super::*;

    fn sample() -> NduSnapshotRefV1 {
        NduSnapshotRefV1 {
            scope_id: StableId::new("subject").unwrap(),
            owner_id: StableId::new("ndu-owner").unwrap(),
            generation: Generation::new(7).unwrap(),
            route_fence: 9,
            revocation_epoch: 11,
            policy_digest: Digest32::of_bytes(b"policy"),
            snapshot_digest: Digest32::of_bytes(b"snapshot"),
            projection_head_digest: Digest32::of_bytes(b"head"),
        }
    }

    #[test]
    fn every_binding_dimension_changes_digest() {
        let initial = sample();
        let original = initial.semantic_digest().unwrap();
        let mut tampered = initial.clone();
        tampered.scope_id = StableId::new("other").unwrap();
        assert_ne!(tampered.semantic_digest().unwrap(), original);
        tampered = initial.clone();
        tampered.route_fence += 1;
        assert_ne!(tampered.semantic_digest().unwrap(), original);
        tampered = initial.clone();
        tampered.revocation_epoch += 1;
        assert_ne!(tampered.semantic_digest().unwrap(), original);
        tampered = initial.clone();
        tampered.projection_head_digest = Digest32::of_bytes(b"new-head");
        assert_ne!(tampered.semantic_digest().unwrap(), original);
    }

    #[test]
    fn refuses_missing_projection_or_fence() {
        let mut value = sample();
        value.route_fence = 0;
        assert_eq!(value.semantic_digest(), Err(NduSnapshotRefErrorV1::InvalidFence));
        value = sample();
        value.projection_head_digest = Digest32::ZERO;
        assert_eq!(value.semantic_digest(), Err(NduSnapshotRefErrorV1::EmptyDigest));
    }
}

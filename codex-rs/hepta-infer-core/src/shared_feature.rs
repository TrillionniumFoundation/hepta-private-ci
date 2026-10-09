//! Immutable, reference-counted Q24 neuron feature payload.
//!
//! A buffer is validated and digested once. Clones share the allocation and
//! cannot mutate it. The digest is byte-for-byte compatible with the existing
//! neuron.runtime V1 canonical input-feature digest; no golden vectors change.

use std::sync::Arc;

use codex_hepta_types::Digest32;

pub const MAX_SHARED_FEATURES: usize = 512;
const Q24: i64 = 1 << 24;
const FEATURE_LIMIT_Q24: i64 = 8 * Q24;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SharedFeatureErrorV1 {
    Width,
    OutOfRange,
    DigestMismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedFeatureBufferV1 {
    values: Arc<[i64]>,
    digest: Digest32,
}

impl SharedFeatureBufferV1 {
    pub fn from_vec(values: Vec<i64>) -> Result<Self, SharedFeatureErrorV1> {
        Self::from_arc(Arc::from(values))
    }

    pub fn from_arc(values: Arc<[i64]>) -> Result<Self, SharedFeatureErrorV1> {
        if values.is_empty() || values.len() > MAX_SHARED_FEATURES {
            return Err(SharedFeatureErrorV1::Width);
        }
        if values.iter().any(|v| !(-FEATURE_LIMIT_Q24..=FEATURE_LIMIT_Q24).contains(v)) {
            return Err(SharedFeatureErrorV1::OutOfRange);
        }
        let digest = canonical_shared_feature_digest_v1(&values);
        Ok(Self { values, digest })
    }

    pub fn from_expected_digest(
        values: Arc<[i64]>,
        expected: Digest32,
    ) -> Result<Self, SharedFeatureErrorV1> {
        let buffer = Self::from_arc(values)?;
        if expected.is_zero() || expected != buffer.digest {
            return Err(SharedFeatureErrorV1::DigestMismatch);
        }
        Ok(buffer)
    }

    pub fn as_slice(&self) -> &[i64] {
        &self.values
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn len(&self) -> usize {
        self.values.len()
    }

    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }

    pub fn shares_allocation_with(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.values, &other.values)
    }
}

/// Golden-vector-compatible implementation of
/// hepta-neuron::canonical_feature_vector_digest_v1.
pub fn canonical_shared_feature_digest_v1(values: &[i64]) -> Digest32 {
    let mut bytes = b"hepta.neuron.input-features.q24.v1".to_vec();
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clone_is_shared_and_digest_matches_v1_domain() {
        let original = SharedFeatureBufferV1::from_vec(vec![0, 1 << 24, -(1 << 24)]).unwrap();
        let clone = original.clone();
        assert!(original.shares_allocation_with(&clone));
        assert_eq!(clone.digest(), canonical_shared_feature_digest_v1(original.as_slice()));
        assert_eq!(
            SharedFeatureBufferV1::from_expected_digest(
                Arc::from(vec![0, 1 << 24, -(1 << 24)]),
                original.digest()
            )
            .unwrap()
            .digest(),
            original.digest()
        );
    }

    #[test]
    fn refuses_invalid_and_swapped_payloads() {
        assert_eq!(SharedFeatureBufferV1::from_vec(vec![]), Err(SharedFeatureErrorV1::Width));
        assert_eq!(
            SharedFeatureBufferV1::from_vec(vec![8 * Q24 + 1]),
            Err(SharedFeatureErrorV1::OutOfRange)
        );
        assert_eq!(
            SharedFeatureBufferV1::from_expected_digest(
                Arc::from(vec![0_i64]), Digest32::of_bytes(b"wrong")
            ),
            Err(SharedFeatureErrorV1::DigestMismatch)
        );
    }
}

//! Research-only, immutable token/patch/time evidence for a shared Stem.
//!
//! Unlike the pooled Q24 V2 vector, this retains ordered feature rows. It owns
//! neither physical Encoder execution nor model/Head selection, final-use
//! authorization, inference dispatch, device memory, or external effects.
//! Cache hits do not grant reuse permission: the caller must check current
//! principal, source freshness, revocation and downstream final use separately.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::shared_feature_v2::SharedFeatureIdentityV2;

const MAX_ROWS: usize = 256;
const MAX_WIDTH: usize = 512;
const MAX_COORDINATE: u16 = 8192;
const Q24_LIMIT: i64 = 8 * (1_i64 << 24);
const COORDINATE_WIRE_BYTES: usize = 12;
const MAX_SNAPSHOT_PAYLOAD_BYTES: usize = 2 * 1024 * 1024;
const MAX_CACHE_ENTRIES: usize = 4096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum FeatureModalityV3 {
    Text = 1,
    Image = 2,
    Audio = 3,
    Video = 4,
    Multimodal = 5,
}

/// Canonical spatial/time coordinates of one feature row. Zero is permitted.
/// For text, both spatial coordinates and time must be zero. For image, time
/// must be zero. For audio, both spatial coordinates must be zero.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct FeatureCoordinatesV3 {
    pub x: u16,
    pub y: u16,
    pub time_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureSequenceIdentityV3 {
    /// Includes principal, purpose, generation, authority epoch and COMPLETE
    /// admitted source-input digest, plus Encoder/tokenizer/normalizer/Q profile.
    pub base: SharedFeatureIdentityV2,
    pub modality: FeatureModalityV3,
    /// The exact patch extraction, audio resampling, chunking or truncation.
    pub preprocessing_digest: Digest32,
    /// Identity of the modality adapter; may denote an identity adapter.
    pub adapter_digest: Digest32,
}

impl FeatureSequenceIdentityV3 {
    pub fn digest(&self) -> Result<Digest32, SequenceFeatureErrorV3> {
        if self.preprocessing_digest.is_zero() || self.adapter_digest.is_zero() {
            return Err(SequenceFeatureErrorV3::InvalidIdentity);
        }
        let base = self
            .base
            .digest()
            .map_err(|_| SequenceFeatureErrorV3::InvalidIdentity)?;
        let mut bytes = b"hepta.infer.sequence-feature-identity.v3\0".to_vec();
        bytes.extend_from_slice(base.as_array());
        bytes.push(self.modality as u8);
        bytes.extend_from_slice(self.preprocessing_digest.as_array());
        bytes.extend_from_slice(self.adapter_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SequenceFeatureErrorV3 {
    InvalidIdentity,
    InvalidShape,
    InvalidMask,
    InvalidCoordinate,
    InvalidValue,
    Expired,
    CapacityExceeded,
    ConflictingSnapshot,
    ContentMismatch,
    Overflow,
}

impl fmt::Display for SequenceFeatureErrorV3 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for SequenceFeatureErrorV3 {}

/// One frozen, content-addressed sequence. All arrays are owned immutable Arc
/// slices; clones and cache borrowers cannot alter another Cell's evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ImmutableFeatureSequenceV3 {
    identity: FeatureSequenceIdentityV3,
    rows: usize,
    width: usize,
    values_q24: Arc<[i64]>,
    mask: Arc<[u8]>,
    coordinates: Arc<[FeatureCoordinatesV3]>,
    expires_at_ms: u64,
    content_digest: Digest32,
    payload_bytes: usize,
}

impl ImmutableFeatureSequenceV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn build(
        identity: FeatureSequenceIdentityV3,
        expires_at_ms: u64,
        rows: usize,
        width: usize,
        values_q24: Arc<[i64]>,
        mask: Arc<[u8]>,
        coordinates: Arc<[FeatureCoordinatesV3]>,
    ) -> Result<Self, SequenceFeatureErrorV3> {
        identity.digest()?;
        if expires_at_ms == 0 {
            return Err(SequenceFeatureErrorV3::Expired);
        }
        if rows == 0 || rows > MAX_ROWS || width == 0 || width > MAX_WIDTH {
            return Err(SequenceFeatureErrorV3::InvalidShape);
        }
        let cells = rows
            .checked_mul(width)
            .ok_or(SequenceFeatureErrorV3::Overflow)?;
        if values_q24.len() != cells || mask.len() != rows || coordinates.len() != rows {
            return Err(SequenceFeatureErrorV3::InvalidShape);
        }
        if !mask.contains(&1) || mask.iter().any(|value| *value > 1) {
            return Err(SequenceFeatureErrorV3::InvalidMask);
        }
        let mut previous_time = None;
        for row in 0..rows {
            let vector = &values_q24[row * width..(row + 1) * width];
            if vector
                .iter()
                .any(|value| !(-Q24_LIMIT..=Q24_LIMIT).contains(value))
            {
                return Err(SequenceFeatureErrorV3::InvalidValue);
            }
            let coord = coordinates[row];
            if mask[row] == 0 {
                if coord != FeatureCoordinatesV3::default() || vector.iter().any(|v| *v != 0) {
                    return Err(SequenceFeatureErrorV3::InvalidMask);
                }
                continue;
            }
            if coord.x > MAX_COORDINATE || coord.y > MAX_COORDINATE {
                return Err(SequenceFeatureErrorV3::InvalidCoordinate);
            }
            match identity.modality {
                FeatureModalityV3::Text
                    if coord.x != 0 || coord.y != 0 || coord.time_micros != 0 =>
                {
                    return Err(SequenceFeatureErrorV3::InvalidCoordinate);
                }
                FeatureModalityV3::Image if coord.time_micros != 0 => {
                    return Err(SequenceFeatureErrorV3::InvalidCoordinate);
                }
                FeatureModalityV3::Audio if coord.x != 0 || coord.y != 0 => {
                    return Err(SequenceFeatureErrorV3::InvalidCoordinate);
                }
                _ => {}
            }
            if matches!(
                identity.modality,
                FeatureModalityV3::Audio | FeatureModalityV3::Video | FeatureModalityV3::Multimodal
            ) {
                if previous_time.is_some_and(|previous| coord.time_micros < previous) {
                    return Err(SequenceFeatureErrorV3::InvalidCoordinate);
                }
                previous_time = Some(coord.time_micros);
            }
        }
        let payload_bytes = cells
            .checked_mul(std::mem::size_of::<i64>())
            .and_then(|bytes| bytes.checked_add(rows))
            .and_then(|bytes| bytes.checked_add(rows * COORDINATE_WIRE_BYTES))
            .ok_or(SequenceFeatureErrorV3::Overflow)?;
        if payload_bytes > MAX_SNAPSHOT_PAYLOAD_BYTES {
            return Err(SequenceFeatureErrorV3::CapacityExceeded);
        }
        let mut bytes = b"hepta.infer.sequence-feature-content.v3\0".to_vec();
        bytes.extend_from_slice(identity.digest()?.as_array());
        bytes.extend_from_slice(&(rows as u64).to_be_bytes());
        bytes.extend_from_slice(&(width as u64).to_be_bytes());
        for value in values_q24.iter() {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&mask);
        for coordinate in coordinates.iter() {
            bytes.extend_from_slice(&coordinate.x.to_be_bytes());
            bytes.extend_from_slice(&coordinate.y.to_be_bytes());
            bytes.extend_from_slice(&coordinate.time_micros.to_be_bytes());
        }
        Ok(Self {
            identity,
            rows,
            width,
            values_q24,
            mask,
            coordinates,
            expires_at_ms,
            content_digest: Digest32::of_bytes(&bytes),
            payload_bytes,
        })
    }

    #[must_use]
    pub fn identity(&self) -> &FeatureSequenceIdentityV3 {
        &self.identity
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        self.content_digest
    }

    #[must_use]
    pub fn shape(&self) -> (usize, usize) {
        (self.rows, self.width)
    }

    #[must_use]
    pub fn payload_bytes(&self) -> usize {
        self.payload_bytes
    }

    #[must_use]
    pub fn expires_at_ms(&self) -> u64 {
        self.expires_at_ms
    }

    /// Row-major frozen Q24 tensor. No raw model input or mutable Cell state.
    #[must_use]
    pub fn values_q24(&self) -> &[i64] {
        &self.values_q24
    }

    #[must_use]
    pub fn mask(&self) -> &[u8] {
        &self.mask
    }

    #[must_use]
    pub fn coordinates(&self) -> &[FeatureCoordinatesV3] {
        &self.coordinates
    }
}

/// Data-only cache. Payload bytes are a canonical logical accounting measure,
/// not RSS, GPU memory, or a measured physical Encoder forward count.
#[derive(Debug)]
pub struct SequenceFeatureCacheV3 {
    maximum_entries: usize,
    maximum_payload_bytes: usize,
    resident_payload_bytes: usize,
    snapshots: BTreeMap<String, Arc<ImmutableFeatureSequenceV3>>,
}

impl SequenceFeatureCacheV3 {
    pub fn new(
        maximum_entries: usize,
        maximum_payload_bytes: usize,
    ) -> Result<Self, SequenceFeatureErrorV3> {
        if maximum_entries == 0 || maximum_entries > MAX_CACHE_ENTRIES || maximum_payload_bytes == 0
        {
            return Err(SequenceFeatureErrorV3::CapacityExceeded);
        }
        Ok(Self {
            maximum_entries,
            maximum_payload_bytes,
            resident_payload_bytes: 0,
            snapshots: BTreeMap::new(),
        })
    }

    pub fn insert(
        &mut self,
        now_ms: u64,
        snapshot: ImmutableFeatureSequenceV3,
    ) -> Result<Arc<ImmutableFeatureSequenceV3>, SequenceFeatureErrorV3> {
        let key = snapshot.identity.digest()?.to_string();
        if now_ms >= snapshot.expires_at_ms {
            return Err(SequenceFeatureErrorV3::Expired);
        }
        if self
            .snapshots
            .get(&key)
            .is_some_and(|old| now_ms >= old.expires_at_ms)
        {
            self.purge_expired(now_ms);
        }
        if let Some(old) = self.snapshots.get(&key) {
            if old.as_ref() == &snapshot {
                return Ok(Arc::clone(old));
            }
            return Err(SequenceFeatureErrorV3::ConflictingSnapshot);
        }
        let mut next = self
            .resident_payload_bytes
            .checked_add(snapshot.payload_bytes)
            .ok_or(SequenceFeatureErrorV3::Overflow)?;
        if self.snapshots.len() >= self.maximum_entries || next > self.maximum_payload_bytes {
            self.purge_expired(now_ms);
            next = self
                .resident_payload_bytes
                .checked_add(snapshot.payload_bytes)
                .ok_or(SequenceFeatureErrorV3::Overflow)?;
        }
        if self.snapshots.len() >= self.maximum_entries || next > self.maximum_payload_bytes {
            return Err(SequenceFeatureErrorV3::CapacityExceeded);
        }
        let item = Arc::new(snapshot);
        self.snapshots.insert(key, Arc::clone(&item));
        self.resident_payload_bytes = next;
        Ok(item)
    }

    /// The expected digest comes from a separately admitted source receipt.
    /// It prevents stale consumers from accidentally resolving a new snapshot
    /// with the same identity after expiry and re-admission.
    pub fn get(
        &self,
        now_ms: u64,
        identity: &FeatureSequenceIdentityV3,
        expected_content_digest: Digest32,
    ) -> Result<Option<Arc<ImmutableFeatureSequenceV3>>, SequenceFeatureErrorV3> {
        if expected_content_digest.is_zero() {
            return Err(SequenceFeatureErrorV3::ContentMismatch);
        }
        let key = identity.digest()?.to_string();
        let Some(item) = self.snapshots.get(&key) else {
            return Ok(None);
        };
        if item.identity != *identity || now_ms >= item.expires_at_ms {
            return Ok(None);
        }
        if item.content_digest != expected_content_digest {
            return Err(SequenceFeatureErrorV3::ContentMismatch);
        }
        Ok(Some(Arc::clone(item)))
    }

    pub fn revoke_before_epoch(
        &mut self,
        principal: &StableId,
        purpose: &StableId,
        minimum_epoch: u64,
    ) -> usize {
        self.retain(|item| {
            item.identity.base.principal_id != *principal
                || item.identity.base.purpose_id != *purpose
                || item.identity.base.authority_epoch >= minimum_epoch
        })
    }

    pub fn invalidate_other_generations(
        &mut self,
        principal: &StableId,
        purpose: &StableId,
        current_generation: Generation,
    ) -> usize {
        self.retain(|item| {
            item.identity.base.principal_id != *principal
                || item.identity.base.purpose_id != *purpose
                || item.identity.base.generation == current_generation
        })
    }

    pub fn purge_expired(&mut self, now_ms: u64) -> usize {
        self.retain(|item| now_ms < item.expires_at_ms)
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.snapshots.len()
    }

    #[must_use]
    pub fn resident_payload_bytes(&self) -> usize {
        self.resident_payload_bytes
    }

    fn retain(&mut self, keep: impl Fn(&ImmutableFeatureSequenceV3) -> bool) -> usize {
        let before = self.snapshots.len();
        self.snapshots.retain(|_, item| keep(item));
        self.resident_payload_bytes = self.snapshots.values().map(|item| item.payload_bytes).sum();
        before - self.snapshots.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity(principal: &str, modality: FeatureModalityV3) -> FeatureSequenceIdentityV3 {
        FeatureSequenceIdentityV3 {
            base: SharedFeatureIdentityV2 {
                principal_id: StableId::new(principal.to_owned()).expect("principal"),
                purpose_id: StableId::new("reasoning".to_owned()).expect("purpose"),
                generation: Generation::new(5).expect("generation"),
                authority_epoch: 2,
                encoder_digest: Digest32::of_bytes(b"frozen encoder"),
                tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
                normalizer_digest: Digest32::of_bytes(b"normalizer"),
                quantization_digest: Digest32::of_bytes(b"q24"),
                input_digest: Digest32::of_bytes(b"complete question, alternatives and context"),
            },
            modality,
            preprocessing_digest: Digest32::of_bytes(b"truncation and patch policy"),
            adapter_digest: Digest32::of_bytes(b"adapter"),
        }
    }

    fn make(id: FeatureSequenceIdentityV3) -> ImmutableFeatureSequenceV3 {
        ImmutableFeatureSequenceV3::build(
            id,
            100,
            2,
            2,
            Arc::from([1_i64, 2, 3, 4]),
            Arc::from([1_u8, 1]),
            Arc::from([FeatureCoordinatesV3::default(); 2]),
        )
        .expect("snapshot")
    }

    #[test]
    fn immutable_shared_rows_are_reused_in_scope_only() {
        let mut cache = SequenceFeatureCacheV3::new(2, 100).expect("cache");
        let id = identity("principal-a", FeatureModalityV3::Text);
        let item = cache.insert(10, make(id.clone())).expect("insert");
        let hit = cache
            .get(20, &id, item.content_digest())
            .expect("get")
            .expect("hit");
        assert!(Arc::ptr_eq(&hit, &item));
        assert_eq!(item.shape(), (2, 2));
        assert_eq!(item.payload_bytes(), 2 * 2 * 8 + 2 + 2 * 12);
        assert_eq!(cache.resident_payload_bytes(), item.payload_bytes());
        assert!(
            cache
                .get(
                    20,
                    &identity("principal-b", FeatureModalityV3::Text),
                    item.content_digest()
                )
                .expect("get")
                .is_none()
        );
        assert_eq!(item.values_q24(), &[1, 2, 3, 4]);
    }

    #[test]
    fn tokenizer_adapter_modality_and_source_bind_identity() {
        let a = identity("p", FeatureModalityV3::Text);
        let mut b = a.clone();
        b.modality = FeatureModalityV3::Image;
        assert_ne!(a.digest().expect("a"), b.digest().expect("b"));
        b = a.clone();
        b.adapter_digest = Digest32::of_bytes(b"different adapter");
        assert_ne!(a.digest().expect("a"), b.digest().expect("b"));
        b = a.clone();
        b.base.input_digest = Digest32::of_bytes(b"changed answer choices");
        assert_ne!(a.digest().expect("a"), b.digest().expect("b"));
        b = a.clone();
        b.preprocessing_digest = Digest32::ZERO;
        assert_eq!(b.digest(), Err(SequenceFeatureErrorV3::InvalidIdentity));
    }

    #[test]
    fn reordered_values_or_coordinates_change_content_digest() {
        let id = identity("p", FeatureModalityV3::Video);
        let base = make(id.clone());
        let changed = ImmutableFeatureSequenceV3::build(
            id.clone(),
            100,
            2,
            2,
            Arc::from([3_i64, 4, 1, 2]),
            Arc::from([1_u8, 1]),
            Arc::from([FeatureCoordinatesV3::default(); 2]),
        )
        .expect("reordered");
        assert_ne!(base.content_digest(), changed.content_digest());
        let positioned = ImmutableFeatureSequenceV3::build(
            id,
            100,
            2,
            2,
            Arc::from([1_i64, 2, 3, 4]),
            Arc::from([1_u8, 1]),
            Arc::from([
                FeatureCoordinatesV3 {
                    x: 1,
                    y: 0,
                    time_micros: 7,
                },
                FeatureCoordinatesV3 {
                    x: 2,
                    y: 0,
                    time_micros: 9,
                },
            ]),
        )
        .expect("coordinates");
        assert_ne!(base.content_digest(), positioned.content_digest());
    }

    #[test]
    fn malformed_padding_and_temporal_regression_reject_before_caching() {
        let id = identity("p", FeatureModalityV3::Audio);
        let bad_pad = ImmutableFeatureSequenceV3::build(
            id.clone(),
            100,
            2,
            1,
            Arc::from([1_i64, 7]),
            Arc::from([1_u8, 0]),
            Arc::from([FeatureCoordinatesV3::default(); 2]),
        );
        assert_eq!(bad_pad, Err(SequenceFeatureErrorV3::InvalidMask));
        let regression = ImmutableFeatureSequenceV3::build(
            id,
            100,
            2,
            1,
            Arc::from([1_i64, 2]),
            Arc::from([1_u8, 1]),
            Arc::from([
                FeatureCoordinatesV3 {
                    x: 0,
                    y: 0,
                    time_micros: 8,
                },
                FeatureCoordinatesV3 {
                    x: 0,
                    y: 0,
                    time_micros: 7,
                },
            ]),
        );
        assert_eq!(regression, Err(SequenceFeatureErrorV3::InvalidCoordinate));
    }

    #[test]
    fn stale_expected_hash_cannot_resolve_replaced_expired_evidence() {
        let mut cache = SequenceFeatureCacheV3::new(1, 100).expect("cache");
        let id = identity("p", FeatureModalityV3::Text);
        let first = cache.insert(1, make(id.clone())).expect("first");
        assert_eq!(
            cache.insert(
                2,
                ImmutableFeatureSequenceV3::build(
                    id.clone(),
                    150,
                    1,
                    1,
                    Arc::from([2_i64]),
                    Arc::from([1_u8]),
                    Arc::from([FeatureCoordinatesV3::default()]),
                )
                .expect("other")
            ),
            Err(SequenceFeatureErrorV3::ConflictingSnapshot)
        );
        let second = cache
            .insert(
                100,
                ImmutableFeatureSequenceV3::build(
                    id.clone(),
                    200,
                    1,
                    1,
                    Arc::from([2_i64]),
                    Arc::from([1_u8]),
                    Arc::from([FeatureCoordinatesV3::default()]),
                )
                .expect("replacement"),
            )
            .expect("insert");
        assert_eq!(
            cache.get(101, &id, first.content_digest()),
            Err(SequenceFeatureErrorV3::ContentMismatch)
        );
        assert!(
            cache
                .get(101, &id, second.content_digest())
                .expect("get")
                .is_some()
        );
        assert_eq!(first.values_q24(), &[1, 2, 3, 4]);
    }

    #[test]
    fn epoch_fence_and_capacity_cannot_evict_live_foreign_scope() {
        let mut cache = SequenceFeatureCacheV3::new(1, 100).expect("cache");
        let a = identity("a", FeatureModalityV3::Text);
        let b = identity("b", FeatureModalityV3::Text);
        cache.insert(1, make(a.clone())).expect("a");
        assert_eq!(
            cache.insert(1, make(b)),
            Err(SequenceFeatureErrorV3::CapacityExceeded)
        );
        let p = StableId::new("a".to_owned()).expect("p");
        let purpose = StableId::new("reasoning".to_owned()).expect("purpose");
        assert_eq!(cache.revoke_before_epoch(&p, &purpose, 3), 1);
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.resident_payload_bytes(), 0);
    }
}

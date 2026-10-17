//! Bounded, scope-fenced, immutable feature snapshots for many logical Neuron Cells.
//!
//! This is a local, non-authorizing cache and a typed identity contract. The caller
//! must first verify source freshness, privacy/reuse eligibility, reservation and
//! the final-use grant. No cache hit carries or creates execution authority.
//! A feature computed from question+options+state is NOT interchangeable with a
//! state-only embedding; the exact admitted input digest belongs in the key.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Weak;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_DIMENSION: usize = 512;
const Q24_ABSOLUTE_LIMIT: i64 = 8 * (1 << 24);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedFeatureIdentityV2 {
    pub principal_id: StableId,
    pub purpose_id: StableId,
    /// Caller-supplied isolation boundary; the owner must attest it at final use.
    pub scope_id: StableId,
    pub generation: Generation,
    pub authority_epoch: u64,
    pub encoder_digest: Digest32,
    pub tokenizer_digest: Digest32,
    /// Do not alias the preprocessor revision with the normalizer revision.
    pub preprocessor_digest: Digest32,
    pub normalizer_digest: Digest32,
    pub quantization_digest: Digest32,
    /// Source frontier changes invalidate even byte-identical input digests.
    pub source_frontier_digest: Digest32,
    /// Hash of the complete, admitted model input (not an unconditioned state).
    pub input_digest: Digest32,
}

impl SharedFeatureIdentityV2 {
    pub fn digest(&self) -> Result<Digest32, SharedFeatureErrorV2> {
        if self.authority_epoch == 0
            || [
                self.encoder_digest,
                self.tokenizer_digest,
                self.preprocessor_digest,
                self.normalizer_digest,
                self.quantization_digest,
                self.source_frontier_digest,
                self.input_digest,
            ]
            .iter()
            .any(|digest| digest.is_zero())
        {
            return Err(SharedFeatureErrorV2::InvalidIdentity);
        }
        let mut bytes = b"hepta.infer.shared-feature-identity.v2".to_vec();
        for id in [&self.principal_id, &self.purpose_id, &self.scope_id] {
            let raw = id.as_str().as_bytes();
            bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        for digest in [
            self.encoder_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
            self.normalizer_digest,
            self.quantization_digest,
            self.source_frontier_digest,
            self.input_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ImmutableFeatureSnapshotV2 {
    pub identity: SharedFeatureIdentityV2,
    pub content_digest: Digest32,
    pub expires_at_ms: u64,
    /// Immutable, shared Q24 buffer. Never contains writable Cell state or grants.
    pub features_q24: Arc<[i64]>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SharedFeatureErrorV2 {
    InvalidIdentity,
    InvalidFeature,
    Expired,
    CapacityExceeded,
    ConflictingSnapshot,
    Overflow,
}

impl fmt::Display for SharedFeatureErrorV2 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl StdError for SharedFeatureErrorV2 {}

/// The identity + full bytes are checked even when a digest key matches.
#[derive(Debug)]
pub struct SharedFeatureCacheV2 {
    maximum_entries: usize,
    maximum_bytes: usize,
    // Counts cached buffers AND retired buffers held by external Arc readers.
    resident_bytes: usize,
    snapshots: BTreeMap<String, Arc<ImmutableFeatureSnapshotV2>>,
    // Track both the snapshot and its underlying Arc<[i64]> allocation:
    // callers may retain either independently after cache eviction.
    retired: Vec<(Weak<ImmutableFeatureSnapshotV2>, Weak<[i64]>, usize)>,
}

impl SharedFeatureCacheV2 {
    pub fn new(maximum_entries: usize, maximum_bytes: usize) -> Result<Self, SharedFeatureErrorV2> {
        if maximum_entries == 0 || maximum_bytes == 0 {
            return Err(SharedFeatureErrorV2::CapacityExceeded);
        }
        Ok(Self {
            maximum_entries,
            maximum_bytes,
            resident_bytes: 0,
            snapshots: BTreeMap::new(),
            retired: Vec::new(),
        })
    }

    pub fn len(&self) -> usize {
        self.snapshots.len()
    }

    pub fn is_empty(&self) -> bool {
        self.snapshots.is_empty()
    }

    /// Conservative cache-owner allocation floor. Revoked/expired snapshots
    /// still held by live readers count until a subsequent reclamation pass.
    /// This is not a measured OS RSS or accelerator allocation.
    pub fn resident_bytes(&self) -> usize {
        self.resident_bytes
    }

    pub fn insert(
        &mut self,
        now_ms: u64,
        identity: SharedFeatureIdentityV2,
        expires_at_ms: u64,
        features_q24: Arc<[i64]>,
    ) -> Result<Arc<ImmutableFeatureSnapshotV2>, SharedFeatureErrorV2> {
        let identity_digest = identity.digest()?.to_string();
        if expires_at_ms <= now_ms {
            return Err(SharedFeatureErrorV2::Expired);
        }
        if features_q24.is_empty()
            || features_q24.len() > MAX_DIMENSION
            || features_q24
                .iter()
                .any(|v| !(-Q24_ABSOLUTE_LIMIT..=Q24_ABSOLUTE_LIMIT).contains(v))
        {
            return Err(SharedFeatureErrorV2::InvalidFeature);
        }
        let content_digest = feature_content_digest_v2(&features_q24);
        self.reclaim_retired();
        // An expired key may be re-admitted, but a live immutable identity
        // must never be silently replaced. Old Arc readers remain immutable
        // and still require independent final-use checks.
        if self
            .snapshots
            .get(&identity_digest)
            .is_some_and(|existing| now_ms >= existing.expires_at_ms)
        {
            self.purge_expired(now_ms);
        }
        if let Some(existing) = self.snapshots.get(&identity_digest) {
            if existing.identity == identity
                && existing.expires_at_ms == expires_at_ms
                && existing.content_digest == content_digest
                && existing.features_q24.as_ref() == features_q24.as_ref()
            {
                return Ok(Arc::clone(existing));
            }
            // No silent replacement of an immutable feature under the same identity.
            return Err(SharedFeatureErrorV2::ConflictingSnapshot);
        }
        let bytes = features_q24
            .len()
            .checked_mul(std::mem::size_of::<i64>())
            .ok_or(SharedFeatureErrorV2::Overflow)?;
        let mut next_bytes = self
            .resident_bytes
            .checked_add(bytes)
            .ok_or(SharedFeatureErrorV2::Overflow)?;
        // Reclaim expired capacity only when needed. Live entries are never
        // evicted to satisfy a different Cell or principal.
        if self.snapshots.len().saturating_add(self.retired.len()) >= self.maximum_entries
            || next_bytes > self.maximum_bytes
        {
            self.purge_expired(now_ms);
            next_bytes = self
                .resident_bytes
                .checked_add(bytes)
                .ok_or(SharedFeatureErrorV2::Overflow)?;
        }
        if self.snapshots.len().saturating_add(self.retired.len()) >= self.maximum_entries
            || next_bytes > self.maximum_bytes
        {
            return Err(SharedFeatureErrorV2::CapacityExceeded);
        }
        let snapshot = Arc::new(ImmutableFeatureSnapshotV2 {
            identity,
            content_digest,
            expires_at_ms,
            features_q24,
        });
        self.snapshots
            .insert(identity_digest, Arc::clone(&snapshot));
        self.resident_bytes = next_bytes;
        Ok(snapshot)
    }

    pub fn get(
        &self,
        now_ms: u64,
        identity: &SharedFeatureIdentityV2,
    ) -> Result<Option<Arc<ImmutableFeatureSnapshotV2>>, SharedFeatureErrorV2> {
        let key = identity.digest()?.to_string();
        let Some(existing) = self.snapshots.get(&key) else {
            return Ok(None);
        };
        if existing.identity != *identity || now_ms >= existing.expires_at_ms {
            return Ok(None);
        }
        Ok(Some(Arc::clone(existing)))
    }

    /// Called only by the cache owner after an independently verified scope fence.
    /// Old entries are removed; existing Arc readers remain immutable and still
    /// need their own final-use admission before any subsequent physical action.
    pub fn revoke_before_epoch(
        &mut self,
        principal_id: &StableId,
        purpose_id: &StableId,
        minimum_epoch: u64,
    ) -> usize {
        self.retain(|snapshot| {
            snapshot.identity.principal_id != *principal_id
                || snapshot.identity.purpose_id != *purpose_id
                || snapshot.identity.authority_epoch >= minimum_epoch
        })
    }

    pub fn invalidate_other_generations(
        &mut self,
        principal_id: &StableId,
        purpose_id: &StableId,
        current_generation: Generation,
    ) -> usize {
        self.retain(|snapshot| {
            snapshot.identity.principal_id != *principal_id
                || snapshot.identity.purpose_id != *purpose_id
                || snapshot.identity.generation == current_generation
        })
    }

    pub fn purge_expired(&mut self, now_ms: u64) -> usize {
        self.retain(|snapshot| now_ms < snapshot.expires_at_ms)
    }

    fn retain(&mut self, keep: impl Fn(&ImmutableFeatureSnapshotV2) -> bool) -> usize {
        let old_count = self.snapshots.len();
        let retired = &mut self.retired;
        self.snapshots.retain(|_, snapshot| {
            if keep(snapshot) {
                return true;
            }
            // Removal from the map does not physically release an Arc held by
            // another Cell. A weak tombstone retains its quota charge without
            // keeping the actual snapshot alive.
            if Arc::strong_count(snapshot) > 1 || Arc::strong_count(&snapshot.features_q24) > 1 {
                retired.push((
                    Arc::downgrade(snapshot),
                    Arc::downgrade(&snapshot.features_q24),
                    snapshot.features_q24.len().saturating_mul(8),
                ));
            }
            false
        });
        self.reclaim_retired();
        old_count - self.snapshots.len()
    }

    fn reclaim_retired(&mut self) {
        self.retired.retain(|(snapshot, features, _)| {
            snapshot.strong_count() > 0 || features.strong_count() > 0
        });
        let cached_bytes = self.snapshots.values().fold(0_usize, |total, snapshot| {
            total.saturating_add(snapshot.features_q24.len().saturating_mul(8))
        });
        self.resident_bytes = self
            .retired
            .iter()
            .fold(cached_bytes, |total, (_, _, bytes)| total.saturating_add(*bytes));
    }
}

pub fn feature_content_digest_v2(features_q24: &[i64]) -> Digest32 {
    let mut bytes = b"hepta.infer.shared-feature-content.v2".to_vec();
    bytes.extend_from_slice(&(features_q24.len() as u64).to_be_bytes());
    for value in features_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity(principal: &str, purpose: &str, epoch: u64) -> SharedFeatureIdentityV2 {
        SharedFeatureIdentityV2 {
            principal_id: StableId::new(principal.to_string()).expect("principal"),
            purpose_id: StableId::new(purpose.to_string()).expect("purpose"),
            scope_id: StableId::new("scope.decision").expect("scope"),
            generation: Generation::new(5).expect("generation"),
            authority_epoch: epoch,
            encoder_digest: Digest32::of_bytes(b"encoder"),
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            preprocessor_digest: Digest32::of_bytes(b"preprocessor"),
            normalizer_digest: Digest32::of_bytes(b"normalizer"),
            quantization_digest: Digest32::of_bytes(b"quantization"),
            source_frontier_digest: Digest32::of_bytes(b"source frontier revision"),
            input_digest: Digest32::of_bytes(b"complete question, options and state"),
        }
    }

    #[test]
    fn shared_immutable_buffer_is_reused_without_scope_alias() {
        let mut cache = SharedFeatureCacheV2::new(2, 128).expect("cache");
        let id = identity("principal.a", "purpose.read", 2);
        let frame = cache
            .insert(10, id.clone(), 100, Arc::from([1_i64, 2, 3]))
            .expect("insert");
        let hit = cache.get(20, &id).expect("lookup").expect("present");
        assert!(Arc::ptr_eq(&frame, &hit));
        assert_eq!(cache.resident_bytes(), 24);
        assert!(
            cache
                .get(20, &identity("principal.b", "purpose.read", 2))
                .expect("lookup")
                .is_none()
        );
        assert!(
            cache
                .get(20, &identity("principal.a", "purpose.write", 2))
                .expect("lookup")
                .is_none()
        );
        assert!(
            cache
                .get(20, &identity("principal.a", "purpose.read", 3))
                .expect("lookup")
                .is_none()
        );
        assert!(cache.get(100, &id).expect("lookup").is_none());
    }

    #[test]
    fn never_replace_cached_identity_with_different_bytes_or_expiry() {
        let mut cache = SharedFeatureCacheV2::new(2, 128).expect("cache");
        let id = identity("p", "q", 2);
        let existing = cache
            .insert(10, id.clone(), 100, Arc::from([2_i64, 4]))
            .expect("insert");
        assert!(Arc::ptr_eq(
            &existing,
            &cache
                .insert(10, id.clone(), 100, Arc::from([2_i64, 4]))
                .expect("idempotent")
        ));
        assert_eq!(
            cache.insert(10, id.clone(), 100, Arc::from([2_i64, 5])),
            Err(SharedFeatureErrorV2::ConflictingSnapshot)
        );
        assert_eq!(
            cache.insert(10, id, 110, Arc::from([2_i64, 4])),
            Err(SharedFeatureErrorV2::ConflictingSnapshot)
        );
    }

    #[test]
    fn capacity_bounds_and_q24_validation_fail_closed() {
        let mut cache = SharedFeatureCacheV2::new(1, 16).expect("cache");
        assert_eq!(
            cache.insert(10, identity("p", "q", 2), 11, Arc::from([9_i64 << 24])),
            Err(SharedFeatureErrorV2::InvalidFeature)
        );
        cache
            .insert(10, identity("p", "q", 2), 20, Arc::from([1_i64, 2]))
            .expect("insert");
        assert_eq!(
            cache.insert(10, identity("p2", "q", 2), 20, Arc::from([1_i64])),
            Err(SharedFeatureErrorV2::CapacityExceeded)
        );
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.resident_bytes(), 16);
        assert_eq!(cache.purge_expired(20), 1);
        assert!(cache.is_empty());
        assert_eq!(cache.resident_bytes(), 0);
    }

    #[test]
    fn expired_capacity_is_reclaimed_without_evicting_live_entries() {
        let mut cache = SharedFeatureCacheV2::new(2, 16).expect("cache");
        let old_id = identity("old", "purpose", 2);
        let old_snapshot = cache
            .insert(10, old_id.clone(), 20, Arc::from([1_i64]))
            .expect("old snapshot");
        let live_id = identity("live", "purpose", 2);
        let live_snapshot = cache
            .insert(10, live_id.clone(), 40, Arc::from([2_i64]))
            .expect("live snapshot");
        let new_id = identity("new", "purpose", 2);
        assert_eq!(
            cache.insert(19, new_id.clone(), 40, Arc::from([3_i64])),
            Err(SharedFeatureErrorV2::CapacityExceeded)
        );
        assert_eq!(
            cache.insert(20, new_id.clone(), 40, Arc::from([9_i64 << 24])),
            Err(SharedFeatureErrorV2::InvalidFeature)
        );
        assert_eq!(cache.len(), 2);
        // The old reader still owns physical memory even after the cache
        // expires its map entry. Reject admission rather than undercount it.
        assert_eq!(
            cache.insert(20, new_id.clone(), 40, Arc::from([3_i64])),
            Err(SharedFeatureErrorV2::CapacityExceeded)
        );
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.resident_bytes(), 16);
        assert_eq!(old_snapshot.features_q24.as_ref(), &[1]);
        drop(old_snapshot);
        cache
            .insert(20, new_id.clone(), 40, Arc::from([3_i64]))
            .expect("released expired reader capacity may be reused");
        assert_eq!(cache.len(), 2);
        assert_eq!(cache.resident_bytes(), 16);
        assert!(cache.get(20, &old_id).expect("expired lookup").is_none());
        assert!(cache.get(20, &new_id).expect("new lookup").is_some());
        let live_hit = cache
            .get(20, &live_id)
            .expect("live lookup")
            .expect("present");
        assert!(Arc::ptr_eq(&live_snapshot, &live_hit));
    }

    #[test]
    fn expired_identity_can_be_readmitted_without_mutating_old_readers() {
        let mut cache = SharedFeatureCacheV2::new(1, 16).expect("cache");
        let id = identity("p", "q", 2);
        let original = cache
            .insert(10, id.clone(), 20, Arc::from([1_i64, 2]))
            .expect("original");
        assert_eq!(
            cache.insert(19, id.clone(), 30, Arc::from([3_i64, 4])),
            Err(SharedFeatureErrorV2::ConflictingSnapshot)
        );
        let original_digest = original.content_digest;
        assert_eq!(
            cache.insert(20, id.clone(), 30, Arc::from([3_i64, 4])),
            Err(SharedFeatureErrorV2::CapacityExceeded)
        );
        assert_eq!(original.features_q24.as_ref(), &[1, 2]);
        drop(original);
        let replacement = cache
            .insert(20, id, 30, Arc::from([3_i64, 4]))
            .expect("expired identity may be readmitted after old reader drops");
        assert_ne!(original_digest, replacement.content_digest);
        assert_eq!(replacement.features_q24.as_ref(), &[3, 4]);
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.resident_bytes(), 16);
    }

    #[test]
    fn generation_and_epoch_fences_invalidate_only_target_scope() {
        let mut cache = SharedFeatureCacheV2::new(4, 256).expect("cache");
        for (principal, epoch) in [("p", 2), ("p", 3), ("other", 2)] {
            cache
                .insert(
                    5,
                    identity(principal, "purpose", epoch),
                    100,
                    Arc::from([1_i64]),
                )
                .expect("insert");
        }
        let p = StableId::new("p".to_string()).expect("p");
        let purpose = StableId::new("purpose".to_string()).expect("purpose");
        assert_eq!(cache.revoke_before_epoch(&p, &purpose, 3), 1);
        assert!(
            cache
                .get(6, &identity("p", "purpose", 2))
                .expect("lookup")
                .is_none()
        );
        assert!(
            cache
                .get(6, &identity("p", "purpose", 3))
                .expect("lookup")
                .is_some()
        );
        assert!(
            cache
                .get(6, &identity("other", "purpose", 2))
                .expect("lookup")
                .is_some()
        );
        assert_eq!(
            cache.invalidate_other_generations(
                &p,
                &purpose,
                Generation::new(8).expect("generation")
            ),
            1
        );
        assert_eq!(cache.len(), 1);
    }

    #[test]
    fn detached_feature_arc_still_consumes_quota_after_snapshot_eviction() {
        let key = identity("old", "purpose", 2);
        let new_key = identity("new", "purpose", 2);
        let mut cache = SharedFeatureCacheV2::new(1, 16).expect("cache");
        let detached: Arc<[i64]> = Arc::from([1_i64, 2]);
        let snapshot = cache
            .insert(1, key, 5, Arc::clone(&detached))
            .expect("insert");
        drop(snapshot);
        assert_eq!(cache.purge_expired(5), 1);
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.resident_bytes(), 16);
        assert_eq!(
            cache.insert(5, new_key.clone(), 20, Arc::from([3_i64, 4])),
            Err(SharedFeatureErrorV2::CapacityExceeded)
        );
        drop(detached);
        cache
            .insert(5, new_key, 20, Arc::from([3_i64, 4]))
            .expect("detached buffer finally freed");
        assert_eq!(cache.resident_bytes(), 16);
    }

    #[test]
    fn feature_digest_binds_shape_order_and_q24_values() {
        assert_ne!(
            feature_content_digest_v2(&[1, 2]),
            feature_content_digest_v2(&[2, 1])
        );
        assert_ne!(
            feature_content_digest_v2(&[1, 2]),
            feature_content_digest_v2(&[1, 2, 0])
        );
        let a = identity("p", "q", 2);
        let mut b = a.clone();
        b.input_digest = Digest32::of_bytes(b"new candidate set");
        assert_ne!(a.digest().expect("a"), b.digest().expect("b"));
    }

    #[test]
    fn four_thousand_ninety_six_logical_readers_share_one_feature_allocation() {
        let key = identity("principal", "purpose", 2);
        let mut cache = SharedFeatureCacheV2::new(1, MAX_DIMENSION * 8).expect("cache");
        let original = cache
            .insert(1, key.clone(), 1000, Arc::from(vec![0_i64; MAX_DIMENSION]))
            .expect("insert");
        let mut readers = Vec::with_capacity(4096);
        for _ in 0..4096 {
            readers.push(
                cache
                    .get(2, &key)
                    .expect("lookup")
                    .expect("resident snapshot"),
            );
        }
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.resident_bytes(), MAX_DIMENSION * 8);
        assert!(
            readers
                .iter()
                .all(|reader| Arc::ptr_eq(&reader.features_q24, &original.features_q24))
        );
    }

    #[test]
    fn isolation_preprocessing_and_source_frontier_each_change_cache_identity() {
        let source = identity("principal", "purpose", 3);
        let mut cache = SharedFeatureCacheV2::new(4, 128).expect("cache");
        cache.insert(1, source.clone(), 100, Arc::from([1_i64 << 24]))
            .expect("insert");
        let mut changed = source.clone();
        changed.scope_id = StableId::new("scope.other").expect("scope");
        assert_ne!(source.digest().expect("source"), changed.digest().expect("changed"));
        assert!(cache.get(2, &changed).expect("lookup").is_none());
        changed = source.clone();
        changed.preprocessor_digest = Digest32::of_bytes(b"different preprocessing");
        assert_ne!(source.digest().expect("source"), changed.digest().expect("changed"));
        assert!(cache.get(2, &changed).expect("lookup").is_none());
        changed = source.clone();
        changed.source_frontier_digest = Digest32::of_bytes(b"new source revision");
        assert_ne!(source.digest().expect("source"), changed.digest().expect("changed"));
        assert!(cache.get(2, &changed).expect("lookup").is_none());
        assert!(cache.get(2, &source).expect("lookup").is_some());
        changed = source.clone();
        changed.preprocessor_digest = Digest32::ZERO;
        assert_eq!(changed.digest(), Err(SharedFeatureErrorV2::InvalidIdentity));
        changed = source;
        changed.source_frontier_digest = Digest32::ZERO;
        assert_eq!(changed.digest(), Err(SharedFeatureErrorV2::InvalidIdentity));
    }
}

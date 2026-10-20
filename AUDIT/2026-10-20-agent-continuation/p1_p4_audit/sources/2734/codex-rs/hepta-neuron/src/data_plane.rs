//! Shared-feature execution data plane for many lightweight neuron heads.
//!
//! `FeatureSnapshotV1` owns one immutable encoder result and every batch item
//! borrows that result through an `Arc`. The reference backend performs the
//! actual deterministic head computation; it is intentionally authority-free
//! and therefore cannot select, promote, release or invoke a provider.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::canonical_feature_vector_digest_v1;

const Q24: i128 = 1_i128 << 24;
const OUTPUT_LIMIT_Q24: i64 = (8 * Q24) as i64;
/// Maximum shape accepted by the existing Neuron wire/runtime request.
///
/// The shared feature fixture can retain a larger hidden vector for an
/// offline backend, but a caller crossing the Neuron wire must opt into this
/// narrower contract explicitly.  Keeping the check here prevents a 4096-wide
/// hidden vector from being mistaken for a wire-compatible request.
pub const NEURON_WIRE_MAX_FEATURES_V1: usize = 512;
pub const NEURON_WIRE_MAX_OUTPUTS_V1: usize = 512;
const MAX_FEATURES: usize = 4_096;
const MAX_OUTPUTS: usize = 64;
const MAX_BATCH_ITEMS: usize = 4_096;
const MAX_MODELS: usize = 4_096;
const MAX_CACHE_ENTRIES: usize = 16_384;
const MAX_RETIRED_IDS: usize = 16_384;
/// A production worker must bound one dispatch to keep queue latency and
/// memory use predictable.  Larger input sets are split into independently
/// digested plans by the caller.
pub const MAX_MICROBATCH_REQUESTS_V1: usize = 256;

/// Identity dimensions that must agree before an encoder result is reused.
///
/// The legacy four-argument [`FeatureSnapshotV1::new`] constructor remains
/// available for callers that only have an encoder and input digest. New
/// callers should use [`FeatureSnapshotIdentityV1::new`] and
/// [`FeatureSnapshotV1::new_with_identity`] so that scope and model lineage
/// cannot be silently mixed in a cache.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct FeatureSnapshotIdentityV1 {
    pub scope: StableId,
    pub workspace: StableId,
    pub purpose: StableId,
    /// Exact question/input realization identity, distinct from the encoded
    /// feature digest so cache provenance remains inspectable.
    pub question: Digest32,
    /// Canonical options/tool configuration identity for the request.
    pub options: Digest32,
    pub source_frontier: Digest32,
    pub model: Digest32,
    pub adapter: Digest32,
    pub tokenizer: Digest32,
    pub normalizer: Digest32,
    pub calibration: Digest32,
}

impl FeatureSnapshotIdentityV1 {
    pub fn new(
        scope: StableId,
        workspace: StableId,
        purpose: StableId,
        source_frontier: Digest32,
        model: Digest32,
        adapter: Digest32,
        tokenizer: Digest32,
        normalizer: Digest32,
        calibration: Digest32,
    ) -> Result<Self, DataPlaneError> {
        Self::new_with_question_options(
            scope,
            workspace,
            purpose,
            tagged_digest(b"legacy.question", source_frontier, model),
            tagged_digest(b"legacy.options", source_frontier, adapter),
            source_frontier,
            model,
            adapter,
            tokenizer,
            normalizer,
            calibration,
        )
    }

    /// Builds a fully explicit cache identity, including the question and
    /// options that produced the shared feature request.
    pub fn new_with_question_options(
        scope: StableId,
        workspace: StableId,
        purpose: StableId,
        question: Digest32,
        options: Digest32,
        source_frontier: Digest32,
        model: Digest32,
        adapter: Digest32,
        tokenizer: Digest32,
        normalizer: Digest32,
        calibration: Digest32,
    ) -> Result<Self, DataPlaneError> {
        let identity = Self {
            scope,
            workspace,
            purpose,
            question,
            options,
            source_frontier,
            model,
            adapter,
            tokenizer,
            normalizer,
            calibration,
        };
        identity.validate()?;
        Ok(identity)
    }

    fn validate(&self) -> Result<(), DataPlaneError> {
        for (field, digest) in [
            ("question", self.question),
            ("options", self.options),
            ("source frontier", self.source_frontier),
            ("model", self.model),
            ("adapter", self.adapter),
            ("tokenizer", self.tokenizer),
            ("normalizer", self.normalizer),
            ("calibration", self.calibration),
        ] {
            validate_digest(digest, field)?;
        }
        Ok(())
    }

    /// Deterministic identity used by the retained legacy constructor.
    fn legacy(encoder_digest: Digest32, input_digest: Digest32) -> Result<Self, DataPlaneError> {
        let stable =
            |value: &str| StableId::new(value).map_err(|_| DataPlaneError::InvalidIdentifier);
        Ok(Self {
            scope: stable("legacy.scope")?,
            workspace: stable("legacy.workspace")?,
            purpose: stable("legacy.purpose")?,
            question: tagged_digest(b"legacy.question", encoder_digest, input_digest),
            options: tagged_digest(b"legacy.options", encoder_digest, input_digest),
            source_frontier: tagged_digest(b"legacy.source-frontier", encoder_digest, input_digest),
            model: encoder_digest,
            adapter: tagged_digest(b"legacy.adapter", encoder_digest, input_digest),
            tokenizer: tagged_digest(b"legacy.tokenizer", encoder_digest, input_digest),
            normalizer: tagged_digest(b"legacy.normalizer", encoder_digest, input_digest),
            calibration: tagged_digest(b"legacy.calibration", encoder_digest, input_digest),
        })
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.neuron.feature-snapshot-identity.v1\0".to_vec();
        append_stable_id(&mut bytes, &self.scope);
        append_stable_id(&mut bytes, &self.workspace);
        append_stable_id(&mut bytes, &self.purpose);
        for digest in [
            self.question,
            self.options,
            self.source_frontier,
            self.model,
            self.adapter,
            self.tokenizer,
            self.normalizer,
            self.calibration,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// An immutable encoder output shared by all heads in one execution batch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureSnapshotV1 {
    encoder_digest: Digest32,
    encoder_generation: Generation,
    input_digest: Digest32,
    identity: FeatureSnapshotIdentityV1,
    features_q24: Arc<[i64]>,
}

impl FeatureSnapshotV1 {
    /// Builds a snapshot and verifies that its digest is the digest of the
    /// exact feature vector. The vector is copied once into shared storage.
    pub fn new(
        encoder_digest: Digest32,
        encoder_generation: Generation,
        input_digest: Digest32,
        features_q24: Vec<i64>,
    ) -> Result<Self, DataPlaneError> {
        Self::new_with_identity(
            encoder_digest,
            encoder_generation,
            input_digest,
            features_q24,
            FeatureSnapshotIdentityV1::legacy(encoder_digest, input_digest)?,
        )
    }

    /// Builds a snapshot with the complete cache and serving identity.
    pub fn new_with_identity(
        encoder_digest: Digest32,
        encoder_generation: Generation,
        input_digest: Digest32,
        features_q24: Vec<i64>,
        identity: FeatureSnapshotIdentityV1,
    ) -> Result<Self, DataPlaneError> {
        validate_digest(encoder_digest, "encoder")?;
        validate_digest(input_digest, "input")?;
        identity.validate()?;
        validate_features(&features_q24)?;
        if canonical_feature_vector_digest_v1(&features_q24) != input_digest {
            return Err(DataPlaneError::FeatureDigestMismatch);
        }
        Ok(Self {
            encoder_digest,
            encoder_generation,
            input_digest,
            identity,
            features_q24: features_q24.into(),
        })
    }

    #[must_use]
    pub fn encoder_digest(&self) -> Digest32 {
        self.encoder_digest
    }

    #[must_use]
    pub fn encoder_generation(&self) -> Generation {
        self.encoder_generation
    }

    #[must_use]
    pub fn input_digest(&self) -> Digest32 {
        self.input_digest
    }

    #[must_use]
    pub fn identity(&self) -> &FeatureSnapshotIdentityV1 {
        &self.identity
    }

    /// Returns the shared feature storage without materializing another vector.
    #[must_use]
    pub fn features_q24(&self) -> &[i64] {
        &self.features_q24
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.neuron.feature-snapshot.v1\0",
            self.encoder_digest.as_array(),
            &self.encoder_generation.get().to_be_bytes(),
            self.input_digest.as_array(),
            self.identity.semantic_digest().as_array(),
        ])
    }
}

/// A small head that maps a shared feature vector to a bounded output vector.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LightweightHeadV1 {
    pub head_digest: Digest32,
    pub feature_width: usize,
    pub output_width: usize,
    pub weights_q24: Vec<Vec<i64>>,
    pub bias_q24: Vec<i64>,
}

impl LightweightHeadV1 {
    /// Reject shapes that cannot be represented by the existing Neuron wire.
    /// This is separate from `validate` because an offline/reference head may
    /// use the wider shared-feature fixture bounds.
    pub fn validate_neuron_wire_compatibility(&self) -> Result<(), DataPlaneError> {
        self.validate()?;
        if self.feature_width > NEURON_WIRE_MAX_FEATURES_V1
            || self.output_width > NEURON_WIRE_MAX_OUTPUTS_V1
        {
            return Err(DataPlaneError::WireDimensionMismatch);
        }
        Ok(())
    }

    fn validate(&self) -> Result<(), DataPlaneError> {
        validate_digest(self.head_digest, "head")?;
        if !(1..=MAX_FEATURES).contains(&self.feature_width)
            || !(1..=MAX_OUTPUTS).contains(&self.output_width)
            || self.weights_q24.len() != self.output_width
            || self.bias_q24.len() != self.output_width
            || self
                .weights_q24
                .iter()
                .any(|row| row.len() != self.feature_width)
        {
            return Err(DataPlaneError::InvalidHead);
        }
        if self
            .weights_q24
            .iter()
            .flatten()
            .any(|value| !(-8 * Q24 as i64..=8 * Q24 as i64).contains(value))
            || self
                .bias_q24
                .iter()
                .any(|value| !(-8 * Q24 as i64..=8 * Q24 as i64).contains(value))
        {
            return Err(DataPlaneError::InvalidHead);
        }
        Ok(())
    }

    fn execute(&self, features: &[i64]) -> Result<Vec<i64>, DataPlaneError> {
        self.validate()?;
        if features.len() != self.feature_width {
            return Err(DataPlaneError::FeatureWidthMismatch);
        }
        let mut output = Vec::with_capacity(self.output_width);
        for (row, bias) in self.weights_q24.iter().zip(&self.bias_q24) {
            let mut accumulator = i128::from(*bias) * Q24;
            for (feature, weight) in features.iter().zip(row) {
                accumulator = accumulator
                    .checked_add(i128::from(*feature) * i128::from(*weight))
                    .ok_or(DataPlaneError::Arithmetic)?;
            }
            let value = accumulator / Q24;
            let value = i64::try_from(value).map_err(|_| DataPlaneError::Arithmetic)?;
            if !(-OUTPUT_LIMIT_Q24..=OUTPUT_LIMIT_Q24).contains(&value) {
                return Err(DataPlaneError::OutputOutOfRange);
            }
            output.push(value);
        }
        Ok(output)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
struct CompatibilityKey {
    encoder_digest: Digest32,
    encoder_generation: Generation,
    feature_width: usize,
    output_width: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ModelDescriptor {
    generation: Generation,
    encoder_digest: Digest32,
    head: LightweightHeadV1,
}

/// Secondary index for finding all heads that can consume one encoder output
/// from the exact encoder generation and shape.
#[derive(Clone, Debug, Eq, PartialEq, Default)]
pub struct CompatibleModelIndexV1 {
    by_id: BTreeMap<StableId, ModelDescriptor>,
    by_compatibility: BTreeMap<CompatibilityKey, BTreeSet<StableId>>,
}

impl CompatibleModelIndexV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Registers a model in the primary map and compatibility secondary index.
    pub fn register(
        &mut self,
        model_id: StableId,
        generation: Generation,
        encoder_digest: Digest32,
        head: LightweightHeadV1,
    ) -> Result<BatchReceiptV1, DataPlaneError> {
        validate_digest(encoder_digest, "encoder")?;
        head.validate()?;
        if self.by_id.len() >= MAX_MODELS || self.by_id.contains_key(&model_id) {
            return Err(DataPlaneError::ModelConflict);
        }
        let receipt_model_id = model_id.clone();
        let head_digest = head.head_digest;
        let key = CompatibilityKey {
            encoder_digest,
            encoder_generation: generation,
            feature_width: head.feature_width,
            output_width: head.output_width,
        };
        self.by_compatibility
            .entry(key)
            .or_default()
            .insert(model_id.clone());
        self.by_id.insert(
            model_id,
            ModelDescriptor {
                generation,
                encoder_digest,
                head,
            },
        );
        BatchReceiptV1::new(
            "register-model",
            &[
                receipt_model_id.as_str().as_bytes(),
                &generation.get().to_be_bytes(),
                encoder_digest.as_array(),
                head_digest.as_array(),
            ],
        )
    }

    /// Returns active IDs compatible with the exact snapshot shape and encoder.
    #[must_use]
    pub fn compatible_models(
        &self,
        snapshot: &FeatureSnapshotV1,
        output_width: usize,
    ) -> Vec<StableId> {
        self.by_compatibility
            .get(&CompatibilityKey {
                encoder_digest: snapshot.encoder_digest,
                encoder_generation: snapshot.encoder_generation,
                feature_width: snapshot.features_q24.len(),
                output_width,
            })
            .map(|models| models.iter().cloned().collect())
            .unwrap_or_default()
    }

    fn get(&self, model_id: &StableId) -> Option<&ModelDescriptor> {
        self.by_id.get(model_id)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RetiredModelRecord {
    retired_generation: Generation,
    replacement_id: StableId,
    replacement_generation: Generation,
    retirement_digest: Digest32,
}

/// Durable-style retired-ID fence. A retired ID can never be silently reused.
#[derive(Clone, Debug, Eq, PartialEq, Default)]
pub struct RetiredIdRegistryV1 {
    records: BTreeMap<StableId, RetiredModelRecord>,
}

impl RetiredIdRegistryV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn retire(
        &mut self,
        retired_id: StableId,
        retired_generation: Generation,
        replacement_id: StableId,
        replacement_generation: Generation,
    ) -> Result<BatchReceiptV1, DataPlaneError> {
        if self.records.len() >= MAX_RETIRED_IDS
            || retired_id == replacement_id
            || self.records.contains_key(&retired_id)
            || self.records.contains_key(&replacement_id)
            || self
                .records
                .values()
                .any(|record| record.replacement_id == replacement_id)
            || replacement_generation <= retired_generation
        {
            return Err(DataPlaneError::InvalidRollover);
        }
        let retirement_digest = Digest32::of_parts(&[
            b"hepta.neuron.retired-id-rollover.v1\0",
            retired_id.as_str().as_bytes(),
            &retired_generation.get().to_be_bytes(),
            replacement_id.as_str().as_bytes(),
            &replacement_generation.get().to_be_bytes(),
        ]);
        self.records.insert(
            retired_id,
            RetiredModelRecord {
                retired_generation,
                replacement_id,
                replacement_generation,
                retirement_digest,
            },
        );
        Ok(BatchReceiptV1 {
            operation: StableId::new("retire-model")
                .map_err(|_| DataPlaneError::InvalidIdentifier)?,
            digest: retirement_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub fn is_retired(&self, model_id: &StableId) -> bool {
        self.records.contains_key(model_id)
    }

    #[must_use]
    pub fn replacement(&self, model_id: &StableId) -> Option<(&StableId, Generation)> {
        self.records
            .get(model_id)
            .map(|record| (&record.replacement_id, record.replacement_generation))
    }

    #[must_use]
    pub fn retirement_digest(&self, model_id: &StableId) -> Option<Digest32> {
        self.records
            .get(model_id)
            .map(|record| record.retirement_digest)
    }

    /// Verifies that every rollover is bound to the model generations that
    /// are actually loaded in the execution index.  The retired model may
    /// already have been removed from the index, but if it is still present
    /// its generation must match the durable retirement record.  A rollover
    /// target is required to exist at exactly the recorded generation and may
    /// not itself be retired; otherwise a route could silently terminate in a
    /// missing or stale model.
    pub fn validate_against(&self, models: &CompatibleModelIndexV1) -> Result<(), DataPlaneError> {
        for (retired_id, record) in &self.records {
            if models
                .get(retired_id)
                .is_some_and(|retired| retired.generation != record.retired_generation)
            {
                return Err(DataPlaneError::InvalidRollover);
            }
            let Some(replacement) = models.get(&record.replacement_id) else {
                return Err(DataPlaneError::InvalidRollover);
            };
            if replacement.generation != record.replacement_generation
                || self.is_retired(&record.replacement_id)
            {
                return Err(DataPlaneError::InvalidRollover);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
struct CacheKey {
    encoder_digest: Digest32,
    encoder_generation: Generation,
    input_digest: Digest32,
    identity: FeatureSnapshotIdentityV1,
}

/// Generation-scoped feature cache. Invalidation advances the generation and
/// clears all entries, making stale snapshots unservable by construction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureSnapshotCacheV1 {
    generation: Generation,
    entries: BTreeMap<CacheKey, FeatureSnapshotV1>,
    maximum_entries: usize,
}

impl FeatureSnapshotCacheV1 {
    pub fn new(generation: Generation, maximum_entries: usize) -> Result<Self, DataPlaneError> {
        if maximum_entries == 0 {
            return Err(DataPlaneError::InvalidCacheCapacity);
        }
        Ok(Self {
            generation,
            entries: BTreeMap::new(),
            maximum_entries: maximum_entries.min(MAX_CACHE_ENTRIES),
        })
    }

    #[must_use]
    pub fn generation(&self) -> Generation {
        self.generation
    }

    pub fn insert(
        &mut self,
        snapshot: FeatureSnapshotV1,
    ) -> Result<BatchReceiptV1, DataPlaneError> {
        if snapshot.encoder_generation != self.generation {
            return Err(DataPlaneError::StaleCacheGeneration);
        }
        let key = CacheKey {
            encoder_digest: snapshot.encoder_digest,
            encoder_generation: snapshot.encoder_generation,
            input_digest: snapshot.input_digest,
            identity: snapshot.identity.clone(),
        };
        if !self.entries.contains_key(&key) && self.entries.len() >= self.maximum_entries {
            return Err(DataPlaneError::CacheCapacityExceeded);
        }
        let snapshot_digest = snapshot.semantic_digest();
        self.entries.insert(key, snapshot);
        BatchReceiptV1::new("cache-insert", &[snapshot_digest.as_array()])
    }

    #[must_use]
    pub fn get(
        &self,
        encoder_digest: Digest32,
        input_digest: Digest32,
        expected_generation: Generation,
    ) -> Option<FeatureSnapshotV1> {
        let Ok(identity) = FeatureSnapshotIdentityV1::legacy(encoder_digest, input_digest) else {
            return None;
        };
        self.get_with_identity(encoder_digest, input_digest, expected_generation, &identity)
    }

    /// Looks up a snapshot using the complete scope/model/cache identity.
    #[must_use]
    pub fn get_with_identity(
        &self,
        encoder_digest: Digest32,
        input_digest: Digest32,
        expected_generation: Generation,
        identity: &FeatureSnapshotIdentityV1,
    ) -> Option<FeatureSnapshotV1> {
        if expected_generation != self.generation {
            return None;
        }
        if identity.validate().is_err() {
            return None;
        }
        self.entries
            .get(&CacheKey {
                encoder_digest,
                encoder_generation: expected_generation,
                input_digest,
                identity: identity.clone(),
            })
            .filter(|snapshot| snapshot.encoder_generation == expected_generation)
            .cloned()
    }

    pub fn invalidate_generation(
        &mut self,
        next_generation: Generation,
    ) -> Result<BatchReceiptV1, DataPlaneError> {
        if next_generation <= self.generation {
            return Err(DataPlaneError::StaleCacheGeneration);
        }
        self.entries.clear();
        self.generation = next_generation;
        BatchReceiptV1::new("cache-invalidate", &[&next_generation.get().to_be_bytes()])
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeadExecutionRequestV1 {
    pub request_id: StableId,
    pub model_id: StableId,
    pub generation: Generation,
    pub snapshot: FeatureSnapshotV1,
}

/// A frozen unit of work handed from the microbatch planner to a worker.
///
/// The planner owns the exact request values (including the immutable feature
/// snapshot).  A worker therefore cannot accidentally execute a different
/// request set under an old plan digest.  Cloning a request does not clone the
/// feature vector because [`FeatureSnapshotV1`] stores it in an `Arc`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MicrobatchPlanV1 {
    worker_id: StableId,
    generation: Generation,
    planned_at_micros: u64,
    deadline_micros: u64,
    requests: Vec<HeadExecutionRequestV1>,
    plan_digest: Digest32,
}

impl MicrobatchPlanV1 {
    /// Build a plan for one shared-feature batch.  Every item must refer to
    /// the same immutable snapshot and generation; heads and model IDs may
    /// differ.  This is the boundary that turns a callable planner into a
    /// worker-consumable, replay-stable artifact.
    pub fn new(
        worker_id: StableId,
        generation: Generation,
        planned_at_micros: u64,
        deadline_micros: u64,
        requests: Vec<HeadExecutionRequestV1>,
    ) -> Result<Self, DataPlaneError> {
        if worker_id.as_str().is_empty()
            || planned_at_micros >= deadline_micros
            || requests.is_empty()
            || requests.len() > MAX_MICROBATCH_REQUESTS_V1
        {
            return Err(DataPlaneError::InvalidMicrobatchPlan);
        }
        let first = requests
            .first()
            .ok_or(DataPlaneError::InvalidMicrobatchPlan)?;
        let snapshot_digest = first.snapshot.semantic_digest();
        let mut seen = BTreeSet::new();
        for request in &requests {
            if request.generation != generation
                || request.snapshot.encoder_generation != generation
                || request.snapshot.semantic_digest() != snapshot_digest
                || !seen.insert(request.request_id.clone())
            {
                return Err(DataPlaneError::InvalidMicrobatchPlan);
            }
        }
        let plan_digest = digest_microbatch_plan(
            &worker_id,
            generation,
            planned_at_micros,
            deadline_micros,
            &requests,
        );
        Ok(Self {
            worker_id,
            generation,
            planned_at_micros,
            deadline_micros,
            requests,
            plan_digest,
        })
    }

    #[must_use]
    pub fn worker_id(&self) -> &StableId {
        &self.worker_id
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub const fn planned_at_micros(&self) -> u64 {
        self.planned_at_micros
    }

    #[must_use]
    pub const fn deadline_micros(&self) -> u64 {
        self.deadline_micros
    }

    #[must_use]
    pub fn requests(&self) -> &[HeadExecutionRequestV1] {
        &self.requests
    }

    #[must_use]
    pub const fn plan_digest(&self) -> Digest32 {
        self.plan_digest
    }

    /// Recompute and validate the frozen identity before the worker crosses
    /// into the backend.  This catches any accidental in-memory mutation in
    /// callers that retain a plan across a retry.
    pub fn validate(&self, now_micros: u64) -> Result<(), DataPlaneError> {
        if now_micros >= self.deadline_micros
            || self.requests.is_empty()
            || self.requests.len() > MAX_MICROBATCH_REQUESTS_V1
            || self.plan_digest
                != digest_microbatch_plan(
                    &self.worker_id,
                    self.generation,
                    self.planned_at_micros,
                    self.deadline_micros,
                    &self.requests,
                )
        {
            return Err(DataPlaneError::InvalidMicrobatchPlan);
        }
        Ok(())
    }
}

/// Plan a bounded shared-feature batch.  This function intentionally returns
/// a frozen plan rather than executing any model work.
pub fn plan_microbatch_v1(
    worker_id: StableId,
    generation: Generation,
    planned_at_micros: u64,
    deadline_micros: u64,
    requests: Vec<HeadExecutionRequestV1>,
) -> Result<MicrobatchPlanV1, DataPlaneError> {
    MicrobatchPlanV1::new(
        worker_id,
        generation,
        planned_at_micros,
        deadline_micros,
        requests,
    )
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeadExecutionOutputV1 {
    pub request_id: StableId,
    pub model_id: StableId,
    pub generation: Generation,
    pub input_digest: Digest32,
    pub output_q24: Vec<i64>,
    pub output_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// A real, deterministic backend batch. It computes every requested head and
/// reuses one immutable feature allocation per request snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReferenceBackendBatchV1 {
    models: CompatibleModelIndexV1,
    retired_ids: RetiredIdRegistryV1,
}

impl ReferenceBackendBatchV1 {
    #[must_use]
    pub fn new(models: CompatibleModelIndexV1, retired_ids: RetiredIdRegistryV1) -> Self {
        Self {
            models,
            retired_ids,
        }
    }

    /// Constructs a backend only when every retired-ID rollover is bound to a
    /// loaded replacement at the recorded generation.  [`Self::new`] remains
    /// available for callers that assemble state incrementally; execution
    /// still repeats this validation before touching a head.
    pub fn try_new(
        models: CompatibleModelIndexV1,
        retired_ids: RetiredIdRegistryV1,
    ) -> Result<Self, DataPlaneError> {
        retired_ids.validate_against(&models)?;
        Ok(Self {
            models,
            retired_ids,
        })
    }

    pub fn execute(
        &self,
        requests: &[HeadExecutionRequestV1],
    ) -> Result<Vec<HeadExecutionOutputV1>, DataPlaneError> {
        if requests.is_empty() || requests.len() > MAX_BATCH_ITEMS {
            return Err(DataPlaneError::InvalidBatchSize);
        }
        self.retired_ids.validate_against(&self.models)?;
        let mut seen = BTreeSet::new();
        let mut outputs = Vec::with_capacity(requests.len());
        for request in requests {
            if !seen.insert(request.request_id.clone()) {
                return Err(DataPlaneError::DuplicateRequest);
            }
            if self.retired_ids.is_retired(&request.model_id) {
                return Err(DataPlaneError::ModelRetired);
            }
            let Some(model) = self.models.get(&request.model_id) else {
                return Err(DataPlaneError::ModelNotFound);
            };
            if request.generation != model.generation
                || request.snapshot.encoder_generation != request.generation
                || request.snapshot.encoder_digest != model.encoder_digest
            {
                return Err(DataPlaneError::ModelGenerationMismatch);
            }
            model.head.validate_neuron_wire_compatibility()?;
            if request.snapshot.features_q24.len() > NEURON_WIRE_MAX_FEATURES_V1 {
                return Err(DataPlaneError::WireDimensionMismatch);
            }
            let output_q24 = model.head.execute(request.snapshot.features_q24())?;
            let output_digest = digest_output(
                &request.request_id,
                &request.model_id,
                request.generation,
                model.head.head_digest,
                request.snapshot.encoder_digest,
                request.snapshot.input_digest,
                request.snapshot.identity.semantic_digest(),
                &output_q24,
            );
            outputs.push(HeadExecutionOutputV1 {
                request_id: request.request_id.clone(),
                model_id: request.model_id.clone(),
                generation: request.generation,
                input_digest: request.snapshot.input_digest,
                output_q24,
                output_digest,
                authority: AuthorityPosture::DENY_ALL,
            });
        }
        Ok(outputs)
    }

    #[must_use]
    pub fn model_index(&self) -> &CompatibleModelIndexV1 {
        &self.models
    }

    /// Returns routable compatible models after applying the retired-ID fence.
    #[must_use]
    pub fn compatible_models(
        &self,
        snapshot: &FeatureSnapshotV1,
        output_width: usize,
    ) -> Vec<StableId> {
        self.models
            .compatible_models(snapshot, output_width)
            .into_iter()
            .filter(|model_id| !self.retired_ids.is_retired(model_id))
            .collect()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BatchReceiptV1 {
    pub operation: StableId,
    pub digest: Digest32,
    pub authority: AuthorityPosture,
}

impl BatchReceiptV1 {
    fn new(operation: &str, binding: &[&[u8]]) -> Result<Self, DataPlaneError> {
        let mut bytes = b"hepta.neuron.data-plane-receipt.v1\0".to_vec();
        bytes.extend_from_slice(operation.as_bytes());
        bytes.extend_from_slice(
            &u32::try_from(binding.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for part in binding {
            bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
            bytes.extend_from_slice(part);
        }
        Ok(Self {
            operation: StableId::new(operation).map_err(|_| DataPlaneError::InvalidIdentifier)?,
            digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DataPlaneError {
    EmptyDigest(&'static str),
    InvalidFeatures,
    FeatureDigestMismatch,
    InvalidHead,
    FeatureWidthMismatch,
    Arithmetic,
    OutputOutOfRange,
    WireDimensionMismatch,
    InvalidIdentifier,
    ModelConflict,
    InvalidRollover,
    InvalidCacheCapacity,
    StaleCacheGeneration,
    CacheCapacityExceeded,
    InvalidBatchSize,
    InvalidMicrobatchPlan,
    DuplicateRequest,
    ModelNotFound,
    ModelRetired,
    ModelGenerationMismatch,
}

impl fmt::Display for DataPlaneError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DataPlaneError {}

fn validate_digest(value: Digest32, field: &'static str) -> Result<(), DataPlaneError> {
    if value.is_zero() {
        return Err(DataPlaneError::EmptyDigest(field));
    }
    Ok(())
}

fn validate_features(features: &[i64]) -> Result<(), DataPlaneError> {
    if features.is_empty()
        || features.len() > MAX_FEATURES
        || features
            .iter()
            .any(|value| !(-8 * Q24 as i64..=8 * Q24 as i64).contains(value))
    {
        return Err(DataPlaneError::InvalidFeatures);
    }
    Ok(())
}

fn tagged_digest(tag: &[u8], encoder_digest: Digest32, input_digest: Digest32) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.neuron.legacy-feature-identity.v1\0",
        tag,
        encoder_digest.as_array(),
        input_digest.as_array(),
    ])
}

fn append_stable_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn digest_output(
    request_id: &StableId,
    model_id: &StableId,
    generation: Generation,
    head_digest: Digest32,
    encoder_digest: Digest32,
    input_digest: Digest32,
    identity_digest: Digest32,
    output: &[i64],
) -> Digest32 {
    let mut bytes = b"hepta.neuron.reference-backend-output.v1\0".to_vec();
    bytes.extend_from_slice(request_id.as_str().as_bytes());
    bytes.extend_from_slice(model_id.as_str().as_bytes());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(head_digest.as_array());
    bytes.extend_from_slice(encoder_digest.as_array());
    bytes.extend_from_slice(input_digest.as_array());
    bytes.extend_from_slice(identity_digest.as_array());
    for value in output {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_microbatch_plan(
    worker_id: &StableId,
    generation: Generation,
    planned_at_micros: u64,
    deadline_micros: u64,
    requests: &[HeadExecutionRequestV1],
) -> Digest32 {
    let mut bytes = b"hepta.neuron.microbatch-plan.v1\0".to_vec();
    append_stable_id(&mut bytes, worker_id);
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(&planned_at_micros.to_be_bytes());
    bytes.extend_from_slice(&deadline_micros.to_be_bytes());
    bytes.extend_from_slice(&(requests.len() as u64).to_be_bytes());
    for request in requests {
        append_stable_id(&mut bytes, &request.request_id);
        append_stable_id(&mut bytes, &request.model_id);
        bytes.extend_from_slice(&request.generation.get().to_be_bytes());
        bytes.extend_from_slice(request.snapshot.semantic_digest().as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "data_plane_tests.rs"]
mod tests;

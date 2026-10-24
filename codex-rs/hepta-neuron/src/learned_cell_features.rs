//! Bounded import of recorded 770D features, without claiming an Encoder call.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

pub const LEARNED_FEATURE_MAGIC_770_V1: &[u8] = b"HEPTA-CELL-FEATURES-770-F64-V1\0";
pub const LEARNED_FEATURE_WIDTH_770_V1: usize = 770;
pub const MAX_LEARNED_FEATURE_ROWS_770_V1: usize = 64;
const HEADER_BYTES: usize = LEARNED_FEATURE_MAGIC_770_V1.len() + 48;
const ROW_BYTES: usize = 32 + LEARNED_FEATURE_WIDTH_770_V1 * 8;

/// Independently selected pins; importing self-described bytes is insufficient.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LearnedFeaturePins770V1 {
    pub artifact_digest: Digest32,
    pub feature_identity_digest: Digest32,
    pub generation: Generation,
}

/// One normalized allocation shared by borrowed references or cheap Arc clones.
///
/// The whole-artifact pin binds ordered source-record digests and raw values.
/// It authenticates bytes selected by the caller, not current source authority.
#[derive(Clone, Debug)]
pub struct SharedLearnedFeatures770V1 {
    pins: LearnedFeaturePins770V1,
    sources: Arc<[Digest32]>,
    pub(crate) normalized: Arc<[f64]>,
}

impl SharedLearnedFeatures770V1 {
    /// Import fixed little-endian FP64 rows and normalize once, as the QA Head
    /// does: x / max(sqrt(sum(x*x)), 1e-12) * sqrt(770).
    pub fn import(
        bytes: &[u8],
        expected: &LearnedFeaturePins770V1,
    ) -> Result<Self, LearnedFeatureError770V1> {
        if !(HEADER_BYTES + ROW_BYTES..=HEADER_BYTES + 64 * ROW_BYTES).contains(&bytes.len())
            || expected.artifact_digest.is_zero()
            || expected.feature_identity_digest.is_zero()
        {
            return Err(LearnedFeatureError770V1::InvalidEnvelope);
        }
        if Digest32::of_bytes(bytes) != expected.artifact_digest {
            return Err(LearnedFeatureError770V1::ArtifactDigestMismatch);
        }
        if !bytes.starts_with(LEARNED_FEATURE_MAGIC_770_V1) {
            return Err(LearnedFeatureError770V1::InvalidEnvelope);
        }
        let header = &bytes[LEARNED_FEATURE_MAGIC_770_V1.len()..HEADER_BYTES];
        if &header[..32] != expected.feature_identity_digest.as_array() {
            return Err(LearnedFeatureError770V1::IdentityMismatch);
        }
        if header[32..40] != expected.generation.get().to_le_bytes() {
            return Err(LearnedFeatureError770V1::GenerationMismatch);
        }
        let mut row_bytes = [0_u8; 8];
        row_bytes.copy_from_slice(&header[40..48]);
        let rows = u64::from_le_bytes(row_bytes);
        if !(1..=MAX_LEARNED_FEATURE_ROWS_770_V1 as u64).contains(&rows)
            || bytes.len() != HEADER_BYTES + rows as usize * ROW_BYTES
        {
            return Err(LearnedFeatureError770V1::InvalidEnvelope);
        }
        let source_end = HEADER_BYTES + rows as usize * 32;
        let mut sources = Vec::with_capacity(rows as usize);
        for chunk in bytes[HEADER_BYTES..source_end].chunks_exact(32) {
            let mut value = [0_u8; 32];
            value.copy_from_slice(chunk);
            let source = Digest32::from_array(value);
            if source.is_zero() || sources.contains(&source) {
                return Err(LearnedFeatureError770V1::InvalidSource);
            }
            sources.push(source);
        }
        let mut normalized = Vec::with_capacity(rows as usize * LEARNED_FEATURE_WIDTH_770_V1);
        for chunk in bytes[source_end..].chunks_exact(8) {
            let mut value = [0_u8; 8];
            value.copy_from_slice(chunk);
            let value = f64::from_le_bytes(value);
            if !value.is_finite() {
                return Err(LearnedFeatureError770V1::Nonfinite);
            }
            normalized.push(value);
        }
        for row in normalized.chunks_exact_mut(LEARNED_FEATURE_WIDTH_770_V1) {
            let norm = row.iter().map(|x| x * x).sum::<f64>().sqrt();
            if !norm.is_finite() {
                return Err(LearnedFeatureError770V1::Nonfinite);
            }
            for value in row {
                *value = *value / norm.max(1e-12) * (LEARNED_FEATURE_WIDTH_770_V1 as f64).sqrt();
            }
        }
        Ok(Self {
            pins: *expected,
            sources: Arc::from(sources),
            normalized: Arc::from(normalized),
        })
    }

    #[must_use]
    pub fn feature_identity_digest(&self) -> Digest32 {
        self.pins.feature_identity_digest
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.pins.generation
    }

    #[must_use]
    pub fn artifact_digest(&self) -> Digest32 {
        self.pins.artifact_digest
    }

    #[must_use]
    pub fn rows(&self) -> usize {
        self.sources.len()
    }

    #[must_use]
    pub fn source_record_digests(&self) -> &[Digest32] {
        &self.sources
    }

    /// Owned numeric bytes only; excludes source metadata and the caller buffer.
    #[must_use]
    pub fn tensor_bytes(&self) -> usize {
        self.normalized.len() * std::mem::size_of::<f64>()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearnedFeatureError770V1 {
    InvalidEnvelope,
    ArtifactDigestMismatch,
    IdentityMismatch,
    GenerationMismatch,
    InvalidSource,
    Nonfinite,
}

impl fmt::Display for LearnedFeatureError770V1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearnedFeatureError770V1 {}

#[cfg(test)]
#[path = "learned_cell_features_tests.rs"]
mod tests;

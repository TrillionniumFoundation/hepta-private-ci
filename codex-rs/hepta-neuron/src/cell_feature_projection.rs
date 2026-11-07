//! Import the existing Python FeatureBundleV1 global Q24 conversion receipt.
//!
//! This is a bounded projection into the native numeric Cell profile, not a
//! replacement tensor bundle. The source owner must verify the original bundle,
//! conversion pin and current source access before constructing the binding.
//! Local hashes do not authenticate that owner or prove nonlinear Head parity.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::CellEncodedInputV1;
use crate::CellEncodingRequestV1;
use crate::CellExecutionError;
use crate::CellInputEncoderV1;

const SCHEMA: &str = "hepta.feature-global-q24-conversion.v1";
const NUMERIC_PROFILE: &str = "signed-q24-nearest-ties-even-v1";
const MAX_RECEIPT_BYTES: usize = 65_536;
const MAX_FEATURES: usize = 512;
const MAX_SOURCE_ROWS: usize = 512;

/// Pins resolved by the current source/artifacts owner. The expected conversion
/// digest is independent of the imported bytes; a self-consistent replacement
/// cannot change the admitted feature vector. Scope/frontier are native pins,
/// not invented source timestamps or token annotations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellFeatureProjectionBindingV1 {
    pub scope_digest: Digest32,
    pub source_frontier: Digest32,
    pub encoder_digest: Digest32,
    pub source_bundle_digest: Digest32,
    pub source_record_digest: Digest32,
    pub conversion_digest: Digest32,
    pub row: usize,
    pub width: usize,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ProjectionWire {
    schema: String,
    numeric_profile: String,
    source_bundle_sha256: String,
    source_record_digest: String,
    row: usize,
    feature_vector_q24: Vec<i64>,
    authority: String,
    legacy_head_parity_qualified: bool,
    conversion_sha256: String,
}

/// Immutable, explicitly global-only input. The model receives the original
/// Q24 values with no added masks, padding, rescaling or silent truncation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGlobalFeatureProjectionV1 {
    binding: CellFeatureProjectionBindingV1,
    schema_digest: Digest32,
    observation: Vec<u8>,
    features: Vec<i64>,
}

/// Names this global-only input profile and its exact width. It is distinct
/// from the original full tensor bundle and from event/token feature schemas.
pub fn cell_global_feature_schema_digest_v1(width: usize) -> Result<Digest32, CellExecutionError> {
    if !(1..=MAX_FEATURES).contains(&width) {
        return Err(CellExecutionError::CapacityExceeded);
    }
    Ok(Digest32::of_parts(&[
        b"hepta.cell.global-feature-input.v1\0",
        SCHEMA.as_bytes(),
        b"\0",
        NUMERIC_PROFILE.as_bytes(),
        &(width as u64).to_be_bytes(),
    ]))
}

impl CellGlobalFeatureProjectionV1 {
    /// Verify the original receipt grammar and Python's sorted, compact SHA256
    /// statement. This checks the supplied owner's pins, not the absent source
    /// tensors; a full conversion/parity claim requires those independent bytes.
    pub fn from_json(
        raw: &[u8],
        binding: CellFeatureProjectionBindingV1,
    ) -> Result<Self, CellExecutionError> {
        if raw.len() > MAX_RECEIPT_BYTES || binding.row >= MAX_SOURCE_ROWS {
            return Err(CellExecutionError::CapacityExceeded);
        }
        let schema_digest = cell_global_feature_schema_digest_v1(binding.width)?;
        if [
            binding.scope_digest,
            binding.source_frontier,
            binding.encoder_digest,
            binding.source_bundle_digest,
            binding.source_record_digest,
            binding.conversion_digest,
        ]
        .into_iter()
        .any(Digest32::is_zero)
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        // Typed deserialization rejects duplicate/unknown keys, bool-as-int,
        // floating numbers, overflow and trailing values before normalization.
        let wire: ProjectionWire =
            serde_json::from_slice(raw).map_err(|_| CellExecutionError::EncodingMismatch)?;
        if wire.schema != SCHEMA
            || wire.numeric_profile != NUMERIC_PROFILE
            || wire.authority != "DENY_ALL"
            || wire.legacy_head_parity_qualified
            || wire.source_bundle_sha256 != binding.source_bundle_digest.to_string()
            || wire.source_record_digest != binding.source_record_digest.to_string()
            || wire.conversion_sha256 != binding.conversion_digest.to_string()
            || wire.row != binding.row
            || wire.feature_vector_q24.len() != binding.width
            || wire
                .feature_vector_q24
                .iter()
                .any(|value| !(-8 * (1 << 24)..=8 * (1 << 24)).contains(value))
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        // Sort explicitly: serde_json's preserve_order feature may be enabled
        // by another workspace crate. Every nested value here is scalar/array.
        let mut fields: BTreeMap<String, serde_json::Value> = serde_json::from_value(
            serde_json::to_value(&wire).map_err(|_| CellExecutionError::EncodingMismatch)?,
        )
        .map_err(|_| CellExecutionError::EncodingMismatch)?;
        let seal = fields
            .remove("conversion_sha256")
            .ok_or(CellExecutionError::EncodingMismatch)?;
        let statement =
            serde_json::to_vec(&fields).map_err(|_| CellExecutionError::EncodingMismatch)?;
        if Digest32::of_bytes(&statement) != binding.conversion_digest {
            return Err(CellExecutionError::EncodingMismatch);
        }
        fields.insert("conversion_sha256".to_string(), seal);
        let observation =
            serde_json::to_vec(&fields).map_err(|_| CellExecutionError::EncodingMismatch)?;
        Ok(Self {
            binding,
            schema_digest,
            observation,
            features: wire.feature_vector_q24,
        })
    }

    pub fn observation_bytes(&self) -> &[u8] {
        &self.observation
    }

    pub fn schema_digest(&self) -> Digest32 {
        self.schema_digest
    }

    pub(crate) fn validate_request(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<(), CellExecutionError> {
        if request.scope.digest() != self.binding.scope_digest {
            return Err(CellExecutionError::ScopeMismatch);
        }
        if request.source_frontier != self.binding.source_frontier {
            return Err(CellExecutionError::StaleSource);
        }
        if request.encoder_digest != self.binding.encoder_digest
            || request.observation != self.observation
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        Ok(())
    }
}

impl CellInputEncoderV1 for CellGlobalFeatureProjectionV1 {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        self.validate_request(request)?;
        Ok(CellEncodedInputV1 {
            encoder_digest: self.binding.encoder_digest,
            feature_vector_q24: self.features.clone(),
            consumed_bytes: self.observation.len(),
            truncated_bytes: 0,
        })
    }
}

#[cfg(test)]
#[path = "cell_feature_projection_tests.rs"]
mod tests;

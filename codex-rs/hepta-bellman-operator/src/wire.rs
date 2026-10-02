//! Bounded canonical JSON for the registered Bellman artifact contract.
//!
//! This is a structural/digest adapter, never an evaluator, model loader or
//! selector. Evidence digests require independent authentication by their owners.
//! The tabular HEPTTB01 payload is not silently promoted to this richer record.

use std::error::Error;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;

pub const MAX_BELLMAN_ARTIFACT_JSON_BYTES: usize = 262_144;
const MAX_ERROR_BUDGET_BYTES: usize = 16_384;

// Field declaration order is lexicographic at every level. The profile contains
// only strings and integers, avoiding floating-point canonicalization ambiguity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BellmanErrorTermWireV1 {
    pub evidence_digest: String,
    pub normalized_error_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BellmanErrorBudgetWireV1 {
    // Presence is a claim to be authenticated, not proof of independent approval.
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_string"
    )]
    pub dominant_approval_evidence_digest: Option<String>,
    pub model: BellmanErrorTermWireV1,
    pub network: BellmanErrorTermWireV1,
    pub optimization: BellmanErrorTermWireV1,
    pub reconstruction: BellmanErrorTermWireV1,
    pub rollout: BellmanErrorTermWireV1,
    pub schema: String,
    pub sensor: BellmanErrorTermWireV1,
    pub statistical: BellmanErrorTermWireV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BellmanOperatorArtifactWireV1 {
    pub action_trunk_digest: String,
    pub applicability_digest: String,
    pub artifact_id: String,
    pub branch_digest: String,
    pub error_budget: BellmanErrorBudgetWireV1,
    pub normalization_digest: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present_string"
    )]
    pub predecessor_artifact_id: Option<String>,
    pub rank: u32,
    pub rollback_digest: String,
    pub runtime_tuple_digest: String,
    pub sensor_core_digest: String,
    pub state_trunk_digest: String,
    pub training_code_digest: String,
    pub training_dataset_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalBellmanArtifactV1 {
    record: BellmanOperatorArtifactWireV1,
    bytes: Vec<u8>,
    digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BellmanArtifactWireError {
    Size,
    Json,
    Identity,
    Digest,
    Rank,
    ErrorBudget,
    DominantApprovalMissing,
    PinMismatch,
}

impl fmt::Display for BellmanArtifactWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for BellmanArtifactWireError {}

impl CanonicalBellmanArtifactV1 {
    /// Bounds the encoded ingress before allocation/deserialization. Duplicate,
    /// unknown and missing fields reject at every typed object boundary.
    pub fn from_json(bytes: &[u8]) -> Result<Self, BellmanArtifactWireError> {
        if bytes.len() > MAX_BELLMAN_ARTIFACT_JSON_BYTES {
            return Err(BellmanArtifactWireError::Size);
        }
        let record = serde_json::from_slice(bytes).map_err(|_| BellmanArtifactWireError::Json)?;
        Self::from_record(record)
    }

    /// The expected canonical digest must come from an independently admitted
    /// owner manifest. Computing it from these bytes supplies no authentication.
    pub fn from_pinned_json(
        bytes: &[u8],
        expected: Digest32,
    ) -> Result<Self, BellmanArtifactWireError> {
        let artifact = Self::from_json(bytes)?;
        if expected.is_zero() || artifact.digest != expected {
            return Err(BellmanArtifactWireError::PinMismatch);
        }
        Ok(artifact)
    }

    pub fn from_record(
        record: BellmanOperatorArtifactWireV1,
    ) -> Result<Self, BellmanArtifactWireError> {
        if record.artifact_id.len() > 128
            || record
                .predecessor_artifact_id
                .as_ref()
                .is_some_and(|id| id.len() > 128)
        {
            return Err(BellmanArtifactWireError::Identity);
        }
        StableId::new(record.artifact_id.clone())
            .map_err(|_| BellmanArtifactWireError::Identity)?;
        if let Some(predecessor) = &record.predecessor_artifact_id {
            StableId::new(predecessor.clone()).map_err(|_| BellmanArtifactWireError::Identity)?;
            if predecessor == &record.artifact_id {
                return Err(BellmanArtifactWireError::Identity);
            }
        }
        if !(1..=64).contains(&record.rank) {
            return Err(BellmanArtifactWireError::Rank);
        }
        for digest in [
            &record.action_trunk_digest,
            &record.applicability_digest,
            &record.branch_digest,
            &record.normalization_digest,
            &record.rollback_digest,
            &record.runtime_tuple_digest,
            &record.sensor_core_digest,
            &record.state_trunk_digest,
            &record.training_code_digest,
            &record.training_dataset_digest,
        ] {
            require_digest(digest)?;
        }
        let budget = &record.error_budget;
        if budget.schema != "hepta.bellman-error-budget.q32.v1" {
            return Err(BellmanArtifactWireError::ErrorBudget);
        }
        let mut total = 0_i128;
        let mut maximum = 0_i128;
        for term in [
            &budget.model,
            &budget.network,
            &budget.optimization,
            &budget.reconstruction,
            &budget.rollout,
            &budget.sensor,
            &budget.statistical,
        ] {
            require_digest(&term.evidence_digest)?;
            if term.normalized_error_q32 < 0 {
                return Err(BellmanArtifactWireError::ErrorBudget);
            }
            let error = i128::from(term.normalized_error_q32);
            total += error;
            maximum = maximum.max(error);
        }
        if total > i128::from(FixedQ32::ONE.raw() / 20) {
            return Err(BellmanArtifactWireError::ErrorBudget);
        }
        if let Some(approval) = &budget.dominant_approval_evidence_digest {
            require_digest(approval)?;
        } else if maximum * 2 > total {
            return Err(BellmanArtifactWireError::DominantApprovalMissing);
        }
        if serde_json::to_vec(budget)
            .map_err(|_| BellmanArtifactWireError::Json)?
            .len()
            > MAX_ERROR_BUDGET_BYTES
        {
            return Err(BellmanArtifactWireError::Size);
        }
        let bytes = serde_json::to_vec(&record).map_err(|_| BellmanArtifactWireError::Json)?;
        if bytes.len() > MAX_BELLMAN_ARTIFACT_JSON_BYTES {
            return Err(BellmanArtifactWireError::Size);
        }
        let digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            record,
            bytes,
            digest,
        })
    }

    pub fn record(&self) -> &BellmanOperatorArtifactWireV1 {
        &self.record
    }
    pub fn canonical_json(&self) -> &[u8] {
        &self.bytes
    }
    pub const fn canonical_digest(&self) -> Digest32 {
        self.digest
    }
}

fn require_digest(value: &str) -> Result<(), BellmanArtifactWireError> {
    if value.len() != 64
        || Digest32::from_str(value)
            .map_err(|_| BellmanArtifactWireError::Digest)?
            .is_zero()
    {
        return Err(BellmanArtifactWireError::Digest);
    }
    Ok(())
}

fn present_string<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Option<String>, D::Error> {
    String::deserialize(deserializer).map(Some)
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;

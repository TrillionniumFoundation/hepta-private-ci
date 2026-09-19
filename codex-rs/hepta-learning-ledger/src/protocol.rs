//! Canonical cross-module protocol adapters owned by learning.ledger.
//!
//! These names and JSON field layouts mirror docs/contracts/PROTOCOL_SCHEMAS.json.
//! Native durable structs may evolve additively, but protocol identifiers and
//! semantic field names do not silently inherit native implementation names.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;

use crate::AuthenticatedOutcomeV1;
use crate::CreditAllocationBatchV1;
use crate::DatasetSnapshotReceiptV3;
use crate::EpisodeDecision;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::OutcomeTerminalityV1;
use crate::OutcomeWatermarkV1;

const MAX_PROTOCOL_BYTES: usize = 262_144;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CanonicalCreditAllocationV1 {
    #[serde(with = "id_wire")]
    pub target_id: StableId,
    pub credit_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CreditAssignmentReceiptV1 {
    #[serde(with = "id_wire")]
    pub credit_id: StableId,
    #[serde(with = "id_wire")]
    pub episode_id: StableId,
    #[serde(with = "digest_wire")]
    pub outcome_digest: Digest32,
    #[serde(default, with = "optional_id_wire")]
    pub parent_credit_id: Option<StableId>,
    pub allocations: Vec<CanonicalCreditAllocationV1>,
    pub conservation_residual_q32: i64,
    #[serde(with = "digest_wire")]
    pub rule_digest: Digest32,
}

impl CreditAssignmentReceiptV1 {
    #[must_use]
    pub fn from_credit_batch(
        batch: &CreditAllocationBatchV1,
        outcome_digest: Digest32,
        rule_digest: Digest32,
    ) -> Self {
        Self {
            credit_id: batch.batch_id.clone(),
            episode_id: batch.episode_id.clone(),
            outcome_digest,
            parent_credit_id: None,
            allocations: batch
                .allocations
                .iter()
                .map(|allocation| CanonicalCreditAllocationV1 {
                    target_id: allocation.target_id.clone(),
                    credit_q32: allocation.credit.raw(),
                })
                .collect(),
            conservation_residual_q32: batch.conservation_residual.raw(),
            rule_digest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct DatasetSnapshotV1 {
    #[serde(with = "id_wire")]
    pub dataset_id: StableId,
    #[serde(with = "digest_wire")]
    pub episode_range_digest: Digest32,
    pub row_count: u64,
    #[serde(with = "digest_wire")]
    pub schema_digest: Digest32,
    #[serde(with = "digest_wire")]
    pub split_policy_digest: Digest32,
    #[serde(with = "digest_wire")]
    pub deletion_cutoff_digest: Digest32,
    #[serde(with = "digest_wire")]
    pub content_digest: Digest32,
}

impl DatasetSnapshotV1 {
    #[must_use]
    pub fn from_dataset_receipt(
        receipt: &DatasetSnapshotReceiptV3,
        schema_digest: Digest32,
        split_policy_digest: Digest32,
    ) -> Self {
        let mut bytes = b"hepta.learning-ledger.dataset-episode-range.v1".to_vec();
        for digest in &receipt.snapshot.source_record_digests {
            bytes.extend_from_slice(digest.as_array());
        }
        Self {
            dataset_id: receipt.snapshot.snapshot_id.clone(),
            episode_range_digest: Digest32::of_bytes(&bytes),
            row_count: receipt.snapshot.source_record_digests.len() as u64,
            schema_digest,
            split_policy_digest,
            deletion_cutoff_digest: receipt.revocation_cut_digest,
            content_digest: receipt.snapshot.dataset_digest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct LearningDecisionV1 {
    #[serde(with = "id_wire")]
    pub decision_id: StableId,
    #[serde(with = "id_wire")]
    pub episode_id: StableId,
    #[serde(with = "digest_wire")]
    pub candidate_set_digest: Digest32,
    #[serde(with = "digest_wire")]
    pub policy_digest: Digest32,
    #[serde(with = "id_wire")]
    pub chosen_id: StableId,
    pub propensity_ppm: u32,
    #[serde(default, with = "optional_digest_wire")]
    pub random_seed_digest: Option<Digest32>,
}

impl LearningDecisionV1 {
    #[must_use]
    pub fn from_episode_decision(
        decision: &EpisodeDecision,
        candidate_set_digest: Digest32,
        policy_digest: Digest32,
        random_seed_digest: Option<Digest32>,
    ) -> Self {
        let ppm = (u128::from(decision.selected_propensity.raw()) * 1_000_000_u128
            + (1_u128 << 31))
            / (1_u128 << 32);
        Self {
            decision_id: decision.record_id.clone(),
            episode_id: decision.episode_id.clone(),
            candidate_set_digest,
            policy_digest,
            chosen_id: decision.selected_candidate_id.clone(),
            propensity_ppm: u32::try_from(ppm.min(1_000_000)).unwrap_or(1_000_000),
            random_seed_digest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CanonicalOutcomeWatermarkV1 {
    pub latest_observable_at: u64,
    #[serde(with = "digest_wire")]
    pub expected_delay_profile_digest: Digest32,
    pub terminality: String,
    #[serde(default, with = "optional_id_wire")]
    pub censoring_reason: Option<StableId>,
    #[serde(default, with = "optional_id_wire")]
    pub correction_predecessor: Option<StableId>,
    pub finalized_at: Option<u64>,
}

impl From<&OutcomeWatermarkV1> for CanonicalOutcomeWatermarkV1 {
    fn from(value: &OutcomeWatermarkV1) -> Self {
        Self {
            latest_observable_at: value.latest_observable_at,
            expected_delay_profile_digest: value.expected_delay_profile_digest,
            terminality: terminality_name(value.terminality).to_owned(),
            censoring_reason: value.censoring_reason.clone(),
            correction_predecessor: value.correction_predecessor.clone(),
            finalized_at: value.finalized_at,
        }
    }
}

impl CanonicalOutcomeWatermarkV1 {
    fn validate_protocol(&self) -> Result<(), ProtocolAdapterError> {
        require_nonzero(
            self.expected_delay_profile_digest,
            "expectedDelayProfileDigest",
        )?;
        validate_terminality(&self.terminality)?;
        match self.terminality.as_str() {
            "pending" => {
                if self.censoring_reason.is_some()
                    || self.correction_predecessor.is_some()
                    || self.finalized_at.is_some()
                {
                    return Err(ProtocolAdapterError::InvalidValue("outcomeWatermark"));
                }
            }
            "censored" => {
                if self.censoring_reason.is_none() || self.finalized_at.is_none() {
                    return Err(ProtocolAdapterError::InvalidValue("outcomeWatermark"));
                }
            }
            "terminal" => {
                if self.censoring_reason.is_some() || self.finalized_at.is_none() {
                    return Err(ProtocolAdapterError::InvalidValue("outcomeWatermark"));
                }
            }
            _ => unreachable!("terminality validated"),
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct LearningEpisodeV1 {
    #[serde(with = "id_wire")]
    pub episode_id: StableId,
    #[serde(with = "digest_wire")]
    pub run_snapshot_digest: Digest32,
    #[serde(with = "digest_vec_wire")]
    pub ordered_event_digests: Vec<Digest32>,
    pub terminality: String,
    pub outcome_watermark: CanonicalOutcomeWatermarkV1,
}

impl LearningEpisodeV1 {
    #[must_use]
    pub fn from_ledger_records(
        episode_id: StableId,
        run_snapshot_digest: Digest32,
        records: &[LedgerRecord],
        watermark: &OutcomeWatermarkV1,
    ) -> Self {
        let ordered_event_digests = records
            .iter()
            .filter(|record| event_episode_id(&record.event) == Some(&episode_id))
            .map(|record| record.event_digest)
            .collect();
        Self {
            episode_id,
            run_snapshot_digest,
            ordered_event_digests,
            terminality: terminality_name(watermark.terminality).to_owned(),
            outcome_watermark: watermark.into(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct OutcomeReceiptV1 {
    #[serde(with = "id_wire")]
    pub outcome_id: StableId,
    #[serde(with = "id_wire")]
    pub episode_id: StableId,
    #[serde(with = "id_wire")]
    pub observer_id: StableId,
    #[serde(with = "digest_wire")]
    pub observation_digest: Digest32,
    pub utility_vector: Vec<i64>,
    pub observed_at_unix_ms: u64,
    pub censoring: String,
}

impl OutcomeReceiptV1 {
    #[must_use]
    pub fn from_authenticated_outcome(
        outcome: &AuthenticatedOutcomeV1,
        observation_digest: Digest32,
    ) -> Self {
        let observed_at_unix_ms = outcome
            .observed_at
            .or(outcome.watermark.finalized_at)
            .unwrap_or(outcome.watermark.latest_observable_at);
        Self {
            outcome_id: outcome.outcome_id.clone(),
            episode_id: outcome.episode_id.clone(),
            observer_id: outcome.observer.principal_id.clone(),
            observation_digest,
            utility_vector: outcome
                .value
                .map_or_else(Vec::new, |value| vec![value.raw()]),
            observed_at_unix_ms,
            censoring: terminality_name(outcome.watermark.terminality).to_owned(),
        }
    }
}

pub trait CanonicalLearningProtocol: Serialize + DeserializeOwned + Sized {
    fn validate_protocol(&self) -> Result<(), ProtocolAdapterError>;

    fn to_canonical_json(&self) -> Result<Vec<u8>, ProtocolAdapterError> {
        self.validate_protocol()?;
        let bytes = serde_json::to_vec(self).map_err(|_| ProtocolAdapterError::Json)?;
        if bytes.len() > MAX_PROTOCOL_BYTES {
            return Err(ProtocolAdapterError::EncodedSize);
        }
        Ok(bytes)
    }

    fn from_canonical_json(bytes: &[u8]) -> Result<Self, ProtocolAdapterError> {
        if bytes.len() > MAX_PROTOCOL_BYTES {
            return Err(ProtocolAdapterError::EncodedSize);
        }
        let value: Self = serde_json::from_slice(bytes).map_err(|_| ProtocolAdapterError::Json)?;
        value.validate_protocol()?;
        Ok(value)
    }
}

impl CanonicalLearningProtocol for CreditAssignmentReceiptV1 {
    fn validate_protocol(&self) -> Result<(), ProtocolAdapterError> {
        require_nonzero(self.outcome_digest, "outcomeDigest")?;
        require_nonzero(self.rule_digest, "ruleDigest")?;
        if self.allocations.is_empty() || self.allocations.len() > 256 {
            return Err(ProtocolAdapterError::InvalidValue("allocations"));
        }
        let mut targets = self
            .allocations
            .iter()
            .map(|allocation| allocation.target_id.clone())
            .collect::<Vec<_>>();
        targets.sort();
        if targets.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(ProtocolAdapterError::InvalidValue("duplicate allocation target"));
        }
        Ok(())
    }
}

impl CanonicalLearningProtocol for DatasetSnapshotV1 {
    fn validate_protocol(&self) -> Result<(), ProtocolAdapterError> {
        if self.row_count == 0 {
            return Err(ProtocolAdapterError::InvalidValue("rowCount"));
        }
        for (label, digest) in [
            ("episodeRangeDigest", self.episode_range_digest),
            ("schemaDigest", self.schema_digest),
            ("splitPolicyDigest", self.split_policy_digest),
            ("deletionCutoffDigest", self.deletion_cutoff_digest),
            ("contentDigest", self.content_digest),
        ] {
            require_nonzero(digest, label)?;
        }
        Ok(())
    }
}

impl CanonicalLearningProtocol for LearningDecisionV1 {
    fn validate_protocol(&self) -> Result<(), ProtocolAdapterError> {
        require_nonzero(self.candidate_set_digest, "candidateSetDigest")?;
        require_nonzero(self.policy_digest, "policyDigest")?;
        if self.propensity_ppm == 0 || self.propensity_ppm > 1_000_000 {
            return Err(ProtocolAdapterError::InvalidValue("propensityPpm"));
        }
        if self.random_seed_digest.is_some_and(|digest| digest.is_zero()) {
            return Err(ProtocolAdapterError::InvalidValue("randomSeedDigest"));
        }
        Ok(())
    }
}

impl CanonicalLearningProtocol for LearningEpisodeV1 {
    fn validate_protocol(&self) -> Result<(), ProtocolAdapterError> {
        require_nonzero(self.run_snapshot_digest, "runSnapshotDigest")?;
        if self.ordered_event_digests.is_empty()
            || self.ordered_event_digests.len() > 4096
            || self
                .ordered_event_digests
                .iter()
                .any(|digest| (*digest).is_zero())
        {
            return Err(ProtocolAdapterError::InvalidValue("orderedEventDigests"));
        }
        validate_terminality(&self.terminality)?;
        self.outcome_watermark.validate_protocol()
    }
}

impl CanonicalLearningProtocol for OutcomeReceiptV1 {
    fn validate_protocol(&self) -> Result<(), ProtocolAdapterError> {
        require_nonzero(self.observation_digest, "observationDigest")?;
        validate_terminality(&self.censoring)?;
        if self.utility_vector.len() > 4096 {
            return Err(ProtocolAdapterError::InvalidValue("utilityVector"));
        }
        if self.censoring == "terminal" && self.utility_vector.is_empty() {
            return Err(ProtocolAdapterError::InvalidValue("utilityVector"));
        }
        if self.censoring != "terminal" && !self.utility_vector.is_empty() {
            return Err(ProtocolAdapterError::InvalidValue("utilityVector"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProtocolAdapterError {
    Json,
    EncodedSize,
    InvalidId,
    InvalidDigest,
    InvalidValue(&'static str),
}

impl fmt::Display for ProtocolAdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProtocolAdapterError {}

fn require_nonzero(
    digest: Digest32,
    label: &'static str,
) -> Result<(), ProtocolAdapterError> {
    if digest.is_zero() {
        return Err(ProtocolAdapterError::InvalidValue(label));
    }
    Ok(())
}

fn validate_terminality(value: &str) -> Result<(), ProtocolAdapterError> {
    match value {
        "pending" | "censored" | "terminal" => Ok(()),
        _ => Err(ProtocolAdapterError::InvalidValue("terminality")),
    }
}

fn terminality_name(value: OutcomeTerminalityV1) -> &'static str {
    match value {
        OutcomeTerminalityV1::Pending => "pending",
        OutcomeTerminalityV1::Censored => "censored",
        OutcomeTerminalityV1::Terminal => "terminal",
    }
}

fn event_episode_id(event: &LedgerEvent) -> Option<&StableId> {
    match event {
        LedgerEvent::Decision(value) => Some(&value.episode_id),
        LedgerEvent::Outcome(value) => Some(&value.episode_id),
        LedgerEvent::Credit(value) => Some(&value.episode_id),
        LedgerEvent::AuthenticatedOutcome(value) => Some(&value.episode_id),
        LedgerEvent::CreditBatch(value) => Some(&value.episode_id),
        LedgerEvent::Revocation(_) | LedgerEvent::UnlearningLineage(_) => None,
    }
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(HEX[(byte >> 4) as usize]));
        output.push(char::from(HEX[(byte & 0x0f) as usize]));
    }
    output
}

fn decode_digest(value: &str) -> Result<Digest32, ProtocolAdapterError> {
    if value.len() != 64 {
        return Err(ProtocolAdapterError::InvalidDigest);
    }
    let mut output = [0_u8; 32];
    let bytes = value.as_bytes();
    for (index, target) in output.iter_mut().enumerate() {
        let high = decode_nibble(bytes[index * 2])?;
        let low = decode_nibble(bytes[index * 2 + 1])?;
        *target = (high << 4) | low;
    }
    Ok(Digest32::from_array(output))
}

fn decode_nibble(value: u8) -> Result<u8, ProtocolAdapterError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(ProtocolAdapterError::InvalidDigest),
    }
}

mod id_wire {
    use super::*;
    use serde::Deserializer;
    use serde::Serializer;

    pub fn serialize<S: Serializer>(value: &StableId, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(value.as_str())
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<StableId, D::Error> {
        let value = String::deserialize(deserializer)?;
        StableId::new(value).map_err(serde::de::Error::custom)
    }
}

mod optional_id_wire {
    use super::*;
    use serde::Deserializer;
    use serde::Serializer;

    pub fn serialize<S: Serializer>(
        value: &Option<StableId>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        match value {
            Some(value) => serializer.serialize_some(value.as_str()),
            None => serializer.serialize_none(),
        }
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<StableId>, D::Error> {
        let value = Option::<String>::deserialize(deserializer)?;
        value
            .map(|value| StableId::new(value).map_err(serde::de::Error::custom))
            .transpose()
    }
}

mod digest_wire {
    use super::*;
    use serde::Deserializer;
    use serde::Serializer;

    pub fn serialize<S: Serializer>(value: &Digest32, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&encode_hex(value.as_array()))
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Digest32, D::Error> {
        let value = String::deserialize(deserializer)?;
        decode_digest(&value).map_err(serde::de::Error::custom)
    }
}

mod optional_digest_wire {
    use super::*;
    use serde::Deserializer;
    use serde::Serializer;

    pub fn serialize<S: Serializer>(
        value: &Option<Digest32>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        match value {
            Some(value) => serializer.serialize_some(&encode_hex(value.as_array())),
            None => serializer.serialize_none(),
        }
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<Digest32>, D::Error> {
        let value = Option::<String>::deserialize(deserializer)?;
        value
            .map(|value| decode_digest(&value).map_err(serde::de::Error::custom))
            .transpose()
    }
}

mod digest_vec_wire {
    use super::*;
    use serde::Deserializer;
    use serde::Serializer;

    pub fn serialize<S: Serializer>(values: &[Digest32], serializer: S) -> Result<S::Ok, S::Error> {
        let encoded = values
            .iter()
            .map(|value| encode_hex(value.as_array()))
            .collect::<Vec<_>>();
        encoded.serialize(serializer)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Vec<Digest32>, D::Error> {
        let encoded = Vec::<String>::deserialize(deserializer)?;
        encoded
            .into_iter()
            .map(|value| decode_digest(&value).map_err(serde::de::Error::custom))
            .collect()
    }
}

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod tests;

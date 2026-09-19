//! Canonical registry protocol names and strict JSON wire adapters for
//! `learning.ledger` public contracts. These structs mirror
//! `docs/contracts/PROTOCOL_SCHEMAS.json`: field order is schema order and
//! unknown fields are rejected during decoding.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AuthenticatedOutcomeV2;
use crate::CreditAllocationBatchV2;
use crate::DatasetSnapshotReceiptV3;
use crate::DurableOutcomeTerminalityV2;
use crate::EpisodeDecision;
use crate::LedgerSnapshot;

const MAX_PROTOCOL_BYTES: usize = 262_144;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct LearningDecisionV1 {
    pub decision_id: String,
    pub episode_id: String,
    pub candidate_set_digest: String,
    pub policy_digest: String,
    pub chosen_id: String,
    pub propensity_ppm: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub random_seed_digest: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct OutcomeReceiptV1 {
    pub outcome_id: String,
    pub episode_id: String,
    pub observer_id: String,
    pub observation_digest: String,
    pub utility_vector: Vec<i64>,
    pub observed_at_unix_ms: u64,
    pub censoring: OutcomeCensoringV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OutcomeCensoringV1 {
    Observed,
    Censored,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CreditAllocationV1Wire {
    pub target_id: String,
    pub credit_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct CreditAssignmentReceiptV1 {
    pub credit_id: String,
    pub episode_id: String,
    pub outcome_digest: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_credit_id: Option<String>,
    pub allocations: Vec<CreditAllocationV1Wire>,
    pub conservation_residual_q32: i64,
    pub rule_digest: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LearningEpisodeTerminalityV1 {
    Pending,
    Censored,
    Terminal,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct EpisodeOutcomeWatermarkV1 {
    pub latest_observable_at_unix_ms: u64,
    pub terminality: LearningEpisodeTerminalityV1,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub finalized_at_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct LearningEpisodeV1 {
    pub episode_id: String,
    pub run_snapshot_digest: String,
    pub ordered_event_digests: Vec<String>,
    pub terminality: LearningEpisodeTerminalityV1,
    pub outcome_watermark: EpisodeOutcomeWatermarkV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct DatasetSnapshotV1 {
    pub dataset_id: String,
    pub episode_range_digest: String,
    pub row_count: u64,
    pub schema_digest: String,
    pub split_policy_digest: String,
    pub deletion_cutoff_digest: String,
    pub content_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProtocolAdapterError {
    EmptyDigest(&'static str),
    NonTerminalOutcome,
    MissingOutcome,
    EpisodeNotFound(String),
    InvalidProbability,
    WireTooLarge,
    Json,
}

impl fmt::Display for ProtocolAdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProtocolAdapterError {}

pub trait CanonicalJsonProtocol: Sized + Serialize + for<'de> Deserialize<'de> {
    fn encode_canonical_json(&self) -> Result<Vec<u8>, ProtocolAdapterError> {
        let bytes = serde_json::to_vec(self).map_err(|_| ProtocolAdapterError::Json)?;
        if bytes.len() > MAX_PROTOCOL_BYTES {
            return Err(ProtocolAdapterError::WireTooLarge);
        }
        Ok(bytes)
    }

    fn decode_canonical_json(bytes: &[u8]) -> Result<Self, ProtocolAdapterError> {
        if bytes.is_empty() || bytes.len() > MAX_PROTOCOL_BYTES {
            return Err(ProtocolAdapterError::WireTooLarge);
        }
        serde_json::from_slice(bytes).map_err(|_| ProtocolAdapterError::Json)
    }
}

impl<T> CanonicalJsonProtocol for T where T: Sized + Serialize + for<'de> Deserialize<'de> {}

pub fn decision_to_canonical_v1(
    decision: &EpisodeDecision,
    candidate_set_digest: Digest32,
    policy_digest: Digest32,
    random_seed_digest: Option<Digest32>,
) -> Result<LearningDecisionV1, ProtocolAdapterError> {
    require_digest(candidate_set_digest, "candidate set")?;
    require_digest(policy_digest, "policy")?;
    if random_seed_digest.is_some_and(|digest| digest.is_zero()) {
        return Err(ProtocolAdapterError::EmptyDigest("random seed"));
    }
    let numerator = u128::from(decision.selected_propensity.raw()) * 1_000_000_u128;
    let rounded = (numerator + (1_u128 << 31)) >> 32;
    let propensity_ppm =
        u32::try_from(rounded).map_err(|_| ProtocolAdapterError::InvalidProbability)?;
    if propensity_ppm > 1_000_000 {
        return Err(ProtocolAdapterError::InvalidProbability);
    }
    Ok(LearningDecisionV1 {
        decision_id: decision.record_id.to_string(),
        episode_id: decision.episode_id.to_string(),
        candidate_set_digest: candidate_set_digest.to_string(),
        policy_digest: policy_digest.to_string(),
        chosen_id: decision.selected_candidate_id.to_string(),
        propensity_ppm,
        random_seed_digest: random_seed_digest.map(|digest| digest.to_string()),
    })
}

pub fn outcome_to_canonical_v1(
    outcome: &AuthenticatedOutcomeV2,
) -> Result<OutcomeReceiptV1, ProtocolAdapterError> {
    if outcome.terminality != DurableOutcomeTerminalityV2::Terminal {
        return Err(ProtocolAdapterError::NonTerminalOutcome);
    }
    let observed_at = outcome
        .observed_at
        .ok_or(ProtocolAdapterError::MissingOutcome)?;
    let value = outcome.value.ok_or(ProtocolAdapterError::MissingOutcome)?;
    let mut bytes = b"hepta.learning-ledger.outcome-receipt.v1".to_vec();
    push_id(&mut bytes, &outcome.outcome_id);
    push_id(&mut bytes, &outcome.episode_id);
    push_id(&mut bytes, &outcome.observer_id);
    bytes.extend_from_slice(&observed_at.to_be_bytes());
    bytes.extend_from_slice(&value.raw().to_be_bytes());
    bytes.extend_from_slice(outcome.unit_profile_digest.as_array());
    bytes.extend_from_slice(outcome.support_digest.as_array());
    bytes.extend_from_slice(outcome.evidence_digest.as_array());
    Ok(OutcomeReceiptV1 {
        outcome_id: outcome.outcome_id.to_string(),
        episode_id: outcome.episode_id.to_string(),
        observer_id: outcome.observer_id.to_string(),
        observation_digest: Digest32::of_bytes(&bytes).to_string(),
        utility_vector: vec![value.raw()],
        observed_at_unix_ms: observed_at,
        censoring: OutcomeCensoringV1::Observed,
    })
}

pub fn credit_batch_to_canonical_receipt(
    batch: &CreditAllocationBatchV2,
    outcome_digest: Digest32,
) -> Result<CreditAssignmentReceiptV1, ProtocolAdapterError> {
    require_digest(outcome_digest, "outcome")?;
    require_digest(batch.rule_digest, "credit rule")?;
    Ok(CreditAssignmentReceiptV1 {
        credit_id: batch.batch_id.to_string(),
        episode_id: batch.episode_id.to_string(),
        outcome_digest: outcome_digest.to_string(),
        parent_credit_id: batch.parent_credit_id.as_ref().map(ToString::to_string),
        allocations: batch
            .allocations
            .iter()
            .map(|allocation| CreditAllocationV1Wire {
                target_id: allocation.target_id.to_string(),
                credit_q32: allocation.credit.raw(),
            })
            .collect(),
        conservation_residual_q32: batch.conservation_residual.raw(),
        rule_digest: batch.rule_digest.to_string(),
    })
}

pub fn episode_to_canonical_v1(
    snapshot: &LedgerSnapshot,
    episode_id: &StableId,
    run_snapshot_digest: Digest32,
) -> Result<LearningEpisodeV1, ProtocolAdapterError> {
    require_digest(run_snapshot_digest, "run snapshot")?;
    let mut ordered_event_digests = Vec::new();
    let mut watermark = 0_u64;
    let mut terminality = LearningEpisodeTerminalityV1::Pending;
    let mut finalized_at = None;
    for record in snapshot.records() {
        let belongs = match &record.event {
            crate::LedgerEvent::Decision(value) => &value.episode_id == episode_id,
            crate::LedgerEvent::DecisionV2(value) => &value.decision.episode_id == episode_id,
            crate::LedgerEvent::Outcome(value) => &value.episode_id == episode_id,
            crate::LedgerEvent::OutcomeV2(value) => &value.episode_id == episode_id,
            crate::LedgerEvent::Credit(value) => &value.episode_id == episode_id,
            crate::LedgerEvent::CreditBatchV2(value) => &value.episode_id == episode_id,
            crate::LedgerEvent::Revocation(_) | crate::LedgerEvent::UnlearningV1(_) => false,
        };
        if belongs {
            ordered_event_digests.push(record.event_digest.to_string());
        }
        if let crate::LedgerEvent::OutcomeV2(value) = &record.event
            && &value.episode_id == episode_id
        {
            watermark = watermark.max(value.latest_observable_at);
            finalized_at = value.finalized_at.or(finalized_at);
            terminality = match value.terminality {
                DurableOutcomeTerminalityV2::Pending => LearningEpisodeTerminalityV1::Pending,
                DurableOutcomeTerminalityV2::Censored => LearningEpisodeTerminalityV1::Censored,
                DurableOutcomeTerminalityV2::Terminal => LearningEpisodeTerminalityV1::Terminal,
            };
        }
    }
    if ordered_event_digests.is_empty() {
        return Err(ProtocolAdapterError::EpisodeNotFound(episode_id.to_string()));
    }
    Ok(LearningEpisodeV1 {
        episode_id: episode_id.to_string(),
        run_snapshot_digest: run_snapshot_digest.to_string(),
        ordered_event_digests,
        terminality,
        outcome_watermark: EpisodeOutcomeWatermarkV1 {
            latest_observable_at_unix_ms: watermark,
            terminality,
            finalized_at_unix_ms: finalized_at,
        },
    })
}

pub fn dataset_receipt_to_canonical_v1(
    receipt: &DatasetSnapshotReceiptV3,
    schema_digest: Digest32,
    split_policy_digest: Digest32,
) -> Result<DatasetSnapshotV1, ProtocolAdapterError> {
    require_digest(schema_digest, "dataset schema")?;
    require_digest(split_policy_digest, "split policy")?;
    let snapshot = &receipt.snapshot;
    let mut range = b"hepta.learning-ledger.dataset-episode-range.v1".to_vec();
    range.extend_from_slice(snapshot.ledger_head_digest.as_array());
    range.extend_from_slice(&snapshot.eligible_frontier.to_be_bytes());
    range.extend_from_slice(&snapshot.outcome_watermark.to_be_bytes());
    for digest in &snapshot.source_record_digests {
        range.extend_from_slice(digest.as_array());
    }
    let mut deletion = b"hepta.learning-ledger.dataset-deletion-cutoff.v1".to_vec();
    deletion.extend_from_slice(receipt.correction_cut_digest.as_array());
    deletion.extend_from_slice(receipt.revocation_cut_digest.as_array());
    Ok(DatasetSnapshotV1 {
        dataset_id: snapshot.snapshot_id.to_string(),
        episode_range_digest: Digest32::of_bytes(&range).to_string(),
        row_count: snapshot.source_record_digests.len() as u64,
        schema_digest: schema_digest.to_string(),
        split_policy_digest: split_policy_digest.to_string(),
        deletion_cutoff_digest: Digest32::of_bytes(&deletion).to_string(),
        content_digest: snapshot.dataset_digest.to_string(),
    })
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), ProtocolAdapterError> {
    if digest.is_zero() {
        return Err(ProtocolAdapterError::EmptyDigest(label));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_json_rejects_unknown_critical_fields() {
        let payload = br#"{"decisionId":"d","episodeId":"e","candidateSetDigest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","policyDigest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","chosenId":"c","propensityPpm":1,"unknown":true}"#;
        assert_eq!(
            LearningDecisionV1::decode_canonical_json(payload),
            Err(ProtocolAdapterError::Json)
        );
    }
}

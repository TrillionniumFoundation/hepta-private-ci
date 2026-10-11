//! Canonical JSON adapters for the registered learning-ledger protocols.
//!
//! These structs use the exact canonical contract names and field spellings from
//! docs/contracts/PROTOCOL_SCHEMAS.json. They are compatibility views over the
//! stronger durable V2 records; they do not weaken product admission. Unknown
//! fields are rejected and encoding is bounded to the registered 256 KiB limit.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;

use crate::AuthenticatedDecisionRecordV2;
use crate::AuthenticatedOutcomeRecordV2;
use crate::AuthenticatedOutcomeTerminality;
use crate::CreditAllocationBatchRecordV2;
use crate::DatasetSnapshotReceiptV3;
use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSnapshot;

const MAX_CANONICAL_JSON: usize = 262_144;
const DATASET_SCHEMA_DOMAIN: &[u8] = b"hepta.learning-ledger.dataset-v1.adapter-schema.v1";
const DATASET_EPISODE_RANGE_DOMAIN: &[u8] = b"hepta.learning-ledger.dataset-v1.episode-range.v1";
const DATASET_DELETION_CUTOFF_DOMAIN: &[u8] =
    b"hepta.learning-ledger.dataset-v1.deletion-cutoff.v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LearningDecisionV1 {
    pub decision_id: String,
    pub episode_id: String,
    pub candidate_set_digest: String,
    pub policy_digest: String,
    pub chosen_id: String,
    pub propensity_ppm: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub random_seed_digest: Option<String>,
}

impl From<&AuthenticatedDecisionRecordV2> for LearningDecisionV1 {
    fn from(value: &AuthenticatedDecisionRecordV2) -> Self {
        Self {
            decision_id: value.record_id.to_string(),
            episode_id: value.episode_id.to_string(),
            candidate_set_digest: candidate_set_digest(&value.candidate_ids).to_string(),
            policy_digest: value.policy_digest.to_string(),
            chosen_id: value.selected_candidate_id.to_string(),
            propensity_ppm: probability_ppm(value.selected_propensity.raw()),
            random_seed_digest: None,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OutcomeCensoringV1 {
    None,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeReceiptV1 {
    pub outcome_id: String,
    pub episode_id: String,
    pub observer_id: String,
    pub observation_digest: String,
    pub utility_vector: Vec<i64>,
    pub observed_at_unix_ms: u64,
    pub censoring: OutcomeCensoringV1,
}

impl TryFrom<&AuthenticatedOutcomeRecordV2> for OutcomeReceiptV1 {
    type Error = LearningProtocolError;

    fn try_from(value: &AuthenticatedOutcomeRecordV2) -> Result<Self, Self::Error> {
        if value.terminality != AuthenticatedOutcomeTerminality::Terminal {
            return Err(LearningProtocolError::NotRepresentable(
                "OutcomeReceiptV1 requires a terminal observed value",
            ));
        }
        let observed_at = value
            .observed_at
            .ok_or(LearningProtocolError::NotRepresentable(
                "OutcomeReceiptV1 requires observedAtUnixMs",
            ))?;
        let utility = value.value.ok_or(LearningProtocolError::NotRepresentable(
            "OutcomeReceiptV1 requires utilityVector",
        ))?;
        Ok(Self {
            outcome_id: value.outcome_id.to_string(),
            episode_id: value.episode_id.to_string(),
            observer_id: value.observer_id.to_string(),
            observation_digest: value.support_digest.to_string(),
            utility_vector: vec![utility.raw()],
            observed_at_unix_ms: observed_at,
            censoring: OutcomeCensoringV1::None,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CreditAllocationV1 {
    pub target_id: String,
    pub credit_q32: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CreditAssignmentReceiptV1 {
    pub credit_id: String,
    pub episode_id: String,
    pub outcome_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_credit_id: Option<String>,
    pub allocations: Vec<CreditAllocationV1>,
    pub conservation_residual_q32: i64,
    pub rule_digest: String,
}

impl CreditAssignmentReceiptV1 {
    pub fn from_batch(
        value: &CreditAllocationBatchRecordV2,
        snapshot: &LedgerSnapshot,
    ) -> Result<Self, LearningProtocolError> {
        let outcome_digest = snapshot
            .records()
            .iter()
            .find_map(|record| match &record.event {
                LedgerEvent::AuthenticatedOutcomeV2(outcome)
                    if outcome.outcome_id == value.outcome_id =>
                {
                    Some(record.event_digest)
                }
                _ => None,
            })
            .ok_or(LearningProtocolError::NotRepresentable(
                "credit outcome is absent from snapshot",
            ))?;
        Ok(Self {
            credit_id: value.batch_id.to_string(),
            episode_id: value.episode_id.to_string(),
            outcome_digest: outcome_digest.to_string(),
            parent_credit_id: None,
            allocations: value
                .allocations
                .iter()
                .map(|allocation| CreditAllocationV1 {
                    target_id: allocation.target_artifact_id.to_string(),
                    credit_q32: allocation.credit.raw(),
                })
                .collect(),
            conservation_residual_q32: value.conservation_residual.raw(),
            rule_digest: value.support_digest.to_string(),
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DatasetSnapshotV1 {
    pub dataset_id: String,
    pub episode_range_digest: String,
    pub row_count: u64,
    pub schema_digest: String,
    pub split_policy_digest: String,
    pub deletion_cutoff_digest: String,
    pub content_digest: String,
}

impl TryFrom<&DatasetSnapshotReceiptV3> for DatasetSnapshotV1 {
    type Error = LearningProtocolError;

    fn try_from(value: &DatasetSnapshotReceiptV3) -> Result<Self, Self::Error> {
        let row_count = u64::try_from(value.snapshot.source_record_digests.len())
            .map_err(|_| LearningProtocolError::Bounds)?;
        let episode_range_digest = digest_list(
            DATASET_EPISODE_RANGE_DOMAIN,
            &value.snapshot.source_record_digests,
        );
        let deletion_cutoff_digest = digest_list(
            DATASET_DELETION_CUTOFF_DOMAIN,
            &[value.correction_cut_digest, value.revocation_cut_digest],
        );
        Ok(Self {
            dataset_id: value.snapshot.snapshot_id.to_string(),
            episode_range_digest: episode_range_digest.to_string(),
            row_count,
            schema_digest: Digest32::of_bytes(DATASET_SCHEMA_DOMAIN).to_string(),
            split_policy_digest: value.inclusion_policy_digest.to_string(),
            deletion_cutoff_digest: deletion_cutoff_digest.to_string(),
            content_digest: value.snapshot.dataset_digest.to_string(),
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EpisodeTerminalityV1 {
    Censored,
    Terminal,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OutcomeWatermarkTerminalityV1 {
    Censored,
    Terminal,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeWatermarkProtocolV1 {
    pub watermark_id: String,
    pub episode_id: String,
    pub observer_id: String,
    pub latest_observable_unix_ms: u64,
    pub expected_delay_profile_digest: String,
    pub terminality: OutcomeWatermarkTerminalityV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub censoring_reason: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub correction_predecessor: Option<String>,
    pub finalized_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LearningEpisodeV1 {
    pub episode_id: String,
    pub run_snapshot_digest: String,
    pub ordered_event_digests: Vec<String>,
    pub terminality: EpisodeTerminalityV1,
    pub outcome_watermark: OutcomeWatermarkProtocolV1,
}

impl LearningEpisodeV1 {
    pub fn from_snapshot(
        snapshot: &LedgerSnapshot,
        episode_id: &StableId,
    ) -> Result<Self, LearningProtocolError> {
        let core = LearningLedger::from_snapshot(snapshot.clone())?;
        let active_ids: BTreeSet<_> = core
            .active_records()
            .into_iter()
            .map(|record| record.event.record_id().clone())
            .collect();

        let decision = snapshot
            .records()
            .iter()
            .find_map(|record| match &record.event {
                LedgerEvent::AuthenticatedDecisionV2(value)
                    if &value.episode_id == episode_id && active_ids.contains(&value.record_id) =>
                {
                    Some(value)
                }
                _ => None,
            })
            .ok_or(LearningProtocolError::NotRepresentable(
                "LearningEpisodeV1 requires an active authenticated decision",
            ))?;

        let outcome = snapshot
            .records()
            .iter()
            .rev()
            .find_map(|record| match &record.event {
                LedgerEvent::AuthenticatedOutcomeV2(value)
                    if &value.episode_id == episode_id && active_ids.contains(&value.record_id) =>
                {
                    Some(value)
                }
                _ => None,
            })
            .ok_or(LearningProtocolError::NotRepresentable(
                "LearningEpisodeV1 requires a finalized outcome",
            ))?;
        let finalized = outcome
            .finalized_at
            .ok_or(LearningProtocolError::NotRepresentable(
                "OutcomeWatermarkV1 requires finalizedUnixMs",
            ))?;
        let (terminality, watermark_terminality) = match outcome.terminality {
            AuthenticatedOutcomeTerminality::Terminal => (
                EpisodeTerminalityV1::Terminal,
                OutcomeWatermarkTerminalityV1::Terminal,
            ),
            AuthenticatedOutcomeTerminality::Censored => (
                EpisodeTerminalityV1::Censored,
                OutcomeWatermarkTerminalityV1::Censored,
            ),
            AuthenticatedOutcomeTerminality::Pending => {
                return Err(LearningProtocolError::NotRepresentable(
                    "LearningEpisodeV1 cannot encode an unfinalized pending episode",
                ));
            }
        };

        let mut episode_record_ids = BTreeSet::new();
        let mut ordered_event_digests = Vec::new();
        for record in snapshot.records() {
            let belongs = match &record.event {
                LedgerEvent::AuthenticatedDecisionV2(value) => &value.episode_id == episode_id,
                LedgerEvent::AuthenticatedOutcomeV2(value) => &value.episode_id == episode_id,
                LedgerEvent::CreditBatchV2(value) => &value.episode_id == episode_id,
                _ => false,
            };
            if belongs {
                episode_record_ids.insert(record.event.record_id().clone());
                ordered_event_digests.push(record.event_digest.to_string());
            }
        }
        for record in snapshot.records() {
            let lineage = match &record.event {
                LedgerEvent::Revocation(value) => {
                    episode_record_ids.contains(&value.target_record_id)
                }
                LedgerEvent::UnlearningLineageV1(value) => {
                    episode_record_ids.contains(&value.source_record_id)
                }
                _ => false,
            };
            if lineage {
                ordered_event_digests.push(record.event_digest.to_string());
            }
        }

        Ok(Self {
            episode_id: episode_id.to_string(),
            run_snapshot_digest: decision.run_snapshot_digest.to_string(),
            ordered_event_digests,
            terminality,
            outcome_watermark: OutcomeWatermarkProtocolV1 {
                watermark_id: outcome.outcome_id.to_string(),
                episode_id: episode_id.to_string(),
                observer_id: outcome.observer_id.to_string(),
                latest_observable_unix_ms: outcome.latest_observable_at,
                expected_delay_profile_digest: outcome.expected_delay_profile_digest.to_string(),
                terminality: watermark_terminality,
                censoring_reason: outcome.censoring_reason.as_ref().map(ToString::to_string),
                correction_predecessor: outcome
                    .correction_predecessor
                    .as_ref()
                    .map(ToString::to_string),
                finalized_unix_ms: finalized,
            },
        })
    }
}

pub fn encode_learning_decision_v1(
    value: &LearningDecisionV1,
) -> Result<Vec<u8>, LearningProtocolError> {
    encode(value)
}

pub fn decode_learning_decision_v1(
    bytes: &[u8],
) -> Result<LearningDecisionV1, LearningProtocolError> {
    decode(bytes)
}

pub fn encode_outcome_receipt_v1(
    value: &OutcomeReceiptV1,
) -> Result<Vec<u8>, LearningProtocolError> {
    encode(value)
}

pub fn decode_outcome_receipt_v1(bytes: &[u8]) -> Result<OutcomeReceiptV1, LearningProtocolError> {
    decode(bytes)
}

pub fn encode_credit_assignment_receipt_v1(
    value: &CreditAssignmentReceiptV1,
) -> Result<Vec<u8>, LearningProtocolError> {
    encode(value)
}

pub fn decode_credit_assignment_receipt_v1(
    bytes: &[u8],
) -> Result<CreditAssignmentReceiptV1, LearningProtocolError> {
    decode(bytes)
}

pub fn encode_dataset_snapshot_v1(
    value: &DatasetSnapshotV1,
) -> Result<Vec<u8>, LearningProtocolError> {
    encode(value)
}

pub fn decode_dataset_snapshot_v1(
    bytes: &[u8],
) -> Result<DatasetSnapshotV1, LearningProtocolError> {
    decode(bytes)
}

pub fn encode_learning_episode_v1(
    value: &LearningEpisodeV1,
) -> Result<Vec<u8>, LearningProtocolError> {
    encode(value)
}

pub fn decode_learning_episode_v1(
    bytes: &[u8],
) -> Result<LearningEpisodeV1, LearningProtocolError> {
    decode(bytes)
}

fn encode<T: Serialize>(value: &T) -> Result<Vec<u8>, LearningProtocolError> {
    let bytes = serde_json::to_vec(value).map_err(|_| LearningProtocolError::Json)?;
    if bytes.len() > MAX_CANONICAL_JSON {
        return Err(LearningProtocolError::Bounds);
    }
    Ok(bytes)
}

fn decode<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, LearningProtocolError> {
    if bytes.len() > MAX_CANONICAL_JSON {
        return Err(LearningProtocolError::Bounds);
    }
    serde_json::from_slice(bytes).map_err(|_| LearningProtocolError::Json)
}

fn probability_ppm(raw: u64) -> u32 {
    let scaled = u128::from(raw) * 1_000_000_u128 / (1_u128 << 32);
    u32::try_from(scaled).unwrap_or(1_000_000)
}

fn candidate_set_digest(ids: &[StableId]) -> Digest32 {
    let mut ids = ids.to_vec();
    ids.sort();
    let mut bytes = b"hepta.learning-ledger.protocol.candidate-set.v1".to_vec();
    bytes.extend_from_slice(&(ids.len() as u64).to_be_bytes());
    for id in ids {
        let raw = id.as_str().as_bytes();
        bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
        bytes.extend_from_slice(raw);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_list(domain: &[u8], values: &[Digest32]) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        bytes.extend_from_slice(value.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningProtocolError {
    Ledger(LedgerError),
    Json,
    Bounds,
    NotRepresentable(&'static str),
}

impl fmt::Display for LearningProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningProtocolError {}

impl From<LedgerError> for LearningProtocolError {
    fn from(value: LedgerError) -> Self {
        Self::Ledger(value)
    }
}

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod tests;

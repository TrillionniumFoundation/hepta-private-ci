//! Complete untrusted Outcome data supplied by the independent Observer.
//! Conversion preserves the original production-v2 signing fields. It creates
//! no verified evidence or receipt; the actual A/C producer still authenticates
//! the supplied signature against its own current trust and task publication.

use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;

use super::deployment_error;
use super::learning_data::PrincipalData;
use super::learning_data::SignedEvidenceData;
use super::learning_data::required_option;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalSignedOutcomeData {
    outcome: OriginalOutcomeData,
    signed: SignedEvidenceData,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalOutcomeData {
    record_id: String,
    outcome_id: String,
    episode_id: String,
    observer: PrincipalData,
    #[serde(deserialize_with = "required_option")]
    observed_at: Option<u64>,
    /// Exact signed FixedQ32::raw() bits, without rounding or rescaling.
    #[serde(deserialize_with = "required_option")]
    value_raw_q32: Option<i64>,
    unit_profile_digest: [u8; 32],
    support_digest: [u8; 32],
    watermark: OriginalOutcomeWatermarkData,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalOutcomeWatermarkData {
    latest_observable_at: u64,
    expected_delay_profile_digest: [u8; 32],
    terminality: OriginalOutcomeTerminalityData,
    #[serde(deserialize_with = "required_option")]
    censoring_reason: Option<String>,
    #[serde(deserialize_with = "required_option")]
    correction_predecessor: Option<String>,
    #[serde(deserialize_with = "required_option")]
    finalized_at: Option<u64>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum OriginalOutcomeTerminalityData {
    Pending,
    Censored,
    Terminal,
}

impl OriginalSignedOutcomeData {
    pub(super) fn into_original(
        self,
    ) -> Result<(AuthenticatedOutcomeV1, SignedLearningEvidenceV1), AgentdError> {
        let data = self.outcome;
        let watermark = data.watermark;
        let outcome = AuthenticatedOutcomeV1 {
            record_id: StableId::new(data.record_id).map_err(deployment_error)?,
            outcome_id: StableId::new(data.outcome_id).map_err(deployment_error)?,
            episode_id: StableId::new(data.episode_id).map_err(deployment_error)?,
            observer: PrincipalData::original(&data.observer)?,
            observed_at: data.observed_at,
            value: data.value_raw_q32.map(FixedQ32::from_raw),
            unit_profile_digest: Digest32::from_array(data.unit_profile_digest),
            support_digest: Digest32::from_array(data.support_digest),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: watermark.latest_observable_at,
                expected_delay_profile_digest: Digest32::from_array(
                    watermark.expected_delay_profile_digest,
                ),
                terminality: match watermark.terminality {
                    OriginalOutcomeTerminalityData::Pending => OutcomeTerminalityV1::Pending,
                    OriginalOutcomeTerminalityData::Censored => OutcomeTerminalityV1::Censored,
                    OriginalOutcomeTerminalityData::Terminal => OutcomeTerminalityV1::Terminal,
                },
                censoring_reason: watermark
                    .censoring_reason
                    .map(StableId::new)
                    .transpose()
                    .map_err(deployment_error)?,
                correction_predecessor: watermark
                    .correction_predecessor
                    .map(StableId::new)
                    .transpose()
                    .map_err(deployment_error)?,
                finalized_at: watermark.finalized_at,
            },
        };
        let signed = SignedEvidenceData::original(&self.signed)?;
        Ok((outcome, signed))
    }
}

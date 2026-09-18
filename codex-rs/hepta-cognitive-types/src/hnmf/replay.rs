use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::CanonicalJsonV1;
use super::EpisodeIdV1;
use super::EventIdV1;
use super::HnmfContractError;
use super::MAX_REPLAY_SELECTION;
use super::PPM;
use super::ResourceReceiptV1;
use super::ValidateHnmfV1;
use super::ppm;
use super::signed_ppm;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeSignalV1 {
    episode_id: EpisodeIdV1,
    utility_delta_ppm: i32,
    prediction_error_ppm: u32,
    novelty_ppm: u32,
    risk_ppm: u32,
    ood_ppm: u32,
    #[serde(with = "super::wire::digest")]
    observer_digest: Digest32,
}

impl OutcomeSignalV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        episode_id: EpisodeIdV1,
        utility_delta_ppm: i32,
        prediction_error_ppm: u32,
        novelty_ppm: u32,
        risk_ppm: u32,
        ood_ppm: u32,
        observer_digest: Digest32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            episode_id,
            utility_delta_ppm,
            prediction_error_ppm,
            novelty_ppm,
            risk_ppm,
            ood_ppm,
            observer_digest,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn modulator_ppm(&self) -> Result<i32, HnmfContractError> {
        self.validate()?;
        let positive = i64::from(self.utility_delta_ppm)
            + i64::from(self.prediction_error_ppm) / 2
            + i64::from(self.novelty_ppm) / 4;
        let negative = i64::from(self.risk_ppm) + i64::from(self.ood_ppm);
        Ok((positive - negative).clamp(-PPM, PPM) as i32)
    }
}

impl ValidateHnmfV1 for OutcomeSignalV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.episode_id == 0 || self.observer_digest.is_zero() {
            return Err(HnmfContractError::Invalid(
                "outcome episode and observer digest must be non-zero",
            ));
        }
        signed_ppm(self.utility_delta_ppm, "outcome utility delta")?;
        ppm(self.prediction_error_ppm, "outcome prediction error")?;
        ppm(self.novelty_ppm, "outcome novelty")?;
        ppm(self.risk_ppm, "outcome risk")?;
        ppm(self.ood_ppm, "outcome OOD")
    }
}

impl CanonicalJsonV1 for OutcomeSignalV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.outcome-signal.v1";
    const MAX_ENCODED_BYTES: usize = 32_768;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplayCandidateV1 {
    event_id: EventIdV1,
    source_bucket: u16,
    expected_utility_gain_ppm: u32,
    prediction_error_ppm: u32,
    novelty_ppm: u32,
    rarity_ppm: u32,
    forgetting_risk_ppm: u32,
    coverage_need_ppm: u32,
    privacy_allowed: bool,
}

impl ReplayCandidateV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        event_id: EventIdV1,
        source_bucket: u16,
        expected_utility_gain_ppm: u32,
        prediction_error_ppm: u32,
        novelty_ppm: u32,
        rarity_ppm: u32,
        forgetting_risk_ppm: u32,
        coverage_need_ppm: u32,
        privacy_allowed: bool,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            event_id,
            source_bucket,
            expected_utility_gain_ppm,
            prediction_error_ppm,
            novelty_ppm,
            rarity_ppm,
            forgetting_risk_ppm,
            coverage_need_ppm,
            privacy_allowed,
        };
        value.validate()?;
        Ok(value)
    }

    pub const fn event_id(&self) -> EventIdV1 {
        self.event_id
    }

    pub const fn source_bucket(&self) -> u16 {
        self.source_bucket
    }

    pub fn score(&self) -> Result<u64, HnmfContractError> {
        self.validate()?;
        Ok([
            self.expected_utility_gain_ppm,
            self.prediction_error_ppm,
            self.novelty_ppm,
            self.rarity_ppm,
            self.forgetting_risk_ppm,
            self.coverage_need_ppm,
        ]
        .into_iter()
        .map(u64::from)
        .sum())
    }
}

impl ValidateHnmfV1 for ReplayCandidateV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.event_id == 0 || self.source_bucket == 0 {
            return Err(HnmfContractError::Invalid("replay candidate identity"));
        }
        for value in [
            self.expected_utility_gain_ppm,
            self.prediction_error_ppm,
            self.novelty_ppm,
            self.rarity_ppm,
            self.forgetting_risk_ppm,
            self.coverage_need_ppm,
        ] {
            ppm(value, "replay score component")?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplaySelectionReceiptV1 {
    #[serde(with = "super::wire::digest")]
    candidate_set_digest: Digest32,
    selected_event_ids: Vec<EventIdV1>,
    source_bucket_counts: BTreeMap<u16, u16>,
    #[serde(with = "super::wire::digest")]
    selection_policy_digest: Digest32,
    resource_receipt: ResourceReceiptV1,
}

impl ReplaySelectionReceiptV1 {
    pub fn try_new(
        candidate_set_digest: Digest32,
        selected_event_ids: Vec<EventIdV1>,
        source_bucket_counts: BTreeMap<u16, u16>,
        selection_policy_digest: Digest32,
        resource_receipt: ResourceReceiptV1,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            candidate_set_digest,
            selected_event_ids,
            source_bucket_counts,
            selection_policy_digest,
            resource_receipt,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for ReplaySelectionReceiptV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.candidate_set_digest.is_zero() || self.selection_policy_digest.is_zero() {
            return Err(HnmfContractError::Invalid("replay receipt digest"));
        }
        if self.selected_event_ids.len() > MAX_REPLAY_SELECTION {
            return Err(HnmfContractError::BoundExceeded("replay selection"));
        }
        if self.selected_event_ids.contains(&0) || self.source_bucket_counts.contains_key(&0) {
            return Err(HnmfContractError::Invalid("replay receipt identity"));
        }
        let unique: BTreeSet<_> = self.selected_event_ids.iter().copied().collect();
        if unique.len() != self.selected_event_ids.len() {
            return Err(HnmfContractError::Conflict("duplicate replay selection"));
        }
        let bucket_total: usize = self
            .source_bucket_counts
            .values()
            .copied()
            .map(usize::from)
            .sum();
        if bucket_total != self.selected_event_ids.len() {
            return Err(HnmfContractError::Conflict(
                "replay bucket counts do not match selection size",
            ));
        }
        self.resource_receipt.validate()
    }
}

impl CanonicalJsonV1 for ReplaySelectionReceiptV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.replay-selection-receipt.v1";
    const MAX_ENCODED_BYTES: usize = 65_536;
}

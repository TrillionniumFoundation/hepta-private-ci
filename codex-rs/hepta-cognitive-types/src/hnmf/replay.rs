use std::collections::BTreeMap;
use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use super::CanonicalContractV1;
use super::CanonicalDigestV1;
use super::ContractErrorV1;
use super::EventIdV1;
use super::MAX_REPLAY_CANDIDATES;
use super::MAX_REPLAY_SELECTION;
use super::ResourceReceiptV1;
use super::validate_nonzero;
use super::validate_ppm;
use super::validate_signed_ppm;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct OutcomeSignalV1 {
    episode_id: u64,
    utility_delta_ppm: i32,
    prediction_error_ppm: u32,
    novelty_ppm: u32,
    risk_ppm: u32,
    ood_ppm: u32,
    observer_digest: CanonicalDigestV1,
}

impl OutcomeSignalV1 {
    pub fn try_new(
        episode_id: u64,
        utility_delta_ppm: i32,
        prediction_error_ppm: u32,
        novelty_ppm: u32,
        risk_ppm: u32,
        ood_ppm: u32,
        observer_digest: CanonicalDigestV1,
    ) -> Result<Self, ContractErrorV1> {
        validate_nonzero(episode_id, "outcome episode id must be non-zero")?;
        validate_signed_ppm(utility_delta_ppm, "outcome utility delta")?;
        for (value, name) in [
            (prediction_error_ppm, "prediction error"),
            (novelty_ppm, "novelty"),
            (risk_ppm, "risk"),
            (ood_ppm, "ood"),
        ] {
            validate_ppm(value, name)?;
        }
        Ok(Self {
            episode_id,
            utility_delta_ppm,
            prediction_error_ppm,
            novelty_ppm,
            risk_ppm,
            ood_ppm,
            observer_digest,
        })
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.episode_id, "outcome episode id must be non-zero")?;
        validate_signed_ppm(self.utility_delta_ppm, "outcome utility delta")?;
        validate_ppm(self.prediction_error_ppm, "prediction error")?;
        validate_ppm(self.novelty_ppm, "novelty")?;
        validate_ppm(self.risk_ppm, "risk")?;
        validate_ppm(self.ood_ppm, "ood")
    }
}

impl CanonicalContractV1 for OutcomeSignalV1 {
    const SCHEMA_ID: &'static str = "OutcomeSignalV1";
    const MAX_ENCODED_BYTES: usize = 32_768;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
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
    ) -> Result<Self, ContractErrorV1> {
        validate_nonzero(event_id, "replay event id must be non-zero")?;
        for (value, name) in [
            (expected_utility_gain_ppm, "expected utility gain"),
            (prediction_error_ppm, "prediction error"),
            (novelty_ppm, "novelty"),
            (rarity_ppm, "rarity"),
            (forgetting_risk_ppm, "forgetting risk"),
            (coverage_need_ppm, "coverage need"),
        ] {
            validate_ppm(value, name)?;
        }
        Ok(Self {
            event_id,
            source_bucket,
            expected_utility_gain_ppm,
            prediction_error_ppm,
            novelty_ppm,
            rarity_ppm,
            forgetting_risk_ppm,
            coverage_need_ppm,
            privacy_allowed,
        })
    }

    fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.event_id, "replay event id must be non-zero")?;
        for (value, name) in [
            (self.expected_utility_gain_ppm, "expected utility gain"),
            (self.prediction_error_ppm, "prediction error"),
            (self.novelty_ppm, "novelty"),
            (self.rarity_ppm, "rarity"),
            (self.forgetting_risk_ppm, "forgetting risk"),
            (self.coverage_need_ppm, "coverage need"),
        ] {
            validate_ppm(value, name)?;
        }
        Ok(())
    }

    fn score(&self) -> u64 {
        [
            self.expected_utility_gain_ppm,
            self.prediction_error_ppm,
            self.novelty_ppm,
            self.rarity_ppm,
            self.forgetting_risk_ppm,
            self.coverage_need_ppm,
        ]
        .into_iter()
        .map(u64::from)
        .sum()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ReplaySelectionReceiptV1 {
    candidate_set_digest: CanonicalDigestV1,
    selected_event_ids: Vec<EventIdV1>,
    source_bucket_counts: BTreeMap<u16, u32>,
    selection_policy_digest: CanonicalDigestV1,
    resource_receipt: ResourceReceiptV1,
}

impl ReplaySelectionReceiptV1 {
    pub fn try_new(
        candidate_set_digest: CanonicalDigestV1,
        selected_event_ids: Vec<EventIdV1>,
        source_bucket_counts: BTreeMap<u16, u32>,
        selection_policy_digest: CanonicalDigestV1,
        resource_receipt: ResourceReceiptV1,
    ) -> Result<Self, ContractErrorV1> {
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

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        if self.selected_event_ids.len() > MAX_REPLAY_SELECTION
            || self.selected_event_ids.contains(&0)
        {
            return Err(ContractErrorV1::BoundExceeded("replay selected events"));
        }
        let mut unique = BTreeSet::new();
        if self
            .selected_event_ids
            .iter()
            .any(|event_id| !unique.insert(*event_id))
        {
            return Err(ContractErrorV1::Conflict("duplicate replay selected event"));
        }
        let count_sum = self
            .source_bucket_counts
            .values()
            .map(|value| *value as usize)
            .sum::<usize>();
        if count_sum != self.selected_event_ids.len() {
            return Err(ContractErrorV1::Conflict(
                "source bucket counts must equal selected event count",
            ));
        }
        self.resource_receipt.validate_absolute()
    }
}

impl CanonicalContractV1 for ReplaySelectionReceiptV1 {
    const SCHEMA_ID: &'static str = "ReplaySelectionReceiptV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}

pub fn select_replay_v1(
    candidates: &[ReplayCandidateV1],
    maximum_selected: usize,
    maximum_per_source_bucket: usize,
    candidate_set_digest: CanonicalDigestV1,
    selection_policy_digest: CanonicalDigestV1,
    resource_receipt: ResourceReceiptV1,
) -> Result<ReplaySelectionReceiptV1, ContractErrorV1> {
    if candidates.len() > MAX_REPLAY_CANDIDATES
        || maximum_selected == 0
        || maximum_selected > MAX_REPLAY_SELECTION
        || maximum_per_source_bucket == 0
        || maximum_per_source_bucket > maximum_selected
    {
        return Err(ContractErrorV1::BoundExceeded("replay selection"));
    }
    for candidate in candidates {
        candidate.validate()?;
    }
    let mut scored = candidates
        .iter()
        .filter(|candidate| candidate.privacy_allowed)
        .collect::<Vec<_>>();
    scored.sort_by(|left, right| {
        right
            .score()
            .cmp(&left.score())
            .then_with(|| left.source_bucket.cmp(&right.source_bucket))
            .then_with(|| left.event_id.cmp(&right.event_id))
    });

    let mut selected_event_ids = Vec::new();
    let mut source_bucket_counts = BTreeMap::<u16, u32>::new();
    for candidate in scored {
        if selected_event_ids.len() >= maximum_selected {
            break;
        }
        let count = source_bucket_counts.entry(candidate.source_bucket).or_default();
        if *count as usize >= maximum_per_source_bucket {
            continue;
        }
        *count += 1;
        selected_event_ids.push(candidate.event_id);
    }
    ReplaySelectionReceiptV1::try_new(
        candidate_set_digest,
        selected_event_ids,
        source_bucket_counts,
        selection_policy_digest,
        resource_receipt,
    )
}

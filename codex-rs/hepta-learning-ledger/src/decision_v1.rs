//! Registered `LearningDecisionV1` and prompt-policy causal support binding.
//!
//! The durable V1 journal format is intentionally unchanged. Prompt/context
//! receipts are reduced to a single support digest and attached to the existing
//! `EpisodeDecision` event so older binaries can still read/rollback every
//! durable journal byte. A deterministic prompt policy is logged with propensity
//! 1.0; this records exposure lineage but does not create positivity for
//! counterfactual prompt arms.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AppendReceipt;
use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;
use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;

const PPM_SCALE: u32 = 1_000_000;
const ABSTAIN_ID: &str = "abstain";
const MAX_ACTIONS: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningDecisionV1 {
    pub decision_id: StableId,
    pub episode_id: StableId,
    pub candidate_set_digest: Digest32,
    pub policy_digest: Digest32,
    pub chosen_id: StableId,
    pub propensity_ppm: u32,
    pub random_seed_digest: Option<Digest32>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCausalSupportV1 {
    pub candidate_completeness_digest: Digest32,
    pub prompt_candidate_receipt_digest: Digest32,
    pub prompt_pricing_set_digest: Digest32,
    pub prompt_portfolio_receipt_digest: Digest32,
    pub prompt_exercise_receipt_digest: Digest32,
    pub context_compilation_receipt_digest: Digest32,
    pub delivery_observation_receipt_digest: Digest32,
    pub delivered: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptLearningDecisionRequestV1 {
    pub record_id: StableId,
    pub objective_digest: Digest32,
    pub policy_id: StableId,
    pub action_ids: Vec<StableId>,
    pub decision: LearningDecisionV1,
    pub support: PromptCausalSupportV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptLearningDecisionArtifactV1 {
    pub learning_decision: LearningDecisionV1,
    pub ledger_decision: EpisodeDecision,
    pub action_set_digest: Digest32,
    pub support_digest: Digest32,
    pub causal_evaluation_eligible: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptLearningAppendReceiptV1 {
    pub artifact: PromptLearningDecisionArtifactV1,
    pub ledger_receipt: AppendReceipt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningDecisionV1Error {
    EmptyDigest(&'static str),
    InvalidPropensity,
    RandomSeedRequired,
    RandomSeedUnexpected,
    AuthorityGranted,
    ReceiptDigestMismatch,
    ActionLimitExceeded,
    MissingAbstain,
    DuplicateAction(String),
    ChosenActionMissing(String),
    CandidateSetDigestMismatch,
    EpisodeMismatch,
    Ledger(LedgerError),
    Arithmetic,
}

impl fmt::Display for LearningDecisionV1Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningDecisionV1Error {}

impl From<LedgerError> for LearningDecisionV1Error {
    fn from(value: LedgerError) -> Self {
        Self::Ledger(value)
    }
}

impl LearningDecisionV1 {
    pub fn new_deterministic(
        decision_id: StableId,
        episode_id: StableId,
        candidate_set_digest: Digest32,
        policy_digest: Digest32,
        chosen_id: StableId,
    ) -> Result<Self, LearningDecisionV1Error> {
        let mut value = Self {
            decision_id,
            episode_id,
            candidate_set_digest,
            policy_digest,
            chosen_id,
            propensity_ppm: PPM_SCALE,
            random_seed_digest: None,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.receipt_digest = Digest32::of_bytes(&value.semantic_json_bytes());
        value.validate()?;
        Ok(value)
    }

    pub fn new_randomized(
        decision_id: StableId,
        episode_id: StableId,
        candidate_set_digest: Digest32,
        policy_digest: Digest32,
        chosen_id: StableId,
        propensity_ppm: u32,
        random_seed_digest: Digest32,
    ) -> Result<Self, LearningDecisionV1Error> {
        let mut value = Self {
            decision_id,
            episode_id,
            candidate_set_digest,
            policy_digest,
            chosen_id,
            propensity_ppm,
            random_seed_digest: Some(random_seed_digest),
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.receipt_digest = Digest32::of_bytes(&value.semantic_json_bytes());
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), LearningDecisionV1Error> {
        for (label, digest) in [
            ("candidate set", self.candidate_set_digest),
            ("policy", self.policy_digest),
            ("decision receipt", self.receipt_digest),
        ] {
            require_digest(label, digest)?;
        }
        if self.propensity_ppm == 0 || self.propensity_ppm > PPM_SCALE {
            return Err(LearningDecisionV1Error::InvalidPropensity);
        }
        match (self.propensity_ppm == PPM_SCALE, self.random_seed_digest) {
            (true, None) => {}
            (true, Some(_)) => return Err(LearningDecisionV1Error::RandomSeedUnexpected),
            (false, Some(seed)) => require_digest("random seed", seed)?,
            (false, None) => return Err(LearningDecisionV1Error::RandomSeedRequired),
        }
        if self.authority.grants_any() {
            return Err(LearningDecisionV1Error::AuthorityGranted);
        }
        if self.receipt_digest != Digest32::of_bytes(&self.semantic_json_bytes()) {
            return Err(LearningDecisionV1Error::ReceiptDigestMismatch);
        }
        Ok(())
    }

    pub fn to_canonical_json(&self) -> Result<Vec<u8>, LearningDecisionV1Error> {
        self.validate()?;
        Ok(self.semantic_json_bytes())
    }

    fn semantic_json_bytes(&self) -> Vec<u8> {
        let mut value = format!(
            "{{\"decisionId\":\"{}\",\"episodeId\":\"{}\",\"candidateSetDigest\":\"{}\",\"policyDigest\":\"{}\",\"chosenId\":\"{}\",\"propensityPpm\":{}",
            self.decision_id,
            self.episode_id,
            self.candidate_set_digest,
            self.policy_digest,
            self.chosen_id,
            self.propensity_ppm,
        );
        if let Some(seed) = self.random_seed_digest {
            value.push_str(&format!(",\"randomSeedDigest\":\"{seed}\""));
        }
        value.push('}');
        value.into_bytes()
    }
}

impl PromptCausalSupportV1 {
    pub fn digest(&self) -> Result<Digest32, LearningDecisionV1Error> {
        for (label, digest) in [
            ("candidate completeness", self.candidate_completeness_digest),
            ("prompt candidate receipt", self.prompt_candidate_receipt_digest),
            ("prompt pricing set", self.prompt_pricing_set_digest),
            ("prompt portfolio receipt", self.prompt_portfolio_receipt_digest),
            ("prompt exercise receipt", self.prompt_exercise_receipt_digest),
            ("context compilation receipt", self.context_compilation_receipt_digest),
            ("delivery observation receipt", self.delivery_observation_receipt_digest),
        ] {
            require_digest(label, digest)?;
        }
        let mut bytes = b"hepta.learning-ledger.prompt-causal-support.v1".to_vec();
        for digest in [
            self.candidate_completeness_digest,
            self.prompt_candidate_receipt_digest,
            self.prompt_pricing_set_digest,
            self.prompt_portfolio_receipt_digest,
            self.prompt_exercise_receipt_digest,
            self.context_compilation_receipt_digest,
            self.delivery_observation_receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(u8::from(self.delivered));
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub fn canonical_prompt_action_set_digest(
    action_ids: &[StableId],
) -> Result<Digest32, LearningDecisionV1Error> {
    if action_ids.is_empty() || action_ids.len() > MAX_ACTIONS {
        return Err(LearningDecisionV1Error::ActionLimitExceeded);
    }
    let mut canonical = action_ids.to_vec();
    canonical.sort();
    for pair in canonical.windows(2) {
        if pair[0] == pair[1] {
            return Err(LearningDecisionV1Error::DuplicateAction(
                pair[0].to_string(),
            ));
        }
    }
    if !canonical.iter().any(|value| value.as_str() == ABSTAIN_ID) {
        return Err(LearningDecisionV1Error::MissingAbstain);
    }
    let mut bytes = b"hepta.learning-ledger.prompt-action-set.v1".to_vec();
    bytes.extend_from_slice(
        &u32::try_from(canonical.len())
            .map_err(|_| LearningDecisionV1Error::Arithmetic)?
            .to_be_bytes(),
    );
    for action_id in canonical {
        push_id(&mut bytes, &action_id);
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn prepare_prompt_learning_decision_v1(
    mut request: PromptLearningDecisionRequestV1,
) -> Result<PromptLearningDecisionArtifactV1, LearningDecisionV1Error> {
    request.decision.validate()?;
    require_digest("objective", request.objective_digest)?;
    if request.decision.episode_id != request.decision.episode_id {
        return Err(LearningDecisionV1Error::EpisodeMismatch);
    }
    request.action_ids.sort();
    for pair in request.action_ids.windows(2) {
        if pair[0] == pair[1] {
            return Err(LearningDecisionV1Error::DuplicateAction(
                pair[0].to_string(),
            ));
        }
    }
    let action_set_digest = canonical_prompt_action_set_digest(&request.action_ids)?;
    if action_set_digest != request.decision.candidate_set_digest {
        return Err(LearningDecisionV1Error::CandidateSetDigestMismatch);
    }
    if !request.action_ids.contains(&request.decision.chosen_id) {
        return Err(LearningDecisionV1Error::ChosenActionMissing(
            request.decision.chosen_id.to_string(),
        ));
    }
    let support_digest = request.support.digest()?;
    let combined_support = decision_support_digest(
        request.decision.receipt_digest,
        action_set_digest,
        support_digest,
    );
    let selected_propensity = ppm_to_probability(request.decision.propensity_ppm)?;
    let ledger_decision = EpisodeDecision {
        record_id: request.record_id,
        episode_id: request.decision.episode_id.clone(),
        objective_digest: request.objective_digest,
        policy_id: request.policy_id,
        candidate_ids: request.action_ids,
        selected_candidate_id: request.decision.chosen_id.clone(),
        selected_propensity,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: combined_support,
    };
    let causal_evaluation_eligible = request.support.delivered
        && request.decision.random_seed_digest.is_some()
        && request.decision.propensity_ppm < PPM_SCALE;
    Ok(PromptLearningDecisionArtifactV1 {
        learning_decision: request.decision,
        ledger_decision,
        action_set_digest,
        support_digest,
        causal_evaluation_eligible,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn append_prompt_learning_decision_v1(
    ledger: &mut LearningLedger,
    request: PromptLearningDecisionRequestV1,
) -> Result<PromptLearningAppendReceiptV1, LearningDecisionV1Error> {
    let artifact = prepare_prompt_learning_decision_v1(request)?;
    let ledger_receipt = ledger.append(LedgerEvent::Decision(artifact.ledger_decision.clone()))?;
    Ok(PromptLearningAppendReceiptV1 {
        artifact,
        ledger_receipt,
    })
}

fn ppm_to_probability(ppm: u32) -> Result<ProbabilityQ32, LearningDecisionV1Error> {
    if ppm == 0 || ppm > PPM_SCALE {
        return Err(LearningDecisionV1Error::InvalidPropensity);
    }
    let numerator = u128::from(ppm)
        .checked_mul(u128::from(ProbabilityQ32::ONE.raw()))
        .ok_or(LearningDecisionV1Error::Arithmetic)?;
    let rounded = numerator
        .checked_add(u128::from(PPM_SCALE / 2))
        .ok_or(LearningDecisionV1Error::Arithmetic)?
        / u128::from(PPM_SCALE);
    let raw = u64::try_from(rounded).map_err(|_| LearningDecisionV1Error::Arithmetic)?;
    ProbabilityQ32::from_raw(raw).map_err(|_| LearningDecisionV1Error::Arithmetic)
}

fn decision_support_digest(
    decision_receipt_digest: Digest32,
    action_set_digest: Digest32,
    causal_support_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.prompt-decision-support.v1".to_vec();
    bytes.extend_from_slice(decision_receipt_digest.as_array());
    bytes.extend_from_slice(action_set_digest.as_array());
    bytes.extend_from_slice(causal_support_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn require_digest(
    label: &'static str,
    digest: Digest32,
) -> Result<(), LearningDecisionV1Error> {
    if digest.is_zero() {
        return Err(LearningDecisionV1Error::EmptyDigest(label));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "decision_v1_tests.rs"]
mod tests;

//! Deterministic H5 neuron-proposal shadow surface.
//!
//! This module is deliberately pure.  It turns a bounded, caller-supplied
//! replay observation into a typed parameter proposal, or an explicit abstain
//! decision.  It does not read or write the cognitive store, mutate KG facts,
//! select a workflow, route a model, or execute an external effect.  The
//! proposal envelope carries those negative boundaries so a future consumer
//! cannot mistake a shadow result for runtime authority.

use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::framing::frame_part;

pub const H5_NEURON_PROPOSAL_SCHEMA_VERSION: u32 = 1;
pub const MAX_NEURON_FEATURES: usize = 32;
pub const MAX_NEURON_FEATURE_KEY_BYTES: usize = 128;
pub const MAX_NEURON_UPDATE_BPS: i32 = 500;

/// A bounded position from the H7 registry.  These positions are proposals
/// over already-existing behavior; none of them permits topology or authority
/// changes.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum NeuronPosition {
    MemoryRetrievalRank,
    WorkflowSelect,
    BranchRoute,
}

impl NeuronPosition {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::MemoryRetrievalRank => "memory-retrieval-rank",
            Self::WorkflowSelect => "workflow-select",
            Self::BranchRoute => "branch-route",
        }
    }

    const fn permits(self, parameter: NeuronParameter) -> bool {
        match self {
            Self::MemoryRetrievalRank => matches!(
                parameter,
                NeuronParameter::RetrievalWeightBps | NeuronParameter::FreshnessDecayBps
            ),
            Self::WorkflowSelect => matches!(
                parameter,
                NeuronParameter::CandidateRankBps | NeuronParameter::AbstainThresholdBps
            ),
            Self::BranchRoute => matches!(
                parameter,
                NeuronParameter::BranchThresholdBps | NeuronParameter::RetryBudgetBps
            ),
        }
    }
}

/// Learnable parameter names are explicit and position-scoped.  There is no
/// enum variant for topology, permissions, base-model weights, or effects.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NeuronParameter {
    RetrievalWeightBps,
    FreshnessDecayBps,
    CandidateRankBps,
    AbstainThresholdBps,
    BranchThresholdBps,
    RetryBudgetBps,
}

impl NeuronParameter {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::RetrievalWeightBps => "retrieval_weight_bps",
            Self::FreshnessDecayBps => "freshness_decay_bps",
            Self::CandidateRankBps => "candidate_rank_bps",
            Self::AbstainThresholdBps => "abstain_threshold_bps",
            Self::BranchThresholdBps => "branch_threshold_bps",
            Self::RetryBudgetBps => "retry_budget_bps",
        }
    }
}

/// One bounded replay feature.  Values are integer basis points, so the
/// proposal path is deterministic across platforms and does not invoke a
/// model.
#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NeuronFeature {
    pub key: String,
    pub value_bps: u16,
}

impl NeuronFeature {
    pub fn new(key: impl Into<String>, value_bps: u16) -> Result<Self, NeuronProposalError> {
        let key = key.into();
        validate_feature_key(&key)?;
        if value_bps > 10_000 {
            return Err(NeuronProposalError::Invalid(
                "feature value must be within 0..=10000 bps".to_string(),
            ));
        }
        Ok(Self { key, value_bps })
    }
}

/// Immutable input snapshot for one proposal.  The state and policy digests
/// bind the proposal to a read epoch; they do not grant authority to use it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NeuronProposalInput {
    pub position: NeuronPosition,
    pub state_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub sample_count: u32,
    pub baseline_bps: u16,
    pub features: Vec<NeuronFeature>,
}

impl NeuronProposalInput {
    pub fn validate(&self) -> Result<(), NeuronProposalError> {
        if self.authority_epoch == 0 {
            return Err(NeuronProposalError::Invalid(
                "authority_epoch must be non-zero".to_string(),
            ));
        }
        if self.sample_count == 0 {
            return Err(NeuronProposalError::Invalid(
                "sample_count must be non-zero".to_string(),
            ));
        }
        if self.baseline_bps > 10_000 {
            return Err(NeuronProposalError::Invalid(
                "baseline must be within 0..=10000 bps".to_string(),
            ));
        }
        if self.features.is_empty() {
            return Err(NeuronProposalError::Invalid(
                "at least one replay feature is required".to_string(),
            ));
        }
        if self.features.len() > MAX_NEURON_FEATURES {
            return Err(NeuronProposalError::Invalid(format!(
                "feature count exceeds {MAX_NEURON_FEATURES}"
            )));
        }
        let mut keys = BTreeSet::new();
        for feature in &self.features {
            validate_feature_key(&feature.key)?;
            if feature.value_bps > 10_000 {
                return Err(NeuronProposalError::Invalid(
                    "feature value must be within 0..=10000 bps".to_string(),
                ));
            }
            if !keys.insert(feature.key.as_str()) {
                return Err(NeuronProposalError::Invalid(
                    "feature keys must be unique".to_string(),
                ));
            }
        }
        Ok(())
    }

    /// Returns the canonical digest of this immutable read snapshot.
    pub fn digest(&self) -> Result<Sha256Digest, NeuronProposalError> {
        self.validate()?;
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, b"hepta:h5:neuron-input:v1");
        frame_part(&mut hasher, self.position.as_str().as_bytes());
        frame_part(&mut hasher, self.state_digest.as_str().as_bytes());
        frame_part(&mut hasher, self.policy_digest.as_str().as_bytes());
        frame_part(&mut hasher, &self.authority_epoch.to_be_bytes());
        frame_part(&mut hasher, &self.sample_count.to_be_bytes());
        frame_part(&mut hasher, &self.baseline_bps.to_be_bytes());
        frame_part(
            &mut hasher,
            &u64::try_from(self.features.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        let mut features = self.features.iter().collect::<Vec<_>>();
        features.sort_by(|left, right| left.key.cmp(&right.key));
        for feature in features {
            frame_part(&mut hasher, feature.key.as_bytes());
            frame_part(&mut hasher, &feature.value_bps.to_be_bytes());
        }
        Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
    }
}

/// Explicitly bounded abstain outcomes are first-class shadow results.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NeuronAbstainReason {
    NoChange,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "decision")]
pub enum NeuronProposalDecision {
    Proposed(NeuronProposal),
    Abstained {
        input_digest: Sha256Digest,
        reason: NeuronAbstainReason,
    },
}

/// A typed, deterministic proposal envelope.  The negative authority fields
/// are intentionally serialized so downstream evidence can assert that this
/// object is not an execution instruction.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NeuronProposal {
    pub schema_version: u32,
    pub proposal_id: Sha256Digest,
    pub input_digest: Sha256Digest,
    pub position: NeuronPosition,
    pub parameter: NeuronParameter,
    pub delta_bps: i32,
    pub confidence_bps: u16,
    pub phase: NeuronProposalPhase,
    pub authority: NeuronProposalAuthority,
    pub production_effects: bool,
    pub execute_allowed: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NeuronProposalPhase {
    Shadow,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NeuronProposalAuthority {
    ProposalOnly,
}

impl NeuronProposal {
    pub fn validate(&self) -> Result<(), NeuronProposalError> {
        if self.schema_version != H5_NEURON_PROPOSAL_SCHEMA_VERSION {
            return Err(NeuronProposalError::Invalid(
                "unsupported neuron proposal schema version".to_string(),
            ));
        }
        if !self.position.permits(self.parameter) {
            return Err(NeuronProposalError::Invalid(
                "parameter is not allowed for this neuron position".to_string(),
            ));
        }
        if !(-MAX_NEURON_UPDATE_BPS..=MAX_NEURON_UPDATE_BPS).contains(&self.delta_bps) {
            return Err(NeuronProposalError::Invalid(format!(
                "delta exceeds +/-{MAX_NEURON_UPDATE_BPS} bps"
            )));
        }
        if self.confidence_bps > 10_000 {
            return Err(NeuronProposalError::Invalid(
                "confidence must be within 0..=10000 bps".to_string(),
            ));
        }
        if self.phase != NeuronProposalPhase::Shadow
            || self.authority != NeuronProposalAuthority::ProposalOnly
            || self.production_effects
            || self.execute_allowed
        {
            return Err(NeuronProposalError::AuthorityBoundary);
        }
        let expected = proposal_id(
            &self.input_digest,
            self.position,
            self.parameter,
            self.delta_bps,
            self.confidence_bps,
        );
        if expected != self.proposal_id {
            return Err(NeuronProposalError::DigestMismatch);
        }
        Ok(())
    }

    pub fn is_shadow_only(&self) -> bool {
        self.phase == NeuronProposalPhase::Shadow
            && self.authority == NeuronProposalAuthority::ProposalOnly
            && !self.production_effects
            && !self.execute_allowed
    }
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum NeuronProposalError {
    #[error("invalid neuron proposal: {0}")]
    Invalid(String),
    #[error("neuron proposal digest does not match its contents")]
    DigestMismatch,
    #[error("neuron proposal crosses the shadow authority boundary")]
    AuthorityBoundary,
}

/// Build one deterministic proposal from an immutable replay snapshot.
///
/// The integer mean is deliberately simple: this is a typed seam for the
/// offline learner, not an online model or routing implementation.  A zero
/// delta is returned as an explicit abstain.  Non-zero deltas are clipped to
/// the fixed H7 update budget.
pub fn shadow_neuron_propose(
    input: &NeuronProposalInput,
    parameter: NeuronParameter,
) -> Result<NeuronProposalDecision, NeuronProposalError> {
    input.validate()?;
    if !input.position.permits(parameter) {
        return Err(NeuronProposalError::Invalid(
            "parameter is not allowed for this neuron position".to_string(),
        ));
    }
    let input_digest = input.digest()?;
    let sum: i64 = input
        .features
        .iter()
        .map(|feature| i64::from(feature.value_bps))
        .sum();
    let mean = sum / i64::try_from(input.features.len()).unwrap_or(1);
    let raw_delta = mean - i64::from(input.baseline_bps);
    if raw_delta == 0 {
        return Ok(NeuronProposalDecision::Abstained {
            input_digest,
            reason: NeuronAbstainReason::NoChange,
        });
    }
    let delta_bps = raw_delta.clamp(
        i64::from(-MAX_NEURON_UPDATE_BPS),
        i64::from(MAX_NEURON_UPDATE_BPS),
    ) as i32;
    let confidence_bps = ((raw_delta.unsigned_abs().min(10_000) as u32)
        .saturating_add(input.sample_count.min(100).saturating_mul(50)))
    .min(10_000) as u16;
    let proposal_id = proposal_id(
        &input_digest,
        input.position,
        parameter,
        delta_bps,
        confidence_bps,
    );
    let proposal = NeuronProposal {
        schema_version: H5_NEURON_PROPOSAL_SCHEMA_VERSION,
        proposal_id,
        input_digest,
        position: input.position,
        parameter,
        delta_bps,
        confidence_bps,
        phase: NeuronProposalPhase::Shadow,
        authority: NeuronProposalAuthority::ProposalOnly,
        production_effects: false,
        execute_allowed: false,
    };
    proposal.validate()?;
    Ok(NeuronProposalDecision::Proposed(proposal))
}

fn proposal_id(
    input_digest: &Sha256Digest,
    position: NeuronPosition,
    parameter: NeuronParameter,
    delta_bps: i32,
    confidence_bps: u16,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta:h5:neuron-proposal:v1");
    frame_part(&mut hasher, input_digest.as_str().as_bytes());
    frame_part(&mut hasher, position.as_str().as_bytes());
    frame_part(&mut hasher, parameter.as_str().as_bytes());
    frame_part(&mut hasher, &delta_bps.to_be_bytes());
    frame_part(&mut hasher, &confidence_bps.to_be_bytes());
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn validate_feature_key(key: &str) -> Result<(), NeuronProposalError> {
    if key.trim().is_empty()
        || key.len() > MAX_NEURON_FEATURE_KEY_BYTES
        || key.as_bytes().contains(&0)
        || key.chars().any(char::is_control)
    {
        return Err(NeuronProposalError::Invalid(
            "feature key must be non-empty, bounded, and free of control characters".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::NeuronAbstainReason;
    use super::NeuronFeature;
    use super::NeuronParameter;
    use super::NeuronPosition;
    use super::NeuronProposalAuthority;
    use super::NeuronProposalDecision;
    use super::NeuronProposalInput;
    use super::NeuronProposalPhase;
    use super::shadow_neuron_propose;
    use codex_hepta_contracts::Sha256Digest;

    fn input(features: Vec<NeuronFeature>, baseline_bps: u16) -> NeuronProposalInput {
        NeuronProposalInput {
            position: NeuronPosition::MemoryRetrievalRank,
            state_digest: Sha256Digest::for_bytes(b"state"),
            policy_digest: Sha256Digest::for_bytes(b"policy"),
            authority_epoch: 3,
            sample_count: 12,
            baseline_bps,
            features,
        }
    }

    #[test]
    fn proposal_is_deterministic_and_feature_order_is_contractual() {
        let first = input(
            vec![
                NeuronFeature::new("freshness", 8_000).expect("feature"),
                NeuronFeature::new("success", 9_000).expect("feature"),
            ],
            7_000,
        );
        let second = input(
            vec![
                NeuronFeature::new("success", 9_000).expect("feature"),
                NeuronFeature::new("freshness", 8_000).expect("feature"),
            ],
            7_000,
        );
        let first =
            shadow_neuron_propose(&first, NeuronParameter::RetrievalWeightBps).expect("proposal");
        let second =
            shadow_neuron_propose(&second, NeuronParameter::RetrievalWeightBps).expect("proposal");
        assert_eq!(
            first, second,
            "feature order must not affect a proposal digest"
        );
        let NeuronProposalDecision::Proposed(proposal) = first else {
            panic!("expected proposal");
        };
        assert_eq!(proposal.delta_bps, 500);
        assert!(proposal.is_shadow_only());
    }

    #[test]
    fn no_change_is_an_explicit_abstain_and_never_an_execution_instruction() {
        let input = input(
            vec![NeuronFeature::new("signal", 5_000).expect("feature")],
            5_000,
        );
        let decision =
            shadow_neuron_propose(&input, NeuronParameter::RetrievalWeightBps).expect("decision");
        assert!(matches!(
            decision,
            NeuronProposalDecision::Abstained {
                reason: NeuronAbstainReason::NoChange,
                ..
            }
        ));
    }

    #[test]
    fn position_scope_and_tamper_validation_are_fail_closed() {
        let input = NeuronProposalInput {
            position: NeuronPosition::WorkflowSelect,
            state_digest: Sha256Digest::for_bytes(b"state"),
            policy_digest: Sha256Digest::for_bytes(b"policy"),
            authority_epoch: 1,
            sample_count: 1,
            baseline_bps: 1_000,
            features: vec![NeuronFeature::new("signal", 9_000).expect("feature")],
        };
        let invalid = shadow_neuron_propose(&input, NeuronParameter::RetryBudgetBps)
            .expect_err("branch parameter cannot target workflow position");
        assert!(matches!(invalid, super::NeuronProposalError::Invalid(_)));

        let decision =
            shadow_neuron_propose(&input, NeuronParameter::CandidateRankBps).expect("proposal");
        let NeuronProposalDecision::Proposed(mut proposal) = decision else {
            panic!("expected proposal");
        };
        proposal.delta_bps = 0;
        assert!(matches!(
            proposal.validate(),
            Err(super::NeuronProposalError::DigestMismatch)
        ));
        proposal.delta_bps = 500;
        proposal.phase = NeuronProposalPhase::Shadow;
        proposal.authority = NeuronProposalAuthority::ProposalOnly;
        proposal.production_effects = false;
        proposal.execute_allowed = false;
        proposal
            .validate()
            .expect("restoring the signed fields must validate");
    }
}

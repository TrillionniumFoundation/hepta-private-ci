//! Record confirmed prompt-portfolio exposure into the causal learning ledger.
//!
//! The runtime supplies the delivery observation. A separate host-owned
//! authenticator admits the behavior-policy assignment witness. Only terminal
//! `Delivered` observations create causal Decision facts; rejected or
//! indeterminate delivery never becomes exposure credit.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::ContextDeliveryObservationV2;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::LedgerError;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_prompt_optimizer::PromptCandidateSetReceiptV1;
use codex_hepta_prompt_optimizer::PromptExerciseDecisionV1;
use codex_hepta_prompt_optimizer::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::PromptPortfolioReceiptV1;
use codex_hepta_prompt_optimizer::PromptPricingReceiptV1;
use codex_hepta_prompt_optimizer::PromptRelationSourceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::PromptContextCompositionErrorV1;
use crate::PromptContextPreparationV1;

const ABSTAIN_ARM_ID: &str = "abstain";
const MAX_ASSIGNMENT_ARMS: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExposureAuthenticationErrorV1 {
    Rejected,
}

/// Authenticates a complete behavior-policy assignment witness.
///
/// The host is responsible for checking the named behavior policy, candidate
/// completeness receipt, random stream and freshness. The optimizer and
/// intelligence façade cannot self-authenticate their own assignment.
pub trait PromptExposureAssignmentAuthenticatorV1 {
    fn authenticate_prompt_assignment(
        &self,
        assignment: &PromptExposureAssignmentV1,
        now_unix_ms: u64,
    ) -> Result<(), PromptExposureAuthenticationErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExposureArmV1 {
    pub arm_id: StableId,
    /// `None` is reserved for the canonical no-intervention arm.
    pub portfolio_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExposureAssignmentV1 {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub policy_id: StableId,
    pub objective_digest: Digest32,
    pub arms: Vec<PromptExposureArmV1>,
    pub selected_arm_id: StableId,
    pub selected_propensity: ProbabilityQ32,
    pub candidate_set_completeness_digest: Digest32,
    pub random_stream_digest: Digest32,
    pub support_digest: Digest32,
    pub valid_until_unix_ms: u64,
    pub assignment_digest: Digest32,
}

impl PromptExposureAssignmentV1 {
    #[must_use]
    pub fn compute_assignment_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.intelligence.prompt-exposure-assignment.v1".to_vec();
        push_id(&mut bytes, &self.record_id);
        push_id(&mut bytes, &self.episode_id);
        push_id(&mut bytes, &self.policy_id);
        bytes.extend_from_slice(self.objective_digest.as_array());
        push_len(&mut bytes, self.arms.len());
        for arm in &self.arms {
            push_id(&mut bytes, &arm.arm_id);
            match arm.portfolio_digest {
                Some(digest) => {
                    bytes.push(1);
                    bytes.extend_from_slice(digest.as_array());
                }
                None => bytes.push(0),
            }
        }
        push_id(&mut bytes, &self.selected_arm_id);
        bytes.extend_from_slice(&self.selected_propensity.raw().to_be_bytes());
        for digest in [
            self.candidate_set_completeness_digest,
            self.random_stream_digest,
            self.support_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.valid_until_unix_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn validate_for(
        &self,
        portfolio: &PromptPortfolioReceiptV1,
        now_unix_ms: u64,
    ) -> Result<(), PromptExposureErrorV1> {
        if self.objective_digest != portfolio.objective_digest
            || self.arms.len() < 2
            || self.arms.len() > MAX_ASSIGNMENT_ARMS
            || self.selected_propensity.raw() == 0
            || self.valid_until_unix_ms == 0
            || now_unix_ms >= self.valid_until_unix_ms
        {
            return Err(PromptExposureErrorV1::InvalidAssignment);
        }
        for digest in [
            self.candidate_set_completeness_digest,
            self.random_stream_digest,
            self.support_digest,
            self.assignment_digest,
        ] {
            if digest.is_zero() {
                return Err(PromptExposureErrorV1::InvalidAssignment);
            }
        }
        let mut seen = BTreeSet::new();
        let mut abstain_count = 0_usize;
        let mut selected_matches_portfolio = false;
        for arm in &self.arms {
            if !seen.insert(arm.arm_id.clone()) {
                return Err(PromptExposureErrorV1::InvalidAssignment);
            }
            if arm.arm_id.as_str() == ABSTAIN_ARM_ID {
                abstain_count += 1;
                if arm.portfolio_digest.is_some() {
                    return Err(PromptExposureErrorV1::InvalidAssignment);
                }
            } else {
                let Some(digest) = arm.portfolio_digest else {
                    return Err(PromptExposureErrorV1::InvalidAssignment);
                };
                if digest.is_zero() {
                    return Err(PromptExposureErrorV1::InvalidAssignment);
                }
                if arm.arm_id == self.selected_arm_id && digest == portfolio.receipt_digest {
                    selected_matches_portfolio = true;
                }
            }
        }
        if abstain_count != 1
            || self.selected_arm_id.as_str() == ABSTAIN_ARM_ID
            || !selected_matches_portfolio
            || self
                .arms
                .windows(2)
                .any(|pair| pair[0].arm_id >= pair[1].arm_id)
            || self.assignment_digest != self.compute_assignment_digest()
        {
            return Err(PromptExposureErrorV1::InvalidAssignment);
        }
        Ok(())
    }
}

/// Appends a validated prompt-exposure decision to the learning owner.
///
/// Implementations must preserve the learning ledger's idempotency and durable
/// predecessor semantics; this façade never bypasses the ledger owner.
pub trait PromptExposureSinkV1 {
    fn append_prompt_exposure(
        &mut self,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, PromptExposureAppendErrorV1>;
}

impl PromptExposureSinkV1 for LearningLedger {
    fn append_prompt_exposure(
        &mut self,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, PromptExposureAppendErrorV1> {
        self.append(event).map_err(PromptExposureAppendErrorV1::Ledger)
    }
}

pub struct DurablePromptExposureSinkV1<'a> {
    ledger: &'a mut DurableLedger,
    expected_predecessor: Digest32,
}

impl<'a> DurablePromptExposureSinkV1<'a> {
    pub fn new(ledger: &'a mut DurableLedger, expected_predecessor: Digest32) -> Self {
        Self {
            ledger,
            expected_predecessor,
        }
    }

    #[must_use]
    pub const fn expected_predecessor(&self) -> Digest32 {
        self.expected_predecessor
    }
}

impl PromptExposureSinkV1 for DurablePromptExposureSinkV1<'_> {
    fn append_prompt_exposure(
        &mut self,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, PromptExposureAppendErrorV1> {
        let receipt = self
            .ledger
            .append(self.expected_predecessor, event)
            .map_err(PromptExposureAppendErrorV1::Durable)?;
        self.expected_predecessor = receipt.chain_digest;
        Ok(receipt)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExposureRecordingDispositionV1 {
    Recorded,
    DeliveryRejected,
    DeliveryIndeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExposureRecordingV1 {
    pub episode_id: StableId,
    pub assignment_digest: Digest32,
    pub preparation_digest: Digest32,
    pub delivery_observation_digest: Digest32,
    pub disposition: PromptExposureRecordingDispositionV1,
    pub ledger_decision: Option<EpisodeDecision>,
    pub ledger_receipt: Option<AppendReceipt>,
    pub recording_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn record_prompt_delivery_exposure_v1<S, A>(
    candidate_set: &PromptCandidateSetReceiptV1,
    pricing: &PromptPricingReceiptV1,
    relations: &PromptRelationSourceV1,
    portfolio: &PromptPortfolioReceiptV1,
    exercise: &PromptExerciseDecisionV1,
    exercise_request: &PromptExerciseRequestV1,
    preparation: &PromptContextPreparationV1,
    delivery: &ContextDeliveryObservationV2,
    assignment: &PromptExposureAssignmentV1,
    now_unix_ms: u64,
    authenticator: &A,
    sink: &mut S,
) -> Result<PromptExposureRecordingV1, PromptExposureErrorV1>
where
    S: PromptExposureSinkV1,
    A: PromptExposureAssignmentAuthenticatorV1,
{
    exercise
        .validate_for(
            candidate_set,
            pricing,
            relations,
            portfolio,
            exercise_request,
        )
        .map_err(PromptExposureErrorV1::Exercise)?;
    preparation
        .validate(exercise, portfolio)
        .map_err(PromptExposureErrorV1::Preparation)?;
    delivery
        .validate_for(&preparation.attachment)
        .map_err(PromptExposureErrorV1::Context)?;
    assignment.validate_for(portfolio, now_unix_ms)?;
    authenticator
        .authenticate_prompt_assignment(assignment, now_unix_ms)
        .map_err(|_| PromptExposureErrorV1::AssignmentAuthenticationRejected)?;

    let disposition = match delivery.disposition {
        ContextDeliveryDispositionV2::Delivered => PromptExposureRecordingDispositionV1::Recorded,
        ContextDeliveryDispositionV2::Rejected => {
            PromptExposureRecordingDispositionV1::DeliveryRejected
        }
        ContextDeliveryDispositionV2::Indeterminate => {
            PromptExposureRecordingDispositionV1::DeliveryIndeterminate
        }
    };
    let (ledger_decision, ledger_receipt) =
        if disposition == PromptExposureRecordingDispositionV1::Recorded {
            let decision = build_ledger_decision(assignment, preparation, delivery);
            let receipt = sink
                .append_prompt_exposure(LedgerEvent::Decision(decision.clone()))
                .map_err(PromptExposureErrorV1::Append)?;
            (Some(decision), Some(receipt))
        } else {
            (None, None)
        };
    let mut recording = PromptExposureRecordingV1 {
        episode_id: assignment.episode_id.clone(),
        assignment_digest: assignment.assignment_digest,
        preparation_digest: preparation.preparation_digest,
        delivery_observation_digest: delivery.observation_digest,
        disposition,
        ledger_decision,
        ledger_receipt,
        recording_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    recording.recording_digest = compute_recording_digest(&recording);
    recording.validate()?;
    Ok(recording)
}

impl PromptExposureRecordingV1 {
    pub fn validate(&self) -> Result<(), PromptExposureErrorV1> {
        if self.authority.grants_any()
            || self.assignment_digest.is_zero()
            || self.preparation_digest.is_zero()
            || self.delivery_observation_digest.is_zero()
            || self.recording_digest.is_zero()
        {
            return Err(PromptExposureErrorV1::InvalidRecording);
        }
        match self.disposition {
            PromptExposureRecordingDispositionV1::Recorded => {
                if self.ledger_decision.is_none() || self.ledger_receipt.is_none() {
                    return Err(PromptExposureErrorV1::InvalidRecording);
                }
            }
            PromptExposureRecordingDispositionV1::DeliveryRejected
            | PromptExposureRecordingDispositionV1::DeliveryIndeterminate => {
                if self.ledger_decision.is_some() || self.ledger_receipt.is_some() {
                    return Err(PromptExposureErrorV1::InvalidRecording);
                }
            }
        }
        if self.recording_digest != compute_recording_digest(self) {
            return Err(PromptExposureErrorV1::InvalidRecording);
        }
        Ok(())
    }
}

fn build_ledger_decision(
    assignment: &PromptExposureAssignmentV1,
    preparation: &PromptContextPreparationV1,
    delivery: &ContextDeliveryObservationV2,
) -> EpisodeDecision {
    let mut support = b"hepta.intelligence.prompt-exposure-support.v1".to_vec();
    for digest in [
        assignment.assignment_digest,
        assignment.candidate_set_completeness_digest,
        assignment.random_stream_digest,
        assignment.support_digest,
        preparation.preparation_digest,
        delivery.observation_digest,
    ] {
        support.extend_from_slice(digest.as_array());
    }
    EpisodeDecision {
        record_id: assignment.record_id.clone(),
        episode_id: assignment.episode_id.clone(),
        objective_digest: assignment.objective_digest,
        policy_id: assignment.policy_id.clone(),
        candidate_ids: assignment
            .arms
            .iter()
            .map(|arm| arm.arm_id.clone())
            .collect(),
        selected_candidate_id: assignment.selected_arm_id.clone(),
        selected_propensity: assignment.selected_propensity,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(&support),
    }
}

fn compute_recording_digest(value: &PromptExposureRecordingV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence.prompt-exposure-recording.v1".to_vec();
    push_id(&mut bytes, &value.episode_id);
    for digest in [
        value.assignment_digest,
        value.preparation_digest,
        value.delivery_observation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(match value.disposition {
        PromptExposureRecordingDispositionV1::Recorded => 0,
        PromptExposureRecordingDispositionV1::DeliveryRejected => 1,
        PromptExposureRecordingDispositionV1::DeliveryIndeterminate => 2,
    });
    if let Some(decision) = &value.ledger_decision {
        bytes.push(1);
        push_id(&mut bytes, &decision.record_id);
        bytes.extend_from_slice(decision.support_digest.as_array());
    } else {
        bytes.push(0);
    }
    if let Some(receipt) = &value.ledger_receipt {
        bytes.push(1);
        bytes.extend_from_slice(&receipt.sequence.get().to_be_bytes());
        bytes.extend_from_slice(receipt.event_digest.as_array());
        bytes.extend_from_slice(receipt.chain_digest.as_array());
    } else {
        bytes.push(0);
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

#[derive(Debug)]
pub enum PromptExposureAppendErrorV1 {
    Ledger(LedgerError),
    Durable(DurableLedgerError),
}

impl fmt::Display for PromptExposureAppendErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptExposureAppendErrorV1 {}

#[derive(Debug)]
pub enum PromptExposureErrorV1 {
    Exercise(codex_hepta_prompt_optimizer::PromptExerciseErrorV1),
    Preparation(PromptContextCompositionErrorV1),
    Context(ContextCompilerV2Error),
    InvalidAssignment,
    AssignmentAuthenticationRejected,
    Append(PromptExposureAppendErrorV1),
    InvalidRecording,
}

impl fmt::Display for PromptExposureErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptExposureErrorV1 {}

#[cfg(test)]
#[path = "prompt_exposure_v1_tests.rs"]
mod tests;

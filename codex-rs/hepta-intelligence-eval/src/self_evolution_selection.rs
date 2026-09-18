//! Independent selection gate for next-generation self-evolution candidates.
//!
//! This module does not activate, promote, merge or release anything. It turns
//! authenticated held-out evaluation into a selector-signed, authority-free
//! witness that a separate runtime control owner can consume for an exact
//! next-generation adoption. The no-change baseline is host policy, never a
//! candidate-supplied convenience baseline.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_learning_ledger::verify_verified_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::SelfEvolutionSelectionWitnessV1;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDispositionV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::LongitudinalTimeEvidenceV1;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_with_signed_longitudinal_evidence_v3;
use crate::future_window_signing_payload_v1;
use crate::longitudinal_evaluation_signing_payload_v3;

const MAX_DATASET_RECORDS: u32 = 1_000_000;

pub type SelfEvolutionSelectionReceiptV1 = SelfEvolutionSelectionWitnessV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionPolicyV1 {
    pub no_change_baseline_id: StableId,
    pub minimum_dataset_records: u32,
    /// Minimum real elapsed duration for every independently observed future
    /// window. Self-evolution selection is longitudinal-only; offline folds or
    /// generated timestamps cannot satisfy this policy.
    pub minimum_future_window_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionRequestV1 {
    pub selection_id: StableId,
    pub predecessor_id: StableId,
    pub predecessor_generation: Generation,
    pub candidate_id: StableId,
    pub candidate_generation: Generation,
    pub candidate_artifact_digest: Digest32,
    pub rollback_digest: Digest32,
}

pub fn selection_signing_payload_v1(
    policy: &SelfEvolutionSelectionPolicyV1,
    request: &SelfEvolutionSelectionRequestV1,
    evaluation: &SignedEvaluationDecisionV1,
    dataset: &DatasetSnapshotReceiptV3,
) -> Result<Vec<u8>, SelfEvolutionSelectionError> {
    validate_policy(policy)?;
    validate_request(request)?;
    let mut bytes = b"hepta.intelligence-eval.self-evolution-selection.v1".to_vec();
    for id in [
        &request.selection_id,
        &request.predecessor_id,
        &request.candidate_id,
        &policy.no_change_baseline_id,
        &evaluation.decision.evaluation_id,
        &evaluation.decision.baseline_id,
    ] {
        push_id(&mut bytes, id)?;
    }
    bytes.extend_from_slice(&request.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.candidate_generation.get().to_be_bytes());
    for digest in [
        request.candidate_artifact_digest,
        request.rollback_digest,
        dataset.snapshot.dataset_digest,
        dataset.snapshot.ledger_head_digest,
        evaluation.decision.evidence_digest,
        evaluation.authentication_digest,
        evaluation.trust_digest,
    ] {
        require_digest(digest)?;
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&policy.minimum_dataset_records.to_be_bytes());
    bytes.extend_from_slice(&policy.minimum_future_window_micros.to_be_bytes());
    Ok(bytes)
}

#[allow(clippy::too_many_arguments)]
pub fn select_self_evolution_v1(
    policy: &SelfEvolutionSelectionPolicyV1,
    request: SelfEvolutionSelectionRequestV1,
    evaluation_bundle: IndependentEvaluationBundleV1,
    metric_roles: Vec<MetricRoleContractV2>,
    evaluation_evidence: &SignedEvaluationEvidenceV1,
    longitudinal_time: &LongitudinalTimeEvidenceV1,
    dataset_receipt: &DatasetSnapshotReceiptV3,
    ledger_snapshot: &LedgerSnapshot,
    selector_evidence: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SelfEvolutionSelectionReceiptV1, SelfEvolutionSelectionError> {
    validate_policy(policy)?;
    validate_request(&request)?;
    verify_dataset_snapshot_receipt_against_ledger_v3(dataset_receipt, ledger_snapshot, now)?;
    if dataset_receipt.snapshot.source_record_digests.len()
        < policy.minimum_dataset_records as usize
    {
        return Err(SelfEvolutionSelectionError::DatasetTooSmall);
    }
    if evaluation_bundle.dataset_digest != dataset_receipt.snapshot.dataset_digest
        || evaluation_bundle.objective_digest != selector_evidence.objective_digest
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    if evaluation_bundle.candidate_id != request.candidate_id
        || evaluation_bundle.baseline_id != policy.no_change_baseline_id
        || request.candidate_id == policy.no_change_baseline_id
    {
        return Err(SelfEvolutionSelectionError::NoChangeBaselineMismatch);
    }

    let evaluation = decide_with_signed_longitudinal_evidence_v3(
        evaluation_bundle.clone(),
        metric_roles.clone(),
        evaluation_evidence,
        longitudinal_time,
        policy.minimum_future_window_micros,
        verifier,
        now,
    )?;
    if evaluation.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err(SelfEvolutionSelectionError::EvaluationRejected);
    }
    if evaluation.decision.candidate_id != request.candidate_id
        || evaluation.decision.baseline_id != policy.no_change_baseline_id
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }

    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evaluation_evidence.generator_plan,
        evaluation_bundle.frozen_plan.plan_digest.as_array(),
        now,
    )?;
    let evaluator_payload = longitudinal_evaluation_signing_payload_v3(
        &evaluation_bundle,
        &metric_roles,
        longitudinal_time,
        policy.minimum_future_window_micros,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &evaluation_evidence.evaluator_bundle,
        &evaluator_payload,
        now,
    )?;

    let selector_payload = selection_signing_payload_v1(
        policy,
        &request,
        &evaluation,
        dataset_receipt,
    )?;
    let selector = verifier.verify(
        LearningEvidenceRoleV1::Selector,
        selector_evidence,
        &selector_payload,
        now,
    )?;
    let observer_payload = future_window_signing_payload_v1(
        &evaluation_bundle,
        longitudinal_time,
        policy.minimum_future_window_micros,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &longitudinal_time.observer,
        &observer_payload,
        now,
    )?;
    verify_verified_role_separation(&generator, &selector, now)?;
    verify_verified_role_separation(&evaluator, &selector, now)?;
    verify_verified_role_separation(&observer, &selector, now)?;

    let selector_evidence_digest = Digest32::of_bytes(&selector_evidence.signing_bytes());
    let mut receipt_bytes = b"hepta.intelligence-eval.self-evolution-selection-receipt.v1".to_vec();
    receipt_bytes.extend_from_slice(&selector_payload);
    receipt_bytes.extend_from_slice(selector_evidence_digest.as_array());
    receipt_bytes.extend_from_slice(&selector_evidence.signature);
    let selection_digest = Digest32::of_bytes(&receipt_bytes);

    Ok(SelfEvolutionSelectionWitnessV1 {
        selection_id: request.selection_id,
        predecessor_id: request.predecessor_id,
        predecessor_generation: request.predecessor_generation,
        candidate_id: request.candidate_id,
        candidate_generation: request.candidate_generation,
        candidate_artifact_digest: request.candidate_artifact_digest,
        rollback_digest: request.rollback_digest,
        no_change_baseline_id: policy.no_change_baseline_id.clone(),
        dataset_digest: dataset_receipt.snapshot.dataset_digest,
        ledger_head_digest: dataset_receipt.snapshot.ledger_head_digest,
        evaluation_evidence_digest: evaluation.decision.evidence_digest,
        evaluation_authentication_digest: evaluation.authentication_digest,
        selector_id: selector.principal().principal_id.clone(),
        selector_evidence_digest,
        selection_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_policy(policy: &SelfEvolutionSelectionPolicyV1) -> Result<(), SelfEvolutionSelectionError> {
    if policy.minimum_dataset_records == 0
        || policy.minimum_dataset_records > MAX_DATASET_RECORDS
        || policy.minimum_future_window_micros == 0
    {
        return Err(SelfEvolutionSelectionError::InvalidPolicy);
    }
    Ok(())
}

fn validate_request(request: &SelfEvolutionSelectionRequestV1) -> Result<(), SelfEvolutionSelectionError> {
    if request.predecessor_generation.next().ok() != Some(request.candidate_generation) {
        return Err(SelfEvolutionSelectionError::GenerationMismatch);
    }
    if request.predecessor_id == request.candidate_id {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    require_digest(request.candidate_artifact_digest)?;
    require_digest(request.rollback_digest)
}

fn require_digest(digest: Digest32) -> Result<(), SelfEvolutionSelectionError> {
    if digest.is_zero() {
        return Err(SelfEvolutionSelectionError::EmptyDigest);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), SelfEvolutionSelectionError> {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| SelfEvolutionSelectionError::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SelfEvolutionSelectionError {
    Dataset(DatasetReceiptError),
    Evaluation(SignedEvaluationError),
    Evidence(SignedEvidenceError),
    InvalidPolicy,
    DatasetTooSmall,
    NoChangeBaselineMismatch,
    BindingMismatch,
    GenerationMismatch,
    EvaluationRejected,
    EmptyDigest,
    Arithmetic,
}

impl fmt::Display for SelfEvolutionSelectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SelfEvolutionSelectionError {}

impl From<DatasetReceiptError> for SelfEvolutionSelectionError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}
impl From<SignedEvaluationError> for SelfEvolutionSelectionError {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Evaluation(value)
    }
}
impl From<SignedEvidenceError> for SelfEvolutionSelectionError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

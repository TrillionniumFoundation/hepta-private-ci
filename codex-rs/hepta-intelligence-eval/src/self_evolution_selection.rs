//! Independent self-evolution selection and rollback admission.
//!
//! Evaluation, selection and behavior consumption remain separate identities.
//! This module verifies real longitudinal evaluation and authoritative ledger
//! membership before it prepares a selection, then requires an independently
//! trusted selector signature before returning an opaque runtime token. Rollback
//! requires a fresh independent evaluator signature over the exact selected
//! candidate and regression evidence. None of these values grants merge,
//! promotion, release, tool, model or external-effect authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_learning_ledger::verify_verified_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDispositionV1;
use crate::LongitudinalTimeEvidenceV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_with_signed_longitudinal_evidence_v3;
use crate::future_window_signing_payload_v1;
use crate::longitudinal_evaluation_signing_payload_v3;

const MAX_DATASET_RECORDS: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionPolicyV1 {
    pub no_change_baseline_id: StableId,
    pub no_change_baseline_digest: Digest32,
    pub minimum_dataset_records: u32,
    pub minimum_future_window_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionRequestV1 {
    pub selection_id: StableId,
    pub predecessor_id: StableId,
    pub predecessor_generation: Generation,
    pub predecessor_artifact_digest: Digest32,
    pub candidate_id: StableId,
    pub candidate_generation: Generation,
    pub candidate_artifact_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionSelectionReceiptV1 {
    pub selection_id: StableId,
    pub objective_digest: Digest32,
    pub predecessor_id: StableId,
    pub predecessor_generation: Generation,
    pub predecessor_artifact_digest: Digest32,
    pub candidate_id: StableId,
    pub candidate_generation: Generation,
    pub candidate_artifact_digest: Digest32,
    pub no_change_baseline_id: StableId,
    pub no_change_baseline_digest: Digest32,
    pub dataset_digest: Digest32,
    pub ledger_head_digest: Digest32,
    pub evaluation_evidence_digest: Digest32,
    pub evaluation_authentication_digest: Digest32,
    pub evaluation_trust_digest: Digest32,
    pub frozen_plan_digest: Digest32,
    pub minimum_dataset_records: u32,
    pub minimum_future_window_micros: u64,
    pub authority: AuthorityPosture,
}

/// Prepared selection with the independently verified generator, evaluator and
/// observer identities retained in memory until a separate selector signs the
/// exact selection payload. Fields are private so callers cannot fabricate the
/// role-verification state.
#[derive(Clone, Debug)]
pub struct PreparedSelfEvolutionSelectionV1 {
    receipt: SelfEvolutionSelectionReceiptV1,
    generator: VerifiedLearningEvidenceV1,
    evaluator: VerifiedLearningEvidenceV1,
    observer: VerifiedLearningEvidenceV1,
}

impl PreparedSelfEvolutionSelectionV1 {
    #[must_use]
    pub fn receipt(&self) -> &SelfEvolutionSelectionReceiptV1 {
        &self.receipt
    }
}

/// Opaque token returned only after selector signature and role-separation
/// verification. Runtime consumers may inspect the receipt but cannot construct
/// a token from receipt bytes alone.
#[derive(Clone, Debug)]
pub struct VerifiedSelfEvolutionSelectionV1 {
    receipt: SelfEvolutionSelectionReceiptV1,
    selector: VerifiedLearningEvidenceV1,
    selector_evidence_digest: Digest32,
    selection_digest: Digest32,
    admitted_at: u64,
    evaluation_actors: [VerifiedLearningEvidenceV1; 3],
}

impl VerifiedSelfEvolutionSelectionV1 {
    /// Cached selection cannot outlive its evidence or a host trust rotation.
    /// This grants no model effect: consumers still need their final-use token.
    pub fn revalidate_current(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), SelfEvolutionSelectionError> {
        if verifier.trust_digest() != self.receipt.evaluation_trust_digest
            || now < self.admitted_at
        {
            return Err(SelfEvolutionSelectionError::BindingMismatch);
        }
        for actor in &self.evaluation_actors {
            verify_verified_role_separation(&self.selector, actor, now)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn receipt(&self) -> &SelfEvolutionSelectionReceiptV1 {
        &self.receipt
    }

    #[must_use]
    pub fn selector_id(&self) -> &StableId {
        &self.selector.principal().principal_id
    }

    #[must_use]
    pub fn selector_evidence_digest(&self) -> Digest32 {
        self.selector_evidence_digest
    }

    #[must_use]
    pub fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }
}

/// Opaque rollback admission. Restoring predecessor bytes advances the runtime
/// generation rather than resurrecting the predecessor generation.
#[derive(Clone, Debug)]
pub struct VerifiedSelfEvolutionRollbackV1 {
    selection: VerifiedSelfEvolutionSelectionV1,
    evaluator: VerifiedLearningEvidenceV1,
    regression_evidence_digest: Digest32,
    rollback_generation: Generation,
    rollback_digest: Digest32,
    admitted_at: u64,
}

impl VerifiedSelfEvolutionRollbackV1 {
    /// A rollback restores previously admitted bytes, but its new authorization
    /// must remain live. It cannot outlive current selector/evaluator trust.
    pub fn revalidate_current(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), SelfEvolutionSelectionError> {
        if verifier.trust_digest() != self.selection.receipt.evaluation_trust_digest
            || now < self.admitted_at
        {
            return Err(SelfEvolutionSelectionError::BindingMismatch);
        }
        verify_verified_role_separation(&self.selection.selector, &self.evaluator, now)?;
        Ok(())
    }

    #[must_use]
    pub fn rollback_digest(&self) -> Digest32 {
        self.rollback_digest
    }

    #[must_use]
    pub fn selection(&self) -> &VerifiedSelfEvolutionSelectionV1 {
        &self.selection
    }

    #[must_use]
    pub fn evaluator_id(&self) -> &StableId {
        &self.evaluator.principal().principal_id
    }

    #[must_use]
    pub fn regression_evidence_digest(&self) -> Digest32 {
        self.regression_evidence_digest
    }

    #[must_use]
    pub fn rollback_generation(&self) -> Generation {
        self.rollback_generation
    }
}

#[allow(clippy::too_many_arguments)]
pub fn prepare_self_evolution_selection_v1(
    policy: &SelfEvolutionSelectionPolicyV1,
    request: SelfEvolutionSelectionRequestV1,
    evaluation_bundle: IndependentEvaluationBundleV1,
    metric_roles: Vec<MetricRoleContractV2>,
    evaluation_evidence: &SignedEvaluationEvidenceV1,
    longitudinal_time: &LongitudinalTimeEvidenceV1,
    dataset_receipt: &DatasetSnapshotReceiptV3,
    ledger_snapshot: &LedgerSnapshot,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<PreparedSelfEvolutionSelectionV1, SelfEvolutionSelectionError> {
    validate_policy(policy)?;
    validate_request(policy, &request)?;
    verify_dataset_snapshot_receipt_against_ledger_v3(dataset_receipt, ledger_snapshot, now)?;
    if dataset_receipt.snapshot.source_record_digests.len()
        < policy.minimum_dataset_records as usize
    {
        return Err(SelfEvolutionSelectionError::DatasetTooSmall);
    }
    if evaluation_bundle.dataset_digest != dataset_receipt.snapshot.dataset_digest
        || evaluation_bundle.objective_digest != dataset_receipt.snapshot.objective_digest
        || evaluation_bundle.candidate_id != request.candidate_id
        || evaluation_bundle.baseline_id != policy.no_change_baseline_id
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
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
    verify_verified_role_separation(&generator, &evaluator, now)?;
    verify_verified_role_separation(&generator, &observer, now)?;
    verify_verified_role_separation(&evaluator, &observer, now)?;

    let receipt = SelfEvolutionSelectionReceiptV1 {
        selection_id: request.selection_id,
        objective_digest: evaluation_bundle.objective_digest,
        predecessor_id: request.predecessor_id,
        predecessor_generation: request.predecessor_generation,
        predecessor_artifact_digest: request.predecessor_artifact_digest,
        candidate_id: request.candidate_id,
        candidate_generation: request.candidate_generation,
        candidate_artifact_digest: request.candidate_artifact_digest,
        no_change_baseline_id: policy.no_change_baseline_id.clone(),
        no_change_baseline_digest: policy.no_change_baseline_digest,
        dataset_digest: dataset_receipt.snapshot.dataset_digest,
        ledger_head_digest: dataset_receipt.snapshot.ledger_head_digest,
        evaluation_evidence_digest: evaluation.decision.evidence_digest,
        evaluation_authentication_digest: evaluation.authentication_digest,
        evaluation_trust_digest: evaluation.trust_digest,
        frozen_plan_digest: evaluation_bundle.frozen_plan.plan_digest,
        minimum_dataset_records: policy.minimum_dataset_records,
        minimum_future_window_micros: policy.minimum_future_window_micros,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(PreparedSelfEvolutionSelectionV1 {
        receipt,
        generator,
        evaluator,
        observer,
    })
}

pub fn selection_signing_payload_v1(
    receipt: &SelfEvolutionSelectionReceiptV1,
) -> Result<Vec<u8>, SelfEvolutionSelectionError> {
    validate_receipt(receipt)?;
    let mut bytes = b"hepta.intelligence-eval.self-evolution-selection.v1\0".to_vec();
    for id in [
        &receipt.selection_id,
        &receipt.predecessor_id,
        &receipt.candidate_id,
        &receipt.no_change_baseline_id,
    ] {
        push_id(&mut bytes, id)?;
    }
    bytes.extend_from_slice(&receipt.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.candidate_generation.get().to_be_bytes());
    for digest in [
        receipt.objective_digest,
        receipt.predecessor_artifact_digest,
        receipt.candidate_artifact_digest,
        receipt.no_change_baseline_digest,
        receipt.dataset_digest,
        receipt.ledger_head_digest,
        receipt.evaluation_evidence_digest,
        receipt.evaluation_authentication_digest,
        receipt.evaluation_trust_digest,
        receipt.frozen_plan_digest,
    ] {
        require_digest(digest)?;
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.minimum_dataset_records.to_be_bytes());
    bytes.extend_from_slice(&receipt.minimum_future_window_micros.to_be_bytes());
    Ok(bytes)
}

pub fn admit_self_evolution_selection_v1(
    prepared: PreparedSelfEvolutionSelectionV1,
    selector_evidence: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<VerifiedSelfEvolutionSelectionV1, SelfEvolutionSelectionError> {
    if verifier.trust_digest() != prepared.receipt.evaluation_trust_digest {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let payload = selection_signing_payload_v1(&prepared.receipt)?;
    let selector = verifier.verify(
        LearningEvidenceRoleV1::Selector,
        selector_evidence,
        &payload,
        now,
    )?;
    for role in [&prepared.generator, &prepared.evaluator, &prepared.observer] {
        verify_verified_role_separation(&selector, role, now)?;
    }
    let selector_evidence_digest = Digest32::of_bytes(&selector_evidence.signing_bytes());
    let mut digest_bytes =
        b"hepta.intelligence-eval.self-evolution-selection-receipt.v1\0".to_vec();
    digest_bytes.extend_from_slice(&payload);
    digest_bytes.extend_from_slice(selector_evidence_digest.as_array());
    digest_bytes.extend_from_slice(&selector_evidence.signature);
    Ok(VerifiedSelfEvolutionSelectionV1 {
        receipt: prepared.receipt,
        selector,
        selector_evidence_digest,
        selection_digest: Digest32::of_bytes(&digest_bytes),
        admitted_at: now,
        evaluation_actors: [prepared.generator, prepared.evaluator, prepared.observer],
    })
}

pub fn rollback_signing_payload_v1(
    selection: &VerifiedSelfEvolutionSelectionV1,
    regression_evidence_digest: Digest32,
) -> Result<Vec<u8>, SelfEvolutionSelectionError> {
    require_digest(regression_evidence_digest)?;
    let receipt = selection.receipt();
    let mut bytes = b"hepta.intelligence-eval.self-evolution-rollback.v1\0".to_vec();
    bytes.extend_from_slice(selection.selection_digest().as_array());
    bytes.extend_from_slice(receipt.candidate_artifact_digest.as_array());
    bytes.extend_from_slice(receipt.predecessor_artifact_digest.as_array());
    bytes.extend_from_slice(&receipt.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(regression_evidence_digest.as_array());
    Ok(bytes)
}

pub fn admit_self_evolution_rollback_v1(
    selection: &VerifiedSelfEvolutionSelectionV1,
    regression_evidence_digest: Digest32,
    evaluator_evidence: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<VerifiedSelfEvolutionRollbackV1, SelfEvolutionSelectionError> {
    if verifier.trust_digest() != selection.receipt.evaluation_trust_digest {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    let payload = rollback_signing_payload_v1(selection, regression_evidence_digest)?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evaluator_evidence,
        &payload,
        now,
    )?;
    verify_verified_role_separation(&selection.selector, &evaluator, now)?;
    let rollback_generation = selection
        .receipt
        .candidate_generation
        .next()
        .map_err(|_| SelfEvolutionSelectionError::GenerationMismatch)?;
    let mut signed_bytes = b"hepta.intelligence-eval.verified-rollback.v1\0".to_vec();
    signed_bytes.extend_from_slice(&payload);
    signed_bytes.extend_from_slice(&evaluator_evidence.signing_bytes());
    signed_bytes.extend_from_slice(&evaluator_evidence.signature);
    Ok(VerifiedSelfEvolutionRollbackV1 {
        selection: selection.clone(),
        evaluator,
        regression_evidence_digest,
        rollback_generation,
        rollback_digest: Digest32::of_bytes(&signed_bytes),
        admitted_at: now,
    })
}

fn validate_policy(
    policy: &SelfEvolutionSelectionPolicyV1,
) -> Result<(), SelfEvolutionSelectionError> {
    if policy.minimum_dataset_records == 0
        || policy.minimum_dataset_records > MAX_DATASET_RECORDS
        || policy.minimum_future_window_micros == 0
    {
        return Err(SelfEvolutionSelectionError::InvalidPolicy);
    }
    require_digest(policy.no_change_baseline_digest)
}

fn validate_request(
    policy: &SelfEvolutionSelectionPolicyV1,
    request: &SelfEvolutionSelectionRequestV1,
) -> Result<(), SelfEvolutionSelectionError> {
    if request.predecessor_generation.next().ok() != Some(request.candidate_generation) {
        return Err(SelfEvolutionSelectionError::GenerationMismatch);
    }
    if request.predecessor_id == request.candidate_id
        || request.predecessor_id != policy.no_change_baseline_id
        || request.predecessor_artifact_digest != policy.no_change_baseline_digest
        || request.predecessor_artifact_digest == request.candidate_artifact_digest
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    require_digest(request.predecessor_artifact_digest)?;
    require_digest(request.candidate_artifact_digest)
}

fn validate_receipt(
    receipt: &SelfEvolutionSelectionReceiptV1,
) -> Result<(), SelfEvolutionSelectionError> {
    if receipt.authority != AuthorityPosture::DENY_ALL
        || receipt.predecessor_generation.next().ok() != Some(receipt.candidate_generation)
        || receipt.predecessor_id != receipt.no_change_baseline_id
        || receipt.predecessor_artifact_digest != receipt.no_change_baseline_digest
        || receipt.predecessor_id == receipt.candidate_id
        || receipt.predecessor_artifact_digest == receipt.candidate_artifact_digest
        || receipt.minimum_dataset_records == 0
        || receipt.minimum_dataset_records > MAX_DATASET_RECORDS
        || receipt.minimum_future_window_micros == 0
    {
        return Err(SelfEvolutionSelectionError::BindingMismatch);
    }
    Ok(())
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

#[cfg(test)]
#[path = "self_evolution_selection_tests.rs"]
mod tests;

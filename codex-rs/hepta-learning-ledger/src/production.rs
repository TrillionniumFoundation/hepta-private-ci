//! Product-facing causal ledger writer.
//!
//! This facade is the only API in this crate that combines current-anchor CAS,
//! signed evidence admission, V2 semantic validation and durable append. The
//! lower-level V1 journal remains for historical replay and qualification
//! compatibility; product composition should bind this writer instead.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AnchorWitnessError;
use crate::AppendReceipt;
use crate::AuthenticatedOutcomeV1;
use crate::CandidateSetCompletenessReceiptV1;
use crate::CausalV2Error;
use crate::CreditAllocationBatchV1;
use crate::CreditAllocationV1;
use crate::DatasetFreezeRequestV1;
use crate::DatasetReceiptError;
use crate::DatasetSnapshotReceiptV3;
use crate::DurableAnchorWitness;
use crate::DurableLearningJournal;
use crate::DurableLedgerError;
use crate::EpisodeDecision;
use crate::OutcomeTerminalityV1;
use crate::LearningEvidenceRoleV1;
use crate::LearningEvidenceVerifierV1;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::Revocation;
use crate::SignedEvidenceError;
use crate::SignedLearningEvidenceV1;
use crate::UnlearningLineageEventV1;
use crate::UnlearningLineageReceiptV1;
use crate::VerifiedLearningEvidenceV1;
use crate::finalize_credit_batch;
use crate::freeze_dataset_receipt_v3;
use crate::validate_authenticated_outcome;
use crate::validate_candidate_set_completeness;
use crate::verify_signed_role_separation;

pub struct ProductionLedgerWriter<J: DurableLearningJournal> {
    journal: J,
    verifier: LearningEvidenceVerifierV1,
}

pub fn decision_admission_payload(
    decision: &EpisodeDecision,
    completeness: &CandidateSetCompletenessReceiptV1,
) -> Result<Vec<u8>, CausalV2Error> {
    let completeness_digest = validate_candidate_set_completeness(completeness)?;
    let mut candidates = decision.candidate_ids.clone();
    candidates.sort();
    let mut bytes = b"hepta.learning-ledger.production-decision.v1".to_vec();
    push_id(&mut bytes, &decision.record_id);
    push_id(&mut bytes, &decision.episode_id);
    bytes.extend_from_slice(decision.objective_digest.as_array());
    push_id(&mut bytes, &decision.policy_id);
    push_len(&mut bytes, candidates.len());
    for candidate in &candidates {
        push_id(&mut bytes, candidate);
    }
    push_id(&mut bytes, &decision.selected_candidate_id);
    bytes.extend_from_slice(&decision.selected_propensity.raw().to_be_bytes());
    bytes.push(decision.completeness.tag());
    bytes.extend_from_slice(completeness_digest.as_array());
    Ok(bytes)
}

#[must_use]
pub fn authenticated_outcome_admission_payload(outcome: &AuthenticatedOutcomeV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.production-outcome.v1".to_vec();
    push_id(&mut bytes, &outcome.record_id);
    push_id(&mut bytes, &outcome.outcome_id);
    push_id(&mut bytes, &outcome.episode_id);
    push_principal(&mut bytes, &outcome.observer);
    push_optional_u64(&mut bytes, outcome.observed_at);
    push_optional_i64(&mut bytes, outcome.value.map(|value| value.raw()));
    bytes.extend_from_slice(outcome.unit_profile_digest.as_array());
    bytes.extend_from_slice(&outcome.watermark.latest_observable_at.to_be_bytes());
    bytes.extend_from_slice(outcome.watermark.expected_delay_profile_digest.as_array());
    bytes.push(match outcome.watermark.terminality {
        OutcomeTerminalityV1::Pending => 0,
        OutcomeTerminalityV1::Censored => 1,
        OutcomeTerminalityV1::Terminal => 2,
    });
    push_optional_id(&mut bytes, outcome.watermark.censoring_reason.as_ref());
    push_optional_id(
        &mut bytes,
        outcome.watermark.correction_predecessor.as_ref(),
    );
    push_optional_u64(&mut bytes, outcome.watermark.finalized_at);
    bytes
}

#[must_use]
pub fn credit_batch_admission_payload(batch: &CreditAllocationBatchV1) -> Vec<u8> {
    let mut allocations: Vec<CreditAllocationV1> = batch.allocations.clone();
    allocations.sort_by_key(|allocation| allocation.target_id.clone());
    let mut bytes = b"hepta.learning-ledger.production-credit-batch.v1".to_vec();
    push_id(&mut bytes, &batch.batch_id);
    push_id(&mut bytes, &batch.episode_id);
    push_id(&mut bytes, &batch.outcome_id);
    push_principal(&mut bytes, &batch.allocator);
    bytes.extend_from_slice(&batch.terminal_outcome.raw().to_be_bytes());
    push_len(&mut bytes, allocations.len());
    for allocation in &allocations {
        push_id(&mut bytes, &allocation.target_id);
        bytes.extend_from_slice(&allocation.credit.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&batch.conservation_residual.raw().to_be_bytes());
    bytes.push(u8::from(batch.finalized));
    bytes
}

#[must_use]
pub fn dataset_freeze_admission_payload(request: &DatasetFreezeRequestV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.production-dataset-freeze.v1".to_vec();
    push_id(&mut bytes, &request.snapshot_id);
    push_principal(&mut bytes, &request.producer);
    bytes.extend_from_slice(request.ledger_head_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(&request.eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&request.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(request.correction_cut_digest.as_array());
    bytes.extend_from_slice(request.revocation_cut_digest.as_array());
    bytes.extend_from_slice(request.inclusion_policy_digest.as_array());
    push_len(&mut bytes, request.source_record_digests.len());
    for digest in &request.source_record_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.pending_outcomes.to_be_bytes());
    bytes.extend_from_slice(&request.censored_outcomes.to_be_bytes());
    bytes
}

#[must_use]
pub fn revocation_admission_payload(revocation: &Revocation) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.production-revocation.v1".to_vec();
    push_id(&mut bytes, &revocation.record_id);
    push_id(&mut bytes, &revocation.target_record_id);
    push_id(&mut bytes, &revocation.authority_id);
    bytes
}

#[must_use]
pub fn unlearning_admission_payload(lineage: &UnlearningLineageEventV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.production-unlearning.v1".to_vec();
    push_id(&mut bytes, &lineage.record_id);
    push_id(&mut bytes, &lineage.source_record_id);
    push_id(&mut bytes, &lineage.derived_id);
    bytes.push(lineage.derived_kind.tag());
    push_optional_id(&mut bytes, lineage.predecessor.as_ref());
    push_id(&mut bytes, &lineage.authority_id);
    bytes.extend_from_slice(lineage.source_digest.as_array());
    bytes.extend_from_slice(lineage.derived_digest.as_array());
    bytes
}

impl<J: DurableLearningJournal> ProductionLedgerWriter<J> {
    #[must_use]
    pub fn new(journal: J, verifier: LearningEvidenceVerifierV1) -> Self {
        Self { journal, verifier }
    }

    #[must_use]
    pub fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        &self.verifier
    }

    #[must_use]
    pub fn into_inner(self) -> J {
        self.journal
    }

    pub fn current_anchor(&self) -> Result<LedgerAnchor, ProductionLedgerError> {
        self.journal.anchor().map_err(Into::into)
    }

    pub fn retain_acknowledgement(
        &self,
        witness: &mut DurableAnchorWitness,
        receipt: &AppendReceipt,
    ) -> Result<LedgerAnchor, ProductionLedgerError> {
        let expected = LedgerAnchor {
            sequence: receipt.sequence.get(),
            chain_digest: receipt.chain_digest,
        };
        if self.journal.anchor()? != expected {
            return Err(ProductionLedgerError::StaleAnchor);
        }
        witness.publish(expected)?;
        if witness.current()? != Some(expected) {
            return Err(ProductionLedgerError::WitnessFrontierMismatch);
        }
        Ok(expected)
    }

    pub fn append_decision(
        &mut self,
        expected_anchor: LedgerAnchor,
        decision: EpisodeDecision,
        completeness: &CandidateSetCompletenessReceiptV1,
        evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        now: u64,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        self.require_anchor(expected_anchor)?;
        let expected_payload = decision_admission_payload(&decision, completeness)?;
        require_exact_payload(payload, &expected_payload)?;
        let verified = self
            .verifier
            .verify(LearningEvidenceRoleV1::Generator, evidence, payload, now)?;

        if completeness.generator_id != verified.principal().principal_id
            || decision.policy_id != verified.principal().principal_id
        {
            return Err(ProductionLedgerError::PrincipalMismatch);
        }
        if usize::try_from(completeness.candidate_count).ok() != Some(decision.candidate_ids.len()) {
            return Err(ProductionLedgerError::CandidateCountMismatch);
        }
        if decision.support_digest != evidence.payload_digest {
            return Err(ProductionLedgerError::SupportDigestMismatch);
        }

        self.journal
            .append(expected_anchor.chain_digest, LedgerEvent::Decision(decision))
            .map_err(Into::into)
    }

    pub fn append_authenticated_outcome(
        &mut self,
        expected_anchor: LedgerAnchor,
        generator: &VerifiedLearningEvidenceV1,
        outcome: AuthenticatedOutcomeV1,
        observer_evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        now: u64,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        self.require_anchor(expected_anchor)?;
        let expected_payload = authenticated_outcome_admission_payload(&outcome);
        require_exact_payload(payload, &expected_payload)?;
        let observer = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            observer_evidence,
            payload,
            now,
        )?;
        verify_signed_role_separation(generator, &observer, now)?;
        if &outcome.observer != observer.principal() {
            return Err(ProductionLedgerError::PrincipalMismatch);
        }
        if outcome.support_digest != observer_evidence.payload_digest {
            return Err(ProductionLedgerError::SupportDigestMismatch);
        }
        validate_authenticated_outcome(generator.principal(), &outcome, now)?;

        self.journal
            .append(
                expected_anchor.chain_digest,
                LedgerEvent::AuthenticatedOutcome(outcome),
            )
            .map_err(Into::into)
    }

    pub fn append_credit_batch(
        &mut self,
        expected_anchor: LedgerAnchor,
        batch: CreditAllocationBatchV1,
        evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        now: u64,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        self.require_anchor(expected_anchor)?;
        let expected_payload = credit_batch_admission_payload(&batch);
        require_exact_payload(payload, &expected_payload)?;
        let allocator =
            self.verifier
                .verify(LearningEvidenceRoleV1::Evaluator, evidence, payload, now)?;
        if &batch.allocator != allocator.principal() {
            return Err(ProductionLedgerError::PrincipalMismatch);
        }
        if batch.support_digest != evidence.payload_digest {
            return Err(ProductionLedgerError::SupportDigestMismatch);
        }
        finalize_credit_batch(batch.clone(), now)?;

        self.journal
            .append(
                expected_anchor.chain_digest,
                LedgerEvent::CreditBatch(batch),
            )
            .map_err(Into::into)
    }

    pub fn append_revocation(
        &mut self,
        expected_anchor: LedgerAnchor,
        revocation: Revocation,
        evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        now: u64,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        self.require_anchor(expected_anchor)?;
        let expected_payload = revocation_admission_payload(&revocation);
        require_exact_payload(payload, &expected_payload)?;
        let authority =
            self.verifier
                .verify(LearningEvidenceRoleV1::Evaluator, evidence, payload, now)?;
        if revocation.authority_id != authority.principal().principal_id {
            return Err(ProductionLedgerError::PrincipalMismatch);
        }
        if revocation.reason_digest != evidence.payload_digest {
            return Err(ProductionLedgerError::SupportDigestMismatch);
        }
        self.journal
            .append(
                expected_anchor.chain_digest,
                LedgerEvent::Revocation(revocation),
            )
            .map_err(Into::into)
    }

    pub fn append_unlearning_lineage(
        &mut self,
        expected_anchor: LedgerAnchor,
        lineage: UnlearningLineageEventV1,
        evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        now: u64,
    ) -> Result<UnlearningLineageReceiptV1, ProductionLedgerError> {
        self.require_anchor(expected_anchor)?;
        let expected_payload = unlearning_admission_payload(&lineage);
        require_exact_payload(payload, &expected_payload)?;
        let authority =
            self.verifier
                .verify(LearningEvidenceRoleV1::Evaluator, evidence, payload, now)?;
        if lineage.authority_id != authority.principal().principal_id {
            return Err(ProductionLedgerError::PrincipalMismatch);
        }
        if lineage.reason_digest != evidence.payload_digest {
            return Err(ProductionLedgerError::SupportDigestMismatch);
        }

        let record_id = lineage.record_id.clone();
        let source_record_id = lineage.source_record_id.clone();
        let derived_id = lineage.derived_id.clone();
        let receipt = self.journal.append(
            expected_anchor.chain_digest,
            LedgerEvent::UnlearningLineage(lineage),
        )?;
        Ok(UnlearningLineageReceiptV1 {
            record_id,
            source_record_id,
            derived_id,
            event_digest: receipt.event_digest,
            chain_digest: receipt.chain_digest,
        })
    }

    pub fn prepare_dataset_freeze_request(
        &self,
        expected_anchor: LedgerAnchor,
        snapshot_id: StableId,
        producer: crate::AuthenticatedPrincipalV1,
        objective_digest: Digest32,
        outcome_watermark: u64,
        inclusion_policy_digest: Digest32,
    ) -> Result<DatasetFreezeRequestV1, ProductionLedgerError> {
        self.require_anchor(expected_anchor)?;
        let snapshot = self.journal.snapshot()?;
        if snapshot.head_digest != expected_anchor.chain_digest {
            return Err(ProductionLedgerError::StaleAnchor);
        }
        let ledger = LearningLedger::from_snapshot(snapshot)
            .map_err(DurableLedgerError::Semantic)?;
        let source_record_digests = ledger.dataset_source_record_digests();
        let (pending_outcomes, censored_outcomes) = ledger.outcome_state_counts();
        Ok(DatasetFreezeRequestV1 {
            snapshot_id,
            producer,
            ledger_head_digest: ledger.head_digest(),
            objective_digest,
            eligible_frontier: ledger.head_sequence(),
            outcome_watermark,
            correction_cut_digest: ledger.correction_cut_digest(),
            revocation_cut_digest: ledger.revocation_cut_digest(),
            inclusion_policy_digest,
            source_record_digests,
            pending_outcomes,
            censored_outcomes,
        })
    }

    pub fn freeze_dataset_from_ledger(
        &self,
        expected_anchor: LedgerAnchor,
        snapshot_id: StableId,
        objective_digest: Digest32,
        outcome_watermark: u64,
        inclusion_policy_digest: Digest32,
        producer_evidence: &SignedLearningEvidenceV1,
        producer_payload: &[u8],
        now: u64,
    ) -> Result<DatasetSnapshotReceiptV3, ProductionLedgerError> {
        self.require_anchor(expected_anchor)?;
        let producer = self.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            producer_evidence,
            producer_payload,
            now,
        )?;
        let request = self.prepare_dataset_freeze_request(
            expected_anchor,
            snapshot_id,
            producer.principal().clone(),
            objective_digest,
            outcome_watermark,
            inclusion_policy_digest,
        )?;
        let expected_payload = dataset_freeze_admission_payload(&request);
        require_exact_payload(producer_payload, &expected_payload)?;
        freeze_dataset_receipt_v3(request, now).map_err(Into::into)
    }

    fn require_anchor(&self, expected: LedgerAnchor) -> Result<(), ProductionLedgerError> {
        if self.journal.anchor()? != expected {
            return Err(ProductionLedgerError::StaleAnchor);
        }
        Ok(())
    }
}

fn require_exact_payload(
    actual: &[u8],
    expected: &[u8],
) -> Result<(), ProductionLedgerError> {
    if actual != expected {
        return Err(ProductionLedgerError::AdmissionPayloadMismatch);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_len(bytes, value.as_str().len());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u32::try_from(value).unwrap_or(u32::MAX).to_be_bytes());
}

fn push_principal(bytes: &mut Vec<u8>, value: &crate::AuthenticatedPrincipalV1) {
    push_id(bytes, &value.principal_id);
    bytes.extend_from_slice(value.credential_chain_digest.as_array());
    bytes.extend_from_slice(value.signing_key_digest.as_array());
    bytes.extend_from_slice(value.scope_digest.as_array());
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&value.expires_at.to_be_bytes());
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
}

fn push_optional_i64(bytes: &mut Vec<u8>, value: Option<i64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionLedgerError {
    Durable(DurableLedgerError),
    Signed(SignedEvidenceError),
    Causal(CausalV2Error),
    Dataset(DatasetReceiptError),
    Witness(AnchorWitnessError),
    StaleAnchor,
    PrincipalMismatch,
    CandidateCountMismatch,
    SupportDigestMismatch,
    AdmissionPayloadMismatch,
    WitnessFrontierMismatch,
}

impl fmt::Display for ProductionLedgerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductionLedgerError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Durable(error) => Some(error),
            Self::Signed(error) => Some(error),
            Self::Causal(error) => Some(error),
            Self::Dataset(error) => Some(error),
            Self::Witness(error) => Some(error),
            Self::StaleAnchor
            | Self::PrincipalMismatch
            | Self::CandidateCountMismatch
            | Self::SupportDigestMismatch
            | Self::AdmissionPayloadMismatch
            | Self::WitnessFrontierMismatch => None,
        }
    }
}

impl From<DurableLedgerError> for ProductionLedgerError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Durable(value)
    }
}

impl From<SignedEvidenceError> for ProductionLedgerError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Signed(value)
    }
}

impl From<CausalV2Error> for ProductionLedgerError {
    fn from(value: CausalV2Error) -> Self {
        Self::Causal(value)
    }
}

impl From<AnchorWitnessError> for ProductionLedgerError {
    fn from(value: AnchorWitnessError) -> Self {
        Self::Witness(value)
    }
}

impl From<DatasetReceiptError> for ProductionLedgerError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}

#[cfg(test)]
#[path = "production_tests.rs"]
mod tests;

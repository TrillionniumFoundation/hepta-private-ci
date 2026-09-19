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

use crate::AppendReceipt;
use crate::AuthenticatedOutcomeV1;
use crate::CandidateSetCompletenessReceiptV1;
use crate::CausalV2Error;
use crate::CreditAllocationBatchV1;
use crate::DatasetFreezeRequestV1;
use crate::DatasetReceiptError;
use crate::DatasetSnapshotReceiptV3;
use crate::DurableLearningJournal;
use crate::DurableLedgerError;
use crate::EpisodeDecision;
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
        let verified = self
            .verifier
            .verify(LearningEvidenceRoleV1::Generator, evidence, payload, now)?;
        validate_candidate_set_completeness(completeness)?;

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

        let snapshot = self.journal.snapshot()?;
        if snapshot.head_digest != expected_anchor.chain_digest {
            return Err(ProductionLedgerError::StaleAnchor);
        }
        let ledger = LearningLedger::from_snapshot(snapshot)
            .map_err(|error| DurableLedgerError::Semantic(error))?;
        let source_record_digests = ledger.dataset_source_record_digests();
        let (pending_outcomes, censored_outcomes) = ledger.outcome_state_counts();

        let request = DatasetFreezeRequestV1 {
            snapshot_id,
            producer: producer.principal().clone(),
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
        };
        freeze_dataset_receipt_v3(request, now).map_err(Into::into)
    }

    fn require_anchor(&self, expected: LedgerAnchor) -> Result<(), ProductionLedgerError> {
        if self.journal.anchor()? != expected {
            return Err(ProductionLedgerError::StaleAnchor);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionLedgerError {
    Durable(DurableLedgerError),
    Signed(SignedEvidenceError),
    Causal(CausalV2Error),
    Dataset(DatasetReceiptError),
    StaleAnchor,
    PrincipalMismatch,
    CandidateCountMismatch,
    SupportDigestMismatch,
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
            Self::StaleAnchor
            | Self::PrincipalMismatch
            | Self::CandidateCountMismatch
            | Self::SupportDigestMismatch => None,
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

impl From<DatasetReceiptError> for ProductionLedgerError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}

#[cfg(test)]
#[path = "production_tests.rs"]
mod tests;

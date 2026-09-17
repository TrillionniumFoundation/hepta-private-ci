//! Authenticated production composition for the append-only learning ledger.
//!
//! This layer makes the causal V2 validators, durable append, and independently
//! retained acknowledgement witness one fail-closed path. It still grants no
//! selection, promotion, release, model, tool, or external-effect authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AppendReceipt;
use crate::AuthenticatedDecisionRecordV2;
use crate::AuthenticatedOutcomeRecordV2;
use crate::AuthenticatedOutcomeV1;
use crate::CandidateSetCompletenessReceiptV1;
use crate::CausalV2Error;
use crate::ConservedCreditBatchRecordV2;
use crate::CreditAllocationBatchV1;
use crate::DatasetFreezeRequestV1;
use crate::DatasetReceiptError;
use crate::DatasetSnapshotReceiptV3;
use crate::DurableLearningJournal;
use crate::DurableLedgerError;
use crate::LearningEvidenceRoleV1;
use crate::LearningEvidenceVerifierV1;
use crate::LearningLedger;
use crate::LearningWitnessError;
use crate::LearningWitnessStore;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::OutcomeFinality;
use crate::OutcomeTerminalityV1;
use crate::Revocation;
use crate::SignedEvidenceError;
use crate::SignedLearningEvidenceV1;
use crate::VerifiedLearningEvidenceV1;
use crate::WitnessReceipt;
use crate::finalize_credit_batch;
use crate::freeze_dataset_receipt_v3;
use crate::validate_authenticated_outcome;
use crate::validate_candidate_set_completeness;
use crate::verify_signed_role_separation;

const MAX_DURABLE_CREDIT_ALLOCATIONS: usize = 224;
const DATASET_POLICY: &[u8] = b"hepta.learning-ledger.dataset-policy.all-active-corrected.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionDecisionRequestV1 {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub objective_digest: Digest32,
    pub policy_id: StableId,
    pub candidate_ids: Vec<StableId>,
    pub selected_candidate_id: StableId,
    pub selected_propensity: ProbabilityQ32,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub generator_evidence: SignedLearningEvidenceV1,
    pub expected_predecessor: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionOutcomeRequestV1 {
    pub outcome: AuthenticatedOutcomeV1,
    pub observer_evidence: SignedLearningEvidenceV1,
    pub expected_predecessor: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionCreditBatchRequestV1 {
    pub record_id: StableId,
    pub batch: CreditAllocationBatchV1,
    pub allocator_evidence: SignedLearningEvidenceV1,
    pub expected_predecessor: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionRevocationRequestV1 {
    pub record_id: StableId,
    pub target_record_id: StableId,
    pub reason_digest: Digest32,
    pub authority_evidence: SignedLearningEvidenceV1,
    pub expected_predecessor: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionDatasetFreezeRequestV1 {
    pub snapshot_id: StableId,
    pub objective_digest: Digest32,
    pub eligible_frontier: u64,
    pub outcome_watermark: u64,
    pub ledger_head_digest: Digest32,
    pub evaluator_evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionCommitReceiptV1 {
    pub ledger: AppendReceipt,
    pub witness: WitnessReceipt,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionDecisionCommitV1 {
    pub commit: ProductionCommitReceiptV1,
    pub generator: VerifiedLearningEvidenceV1,
}

#[derive(Debug)]
pub enum ProductionLedgerError {
    Binding(&'static str),
    UnacknowledgedTail,
    Arithmetic,
    Evidence(SignedEvidenceError),
    Causal(CausalV2Error),
    Durable(DurableLedgerError),
    Witness(LearningWitnessError),
    Dataset(DatasetReceiptError),
    Ledger(crate::LedgerError),
}

impl fmt::Display for ProductionLedgerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ProductionLedgerError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Evidence(error) => Some(error),
            Self::Causal(error) => Some(error),
            Self::Durable(error) => Some(error),
            Self::Witness(error) => Some(error),
            Self::Dataset(error) => Some(error),
            Self::Ledger(error) => Some(error),
            Self::Binding(_) | Self::UnacknowledgedTail | Self::Arithmetic => None,
        }
    }
}

impl From<SignedEvidenceError> for ProductionLedgerError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<CausalV2Error> for ProductionLedgerError {
    fn from(value: CausalV2Error) -> Self {
        Self::Causal(value)
    }
}
impl From<DurableLedgerError> for ProductionLedgerError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Durable(value)
    }
}
impl From<LearningWitnessError> for ProductionLedgerError {
    fn from(value: LearningWitnessError) -> Self {
        Self::Witness(value)
    }
}
impl From<DatasetReceiptError> for ProductionLedgerError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}
impl From<crate::LedgerError> for ProductionLedgerError {
    fn from(value: crate::LedgerError) -> Self {
        Self::Ledger(value)
    }
}

/// Single product-facing writer. Every acknowledged mutation advances the
/// durable journal first and then the independent witness; new mutations cannot
/// step over an unacknowledged durable tail.
pub struct ProductionLearningLedger<J, W> {
    verifier: LearningEvidenceVerifierV1,
    ledger: J,
    witness: W,
}

impl<J, W> ProductionLearningLedger<J, W>
where
    J: DurableLearningJournal,
    W: LearningWitnessStore,
{
    pub fn new(
        verifier: LearningEvidenceVerifierV1,
        ledger: J,
        witness: W,
    ) -> Result<Self, ProductionLedgerError> {
        let snapshot = ledger.snapshot()?;
        if anchor_for_snapshot(&snapshot)? != witness.current_anchor() {
            return Err(ProductionLedgerError::UnacknowledgedTail);
        }
        Ok(Self {
            verifier,
            ledger,
            witness,
        })
    }

    #[must_use]
    pub fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        &self.verifier
    }

    #[must_use]
    pub fn witness_anchor(&self) -> LedgerAnchor {
        self.witness.current_anchor()
    }

    pub fn snapshot(&self) -> Result<LedgerSnapshot, ProductionLedgerError> {
        self.ledger.snapshot().map_err(Into::into)
    }

    pub fn into_parts(self) -> (LearningEvidenceVerifierV1, J, W) {
        (self.verifier, self.ledger, self.witness)
    }

    pub fn append_decision(
        &mut self,
        mut request: ProductionDecisionRequestV1,
        now: u64,
    ) -> Result<ProductionDecisionCommitV1, ProductionLedgerError> {
        request.candidate_ids.sort();
        if request
            .candidate_ids
            .windows(2)
            .any(|pair| pair[0] == pair[1])
        {
            return Err(ProductionLedgerError::Binding("duplicate candidate"));
        }
        let completeness_digest = validate_candidate_set_completeness(&request.completeness)?;
        if usize::try_from(request.completeness.candidate_count).ok()
            != Some(request.candidate_ids.len())
        {
            return Err(ProductionLedgerError::Binding("candidate count"));
        }
        let payload = production_decision_signing_payload_v1(&request, completeness_digest)?;
        let generator = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &request.generator_evidence,
            &payload,
            now,
        )?;
        if request.objective_digest != request.generator_evidence.objective_digest
            || request.completeness.generator_id != generator.principal().principal_id
        {
            return Err(ProductionLedgerError::Binding("generator decision context"));
        }
        let evidence_digest = Digest32::of_bytes(&request.generator_evidence.signing_bytes());
        let event = LedgerEvent::AuthenticatedDecision(AuthenticatedDecisionRecordV2 {
            record_id: request.record_id,
            episode_id: request.episode_id,
            objective_digest: request.objective_digest,
            policy_id: request.policy_id,
            generator: generator.principal().clone(),
            completeness: request.completeness,
            candidate_ids: request.candidate_ids,
            selected_candidate_id: request.selected_candidate_id,
            selected_propensity: request.selected_propensity,
            evidence_digest,
        });
        let commit = self.commit(request.expected_predecessor, event, evidence_digest)?;
        Ok(ProductionDecisionCommitV1 { commit, generator })
    }

    pub fn append_outcome(
        &mut self,
        generator: &VerifiedLearningEvidenceV1,
        request: ProductionOutcomeRequestV1,
        now: u64,
    ) -> Result<ProductionCommitReceiptV1, ProductionLedgerError> {
        let snapshot = self.ledger.snapshot()?;
        let decision = authenticated_decision_for_episode(&snapshot, &request.outcome.episode_id)
            .ok_or(ProductionLedgerError::Binding(
                "outcome requires authenticated decision",
            ))?;
        if generator.principal() != &decision.generator
            || request.observer_evidence.objective_digest != decision.objective_digest
        {
            return Err(ProductionLedgerError::Binding("generator or objective"));
        }

        let payload = production_outcome_signing_payload_v1(
            &request.outcome,
            request.expected_predecessor,
        )?;
        let observer = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &request.observer_evidence,
            &payload,
            now,
        )?;
        if observer.principal() != &request.outcome.observer {
            return Err(ProductionLedgerError::Binding("observer principal"));
        }
        verify_signed_role_separation(generator, &observer, now)?;
        validate_authenticated_outcome(generator.principal(), &request.outcome, now)?;

        let evidence_digest = Digest32::of_bytes(&request.observer_evidence.signing_bytes());
        let event = LedgerEvent::AuthenticatedOutcome(AuthenticatedOutcomeRecordV2 {
            outcome: request.outcome,
            evidence_digest,
        });
        self.commit(request.expected_predecessor, event, evidence_digest)
    }

    pub fn append_credit_batch(
        &mut self,
        generator: &VerifiedLearningEvidenceV1,
        mut request: ProductionCreditBatchRequestV1,
        now: u64,
    ) -> Result<ProductionCommitReceiptV1, ProductionLedgerError> {
        if request.batch.allocations.len() > MAX_DURABLE_CREDIT_ALLOCATIONS {
            return Err(ProductionLedgerError::Binding(
                "credit batch exceeds durable frame profile",
            ));
        }
        request
            .batch
            .allocations
            .sort_by_key(|allocation| allocation.target_id.clone());
        let payload = production_credit_batch_signing_payload_v1(&request)?;
        let allocator = self.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &request.allocator_evidence,
            &payload,
            now,
        )?;
        if allocator.principal() != &request.batch.allocator {
            return Err(ProductionLedgerError::Binding("allocator principal"));
        }

        let snapshot = self.ledger.snapshot()?;
        let decision = authenticated_decision_for_episode(&snapshot, &request.batch.episode_id)
            .ok_or(ProductionLedgerError::Binding(
                "credit requires authenticated decision",
            ))?;
        if generator.principal() != &decision.generator
            || request.allocator_evidence.objective_digest != decision.objective_digest
        {
            return Err(ProductionLedgerError::Binding("credit objective"));
        }
        verify_signed_role_separation(generator, &allocator, now)?;

        let receipt = finalize_credit_batch(request.batch.clone(), now)?;
        let evidence_digest = Digest32::of_bytes(&request.allocator_evidence.signing_bytes());
        let event = LedgerEvent::ConservedCreditBatch(ConservedCreditBatchRecordV2 {
            record_id: request.record_id,
            batch: request.batch,
            batch_digest: receipt.batch_digest,
            evidence_digest,
        });
        self.commit(request.expected_predecessor, event, evidence_digest)
    }

    pub fn append_revocation(
        &mut self,
        request: ProductionRevocationRequestV1,
        now: u64,
    ) -> Result<ProductionCommitReceiptV1, ProductionLedgerError> {
        if request.reason_digest.is_zero() {
            return Err(ProductionLedgerError::Binding("revocation reason"));
        }
        let payload = production_revocation_signing_payload_v1(&request)?;
        let authority = self.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &request.authority_evidence,
            &payload,
            now,
        )?;
        let evidence_digest = Digest32::of_bytes(&request.authority_evidence.signing_bytes());
        let event = LedgerEvent::Revocation(Revocation {
            record_id: request.record_id,
            target_record_id: request.target_record_id,
            authority_id: authority.principal().principal_id.clone(),
            reason_digest: request.reason_digest,
        });
        self.commit(request.expected_predecessor, event, evidence_digest)
    }

    pub fn freeze_dataset(
        &self,
        request: ProductionDatasetFreezeRequestV1,
        now: u64,
    ) -> Result<DatasetSnapshotReceiptV3, ProductionLedgerError> {
        let current = self.ledger.snapshot()?;
        let current_anchor = anchor_for_snapshot(&current)?;
        if current_anchor != self.witness.current_anchor() {
            return Err(ProductionLedgerError::UnacknowledgedTail);
        }
        let frontier = usize::try_from(request.eligible_frontier)
            .map_err(|_| ProductionLedgerError::Arithmetic)?;
        if frontier == 0 || frontier > current.records().len() {
            return Err(ProductionLedgerError::Binding("eligible frontier"));
        }
        let prefix_records = current.records()[..frontier].to_vec();
        let prefix_head = prefix_records
            .last()
            .map(|record| record.chain_digest)
            .ok_or(ProductionLedgerError::Binding("empty prefix"))?;
        if prefix_head != request.ledger_head_digest {
            return Err(ProductionLedgerError::Binding("ledger head"));
        }
        let signing_payload = production_dataset_freeze_signing_payload_v1(&request)?;
        let producer = self.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &request.evaluator_evidence,
            &signing_payload,
            now,
        )?;
        if request.objective_digest != request.evaluator_evidence.objective_digest {
            return Err(ProductionLedgerError::Binding("dataset objective"));
        }

        let prefix = LedgerSnapshot {
            records: prefix_records,
            head_digest: prefix_head,
        };
        let replayed = LearningLedger::from_snapshot(prefix.clone())?;
        let derived = derive_dataset_membership(&replayed, &prefix, request.objective_digest)?;

        let freeze = DatasetFreezeRequestV1 {
            snapshot_id: request.snapshot_id,
            producer: producer.principal().clone(),
            ledger_head_digest: prefix_head,
            objective_digest: request.objective_digest,
            eligible_frontier: request.eligible_frontier,
            outcome_watermark: request.outcome_watermark,
            correction_cut_digest: derived.correction_cut_digest,
            revocation_cut_digest: derived.revocation_cut_digest,
            inclusion_policy_digest: Digest32::of_bytes(DATASET_POLICY),
            source_record_digests: derived.source_record_digests,
            pending_outcomes: derived.pending_outcomes,
            censored_outcomes: derived.censored_outcomes,
        };
        freeze_dataset_receipt_v3(freeze, now).map_err(Into::into)
    }

    fn commit(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
        evidence_digest: Digest32,
    ) -> Result<ProductionCommitReceiptV1, ProductionLedgerError> {
        let witnessed = self.witness.current_anchor();
        if expected_predecessor != witnessed.chain_digest {
            return Err(ProductionLedgerError::Binding(
                "expected predecessor is not the acknowledged frontier",
            ));
        }
        let ledger = self.ledger.append(expected_predecessor, event)?;
        let expected_sequence = witnessed
            .sequence
            .checked_add(1)
            .ok_or(ProductionLedgerError::Arithmetic)?;
        if ledger.sequence.get() != expected_sequence {
            return Err(ProductionLedgerError::UnacknowledgedTail);
        }
        let anchor = LedgerAnchor {
            sequence: ledger.sequence.get(),
            chain_digest: ledger.chain_digest,
        };
        let witness = self.witness.persist(anchor)?;
        Ok(ProductionCommitReceiptV1 {
            ledger,
            witness,
            evidence_digest,
        })
    }
}

pub fn production_decision_signing_payload_v1(
    request: &ProductionDecisionRequestV1,
    completeness_digest: Digest32,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let mut candidates = request.candidate_ids.clone();
    candidates.sort();
    if candidates.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(ProductionLedgerError::Binding("duplicate candidate"));
    }
    let mut bytes = b"hepta.learning-ledger.production-decision.v1".to_vec();
    push_id(&mut bytes, &request.record_id)?;
    push_id(&mut bytes, &request.episode_id)?;
    bytes.extend_from_slice(request.objective_digest.as_array());
    push_id(&mut bytes, &request.policy_id)?;
    push_len(&mut bytes, candidates.len())?;
    for candidate in &candidates {
        push_id(&mut bytes, candidate)?;
    }
    push_id(&mut bytes, &request.selected_candidate_id)?;
    bytes.extend_from_slice(&request.selected_propensity.raw().to_be_bytes());
    bytes.extend_from_slice(completeness_digest.as_array());
    bytes.extend_from_slice(request.expected_predecessor.as_array());
    Ok(bytes)
}

pub fn production_outcome_signing_payload_v1(
    outcome: &AuthenticatedOutcomeV1,
    expected_predecessor: Digest32,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let mut bytes = b"hepta.learning-ledger.production-outcome.v1".to_vec();
    push_id(&mut bytes, &outcome.record_id)?;
    push_id(&mut bytes, &outcome.outcome_id)?;
    push_id(&mut bytes, &outcome.episode_id)?;
    push_principal(&mut bytes, &outcome.observer)?;
    push_optional_u64(&mut bytes, outcome.observed_at);
    push_optional_fixed(&mut bytes, outcome.value);
    bytes.extend_from_slice(outcome.unit_profile_digest.as_array());
    bytes.extend_from_slice(outcome.support_digest.as_array());
    bytes.extend_from_slice(&outcome.watermark.latest_observable_at.to_be_bytes());
    bytes.extend_from_slice(outcome.watermark.expected_delay_profile_digest.as_array());
    bytes.push(match outcome.watermark.terminality {
        OutcomeTerminalityV1::Pending => 0,
        OutcomeTerminalityV1::Censored => 1,
        OutcomeTerminalityV1::Terminal => 2,
    });
    push_optional_id(&mut bytes, outcome.watermark.censoring_reason.as_ref())?;
    push_optional_id(
        &mut bytes,
        outcome.watermark.correction_predecessor.as_ref(),
    )?;
    push_optional_u64(&mut bytes, outcome.watermark.finalized_at);
    bytes.extend_from_slice(expected_predecessor.as_array());
    Ok(bytes)
}

pub fn production_credit_batch_signing_payload_v1(
    request: &ProductionCreditBatchRequestV1,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let mut batch = request.batch.clone();
    batch
        .allocations
        .sort_by_key(|allocation| allocation.target_id.clone());
    if batch
        .allocations
        .windows(2)
        .any(|pair| pair[0].target_id == pair[1].target_id)
    {
        return Err(ProductionLedgerError::Binding("duplicate credit target"));
    }
    let mut bytes = b"hepta.learning-ledger.production-credit-batch.v1".to_vec();
    push_id(&mut bytes, &request.record_id)?;
    push_id(&mut bytes, &batch.batch_id)?;
    push_id(&mut bytes, &batch.episode_id)?;
    push_id(&mut bytes, &batch.outcome_id)?;
    push_principal(&mut bytes, &batch.allocator)?;
    bytes.extend_from_slice(&batch.terminal_outcome.raw().to_be_bytes());
    push_len(&mut bytes, batch.allocations.len())?;
    for allocation in &batch.allocations {
        push_id(&mut bytes, &allocation.target_id)?;
        bytes.extend_from_slice(&allocation.credit.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&batch.conservation_residual.raw().to_be_bytes());
    bytes.extend_from_slice(batch.support_digest.as_array());
    bytes.push(u8::from(batch.finalized));
    bytes.extend_from_slice(request.expected_predecessor.as_array());
    Ok(bytes)
}

pub fn production_revocation_signing_payload_v1(
    request: &ProductionRevocationRequestV1,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let mut bytes = b"hepta.learning-ledger.production-revocation.v1".to_vec();
    push_id(&mut bytes, &request.record_id)?;
    push_id(&mut bytes, &request.target_record_id)?;
    bytes.extend_from_slice(request.reason_digest.as_array());
    bytes.extend_from_slice(request.expected_predecessor.as_array());
    Ok(bytes)
}

pub fn production_dataset_freeze_signing_payload_v1(
    request: &ProductionDatasetFreezeRequestV1,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let mut bytes = b"hepta.learning-ledger.production-dataset-freeze.v1".to_vec();
    push_id(&mut bytes, &request.snapshot_id)?;
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(&request.eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&request.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(request.ledger_head_digest.as_array());
    Ok(bytes)
}

#[derive(Debug)]
struct DerivedDataset {
    source_record_digests: Vec<Digest32>,
    correction_cut_digest: Digest32,
    revocation_cut_digest: Digest32,
    pending_outcomes: u32,
    censored_outcomes: u32,
}

fn derive_dataset_membership(
    replayed: &LearningLedger,
    prefix: &LedgerSnapshot,
    objective: Digest32,
) -> Result<DerivedDataset, ProductionLedgerError> {
    let mut episode_objective = BTreeMap::<StableId, Digest32>::new();
    for record in prefix.records() {
        match &record.event {
            LedgerEvent::Decision(value) => {
                episode_objective.insert(value.episode_id.clone(), value.objective_digest);
            }
            LedgerEvent::AuthenticatedDecision(value) => {
                episode_objective.insert(value.episode_id.clone(), value.objective_digest);
            }
            _ => {}
        }
    }

    let mut superseded = BTreeSet::<StableId>::new();
    let active = replayed.active_records();
    for record in &active {
        if let LedgerEvent::AuthenticatedOutcome(value) = &record.event
            && episode_objective.get(&value.outcome.episode_id) == Some(&objective)
            && let Some(predecessor) = &value.outcome.watermark.correction_predecessor
        {
            superseded.insert(predecessor.clone());
        }
    }

    let mut sources = Vec::new();
    let mut corrections = Vec::new();
    let mut revocations = Vec::new();
    let mut pending = 0_u32;
    let mut censored = 0_u32;

    for record in &active {
        match &record.event {
            LedgerEvent::Revocation(_) => {
                revocations.push(record.event_digest);
            }
            LedgerEvent::Decision(value) => {
                if value.objective_digest == objective {
                    sources.push(record.event_digest);
                }
            }
            LedgerEvent::AuthenticatedDecision(value) => {
                if value.objective_digest == objective {
                    sources.push(record.event_digest);
                }
            }
            LedgerEvent::Outcome(value) => {
                if episode_objective.get(&value.episode_id) == Some(&objective)
                    && !superseded.contains(&value.outcome_id)
                {
                    if value.finality == OutcomeFinality::Intermediate {
                        pending = pending
                            .checked_add(1)
                            .ok_or(ProductionLedgerError::Arithmetic)?;
                    }
                    sources.push(record.event_digest);
                }
            }
            LedgerEvent::AuthenticatedOutcome(value) => {
                if episode_objective.get(&value.outcome.episode_id) == Some(&objective) {
                    if value.outcome.watermark.correction_predecessor.is_some() {
                        corrections.push(record.event_digest);
                    }
                    if !superseded.contains(&value.outcome.outcome_id) {
                        match value.outcome.watermark.terminality {
                            OutcomeTerminalityV1::Pending => {
                                pending = pending
                                    .checked_add(1)
                                    .ok_or(ProductionLedgerError::Arithmetic)?;
                            }
                            OutcomeTerminalityV1::Censored => {
                                censored = censored
                                    .checked_add(1)
                                    .ok_or(ProductionLedgerError::Arithmetic)?;
                            }
                            OutcomeTerminalityV1::Terminal => {}
                        }
                        sources.push(record.event_digest);
                    }
                }
            }
            LedgerEvent::Credit(value) => {
                if episode_objective.get(&value.episode_id) == Some(&objective)
                    && !superseded.contains(&value.outcome_id)
                {
                    sources.push(record.event_digest);
                }
            }
            LedgerEvent::ConservedCreditBatch(value) => {
                if episode_objective.get(&value.batch.episode_id) == Some(&objective)
                    && !superseded.contains(&value.batch.outcome_id)
                {
                    sources.push(record.event_digest);
                }
            }
        }
    }

    sources.sort_unstable();
    Ok(DerivedDataset {
        source_record_digests: sources,
        correction_cut_digest: cut_digest(
            b"hepta.learning-ledger.correction-cut.v1",
            &corrections,
        )?,
        revocation_cut_digest: cut_digest(
            b"hepta.learning-ledger.revocation-cut.v1",
            &revocations,
        )?,
        pending_outcomes: pending,
        censored_outcomes: censored,
    })
}

fn authenticated_decision_for_episode<'a>(
    snapshot: &'a LedgerSnapshot,
    episode_id: &StableId,
) -> Option<&'a AuthenticatedDecisionRecordV2> {
    snapshot.records().iter().find_map(|record| match &record.event {
        LedgerEvent::AuthenticatedDecision(value) if &value.episode_id == episode_id => Some(value),
        _ => None,
    })
}

fn anchor_for_snapshot(snapshot: &LedgerSnapshot) -> Result<LedgerAnchor, ProductionLedgerError> {
    if snapshot.records().is_empty() {
        if snapshot.head_digest.is_zero() {
            return Ok(LedgerAnchor {
                sequence: 0,
                chain_digest: Digest32::ZERO,
            });
        }
        return Err(ProductionLedgerError::Binding("empty snapshot head"));
    }
    Ok(LedgerAnchor {
        sequence: u64::try_from(snapshot.records().len())
            .map_err(|_| ProductionLedgerError::Arithmetic)?,
        chain_digest: snapshot.head_digest,
    })
}

fn cut_digest(domain: &[u8], digests: &[Digest32]) -> Result<Digest32, ProductionLedgerError> {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(
        &u64::try_from(digests.len())
            .map_err(|_| ProductionLedgerError::Arithmetic)?
            .to_be_bytes(),
    );
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_principal(
    bytes: &mut Vec<u8>,
    principal: &crate::AuthenticatedPrincipalV1,
) -> Result<(), ProductionLedgerError> {
    push_id(bytes, &principal.principal_id)?;
    bytes.extend_from_slice(principal.credential_chain_digest.as_array());
    bytes.extend_from_slice(principal.signing_key_digest.as_array());
    bytes.extend_from_slice(principal.scope_digest.as_array());
    bytes.extend_from_slice(&principal.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&principal.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&principal.expires_at.to_be_bytes());
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ProductionLedgerError> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| ProductionLedgerError::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), ProductionLedgerError> {
    bytes.extend_from_slice(
        &u32::try_from(value)
            .map_err(|_| ProductionLedgerError::Arithmetic)?
            .to_be_bytes(),
    );
    Ok(())
}

fn push_optional_id(
    bytes: &mut Vec<u8>,
    value: Option<&StableId>,
) -> Result<(), ProductionLedgerError> {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value)?;
        }
        None => bytes.push(0),
    }
    Ok(())
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

fn push_optional_fixed(bytes: &mut Vec<u8>, value: Option<codex_hepta_types::FixedQ32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
}

#[cfg(test)]
#[path = "production_tests.rs"]
mod tests;

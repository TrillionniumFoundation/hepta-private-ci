//! Product-facing causal ledger writer.
//!
//! This is the only typed writer intended for product composition. It owns the
//! current signed-evidence verifier, admits only authenticated V2 facts, commits
//! one durable ledger event at a time, and advances an independently retained
//! witness before acknowledging success. Legacy LearningLedger/DurableLedger
//! APIs remain readable compatibility surfaces and qualification fixtures.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::ActivatedLearningTrustV1;
use crate::AppendReceipt;
use crate::AuthenticatedDecisionRecordV2;
use crate::AuthenticatedOutcomeRecordV2;
use crate::AuthenticatedOutcomeTerminality;
use crate::AuthenticatedOutcomeV1;
use crate::AuthenticatedPrincipalV1;
use crate::CandidateSetCompletenessReceiptV1;
use crate::CausalV2Error;
use crate::CreditAllocationBatchRecordV2;
use crate::CreditAllocationBatchV1;
use crate::CreditAllocationRecordV2;
use crate::DatasetFreezeRequestV1;
use crate::DatasetReceiptError;
use crate::DatasetSnapshotReceiptV3;
use crate::DurableLedger;
use crate::DurableLedgerError;
use crate::LearningEvidenceRoleV1;
use crate::LearningEvidenceVerifierV1;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSegmentCheckpoint;
use crate::LedgerSnapshot;
use crate::LedgerWitnessFrontier;
use crate::LedgerWitnessStore;
use crate::OutcomeTerminalityV1;
use crate::SegmentedLedger;
use crate::SignedEvidenceError;
use crate::SignedLearningEvidenceV1;
use crate::UnlearningLineageEventV1;
use crate::VerifiedLearningEvidenceV1;
use crate::finalize_credit_batch;
use crate::freeze_dataset_receipt_v3;
use crate::validate_candidate_set_completeness;

const MAX_PRODUCTION_CANDIDATES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionDecisionV2 {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub run_snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub policy_digest: Digest32,
    pub candidate_ids: Vec<StableId>,
    pub selected_candidate_id: StableId,
    pub selected_propensity: ProbabilityQ32,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnlearningLineageRequestV1 {
    pub record_id: StableId,
    pub lineage_id: StableId,
    pub source_record_id: StableId,
    pub dataset_snapshot_id: StableId,
    pub artifact_id: StableId,
    pub reason_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnlearningLineageReceiptV1 {
    pub lineage_id: StableId,
    pub source_record_id: StableId,
    pub dataset_snapshot_id: StableId,
    pub artifact_id: StableId,
    pub append: AppendReceipt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetFreezePlanV2 {
    pub snapshot_id: StableId,
    pub objective_digest: Digest32,
    pub inclusion_policy_digest: Digest32,
}

enum LedgerBackend {
    Durable(DurableLedger),
    Segmented(SegmentedLedger),
}

impl LedgerBackend {
    fn binding(&self) -> Digest32 {
        match self {
            Self::Durable(value) => value.binding_digest(),
            Self::Segmented(value) => value.binding_digest(),
        }
    }

    fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        match self {
            Self::Durable(value) => value.append(expected_predecessor, event),
            Self::Segmented(value) => value.append(expected_predecessor, event),
        }
    }

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        match self {
            Self::Durable(value) => value.snapshot(),
            Self::Segmented(value) => value.snapshot(),
        }
    }

    fn frontier(&self) -> Result<LedgerWitnessFrontier, DurableLedgerError> {
        match self {
            Self::Durable(value) => {
                let snapshot = value.snapshot()?;
                Ok(frontier_from_snapshot(&snapshot))
            }
            Self::Segmented(value) => {
                let checkpoint = value.checkpoint()?;
                Ok(LedgerWitnessFrontier {
                    anchor: checkpoint.anchor,
                    segment: Some(checkpoint.segment),
                    sealed: checkpoint.sealed,
                })
            }
        }
    }
}

/// Product writer with immutable trust state and a separately durable witness.
/// The backend is consumed at construction, so callers using this API cannot
/// bypass typed admission through the same owned handle.
pub struct LedgerWriter {
    backend: LedgerBackend,
    witness: LedgerWitnessStore,
    trust: ActivatedLearningTrustV1,
}

impl LedgerWriter {
    pub fn from_durable(
        ledger: DurableLedger,
        witness: LedgerWitnessStore,
        trust: ActivatedLearningTrustV1,
    ) -> Result<Self, ProductionLedgerError> {
        Self::new(LedgerBackend::Durable(ledger), witness, trust)
    }

    pub fn from_segmented(
        ledger: SegmentedLedger,
        witness: LedgerWitnessStore,
        trust: ActivatedLearningTrustV1,
    ) -> Result<Self, ProductionLedgerError> {
        Self::new(LedgerBackend::Segmented(ledger), witness, trust)
    }

    fn new(
        backend: LedgerBackend,
        mut witness: LedgerWitnessStore,
        trust: ActivatedLearningTrustV1,
    ) -> Result<Self, ProductionLedgerError> {
        if backend.binding() != witness.binding() {
            return Err(ProductionLedgerError::Binding("ledger/witness binding"));
        }
        let snapshot = backend.snapshot()?;
        let ledger_frontier = backend.frontier()?;
        let witness_frontier = witness.frontier()?;
        if ledger_frontier.anchor.sequence == witness_frontier.anchor.sequence
            && ledger_frontier.anchor.chain_digest == witness_frontier.anchor.chain_digest
            && ledger_frontier != witness_frontier
        {
            witness.advance(witness_frontier, ledger_frontier)?;
        }
        let witness_frontier = witness.frontier()?;
        validate_witness_state(&snapshot, ledger_frontier, witness_frontier)?;
        Ok(Self {
            backend,
            witness,
            trust,
        })
    }

    #[must_use]
    pub fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        self.trust.verifier()
    }

    #[must_use]
    pub fn trust_distribution_digest(&self) -> Digest32 {
        self.trust.distribution_digest()
    }

    #[must_use]
    pub const fn trust_generation(&self) -> u64 {
        self.trust.generation()
    }

    pub fn snapshot(&self) -> Result<LedgerSnapshot, ProductionLedgerError> {
        self.backend.snapshot().map_err(Into::into)
    }

    pub fn witness_frontier(&self) -> Result<LedgerWitnessFrontier, ProductionLedgerError> {
        self.witness.frontier().map_err(Into::into)
    }

    pub fn segmented_checkpoint(
        &self,
    ) -> Result<Option<LedgerSegmentCheckpoint>, ProductionLedgerError> {
        match &self.backend {
            LedgerBackend::Durable(_) => Ok(None),
            LedgerBackend::Segmented(value) => value.checkpoint().map(Some).map_err(Into::into),
        }
    }

    pub fn rotate_segment(
        &mut self,
        next_segment: File,
        expected: LedgerAnchor,
    ) -> Result<LedgerSegmentCheckpoint, ProductionLedgerError> {
        let before = self.witness.frontier()?;
        let LedgerBackend::Segmented(ledger) = &mut self.backend else {
            return Err(ProductionLedgerError::UnsupportedBackend);
        };
        ledger.rotate(next_segment, expected)?;
        let after = self.backend.frontier()?;
        if let Err(witness_error) = self.witness.advance(before, after) {
            return Err(ProductionLedgerError::IndeterminateAfterTopologyChange {
                witness_error,
            });
        }
        self.segmented_checkpoint()?
            .ok_or(ProductionLedgerError::UnsupportedBackend)
    }

    pub fn append_decision(
        &mut self,
        expected_predecessor: Digest32,
        request: ProductionDecisionV2,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        let payload = decision_signing_payload_v2(&request)?;
        let verified = self
            .trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Generator, evidence, &payload, now)?;
        require_role(&verified, LearningEvidenceRoleV1::Generator)?;
        if request.objective_digest != self.trust.verifier().objective_digest()
            || request.completeness.generator_id != verified.principal().principal_id
        {
            return Err(ProductionLedgerError::Binding(
                "decision objective or generator",
            ));
        }
        let completeness_digest = validate_production_completeness(&request)?;
        let principal = verified.principal();
        let event = LedgerEvent::AuthenticatedDecisionV2(AuthenticatedDecisionRecordV2 {
            record_id: request.record_id,
            episode_id: request.episode_id,
            run_snapshot_digest: request.run_snapshot_digest,
            objective_digest: request.objective_digest,
            policy_digest: request.policy_digest,
            generator_id: principal.principal_id.clone(),
            generator_controller_id: verified.controller_id().clone(),
            generator_credential_chain_digest: principal.credential_chain_digest,
            generator_signing_key_digest: principal.signing_key_digest,
            generator_scope_digest: principal.scope_digest,
            generator_authority_epoch: principal.authority_epoch,
            candidate_ids: request.candidate_ids,
            selected_candidate_id: request.selected_candidate_id,
            selected_propensity: request.selected_propensity,
            candidate_completeness_digest: completeness_digest,
            support_digest: request.support_digest,
            authentication_digest: signed_evidence_digest(evidence),
        });
        self.commit(expected_predecessor, event)
    }

    pub fn append_outcome(
        &mut self,
        expected_predecessor: Digest32,
        outcome: AuthenticatedOutcomeV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        let payload = outcome_signing_payload_v2(&outcome);
        let verified = self
            .trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Observer, evidence, &payload, now)?;
        require_role(&verified, LearningEvidenceRoleV1::Observer)?;
        if verified.principal() != &outcome.observer {
            return Err(ProductionLedgerError::Binding("outcome observer"));
        }
        validate_outcome_time(&outcome, now)?;

        let snapshot = self.backend.snapshot()?;
        let decision = find_authenticated_decision(&snapshot, &outcome.episode_id)?;
        if decision.objective_digest != self.trust.verifier().objective_digest() {
            return Err(ProductionLedgerError::Binding("outcome objective"));
        }
        ensure_independent_from_decision(decision, &verified)?;

        let event = LedgerEvent::AuthenticatedOutcomeV2(AuthenticatedOutcomeRecordV2 {
            record_id: outcome.record_id,
            outcome_id: outcome.outcome_id,
            episode_id: outcome.episode_id,
            observer_id: verified.principal().principal_id.clone(),
            observer_controller_id: verified.controller_id().clone(),
            observer_credential_chain_digest: verified.principal().credential_chain_digest,
            observer_signing_key_digest: verified.principal().signing_key_digest,
            observer_scope_digest: verified.principal().scope_digest,
            observer_authority_epoch: verified.principal().authority_epoch,
            observed_at: outcome.observed_at,
            value: outcome.value,
            unit_profile_digest: outcome.unit_profile_digest,
            support_digest: outcome.support_digest,
            latest_observable_at: outcome.watermark.latest_observable_at,
            expected_delay_profile_digest: outcome.watermark.expected_delay_profile_digest,
            terminality: match outcome.watermark.terminality {
                OutcomeTerminalityV1::Pending => AuthenticatedOutcomeTerminality::Pending,
                OutcomeTerminalityV1::Censored => AuthenticatedOutcomeTerminality::Censored,
                OutcomeTerminalityV1::Terminal => AuthenticatedOutcomeTerminality::Terminal,
            },
            censoring_reason: outcome.watermark.censoring_reason,
            correction_predecessor: outcome.watermark.correction_predecessor,
            finalized_at: outcome.watermark.finalized_at,
            authentication_digest: signed_evidence_digest(evidence),
        });
        self.commit(expected_predecessor, event)
    }

    pub fn append_credit_batch(
        &mut self,
        expected_predecessor: Digest32,
        mut batch: CreditAllocationBatchV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        batch
            .allocations
            .sort_by_key(|allocation| allocation.target_id.clone());
        let finalized = finalize_credit_batch(batch.clone(), now)?;
        let payload = credit_batch_signing_payload_v2(&batch, finalized.batch_digest);
        let verified = self.trust.verifier().verify(
            LearningEvidenceRoleV1::CreditAllocator,
            evidence,
            &payload,
            now,
        )?;
        require_role(&verified, LearningEvidenceRoleV1::CreditAllocator)?;
        if verified.principal() != &batch.allocator {
            return Err(ProductionLedgerError::Binding("credit allocator"));
        }
        let event = LedgerEvent::CreditBatchV2(CreditAllocationBatchRecordV2 {
            record_id: batch.batch_id.clone(),
            batch_id: batch.batch_id,
            episode_id: batch.episode_id,
            outcome_id: batch.outcome_id,
            allocator_id: verified.principal().principal_id.clone(),
            allocator_controller_id: verified.controller_id().clone(),
            allocator_credential_chain_digest: verified.principal().credential_chain_digest,
            allocator_signing_key_digest: verified.principal().signing_key_digest,
            allocator_scope_digest: verified.principal().scope_digest,
            allocator_authority_epoch: verified.principal().authority_epoch,
            terminal_outcome: batch.terminal_outcome,
            allocations: batch
                .allocations
                .into_iter()
                .map(|allocation| CreditAllocationRecordV2 {
                    target_artifact_id: allocation.target_id,
                    credit: allocation.credit,
                })
                .collect(),
            conservation_residual: batch.conservation_residual,
            support_digest: batch.support_digest,
            authentication_digest: signed_evidence_digest(evidence),
        });
        self.commit(expected_predecessor, event)
    }

    pub fn append_unlearning(
        &mut self,
        expected_predecessor: Digest32,
        request: UnlearningLineageRequestV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<UnlearningLineageReceiptV1, ProductionLedgerError> {
        let payload = unlearning_signing_payload_v1(&request);
        let verified = self.trust.verifier().verify(
            LearningEvidenceRoleV1::UnlearningAuthority,
            evidence,
            &payload,
            now,
        )?;
        require_role(&verified, LearningEvidenceRoleV1::UnlearningAuthority)?;
        let event = LedgerEvent::UnlearningLineageV1(UnlearningLineageEventV1 {
            record_id: request.record_id,
            lineage_id: request.lineage_id.clone(),
            source_record_id: request.source_record_id.clone(),
            dataset_snapshot_id: request.dataset_snapshot_id.clone(),
            artifact_id: request.artifact_id.clone(),
            authority_id: verified.principal().principal_id.clone(),
            reason_digest: request.reason_digest,
            authentication_digest: signed_evidence_digest(evidence),
        });
        let append = self.commit(expected_predecessor, event)?;
        Ok(UnlearningLineageReceiptV1 {
            lineage_id: request.lineage_id,
            source_record_id: request.source_record_id,
            dataset_snapshot_id: request.dataset_snapshot_id,
            artifact_id: request.artifact_id,
            append,
        })
    }

    /// Build a dataset receipt from the current anchored ledger. Source records,
    /// correction cut, revocation cut, eligible frontier and outcome watermark
    /// are derived from the snapshot and cannot be supplied by the caller.
    pub fn freeze_dataset(
        &self,
        plan: DatasetFreezePlanV2,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<DatasetSnapshotReceiptV3, ProductionLedgerError> {
        let snapshot = self.backend.snapshot()?;
        let payload = dataset_freeze_signing_payload_v2(&snapshot, &plan)?;
        let verified = self.trust.verifier().verify(
            LearningEvidenceRoleV1::Evaluator,
            evidence,
            &payload,
            now,
        )?;
        require_role(&verified, LearningEvidenceRoleV1::Evaluator)?;
        freeze_dataset_from_ledger(&snapshot, plan, verified.principal().clone(), now)
    }

    fn commit(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        let before_snapshot = self.backend.snapshot()?;
        let before_ledger = self.backend.frontier()?;
        let before_witness = self.witness.frontier()?;
        let lag = validate_witness_state(&before_snapshot, before_ledger, before_witness)?;
        if lag == 1 {
            let Some(last) = before_snapshot.records().last() else {
                return Err(ProductionLedgerError::WitnessLag);
            };
            if last.event != event || last.predecessor_chain_digest != expected_predecessor {
                return Err(ProductionLedgerError::WitnessLag);
            }
        }

        let receipt = self.backend.append(expected_predecessor, event)?;
        if receipt.sequence.get() <= before_witness.anchor.sequence {
            return Ok(receipt);
        }

        let after = self.backend.frontier()?;
        let expected_sequence = before_witness
            .anchor
            .sequence
            .checked_add(1)
            .ok_or(ProductionLedgerError::WitnessLag)?;
        if receipt.sequence.get() != expected_sequence
            || after.anchor.sequence != receipt.sequence.get()
            || after.anchor.chain_digest != receipt.chain_digest
        {
            return Err(ProductionLedgerError::WitnessLag);
        }
        if let Err(error) = self.witness.advance(before_witness, after) {
            return Err(ProductionLedgerError::IndeterminateAfterLedgerCommit {
                receipt,
                witness_error: error,
            });
        }
        Ok(receipt)
    }
}

pub fn candidate_ids_digest_v2(candidate_ids: &[StableId]) -> Digest32 {
    let mut ids = candidate_ids.to_vec();
    ids.sort();
    let mut bytes = b"hepta.learning-ledger.candidate-ids.v2".to_vec();
    bytes.extend_from_slice(&(ids.len() as u64).to_be_bytes());
    for id in ids {
        push_id(&mut bytes, &id);
    }
    Digest32::of_bytes(&bytes)
}

pub fn candidate_order_digest_v2(candidate_ids: &[StableId]) -> Digest32 {
    let mut ids = candidate_ids.to_vec();
    ids.sort();
    let mut bytes = b"hepta.learning-ledger.candidate-order.v2".to_vec();
    bytes.extend_from_slice(&(ids.len() as u64).to_be_bytes());
    for id in ids {
        push_id(&mut bytes, &id);
    }
    Digest32::of_bytes(&bytes)
}

pub fn decision_signing_payload_v2(
    request: &ProductionDecisionV2,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let completeness_digest = validate_production_completeness(request)?;
    let mut ids = request.candidate_ids.clone();
    ids.sort();
    let mut bytes = b"hepta.learning-ledger.production-decision.v2".to_vec();
    push_id(&mut bytes, &request.record_id);
    push_id(&mut bytes, &request.episode_id);
    bytes.extend_from_slice(request.run_snapshot_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.policy_digest.as_array());
    bytes.extend_from_slice(completeness_digest.as_array());
    bytes.extend_from_slice(&(ids.len() as u64).to_be_bytes());
    for id in ids {
        push_id(&mut bytes, &id);
    }
    push_id(&mut bytes, &request.selected_candidate_id);
    bytes.extend_from_slice(&request.selected_propensity.raw().to_be_bytes());
    bytes.extend_from_slice(request.support_digest.as_array());
    Ok(bytes)
}

pub fn outcome_signing_payload_v2(outcome: &AuthenticatedOutcomeV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.production-outcome.v2".to_vec();
    push_id(&mut bytes, &outcome.record_id);
    push_id(&mut bytes, &outcome.outcome_id);
    push_id(&mut bytes, &outcome.episode_id);
    push_principal(&mut bytes, &outcome.observer);
    push_optional_u64(&mut bytes, outcome.observed_at);
    match outcome.value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(outcome.unit_profile_digest.as_array());
    bytes.extend_from_slice(outcome.support_digest.as_array());
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

pub fn credit_batch_signing_payload_v2(
    batch: &CreditAllocationBatchV1,
    batch_digest: Digest32,
) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.production-credit-batch.v2".to_vec();
    bytes.extend_from_slice(batch_digest.as_array());
    push_id(&mut bytes, &batch.batch_id);
    push_id(&mut bytes, &batch.episode_id);
    push_id(&mut bytes, &batch.outcome_id);
    push_principal(&mut bytes, &batch.allocator);
    bytes
}

pub fn unlearning_signing_payload_v1(request: &UnlearningLineageRequestV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.unlearning-lineage.v1".to_vec();
    push_id(&mut bytes, &request.record_id);
    push_id(&mut bytes, &request.lineage_id);
    push_id(&mut bytes, &request.source_record_id);
    push_id(&mut bytes, &request.dataset_snapshot_id);
    push_id(&mut bytes, &request.artifact_id);
    bytes.extend_from_slice(request.reason_digest.as_array());
    bytes
}

pub fn dataset_freeze_signing_payload_v2(
    snapshot: &LedgerSnapshot,
    plan: &DatasetFreezePlanV2,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let derived = derive_dataset(snapshot, plan)?;
    let mut bytes = b"hepta.learning-ledger.dataset-freeze-plan.v2".to_vec();
    push_id(&mut bytes, &plan.snapshot_id);
    bytes.extend_from_slice(plan.objective_digest.as_array());
    bytes.extend_from_slice(plan.inclusion_policy_digest.as_array());
    bytes.extend_from_slice(snapshot.head_digest.as_array());
    bytes.extend_from_slice(&derived.eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&derived.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(derived.correction_cut_digest.as_array());
    bytes.extend_from_slice(derived.revocation_cut_digest.as_array());
    bytes.extend_from_slice(&(derived.source_record_digests.len() as u64).to_be_bytes());
    for digest in derived.source_record_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

pub fn freeze_dataset_from_ledger(
    snapshot: &LedgerSnapshot,
    plan: DatasetFreezePlanV2,
    producer: AuthenticatedPrincipalV1,
    now: u64,
) -> Result<DatasetSnapshotReceiptV3, ProductionLedgerError> {
    producer
        .validate(now)
        .map_err(ProductionLedgerError::Causal)?;
    let derived = derive_dataset(snapshot, &plan)?;
    let request = DatasetFreezeRequestV1 {
        snapshot_id: plan.snapshot_id,
        producer,
        ledger_head_digest: snapshot.head_digest,
        objective_digest: plan.objective_digest,
        eligible_frontier: derived.eligible_frontier,
        outcome_watermark: derived.outcome_watermark,
        correction_cut_digest: derived.correction_cut_digest,
        revocation_cut_digest: derived.revocation_cut_digest,
        inclusion_policy_digest: plan.inclusion_policy_digest,
        source_record_digests: derived.source_record_digests,
        pending_outcomes: derived.pending_outcomes,
        censored_outcomes: derived.censored_outcomes,
    };
    freeze_dataset_receipt_v3(request, now).map_err(Into::into)
}

fn validate_production_completeness(
    request: &ProductionDecisionV2,
) -> Result<Digest32, ProductionLedgerError> {
    if request.run_snapshot_digest.is_zero()
        || request.policy_digest.is_zero()
        || request.candidate_ids.is_empty()
        || request.candidate_ids.len() > MAX_PRODUCTION_CANDIDATES
        || request.completeness.candidate_count as usize != request.candidate_ids.len()
        || request.completeness.omitted_count_bound != 0
        || request.completeness.candidates_digest != candidate_ids_digest_v2(&request.candidate_ids)
        || request.completeness.canonical_order_digest
            != candidate_order_digest_v2(&request.candidate_ids)
    {
        return Err(ProductionLedgerError::Binding("candidate completeness"));
    }
    let mut unique = request.candidate_ids.clone();
    unique.sort();
    if unique.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(ProductionLedgerError::Binding("duplicate candidate"));
    }
    validate_candidate_set_completeness(&request.completeness).map_err(Into::into)
}

fn validate_outcome_time(
    outcome: &AuthenticatedOutcomeV1,
    now: u64,
) -> Result<(), ProductionLedgerError> {
    if outcome.watermark.latest_observable_at > now
        || outcome.observed_at.is_some_and(|value| value > now)
        || outcome.watermark.finalized_at.is_some_and(|value| value > now)
    {
        return Err(ProductionLedgerError::Binding("outcome time"));
    }
    Ok(())
}

fn require_role(
    evidence: &VerifiedLearningEvidenceV1,
    expected: LearningEvidenceRoleV1,
) -> Result<(), ProductionLedgerError> {
    if evidence.role() != expected {
        Err(ProductionLedgerError::Role(expected))
    } else {
        Ok(())
    }
}

fn ensure_independent_from_decision(
    decision: &AuthenticatedDecisionRecordV2,
    observer: &VerifiedLearningEvidenceV1,
) -> Result<(), ProductionLedgerError> {
    let principal = observer.principal();
    if decision.generator_id == principal.principal_id
        || decision.generator_controller_id == *observer.controller_id()
        || decision.generator_credential_chain_digest == principal.credential_chain_digest
        || decision.generator_signing_key_digest == principal.signing_key_digest
    {
        return Err(ProductionLedgerError::Binding(
            "generator/observer independence",
        ));
    }
    Ok(())
}

fn find_authenticated_decision<'a>(
    snapshot: &'a LedgerSnapshot,
    episode_id: &StableId,
) -> Result<&'a AuthenticatedDecisionRecordV2, ProductionLedgerError> {
    let ledger = LearningLedger::from_snapshot(snapshot.clone())?;
    let active_record_id = ledger
        .active_records()
        .into_iter()
        .find_map(|record| match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) if &value.episode_id == episode_id => {
                Some(value.record_id.clone())
            }
            _ => None,
        })
        .ok_or(ProductionLedgerError::AuthenticatedDecisionRequired)?;
    snapshot
        .records()
        .iter()
        .find_map(|record| match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value)
                if value.record_id == active_record_id =>
            {
                Some(value)
            }
            _ => None,
        })
        .ok_or(ProductionLedgerError::AuthenticatedDecisionRequired)
}

#[derive(Clone, Debug)]
struct DerivedDataset {
    eligible_frontier: u64,
    outcome_watermark: u64,
    correction_cut_digest: Digest32,
    revocation_cut_digest: Digest32,
    source_record_digests: Vec<Digest32>,
    pending_outcomes: u32,
    censored_outcomes: u32,
}

fn derive_dataset(
    snapshot: &LedgerSnapshot,
    plan: &DatasetFreezePlanV2,
) -> Result<DerivedDataset, ProductionLedgerError> {
    if snapshot.records().is_empty() || snapshot.head_digest.is_zero() {
        return Err(ProductionLedgerError::Binding("empty ledger"));
    }
    let ledger = LearningLedger::from_snapshot(snapshot.clone())?;
    let active = ledger.active_records();
    let mut episodes = BTreeSet::new();
    for record in &active {
        if let LedgerEvent::AuthenticatedDecisionV2(decision) = &record.event
            && decision.objective_digest == plan.objective_digest
        {
            episodes.insert(decision.episode_id.clone());
        }
    }
    if episodes.is_empty() {
        return Err(ProductionLedgerError::AuthenticatedDecisionRequired);
    }

    let mut source_record_digests = Vec::new();
    let mut correction_digests = Vec::new();
    let mut revocation_digests = Vec::new();
    let mut outcome_watermark = 0_u64;
    let mut pending_outcomes = 0_u32;
    let mut censored_outcomes = 0_u32;

    for record in &active {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value)
                if episodes.contains(&value.episode_id) =>
            {
                source_record_digests.push(record.event_digest);
            }
            LedgerEvent::AuthenticatedOutcomeV2(value)
                if episodes.contains(&value.episode_id) =>
            {
                source_record_digests.push(record.event_digest);
                outcome_watermark = outcome_watermark.max(value.latest_observable_at);
                match value.terminality {
                    AuthenticatedOutcomeTerminality::Pending => {
                        pending_outcomes = pending_outcomes
                            .checked_add(1)
                            .ok_or(ProductionLedgerError::Binding("pending count"))?;
                    }
                    AuthenticatedOutcomeTerminality::Censored => {
                        censored_outcomes = censored_outcomes
                            .checked_add(1)
                            .ok_or(ProductionLedgerError::Binding("censored count"))?;
                    }
                    AuthenticatedOutcomeTerminality::Terminal => {}
                }
            }
            LedgerEvent::CreditBatchV2(value) if episodes.contains(&value.episode_id) => {
                source_record_digests.push(record.event_digest);
            }
            _ => {}
        }
    }

    for record in snapshot.records() {
        match &record.event {
            LedgerEvent::AuthenticatedOutcomeV2(value)
                if episodes.contains(&value.episode_id)
                    && value.correction_predecessor.is_some() =>
            {
                correction_digests.push(record.event_digest);
            }
            LedgerEvent::Revocation(_) | LedgerEvent::UnlearningLineageV1(_) => {
                revocation_digests.push(record.event_digest);
            }
            _ => {}
        }
    }
    if outcome_watermark == 0 {
        return Err(ProductionLedgerError::OutcomeWatermarkRequired);
    }
    source_record_digests.sort_unstable();

    let eligible_frontier = snapshot
        .records()
        .last()
        .map(|record| record.sequence.get())
        .ok_or(ProductionLedgerError::Binding("empty ledger"))?;
    Ok(DerivedDataset {
        eligible_frontier,
        outcome_watermark,
        correction_cut_digest: digest_cut(
            b"hepta.learning-ledger.correction-cut.v2",
            &correction_digests,
        ),
        revocation_cut_digest: digest_cut(
            b"hepta.learning-ledger.revocation-cut.v2",
            &revocation_digests,
        ),
        source_record_digests,
        pending_outcomes,
        censored_outcomes,
    })
}

fn digest_cut(domain: &[u8], digests: &[Digest32]) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&(digests.len() as u64).to_be_bytes());
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn signed_evidence_digest(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut bytes = evidence.signing_bytes();
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}

fn frontier_from_snapshot(snapshot: &LedgerSnapshot) -> LedgerWitnessFrontier {
    match snapshot.records().last() {
        Some(record) => LedgerWitnessFrontier {
            anchor: LedgerAnchor {
                sequence: record.sequence.get(),
                chain_digest: record.chain_digest,
            },
            segment: None,
            sealed: false,
        },
        None => LedgerWitnessFrontier::empty(),
    }
}

fn validate_witness_state(
    snapshot: &LedgerSnapshot,
    ledger: LedgerWitnessFrontier,
    witness: LedgerWitnessFrontier,
) -> Result<u64, ProductionLedgerError> {
    if ledger.anchor.sequence < witness.anchor.sequence {
        return Err(ProductionLedgerError::WitnessLag);
    }
    let lag = ledger.anchor.sequence - witness.anchor.sequence;
    if lag > 1 {
        return Err(ProductionLedgerError::WitnessLag);
    }
    if witness.anchor.sequence == 0 {
        if !witness.anchor.chain_digest.is_zero() {
            return Err(ProductionLedgerError::WitnessLag);
        }
    } else {
        let index = usize::try_from(witness.anchor.sequence - 1)
            .map_err(|_| ProductionLedgerError::WitnessLag)?;
        let record = snapshot
            .records()
            .get(index)
            .ok_or(ProductionLedgerError::WitnessLag)?;
        if record.chain_digest != witness.anchor.chain_digest {
            return Err(ProductionLedgerError::WitnessLag);
        }
    }
    if lag == 0 {
        if ledger.anchor.chain_digest != witness.anchor.chain_digest {
            return Err(ProductionLedgerError::WitnessLag);
        }
        match (ledger.segment, witness.segment) {
            (None, None) => {
                if ledger.sealed != witness.sealed {
                    return Err(ProductionLedgerError::WitnessLag);
                }
            }
            (Some(0), None) if ledger.anchor.sequence == 0 && !ledger.sealed && !witness.sealed => {}
            (Some(ledger_segment), Some(witness_segment))
                if ledger_segment == witness_segment && ledger.sealed == witness.sealed => {}
            _ => return Err(ProductionLedgerError::WitnessLag),
        }
    } else if let (Some(witness_segment), Some(ledger_segment)) =
        (witness.segment, ledger.segment)
        && witness_segment != ledger_segment
    {
        return Err(ProductionLedgerError::WitnessLag);
    }
    Ok(lag)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
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

fn push_principal(bytes: &mut Vec<u8>, principal: &AuthenticatedPrincipalV1) {
    push_id(bytes, &principal.principal_id);
    bytes.extend_from_slice(principal.credential_chain_digest.as_array());
    bytes.extend_from_slice(principal.signing_key_digest.as_array());
    bytes.extend_from_slice(principal.scope_digest.as_array());
    bytes.extend_from_slice(&principal.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&principal.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&principal.expires_at.to_be_bytes());
}

#[derive(Debug)]
pub enum ProductionLedgerError {
    Durable(DurableLedgerError),
    Ledger(LedgerError),
    Evidence(SignedEvidenceError),
    Causal(CausalV2Error),
    Dataset(DatasetReceiptError),
    Binding(&'static str),
    Role(LearningEvidenceRoleV1),
    AuthenticatedDecisionRequired,
    OutcomeWatermarkRequired,
    WitnessLag,
    UnsupportedBackend,
    IndeterminateAfterLedgerCommit {
        receipt: AppendReceipt,
        witness_error: DurableLedgerError,
    },
    IndeterminateAfterTopologyChange {
        witness_error: DurableLedgerError,
    },
}

impl fmt::Display for ProductionLedgerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductionLedgerError {}

impl From<DurableLedgerError> for ProductionLedgerError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Durable(value)
    }
}

impl From<LedgerError> for ProductionLedgerError {
    fn from(value: LedgerError) -> Self {
        Self::Ledger(value)
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

impl From<DatasetReceiptError> for ProductionLedgerError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}

#[cfg(test)]
#[path = "production_tests.rs"]
mod tests;

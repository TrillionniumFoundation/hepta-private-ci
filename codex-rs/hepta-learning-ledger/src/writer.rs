//! Product-facing causal ledger writer. This is the strong admission boundary:
//! authenticated decisions, outcome revisions, conserved credit batches and
//! unlearning lineage are committed through one witnessed durable sequence.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::AppendReceipt;
use crate::AuthenticatedDecisionV2;
use crate::AuthenticatedOutcomeV1;
use crate::AuthenticatedOutcomeV2;
use crate::AuthenticatedPrincipalV1;
use crate::CandidateSetCompletenessReceiptV1;
use crate::CreditAllocationBatchV1;
use crate::CreditAllocationBatchV2;
use crate::DatasetFreezeRequestV1;
use crate::DatasetReceiptError;
use crate::DatasetSnapshotReceiptV3;
use crate::DurableCreditAllocationV1;
use crate::DurableLearningJournal;
use crate::DurableLedgerError;
use crate::DurableOutcomeTerminalityV2;
use crate::EpisodeDecision;
use crate::IndependentLedgerWitness;
use crate::LearningEvidenceRoleV1;
use crate::LearningEvidenceVerifierV1;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::OutcomeTerminalityV1;
use crate::SignedEvidenceError;
use crate::SignedLearningEvidenceV1;
use crate::UnlearningLineageEventV1;
use crate::WitnessError;
use crate::finalize_credit_batch;
use crate::freeze_dataset_receipt_v3;
use crate::validate_candidate_set_completeness;

const MAX_DURABLE_CREDIT_ALLOCATIONS: usize = 128;
const CUT_DOMAIN_CORRECTION: &[u8] = b"hepta.learning-ledger.correction-cut.v1";
const CUT_DOMAIN_REVOCATION: &[u8] = b"hepta.learning-ledger.revocation-cut.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnlearningLineageRequestV1 {
    pub record_id: StableId,
    pub lineage_id: StableId,
    pub reason_digest: Digest32,
    pub source_record_ids: Vec<StableId>,
    pub dataset_ids: Vec<StableId>,
    pub artifact_ids: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnlearningLineageReceiptV1 {
    pub lineage_id: StableId,
    pub sequence: u64,
    pub chain_digest: Digest32,
    pub source_count: u32,
    pub dataset_count: u32,
    pub artifact_count: u32,
    pub lineage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetFreezePlanV1 {
    pub request: DatasetFreezeRequestV1,
    pub evidence_payload: Vec<u8>,
}

#[derive(Debug)]
pub enum LedgerWriterError {
    Durable(DurableLedgerError),
    Witness(WitnessError),
    Evidence(SignedEvidenceError),
    Semantic(LedgerError),
    Dataset(DatasetReceiptError),
    Binding(&'static str),
    WitnessAhead,
    WitnessMismatch,
    UnwitnessedTail,
    Poisoned,
}

impl fmt::Display for LedgerWriterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LedgerWriterError {}

impl From<DurableLedgerError> for LedgerWriterError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Durable(value)
    }
}

impl From<WitnessError> for LedgerWriterError {
    fn from(value: WitnessError) -> Self {
        Self::Witness(value)
    }
}

impl From<SignedEvidenceError> for LedgerWriterError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

impl From<LedgerError> for LedgerWriterError {
    fn from(value: LedgerError) -> Self {
        Self::Semantic(value)
    }
}

impl From<DatasetReceiptError> for LedgerWriterError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}

/// Strong product writer. The verifier is an immutable host-owned trust
/// snapshot and the witness is a separately retained durable acknowledgement
/// chain. Only this type should be composed into a production caller.
pub struct LedgerWriter<J: DurableLearningJournal> {
    journal: J,
    verifier: LearningEvidenceVerifierV1,
    witness: IndependentLedgerWitness,
    poisoned: bool,
}

impl<J: DurableLearningJournal> LedgerWriter<J> {
    pub fn new(
        journal: J,
        verifier: LearningEvidenceVerifierV1,
        witness: IndependentLedgerWitness,
    ) -> Result<Self, LedgerWriterError> {
        let writer = Self {
            journal,
            verifier,
            witness,
            poisoned: false,
        };
        writer.validate_witness_prefix()?;
        Ok(writer)
    }

    #[must_use]
    pub fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        &self.verifier
    }

    pub fn witness_anchor(&self) -> Result<LedgerAnchor, LedgerWriterError> {
        Ok(self.witness.anchor()?)
    }

    pub fn append_decision(
        &mut self,
        decision: EpisodeDecision,
        completeness: CandidateSetCompletenessReceiptV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AppendReceipt, LedgerWriterError> {
        let completeness_digest = validate_candidate_set_completeness(&completeness)
            .map_err(|_| LedgerWriterError::Binding("candidate completeness"))?;
        let mut canonical_ids = decision.candidate_ids.clone();
        canonical_ids.sort();
        if decision.objective_digest != self.verifier.objective_digest()
            || completeness.generator_id != decision.policy_id
            || completeness.candidate_count as usize != canonical_ids.len()
            || completeness.omitted_count_bound != 0
            || completeness.candidates_digest
                != crate::ledger::candidate_ids_digest(&canonical_ids)
        {
            return Err(LedgerWriterError::Binding("decision/completeness"));
        }
        let payload = decision_evidence_payload(&decision, completeness_digest);
        let verified = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            evidence,
            &payload,
            now,
        )?;
        if verified.principal().principal_id != decision.policy_id
            || verified.principal().scope_digest != self.verifier.scope_digest()
            || verified.principal().authority_epoch != self.verifier.authority_epoch()
        {
            return Err(LedgerWriterError::Binding("generator identity"));
        }
        let principal = verified.principal();
        let event = AuthenticatedDecisionV2 {
            decision,
            generator_credential_chain_digest: principal.credential_chain_digest,
            generator_signing_key_digest: principal.signing_key_digest,
            generator_controller_id: verified.controller_id().clone(),
            generator_scope_digest: principal.scope_digest,
            generator_authority_epoch: principal.authority_epoch,
            candidate_set_digest: completeness.candidates_digest,
            candidate_count: completeness.candidate_count,
            omitted_count_bound: completeness.omitted_count_bound,
            candidate_receipt_digest: completeness_digest,
            evidence_digest: evidence.evidence_digest(),
        };
        self.commit(LedgerEvent::DecisionV2(event))
    }

    pub fn append_outcome(
        &mut self,
        outcome: AuthenticatedOutcomeV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AppendReceipt, LedgerWriterError> {
        if outcome.watermark.latest_observable_at > now
            || outcome.watermark.finalized_at.is_some_and(|at| at > now)
        {
            return Err(LedgerWriterError::Binding("outcome time frontier"));
        }
        let payload = outcome_evidence_payload(&outcome);
        let verified = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            evidence,
            &payload,
            now,
        )?;
        if verified.principal() != &outcome.observer {
            return Err(LedgerWriterError::Binding("observer identity"));
        }
        let principal = verified.principal();
        let terminality = match outcome.watermark.terminality {
            OutcomeTerminalityV1::Pending => DurableOutcomeTerminalityV2::Pending,
            OutcomeTerminalityV1::Censored => DurableOutcomeTerminalityV2::Censored,
            OutcomeTerminalityV1::Terminal => DurableOutcomeTerminalityV2::Terminal,
        };
        let event = AuthenticatedOutcomeV2 {
            record_id: outcome.record_id,
            outcome_id: outcome.outcome_id,
            episode_id: outcome.episode_id,
            observer_id: principal.principal_id.clone(),
            observer_credential_chain_digest: principal.credential_chain_digest,
            observer_signing_key_digest: principal.signing_key_digest,
            observer_controller_id: verified.controller_id().clone(),
            observer_scope_digest: principal.scope_digest,
            observer_authority_epoch: principal.authority_epoch,
            observed_at: outcome.observed_at,
            value: outcome.value,
            unit_profile_digest: outcome.unit_profile_digest,
            support_digest: outcome.support_digest,
            latest_observable_at: outcome.watermark.latest_observable_at,
            expected_delay_profile_digest: outcome.watermark.expected_delay_profile_digest,
            terminality,
            censoring_reason: outcome.watermark.censoring_reason,
            correction_predecessor: outcome.watermark.correction_predecessor,
            finalized_at: outcome.watermark.finalized_at,
            evidence_digest: evidence.evidence_digest(),
        };
        self.commit(LedgerEvent::OutcomeV2(event))
    }

    pub fn append_credit_batch(
        &mut self,
        record_id: StableId,
        batch: CreditAllocationBatchV1,
        parent_credit_id: Option<StableId>,
        rule_digest: Digest32,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AppendReceipt, LedgerWriterError> {
        if batch.allocations.len() > MAX_DURABLE_CREDIT_ALLOCATIONS || rule_digest.is_zero() {
            return Err(LedgerWriterError::Binding("credit batch bounds"));
        }
        let finalized = finalize_credit_batch(batch.clone(), now)
            .map_err(|_| LedgerWriterError::Binding("credit conservation"))?;
        let payload = finalized.batch_digest.as_array();
        let verified = self.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            evidence,
            payload,
            now,
        )?;
        if verified.principal() != &batch.allocator {
            return Err(LedgerWriterError::Binding("allocator identity"));
        }
        let principal = verified.principal();
        let event = CreditAllocationBatchV2 {
            record_id,
            batch_id: batch.batch_id,
            episode_id: batch.episode_id,
            outcome_id: batch.outcome_id,
            allocator_id: principal.principal_id.clone(),
            allocator_credential_chain_digest: principal.credential_chain_digest,
            allocator_signing_key_digest: principal.signing_key_digest,
            allocator_controller_id: verified.controller_id().clone(),
            allocator_scope_digest: principal.scope_digest,
            allocator_authority_epoch: principal.authority_epoch,
            terminal_outcome: batch.terminal_outcome,
            allocations: batch
                .allocations
                .into_iter()
                .map(|allocation| DurableCreditAllocationV1 {
                    target_id: allocation.target_id,
                    credit: allocation.credit,
                })
                .collect(),
            conservation_residual: batch.conservation_residual,
            parent_credit_id,
            rule_digest,
            support_digest: batch.support_digest,
            evidence_digest: evidence.evidence_digest(),
        };
        self.commit(LedgerEvent::CreditBatchV2(event))
    }

    pub fn append_unlearning(
        &mut self,
        request: UnlearningLineageRequestV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<UnlearningLineageReceiptV1, LedgerWriterError> {
        let payload = unlearning_evidence_payload(&request, self.verifier.scope_digest());
        let verified = self.verifier.verify(
            LearningEvidenceRoleV1::RevocationAuthority,
            evidence,
            &payload,
            now,
        )?;
        let snapshot = self.journal.snapshot()?;
        let predecessor_lineage_id = snapshot.records().iter().rev().find_map(|record| {
            match &record.event {
                LedgerEvent::UnlearningV1(value)
                    if value.scope_digest == self.verifier.scope_digest() =>
                {
                    Some(value.lineage_id.clone())
                }
                _ => None,
            }
        });
        let principal = verified.principal();
        let event = UnlearningLineageEventV1 {
            record_id: request.record_id,
            lineage_id: request.lineage_id.clone(),
            scope_digest: self.verifier.scope_digest(),
            authority_id: principal.principal_id.clone(),
            authority_credential_chain_digest: principal.credential_chain_digest,
            authority_signing_key_digest: principal.signing_key_digest,
            authority_controller_id: verified.controller_id().clone(),
            authority_epoch: principal.authority_epoch,
            reason_digest: request.reason_digest,
            source_record_ids: request.source_record_ids.clone(),
            dataset_ids: request.dataset_ids.clone(),
            artifact_ids: request.artifact_ids.clone(),
            predecessor_lineage_id,
            evidence_digest: evidence.evidence_digest(),
        };
        let lineage_digest = Digest32::of_bytes(&crate::ledger::encode_event(
            &LedgerEvent::UnlearningV1(event.clone()),
        ));
        let receipt = self.commit(LedgerEvent::UnlearningV1(event))?;
        Ok(UnlearningLineageReceiptV1 {
            lineage_id: request.lineage_id,
            sequence: receipt.sequence.get(),
            chain_digest: receipt.chain_digest,
            source_count: request.source_record_ids.len() as u32,
            dataset_count: request.dataset_ids.len() as u32,
            artifact_count: request.artifact_ids.len() as u32,
            lineage_digest,
        })
    }

    pub fn prepare_dataset_freeze(
        &self,
        snapshot_id: StableId,
        producer: AuthenticatedPrincipalV1,
        inclusion_policy_digest: Digest32,
    ) -> Result<DatasetFreezePlanV1, LedgerWriterError> {
        if inclusion_policy_digest.is_zero() {
            return Err(LedgerWriterError::Binding("inclusion policy"));
        }
        let snapshot = self.fully_witnessed_snapshot()?;
        let request = derive_dataset_request(
            snapshot,
            snapshot_id,
            producer,
            self.verifier.objective_digest(),
            inclusion_policy_digest,
        )?;
        let evidence_payload = dataset_freeze_evidence_payload(&request);
        Ok(DatasetFreezePlanV1 {
            request,
            evidence_payload,
        })
    }

    pub fn freeze_dataset_from_ledger(
        &self,
        plan: DatasetFreezePlanV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<DatasetSnapshotReceiptV3, LedgerWriterError> {
        let fresh = self.prepare_dataset_freeze(
            plan.request.snapshot_id.clone(),
            plan.request.producer.clone(),
            plan.request.inclusion_policy_digest,
        )?;
        if fresh != plan {
            return Err(LedgerWriterError::Binding("stale dataset freeze plan"));
        }
        let verified = self.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            evidence,
            &plan.evidence_payload,
            now,
        )?;
        if verified.principal() != &plan.request.producer {
            return Err(LedgerWriterError::Binding("dataset producer identity"));
        }
        Ok(freeze_dataset_receipt_v3(plan.request, now)?)
    }

    fn commit(&mut self, event: LedgerEvent) -> Result<AppendReceipt, LedgerWriterError> {
        if self.poisoned {
            return Err(LedgerWriterError::Poisoned);
        }
        let anchor = self.witness.anchor()?;
        let snapshot = self.journal.snapshot()?;
        validate_anchor_against_snapshot(anchor, &snapshot)?;
        if snapshot.records().len() > anchor.sequence as usize {
            let next = &snapshot.records()[anchor.sequence as usize];
            let event_digest = Digest32::of_bytes(&crate::ledger::encode_event(&event));
            if next.predecessor_chain_digest != anchor.chain_digest
                || next.event_digest != event_digest
            {
                return Err(LedgerWriterError::UnwitnessedTail);
            }
        }
        let receipt = self.journal.append(anchor.chain_digest, event)?;
        if receipt.sequence.get() != anchor.sequence + 1 {
            return Err(LedgerWriterError::WitnessMismatch);
        }
        self.poisoned = true;
        if let Err(error) = self.witness.append_anchor(LedgerAnchor {
            sequence: receipt.sequence.get(),
            chain_digest: receipt.chain_digest,
        }) {
            return Err(LedgerWriterError::Witness(error));
        }
        self.poisoned = false;
        Ok(receipt)
    }

    fn validate_witness_prefix(&self) -> Result<(), LedgerWriterError> {
        let anchor = self.witness.anchor()?;
        let snapshot = self.journal.snapshot()?;
        validate_anchor_against_snapshot(anchor, &snapshot)
    }

    fn fully_witnessed_snapshot(&self) -> Result<LedgerSnapshot, LedgerWriterError> {
        let anchor = self.witness.anchor()?;
        let snapshot = self.journal.snapshot()?;
        validate_anchor_against_snapshot(anchor, &snapshot)?;
        if snapshot.records().len() != anchor.sequence as usize
            || snapshot.head_digest != anchor.chain_digest
        {
            return Err(LedgerWriterError::UnwitnessedTail);
        }
        Ok(snapshot)
    }
}

pub fn decision_evidence_payload(
    decision: &EpisodeDecision,
    candidate_receipt_digest: Digest32,
) -> Vec<u8> {
    let mut normalized = decision.clone();
    normalized.candidate_ids.sort();
    let event_digest = Digest32::of_bytes(&crate::ledger::encode_event(
        &LedgerEvent::Decision(normalized),
    ));
    let mut bytes = b"hepta.learning-ledger.production-decision.v2".to_vec();
    bytes.extend_from_slice(event_digest.as_array());
    bytes.extend_from_slice(candidate_receipt_digest.as_array());
    bytes
}

pub fn outcome_evidence_payload(outcome: &AuthenticatedOutcomeV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.production-outcome.v2".to_vec();
    push_id(&mut bytes, &outcome.record_id);
    push_id(&mut bytes, &outcome.outcome_id);
    push_id(&mut bytes, &outcome.episode_id);
    push_principal(&mut bytes, &outcome.observer);
    push_optional_u64(&mut bytes, outcome.observed_at);
    push_optional_fixed(&mut bytes, outcome.value);
    bytes.extend_from_slice(outcome.unit_profile_digest.as_array());
    bytes.extend_from_slice(outcome.support_digest.as_array());
    bytes.extend_from_slice(&outcome.watermark.latest_observable_at.to_be_bytes());
    bytes.extend_from_slice(
        outcome
            .watermark
            .expected_delay_profile_digest
            .as_array(),
    );
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

pub fn unlearning_evidence_payload(
    request: &UnlearningLineageRequestV1,
    scope_digest: Digest32,
) -> Vec<u8> {
    let mut sources = request.source_record_ids.clone();
    let mut datasets = request.dataset_ids.clone();
    let mut artifacts = request.artifact_ids.clone();
    sources.sort();
    datasets.sort();
    artifacts.sort();
    let mut bytes = b"hepta.learning-ledger.unlearning-lineage.v1".to_vec();
    push_id(&mut bytes, &request.record_id);
    push_id(&mut bytes, &request.lineage_id);
    bytes.extend_from_slice(scope_digest.as_array());
    bytes.extend_from_slice(request.reason_digest.as_array());
    push_ids(&mut bytes, &sources);
    push_ids(&mut bytes, &datasets);
    push_ids(&mut bytes, &artifacts);
    bytes
}

fn validate_anchor_against_snapshot(
    anchor: LedgerAnchor,
    snapshot: &LedgerSnapshot,
) -> Result<(), LedgerWriterError> {
    if anchor.sequence as usize > snapshot.records().len() {
        return Err(LedgerWriterError::WitnessAhead);
    }
    if anchor.sequence == 0 {
        if !anchor.chain_digest.is_zero() {
            return Err(LedgerWriterError::WitnessMismatch);
        }
        return Ok(());
    }
    let record = &snapshot.records()[(anchor.sequence - 1) as usize];
    if record.chain_digest != anchor.chain_digest {
        return Err(LedgerWriterError::WitnessMismatch);
    }
    Ok(())
}

fn derive_dataset_request(
    snapshot: LedgerSnapshot,
    snapshot_id: StableId,
    producer: AuthenticatedPrincipalV1,
    objective_digest: Digest32,
    inclusion_policy_digest: Digest32,
) -> Result<DatasetFreezeRequestV1, LedgerWriterError> {
    if snapshot.records().is_empty() || snapshot.head_digest.is_zero() {
        return Err(LedgerWriterError::Binding("empty ledger"));
    }
    let rebuilt = LearningLedger::from_snapshot(snapshot.clone())?;
    let active_ids = rebuilt
        .active_records()
        .into_iter()
        .map(|record| record.event.record_id().clone())
        .collect::<BTreeSet<_>>();
    let mut source_record_digests = Vec::new();
    let mut correction_digests = Vec::new();
    let mut revocation_digests = Vec::new();
    let mut pending_outcomes = 0_u32;
    let mut censored_outcomes = 0_u32;
    let mut outcome_watermark = 0_u64;

    for record in snapshot.records() {
        match &record.event {
            LedgerEvent::Revocation(_) | LedgerEvent::UnlearningV1(_) => {
                revocation_digests.push(record.event_digest);
            }
            LedgerEvent::OutcomeV2(value) => {
                outcome_watermark = outcome_watermark.max(value.latest_observable_at);
                if value.correction_predecessor.is_some() {
                    correction_digests.push(record.event_digest);
                }
                if active_ids.contains(record.event.record_id()) {
                    source_record_digests.push(record.event_digest);
                    match value.terminality {
                        DurableOutcomeTerminalityV2::Pending => pending_outcomes += 1,
                        DurableOutcomeTerminalityV2::Censored => censored_outcomes += 1,
                        DurableOutcomeTerminalityV2::Terminal => (),
                    }
                }
            }
            _ if active_ids.contains(record.event.record_id()) => {
                source_record_digests.push(record.event_digest);
            }
            _ => (),
        }
    }
    if source_record_digests.is_empty() || outcome_watermark == 0 {
        return Err(LedgerWriterError::Binding(
            "no eligible witnessed dataset frontier",
        ));
    }
    source_record_digests.sort_unstable();
    source_record_digests.dedup();
    let correction_cut_digest = digest_cut(CUT_DOMAIN_CORRECTION, &correction_digests);
    let revocation_cut_digest = digest_cut(CUT_DOMAIN_REVOCATION, &revocation_digests);
    Ok(DatasetFreezeRequestV1 {
        snapshot_id,
        producer,
        ledger_head_digest: snapshot.head_digest,
        objective_digest,
        eligible_frontier: snapshot.records().len() as u64,
        outcome_watermark,
        correction_cut_digest,
        revocation_cut_digest,
        inclusion_policy_digest,
        source_record_digests,
        pending_outcomes,
        censored_outcomes,
    })
}

fn dataset_freeze_evidence_payload(request: &DatasetFreezeRequestV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.dataset-freeze-plan.v1".to_vec();
    push_id(&mut bytes, &request.snapshot_id);
    push_principal(&mut bytes, &request.producer);
    for digest in [
        request.ledger_head_digest,
        request.objective_digest,
        request.correction_cut_digest,
        request.revocation_cut_digest,
        request.inclusion_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&request.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(&(request.source_record_digests.len() as u64).to_be_bytes());
    for digest in &request.source_record_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.pending_outcomes.to_be_bytes());
    bytes.extend_from_slice(&request.censored_outcomes.to_be_bytes());
    bytes
}

fn digest_cut(domain: &[u8], digests: &[Digest32]) -> Digest32 {
    let mut ordered = digests.to_vec();
    ordered.sort_unstable();
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&(ordered.len() as u64).to_be_bytes());
    for digest in ordered {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
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

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    bytes.extend_from_slice(&(values.len() as u32).to_be_bytes());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
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

fn push_optional_fixed(bytes: &mut Vec<u8>, value: Option<FixedQ32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
}

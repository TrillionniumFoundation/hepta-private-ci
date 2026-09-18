use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::AuthenticatedDecisionV2;
use crate::AuthenticatedOutcomeV2;
use crate::CandidateSetCompleteness;
use crate::CreditAllocationBatchV2;
use crate::CreditAssignment;
use crate::DurableCreditAllocationV1;
use crate::DurableOutcomeTerminalityV2;
use crate::EpisodeDecision;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::LedgerSnapshot;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;
use crate::UnlearningLineageEventV1;

const MAX_RECORDS: usize = 1_000_000;
const MAX_CANDIDATES: usize = 128;
const MAX_CREDIT_ALLOCATIONS: usize = 128;
const MAX_LINEAGE_TARGETS: usize = 64;
const EVENT_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";
const CHAIN_DIGEST_DOMAIN: &[u8] = b"hepta.learning-ledger.chain.v1";
const CANDIDATE_IDS_DOMAIN: &[u8] = b"hepta.learning-ledger.candidate-ids.v2";

#[derive(Clone, Debug)]
struct IdentityIndex {
    principal_id: StableId,
    credential_chain_digest: Digest32,
    signing_key_digest: Digest32,
    controller_id: StableId,
    scope_digest: Digest32,
    authority_epoch: u64,
}

#[derive(Clone, Debug)]
struct DecisionIndex {
    record_id: StableId,
    policy_id: StableId,
    identity: Option<IdentityIndex>,
}

#[derive(Clone, Debug)]
struct OutcomeIndex {
    record_id: StableId,
    episode_id: StableId,
    terminal: bool,
    value: Option<FixedQ32>,
    identity: Option<IdentityIndex>,
}

pub(crate) struct PreparedAppend {
    pub(crate) record: LedgerRecord,
    pub(crate) disposition: AppendDisposition,
}

#[derive(Clone, Debug, Default)]
pub struct LearningLedger {
    records: Vec<LedgerRecord>,
    record_digests: BTreeMap<StableId, Digest32>,
    record_kinds: BTreeMap<StableId, u8>,
    decisions: BTreeMap<StableId, DecisionIndex>,
    outcomes: BTreeMap<StableId, OutcomeIndex>,
    outcome_heads: BTreeMap<StableId, StableId>,
    credit_ids: BTreeSet<StableId>,
    credit_keys: BTreeSet<(StableId, StableId, StableId)>,
    lineage_ids: BTreeSet<StableId>,
    lineage_heads: BTreeMap<Digest32, StableId>,
    invalidated_datasets: BTreeSet<StableId>,
    invalidated_artifacts: BTreeSet<StableId>,
    revoked: BTreeSet<StableId>,
}

impl LearningLedger {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn append(&mut self, event: LedgerEvent) -> Result<AppendReceipt, LedgerError> {
        let prepared = self.prepare(event)?;
        self.apply(prepared)
    }

    pub(crate) fn prepare(&self, mut event: LedgerEvent) -> Result<PreparedAppend, LedgerError> {
        normalize_event(&mut event)?;
        let record_id = event.record_id().clone();
        let event_digest = digest_event(&event);
        if let Some(existing_digest) = self.record_digests.get(&record_id) {
            if *existing_digest != event_digest {
                return Err(LedgerError::IdentityConflict(record_id.to_string()));
            }
            let record = self
                .records
                .iter()
                .find(|record| record.event.record_id() == &record_id)
                .ok_or(LedgerError::InternalInvariant)?;
            return Ok(PreparedAppend {
                record: record.clone(),
                disposition: AppendDisposition::IdempotentReplay,
            });
        }
        if self.records.len() >= MAX_RECORDS {
            return Err(LedgerError::RecordLimitExceeded);
        }
        self.validate_event(&event)?;
        let sequence_value = u64::try_from(self.records.len())
            .map_err(|_| LedgerError::SequenceOverflow)?
            .checked_add(1)
            .ok_or(LedgerError::SequenceOverflow)?;
        let sequence =
            LogicalSequence::new(sequence_value).map_err(|_| LedgerError::SequenceOverflow)?;
        let predecessor_chain_digest = self
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        let chain_digest = digest_chain(predecessor_chain_digest, sequence, event_digest);
        Ok(PreparedAppend {
            record: LedgerRecord {
                sequence,
                predecessor_chain_digest,
                event_digest,
                chain_digest,
                event,
            },
            disposition: AppendDisposition::Appended,
        })
    }

    pub(crate) fn apply(&mut self, prepared: PreparedAppend) -> Result<AppendReceipt, LedgerError> {
        let PreparedAppend {
            record,
            disposition,
        } = prepared;
        let result = receipt(&record, disposition);
        if disposition == AppendDisposition::Appended {
            let head = self
                .records
                .last()
                .map_or(Digest32::ZERO, |row| row.chain_digest);
            if record.predecessor_chain_digest != head
                || record.sequence.get() != self.records.len() as u64 + 1
            {
                return Err(LedgerError::InternalInvariant);
            }
            self.index_record(&record);
            self.records.push(record);
        }
        Ok(result)
    }

    #[must_use]
    pub fn records(&self) -> &[LedgerRecord] {
        &self.records
    }

    #[must_use]
    pub fn active_records(&self) -> Vec<&LedgerRecord> {
        self.records
            .iter()
            .filter(|record| self.record_is_active(record))
            .collect()
    }

    #[must_use]
    pub fn dataset_is_invalidated(&self, dataset_id: &StableId) -> bool {
        self.invalidated_datasets.contains(dataset_id)
    }

    #[must_use]
    pub fn artifact_is_invalidated(&self, artifact_id: &StableId) -> bool {
        self.invalidated_artifacts.contains(artifact_id)
    }

    #[must_use]
    pub fn current_lineage_head(&self, scope_digest: Digest32) -> Option<&StableId> {
        self.lineage_heads.get(&scope_digest)
    }

    #[must_use]
    pub fn snapshot(&self) -> LedgerSnapshot {
        LedgerSnapshot {
            records: self.records.clone(),
            head_digest: self
                .records
                .last()
                .map_or(Digest32::ZERO, |record| record.chain_digest),
        }
    }

    pub fn from_snapshot(snapshot: LedgerSnapshot) -> Result<Self, LedgerError> {
        let expected_head = snapshot.head_digest;
        let mut ledger = Self::new();
        for expected in snapshot.records {
            let receipt = ledger.append(expected.event.clone())?;
            let actual = ledger
                .records
                .last()
                .ok_or(LedgerError::InternalInvariant)?;
            if actual != &expected || receipt.disposition != AppendDisposition::Appended {
                return Err(LedgerError::SnapshotRecordMismatch(expected.sequence.get()));
            }
        }
        let actual_head = ledger
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        if actual_head != expected_head {
            return Err(LedgerError::SnapshotHeadMismatch);
        }
        Ok(ledger)
    }

    fn validate_event(&self, event: &LedgerEvent) -> Result<(), LedgerError> {
        validate_support_digests(event)?;
        match event {
            LedgerEvent::Decision(value) => self.validate_decision(value),
            LedgerEvent::Outcome(value) => self.validate_outcome(value),
            LedgerEvent::Credit(value) => self.validate_credit(value),
            LedgerEvent::Revocation(value) => self.validate_revocation(value),
            LedgerEvent::DecisionV2(value) => self.validate_decision_v2(value),
            LedgerEvent::OutcomeV2(value) => self.validate_outcome_v2(value),
            LedgerEvent::CreditBatchV2(value) => self.validate_credit_batch_v2(value),
            LedgerEvent::UnlearningV1(value) => self.validate_unlearning_v1(value),
        }
    }

    fn validate_decision(&self, decision: &EpisodeDecision) -> Result<(), LedgerError> {
        if decision.completeness != CandidateSetCompleteness::Complete {
            return Err(LedgerError::IncompleteCandidateSet);
        }
        if decision.candidate_ids.is_empty() {
            return Err(LedgerError::EmptyCandidateSet);
        }
        if decision.candidate_ids.len() > MAX_CANDIDATES {
            return Err(LedgerError::CandidateLimitExceeded);
        }
        if !decision
            .candidate_ids
            .iter()
            .any(|candidate| candidate.as_str() == "abstain")
        {
            return Err(LedgerError::MissingAbstainCandidate);
        }
        if !decision
            .candidate_ids
            .contains(&decision.selected_candidate_id)
        {
            return Err(LedgerError::SelectedCandidateMissing(
                decision.selected_candidate_id.to_string(),
            ));
        }
        if decision.selected_propensity.raw() == 0 {
            return Err(LedgerError::ZeroSelectedPropensity);
        }
        if self.decisions.contains_key(&decision.episode_id) {
            return Err(LedgerError::EpisodeAlreadyExists(
                decision.episode_id.to_string(),
            ));
        }
        Ok(())
    }

    fn validate_decision_v2(&self, value: &AuthenticatedDecisionV2) -> Result<(), LedgerError> {
        self.validate_decision(&value.decision)?;
        for (label, digest) in [
            ("generator credential chain", value.generator_credential_chain_digest),
            ("generator signing key", value.generator_signing_key_digest),
            ("generator scope", value.generator_scope_digest),
            ("candidate set", value.candidate_set_digest),
            ("candidate receipt", value.candidate_receipt_digest),
            ("generator evidence", value.evidence_digest),
        ] {
            if digest.is_zero() {
                return Err(LedgerError::EmptyDigest(label));
            }
        }
        if value.generator_authority_epoch == 0 {
            return Err(LedgerError::InvalidAuthorityEpoch);
        }
        if value.candidate_count as usize != value.decision.candidate_ids.len()
            || value.omitted_count_bound != 0
            || value.candidate_set_digest != candidate_ids_digest(&value.decision.candidate_ids)
        {
            return Err(LedgerError::IncompleteCandidateSet);
        }
        Ok(())
    }

    fn validate_outcome(&self, outcome: &OutcomeObservation) -> Result<(), LedgerError> {
        if self.outcomes.contains_key(&outcome.outcome_id) {
            return Err(LedgerError::OutcomeAlreadyExists(
                outcome.outcome_id.to_string(),
            ));
        }
        let decision = self
            .decisions
            .get(&outcome.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(outcome.episode_id.to_string()))?;
        if decision.identity.is_some() {
            return Err(LedgerError::WeakV1WriteDenied);
        }
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(outcome.episode_id.to_string()));
        }
        if decision.policy_id == outcome.observer_id {
            return Err(LedgerError::PolicySelfLabelsOutcome);
        }
        Ok(())
    }

    fn validate_outcome_v2(&self, outcome: &AuthenticatedOutcomeV2) -> Result<(), LedgerError> {
        if self.outcomes.contains_key(&outcome.outcome_id) {
            return Err(LedgerError::OutcomeAlreadyExists(
                outcome.outcome_id.to_string(),
            ));
        }
        let decision = self
            .decisions
            .get(&outcome.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(outcome.episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(outcome.episode_id.to_string()));
        }
        let generator = decision.identity.as_ref().ok_or_else(|| {
            LedgerError::EpisodeNotAuthenticated(outcome.episode_id.to_string())
        })?;
        if generator.principal_id == outcome.observer_id {
            return Err(LedgerError::IdentityRoleCollision("principal"));
        }
        if generator.credential_chain_digest == outcome.observer_credential_chain_digest {
            return Err(LedgerError::IdentityRoleCollision("credential chain"));
        }
        if generator.signing_key_digest == outcome.observer_signing_key_digest {
            return Err(LedgerError::IdentityRoleCollision("signing key"));
        }
        if generator.controller_id == outcome.observer_controller_id {
            return Err(LedgerError::IdentityRoleCollision("controller"));
        }
        if generator.scope_digest != outcome.observer_scope_digest {
            return Err(LedgerError::ScopeMismatch);
        }
        if generator.authority_epoch != outcome.observer_authority_epoch {
            return Err(LedgerError::AuthorityEpochMismatch);
        }
        if outcome.observer_authority_epoch == 0 {
            return Err(LedgerError::InvalidAuthorityEpoch);
        }
        validate_outcome_state(outcome)?;
        match &outcome.correction_predecessor {
            Some(predecessor) => {
                let prior = self.outcomes.get(predecessor).ok_or_else(|| {
                    LedgerError::CorrectionPredecessorMissing(predecessor.to_string())
                })?;
                if prior.episode_id != outcome.episode_id {
                    return Err(LedgerError::CorrectionEpisodeMismatch);
                }
                if self.outcome_heads.get(&outcome.episode_id) != Some(predecessor) {
                    return Err(LedgerError::CorrectionNotHead);
                }
                if self.revoked.contains(&prior.record_id) {
                    return Err(LedgerError::OutcomeRevoked(predecessor.to_string()));
                }
            }
            None => {
                if self.outcome_heads.contains_key(&outcome.episode_id) {
                    return Err(LedgerError::CorrectionNotHead);
                }
            }
        }
        Ok(())
    }

    fn validate_credit(&self, credit: &CreditAssignment) -> Result<(), LedgerError> {
        if self.credit_ids.contains(&credit.credit_id) {
            return Err(LedgerError::CreditIdentityAlreadyExists(
                credit.credit_id.to_string(),
            ));
        }
        let decision = self
            .decisions
            .get(&credit.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(credit.episode_id.to_string()))?;
        if decision.identity.is_some() {
            return Err(LedgerError::WeakV1WriteDenied);
        }
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(credit.episode_id.to_string()));
        }
        let outcome = self
            .outcomes
            .get(&credit.outcome_id)
            .ok_or_else(|| LedgerError::OutcomeNotFound(credit.outcome_id.to_string()))?;
        if outcome.identity.is_some() {
            return Err(LedgerError::WeakV1WriteDenied);
        }
        if self.revoked.contains(&outcome.record_id) {
            return Err(LedgerError::OutcomeRevoked(credit.outcome_id.to_string()));
        }
        if outcome.episode_id != credit.episode_id {
            return Err(LedgerError::OutcomeEpisodeMismatch);
        }
        if !outcome.terminal {
            return Err(LedgerError::OutcomeNotTerminal);
        }
        let key = (
            credit.episode_id.clone(),
            credit.outcome_id.clone(),
            credit.target_artifact_id.clone(),
        );
        if self.credit_keys.contains(&key) {
            return Err(LedgerError::CreditAlreadyAssigned);
        }
        Ok(())
    }

    fn validate_credit_batch_v2(&self, batch: &CreditAllocationBatchV2) -> Result<(), LedgerError> {
        if self.credit_ids.contains(&batch.batch_id) {
            return Err(LedgerError::CreditIdentityAlreadyExists(
                batch.batch_id.to_string(),
            ));
        }
        if batch.allocations.is_empty() {
            return Err(LedgerError::CreditBatchEmpty);
        }
        if batch.allocations.len() > MAX_CREDIT_ALLOCATIONS {
            return Err(LedgerError::CreditBatchLimitExceeded);
        }
        let decision = self
            .decisions
            .get(&batch.episode_id)
            .ok_or_else(|| LedgerError::EpisodeNotFound(batch.episode_id.to_string()))?;
        if self.revoked.contains(&decision.record_id) {
            return Err(LedgerError::EpisodeRevoked(batch.episode_id.to_string()));
        }
        let generator = decision.identity.as_ref().ok_or_else(|| {
            LedgerError::EpisodeNotAuthenticated(batch.episode_id.to_string())
        })?;
        let outcome = self
            .outcomes
            .get(&batch.outcome_id)
            .ok_or_else(|| LedgerError::OutcomeNotFound(batch.outcome_id.to_string()))?;
        if self.revoked.contains(&outcome.record_id) {
            return Err(LedgerError::OutcomeRevoked(batch.outcome_id.to_string()));
        }
        if outcome.episode_id != batch.episode_id {
            return Err(LedgerError::OutcomeEpisodeMismatch);
        }
        if !outcome.terminal {
            return Err(LedgerError::OutcomeNotTerminal);
        }
        let observer = outcome.identity.as_ref().ok_or_else(|| {
            LedgerError::OutcomeNotAuthenticated(batch.outcome_id.to_string())
        })?;
        let Some(outcome_value) = outcome.value else {
            return Err(LedgerError::OutcomeNotTerminal);
        };
        if batch.terminal_outcome != outcome_value {
            return Err(LedgerError::CreditOutcomeValueMismatch);
        }
        if batch.allocator_id == generator.principal_id
            || batch.allocator_id == observer.principal_id
        {
            return Err(LedgerError::IdentityRoleCollision("principal"));
        }
        for (label, left, right) in [
            (
                "generator credential chain",
                batch.allocator_credential_chain_digest,
                generator.credential_chain_digest,
            ),
            (
                "generator signing key",
                batch.allocator_signing_key_digest,
                generator.signing_key_digest,
            ),
            (
                "observer credential chain",
                batch.allocator_credential_chain_digest,
                observer.credential_chain_digest,
            ),
            (
                "observer signing key",
                batch.allocator_signing_key_digest,
                observer.signing_key_digest,
            ),
        ] {
            if left == right {
                return Err(LedgerError::IdentityRoleCollision(label));
            }
        }
        if batch.allocator_controller_id == generator.controller_id
            || batch.allocator_controller_id == observer.controller_id
        {
            return Err(LedgerError::IdentityRoleCollision("controller"));
        }
        if batch.allocator_scope_digest != generator.scope_digest
            || batch.allocator_scope_digest != observer.scope_digest
        {
            return Err(LedgerError::ScopeMismatch);
        }
        if batch.allocator_authority_epoch != generator.authority_epoch
            || batch.allocator_authority_epoch != observer.authority_epoch
        {
            return Err(LedgerError::AuthorityEpochMismatch);
        }
        if let Some(parent) = &batch.parent_credit_id
            && !self.credit_ids.contains(parent)
        {
            return Err(LedgerError::CreditParentNotFound(parent.to_string()));
        }
        let mut allocated = 0_i128;
        for allocation in &batch.allocations {
            let key = (
                batch.episode_id.clone(),
                batch.outcome_id.clone(),
                allocation.target_id.clone(),
            );
            if self.credit_keys.contains(&key) {
                return Err(LedgerError::CreditAlreadyAssigned);
            }
            allocated = allocated
                .checked_add(i128::from(allocation.credit.raw()))
                .ok_or(LedgerError::CreditConservation)?;
        }
        let conserved = allocated
            .checked_add(i128::from(batch.conservation_residual.raw()))
            .ok_or(LedgerError::CreditConservation)?;
        if conserved != i128::from(batch.terminal_outcome.raw()) {
            return Err(LedgerError::CreditConservation);
        }
        Ok(())
    }

    fn validate_revocation(&self, revocation: &Revocation) -> Result<(), LedgerError> {
        let Some(kind) = self.record_kinds.get(&revocation.target_record_id) else {
            return Err(LedgerError::TargetNotFound(
                revocation.target_record_id.to_string(),
            ));
        };
        if *kind == event_kind_code(EventKind::Revocation) {
            return Err(LedgerError::RevocationOfRevocation);
        }
        if self.revoked.contains(&revocation.target_record_id) {
            return Err(LedgerError::TargetAlreadyRevoked(
                revocation.target_record_id.to_string(),
            ));
        }
        Ok(())
    }

    fn validate_unlearning_v1(
        &self,
        lineage: &UnlearningLineageEventV1,
    ) -> Result<(), LedgerError> {
        if self.lineage_ids.contains(&lineage.lineage_id) {
            return Err(LedgerError::LineageIdentityAlreadyExists(
                lineage.lineage_id.to_string(),
            ));
        }
        if lineage.source_record_ids.is_empty() {
            return Err(LedgerError::LineageEmptySources);
        }
        if lineage.source_record_ids.len() > MAX_LINEAGE_TARGETS
            || lineage.dataset_ids.len() > MAX_LINEAGE_TARGETS
            || lineage.artifact_ids.len() > MAX_LINEAGE_TARGETS
        {
            return Err(LedgerError::LineageTargetLimitExceeded);
        }
        if lineage.authority_epoch == 0 {
            return Err(LedgerError::InvalidAuthorityEpoch);
        }
        for source in &lineage.source_record_ids {
            if !self.record_kinds.contains_key(source) {
                return Err(LedgerError::TargetNotFound(source.to_string()));
            }
        }
        match (
            self.lineage_heads.get(&lineage.scope_digest),
            &lineage.predecessor_lineage_id,
        ) {
            (None, None) => (),
            (Some(expected), Some(actual)) if expected == actual => (),
            _ => return Err(LedgerError::LineagePredecessorMismatch),
        }
        Ok(())
    }

    fn index_record(&mut self, record: &LedgerRecord) {
        let record_id = record.event.record_id().clone();
        self.record_digests
            .insert(record_id.clone(), record.event_digest);
        self.record_kinds
            .insert(record_id, event_kind(&record.event));
        match &record.event {
            LedgerEvent::Decision(value) => {
                self.decisions.insert(
                    value.episode_id.clone(),
                    DecisionIndex {
                        record_id: value.record_id.clone(),
                        policy_id: value.policy_id.clone(),
                        identity: None,
                    },
                );
            }
            LedgerEvent::DecisionV2(value) => {
                self.decisions.insert(
                    value.decision.episode_id.clone(),
                    DecisionIndex {
                        record_id: value.decision.record_id.clone(),
                        policy_id: value.decision.policy_id.clone(),
                        identity: Some(IdentityIndex {
                            principal_id: value.decision.policy_id.clone(),
                            credential_chain_digest: value.generator_credential_chain_digest,
                            signing_key_digest: value.generator_signing_key_digest,
                            controller_id: value.generator_controller_id.clone(),
                            scope_digest: value.generator_scope_digest,
                            authority_epoch: value.generator_authority_epoch,
                        }),
                    },
                );
            }
            LedgerEvent::Outcome(value) => {
                self.outcomes.insert(
                    value.outcome_id.clone(),
                    OutcomeIndex {
                        record_id: value.record_id.clone(),
                        episode_id: value.episode_id.clone(),
                        terminal: value.finality == OutcomeFinality::Terminal,
                        value: Some(value.value),
                        identity: None,
                    },
                );
                self.outcome_heads
                    .insert(value.episode_id.clone(), value.outcome_id.clone());
            }
            LedgerEvent::OutcomeV2(value) => {
                self.outcomes.insert(
                    value.outcome_id.clone(),
                    OutcomeIndex {
                        record_id: value.record_id.clone(),
                        episode_id: value.episode_id.clone(),
                        terminal: value.terminality == DurableOutcomeTerminalityV2::Terminal,
                        value: value.value,
                        identity: Some(IdentityIndex {
                            principal_id: value.observer_id.clone(),
                            credential_chain_digest: value.observer_credential_chain_digest,
                            signing_key_digest: value.observer_signing_key_digest,
                            controller_id: value.observer_controller_id.clone(),
                            scope_digest: value.observer_scope_digest,
                            authority_epoch: value.observer_authority_epoch,
                        }),
                    },
                );
                self.outcome_heads
                    .insert(value.episode_id.clone(), value.outcome_id.clone());
            }
            LedgerEvent::Credit(value) => {
                self.credit_ids.insert(value.credit_id.clone());
                self.credit_keys.insert((
                    value.episode_id.clone(),
                    value.outcome_id.clone(),
                    value.target_artifact_id.clone(),
                ));
            }
            LedgerEvent::CreditBatchV2(value) => {
                self.credit_ids.insert(value.batch_id.clone());
                for allocation in &value.allocations {
                    self.credit_keys.insert((
                        value.episode_id.clone(),
                        value.outcome_id.clone(),
                        allocation.target_id.clone(),
                    ));
                }
            }
            LedgerEvent::Revocation(value) => {
                self.revoked.insert(value.target_record_id.clone());
            }
            LedgerEvent::UnlearningV1(value) => {
                self.lineage_ids.insert(value.lineage_id.clone());
                self.lineage_heads
                    .insert(value.scope_digest, value.lineage_id.clone());
                self.revoked.extend(value.source_record_ids.iter().cloned());
                self.invalidated_datasets
                    .extend(value.dataset_ids.iter().cloned());
                self.invalidated_artifacts
                    .extend(value.artifact_ids.iter().cloned());
            }
        }
    }

    fn record_is_active(&self, record: &LedgerRecord) -> bool {
        let record_id = record.event.record_id();
        if self.revoked.contains(record_id) {
            return false;
        }
        match &record.event {
            LedgerEvent::Decision(_) | LedgerEvent::DecisionV2(_) => true,
            LedgerEvent::Outcome(outcome) => self
                .decisions
                .get(&outcome.episode_id)
                .is_some_and(|decision| !self.revoked.contains(&decision.record_id)),
            LedgerEvent::OutcomeV2(outcome) => self
                .decisions
                .get(&outcome.episode_id)
                .is_some_and(|decision| !self.revoked.contains(&decision.record_id)),
            LedgerEvent::Credit(credit) => {
                self.credit_ancestors_active(&credit.episode_id, &credit.outcome_id)
            }
            LedgerEvent::CreditBatchV2(credit) => {
                self.credit_ancestors_active(&credit.episode_id, &credit.outcome_id)
            }
            LedgerEvent::Revocation(_) | LedgerEvent::UnlearningV1(_) => true,
        }
    }

    fn credit_ancestors_active(&self, episode_id: &StableId, outcome_id: &StableId) -> bool {
        let decision_active = self
            .decisions
            .get(episode_id)
            .is_some_and(|decision| !self.revoked.contains(&decision.record_id));
        let outcome_active = self
            .outcomes
            .get(outcome_id)
            .is_some_and(|outcome| !self.revoked.contains(&outcome.record_id));
        decision_active && outcome_active
    }
}

fn validate_outcome_state(outcome: &AuthenticatedOutcomeV2) -> Result<(), LedgerError> {
    if outcome.latest_observable_at == 0 {
        return Err(LedgerError::OutcomeStateMismatch);
    }
    match outcome.terminality {
        DurableOutcomeTerminalityV2::Pending => {
            if outcome.observed_at.is_some()
                || outcome.value.is_some()
                || outcome.finalized_at.is_some()
                || outcome.censoring_reason.is_some()
                || outcome.correction_predecessor.is_some()
            {
                return Err(LedgerError::OutcomeStateMismatch);
            }
        }
        DurableOutcomeTerminalityV2::Censored => {
            let Some(finalized_at) = outcome.finalized_at else {
                return Err(LedgerError::OutcomeStateMismatch);
            };
            if outcome.observed_at.is_some()
                || outcome.value.is_some()
                || outcome.censoring_reason.is_none()
                || finalized_at < outcome.latest_observable_at
            {
                return Err(LedgerError::OutcomeStateMismatch);
            }
        }
        DurableOutcomeTerminalityV2::Terminal => {
            let (Some(observed_at), Some(_), Some(finalized_at)) =
                (outcome.observed_at, outcome.value, outcome.finalized_at)
            else {
                return Err(LedgerError::OutcomeStateMismatch);
            };
            if outcome.censoring_reason.is_some()
                || observed_at > outcome.latest_observable_at
                || finalized_at < observed_at
            {
                return Err(LedgerError::OutcomeStateMismatch);
            }
        }
    }
    Ok(())
}

fn validate_support_digests(event: &LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::Decision(value) => validate_decision_digests(value),
        LedgerEvent::DecisionV2(value) => validate_decision_digests(&value.decision),
        LedgerEvent::Outcome(value) => {
            if value.support_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("outcome support"));
            }
            Ok(())
        }
        LedgerEvent::OutcomeV2(value) => {
            for (label, digest) in [
                ("observer credential chain", value.observer_credential_chain_digest),
                ("observer signing key", value.observer_signing_key_digest),
                ("observer scope", value.observer_scope_digest),
                ("outcome unit profile", value.unit_profile_digest),
                ("outcome support", value.support_digest),
                ("expected delay profile", value.expected_delay_profile_digest),
                ("observer evidence", value.evidence_digest),
            ] {
                if digest.is_zero() {
                    return Err(LedgerError::EmptyDigest(label));
                }
            }
            Ok(())
        }
        LedgerEvent::Credit(value) => {
            if value.support_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("credit support"));
            }
            Ok(())
        }
        LedgerEvent::CreditBatchV2(value) => {
            for (label, digest) in [
                ("allocator credential chain", value.allocator_credential_chain_digest),
                ("allocator signing key", value.allocator_signing_key_digest),
                ("allocator scope", value.allocator_scope_digest),
                ("credit rule", value.rule_digest),
                ("credit support", value.support_digest),
                ("allocator evidence", value.evidence_digest),
            ] {
                if digest.is_zero() {
                    return Err(LedgerError::EmptyDigest(label));
                }
            }
            if value.allocator_authority_epoch == 0 {
                return Err(LedgerError::InvalidAuthorityEpoch);
            }
            Ok(())
        }
        LedgerEvent::Revocation(value) => {
            if value.reason_digest.is_zero() {
                return Err(LedgerError::EmptyDigest("revocation reason"));
            }
            Ok(())
        }
        LedgerEvent::UnlearningV1(value) => {
            for (label, digest) in [
                ("unlearning scope", value.scope_digest),
                (
                    "unlearning authority credential chain",
                    value.authority_credential_chain_digest,
                ),
                (
                    "unlearning authority signing key",
                    value.authority_signing_key_digest,
                ),
                ("unlearning reason", value.reason_digest),
                ("unlearning evidence", value.evidence_digest),
            ] {
                if digest.is_zero() {
                    return Err(LedgerError::EmptyDigest(label));
                }
            }
            Ok(())
        }
    }
}

fn validate_decision_digests(value: &EpisodeDecision) -> Result<(), LedgerError> {
    if value.objective_digest.is_zero() {
        return Err(LedgerError::EmptyDigest("objective"));
    }
    if value.support_digest.is_zero() {
        return Err(LedgerError::EmptyDigest("decision support"));
    }
    Ok(())
}

fn normalize_event(event: &mut LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::Decision(decision) => normalize_candidates(decision),
        LedgerEvent::DecisionV2(value) => normalize_candidates(&mut value.decision),
        LedgerEvent::CreditBatchV2(value) => {
            value
                .allocations
                .sort_by(|left, right| left.target_id.cmp(&right.target_id));
            for window in value.allocations.windows(2) {
                if window[0].target_id == window[1].target_id {
                    return Err(LedgerError::DuplicateCreditTarget(
                        window[0].target_id.to_string(),
                    ));
                }
            }
            Ok(())
        }
        LedgerEvent::UnlearningV1(value) => {
            normalize_lineage_ids(&mut value.source_record_ids)?;
            normalize_lineage_ids(&mut value.dataset_ids)?;
            normalize_lineage_ids(&mut value.artifact_ids)?;
            Ok(())
        }
        LedgerEvent::Outcome(_)
        | LedgerEvent::OutcomeV2(_)
        | LedgerEvent::Credit(_)
        | LedgerEvent::Revocation(_) => Ok(()),
    }
}

fn normalize_candidates(decision: &mut EpisodeDecision) -> Result<(), LedgerError> {
    if decision.candidate_ids.len() > MAX_CANDIDATES {
        return Err(LedgerError::CandidateLimitExceeded);
    }
    decision.candidate_ids.sort();
    for window in decision.candidate_ids.windows(2) {
        if window[0] == window[1] {
            return Err(LedgerError::DuplicateCandidate(window[0].to_string()));
        }
    }
    Ok(())
}

fn normalize_lineage_ids(values: &mut [StableId]) -> Result<(), LedgerError> {
    values.sort();
    for window in values.windows(2) {
        if window[0] == window[1] {
            return Err(LedgerError::DuplicateLineageTarget(
                window[0].to_string(),
            ));
        }
    }
    Ok(())
}

fn receipt(record: &LedgerRecord, disposition: AppendDisposition) -> AppendReceipt {
    AppendReceipt {
        disposition,
        sequence: record.sequence,
        event_digest: record.event_digest,
        chain_digest: record.chain_digest,
    }
}

#[derive(Clone, Copy)]
enum EventKind {
    Decision,
    Outcome,
    Credit,
    Revocation,
    DecisionV2,
    OutcomeV2,
    CreditBatchV2,
    UnlearningV1,
}

const fn event_kind_code(kind: EventKind) -> u8 {
    match kind {
        EventKind::Decision => 0,
        EventKind::Outcome => 1,
        EventKind::Credit => 2,
        EventKind::Revocation => 3,
        EventKind::DecisionV2 => 4,
        EventKind::OutcomeV2 => 5,
        EventKind::CreditBatchV2 => 6,
        EventKind::UnlearningV1 => 7,
    }
}

fn event_kind(event: &LedgerEvent) -> u8 {
    let kind = match event {
        LedgerEvent::Decision(_) => EventKind::Decision,
        LedgerEvent::Outcome(_) => EventKind::Outcome,
        LedgerEvent::Credit(_) => EventKind::Credit,
        LedgerEvent::Revocation(_) => EventKind::Revocation,
        LedgerEvent::DecisionV2(_) => EventKind::DecisionV2,
        LedgerEvent::OutcomeV2(_) => EventKind::OutcomeV2,
        LedgerEvent::CreditBatchV2(_) => EventKind::CreditBatchV2,
        LedgerEvent::UnlearningV1(_) => EventKind::UnlearningV1,
    };
    event_kind_code(kind)
}

fn digest_event(event: &LedgerEvent) -> Digest32 {
    Digest32::of_bytes(&encode_event(event))
}

pub(crate) fn candidate_ids_digest(values: &[StableId]) -> Digest32 {
    let mut bytes = CANDIDATE_IDS_DOMAIN.to_vec();
    push_ids(&mut bytes, values);
    Digest32::of_bytes(&bytes)
}

pub(crate) fn encode_event(event: &LedgerEvent) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EVENT_DIGEST_DOMAIN);
    bytes.push(event_kind(event));
    match event {
        LedgerEvent::Decision(value) => push_decision(&mut bytes, value),
        LedgerEvent::Outcome(value) => push_outcome(&mut bytes, value),
        LedgerEvent::Credit(value) => push_credit(&mut bytes, value),
        LedgerEvent::Revocation(value) => push_revocation(&mut bytes, value),
        LedgerEvent::DecisionV2(value) => push_decision_v2(&mut bytes, value),
        LedgerEvent::OutcomeV2(value) => push_outcome_v2(&mut bytes, value),
        LedgerEvent::CreditBatchV2(value) => push_credit_batch_v2(&mut bytes, value),
        LedgerEvent::UnlearningV1(value) => push_unlearning_v1(&mut bytes, value),
    }
    bytes
}

fn digest_chain(
    predecessor: Digest32,
    sequence: LogicalSequence,
    event_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::with_capacity(CHAIN_DIGEST_DOMAIN.len() + 72);
    bytes.extend_from_slice(CHAIN_DIGEST_DOMAIN);
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&sequence.get().to_be_bytes());
    bytes.extend_from_slice(event_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_decision(bytes: &mut Vec<u8>, value: &EpisodeDecision) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.episode_id);
    push_digest(bytes, value.objective_digest);
    push_id(bytes, &value.policy_id);
    push_ids(bytes, &value.candidate_ids);
    push_id(bytes, &value.selected_candidate_id);
    bytes.extend_from_slice(&value.selected_propensity.raw().to_be_bytes());
    bytes.push(value.completeness.tag());
    push_digest(bytes, value.support_digest);
}

fn push_decision_v2(bytes: &mut Vec<u8>, value: &AuthenticatedDecisionV2) {
    push_decision(bytes, &value.decision);
    push_digest(bytes, value.generator_credential_chain_digest);
    push_digest(bytes, value.generator_signing_key_digest);
    push_id(bytes, &value.generator_controller_id);
    push_digest(bytes, value.generator_scope_digest);
    bytes.extend_from_slice(&value.generator_authority_epoch.to_be_bytes());
    push_digest(bytes, value.candidate_set_digest);
    bytes.extend_from_slice(&value.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&value.omitted_count_bound.to_be_bytes());
    push_digest(bytes, value.candidate_receipt_digest);
    push_digest(bytes, value.evidence_digest);
}

fn push_outcome(bytes: &mut Vec<u8>, value: &OutcomeObservation) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.observer_id);
    bytes.extend_from_slice(&value.value.raw().to_be_bytes());
    bytes.push(value.finality.tag());
    push_digest(bytes, value.support_digest);
}

fn push_outcome_v2(bytes: &mut Vec<u8>, value: &AuthenticatedOutcomeV2) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.observer_id);
    push_digest(bytes, value.observer_credential_chain_digest);
    push_digest(bytes, value.observer_signing_key_digest);
    push_id(bytes, &value.observer_controller_id);
    push_digest(bytes, value.observer_scope_digest);
    bytes.extend_from_slice(&value.observer_authority_epoch.to_be_bytes());
    push_optional_u64(bytes, value.observed_at);
    push_optional_fixed(bytes, value.value);
    push_digest(bytes, value.unit_profile_digest);
    push_digest(bytes, value.support_digest);
    bytes.extend_from_slice(&value.latest_observable_at.to_be_bytes());
    push_digest(bytes, value.expected_delay_profile_digest);
    bytes.push(value.terminality.tag());
    push_optional_id(bytes, value.censoring_reason.as_ref());
    push_optional_id(bytes, value.correction_predecessor.as_ref());
    push_optional_u64(bytes, value.finalized_at);
    push_digest(bytes, value.evidence_digest);
}

fn push_credit(bytes: &mut Vec<u8>, value: &CreditAssignment) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.credit_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.target_artifact_id);
    push_id(bytes, &value.allocator_id);
    bytes.extend_from_slice(&value.credit.raw().to_be_bytes());
    push_digest(bytes, value.support_digest);
}

fn push_credit_batch_v2(bytes: &mut Vec<u8>, value: &CreditAllocationBatchV2) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.batch_id);
    push_id(bytes, &value.episode_id);
    push_id(bytes, &value.outcome_id);
    push_id(bytes, &value.allocator_id);
    push_digest(bytes, value.allocator_credential_chain_digest);
    push_digest(bytes, value.allocator_signing_key_digest);
    push_id(bytes, &value.allocator_controller_id);
    push_digest(bytes, value.allocator_scope_digest);
    bytes.extend_from_slice(&value.allocator_authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.terminal_outcome.raw().to_be_bytes());
    push_len(bytes, value.allocations.len());
    for allocation in &value.allocations {
        push_credit_allocation(bytes, allocation);
    }
    bytes.extend_from_slice(&value.conservation_residual.raw().to_be_bytes());
    push_optional_id(bytes, value.parent_credit_id.as_ref());
    push_digest(bytes, value.rule_digest);
    push_digest(bytes, value.support_digest);
    push_digest(bytes, value.evidence_digest);
}

fn push_credit_allocation(bytes: &mut Vec<u8>, value: &DurableCreditAllocationV1) {
    push_id(bytes, &value.target_id);
    bytes.extend_from_slice(&value.credit.raw().to_be_bytes());
}

fn push_revocation(bytes: &mut Vec<u8>, value: &Revocation) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.target_record_id);
    push_id(bytes, &value.authority_id);
    push_digest(bytes, value.reason_digest);
}

fn push_unlearning_v1(bytes: &mut Vec<u8>, value: &UnlearningLineageEventV1) {
    push_id(bytes, &value.record_id);
    push_id(bytes, &value.lineage_id);
    push_digest(bytes, value.scope_digest);
    push_id(bytes, &value.authority_id);
    push_digest(bytes, value.authority_credential_chain_digest);
    push_digest(bytes, value.authority_signing_key_digest);
    push_id(bytes, &value.authority_controller_id);
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    push_digest(bytes, value.reason_digest);
    push_ids(bytes, &value.source_record_ids);
    push_ids(bytes, &value.dataset_ids);
    push_ids(bytes, &value.artifact_ids);
    push_optional_id(bytes, value.predecessor_lineage_id.as_ref());
    push_digest(bytes, value.evidence_digest);
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
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

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    let converted = u32::try_from(value).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&converted.to_be_bytes());
}

#[cfg(test)]
#[path = "ledger_tests.rs"]
mod tests;

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::ControlRuntimeDecisionPublisherV1;
use crate::ControlRuntimePublicationErrorV1;
use crate::ControlRuntimePublicationHeadV1;
use crate::ControlRuntimePublicationKindV1;
use crate::ControlRuntimePublicationReceiptV1;
use crate::ControlRuntimePublicationV1;
use crate::DurablePlannerJournalError;
use crate::DurablePlannerJournalV1;
use crate::ExecutionAttemptErrorV1;
use crate::ExecutionAttemptV1;
use crate::ExecutionTerminalOutcomeV1;
use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::GrantRequestSetV1;
use crate::NduPlanEvaluationV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlannerError;
use crate::PlannerJournalAnchorV1;
use crate::PlannerJournalStoreV1;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::SnapshotRequestV1;
use crate::TrustedClockError;
use crate::TrustedClockV1;
use crate::collect_snapshot;
use crate::finalize_plan;
use crate::prepare_plan;
use crate::request_execution_grants;

const MAX_TRUSTED_PRODUCERS: usize = 64;
const DECISION_BUNDLE_MAGIC: &[u8; 8] = b"HCPDEC01";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedOwnerProducerV1 {
    pub producer_id: StableId,
    pub owner_id: StableId,
    pub key_epoch: u64,
    pub verifying_key: [u8; 32],
    pub valid_after_micros: u64,
    pub valid_before_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOwnerSummaryV1 {
    summary: OwnerSummaryV1,
    producer_id: StableId,
    key_epoch: u64,
    issued_at_micros: u64,
    expires_at_micros: u64,
    summary_digest: Digest32,
    signature: [u8; 64],
}

impl AuthenticatedOwnerSummaryV1 {
    pub fn new(
        summary: OwnerSummaryV1,
        producer_id: StableId,
        key_epoch: u64,
        issued_at_micros: u64,
        expires_at_micros: u64,
        signature: [u8; 64],
    ) -> Result<Self, OwnerPortAuthenticationErrorV1> {
        if key_epoch == 0 || expires_at_micros <= issued_at_micros {
            return Err(OwnerPortAuthenticationErrorV1::InvalidEnvelope);
        }
        let summary_digest = owner_summary_digest_v1(&summary);
        Ok(Self {
            summary,
            producer_id,
            key_epoch,
            issued_at_micros,
            expires_at_micros,
            summary_digest,
            signature,
        })
    }

    #[must_use]
    pub fn summary(&self) -> &OwnerSummaryV1 {
        &self.summary
    }

    #[must_use]
    pub fn producer_id(&self) -> &StableId {
        &self.producer_id
    }

    #[must_use]
    pub const fn key_epoch(&self) -> u64 {
        self.key_epoch
    }

    #[must_use]
    pub const fn issued_at_micros(&self) -> u64 {
        self.issued_at_micros
    }

    #[must_use]
    pub const fn expires_at_micros(&self) -> u64 {
        self.expires_at_micros
    }

    #[must_use]
    pub const fn summary_digest(&self) -> Digest32 {
        self.summary_digest
    }

    #[must_use]
    pub fn signature(&self) -> &[u8; 64] {
        &self.signature
    }

    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        owner_summary_signing_bytes_v1(
            &self.summary,
            &self.producer_id,
            self.key_epoch,
            self.issued_at_micros,
            self.expires_at_micros,
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerPortAdmissionReceiptV1 {
    pub producer_id: StableId,
    pub owner_id: StableId,
    pub key_epoch: u64,
    pub summary_digest: Digest32,
    pub trust_set_digest: Digest32,
    pub admitted_at_micros: u64,
    pub expires_at_micros: u64,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerPortAuthenticationErrorV1 {
    Bounds,
    DuplicateProducer,
    InvalidTrustRecord,
    InvalidEnvelope,
    UnknownProducer,
    OwnerMismatch,
    KeyEpochMismatch,
    NotYetValid,
    Expired,
    InvalidSignature,
}

impl std::fmt::Display for OwnerPortAuthenticationErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for OwnerPortAuthenticationErrorV1 {}

#[derive(Clone, Debug)]
pub struct Ed25519OwnerPortAuthenticatorV1 {
    producers: BTreeMap<StableId, TrustedOwnerProducerV1>,
    trust_set_digest: Digest32,
}

impl Ed25519OwnerPortAuthenticatorV1 {
    pub fn new(
        mut producers: Vec<TrustedOwnerProducerV1>,
    ) -> Result<Self, OwnerPortAuthenticationErrorV1> {
        if producers.is_empty() || producers.len() > MAX_TRUSTED_PRODUCERS {
            return Err(OwnerPortAuthenticationErrorV1::Bounds);
        }
        producers.sort_by(|left, right| left.producer_id.cmp(&right.producer_id));
        let mut by_id = BTreeMap::new();
        for producer in producers {
            if producer.key_epoch == 0
                || producer.valid_before_micros <= producer.valid_after_micros
                || VerifyingKey::from_bytes(&producer.verifying_key).is_err()
            {
                return Err(OwnerPortAuthenticationErrorV1::InvalidTrustRecord);
            }
            if by_id
                .insert(producer.producer_id.clone(), producer)
                .is_some()
            {
                return Err(OwnerPortAuthenticationErrorV1::DuplicateProducer);
            }
        }
        let trust_set_digest = digest_trust_set(by_id.values());
        Ok(Self {
            producers: by_id,
            trust_set_digest,
        })
    }

    #[must_use]
    pub const fn trust_set_digest(&self) -> Digest32 {
        self.trust_set_digest
    }

    pub fn verify(
        &self,
        envelope: &AuthenticatedOwnerSummaryV1,
        now_micros: u64,
    ) -> Result<OwnerPortAdmissionReceiptV1, OwnerPortAuthenticationErrorV1> {
        if envelope.summary_digest != owner_summary_digest_v1(&envelope.summary)
            || envelope.key_epoch == 0
            || envelope.expires_at_micros <= envelope.issued_at_micros
        {
            return Err(OwnerPortAuthenticationErrorV1::InvalidEnvelope);
        }
        let producer = self
            .producers
            .get(&envelope.producer_id)
            .ok_or(OwnerPortAuthenticationErrorV1::UnknownProducer)?;
        if producer.owner_id != envelope.summary.owner_id {
            return Err(OwnerPortAuthenticationErrorV1::OwnerMismatch);
        }
        if producer.key_epoch != envelope.key_epoch {
            return Err(OwnerPortAuthenticationErrorV1::KeyEpochMismatch);
        }
        let valid_after = producer.valid_after_micros.max(envelope.issued_at_micros);
        let valid_before = producer
            .valid_before_micros
            .min(envelope.expires_at_micros)
            .min(envelope.summary.expires_at_micros);
        if now_micros < valid_after {
            return Err(OwnerPortAuthenticationErrorV1::NotYetValid);
        }
        if now_micros >= valid_before {
            return Err(OwnerPortAuthenticationErrorV1::Expired);
        }
        VerifyingKey::from_bytes(&producer.verifying_key)
            .map_err(|_| OwnerPortAuthenticationErrorV1::InvalidTrustRecord)?
            .verify_strict(
                &envelope.signing_bytes(),
                &Signature::from_bytes(&envelope.signature),
            )
            .map_err(|_| OwnerPortAuthenticationErrorV1::InvalidSignature)?;

        let mut receipt = OwnerPortAdmissionReceiptV1 {
            producer_id: envelope.producer_id.clone(),
            owner_id: envelope.summary.owner_id.clone(),
            key_epoch: envelope.key_epoch,
            summary_digest: envelope.summary_digest,
            trust_set_digest: self.trust_set_digest,
            admitted_at_micros: now_micros,
            expires_at_micros: valid_before,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = digest_admission_receipt(&receipt);
        Ok(receipt)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedGlobalStateSnapshotV1 {
    snapshot: GlobalStateSnapshotV1,
    admissions: Vec<OwnerPortAdmissionReceiptV1>,
    publication: ControlRuntimePublicationReceiptV1,
}

impl AuthenticatedGlobalStateSnapshotV1 {
    #[must_use]
    pub fn snapshot(&self) -> &GlobalStateSnapshotV1 {
        &self.snapshot
    }

    #[must_use]
    pub fn admissions(&self) -> &[OwnerPortAdmissionReceiptV1] {
        &self.admissions
    }

    #[must_use]
    pub fn publication(&self) -> &ControlRuntimePublicationReceiptV1 {
        &self.publication
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedExecutionPlanV1 {
    pub receipt: FeasiblePlanReceiptV1,
    pub grant_requests: GrantRequestSetV1,
    pub attempt: ExecutionAttemptV1,
    pub publication: ControlRuntimePublicationReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlRuntimeOwnerErrorV1 {
    InvalidPolicyEpoch,
    PolicyEpochRegression,
    Clock(TrustedClockError),
    Authentication(OwnerPortAuthenticationErrorV1),
    Planner(PlannerError),
    Journal(DurablePlannerJournalError),
    Publication(ControlRuntimePublicationErrorV1),
    Attempt(ExecutionAttemptErrorV1),
    DuplicateAttempt(StableId),
    UnknownAttempt(StableId),
    PublicationJournalMismatch,
    UnpublishedJournalTail,
    CorruptDecisionBundle,
    AttemptHistoryConflict(StableId),
}

impl std::fmt::Display for ControlRuntimeOwnerErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ControlRuntimeOwnerErrorV1 {}

impl From<TrustedClockError> for ControlRuntimeOwnerErrorV1 {
    fn from(error: TrustedClockError) -> Self {
        Self::Clock(error)
    }
}

impl From<OwnerPortAuthenticationErrorV1> for ControlRuntimeOwnerErrorV1 {
    fn from(error: OwnerPortAuthenticationErrorV1) -> Self {
        Self::Authentication(error)
    }
}

impl From<PlannerError> for ControlRuntimeOwnerErrorV1 {
    fn from(error: PlannerError) -> Self {
        Self::Planner(error)
    }
}

impl From<DurablePlannerJournalError> for ControlRuntimeOwnerErrorV1 {
    fn from(error: DurablePlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

impl From<ControlRuntimePublicationErrorV1> for ControlRuntimeOwnerErrorV1 {
    fn from(error: ControlRuntimePublicationErrorV1) -> Self {
        Self::Publication(error)
    }
}

impl From<ExecutionAttemptErrorV1> for ControlRuntimeOwnerErrorV1 {
    fn from(error: ExecutionAttemptErrorV1) -> Self {
        Self::Attempt(error)
    }
}

#[derive(Debug)]
struct PendingPublicationV1 {
    expected: ControlRuntimePublicationHeadV1,
    record: ControlRuntimePublicationV1,
    attempt: Option<ExecutionAttemptV1>,
}

#[derive(Debug)]
pub struct ControlRuntimeOwnerV1<C, S, A, P> {
    owner_id: StableId,
    policy_epoch: u64,
    clock: C,
    journal: DurablePlannerJournalV1<S, A>,
    publisher: P,
    publication_head: ControlRuntimePublicationHeadV1,
    authenticator: Ed25519OwnerPortAuthenticatorV1,
    attempts: BTreeMap<StableId, ExecutionAttemptV1>,
    pending_publication: Option<PendingPublicationV1>,
}

impl<C, S, A, P> ControlRuntimeOwnerV1<C, S, A, P>
where
    C: TrustedClockV1,
    S: PlannerJournalStoreV1,
    A: PlannerJournalAnchorV1,
    P: ControlRuntimeDecisionPublisherV1,
{
    pub fn open(
        owner_id: StableId,
        policy_epoch: u64,
        clock: C,
        journal: DurablePlannerJournalV1<S, A>,
        mut publisher: P,
        authenticator: Ed25519OwnerPortAuthenticatorV1,
    ) -> Result<Self, ControlRuntimeOwnerErrorV1> {
        if policy_epoch == 0 {
            return Err(ControlRuntimeOwnerErrorV1::InvalidPolicyEpoch);
        }
        let records = publisher.load_records(&owner_id)?;
        let mut attempts = BTreeMap::new();
        let mut previous_epoch = 0;
        for record in &records {
            if record.policy_epoch < previous_epoch || record.policy_epoch > policy_epoch {
                return Err(ControlRuntimeOwnerErrorV1::PolicyEpochRegression);
            }
            previous_epoch = record.policy_epoch;
            if !journal.journal().contains_head(record.journal_head) {
                return Err(ControlRuntimeOwnerErrorV1::PublicationJournalMismatch);
            }
            if let Some(attempt) = attempt_from_publication(record)? {
                merge_recovered_attempt(&mut attempts, attempt)?;
            }
        }
        let publication_head = records.last().map_or_else(
            ControlRuntimePublicationHeadV1::empty,
            ControlRuntimePublicationV1::head,
        );
        let published_journal_head = records
            .last()
            .map_or_else(crate::PlannerJournalHeadV1::empty, |record| record.journal_head);
        if published_journal_head != journal.head() {
            return Err(ControlRuntimeOwnerErrorV1::UnpublishedJournalTail);
        }
        Ok(Self {
            owner_id,
            policy_epoch,
            clock,
            journal,
            publisher,
            publication_head,
            authenticator,
            attempts,
            pending_publication: None,
        })
    }

    #[must_use]
    pub fn owner_id(&self) -> &StableId {
        &self.owner_id
    }

    #[must_use]
    pub const fn policy_epoch(&self) -> u64 {
        self.policy_epoch
    }

    #[must_use]
    pub fn journal(&self) -> &crate::PlannerJournalV1 {
        self.journal.journal()
    }

    #[must_use]
    pub fn attempt(&self, attempt_id: &StableId) -> Option<&ExecutionAttemptV1> {
        self.attempts.get(attempt_id)
    }

    #[must_use]
    pub fn attempts(&self) -> &BTreeMap<StableId, ExecutionAttemptV1> {
        &self.attempts
    }

    pub fn collect_authenticated_snapshot(
        &mut self,
        mut request: SnapshotRequestV1,
        envelopes: Vec<AuthenticatedOwnerSummaryV1>,
    ) -> Result<AuthenticatedGlobalStateSnapshotV1, ControlRuntimeOwnerErrorV1> {
        self.flush_pending_publication()?;
        let now = self.clock.now_micros()?;
        request.collected_at_micros = now;
        let mut admissions = Vec::with_capacity(envelopes.len());
        let mut summaries = Vec::with_capacity(envelopes.len());
        let mut admitted_owners = BTreeSet::new();
        for envelope in envelopes {
            let admission = self.authenticator.verify(&envelope, now)?;
            if !admitted_owners.insert(admission.owner_id.clone()) {
                return Err(OwnerPortAuthenticationErrorV1::InvalidEnvelope.into());
            }
            summaries.push(envelope.summary);
            admissions.push(admission);
        }
        let snapshot = collect_snapshot(request, summaries)?;
        self.journal.record_snapshot(&snapshot)?;
        let payload = snapshot_publication_payload(&snapshot, &admissions);
        let publication = self.publish(
            ControlRuntimePublicationKindV1::SnapshotAdmitted,
            payload,
            now,
            None,
        )?;
        Ok(AuthenticatedGlobalStateSnapshotV1 {
            snapshot,
            admissions,
            publication,
        })
    }

    pub fn prepare_plan(
        &mut self,
        snapshot: &AuthenticatedGlobalStateSnapshotV1,
        mut request: PlanningRequestV1,
    ) -> Result<PreparedPlanInputV1, ControlRuntimeOwnerErrorV1> {
        self.flush_pending_publication()?;
        request.now_micros = self.clock.now_micros()?;
        Ok(prepare_plan(snapshot.snapshot(), request)?)
    }

    pub fn finalize_selected_plan(
        &mut self,
        snapshot: &AuthenticatedGlobalStateSnapshotV1,
        prepared: &PreparedPlanInputV1,
        evaluation: &NduPlanEvaluationV1,
        attempt_id: StableId,
        attempt_deadline_micros: u64,
    ) -> Result<SelectedExecutionPlanV1, ControlRuntimeOwnerErrorV1> {
        self.flush_pending_publication()?;
        if self.attempts.contains_key(&attempt_id) {
            return Err(ControlRuntimeOwnerErrorV1::DuplicateAttempt(attempt_id));
        }
        let finalize_now = self.clock.now_micros()?;
        let receipt = finalize_plan(snapshot.snapshot(), prepared, evaluation, finalize_now)?;
        // Re-read the owner-controlled clock after evaluation and immediately
        // before constructing the final authority request projection.
        let final_use_now = self.clock.now_micros()?;
        let grant_requests =
            request_execution_grants(snapshot.snapshot(), prepared, &receipt, final_use_now)?;
        let deadline = attempt_deadline_micros.min(receipt.expires_at_micros());
        let mut attempt =
            ExecutionAttemptV1::new(attempt_id.clone(), receipt.receipt_digest(), final_use_now, deadline)?;
        attempt.record_grant_request(grant_requests.request_set_digest(), final_use_now)?;

        self.journal.record_decision(&receipt)?;
        self.journal.select_plan(
            selection_identity_digest(
                &self.owner_id,
                self.policy_epoch,
                &attempt_id,
                receipt.receipt_digest(),
            ),
            &receipt,
        )?;
        let payload = decision_bundle_payload(&receipt, &grant_requests, &attempt);
        let publication = self.publish(
            ControlRuntimePublicationKindV1::DecisionCommitted,
            payload,
            final_use_now,
            Some(attempt.clone()),
        )?;
        Ok(SelectedExecutionPlanV1 {
            receipt,
            grant_requests,
            attempt,
            publication,
        })
    }

    pub fn record_authorization(
        &mut self,
        attempt_id: &StableId,
        authority_decision_digest: Digest32,
    ) -> Result<ExecutionAttemptV1, ControlRuntimeOwnerErrorV1> {
        self.transition_attempt(attempt_id, |attempt, now| {
            attempt.record_authorization(authority_decision_digest, now)
        })
    }

    pub fn record_dispatch(
        &mut self,
        attempt_id: &StableId,
        dispatch_digest: Digest32,
    ) -> Result<ExecutionAttemptV1, ControlRuntimeOwnerErrorV1> {
        self.transition_attempt(attempt_id, |attempt, now| {
            attempt.record_dispatch(dispatch_digest, now)
        })
    }

    pub fn mark_timeout(
        &mut self,
        attempt_id: &StableId,
        uncertainty_digest: Option<Digest32>,
    ) -> Result<ExecutionAttemptV1, ControlRuntimeOwnerErrorV1> {
        self.transition_attempt(attempt_id, |attempt, now| {
            attempt.mark_timeout(uncertainty_digest, now)
        })
    }

    pub fn mark_indeterminate(
        &mut self,
        attempt_id: &StableId,
        uncertainty_digest: Digest32,
    ) -> Result<ExecutionAttemptV1, ControlRuntimeOwnerErrorV1> {
        self.transition_attempt(attempt_id, |attempt, now| {
            attempt.mark_indeterminate(uncertainty_digest, now)
        })
    }

    pub fn record_terminal_observation(
        &mut self,
        attempt_id: &StableId,
        observation_digest: Digest32,
        outcome: ExecutionTerminalOutcomeV1,
    ) -> Result<ExecutionAttemptV1, ControlRuntimeOwnerErrorV1> {
        self.transition_attempt(attempt_id, |attempt, now| {
            attempt.record_terminal_observation(observation_digest, outcome, now)
        })
    }

    pub fn revoke_attempt(
        &mut self,
        attempt_id: &StableId,
        revocation_identity_digest: Digest32,
        uncertainty_digest: Option<Digest32>,
    ) -> Result<ExecutionAttemptV1, ControlRuntimeOwnerErrorV1> {
        self.flush_pending_publication()?;
        let mut attempt = self
            .attempts
            .get(attempt_id)
            .cloned()
            .ok_or_else(|| ControlRuntimeOwnerErrorV1::UnknownAttempt(attempt_id.clone()))?;
        let now = self.clock.now_micros()?;
        attempt.revoke(uncertainty_digest, now)?;
        self.journal
            .revoke(revocation_identity_digest, attempt.plan_receipt_digest())?;
        let payload = attempt.export_bytes();
        self.publish(
            ControlRuntimePublicationKindV1::PlanRevoked,
            payload,
            now,
            Some(attempt.clone()),
        )?;
        Ok(attempt)
    }

    pub fn flush_pending_publication(
        &mut self,
    ) -> Result<(), ControlRuntimeOwnerErrorV1> {
        let Some(pending) = self.pending_publication.take() else {
            return Ok(());
        };
        match self
            .publisher
            .compare_and_publish(pending.expected, &pending.record)
        {
            Ok(receipt) => {
                self.accept_publication_receipt(&pending.record, &receipt)?;
                if let Some(attempt) = pending.attempt {
                    self.attempts.insert(attempt.attempt_id().clone(), attempt);
                }
                Ok(())
            }
            Err(error) => {
                self.pending_publication = Some(pending);
                Err(error.into())
            }
        }
    }

    #[must_use]
    pub fn has_pending_publication(&self) -> bool {
        self.pending_publication.is_some()
    }

    pub fn into_parts(
        self,
    ) -> (
        C,
        DurablePlannerJournalV1<S, A>,
        P,
        Ed25519OwnerPortAuthenticatorV1,
    ) {
        (self.clock, self.journal, self.publisher, self.authenticator)
    }

    fn transition_attempt<F>(
        &mut self,
        attempt_id: &StableId,
        transition: F,
    ) -> Result<ExecutionAttemptV1, ControlRuntimeOwnerErrorV1>
    where
        F: FnOnce(&mut ExecutionAttemptV1, u64) -> Result<(), ExecutionAttemptErrorV1>,
    {
        self.flush_pending_publication()?;
        let mut attempt = self
            .attempts
            .get(attempt_id)
            .cloned()
            .ok_or_else(|| ControlRuntimeOwnerErrorV1::UnknownAttempt(attempt_id.clone()))?;
        let now = self.clock.now_micros()?;
        transition(&mut attempt, now)?;
        self.publish(
            ControlRuntimePublicationKindV1::AttemptTransition,
            attempt.export_bytes(),
            now,
            Some(attempt.clone()),
        )?;
        Ok(attempt)
    }

    fn publish(
        &mut self,
        kind: ControlRuntimePublicationKindV1,
        payload: Vec<u8>,
        occurred_at_micros: u64,
        attempt: Option<ExecutionAttemptV1>,
    ) -> Result<ControlRuntimePublicationReceiptV1, ControlRuntimeOwnerErrorV1> {
        let expected = self.publication_head;
        let record = ControlRuntimePublicationV1::new(
            self.owner_id.clone(),
            expected,
            self.policy_epoch,
            kind,
            Digest32::of_bytes(&payload),
            payload,
            self.journal.head(),
            occurred_at_micros,
        )?;
        match self.publisher.compare_and_publish(expected, &record) {
            Ok(receipt) => {
                self.accept_publication_receipt(&record, &receipt)?;
                if let Some(attempt) = attempt {
                    self.attempts.insert(attempt.attempt_id().clone(), attempt);
                }
                Ok(receipt)
            }
            Err(error) => {
                self.pending_publication = Some(PendingPublicationV1 {
                    expected,
                    record,
                    attempt,
                });
                Err(error.into())
            }
        }
    }

    fn accept_publication_receipt(
        &mut self,
        record: &ControlRuntimePublicationV1,
        receipt: &ControlRuntimePublicationReceiptV1,
    ) -> Result<(), ControlRuntimeOwnerErrorV1> {
        if receipt.committed_head != record.head() || receipt.durable_log_digest.is_zero() {
            return Err(ControlRuntimePublicationErrorV1::CorruptRecord.into());
        }
        self.publication_head = receipt.committed_head;
        Ok(())
    }
}

#[must_use]
pub fn owner_summary_digest_v1(summary: &OwnerSummaryV1) -> Digest32 {
    let mut bytes = b"hepta.control.owner-summary.v1".to_vec();
    push_text(&mut bytes, summary.owner_id.as_str());
    bytes.extend_from_slice(&summary.revision.get().to_be_bytes());
    bytes.extend_from_slice(summary.objective_digest.as_array());
    bytes.extend_from_slice(&summary.body_generation.get().to_be_bytes());
    bytes.extend_from_slice(summary.configuration_digest.as_array());
    bytes.extend_from_slice(&summary.observed_at_micros.to_be_bytes());
    bytes.extend_from_slice(&summary.expires_at_micros.to_be_bytes());
    bytes.push(match summary.readiness {
        OwnerReadinessV1::Ready => 0,
        OwnerReadinessV1::Degraded => 1,
        OwnerReadinessV1::Unavailable => 2,
    });
    bytes.extend_from_slice(summary.source_frontier_digest.as_array());
    bytes.extend_from_slice(summary.support_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[must_use]
pub fn owner_summary_signing_bytes_v1(
    summary: &OwnerSummaryV1,
    producer_id: &StableId,
    key_epoch: u64,
    issued_at_micros: u64,
    expires_at_micros: u64,
) -> Vec<u8> {
    let mut bytes = b"hepta.control.authenticated-owner-summary.v1".to_vec();
    bytes.extend_from_slice(owner_summary_digest_v1(summary).as_array());
    push_text(&mut bytes, producer_id.as_str());
    bytes.extend_from_slice(&key_epoch.to_be_bytes());
    bytes.extend_from_slice(&issued_at_micros.to_be_bytes());
    bytes.extend_from_slice(&expires_at_micros.to_be_bytes());
    bytes
}

fn digest_trust_set<'a>(
    producers: impl Iterator<Item = &'a TrustedOwnerProducerV1>,
) -> Digest32 {
    let mut bytes = b"hepta.control.owner-port-trust-set.v1".to_vec();
    for producer in producers {
        push_text(&mut bytes, producer.producer_id.as_str());
        push_text(&mut bytes, producer.owner_id.as_str());
        bytes.extend_from_slice(&producer.key_epoch.to_be_bytes());
        bytes.extend_from_slice(&producer.verifying_key);
        bytes.extend_from_slice(&producer.valid_after_micros.to_be_bytes());
        bytes.extend_from_slice(&producer.valid_before_micros.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_admission_receipt(receipt: &OwnerPortAdmissionReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control.owner-port-admission.v1".to_vec();
    push_text(&mut bytes, receipt.producer_id.as_str());
    push_text(&mut bytes, receipt.owner_id.as_str());
    bytes.extend_from_slice(&receipt.key_epoch.to_be_bytes());
    bytes.extend_from_slice(receipt.summary_digest.as_array());
    bytes.extend_from_slice(receipt.trust_set_digest.as_array());
    bytes.extend_from_slice(&receipt.admitted_at_micros.to_be_bytes());
    bytes.extend_from_slice(&receipt.expires_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn snapshot_publication_payload(
    snapshot: &GlobalStateSnapshotV1,
    admissions: &[OwnerPortAdmissionReceiptV1],
) -> Vec<u8> {
    let mut bytes = b"hepta.control.snapshot-publication.v1".to_vec();
    bytes.extend_from_slice(snapshot.snapshot_digest().as_array());
    bytes.extend_from_slice(&(admissions.len() as u32).to_be_bytes());
    for admission in admissions {
        bytes.extend_from_slice(admission.receipt_digest.as_array());
    }
    bytes
}

fn selection_identity_digest(
    owner_id: &StableId,
    policy_epoch: u64,
    attempt_id: &StableId,
    receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.control.selected-plan.v1".to_vec();
    push_text(&mut bytes, owner_id.as_str());
    bytes.extend_from_slice(&policy_epoch.to_be_bytes());
    push_text(&mut bytes, attempt_id.as_str());
    bytes.extend_from_slice(receipt_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn decision_bundle_payload(
    receipt: &FeasiblePlanReceiptV1,
    requests: &GrantRequestSetV1,
    attempt: &ExecutionAttemptV1,
) -> Vec<u8> {
    let attempt_bytes = attempt.export_bytes();
    let mut bytes = Vec::with_capacity(8 + 32 + 32 + 4 + attempt_bytes.len());
    bytes.extend_from_slice(DECISION_BUNDLE_MAGIC);
    bytes.extend_from_slice(receipt.receipt_digest().as_array());
    bytes.extend_from_slice(requests.request_set_digest().as_array());
    bytes.extend_from_slice(&(attempt_bytes.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&attempt_bytes);
    bytes
}

fn attempt_from_publication(
    record: &ControlRuntimePublicationV1,
) -> Result<Option<ExecutionAttemptV1>, ControlRuntimeOwnerErrorV1> {
    match record.kind {
        ControlRuntimePublicationKindV1::DecisionCommitted => {
            if record.payload.len() < 8 + 32 + 32 + 4
                || &record.payload[..8] != DECISION_BUNDLE_MAGIC
            {
                return Err(ControlRuntimeOwnerErrorV1::CorruptDecisionBundle);
            }
            let attempt_len = usize::try_from(u32::from_be_bytes(
                record.payload[72..76]
                    .try_into()
                    .map_err(|_| ControlRuntimeOwnerErrorV1::CorruptDecisionBundle)?,
            ))
            .map_err(|_| ControlRuntimeOwnerErrorV1::CorruptDecisionBundle)?;
            let end = 76_usize
                .checked_add(attempt_len)
                .ok_or(ControlRuntimeOwnerErrorV1::CorruptDecisionBundle)?;
            if end != record.payload.len() {
                return Err(ControlRuntimeOwnerErrorV1::CorruptDecisionBundle);
            }
            Ok(Some(ExecutionAttemptV1::reopen(&record.payload[76..end])?))
        }
        ControlRuntimePublicationKindV1::AttemptTransition
        | ControlRuntimePublicationKindV1::PlanRevoked => {
            Ok(Some(ExecutionAttemptV1::reopen(&record.payload)?))
        }
        ControlRuntimePublicationKindV1::SnapshotAdmitted
        | ControlRuntimePublicationKindV1::GrantRequestsCommitted => Ok(None),
    }
}

fn merge_recovered_attempt(
    attempts: &mut BTreeMap<StableId, ExecutionAttemptV1>,
    attempt: ExecutionAttemptV1,
) -> Result<(), ControlRuntimeOwnerErrorV1> {
    if let Some(previous) = attempts.get(attempt.attempt_id()) {
        if attempt.transition_sequence() <= previous.transition_sequence()
            || attempt.plan_receipt_digest() != previous.plan_receipt_digest()
        {
            return Err(ControlRuntimeOwnerErrorV1::AttemptHistoryConflict(
                attempt.attempt_id().clone(),
            ));
        }
    }
    attempts.insert(attempt.attempt_id().clone(), attempt);
    Ok(())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::Revision;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;
    use crate::InMemoryControlRuntimeDecisionPublisherV1;
    use crate::InMemoryPlannerJournalAnchorV1;
    use crate::InMemoryPlannerJournalStoreV1;
    use crate::ManualTrustedClockV1;
    use crate::NduPlanEvaluationInputV1;
    use crate::PlanCandidateV1;
    use crate::PlannerAxisValueV1;
    use crate::PlanningEvaluationDispositionV1;
    use crate::ResourceReservationV1;
    use crate::bind_ndu_plan_evaluation_v1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn summary() -> OwnerSummaryV1 {
        OwnerSummaryV1 {
            owner_id: id("planner"),
            revision: Revision::new(1).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: Generation::new(1).expect("generation"),
            configuration_digest: digest("configuration"),
            observed_at_micros: 90,
            expires_at_micros: 500,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }
    }

    fn signed_summary(signing: &SigningKey) -> AuthenticatedOwnerSummaryV1 {
        let summary = summary();
        let producer = id("planner-producer");
        let bytes = owner_summary_signing_bytes_v1(&summary, &producer, 1, 80, 500);
        AuthenticatedOwnerSummaryV1::new(
            summary,
            producer,
            1,
            80,
            500,
            signing.sign(&bytes).to_bytes(),
        )
        .expect("envelope")
    }

    fn snapshot_request() -> SnapshotRequestV1 {
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: Generation::new(1).expect("generation"),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 0,
            maximum_owner_age_micros: 50,
            expires_at_micros: 500,
            required_owner_ids: vec![id("planner")],
        }
    }

    fn candidate(name: &str) -> PlanCandidateV1 {
        PlanCandidateV1 {
            candidate_id: id(name),
            operation_id: id(&format!("operation-{name}")),
            plan_digest: digest(&format!("plan:{name}")),
            required_owner_ids: vec![id("planner")],
            final_payload_digests: (name != "abstain")
                .then(|| digest(&format!("payload:{name}")))
                .into_iter()
                .collect(),
            resource_costs: vec![PlannerAxisValueV1 {
                axis: id("compute"),
                value: if name == "abstain" {
                    FixedQ32::ZERO
                } else {
                    FixedQ32::from_raw(1_i64 << 32)
                },
            }],
        }
    }

    fn planning_request() -> PlanningRequestV1 {
        PlanningRequestV1 {
            plan_id: id("plan-run"),
            now_micros: 0,
            deadline_micros: 400,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("resource-profile"),
            candidates: vec![candidate("abstain"), candidate("work")],
            resource_reservations: vec![ResourceReservationV1 {
                axis: id("compute"),
                endowment: FixedQ32::from_raw(10_i64 << 32),
                essential_floor: FixedQ32::ZERO,
            }],
        }
    }

    fn authenticator(signing: &SigningKey) -> Ed25519OwnerPortAuthenticatorV1 {
        Ed25519OwnerPortAuthenticatorV1::new(vec![TrustedOwnerProducerV1 {
            producer_id: id("planner-producer"),
            owner_id: id("planner"),
            key_epoch: 1,
            verifying_key: signing.verifying_key().to_bytes(),
            valid_after_micros: 1,
            valid_before_micros: 500,
        }])
        .expect("authenticator")
    }

    #[test]
    fn unique_owner_authenticates_persists_publishes_and_recovers_attempts() {
        let signing = SigningKey::from_bytes(&[7_u8; 32]);
        let journal = DurablePlannerJournalV1::open(
            InMemoryPlannerJournalStoreV1::default(),
            InMemoryPlannerJournalAnchorV1::default(),
        )
        .expect("journal");
        let mut owner = ControlRuntimeOwnerV1::open(
            id("control.runtime"),
            1,
            ManualTrustedClockV1::new(100),
            journal,
            InMemoryControlRuntimeDecisionPublisherV1::default(),
            authenticator(&signing),
        )
        .expect("owner");
        let snapshot = owner
            .collect_authenticated_snapshot(snapshot_request(), vec![signed_summary(&signing)])
            .expect("snapshot");
        let prepared = owner
            .prepare_plan(&snapshot, planning_request())
            .expect("prepared");
        let evaluation = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
            objective_digest: prepared.objective_digest(),
            body_generation: prepared.body_generation(),
            evaluation_policy_digest: prepared.evaluation_policy_digest(),
            evaluation_digest: digest("ndu-evaluation"),
            evaluated_candidate_ids: prepared
                .feasible_candidates()
                .iter()
                .map(|candidate| candidate.candidate_id.clone())
                .collect(),
            rejected_candidate_ids: Vec::new(),
            pareto_candidate_ids: vec![id("work")],
            advisory_candidate_id: Some(id("work")),
            uncertainty_digest: digest("uncertainty"),
            disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
        })
        .expect("evaluation");
        let selected = owner
            .finalize_selected_plan(
                &snapshot,
                &prepared,
                &evaluation,
                id("attempt-1"),
                300,
            )
            .expect("selected");
        assert_eq!(
            selected.attempt.phase(),
            crate::ExecutionAttemptPhaseV1::GrantRequested
        );
        owner
            .record_authorization(&id("attempt-1"), digest("authority"))
            .expect("authorization");

        let (clock, journal, publisher, auth) = owner.into_parts();
        let recovered = ControlRuntimeOwnerV1::open(
            id("control.runtime"),
            1,
            clock,
            journal,
            publisher,
            auth,
        )
        .expect("recover owner");
        assert_eq!(
            recovered
                .attempt(&id("attempt-1"))
                .expect("attempt")
                .phase(),
            crate::ExecutionAttemptPhaseV1::Authorized
        );
    }

    #[test]
    fn invalid_signature_is_rejected_before_snapshot_admission() {
        let signing = SigningKey::from_bytes(&[7_u8; 32]);
        let other = SigningKey::from_bytes(&[8_u8; 32]);
        let journal = DurablePlannerJournalV1::open(
            InMemoryPlannerJournalStoreV1::default(),
            InMemoryPlannerJournalAnchorV1::default(),
        )
        .expect("journal");
        let mut owner = ControlRuntimeOwnerV1::open(
            id("control.runtime"),
            1,
            ManualTrustedClockV1::new(100),
            journal,
            InMemoryControlRuntimeDecisionPublisherV1::default(),
            authenticator(&signing),
        )
        .expect("owner");
        assert!(matches!(
            owner.collect_authenticated_snapshot(
                snapshot_request(),
                vec![signed_summary(&other)]
            ),
            Err(ControlRuntimeOwnerErrorV1::Authentication(
                OwnerPortAuthenticationErrorV1::InvalidSignature
            ))
        ));
    }
}

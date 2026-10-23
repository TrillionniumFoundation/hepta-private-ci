//! Borrowed, current evidence from the actual durable ledger owner.

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::*;
use crate::signed_evidence::CurrentLearningActorV1;

/// Trusted host clock installed on the ledger owner, never submitted with an
/// evidence request. Implementations must report current UTC seconds and fail
/// on unavailable time. The default owner clock uses `SystemTime`.
pub trait CurrentOutcomeHostClockV1: Send + Sync {
    fn now_unix_seconds(&self) -> Result<u64, ProductionLedgerError>;
}

struct SystemCurrentOutcomeClock;

impl CurrentOutcomeHostClockV1 for SystemCurrentOutcomeClock {
    fn now_unix_seconds(&self) -> Result<u64, ProductionLedgerError> {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_secs())
            .map_err(|_| ProductionLedgerError::Binding("owner clock unavailable"))
    }
}

pub(super) struct CurrentOutcomeClockState {
    clock: Arc<dyn CurrentOutcomeHostClockV1>,
    observed_floor: AtomicU64,
}

impl Default for CurrentOutcomeClockState {
    fn default() -> Self {
        Self {
            clock: Arc::new(SystemCurrentOutcomeClock),
            observed_floor: AtomicU64::new(0),
        }
    }
}

impl CurrentOutcomeClockState {
    fn now(&self) -> Result<u64, ProductionLedgerError> {
        let now = self.clock.now_unix_seconds()?;
        if now < self.observed_floor.fetch_max(now, Ordering::SeqCst) {
            return Err(ProductionLedgerError::Binding("owner clock regressed"));
        }
        Ok(now)
    }
}

/// No constructor, clone or deserialization is exposed. The owner borrow fences
/// correction, unlearning and trust rotation until this evidence is dropped.
/// Time still advances: consumers must call `ensure_current` at their final use.
/// This evidence grants no permission to execute or promote a procedure.
pub struct CurrentAuthenticatedOutcomeV1<'owner> {
    owner: &'owner LedgerWriter,
    outcome_record: &'owner LedgerRecord,
    outcome: &'owner AuthenticatedOutcomeRecordV2,
    decision_record: &'owner LedgerRecord,
    decision: &'owner AuthenticatedDecisionRecordV2,
    frontier: LedgerWitnessFrontier,
    valid_until: u64,
}

impl CurrentAuthenticatedOutcomeV1<'_> {
    pub(super) fn owner_time(&self) -> Result<u64, ProductionLedgerError> {
        self.owner.outcome_clock.now()
    }

    pub fn ensure_current(&self) -> Result<(), ProductionLedgerError> {
        self.owner.resolve_current_outcome(
            &self.outcome.record_id,
            &self.outcome.episode_id,
            self.outcome.support_digest,
        )?;
        Ok(())
    }

    #[must_use]
    pub fn outcome(&self) -> &AuthenticatedOutcomeRecordV2 {
        self.outcome
    }

    #[must_use]
    pub fn decision(&self) -> &AuthenticatedDecisionRecordV2 {
        self.decision
    }

    #[must_use]
    pub fn outcome_event_digest(&self) -> Digest32 {
        self.outcome_record.event_digest
    }

    #[must_use]
    pub fn decision_event_digest(&self) -> Digest32 {
        self.decision_record.event_digest
    }

    #[must_use]
    pub fn ledger_binding(&self) -> Digest32 {
        self.owner.backend.binding()
    }

    #[must_use]
    pub fn witness_frontier(&self) -> LedgerWitnessFrontier {
        self.frontier
    }

    #[must_use]
    pub fn trust_distribution_digest(&self) -> Digest32 {
        self.owner.trust_distribution_digest()
    }

    #[must_use]
    pub fn valid_until_unix_seconds(&self) -> u64 {
        self.valid_until
    }
}

impl LedgerWriter {
    /// Host assembly only. Retains the observation floor across clock changes;
    /// requests cannot supply a time or replace this clock through an evidence DTO.
    pub fn configure_current_outcome_clock(&mut self, clock: Arc<dyn CurrentOutcomeHostClockV1>) {
        self.outcome_clock.clock = clock;
    }

    pub fn resolve_current_outcome(
        &self,
        record_id: &StableId,
        episode_id: &StableId,
        expected_support: Digest32,
    ) -> Result<CurrentAuthenticatedOutcomeV1<'_>, ProductionLedgerError> {
        let now = self.outcome_clock.now()?;
        let trust_expiry = self.trust.current_valid_until(now)?;
        let ledger = self.backend.core()?;
        let frontier = self.backend.frontier()?;
        let witness = self.witness.frontier()?;
        if validate_witness_state(ledger.records(), frontier, witness)? != 0 || frontier != witness
        {
            return Err(ProductionLedgerError::WitnessLag);
        }
        let record = ledger
            .active_record_by_id(record_id)?
            .ok_or(ProductionLedgerError::Binding("outcome no longer active"))?;
        let LedgerEvent::AuthenticatedOutcomeV2(outcome) = &record.event else {
            return Err(ProductionLedgerError::Binding(
                "authenticated outcome required",
            ));
        };
        if &outcome.episode_id != episode_id
            || expected_support.is_zero()
            || outcome.support_digest != expected_support
        {
            return Err(ProductionLedgerError::Binding("outcome support binding"));
        }
        let (Some(observed), Some(finalized), Some(_)) =
            (outcome.observed_at, outcome.finalized_at, outcome.value)
        else {
            return Err(ProductionLedgerError::Binding(
                "terminal measured outcome required",
            ));
        };
        if outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
            || outcome.censoring_reason.is_some()
            || observed > finalized
            || finalized > now
            || outcome.latest_observable_at > finalized
        {
            return Err(ProductionLedgerError::Binding("terminal outcome time"));
        }
        let decision = find_authenticated_decision(ledger, episode_id)?;
        if decision.objective_digest != self.verifier().objective_digest() {
            return Err(ProductionLedgerError::Binding("current outcome objective"));
        }
        let decision_record = ledger
            .active_record_by_id(&decision.record_id)?
            .ok_or(ProductionLedgerError::AuthenticatedDecisionRequired)?;
        let generator_expiry = self.verifier().verify_current_actor(
            CurrentLearningActorV1 {
                id: &decision.generator_id,
                controller: &decision.generator_controller_id,
                credential: decision.generator_credential_chain_digest,
                key: decision.generator_signing_key_digest,
                scope: decision.generator_scope_digest,
                epoch: decision.generator_authority_epoch,
            },
            LearningEvidenceRoleV1::Generator,
            now,
        )?;
        let observer_expiry = self.verifier().verify_current_actor(
            CurrentLearningActorV1 {
                id: &outcome.observer_id,
                controller: &outcome.observer_controller_id,
                credential: outcome.observer_credential_chain_digest,
                key: outcome.observer_signing_key_digest,
                scope: outcome.observer_scope_digest,
                epoch: outcome.observer_authority_epoch,
            },
            LearningEvidenceRoleV1::Observer,
            now,
        )?;
        Ok(CurrentAuthenticatedOutcomeV1 {
            owner: self,
            outcome_record: record,
            outcome,
            decision_record,
            decision,
            frontier,
            valid_until: trust_expiry.min(generator_expiry).min(observer_expiry),
        })
    }
}

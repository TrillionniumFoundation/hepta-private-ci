//! Independent original business observations. Accepted witnessed ledger facts
//! are history; only a new append consumes current Observer authorization.

use super::*;

impl OriginalCellQ24TaskLedgerProducerV1 {
    pub fn submit_original_terminal_outcome(
        &self,
        outcome: AuthenticatedOutcomeV1,
        signed: &SignedLearningEvidenceV1,
    ) -> Result<OriginalCellQ24TaskLedgerStatusV1, Error> {
        let mut state = self.state.lock().map_err(|_| Error::Binding("producer lock"))?;
        let captured = self.capture(&mut state)?;
        let mut locked = self.ledger.lock().map_err(|_| Error::Binding("ledger lock"))?;
        let ledger: &mut LedgerWriter = &mut locked;
        self.require_ledger(ledger)?;
        let (snapshot, _) = original_snapshot(ledger)?;
        self.recorded_decision(&mut state, ledger, &captured, &snapshot)?;
        self.require_outcome(&outcome, &captured)?;
        let payload = outcome_signing_payload_v2(&outcome);
        if outcome_codec::decode(&payload)? != outcome {
            return Err(Error::Binding("canonical original business observation"));
        }
        let bytes = match state.journal.read(&self.outcome_key) {
            Ok(bytes) => bytes,
            Err(LearningOriginalOwnerErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {
                if snapshot.records().iter().any(|record| matches!(
                    &record.event, LedgerEvent::AuthenticatedOutcomeV2(value)
                        if value.episode_id == self.config.episode_id
                )) {
                    return Err(Error::Binding("Outcome exists outside original observation journal"));
                }
                witnessed_snapshot(ledger)?;
                // Only a new original observation claim consumes current
                // Observer authorization. A witnessed retry remains history.
                ledger.validate_observed_outcome(&outcome, signed, now()?)?;
                self.require_source(&captured)?;
                state.journal.commit_once(&self.outcome_key, || {
                    self.require_source(&captured).map_err(owner_binding)?;
                    binding::encode(snapshot.head_digest, &payload, signed)
                })?
            }
            Err(error) => return Err(error.into()),
        };
        let (_, original_payload, original_signed) = binding::decode(&bytes)?;
        if original_payload != payload || &original_signed != signed {
            return Err(Error::Binding("original Outcome signature is immutable"));
        }
        self.resume_original_outcome(&mut state, ledger, &captured)?;
        self.status(&mut state, ledger, &captured)
    }

    pub(super) fn resume_original_outcome(
        &self,
        state: &mut State,
        ledger: &mut LedgerWriter,
        captured: &Captured,
    ) -> Result<(), Error> {
        let bytes = match state.journal.read(&self.outcome_key) {
            Ok(bytes) => bytes,
            Err(LearningOriginalOwnerErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {
                return Ok(());
            }
            Err(error) => return Err(error.into()),
        };
        let (predecessor, payload, signed) = binding::decode(&bytes)?;
        let original = outcome_codec::decode(&payload)?;
        self.require_outcome(&original, captured)?;
        let (snapshot, frontier) = original_snapshot(ledger)?;
        self.recorded_decision(state, ledger, captured, &snapshot)?;
        let expected = outcome_event(&original, &signed, &self.config.observer);
        let accepted = snapshot.records().iter().any(|record|
            record.event == expected && record.predecessor_chain_digest == predecessor
                && record.sequence.get() <= frontier.anchor.sequence);
        self.require_source(captured)?;
        if !accepted {
            // Reuse only the retained original observation and signature. An
            // unappended expired signature fails here; there is no renewal.
            ledger.validate_observed_outcome(&original, &signed, now()?)?;
            ledger.append_outcome(predecessor, original, &signed, now()?)?;
        }
        self.require_source(captured)?;
        Ok(())
    }

    pub(super) fn status(
        &self,
        state: &mut State,
        ledger: &LedgerWriter,
        captured: &Captured,
    ) -> Result<OriginalCellQ24TaskLedgerStatusV1, Error> {
        self.require_source(captured)?;
        self.require_ledger(ledger)?;
        let snapshot = witnessed_snapshot(ledger)?;
        let decision = self.recorded_decision(state, ledger, captured, &snapshot)?;
        let result = match state.journal.read(&self.outcome_key) {
            Err(LearningOriginalOwnerErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {
                if snapshot.records().iter().any(|record| matches!(
                    &record.event, LedgerEvent::AuthenticatedOutcomeV2(value)
                        if value.episode_id == self.config.episode_id
                )) {
                    return Err(Error::Binding("unowned original Outcome"));
                }
                OriginalCellQ24TaskLedgerStatusV1::AwaitingOutcome { decision }
            }
            Err(error) => return Err(error.into()),
            Ok(bytes) => {
                let (predecessor, payload, signed) = binding::decode(&bytes)?;
                let original = outcome_codec::decode(&payload)?;
                self.require_outcome(&original, captured)?;
                let expected = outcome_event(&original, &signed, &self.config.observer);
                let replay = LearningLedger::from_snapshot(snapshot.clone())
                    .map_err(ProductionLedgerError::from)?;
                let outcome = replay.active_records().into_iter().find(|record|
                    record.event == expected && record.predecessor_chain_digest == predecessor
                        && record.sequence > decision.sequence)
                    .cloned().ok_or(LearningOriginalOwnerErrorV1::CommitUncertain)?;
                // The exact active record is covered by the original witness.
                // Verify its unchanged signature at original issue time only.
                let observed = ledger.verifier().verify(
                    LearningEvidenceRoleV1::Observer, &signed, &payload, signed.issued_at,
                )?;
                if observed.principal() != &self.config.observer.principal
                    || observed.controller_id() != &self.config.observer.controller_id
                    || state.journal.read(&self.outcome_key)? != bytes
                {
                    return Err(Error::Binding("original historical Observer"));
                }
                OriginalCellQ24TaskLedgerStatusV1::Complete { decision, outcome }
            }
        };
        self.require_source(captured)?;
        self.require_ledger(ledger)?;
        if witnessed_snapshot(ledger)? != snapshot {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(result)
    }

    fn recorded_decision(
        &self,
        state: &mut State,
        ledger: &LedgerWriter,
        captured: &Captured,
        snapshot: &LedgerSnapshot,
    ) -> Result<LedgerRecord, Error> {
        let bytes = state.journal.read(&self.decision_key)?;
        let (predecessor, payload, signed) = binding::decode(&bytes)?;
        if payload != decision_signing_payload_v2(&captured.decision)?
            || signed.evidence_id != self.decision_key.plan_id
        {
            return Err(Error::Binding("original recorded Decision preimage"));
        }
        ledger.verify_active_decision_binding(
            &captured.decision.record_id, &captured.decision.episode_id,
        )?;
        let expected = binding::decision_event(&captured.decision, &signed, &self.config.generator)?;
        let (current, frontier) = original_snapshot(ledger)?;
        if current != *snapshot {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        let record = snapshot.records().iter().find(|record|
            record.event == expected && record.predecessor_chain_digest == predecessor
                && record.sequence.get() <= frontier.anchor.sequence)
            .cloned().ok_or(LearningOriginalOwnerErrorV1::CommitUncertain)?;
        let generator = ledger.verifier().verify(
            LearningEvidenceRoleV1::Generator, &signed, &payload, signed.issued_at,
        )?;
        if generator.principal() != &self.config.generator.principal
            || generator.controller_id() != &self.config.generator.controller_id
            || state.journal.read(&self.decision_key)? != bytes
        {
            return Err(Error::Binding("original historical Generator"));
        }
        Ok(record)
    }

    fn require_outcome(
        &self,
        outcome: &AuthenticatedOutcomeV1,
        captured: &Captured,
    ) -> Result<(), Error> {
        if outcome.record_id != self.config.outcome_record_id
            || outcome.outcome_id != self.config.outcome_id
            || outcome.episode_id != self.config.episode_id
            || outcome.observer != self.config.observer.principal
            || outcome.support_digest != captured.publication.publication_digest()
            || outcome.unit_profile_digest != self.config.unit_profile_digest
            || outcome.watermark.expected_delay_profile_digest != self.config.expected_delay_profile_digest
            || outcome.watermark.terminality != OutcomeTerminalityV1::Terminal
            || outcome.watermark.censoring_reason.is_some()
            || outcome.watermark.correction_predecessor.is_some()
            || outcome.observed_at.is_none()
            || outcome.watermark.finalized_at.is_none()
            || outcome.value.is_none_or(|value| !(-(8_i64 << 32)..=(8_i64 << 32)).contains(&value.raw()))
        {
            return Err(Error::Binding("original independent Terminal business observation"));
        }
        Ok(())
    }
}

fn outcome_event(
    outcome: &AuthenticatedOutcomeV1,
    signed: &SignedLearningEvidenceV1,
    observer: &TrustedLearningSignerV1,
) -> LedgerEvent {
    LedgerEvent::AuthenticatedOutcomeV2(AuthenticatedOutcomeRecordV2 {
        record_id: outcome.record_id.clone(), outcome_id: outcome.outcome_id.clone(),
        episode_id: outcome.episode_id.clone(), observer_id: observer.principal.principal_id.clone(),
        observer_controller_id: observer.controller_id.clone(),
        observer_credential_chain_digest: observer.principal.credential_chain_digest,
        observer_signing_key_digest: observer.principal.signing_key_digest,
        observer_scope_digest: observer.principal.scope_digest,
        observer_authority_epoch: observer.principal.authority_epoch,
        observed_at: outcome.observed_at, value: outcome.value,
        unit_profile_digest: outcome.unit_profile_digest, support_digest: outcome.support_digest,
        latest_observable_at: outcome.watermark.latest_observable_at,
        expected_delay_profile_digest: outcome.watermark.expected_delay_profile_digest,
        terminality: match outcome.watermark.terminality {
            OutcomeTerminalityV1::Pending => AuthenticatedOutcomeTerminality::Pending,
            OutcomeTerminalityV1::Censored => AuthenticatedOutcomeTerminality::Censored,
            OutcomeTerminalityV1::Terminal => AuthenticatedOutcomeTerminality::Terminal,
        },
        censoring_reason: outcome.watermark.censoring_reason.clone(),
        correction_predecessor: outcome.watermark.correction_predecessor.clone(),
        finalized_at: outcome.watermark.finalized_at,
        authentication_digest: binding::authentication_digest(signed),
    })
}

//! The original producer supplies task data while its real Source, Cell,
//! CURRENT and signature owners remain live. No external data becomes a cap.

use codex_hepta_agent_protocol::MAX_Q24_DECISION_PREIMAGE_BYTES;
use codex_hepta_agent_protocol::Q24OriginalTaskObservationV1;

use super::*;

impl OriginalCellQ24TaskLedgerProducerV1 {
    pub(crate) fn read_original_task_observation(
        &self,
    ) -> Result<Q24OriginalTaskObservationV1, Error> {
        let OriginalTaskCustodyV1::Active { cell, .. } = &self.task else {
            return Err(Error::Binding("live original task observation required"));
        };
        let cell: &PublishedCircuitCellOwnerV1<FileAnchorWitnessStore> = cell;
        let mut state = self
            .state
            .lock()
            .map_err(|_| Error::Binding("producer lock"))?;
        let captured = self.capture(&mut state)?;
        let before = cell
            .committed(&captured.publication)
            .map_err(|_| Error::Binding("original Cell/CURRENT/FinalUse is unavailable"))?;
        self.require_source(&captured)?;
        let ledger = self
            .ledger
            .lock()
            .map_err(|_| Error::Binding("ledger lock"))?;
        ledger.verifier().require_signer_binding(
            LearningEvidenceRoleV1::Observer,
            &self.config.observer,
            now()?,
        )?;
        let status = self.status(&mut state, &ledger, &captured)?;
        let decision = match &status {
            OriginalCellQ24TaskLedgerStatusV1::AwaitingOutcome { decision }
            | OriginalCellQ24TaskLedgerStatusV1::Complete { decision, .. } => decision,
        };
        let payload = decision_signing_payload_v2(&captured.decision)?;
        if payload.is_empty() || payload.len() > MAX_Q24_DECISION_PREIMAGE_BYTES {
            return Err(Error::Binding(
                "bounded original Decision preimage required",
            ));
        }
        let observation = Q24OriginalTaskObservationV1 {
            run_id: captured.decision.record_id.to_string(),
            source_publication_digest: captured.publication.publication_digest().to_string(),
            source_history_digest: captured.publication.history_digest().to_string(),
            decision_preimage_hex: control::hex(&payload),
            decision_sequence: decision.sequence.get(),
            decision_chain_digest: decision.chain_digest.to_string(),
            episode_id: self.config.episode_id.to_string(),
            selected_candidate_id: captured.decision.selected_candidate_id.to_string(),
            outcome_record_id: self.config.outcome_record_id.to_string(),
            outcome_id: self.config.outcome_id.to_string(),
            unit_profile_digest: self.config.unit_profile_digest.to_string(),
            expected_delay_profile_digest: self.config.expected_delay_profile_digest.to_string(),
            observer_principal_id: self.config.observer.principal.principal_id.to_string(),
            observer_controller_id: self.config.observer.controller_id.to_string(),
        };
        if self.status(&mut state, &ledger, &captured)? != status {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        ledger.verifier().require_signer_binding(
            LearningEvidenceRoleV1::Observer,
            &self.config.observer,
            now()?,
        )?;
        self.require_source(&captured)?;
        if cell.committed(&captured.publication).map_err(|_| {
            Error::Binding("original Cell/CURRENT/FinalUse changed during observation")
        })? != before
        {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(observation)
    }
}

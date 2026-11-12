//! Signature/data verification of one original first-A Ledger cut.
//! The actual Root caller supplies independently retained files, publication,
//! Cell data and its registered trust. Nothing returned here authorizes a new
//! recipient, reopens a writer, signs evidence or creates a Dataset grant.

use super::*;
use crate::CircuitTaskSourceInputV1;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellDefinitionV1;

pub(crate) struct OriginalTaskLedgerHistoryContextV1<'a> {
    pub(crate) identity: &'a AgentdIdentity,
    pub(crate) definition: &'a CellDefinitionV1,
    pub(crate) source: &'a CircuitTaskSourceInputV1,
    pub(crate) config: &'a OriginalCellQ24TaskLedgerConfigV1,
    pub(crate) ledger_binding: Digest32,
    pub(crate) verifier: &'a LearningEvidenceVerifierV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OriginalTaskLedgerHistoryDataV1 {
    pub(crate) signature_binding: Digest32,
    pub(crate) decision: LedgerRecord,
    pub(crate) outcome: LedgerRecord,
}

impl OriginalTaskLedgerHistoryContextV1<'_> {
    pub(crate) fn signature_binding(&self) -> Result<Digest32, Error> {
        if self.verifier.objective_digest() != self.source.objective_digest
            || self.source.scope.agent_id.as_str() != self.identity.agent_id.as_str()
            || self.config.outcome_record_id == self.source.scope.run_id
            || !(1..=86_400).contains(&self.config.maximum_signature_lifetime_seconds)
        {
            return Err(Error::Binding("original historical task context"));
        }
        let task = crate::circuit_feature_task_digest_v1(self.definition, self.source)
            .map_err(|_| Error::Binding("original historical task digest"))?;
        projection::configuration_digest(
            self.config,
            task,
            self.ledger_binding,
            self.verifier.trust_digest(),
            self.identity,
        )
    }

    pub(crate) fn execution_keys(&self) -> Result<[ProductEvaluationExecutionKeyV1; 2], Error> {
        let binding = self.signature_binding()?;
        Ok([
            execution_key("decision", binding)?,
            execution_key("outcome", binding)?,
        ])
    }

    /// Only the explicit empty-baseline first-A profile is supported: exactly
    /// one original Decision followed by its independent Terminal Outcome.
    /// The caller brackets these bytes with the actual complete four-file cut.
    pub(crate) fn verify_original_terminal(
        &self,
        observed: &LedgerReadOnlyObservationV1,
        publication: &CircuitTaskSourcePublicationV1,
        cell: &CellDecisionReceiptV1,
        decision_bytes: &[u8],
        outcome_bytes: &[u8],
        now: u64,
    ) -> Result<OriginalTaskLedgerHistoryDataV1, Error> {
        let signature_binding = self.signature_binding()?;
        if observed.cut.binding != self.ledger_binding
            || observed.cut.frontier.segment.is_some()
            || observed.cut.frontier.sealed
            || observed.cut.frontier.anchor.sequence != 2
            || observed.snapshot.records().len() != 2
            || observed.snapshot.head_digest != observed.cut.frontier.anchor.chain_digest
        {
            return Err(Error::Binding("exact original first-A Ledger cut"));
        }
        // Rebuild the semantic indexes even for this data-only function. The
        // physical view must still be re-observed by the owning Root caller.
        let replay = LearningLedger::from_snapshot(observed.snapshot.clone())
            .map_err(ProductionLedgerError::from)?;
        if replay.active_records().len() != 2 {
            return Err(Error::Binding("original first-A facts are not active"));
        }
        publication
            .require_decision(cell)
            .map_err(|_| Error::Binding("original Source and physical Cell decision differ"))?;
        let decision =
            projection::decision(self.config, self.definition, self.source, publication, cell)?;
        let (decision_predecessor, decision_payload, decision_signed) =
            binding::decode(decision_bytes)?;
        let keys = self.execution_keys()?;
        if decision_payload != decision_signing_payload_v2(&decision)?
            || decision_signed.evidence_id != keys[0].plan_id
            || decision_signed.issued_at > now
            || decision_signed.issued_at >= self.config.claim_deadline_unix_seconds
            || decision_signed
                .expires_at
                .checked_sub(decision_signed.issued_at)
                .is_none_or(|lifetime| lifetime > self.config.maximum_signature_lifetime_seconds)
        {
            return Err(Error::Binding(
                "original Generator signature preimage or time",
            ));
        }
        self.verifier.require_signer_binding(
            LearningEvidenceRoleV1::Generator,
            &self.config.generator,
            decision_signed.issued_at,
        )?;
        let generator = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &decision_signed,
            &decision_payload,
            decision_signed.issued_at,
        )?;
        let (outcome_predecessor, outcome_payload, outcome_signed) =
            binding::decode(outcome_bytes)?;
        let outcome = outcome_codec::decode(&outcome_payload)?;
        projection::require_outcome(self.config, publication, &outcome)?;
        if outcome_signing_payload_v2(&outcome) != outcome_payload
            || outcome_signed.issued_at > now
            || outcome.watermark.latest_observable_at > now
            || outcome.observed_at.is_some_and(|at| at > now)
            || outcome.watermark.finalized_at.is_some_and(|at| at > now)
        {
            return Err(Error::Binding(
                "original Observer signature preimage or time",
            ));
        }
        self.verifier.require_signer_binding(
            LearningEvidenceRoleV1::Observer,
            &self.config.observer,
            outcome_signed.issued_at,
        )?;
        let observer = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &outcome_signed,
            &outcome_payload,
            outcome_signed.issued_at,
        )?;
        if generator.principal() != &self.config.generator.principal
            || generator.controller_id() != &self.config.generator.controller_id
            || observer.principal() != &self.config.observer.principal
            || observer.controller_id() != &self.config.observer.controller_id
            || generator.principal().principal_id == observer.principal().principal_id
            || generator.principal().credential_chain_digest
                == observer.principal().credential_chain_digest
            || generator.principal().signing_key_digest == observer.principal().signing_key_digest
            || generator.controller_id() == observer.controller_id()
            || self.config.generator.revoked_at.is_some_and(|at| now >= at)
            || self.config.observer.revoked_at.is_some_and(|at| now >= at)
        {
            return Err(Error::Binding(
                "original independently enrolled Generator and Observer",
            ));
        }
        let records = replay.records();
        let [original_decision, original_outcome] = records else {
            return Err(Error::Binding("original first-A record count"));
        };
        if original_decision.sequence.get() != 1
            || original_outcome.sequence.get() != 2
            || original_decision.predecessor_chain_digest != Digest32::ZERO
            || original_decision.predecessor_chain_digest != decision_predecessor
            || original_outcome.predecessor_chain_digest != original_decision.chain_digest
            || original_outcome.predecessor_chain_digest != outcome_predecessor
            || original_decision.event
                != binding::decision_event(&decision, &decision_signed, &self.config.generator)?
            || original_outcome.event
                != projection::outcome_event(&outcome, &outcome_signed, &self.config.observer)
        {
            return Err(Error::Binding(
                "original witnessed Decision and Outcome differ",
            ));
        }
        Ok(OriginalTaskLedgerHistoryDataV1 {
            signature_binding,
            decision: original_decision.clone(),
            outcome: original_outcome.clone(),
        })
    }
}

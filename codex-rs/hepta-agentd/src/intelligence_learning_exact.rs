//! Exact interactive Decision/Outcome closure for the canonical product path.
//!
//! The background reconciler remains fair and destination-wide. Interactive
//! physical execution must instead close the operation it just prepared, so it
//! can prove that its own Decision is durably acknowledged before model send and
//! that its own terminal Outcome is durably acknowledged afterwards. This module
//! reuses the same immutable payload, kernel.operations state machine, current
//! final-use authority and sole LedgerWriter; it does not add another writer or
//! execution spine.

use super::*;
use codex_hepta_operations::DurableOperationRecord;
use codex_hepta_operations::DurableOperationState;

impl AgentdIntelligenceLearningHostV1 {
    /// Persist and apply the exact Decision for this prepared run.
    ///
    /// A physical caller must require `Acknowledged` before crossing the model
    /// send boundary. `Rejected`, `Revoked` and `Indeterminate` are returned
    /// distinctly and never become implicit permission to continue.
    pub async fn record_decision_before_dispatch_v1(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        request: AgentdIntelligenceDecisionAppendV1,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        let frozen = prepared.clone();
        let writer = Arc::clone(&self.writer);
        let payload = self
            .run_io(move || {
                let writer = writer
                    .lock()
                    .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                Ok(LearningPayloadV1::Decision(decision_payload(
                    &writer, &frozen, request,
                )?))
            })
            .await?;
        self.enqueue_and_dispatch_exact_v1(prepared, payload, None)
            .await
    }

    /// Persist and apply the exact terminal Outcome for this prepared run.
    ///
    /// The request is already bound to an observed terminal Agentd receipt and
    /// provider digest by `outcome_payload`; this method only closes the matching
    /// immutable learning operation.
    pub async fn record_outcome_after_terminal_v1(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        request: AgentdIntelligenceOutcomeAppendV1,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        let frozen = prepared.clone();
        let writer = Arc::clone(&self.writer);
        let payload = self
            .run_io(move || {
                let writer = writer
                    .lock()
                    .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                Ok(LearningPayloadV1::Outcome(outcome_payload(
                    &writer, &frozen, request,
                )?))
            })
            .await?;
        let predecessor = decision_operation_id(
            &payload.run_id()?,
            payload.episode_id(),
            payload.run_snapshot_digest()?,
            prepared.envelope.decision.decision_digest,
        )?;
        self.enqueue_and_dispatch_exact_v1(prepared, payload, Some(predecessor))
            .await
    }

    async fn enqueue_and_dispatch_exact_v1(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        payload: LearningPayloadV1,
        expected_predecessor: Option<StableId>,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        if prepared.run_snapshot().generation != self.generation.get() {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "learning outbox generation",
            ));
        }
        let envelope = PersistedLearningEnvelopeV1 {
            schema_version: LEARNING_PAYLOAD_SCHEMA_VERSION,
            owner_generation: self.generation.get(),
            payload,
        };
        let encoded = serde_json::to_vec(&envelope)
            .map_err(|error| AgentdIntelligenceLearningErrorV1::Json(error.to_string()))?;
        if encoded.is_empty() || encoded.len() > MAX_LEARNING_PAYLOAD_BYTES {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "learning payload size",
            ));
        }

        let payload_digest = Digest32::of_bytes(&encoded);
        let root = self.payload_root.clone();
        self.run_io(move || persist_payload(&root, payload_digest, &encoded))
            .await?;
        let scope_id = envelope.payload.run_id()?;
        let operation_id = envelope.payload.operation_id()?;
        let intent = DurableOperationIntentV1 {
            scope_id: scope_id.clone(),
            operation_id: operation_id.clone(),
            expected_predecessor,
            destination: self.destination.clone(),
            payload_digest,
            owner_generation: self.generation,
        };
        self.operations.prepare_intent(&intent).await?;

        let persisted = self.load_payload(payload_digest).await?;
        validate_claim_payload(&intent, &persisted)?;

        // Destination-first observation makes retry safe even when the process
        // died after the ledger commit but before source acknowledgement.
        let writer = Arc::clone(&self.writer);
        let observed = persisted.clone();
        let destination_observation = self
            .run_io(move || {
                let mut writer = writer
                    .lock()
                    .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                Ok(observe_applied_payload(&mut writer, &observed))
            })
            .await?;

        match destination_observation {
            Ok(Some(receipt)) => {
                return self
                    .settle_observation(
                        &scope_id,
                        &operation_id,
                        ApplyObservation::Acknowledged(receipt),
                    )
                    .await;
            }
            Ok(None) => {}
            Err(error) => {
                return self
                    .settle_observation(&scope_id, &operation_id, classify_apply(Err(error)))
                    .await;
            }
        }

        let Some(claim) = self
            .operations
            .claim_operation(
                &scope_id,
                &operation_id,
                &self.worker_id,
                self.generation,
                CLAIM_LEASE,
            )
            .await?
        else {
            let record = self
                .operations
                .operation(&scope_id, &operation_id)
                .await?
                .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
            return Ok(existing_exact_receipt(record));
        };

        let grants = Arc::clone(&self.grants);
        let binding = claim.intent.final_use_binding();
        let signed = match self
            .run_io(move || grants.signed_grant(&binding).map_err(Into::into))
            .await
        {
            Ok(value) => value,
            Err(error) => {
                self.operations
                    .defer_pre_dispatch_claim_v1(&claim, GRANT_RETRY_DELAY)
                    .await?;
                return Err(error);
            }
        };
        let authorized = self
            .operations
            .authorize_dispatch(&self.authority, &signed, &claim)
            .await?;
        let observation = self.execute_ledger_operation(authorized, persisted).await?;
        self.settle_observation(&scope_id, &operation_id, observation)
            .await
    }
}

fn existing_exact_receipt(record: DurableOperationRecord) -> AgentdIntelligenceLearningReceiptV1 {
    let evidence_digest = record
        .terminal_evidence_digest
        .or(record.indeterminate_digest)
        .unwrap_or(record.semantic_digest);
    let disposition = match (record.state, record.terminal_outcome) {
        (DurableOperationState::NotApplied, Some(ReconciliationOutcome::NotApplied)) => {
            AgentdIntelligenceLearningDispositionV1::Rejected
        }
        (DurableOperationState::Quarantined, Some(ReconciliationOutcome::Quarantined)) => {
            AgentdIntelligenceLearningDispositionV1::Revoked
        }
        // An Applied source record without the exact destination event is not
        // sufficient proof for physical send. Keep it reconcile-only.
        _ => AgentdIntelligenceLearningDispositionV1::Indeterminate,
    };
    AgentdIntelligenceLearningReceiptV1 {
        operation_id: record.intent.operation_id,
        disposition,
        evidence_digest,
        append: None,
    }
}

//! Public product-safe methods over the durable intelligence learning host.
//!
//! Product settlement is exact-operation scoped. It never consumes a grant or
//! writer attempt for whichever unrelated destination row happens to sort first.
//! Current wall-clock time is acquired inside Agentd for every first apply or
//! replay of a missing destination event; immutable payload time remains only
//! historical admission metadata.

use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_operations::DurableOperationState;

use super::*;

const EXACT_OPERATION_RETRY_DELAY: Duration = Duration::from_secs(1);

impl AgentdIntelligenceLearningHostV1 {
    pub async fn dispatch_next_current(
        &self,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1>
    {
        self.dispatch_next_at(current_validation_time()?).await
    }

    pub async fn reconcile_unsettled_current(
        &self,
        limit: u32,
    ) -> Result<Vec<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1> {
        self.reconcile_unsettled_at(limit, current_validation_time()?)
            .await
    }

    pub fn learning_scope_id_for(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
    ) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        parse_id(&prepared.run_snapshot().run_id)
    }

    pub fn decision_operation_id_for(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        episode_id: &StableId,
    ) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        let snapshot = prepared.run_snapshot();
        decision_operation_id(
            &parse_id(&snapshot.run_id)?,
            episode_id.as_str(),
            intelligence_run_snapshot_digest_v1(prepared)?,
            prepared.envelope.decision.decision_digest,
        )
    }

    pub fn outcome_operation_id_for(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        request: &AgentdIntelligenceOutcomeAppendV1,
    ) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        let snapshot = prepared.run_snapshot();
        let physical_binding = intelligence_physical_terminal_binding_digest_v1(
            prepared,
            &request.run_receipt,
            request.provider_terminal_digest,
        )?;
        outcome_operation_id(
            &parse_id(&snapshot.run_id)?,
            request.outcome.outcome_id.as_str(),
            physical_binding,
        )
    }

    /// Dispatch this exact prepared operation. Older queued work remains queued
    /// and cannot consume the final-use grant intended for this run/episode.
    pub async fn dispatch_operation_current(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1>
    {
        self.dispatch_operation_at(scope_id, operation_id, current_validation_time()?)
            .await
    }

    async fn dispatch_operation_at(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        validation_now: u64,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1>
    {
        let Some(claim) = self
            .operations
            .claim_operation(
                scope_id,
                operation_id,
                &self.worker_id,
                self.generation,
                CLAIM_LEASE,
            )
            .await?
        else {
            return Ok(None);
        };
        let payload = self.load_payload(claim.intent.payload_digest)?;
        validate_claim_payload(&claim.intent, &payload)?;

        if let Some(observation) = validation_time_observation(&payload, validation_now) {
            let evidence_digest = observation_digest(&observation);
            self.operations
                .release_not_dispatched(
                    &claim,
                    evidence_digest,
                    EXACT_OPERATION_RETRY_DELAY,
                )
                .await?;
            return Ok(Some(AgentdIntelligenceLearningReceiptV1 {
                operation_id: claim.intent.operation_id,
                disposition: AgentdIntelligenceLearningDispositionV1::Indeterminate,
                evidence_digest,
                append: None,
            }));
        }

        let binding = claim.intent.final_use_binding();
        let signed = match self.grants.signed_grant(&binding) {
            Ok(value) => value,
            Err(error) if retryable_product_grant_error(&error) => {
                let evidence_digest = product_grant_error_digest(&error);
                self.operations
                    .release_not_dispatched(
                        &claim,
                        evidence_digest,
                        EXACT_OPERATION_RETRY_DELAY,
                    )
                    .await?;
                return Ok(Some(AgentdIntelligenceLearningReceiptV1 {
                    operation_id: claim.intent.operation_id,
                    disposition: AgentdIntelligenceLearningDispositionV1::Indeterminate,
                    evidence_digest,
                    append: None,
                }));
            }
            Err(error) => {
                let evidence_digest = product_grant_error_digest(&error);
                self.operations
                    .release_not_dispatched(
                        &claim,
                        evidence_digest,
                        EXACT_OPERATION_RETRY_DELAY,
                    )
                    .await?;
                return Err(error.into());
            }
        };
        let authorized = self
            .operations
            .authorize_dispatch(&self.authority, &signed, &claim)
            .await?;
        let observation = self
            .operations
            .execute_authorized(authorized, |_| {
                let applied = match self.writer.lock() {
                    Ok(mut writer) => {
                        apply_payload_current(&mut writer, &payload, validation_now)
                    }
                    Err(_) => ApplyObservation::Indeterminate(Digest32::of_bytes(
                        b"hepta.agentd.intelligence-learning.writer-poisoned.v1",
                    )),
                };
                match &applied {
                    ApplyObservation::Acknowledged(receipt) => DispatchEffect::Dispatched {
                        value: applied.clone(),
                        dispatch_digest: receipt.chain_digest,
                        acknowledgement_digest: Some(receipt.chain_digest),
                    },
                    ApplyObservation::Rejected(digest)
                    | ApplyObservation::Revoked(digest)
                    | ApplyObservation::Indeterminate(digest) => DispatchEffect::Indeterminate {
                        value: applied.clone(),
                        reason_digest: *digest,
                    },
                }
            })
            .await?;
        Ok(Some(
            self.settle_observation(scope_id, operation_id, observation)
                .await?,
        ))
    }

    /// Reconcile this exact unsettled operation. Destination equality is checked
    /// first. Only an absent exact event reaches current evidence and fresh
    /// final-use authority.
    pub async fn reconcile_operation_current(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1>
    {
        self.reconcile_operation_at(scope_id, operation_id, current_validation_time()?)
            .await
    }

    async fn reconcile_operation_at(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        validation_now: u64,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1>
    {
        let Some(record) = self.operations.operation(scope_id, operation_id).await? else {
            return Err(AgentdIntelligenceLearningErrorV1::Operation(
                DurableOperationError::Missing(operation_id.clone()),
            ));
        };
        if record.state.is_terminal() {
            return terminal_receipt(record).map(Some);
        }
        if record.state == DurableOperationState::Prepared {
            return self
                .dispatch_operation_at(scope_id, operation_id, validation_now)
                .await;
        }
        if !matches!(
            record.state,
            DurableOperationState::Dispatching
                | DurableOperationState::Dispatched
                | DurableOperationState::Indeterminate
        ) {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "exact operation reconciliation state",
            ));
        }

        let record = if record.intent.owner_generation == self.generation {
            record
        } else {
            self.operations
                .adopt_unsettled_generation(scope_id, operation_id, self.generation)
                .await?
        };
        let payload = self.load_payload(record.intent.payload_digest)?;
        validate_claim_payload(&record.intent, &payload)?;
        let observation = match self.writer.lock() {
            Ok(mut writer) => match observe_applied_payload(&writer, &payload) {
                Ok(Some(receipt)) => ApplyObservation::Acknowledged(receipt),
                Ok(None) => {
                    if let Some(failure) = validation_time_observation(&payload, validation_now) {
                        failure
                    } else {
                        let binding = record.intent.final_use_binding();
                        match self.grants.signed_grant(&binding) {
                            Ok(signed) => match claim_final_use(&self.authority, &signed, &binding) {
                                Ok(token) => match dispatch_final_use(
                                    &self.authority,
                                    token,
                                    &binding,
                                    || apply_payload_current(&mut writer, &payload, validation_now),
                                ) {
                                    Ok(result) => result,
                                    Err(error) => classify_authority_error(error),
                                },
                                Err(error) => classify_authority_error(error),
                            },
                            Err(error) if retryable_product_grant_error(&error) => {
                                ApplyObservation::Indeterminate(product_grant_error_digest(&error))
                            }
                            Err(error) => return Err(error.into()),
                        }
                    }
                }
                Err(error) => classify_apply(Err(error)),
            },
            Err(_) => ApplyObservation::Indeterminate(Digest32::of_bytes(
                b"hepta.agentd.intelligence-learning.writer-poisoned.v1",
            )),
        };
        Ok(Some(
            self.settle_observation(scope_id, operation_id, observation)
                .await?,
        ))
    }

    /// Advance and inspect one exact durable operation. This method never treats
    /// enqueue, another operation's dispatch, or transport acknowledgement as
    /// success. Only the requested operation's persisted terminal state closes
    /// this call.
    pub async fn settle_operation_current(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        maximum_steps: u32,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        if maximum_steps == 0 || maximum_steps > MAX_RECONCILE_BATCH {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "operation settlement steps",
            ));
        }
        for _ in 0..maximum_steps {
            let record = self
                .operations
                .operation(scope_id, operation_id)
                .await?
                .ok_or_else(|| {
                    AgentdIntelligenceLearningErrorV1::Operation(
                        DurableOperationError::Missing(operation_id.clone()),
                    )
                })?;
            if record.state.is_terminal() {
                return terminal_receipt(record);
            }
            let receipt = match record.state {
                DurableOperationState::Prepared => {
                    self.dispatch_operation_current(scope_id, operation_id).await?
                }
                DurableOperationState::Dispatching
                | DurableOperationState::Dispatched
                | DurableOperationState::Indeterminate => {
                    self.reconcile_operation_current(scope_id, operation_id)
                        .await?
                }
                DurableOperationState::Applied
                | DurableOperationState::NotApplied
                | DurableOperationState::Quarantined => unreachable!(),
            };
            if let Some(receipt) = receipt {
                if receipt.disposition
                    != AgentdIntelligenceLearningDispositionV1::Indeterminate
                {
                    return Ok(receipt);
                }
            }
        }

        if let Some(record) = self.operations.operation(scope_id, operation_id).await? {
            if record.state.is_terminal() {
                return terminal_receipt(record);
            }
        }
        let mut bytes = b"hepta.agentd.intelligence-learning-settlement-budget.v1\0".to_vec();
        push_id(&mut bytes, scope_id)?;
        push_id(&mut bytes, operation_id)?;
        bytes.extend_from_slice(&maximum_steps.to_be_bytes());
        Ok(AgentdIntelligenceLearningReceiptV1 {
            operation_id: operation_id.clone(),
            disposition: AgentdIntelligenceLearningDispositionV1::Indeterminate,
            evidence_digest: Digest32::of_bytes(&bytes),
            append: None,
        })
    }
}

fn apply_payload_current(
    writer: &mut LedgerWriter,
    payload: &PersistedLearningEnvelopeV1,
    validation_now: u64,
) -> ApplyObservation {
    if let Some(failure) = validation_time_observation(payload, validation_now) {
        return failure;
    }
    let mut current = payload.clone();
    match &mut current.payload {
        LearningPayloadV1::Decision(value) => value.now = validation_now,
        LearningPayloadV1::Outcome(value) => value.now = validation_now,
    }
    classify_apply(apply_payload(writer, &current))
}

fn validation_time_observation(
    payload: &PersistedLearningEnvelopeV1,
    validation_now: u64,
) -> Option<ApplyObservation> {
    let historical = match &payload.payload {
        LearningPayloadV1::Decision(value) => value.now,
        LearningPayloadV1::Outcome(value) => value.now,
    };
    if validation_now == 0 || historical == 0 || validation_now < historical {
        let mut bytes = b"hepta.agentd.intelligence-learning-clock-rollback.v1\0".to_vec();
        bytes.extend_from_slice(&historical.to_be_bytes());
        bytes.extend_from_slice(&validation_now.to_be_bytes());
        Some(ApplyObservation::Indeterminate(Digest32::of_bytes(&bytes)))
    } else {
        None
    }
}

fn observation_digest(observation: &ApplyObservation) -> Digest32 {
    match observation {
        ApplyObservation::Acknowledged(receipt) => receipt.chain_digest,
        ApplyObservation::Rejected(digest)
        | ApplyObservation::Revoked(digest)
        | ApplyObservation::Indeterminate(digest) => *digest,
    }
}

fn retryable_product_grant_error(error: &AgentdError) -> bool {
    matches!(error, AgentdError::Overloaded { .. } | AgentdError::Io(_))
}

fn product_grant_error_digest(error: &AgentdError) -> Digest32 {
    Digest32::of_bytes(
        format!("hepta.agentd.intelligence-learning-grant.v1:{error}").as_bytes(),
    )
}

fn terminal_receipt(
    record: codex_hepta_operations::DurableOperationRecord,
) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
    let evidence_digest = record.terminal_evidence_digest.ok_or(
        AgentdIntelligenceLearningErrorV1::Invalid("terminal operation evidence"),
    )?;
    let disposition = match record.state {
        DurableOperationState::Applied => AgentdIntelligenceLearningDispositionV1::Acknowledged,
        DurableOperationState::NotApplied => AgentdIntelligenceLearningDispositionV1::Rejected,
        DurableOperationState::Quarantined => AgentdIntelligenceLearningDispositionV1::Revoked,
        _ => {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "nonterminal operation settlement",
            ));
        }
    };
    Ok(AgentdIntelligenceLearningReceiptV1 {
        operation_id: record.intent.operation_id,
        disposition,
        evidence_digest,
        append: None,
    })
}

fn current_validation_time() -> Result<u64, AgentdIntelligenceLearningErrorV1> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdIntelligenceLearningErrorV1::Invalid("learning validation clock"))?
        .as_millis();
    u64::try_from(millis)
        .ok()
        .filter(|value| *value != 0)
        .ok_or(AgentdIntelligenceLearningErrorV1::Invalid(
            "learning validation clock",
        ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn product_validation_clock_is_current_and_nonzero() {
        assert!(current_validation_time().expect("clock") > 0);
    }
}

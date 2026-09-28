//! Current-time execution boundary for the durable intelligence learning host.
//!
//! Persisted payload time is historical admission metadata. It is never reused
//! as proof that evidence is still valid when a not-yet-applied Decision or
//! Outcome is first written after delay or restart. Destination-first recovery
//! remains special: an exact already-applied event is acknowledged as historical
//! fact before any new authority or current evidence is requested.

use super::*;

const GRANT_RETRY_DELAY: Duration = Duration::from_secs(1);

impl LearningPayloadV1 {
    fn historical_admission_time(&self) -> u64 {
        match self {
            Self::Decision(value) => value.now,
            Self::Outcome(value) => value.now,
        }
    }
}

impl AgentdIntelligenceLearningHostV1 {
    /// Dispatch one newly prepared operation using the caller's current trusted
    /// validation time. The immutable payload retains its historical admission
    /// time, but first application verifies evidence and appends at
    /// `validation_now`.
    pub(crate) async fn dispatch_next_at(
        &self,
        validation_now: u64,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1>
    {
        let Some(claim) = self
            .operations
            .claim_next(
                &self.destination,
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
        let binding = claim.intent.final_use_binding();
        let signed = match self.grants.signed_grant(&binding) {
            Ok(value) => value,
            Err(error) if retryable_grant_error(&error) => {
                let evidence_digest = grant_error_digest(&error);
                self.operations
                    .release_not_dispatched(&claim, evidence_digest, GRANT_RETRY_DELAY)
                    .await?;
                return Ok(Some(AgentdIntelligenceLearningReceiptV1 {
                    operation_id: claim.intent.operation_id,
                    disposition: AgentdIntelligenceLearningDispositionV1::Indeterminate,
                    evidence_digest,
                    append: None,
                }));
            }
            Err(error) => {
                let evidence_digest = grant_error_digest(&error);
                self.operations
                    .release_not_dispatched(&claim, evidence_digest, GRANT_RETRY_DELAY)
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
                let applied = validation_time_failure(&payload, validation_now).unwrap_or_else(|| {
                    match self.writer.lock() {
                        Ok(mut writer) => {
                            classify_apply(apply_payload_at(&mut writer, &payload, validation_now))
                        }
                        Err(_) => ApplyObservation::Indeterminate(Digest32::of_bytes(
                            b"hepta.agentd.intelligence-learning.writer-poisoned.v1",
                        )),
                    }
                });
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
            self.settle_observation(
                &claim.intent.scope_id,
                &claim.intent.operation_id,
                observation,
            )
            .await?,
        ))
    }

    /// Reconcile unsettled operations at a current trusted time. Exact
    /// destination equality is observed first and can acknowledge historical
    /// fact without renewing evidence. Only a missing destination event reaches
    /// fresh authority and current-time evidence validation.
    pub(crate) async fn reconcile_unsettled_at(
        &self,
        limit: u32,
        validation_now: u64,
    ) -> Result<Vec<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1> {
        if limit == 0 || limit > MAX_RECONCILE_BATCH {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "reconciliation limit",
            ));
        }
        let records = self
            .operations
            .unsettled_operations(&self.destination, limit)
            .await?;
        let mut receipts = Vec::with_capacity(records.len());
        for record in records {
            let record = if record.intent.owner_generation == self.generation {
                record
            } else {
                self.operations
                    .adopt_unsettled_generation(
                        &record.intent.scope_id,
                        &record.intent.operation_id,
                        self.generation,
                    )
                    .await?
            };
            let payload = self.load_payload(record.intent.payload_digest)?;
            validate_claim_payload(&record.intent, &payload)?;
            let observation = match self.writer.lock() {
                Ok(mut writer) => match observe_applied_payload(&writer, &payload) {
                    Ok(Some(receipt)) => ApplyObservation::Acknowledged(receipt),
                    Ok(None) => {
                        if let Some(failure) = validation_time_failure(&payload, validation_now) {
                            failure
                        } else {
                            let binding = record.intent.final_use_binding();
                            match self.grants.signed_grant(&binding) {
                                Ok(signed) => match claim_final_use(&self.authority, &signed, &binding) {
                                    Ok(token) => match dispatch_final_use(
                                        &self.authority,
                                        token,
                                        &binding,
                                        || {
                                            classify_apply(apply_payload_at(
                                                &mut writer,
                                                &payload,
                                                validation_now,
                                            ))
                                        },
                                    ) {
                                        Ok(result) => result,
                                        Err(error) => classify_authority_error(error),
                                    },
                                    Err(error) => classify_authority_error(error),
                                },
                                Err(error) if retryable_grant_error(&error) => {
                                    ApplyObservation::Indeterminate(grant_error_digest(&error))
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
            receipts.push(
                self.settle_observation(
                    &record.intent.scope_id,
                    &record.intent.operation_id,
                    observation,
                )
                .await?,
            );
        }
        Ok(receipts)
    }
}

fn validation_time_failure(
    payload: &PersistedLearningEnvelopeV1,
    validation_now: u64,
) -> Option<ApplyObservation> {
    let historical = payload.payload.historical_admission_time();
    if validation_now == 0 || historical == 0 || validation_now < historical {
        let mut bytes = b"hepta.agentd.intelligence-learning-clock-rollback.v1\0".to_vec();
        bytes.extend_from_slice(&historical.to_be_bytes());
        bytes.extend_from_slice(&validation_now.to_be_bytes());
        Some(ApplyObservation::Indeterminate(Digest32::of_bytes(&bytes)))
    } else {
        None
    }
}

fn apply_payload_at(
    writer: &mut LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
    validation_now: u64,
) -> Result<AppendReceipt, ProductionLedgerError> {
    match &envelope.payload {
        LearningPayloadV1::Decision(value) => {
            apply_decision_at(writer, value, validation_now)
        }
        LearningPayloadV1::Outcome(value) => apply_outcome_at(writer, value, validation_now),
    }
}

fn apply_decision_at(
    writer: &mut LedgerWriter,
    payload: &DecisionPayloadV1,
    validation_now: u64,
) -> Result<AppendReceipt, ProductionLedgerError> {
    let request = decision_request_from_payload(payload)?;
    let evidence = payload
        .evidence
        .to_typed(LearningEvidenceRoleV1::Generator)?;
    let current_binding =
        verify_decision_evidence_binding(writer, &request, &evidence, validation_now)?;
    if current_binding != payload.evidence_binding {
        return Err(ProductionLedgerError::Binding(
            "decision verified evidence drift",
        ));
    }
    writer.append_decision(
        ledger_digest(&payload.expected_ledger_predecessor)?,
        request,
        &evidence,
        validation_now,
    )
}

fn apply_outcome_at(
    writer: &mut LedgerWriter,
    payload: &OutcomePayloadV1,
    validation_now: u64,
) -> Result<AppendReceipt, ProductionLedgerError> {
    let decision_record_id = ledger_id(&payload.decision_record_id)?;
    let episode_id = ledger_id(&payload.episode_id)?;
    writer.verify_active_decision_binding(&decision_record_id, &episode_id)?;
    let expected_snapshot = ledger_digest(&payload.expected_run_snapshot_digest)?;
    let expected_candidate = ledger_id(&payload.selected_candidate_id)?;
    let records = writer.records()?;
    let decision_matches = records.iter().rev().any(|record| {
        matches!(
            &record.event,
            LedgerEvent::AuthenticatedDecisionV2(value)
                if value.record_id == decision_record_id
                    && value.episode_id == episode_id
                    && value.run_snapshot_digest == expected_snapshot
                    && value.selected_candidate_id == expected_candidate
        )
    });
    if !decision_matches {
        return Err(ProductionLedgerError::Binding(
            "outcome decision/candidate/snapshot",
        ));
    }
    let outcome = outcome_from_payload(payload)?;
    if outcome.episode_id != episode_id
        || outcome.support_digest != ledger_digest(&payload.physical_binding_digest)?
        || outcome.watermark.terminality != OutcomeTerminalityV1::Terminal
    {
        return Err(ProductionLedgerError::Binding(
            "outcome physical terminal binding",
        ));
    }
    let evidence = payload
        .evidence
        .to_typed(LearningEvidenceRoleV1::Observer)?;
    let current_binding =
        verify_outcome_evidence_binding(writer, &outcome, &evidence, validation_now)?;
    if current_binding != payload.evidence_binding {
        return Err(ProductionLedgerError::Binding(
            "outcome verified evidence drift",
        ));
    }
    writer.append_outcome(
        ledger_digest(&payload.expected_ledger_predecessor)?,
        outcome,
        &evidence,
        validation_now,
    )
}

fn retryable_grant_error(error: &AgentdError) -> bool {
    matches!(error, AgentdError::Overloaded { .. } | AgentdError::Io(_))
}

fn grant_error_digest(error: &AgentdError) -> Digest32 {
    Digest32::of_bytes(
        format!("hepta.agentd.intelligence-learning-grant.v1:{error}").as_bytes(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn historical_payload(now: u64) -> PersistedLearningEnvelopeV1 {
        PersistedLearningEnvelopeV1 {
            schema_version: LEARNING_PAYLOAD_SCHEMA_VERSION,
            owner_generation: 1,
            payload: LearningPayloadV1::Decision(DecisionPayloadV1 {
                expected_ledger_predecessor: "predecessor".to_string(),
                record_id: "run.clock".to_string(),
                episode_id: "episode.clock".to_string(),
                run_snapshot_digest: "snapshot".to_string(),
                objective_digest: "objective".to_string(),
                policy_digest: "policy".to_string(),
                candidate_ids: vec!["candidate.clock".to_string()],
                selected_candidate_id: "candidate.clock".to_string(),
                selected_propensity_raw: 1,
                completeness: CompletenessPayloadV1 {
                    set_id: "set.clock".to_string(),
                    state_digest: "state".to_string(),
                    generator_id: "generator".to_string(),
                    generator_code_digest: "code".to_string(),
                    grammar_digest: "grammar".to_string(),
                    hard_filter_digest: "filter".to_string(),
                    truncation_digest: "truncation".to_string(),
                    candidates_digest: "candidates".to_string(),
                    candidate_count: 1,
                    omitted_count_bound: 0,
                    canonical_order_digest: "order".to_string(),
                    complete_for_generator: true,
                },
                support_digest: "support".to_string(),
                decision_digest: "decision".to_string(),
                evidence: EvidencePayloadV1 {
                    evidence_id: "evidence.clock".to_string(),
                    principal_id: "principal.clock".to_string(),
                    role: "generator".to_string(),
                    trust_digest: "trust".to_string(),
                    scope_digest: "scope".to_string(),
                    objective_digest: "objective".to_string(),
                    authority_epoch: 1,
                    issued_at: 1,
                    expires_at: 2,
                    payload_digest: "payload".to_string(),
                    signature: vec![0; 64],
                },
                evidence_binding: VerifiedEvidenceBindingPayloadV1 {
                    principal_id: "principal.clock".to_string(),
                    controller_id: "controller.clock".to_string(),
                    credential_chain_digest: "credential".to_string(),
                    signing_key_digest: "key".to_string(),
                    scope_digest: "scope".to_string(),
                    authority_epoch: 1,
                    authentication_digest: "authentication".to_string(),
                },
                now,
            }),
        }
    }

    #[test]
    fn delayed_first_application_uses_current_validation_time() {
        assert!(validation_time_failure(&historical_payload(150), 201).is_none());
    }

    #[test]
    fn clock_rollback_is_indeterminate_not_success() {
        assert!(matches!(
            validation_time_failure(&historical_payload(150), 149),
            Some(ApplyObservation::Indeterminate(_))
        ));
    }
}

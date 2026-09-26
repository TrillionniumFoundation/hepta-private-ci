#!/usr/bin/env python3
"""Assert fresh final-use authority for product-learning restart replay."""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{path}: expected one learning reconcile target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = "codex-rs/hepta-agentd/src/intelligence_learning.rs"
    replace_once(
        path,
        "use codex_hepta_contracts::FinalUseAuthority;",
        '''use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_contracts::dispatch_final_use;''',
    )
    replace_once(
        path,
        "use codex_hepta_learning_ledger::AppendReceipt;",
        '''use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::AppendReceipt;''',
    )
    replace_once(
        path,
        '''    Operation(DurableOperationError),
    Ledger(ProductionLedgerError),''',
        '''    Operation(DurableOperationError),
    Authority(FinalUseError),
    Ledger(ProductionLedgerError),''',
    )
    replace_once(
        path,
        '''impl From<ProductionLedgerError> for AgentdIntelligenceLearningErrorV1 {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Ledger(value)
    }
}
''',
        '''impl From<ProductionLedgerError> for AgentdIntelligenceLearningErrorV1 {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Ledger(value)
    }
}

impl From<FinalUseError> for AgentdIntelligenceLearningErrorV1 {
    fn from(value: FinalUseError) -> Self {
        Self::Authority(value)
    }
}
''',
    )

    old_reconcile = '''    /// Reconcile dispatching/dispatched/indeterminate records after process
    /// restart. Exact payload replay is permitted because LedgerWriter enforces
    /// record identity, predecessor CAS and idempotent semantics.
    pub async fn reconcile_unsettled(
        &self,
        limit: u32,
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
                Ok(mut writer) => classify_apply(apply_payload(&mut writer, &payload)),
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
'''
    new_reconcile = '''    /// Reconcile dispatching/dispatched/indeterminate records after process
    /// restart. The destination is observed first. If the exact event is already
    /// present, the operation is acknowledged without consuming new authority.
    /// Otherwise the exact payload/original predecessor may be replayed only
    /// behind a fresh final-use grant for the adopted operation generation.
    pub async fn reconcile_unsettled(
        &self,
        limit: u32,
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
                        let binding = record.intent.final_use_binding();
                        let signed = self.grants.signed_grant(&binding)?;
                        match claim_final_use(&self.authority, &signed, &binding) {
                            Ok(token) => match dispatch_final_use(
                                &self.authority,
                                token,
                                &binding,
                                || apply_payload(&mut writer, &payload),
                            ) {
                                Ok(result) => classify_apply(result),
                                Err(error) => classify_authority_error(error),
                            },
                            Err(error) => classify_authority_error(error),
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
'''
    replace_once(path, old_reconcile, new_reconcile)

    replace_once(
        path,
        '''fn apply_payload(
    writer: &mut LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<AppendReceipt, ProductionLedgerError> {''',
        '''fn observe_applied_payload(
    writer: &LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<Option<AppendReceipt>, ProductionLedgerError> {
    let records = writer.records()?;
    let matched = records.iter().rev().find(|record| match &envelope.payload {
        LearningPayloadV1::Decision(payload) => {
            let Ok(record_id) = ledger_id(&payload.record_id) else {
                return false;
            };
            let Ok(episode_id) = ledger_id(&payload.episode_id) else {
                return false;
            };
            let Ok(run_snapshot_digest) = ledger_digest(&payload.run_snapshot_digest) else {
                return false;
            };
            let Ok(objective_digest) = ledger_digest(&payload.objective_digest) else {
                return false;
            };
            let Ok(policy_digest) = ledger_digest(&payload.policy_digest) else {
                return false;
            };
            let Ok(selected_candidate_id) = ledger_id(&payload.selected_candidate_id) else {
                return false;
            };
            let Ok(support_digest) = ledger_digest(&payload.support_digest) else {
                return false;
            };
            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(candidate_ids) = payload
                .candidate_ids
                .iter()
                .map(|value| ledger_id(value))
                .collect::<Result<Vec<_>, _>>()
            else {
                return false;
            };
            matches!(
                &record.event,
                LedgerEvent::AuthenticatedDecisionV2(value)
                    if value.record_id == record_id
                        && value.episode_id == episode_id
                        && value.run_snapshot_digest == run_snapshot_digest
                        && value.objective_digest == objective_digest
                        && value.policy_digest == policy_digest
                        && value.candidate_ids == candidate_ids
                        && value.selected_candidate_id == selected_candidate_id
                        && value.selected_propensity.raw() == payload.selected_propensity_raw
                        && value.completeness == completeness
                        && value.support_digest == support_digest
            )
        }
        LearningPayloadV1::Outcome(payload) => {
            let Ok(expected) = payload.outcome.to_typed() else {
                return false;
            };
            matches!(
                &record.event,
                LedgerEvent::AuthenticatedOutcomeV2(value) if value == &expected
            )
        }
    });
    Ok(matched.map(|record| AppendReceipt {
        disposition: AppendDisposition::IdempotentReplay,
        sequence: record.sequence,
        event_digest: record.event_digest,
        chain_digest: record.chain_digest,
    }))
}

fn apply_payload(
    writer: &mut LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<AppendReceipt, ProductionLedgerError> {''',
    )
    replace_once(
        path,
        '''fn classify_apply(result: Result<AppendReceipt, ProductionLedgerError>) -> ApplyObservation {
    match result {''',
        '''fn classify_authority_error(error: FinalUseError) -> ApplyObservation {
    let digest = Digest32::of_bytes(
        format!("hepta.agentd.intelligence-learning-authority.v1:{error:?}").as_bytes(),
    );
    match error {
        FinalUseError::Revoked
        | FinalUseError::EpochMismatch
        | FinalUseError::StaleRevocationHead
        | FinalUseError::Expired => ApplyObservation::Revoked(digest),
        FinalUseError::InvalidGrant
        | FinalUseError::InvalidTrust
        | FinalUseError::AntiRollbackViolation
        | FinalUseError::InvalidSignature
        | FinalUseError::BindingMismatch
        | FinalUseError::NotYetValid => ApplyObservation::Rejected(digest),
        FinalUseError::AlreadyClaimed
        | FinalUseError::CapacityExceeded
        | FinalUseError::DispatchInProgress
        | FinalUseError::Unavailable
        | FinalUseError::UnsafeStateDirectory
        | FinalUseError::StateLocked => ApplyObservation::Indeterminate(digest),
    }
}

fn classify_apply(result: Result<AppendReceipt, ProductionLedgerError>) -> ApplyObservation {
    match result {''',
    )


if __name__ == "__main__":
    main()

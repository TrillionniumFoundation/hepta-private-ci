//! Typed application receipt retirement in the original append-only journal.

use super::*;
use crate::ProductionRetirementAck;
use crate::production_writer::RecordedRetirementAck;

pub(super) const RETIREMENT_ACK_KIND: &str = "retirement_acknowledged";

fn checked_terminal_destination(
    topic: &str,
    payload: &str,
    terminal: &str,
) -> Result<String, LocalLeaseOutboxError> {
    let value: serde_json::Value = serde_json::from_str(payload)
        .map_err(|_| corrupt("retirement original payload is invalid"))?;
    let target = value
        .get("target")
        .ok_or_else(|| corrupt("retirement payload has no target"))?;
    let (outcome, destination) = match topic {
        crate::NOTES_REPLACE_TOPIC_V1 => {
            let checked =
                crate::production_notes::NotesTerminalReceipt::from_json(payload, terminal)
                    .map_err(LocalLeaseOutboxError::Invalid)?;
            let target: crate::NotesTargetIdentity = serde_json::from_value(target.clone())
                .map_err(|_| corrupt("retirement Notes target is invalid"))?;
            (checked.outcome(), target.destination_id())
        }
        crate::CALCULATOR_EVALUATE_TOPIC_V1 => {
            let checked = crate::production_calculator::CalculatorTerminalReceipt::from_json(
                payload, terminal,
            )
            .map_err(LocalLeaseOutboxError::Invalid)?;
            let target: crate::CalculatorTargetIdentity = serde_json::from_value(target.clone())
                .map_err(|_| corrupt("retirement Calculator target is invalid"))?;
            (checked.outcome(), target.destination_id())
        }
        _ => return Err(corrupt("retirement ACK targets another topic")),
    };
    if outcome != LocalReconcileOutcome::Committed {
        return Err(corrupt("retirement ACK has no applied original terminal"));
    }
    Ok(destination)
}

fn checked_record(
    event: &EventRow,
    outbox: &OutboxRow,
    terminal: &EventRow,
) -> Result<RecordedRetirementAck, LocalLeaseOutboxError> {
    let record: RecordedRetirementAck = serde_json::from_str(&event.payload_json)
        .map_err(|_| corrupt("invalid typed retirement ACK event"))?;
    let destination =
        checked_terminal_destination(&outbox.topic, &outbox.payload_json, &terminal.payload_json)?;
    if record.schema_version != 1
        || record.operation_id != event.occurrence_key
        || record.operation_id != outbox.occurrence_key
        || record.destination_id != destination
        || record.topic != outbox.topic
        || record.payload_sha256 != outbox.payload_sha256
        || record.terminal_receipt_sha256 != terminal.payload_sha256
        || terminal.kind != "reconcile_committed"
        || event.sequence <= terminal.sequence
        || event.generation < terminal.generation
        || (event.generation == terminal.generation
            && event.fencing_token != terminal.fencing_token)
    {
        return Err(corrupt(
            "retirement ACK differs from the original committed operation",
        ));
    }
    Ok(record)
}

/// Full-chain replay must reject a neutral metadata event with a fabricated or
/// foreign application binding, even though it leaves Committed unchanged.
pub(super) fn verify_retirement_pairing(
    events: &[EventRow],
    outboxes: &[OutboxRow],
) -> Result<(), LocalLeaseOutboxError> {
    for event in events
        .iter()
        .filter(|event| event.kind == RETIREMENT_ACK_KIND)
    {
        let outbox = outboxes
            .iter()
            .find(|row| row.occurrence_key == event.occurrence_key)
            .ok_or_else(|| corrupt("retirement ACK has no original outbox"))?;
        let terminal = events
            .iter()
            .find(|row| {
                row.occurrence_key == event.occurrence_key && row.kind == "reconcile_committed"
            })
            .ok_or_else(|| corrupt("retirement ACK has no original terminal"))?;
        checked_record(event, outbox, terminal)?;
    }
    Ok(())
}

pub(super) fn verify_retirement_lease(
    lease_id: &str,
    events: &[EventRow],
) -> Result<(), LocalLeaseOutboxError> {
    for event in events
        .iter()
        .filter(|event| event.kind == RETIREMENT_ACK_KIND)
    {
        let record: RecordedRetirementAck = serde_json::from_str(&event.payload_json)
            .map_err(|_| corrupt("invalid typed retirement ACK event"))?;
        if record.lease_id != lease_id {
            return Err(corrupt("retirement ACK targets another source lease"));
        }
    }
    Ok(())
}

impl LocalLeaseOutbox {
    pub(crate) async fn retained_application_retirement_ack_transaction(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        operation_id: &str,
        topic: &str,
    ) -> Result<Option<RecordedRetirementAck>, LocalLeaseOutboxError> {
        validate_text(operation_id, "operation id", /*max_bytes*/ 512)?;
        self.require_current_transaction(transaction).await?;
        let admission = find_admission(
            transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("retirement has no original operation admission"))?;
        let outbox = find_outbox(
            transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("retirement admission has no original outbox"))?;
        let stored = find_operation(transaction, operation_id)
            .await?
            .ok_or_else(|| corrupt("retirement admission has no original operation"))?;
        let operation = verify_operation_row_incremental(
            &stored,
            &self.lease_id,
            &self.owner_agent_id,
            &admission,
            &outbox,
        )?;
        if outbox.topic != topic {
            return Err(corrupt(
                "retirement observation targets another application",
            ));
        }
        ensure_occurrence_readable(transaction, self, &admission, &outbox).await?;
        let events = verify_event_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outboxes =
            verify_outbox_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outboxes)?;
        if current_outcome(
            transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?
            != LocalOutcomeState::Committed
        {
            return Err(LocalLeaseOutboxError::IllegalTransition(
                "retirement observation requires the original Committed operation".into(),
            ));
        }
        let terminal = find_transition(
            transaction,
            &self.lease_id,
            operation_id,
            "reconcile_committed",
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("retirement original terminal disappeared"))?;
        let destination =
            checked_terminal_destination(topic, &outbox.payload_json, &terminal.payload_json)?;
        if operation.destination_id().as_str() != destination {
            return Err(corrupt(
                "retirement target differs from original operation destination",
            ));
        }
        let Some(event) = find_transition(
            transaction,
            &self.lease_id,
            operation_id,
            RETIREMENT_ACK_KIND,
            &self.owner_agent_id,
        )
        .await?
        else {
            return Ok(None);
        };
        let record = checked_record(&event, &outbox, &terminal)?;
        if record.lease_id != self.lease_id {
            return Err(corrupt("retirement ACK belongs to another source lease"));
        }
        Ok(Some(record))
    }

    pub(crate) async fn record_application_retirement_ack(
        &self,
        acknowledgement: &ProductionRetirementAck,
        live_check: impl Fn() -> Result<(), String>,
    ) -> Result<(), LocalLeaseOutboxError> {
        let record = acknowledgement.record();
        if record.lease_id != self.lease_id {
            return Err(LocalLeaseOutboxError::AccessDenied(
                "retirement ACK belongs to another writer".into(),
            ));
        }
        // This is the original guarded writable pool. Managed checkout first
        // durably invalidates Current; the lock-only barrier is never upgraded.
        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let existing = self
            .retained_application_retirement_ack_transaction(
                &mut transaction,
                &record.operation_id,
                &record.topic,
            )
            .await?;
        if let Some(existing) = existing {
            if existing != *record {
                return Err(corrupt("retirement replay changed its source binding"));
            }
            transaction
                .rollback()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(());
        }
        let outbox = find_outbox(
            &mut transaction,
            &self.lease_id,
            &record.operation_id,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("retirement original outbox disappeared"))?;
        let terminal = find_transition(
            &mut transaction,
            &self.lease_id,
            &record.operation_id,
            "reconcile_committed",
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("retirement original terminal disappeared"))?;
        let destination = checked_terminal_destination(
            &outbox.topic,
            &outbox.payload_json,
            &terminal.payload_json,
        )?;
        if record.schema_version != 1
            || record.destination_id != destination
            || record.payload_sha256 != outbox.payload_sha256
            || record.terminal_receipt_sha256 != terminal.payload_sha256
        {
            return Err(corrupt(
                "validated target ACK changed before its source COMMIT",
            ));
        }
        let payload = serde_json::to_string(record)
            .map_err(|error| LocalLeaseOutboxError::Invalid(error.to_string()))?;
        let payload_sha256 = Sha256Digest::for_bytes(payload.as_bytes());
        let sequence = next_event_sequence(&mut transaction, &self.lease_id).await?;
        let previous = event_head(&mut transaction, &self.lease_id).await?;
        let event_id = journal_row_id("event", &self.lease_id, sequence);
        let digest = event_digest(
            &self.lease_id,
            sequence,
            &event_id,
            &record.operation_id,
            &self.owner_agent_id,
            self.generation,
            &self.fencing_token,
            RETIREMENT_ACK_KIND,
            &payload_sha256,
            &previous,
        );
        insert_event(
            &mut transaction,
            EventInsert {
                lease_id: &self.lease_id,
                sequence,
                event_id: &event_id,
                occurrence_key: &record.operation_id,
                owner: &self.owner_agent_id,
                generation: self.generation,
                fencing_token: &self.fencing_token,
                kind: RETIREMENT_ACK_KIND,
                payload_json: &payload,
                payload_sha256: &payload_sha256,
                previous_sha256: &previous,
                event_sha256: &digest,
            },
        )
        .await?;
        live_check().map_err(LocalLeaseOutboxError::AccessDenied)?;
        self.require_current_transaction(&mut transaction).await?;
        live_check().map_err(LocalLeaseOutboxError::AccessDenied)?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(())
    }
}

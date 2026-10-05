//! Compatible imports/exports for retained V1 operation metadata.
//! An import never becomes admission authority and never overwrites live work.
use crate::canonical::{
    CanonicalLimits, EmptyText, MAX_SAFE_INTEGER, assert_canonical_text, assert_sha256,
    assert_stable_identifier, canonical_json, safe_integer,
};
use crate::error::{ControlError, ErrorCode};
use crate::ledger::{Entry, OperationLedger, OperationState, RequestEnvelope};
use serde_json::{Value, json};
use std::collections::BTreeMap;

const SCHEMA: &str = "hepta.ui-control.recovery-state.v1";
const REQUEST_FIELDS: [&str; 12] = [
    "protocolVersion",
    "method",
    "operationId",
    "semanticDigest",
    "action",
    "targetId",
    "reason",
    "sessionId",
    "connectionGeneration",
    "generation",
    "displayedRevision",
    "snapshotDigest",
];

impl OperationLedger {
    pub fn export_recovery(&self) -> Value {
        json!({"schema": SCHEMA, "operations": self.pending.values()
            .filter(|entry| entry.identity_id == self.identity_id).map(Entry::recovery_value).collect::<Vec<_>>()})
    }

    pub fn restore_recovery(&mut self, state: &Value) -> Result<(), ControlError> {
        if state.get("schema").and_then(Value::as_str) != Some(SCHEMA) {
            return Err(ControlError::invalid());
        }
        let records = state
            .get("operations")
            .and_then(Value::as_array)
            .ok_or_else(ControlError::invalid)?;
        if records.len() > self.max_pending {
            return Err(ControlError::new(ErrorCode::PendingLimit));
        }
        canonical_json(
            state,
            &CanonicalLimits {
                max_array_length: self.max_pending,
                max_entries: 20 * self.max_pending + 4,
                max_encoded_bytes: 8192 * self.max_pending,
                ..CanonicalLimits::default()
            },
        )?;
        let mut restored = BTreeMap::new();
        for record in records {
            let entry = decode_record(record, self.identity_id.clone())?;
            let id = entry.request.operation_id.clone();
            if restored.insert(id, entry).is_some() {
                return Err(ControlError::invalid());
            }
        }
        // Validate the entire merge before changing any retained record.
        let mut additional = 0;
        for (id, entry) in &restored {
            if let Some(prior) = self.pending.get(id).or_else(|| self.completed.get(id)) {
                if prior.identity_id != entry.identity_id || prior.request != entry.request {
                    return Err(ControlError::new(ErrorCode::OperationConflict));
                }
            } else {
                additional += 1;
            }
        }
        if self.pending.len() + additional > self.max_pending {
            return Err(ControlError::new(ErrorCode::PendingLimit));
        }
        for (id, entry) in restored {
            if !self.completed.contains_key(&id) {
                self.pending.entry(id).or_insert(entry);
            }
        }
        Ok(())
    }
}

fn decode_record(record: &Value, identity_id: Option<String>) -> Result<Entry, ControlError> {
    let fields = record.as_object().ok_or_else(ControlError::invalid)?;
    let mut request_value: serde_json::Map<_, _> = REQUEST_FIELDS
        .into_iter()
        .map(|key| {
            Ok((
                key.to_owned(),
                fields.get(key).ok_or_else(ControlError::invalid)?.clone(),
            ))
        })
        .collect::<Result<_, ControlError>>()?;
    // JavaScript has one Number type: integer-valued decimal JSON must preserve its value.
    for key in ["connectionGeneration", "generation", "displayedRevision"] {
        let value = safe_integer(
            request_value.get(key).ok_or_else(ControlError::invalid)?,
            1,
            MAX_SAFE_INTEGER,
        )?;
        request_value.insert(key.to_owned(), json!(value));
    }
    let request: RequestEnvelope = serde_json::from_value(Value::Object(request_value))
        .map_err(|_| ControlError::invalid())?;
    assert_canonical_text(&request.protocol_version, 128, EmptyText::Forbidden)?;
    assert_canonical_text(&request.method, 64, EmptyText::Forbidden)?;
    assert_canonical_text(&request.action, 64, EmptyText::Forbidden)?;
    assert_canonical_text(&request.reason, 1024, EmptyText::Forbidden)?;
    for id in [
        &request.operation_id,
        &request.target_id,
        &request.session_id,
    ] {
        assert_stable_identifier(id)?;
    }
    for digest in [&request.semantic_digest, &request.snapshot_digest] {
        assert_sha256(digest)?;
    }
    for value in [
        request.connection_generation,
        request.generation,
        request.displayed_revision,
    ] {
        if value == 0 || value > MAX_SAFE_INTEGER as u64 {
            return Err(ControlError::invalid());
        }
    }
    let timestamp = |name: &str| -> Result<u64, ControlError> {
        Ok(safe_integer(
            fields.get(name).ok_or_else(ControlError::invalid)?,
            1,
            MAX_SAFE_INTEGER,
        )? as u64)
    };
    let audit_trace_id = match fields.get("auditTraceId") {
        None | Some(Value::Null) => None,
        Some(Value::String(id)) => {
            assert_stable_identifier(id)?;
            Some(id.clone())
        }
        Some(_) => return Err(ControlError::invalid()),
    };
    Ok(Entry {
        identity_id,
        reservation: 0,
        request,
        state: OperationState::Indeterminate,
        created_at: timestamp("createdAt")?,
        updated_at: timestamp("updatedAt")?,
        audit_trace_id,
        terminal_status: None,
        outcome_digest: None,
    })
}

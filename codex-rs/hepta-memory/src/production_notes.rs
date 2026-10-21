//! Exact Notes document mutations through the existing production outbox.
//!
//! A document receipt proves an application-model update, not durable source
//! publication or compositor presentation. This destination owns no authority,
//! operation ledger, reconnect policy, or default runtime registration.

use std::sync::Arc;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::FinalUseProductionOutboxTarget;
use crate::ProductionDispatchFuture;
use crate::ProductionDispatchRequest;
use crate::ProductionOutboxTarget;
use crate::ProductionTargetOutcome;
use crate::ProductionTerminalObservation;
use crate::ProductionTerminalObservationFuture;

pub const NOTES_REPLACE_TOPIC_V1: &str = "trill.notes.replace.v1";
pub const NOTES_REQUEST_MAX_BYTES: usize = 8192;
pub const NOTES_RESPONSE_MAX_BYTES: usize = 2048;

/// A Session-created application incarnation, supplied by trusted bootstrap.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NotesTargetIdentity {
    pub session_instance: String,
    pub task_id: u64,
    pub incarnation: String,
}

impl NotesTargetIdentity {
    pub fn validate(&self) -> Result<(), String> {
        if self.task_id == 0
            || !lower_hex(&self.session_instance, 32)
            || !lower_hex(&self.incarnation, 32)
        {
            return Err("invalid Notes application identity".to_string());
        }
        Ok(())
    }

    pub fn destination_id(&self) -> String {
        format!("trill.notes:{}:{}:{}", self.session_instance, self.task_id, self.incarnation)
    }

    pub fn scope_digest(&self) -> Digest32 {
        Digest32::of_bytes(format!("trill.notes.scope.v1\0{}\0{}\0{}", self.session_instance, self.task_id, self.incarnation).as_bytes())
    }

    pub fn predecessor_digest(&self, revision: u64) -> Digest32 {
        Digest32::of_bytes(format!("trill.notes.predecessor.v1\0{}\0{}\0{}\0{}", self.session_instance, self.task_id, self.incarnation, revision).as_bytes())
    }
}

/// An already-private, inherited application channel. Implementations perform
/// the exact write and bounded response read synchronously, without reconnect,
/// replay, detached work, or retaining borrowed request bytes. `invalidate`
/// permanently closes an ambiguous stream so late replies cannot be reused.
pub trait NotesPrivateChannel: Send + Sync {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String>;
    fn invalidate(&self);
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NotesReplace {
    schema_version: u16,
    action: ReplaceAction,
    operation_id: String,
    destination_id: String,
    target: NotesTargetIdentity,
    expected_revision: u64,
    text: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum ReplaceAction {
    ReplaceNote,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NotesResponse {
    schema_version: u16,
    target: NotesTargetIdentity,
    operation_id: String,
    payload_sha256: String,
    result: NotesResult,
}

#[derive(Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
enum NotesResult {
    Applied { previous_revision: u64, revision: u64, text_sha256: String },
    NotApplied { reason: NotAppliedReason, current_revision: u64 },
    Unknown { current_revision: u64 },
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum NotAppliedReason {
    RevisionConflict,
    OperationConflict,
    RevisionExhausted,
    TargetMismatch,
    UiDeadlineElapsed,
}

#[derive(Serialize)]
struct NotesObserve<'a> {
    schema_version: u16,
    action: &'static str,
    target: &'a NotesTargetIdentity,
    operation_id: &'a str,
    payload_sha256: &'a str,
}

/// Parse once to produce the original authority-free intent. The caller must
/// persist this intent and the same payload bytes with `prepare_operation`.
pub fn notes_operation_intent(
    target: &NotesTargetIdentity,
    payload: &str,
    subject: StableId,
    policy_generation: Generation,
) -> Result<OperationIntentV1, String> {
    let parsed = parse_replace(target, payload)?;
    OperationIntentV1::new(
        StableId::new(parsed.operation_id).map_err(|error| error.to_string())?,
        subject,
        StableId::new(target.destination_id()).map_err(|error| error.to_string())?,
        Digest32::of_bytes(payload.as_bytes()),
        target.scope_digest(),
        policy_generation,
        Some(target.predecessor_digest(parsed.expected_revision)),
    ).map_err(|error| error.to_string())
}

fn parse_replace(target: &NotesTargetIdentity, raw: &str) -> Result<NotesReplace, String> {
    if raw.is_empty() || raw.len() > NOTES_REQUEST_MAX_BYTES {
        return Err("Notes request exceeds its bound".to_string());
    }
    let parsed: NotesReplace = serde_json::from_str(raw).map_err(|_| "invalid Notes request schema")?;
    target.validate()?;
    if parsed.schema_version != 1 || !matches!(parsed.action, ReplaceAction::ReplaceNote)
        || parsed.target != *target || parsed.destination_id != target.destination_id()
        || parsed.text.len() > 4096 || StableId::new(&parsed.operation_id).is_err()
    {
        return Err("Notes request does not match the application".to_string());
    }
    Ok(parsed)
}

/// Explicitly attached destination for one Notes application incarnation.
pub struct ProductionNotesTarget {
    identity: NotesTargetIdentity,
    destination: String,
    channel: Arc<dyn NotesPrivateChannel>,
}

impl ProductionNotesTarget {
    pub fn new(identity: NotesTargetIdentity, channel: Arc<dyn NotesPrivateChannel>) -> Result<Self, String> {
        identity.validate()?;
        Ok(Self { destination: identity.destination_id(), identity, channel })
    }

    fn decode(&self, request: &ProductionDispatchRequest) -> Result<NotesReplace, String> {
        let parsed = parse_replace(&self.identity, &request.payload_json)?;
        let intent = notes_operation_intent(&self.identity, &request.payload_json,
            StableId::new(&request.operation_subject_id).map_err(|error| error.to_string())?,
            Generation::new(request.operation_policy_generation).map_err(|error| error.to_string())?)?;
        let predecessor = self.identity.predecessor_digest(parsed.expected_revision).to_string();
        if request.schema_version != crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || request.namespace != crate::PRODUCTION_DURABLE_WRITER_NAMESPACE
            || request.topic != NOTES_REPLACE_TOPIC_V1
            || request.operation_destination_id != self.destination
            || request.occurrence_key != parsed.operation_id
            || request.idempotency_key != parsed.operation_id
            || request.payload_sha256 != Sha256Digest::for_bytes(request.payload_json.as_bytes())
            || request.operation_scope_sha256.as_str() != intent.scope_digest().to_string()
            || request.operation_semantic_sha256.as_str() != intent.semantic_digest().to_string()
            || request.expected_predecessor_sha256.as_ref().map(Sha256Digest::as_str)
                != Some(predecessor.as_str())
        {
            return Err("Notes request differs from the original durable operation".to_string());
        }
        Ok(parsed)
    }

    fn response(&self, bytes: Vec<u8>, request: &NotesReplace, digest: &str) -> Result<(NotesResult, String), String> {
        if bytes.is_empty() || bytes.len() > NOTES_RESPONSE_MAX_BYTES {
            return Err("Notes response exceeds its bound".to_string());
        }
        let response: NotesResponse = serde_json::from_slice(&bytes).map_err(|_| "invalid Notes response schema")?;
        if response.schema_version != 1 || response.target != self.identity
            || response.operation_id != request.operation_id || response.payload_sha256 != digest
        {
            return Err("Notes response identity mismatch".to_string());
        }
        if let NotesResult::Applied { previous_revision, revision, text_sha256 } = &response.result
            && (*previous_revision != request.expected_revision
                || previous_revision.checked_add(1) != Some(*revision)
                || *text_sha256 != Sha256Digest::for_bytes(request.text.as_bytes()).as_str())
        {
            return Err("Notes response does not prove the requested document mutation".to_string());
        }
        let receipt = String::from_utf8(bytes).map_err(|_| "Notes response is not UTF-8")?;
        Ok((response.result, receipt))
    }
}

impl ProductionOutboxTarget for ProductionNotesTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        // This entire exchange happens in the original synchronous FinalUse
        // consumer entry. Constructing an unpolled future cannot defer effect.
        let outcome = match self.decode(&request) {
            Err(reason) => ProductionTargetOutcome::Rejected { reason },
            Ok(parsed) => match self.channel.exchange(request.payload_json.as_bytes())
                .and_then(|bytes| self.response(bytes, &parsed, request.payload_sha256.as_str())) {
                Ok((NotesResult::Applied { .. }, receipt)) => ProductionTargetOutcome::Committed { receipt },
                Ok((NotesResult::NotApplied { reason, current_revision }, receipt)) => {
                    let _ = (reason, current_revision);
                    ProductionTargetOutcome::NotApplied { reason: receipt }
                }
                Ok((NotesResult::Unknown { current_revision }, _)) => {
                    self.channel.invalidate();
                    ProductionTargetOutcome::Indeterminate { reason: format!("Notes receipt unavailable at revision {current_revision}") }
                }
                Err(reason) => { self.channel.invalidate(); ProductionTargetOutcome::Indeterminate { reason } }
            },
        };
        Box::pin(async move { outcome })
    }
}

impl FinalUseProductionOutboxTarget for ProductionNotesTarget {
    fn destination_id(&self) -> &str { &self.destination }

    fn observe_terminal<'a>(&'a self, request: &'a ProductionDispatchRequest) -> ProductionTerminalObservationFuture<'a> {
        let observation = match self.decode(request) {
            Err(reason) => ProductionTerminalObservation::Unavailable { reason },
            Ok(parsed) => {
                let query = NotesObserve { schema_version: 1, action: "observe", target: &self.identity,
                    operation_id: &parsed.operation_id, payload_sha256: request.payload_sha256.as_str() };
                let result = serde_json::to_vec(&query).map_err(|error| error.to_string())
                    .and_then(|bytes| self.channel.exchange(&bytes))
                    .and_then(|bytes| self.response(bytes, &parsed, request.payload_sha256.as_str()));
                match result {
                    Ok((NotesResult::Applied { .. }, receipt)) => ProductionTerminalObservation::Applied { receipt },
                    Ok((NotesResult::Unknown { .. } | NotesResult::NotApplied { .. }, _)) =>
                        ProductionTerminalObservation::Indeterminate { reason: "Notes has no retained receipt for this exact operation".to_string() },
                    Err(reason) => { self.channel.invalidate(); ProductionTerminalObservation::Unavailable { reason } }
                }
            }
        };
        Box::pin(async move { observation })
    }
}

fn lower_hex(value: &str, length: usize) -> bool {
    value.len() == length && value.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

#[cfg(test)]
#[path = "production_notes_tests.rs"]
mod tests;

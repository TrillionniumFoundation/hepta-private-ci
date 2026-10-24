//! The original Notes payload validator and writer own preparation semantics.
//! This stage is shared with original-owner tests; it grants no dispatch right.

use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::NOTES_REPLACE_TOPIC_V1;
use codex_hepta_memory::NotesDocumentState;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::notes_operation_intent;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde_json::json;

use crate::AgentdError;
use crate::notes_literal_adapter::invalid;

pub(crate) struct LiteralOperationInput<'a> {
    pub target: &'a NotesTargetIdentity,
    pub observed: &'a NotesDocumentState,
    pub run_id: &'a str,
    pub text: &'a str,
    pub subject: &'a str,
    pub policy_generation: Generation,
}

pub(crate) async fn prepare_original_literal(
    writer: &ProductionDurableWriter,
    input: LiteralOperationInput<'_>,
) -> Result<Digest32, AgentdError> {
    if input.observed.target != *input.target || input.observed.receipt_pending
        || input.text.trim().is_empty() || input.text.len() > 4096
        || writer.owner_agent_id().as_str() != input.subject
    {
        return Err(invalid("Notes predecessor, pending receipt, text or original subject is invalid"));
    }
    let payload = serde_json::to_string(&json!({
        "schema_version":1, "action":"replace_note", "operation_id":input.run_id,
        "destination_id":input.target.destination_id(), "target":input.target,
        "expected_revision":input.observed.revision, "text":input.text,
    }))?;
    let operation = notes_operation_intent(
        input.target, &payload, StableId::new(input.subject).map_err(|error| invalid(&error.to_string()))?,
        input.policy_generation,
    ).map_err(AgentdError::Invalid)?;
    writer.prepare_operation(operation.clone(), NOTES_REPLACE_TOPIC_V1, payload.clone()).await?;
    let retained = writer.retained_operation(input.run_id).await?
        .ok_or_else(|| invalid("original Notes preparation was not retained"))?;
    if retained.operation != operation || retained.topic != NOTES_REPLACE_TOPIC_V1
        || retained.payload_json != payload || retained.state != LocalOutcomeState::Queued
    {
        return Err(invalid("original Notes preparation is different or already entered execution"));
    }
    Ok(operation.semantic_digest())
}

pub(crate) fn utc_millis(milliseconds: u64) -> Result<String, AgentdError> {
    let seconds = libc::time_t::try_from(milliseconds / 1_000)
        .map_err(|_| invalid("protected time exceeds UTC conversion bound"))?;
    let mut output = std::mem::MaybeUninit::<libc::tm>::uninit();
    // SAFETY: both pointers refer to live correctly sized objects. The output
    // is read only after gmtime_r reports successful initialization.
    let output = unsafe {
        if libc::gmtime_r(&seconds, output.as_mut_ptr()).is_null() {
            return Err(invalid("protected time conversion failed"));
        }
        output.assume_init()
    };
    if !(70..=8099).contains(&output.tm_year) {
        return Err(invalid("protected UTC year outside admitted profile"));
    }
    Ok(format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z", output.tm_year + 1900,
        output.tm_mon + 1, output.tm_mday, output.tm_hour, output.tm_min, output.tm_sec,
        milliseconds % 1_000))
}

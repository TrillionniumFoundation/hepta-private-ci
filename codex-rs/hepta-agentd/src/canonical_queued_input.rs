//! Derive one exact queue input from the original signed Objective journal.
//! These values correlate owners; they grant no execution authority and own
//! neither a queue nor a second record of delivery or operation outcomes.

use std::fmt;
use std::str::FromStr;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_context_compiler::ContextItem;
use codex_hepta_context_compiler::ContextRole;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_protocol::ThreadId;
use codex_protocol::user_input::UserInput;
use codex_protocol::user_input::user_input_payload_sha256;

use crate::AgentdIdentity;
use crate::AuthBusObjectiveBody;
use crate::NativeContextBindingV1;
use crate::NativeContextMaterialV1;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::RunSnapshot;

#[derive(Clone, Eq, PartialEq)]
pub(crate) struct CanonicalQueuedInputV1 {
    pub(crate) thread_id: String,
    pub(crate) client_user_message_id: String,
    pub(crate) input_payload_sha256: String,
    pub(crate) text: String,
    pub(crate) run_id: String,
    pub(crate) signed_body_digest: Digest32,
}

impl fmt::Debug for CanonicalQueuedInputV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CanonicalQueuedInputV1")
            .field("thread_id", &self.thread_id)
            .field("client_user_message_id", &self.client_user_message_id)
            .field("input_payload_sha256", &self.input_payload_sha256)
            .field("run_id", &self.run_id)
            .field("signed_body_digest", &self.signed_body_digest)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CanonicalQueuedRunV1 {
    pub(crate) input: CanonicalQueuedInputV1,
    pub(crate) context: NativeContextBindingV1,
}

fn signed_body(record: &RunStartRecordV1) -> Result<AuthBusObjectiveBody> {
    let payload = record
        .authenticated_payload
        .as_deref()
        .context("original RunStart has no authenticated queued input bytes")?;
    ensure!(
        !payload.is_empty()
            && payload.len() <= 48 * 1024
            && Digest32::of_bytes(payload) == record.authentication.signed_body_digest,
        "original authenticated input bytes or digest differ"
    );
    let body: AuthBusObjectiveBody = serde_json::from_slice(payload)?;
    ensure!(
        serde_json::to_vec(&body)? == payload,
        "original queued input is not the exact typed signed body"
    );
    ensure!(
        body.run_id == record.snapshot.run_id.as_str()
            && body.authority_epoch == record.snapshot.authority_epoch
            && Digest32::from_str(&body.runtime_body_digest)? == record.runtime_body_digest
            && Digest32::from_str(&body.preference_state_digest)?
                == record.snapshot.preference_state_digest
            && Digest32::from_str(&body.model_tuple_digest)? == record.snapshot.model_tuple_digest
            && Digest32::from_str(&body.prompt_registry_digest)?
                == record.snapshot.prompt_registry_digest
            && Digest32::from_str(&body.artifact_set_digest)?
                == record.snapshot.artifact_set_digest,
        "original signed body differs from its RunStart identity"
    );
    let queued = body
        .queued_input
        .as_ref()
        .context("signed Objective has no queued input")?;
    let thread =
        ThreadId::from_string(&queued.thread_id).context("signed Objective thread identity")?;
    ensure!(
        thread.to_string() == queued.thread_id,
        "signed Objective thread identity is not canonical"
    );
    ensure!(
        !queued.text.is_empty() && queued.text.len() <= 8 * 1024,
        "signed Objective text exceeds its input bound"
    );
    Ok(body)
}

pub(crate) fn queued_client_user_message_id(
    identity: &AgentdIdentity,
    record: &RunStartRecordV1,
) -> Result<String> {
    let authentication = &record.authentication;
    let client_digest = Digest32::of_bytes(&serde_json::to_vec(&(
        "hepta.agentd.objective-queued-input.v1",
        identity.agent_id.as_str(),
        record.snapshot.run_id.as_str(),
        authentication.issuer_id.as_str(),
        authentication.key_epoch,
        authentication.message_id.as_str(),
        authentication.sequence,
        authentication.signed_body_digest.to_string(),
    ))?);
    Ok(format!("hepta.objective:{client_digest}"))
}

pub(crate) fn queued_input(
    identity: &AgentdIdentity,
    record: &RunStartRecordV1,
) -> Result<CanonicalQueuedInputV1> {
    let body = signed_body(record)?;
    ensure!(
        body.spawn_generation == identity.spawn_generation,
        "signed Objective belongs to another original spawn"
    );
    let queued = body
        .queued_input
        .context("signed Objective has no queued input")?;
    let client_user_message_id = queued_client_user_message_id(identity, record)?;
    let input_payload_sha256 = user_input_payload_sha256(&[UserInput::Text {
        text: queued.text.clone(),
        text_elements: Vec::new(),
    }])?;
    Ok(CanonicalQueuedInputV1 {
        thread_id: queued.thread_id,
        client_user_message_id,
        input_payload_sha256,
        text: queued.text,
        run_id: record.snapshot.run_id.to_string(),
        signed_body_digest: record.authentication.signed_body_digest,
    })
}

/// Context-owner metadata for the actual text retained in the original signed
/// Objective. `token_count` is the existing owner's declared cost, not a new
/// tokenizer measurement. Material is always untrusted evidence; the prepared
/// compiler still selects it and enforces its own budget before rendering.
pub fn signed_objective_queued_text_item(
    record: &RunStartRecordV1,
    token_count: u64,
) -> Result<ContextItem> {
    let body = signed_body(record)?;
    let queued = body
        .queued_input
        .context("signed Objective has no queued input")?;
    ensure!(
        token_count > 0,
        "signed Objective context cost must be positive"
    );
    Ok(ContextItem {
        item_id: StableId::new(format!(
            "objective.queued:{}",
            record.authentication.signed_body_digest
        ))?,
        role: ContextRole::UntrustedEvidence,
        content_digest: Digest32::of_bytes(queued.text.as_bytes()),
        source_digest: record.authentication.signed_body_digest,
        token_count,
        contains_secret: false,
    })
}

pub(crate) fn bind_selected_text(
    record: &RunStartRecordV1,
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<NativeContextBindingV1> {
    prepared.bind_native_context(selected_text_materials(record, prepared)?)
}

pub(crate) fn selected_text_materials(
    record: &RunStartRecordV1,
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<Vec<NativeContextMaterialV1>> {
    let selected = prepared.selected_native_context_items();
    let [item] = selected.as_slice() else {
        anyhow::bail!(
            "native Objective requires the one original signed text source; other source bytes are unavailable"
        );
    };
    let expected = signed_objective_queued_text_item(record, item.token_count)?;
    ensure!(
        item == &expected,
        "native Objective selected a different original source or trust role"
    );
    let body = signed_body(record)?;
    let text = body
        .queued_input
        .context("signed Objective has no queued input")?
        .text;
    Ok(vec![NativeContextMaterialV1 {
        item_id: expected.item_id,
        source_digest: expected.source_digest,
        content: text.into_bytes(),
    }])
}

pub(crate) fn verify_admitted_record(record: &RunStartRecordV1, run: &RunSnapshot) -> Result<()> {
    // The compiled request/body/artifact digests have their canonical meanings
    // and are not replaced with the differently scoped ingress body digests.
    let original_deadline = record
        .admission
        .deadline_unix_micros
        .checked_add(999)
        .context("original Objective deadline overflow")?
        / 1_000;
    ensure!(
        run.run_id == record.snapshot.run_id.as_str()
            && run.objective_digest == record.snapshot.objective_digest.to_string()
            && run.authority_epoch == record.snapshot.authority_epoch
            && run.generation == record.snapshot.generation
            && run.fence_digest == record.snapshot.fence_digest.to_string()
            && run.deadline_ms <= original_deadline,
        "native original run no longer matches its signed Objective"
    );
    Ok(())
}

#[cfg(test)]
#[path = "canonical_queued_input_tests.rs"]
mod tests;

//! Finite Notes tools for one original App Server thread. The model supplies
//! only text and an observed revision. Root, thread identity, operation owner,
//! target, profile, and provenance come from the retained trusted composition.
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_app_server_protocol::DynamicToolFunctionSpec;
use codex_app_server_protocol::DynamicToolSpec;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdNotesLiteralAdapter;
use crate::AgentdNotesLiteralBindings;
use crate::AgentdNotesPreparedObjective;
use crate::AgentdRootProductionAttachment;
use crate::notes_literal_adapter::NotesAdapterProfile;
use crate::notes_literal_adapter::invalid;
use crate::text_session::AgentdTextSessionConfig;

#[path = "notes_thread_proof.rs"]
mod proof;
#[path = "notes_thread_runtime.rs"]
mod runtime;
use proof::VerifiedNotesThreadCall;

pub(crate) const READ_TOOL: &str = "hepta_notes_state";
pub(crate) const REPLACE_TOOL: &str = "hepta_notes_replace";

/// Install this exact catalog at the original `thread/start`. Resume must use
/// the original owner's retained catalog and cannot silently add tools.
pub fn original_notes_thread_tools() -> Vec<DynamicToolSpec> {
    [
        (READ_TOOL, "Read the attached Notes document identity, current revision and content hash. This does not grant write authority.", json!({
            "type":"object", "properties":{}, "required":[], "additionalProperties":false
        })),
        (REPLACE_TOOL, "Replace the attached Notes document with exact text at the revision returned by hepta_notes_state. Root must authorize the original operation. Preserve an unknown result's operation identity; never repeat it as a new effect.", json!({
            "type":"object", "properties":{
                "text":{"type":"string", "maxLength":4096},
                "expected_revision":{"type":"integer", "minimum":0}
            }, "required":["text","expected_revision"], "additionalProperties":false
        })),
    ].into_iter().map(|(name, description, input_schema)| DynamicToolSpec::Function(DynamicToolFunctionSpec {
        name: name.into(), description: description.into(), input_schema, defer_loading: false,
    })).collect()
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReplaceArguments {
    text: String,
    expected_revision: u64,
}

/// A required original-Agentd task. It owns one original connection and one
/// non-cloneable adapter; no renderer message can construct a tool proof.
pub struct AgentdNotesThreadToolRuntime {
    adapter: AgentdNotesLiteralAdapter,
    route: AgentdTextSessionConfig,
}

impl AgentdConfig {
    /// Select the explicit model-tool profile, original protected writer and
    /// fixed existing thread. This is mutually exclusive with the literal UI.
    pub fn with_root_notes_thread_tools(
        self,
        attachment: &AgentdRootProductionAttachment,
        bindings: AgentdNotesLiteralBindings,
        route: AgentdTextSessionConfig,
        deadline: Duration,
    ) -> Result<Self, AgentdError> {
        if route.agent_id != self.identity().agent_id
            || route.spawn_generation != self.identity().spawn_generation
            || route.control_socket != self.identity().control_socket
            || route.codex_home != self.identity().home_root
            || route.thread_id.is_empty()
            || route.thread_id.len() > 128
            || route.app_server_session_id.is_empty()
            || route.app_server_session_id.len() > 256
        {
            return Err(invalid(
                "original Notes thread differs from this retained Agentd",
            ));
        }
        let (configured, adapter) = self.with_root_notes_adapter(
            attachment,
            bindings,
            deadline,
            NotesAdapterProfile::OriginalThread,
        )?;
        configured.install_original_notes_thread_tools(Self::thread_tool_runtime(adapter, route))
    }

    fn thread_tool_runtime(
        adapter: AgentdNotesLiteralAdapter,
        route: AgentdTextSessionConfig,
    ) -> AgentdNotesThreadToolRuntime {
        AgentdNotesThreadToolRuntime { adapter, route }
    }
}

impl AgentdNotesThreadToolRuntime {
    pub(crate) fn validate_for(&self, config: &AgentdConfig) -> Result<(), AgentdError> {
        let writer = config
            .production_writer_host()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        if self.adapter.identity != *config.identity()
            || !Arc::ptr_eq(&self.adapter.writer, &writer.writer())
            || config.notes_objective().as_ref().map(|notes| &notes.target)
                != Some(self.adapter.observer.target())
        {
            return Err(invalid(
                "original Notes thread tool differs from its writer/target",
            ));
        }
        self.adapter.check_available()
    }

    async fn observe_document(&self) -> Result<Value, AgentdError> {
        self.adapter.check_available()?;
        let permit = Arc::clone(&self.adapter.blocking)
            .try_acquire_owned()
            .map_err(|_| invalid("previous original Notes observation is still running"))?;
        let observer = self.adapter.observer.clone();
        let state = tokio::time::timeout(
            self.adapter.deadline,
            tokio::task::spawn_blocking(move || {
                let _permit = permit;
                observer.observe_document()
            }),
        )
        .await
        .map_err(|_| invalid("original Notes observation timed out"))?
        .map_err(|_| invalid("original Notes observation worker failed"))??;
        self.adapter.check_available()?;
        Ok(
            json!({"target":state.target,"revision":state.revision,"text_sha256":state.text_sha256.as_str(),"receipt_pending":state.receipt_pending}),
        )
    }

    async fn execute(&mut self, call: &VerifiedNotesThreadCall) -> Result<Value, AgentdError> {
        let provenance = json!({
            "kind":"original_core_dynamic_tool", "thread_id":self.route.thread_id,
            "app_server_session_id":self.route.app_server_session_id,
            "turn_id":call.turn_id(), "call_id":call.call_id(),
            "callback_sha256":call.callback_digest().to_string(),
            "model_tuple_sha256":self.adapter.bindings.model_tuple_digest.to_string(),
            "runtime_body_sha256":self.adapter.bindings.runtime_body_digest.to_string(),
            "prompt_registry_sha256":self.adapter.bindings.prompt_registry_digest.to_string(),
            "artifact_set_sha256":self.adapter.bindings.artifact_set_digest.to_string(),
        });
        if call.tool() == READ_TOOL {
            return Ok(json!({"provenance":provenance,"document":self.observe_document().await?}));
        }
        let arguments: ReplaceArguments = serde_json::from_value(call.arguments().clone())?;
        if arguments.text.trim().is_empty() || arguments.text.len() > 4096 {
            return Err(invalid("original Notes text exceeds its UTF-8 byte bound"));
        }
        let request_id = call.intent_id(&self.route)?;
        let run_id = self.adapter.run_id(&request_id)?;
        let end = Instant::now() + self.adapter.deadline;
        let prepared = self
            .adapter
            .prepare_thread(&request_id, &arguments.text, arguments.expected_revision)
            .await?;
        let submission = match prepared {
            AgentdNotesPreparedObjective::Retained(_) => None,
            ready @ AgentdNotesPreparedObjective::Ready { .. } => {
                let remaining = end
                    .checked_duration_since(Instant::now())
                    .filter(|value| !value.is_zero())
                    .ok_or_else(|| invalid("original Notes tool submission deadline elapsed"))?;
                // Consumes the same original sender fence once. No resend on a
                // lost acknowledgement or replayed original callback.
                Some(ready.submit_once(remaining).await?)
            }
        };
        let original = self
            .adapter
            .writer
            .retained_operation(&run_id)
            .await?
            .ok_or_else(|| invalid("original Notes operation disappeared"))?;
        let receipt = self
            .adapter
            .writer
            .retained_notes_terminal_receipt(&run_id)
            .await?;
        let request_sha256 = self
            .adapter
            .retained_thread_request_sha256(&request_id)
            .await?;
        let sender_observation_retained = submission.map(|observed| {
            observed.retention == crate::AgentdNotesObservationRetention::Acknowledged
        });
        Ok(json!({
            "provenance":provenance, "operation_id":run_id,
            "semantic_sha256":original.operation.semantic_digest().to_string(),
            "exact_request_sha256":request_sha256,
            "sender_observation_retained":sender_observation_retained,
            "state":format!("{:?}",original.state), "receipt_utf8":receipt,
            "document":self.observe_document().await?,
        }))
    }
}

#[cfg(test)]
#[path = "notes_thread_tool_tests.rs"]
mod tests;

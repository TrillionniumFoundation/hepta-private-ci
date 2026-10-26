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

#[path = "notes_thread_human.rs"]
pub(crate) mod human;
#[path = "notes_thread_proof.rs"]
mod proof;
#[path = "notes_thread_runtime.rs"]
mod runtime;
#[path = "notes_thread_status.rs"]
mod status;
use human::VerifiedHumanTurn;
use proof::OriginalNotesThreadItem;
use proof::VerifiedNotesThreadCall;
use proof::VerifiedNotesThreadOperation;
use status::StatusArguments;

pub(crate) const READ_TOOL: &str = "hepta_notes_state";
pub(crate) const REPLACE_TOOL: &str = "hepta_notes_replace";
pub(crate) const STATUS_TOOL: &str = "hepta_notes_status";

/// Install this exact catalog at the original `thread/start`. Resume must use
/// the original owner's retained catalog and cannot silently add tools.
pub fn original_notes_thread_tools() -> Vec<DynamicToolSpec> {
    [
        (READ_TOOL, "Read the attached Notes document identity, current revision and content hash. This does not grant write authority.", json!({
            "type":"object", "properties":{}, "required":[], "additionalProperties":false
        })),
        (REPLACE_TOOL, "Replace the attached Notes document once per original turn with exact text at the revision returned by hepta_notes_state. Root must authorize the original operation. After any attempt, use only hepta_notes_status or hepta_notes_state in this turn. A new call ID cannot repeat an unknown effect.", json!({
            "type":"object", "properties":{
                "text":{"type":"string", "maxLength":4096},
                "expected_revision":{"type":"integer", "minimum":0}
            }, "required":["text","expected_revision"], "additionalProperties":false
        })),
        (STATUS_TOOL, "Read only an original hepta_notes_replace result in this same thread. Supply its original turn_id and call_id, or selector {kind: latest_original_replace} when a lost reply or compacted context hid those IDs. Discovery checks at most 16 original turns and returns the first write of the latest matching turn, never a retry call. Unknown/window_exhausted means do not repeat the effect. Original receipt/target and current_document are separate. This never prepares, signs, sends, or repeats an effect.", json!({
            "type":"object", "properties":{
                "turn_id":{"type":"string","maxLength":128},
                "call_id":{"type":"string","maxLength":128},
                "selector":{"type":"object", "properties":{"kind":{"type":"string","enum":["latest_original_replace"]}},"required":["kind"],"additionalProperties":false}
            }, "oneOf":[
                {"required":["turn_id","call_id"],"not":{"required":["selector"]}},
                {"required":["selector"],"not":{"anyOf":[{"required":["turn_id"]},{"required":["call_id"]}]}}
            ], "additionalProperties":false
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
    session: Option<crate::AgentdNotesSessionLifetime>,
    seed: Option<crate::NotesThreadSeedReceipt>,
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
        AgentdNotesThreadToolRuntime {
            adapter,
            route,
            session: None,
            seed: None,
        }
    }
}

impl AgentdNotesThreadToolRuntime {
    pub(crate) fn install_seed(
        &mut self,
        seed: crate::NotesThreadSeedReceipt,
    ) -> Result<(), AgentdError> {
        if self.seed.is_some()
            || seed.codex_home != self.route.codex_home
            || seed.thread_id != self.route.thread_id
            || seed.app_server_session_id != self.route.app_server_session_id
            || seed.model_tuple_digest()? != self.adapter.bindings.model_tuple_digest
        {
            return Err(invalid(
                "original Notes seed differs from the retained model route",
            ));
        }
        seed.verify_persisted()?;
        self.seed = Some(seed);
        Ok(())
    }
    pub(crate) fn install_session(
        &mut self,
        session: crate::AgentdNotesSessionLifetime,
    ) -> Result<(), AgentdError> {
        if self.session.is_some() {
            return Err(invalid("original Notes Session is already held"));
        }
        session.check_alive()?;
        self.session = Some(session);
        Ok(())
    }

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

    fn provenance(&self, call: &OriginalNotesThreadItem) -> Value {
        json!({
            "kind":"original_core_dynamic_tool", "thread_id":self.route.thread_id,
            "app_server_session_id":self.route.app_server_session_id,
            "turn_id":call.turn_id(), "call_id":call.call_id(),
            "callback_sha256":call.callback_digest().to_string(),
            "model_tuple_sha256":self.adapter.bindings.model_tuple_digest.to_string(),
            "runtime_body_sha256":self.adapter.bindings.runtime_body_digest.to_string(),
            "prompt_registry_sha256":self.adapter.bindings.prompt_registry_digest.to_string(),
            "artifact_set_sha256":self.adapter.bindings.artifact_set_digest.to_string(),
        })
    }

    async fn execute(
        &mut self,
        call: &VerifiedNotesThreadCall,
        human: &VerifiedHumanTurn,
    ) -> Result<Value, AgentdError> {
        if call.tool() == READ_TOOL {
            return Ok(
                json!({"provenance":self.provenance(call),"document":self.observe_document().await?}),
            );
        }
        if call.tool() != REPLACE_TOOL {
            return Err(invalid("operation status cannot enter Notes preparation"));
        }
        let arguments: ReplaceArguments = serde_json::from_value(call.arguments().clone())?;
        if arguments.text.trim().is_empty() || arguments.text.len() > 4096 {
            return Err(invalid("original Notes text exceeds its UTF-8 byte bound"));
        }
        let request_id = call.turn_intent_id(&self.route)?;
        let original_call_id = call.intent_id(&self.route)?;
        let end = Instant::now() + self.adapter.deadline;
        let prepared = self
            .adapter
            .prepare_thread(
                &request_id,
                &original_call_id,
                &arguments.text,
                arguments.expected_revision,
                human,
            )
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
        let retained = submission.map(|observed| {
            observed.retention == crate::AgentdNotesObservationRetention::Acknowledged
        });
        self.observe_operation(call, retained).await
    }

    async fn observe_retained(
        &mut self,
        original: &VerifiedNotesThreadOperation,
    ) -> Result<Value, AgentdError> {
        self.observe_operation(original.original_item(), None).await
    }

    async fn observe_operation(
        &self,
        call: &OriginalNotesThreadItem,
        sender_observation_retained: Option<bool>,
    ) -> Result<Value, AgentdError> {
        let request_id = call.turn_intent_id(&self.route)?;
        let original_call_id = call.intent_id(&self.route)?;
        let run_id = self.adapter.run_id(&request_id)?;
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
            .retained_thread_request_sha256(&request_id, &original_call_id)
            .await?;
        let payload: Value = serde_json::from_str(&original.payload_json)?;
        let original_target: codex_hepta_memory::NotesTargetIdentity =
            serde_json::from_value(payload["target"].clone())?;
        original_target
            .validate()
            .map_err(|error| invalid(&error))?;
        if payload["operation_id"] != run_id
            || original_target.destination_id() != original.operation.destination_id().as_str()
        {
            return Err(invalid(
                "original Notes result target differs from its source",
            ));
        }
        // Losing the application or its readback cannot erase an already
        // verified immutable source receipt. Report freshness separately.
        let document = self.observe_document().await.ok();
        Ok(json!({
            "provenance":self.provenance(call), "operation_id":run_id,
            "semantic_sha256":original.operation.semantic_digest().to_string(),
            "exact_request_sha256":request_sha256,
            "sender_observation_retained":sender_observation_retained,
            "state":format!("{:?}",original.state), "receipt_utf8":receipt,
            "original_target":original_target,
            "current_document_readback_available":document.is_some(), "current_document":document,
        }))
    }
}

#[cfg(test)]
#[path = "notes_thread_tool_tests.rs"]
mod tests;

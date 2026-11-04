//! Six finite tools on one newly seeded original Core thread and original writer.
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdNotesLiteralAdapter;
use crate::AgentdNotesLiteralBindings;
use crate::AgentdNotesPreparedObjective;
use crate::desktop_thread_catalog::CALCULATOR_EVALUATE_TOOL;
use crate::desktop_thread_catalog::CALCULATOR_READ_TOOL;
use crate::desktop_thread_catalog::CALCULATOR_STATUS_TOOL;
use crate::notes_literal_adapter::NotesAdapterProfile;
use crate::notes_literal_adapter::desktop_recorded::RecordedDesktopLookup;
use crate::notes_literal_adapter::desktop_recorded::RecordedDesktopOperation;
use crate::notes_literal_adapter::invalid;
use crate::notes_thread_tool::READ_TOOL;
use crate::notes_thread_tool::REPLACE_TOOL;
use crate::notes_thread_tool::STATUS_TOOL;
use crate::notes_thread_tool::human;
use crate::text_session::AgentdTextSessionConfig;
use human::VerifiedHumanTurn;
use serde_json::Value;
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;

#[path = "desktop_thread_arguments.rs"]
pub(crate) mod arguments;
#[path = "desktop_thread_observe.rs"]
mod observe;
#[path = "desktop_thread_proof.rs"]
mod proof;
#[path = "desktop_thread_runtime.rs"]
mod runtime;
#[path = "desktop_thread_transport.rs"]
mod transport;
use arguments::CalculatorArguments;
use arguments::NotesArguments;
use arguments::StatusArguments;
use proof::OriginalDesktopThreadItem;
use proof::VerifiedDesktopThreadCall;
use proof::VerifiedDesktopThreadOperation;

/// One required task; no renderer can construct its original Core/human proof.
pub struct AgentdDesktopThreadToolRuntime {
    adapter: AgentdNotesLiteralAdapter,
    calculator: crate::AgentdCalculatorStateObserver,
    route: AgentdTextSessionConfig,
    session: Option<crate::AgentdNotesSessionLifetime>,
    seed: crate::DesktopThreadSeedReceipt,
}

impl AgentdConfig {
    /// Compose only the new six-tool profile after the exact joint Root handoff.
    /// The legacy Notes thread, recovery entry and catalog are not reinterpreted.
    pub fn with_root_desktop_thread_tools(
        self,
        attachment: &crate::AgentdDesktopProductionAttachment,
        bindings: AgentdNotesLiteralBindings,
        route: AgentdTextSessionConfig,
        seed: crate::DesktopThreadSeedReceipt,
        session: crate::AgentdNotesSessionLifetime,
        deadline: Duration,
    ) -> Result<Self, AgentdError> {
        if route.agent_id != self.identity().agent_id
            || route.spawn_generation != self.identity().spawn_generation
            || route.control_socket != self.identity().control_socket
            || route.codex_home != self.identity().home_root
            || seed.codex_home != route.codex_home
            || seed.thread_id != route.thread_id
            || seed.app_server_session_id != route.app_server_session_id
            || seed.model_tuple_digest()? != bindings.model_tuple_digest
        {
            return Err(invalid(
                "original Desktop route/seed differs from this retained daemon",
            ));
        }
        seed.verify_persisted()?;
        session.check_alive()?;
        let (configured, adapter) = self.with_root_notes_adapter(
            &attachment.root,
            bindings,
            deadline,
            NotesAdapterProfile::OriginalDesktop,
        )?;
        let configured =
            configured.with_desktop_objective(crate::AgentdDesktopObjectiveConfig {
                profile_digest: adapter.profile_digest,
                notes: adapter.observer.target().clone(),
                calculator: attachment.calculator.target().clone(),
            })?;
        configured.install_original_desktop_thread_tools(AgentdDesktopThreadToolRuntime {
            adapter,
            calculator: attachment.calculator.clone(),
            route,
            session: Some(session),
            seed,
        })
    }
}

impl AgentdDesktopThreadToolRuntime {
    async fn execute(
        &mut self,
        call: &VerifiedDesktopThreadCall,
        human: &VerifiedHumanTurn,
    ) -> Result<Value, AgentdError> {
        if matches!(call.tool(), READ_TOOL | CALCULATOR_READ_TOOL) {
            return Ok(
                json!({"provenance":self.provenance(call),"current_state":self.observe_current(call.tool()).await?}),
            );
        }
        if !matches!(call.tool(), REPLACE_TOOL | CALCULATOR_EVALUATE_TOOL) {
            return Err(invalid("status cannot enter Desktop preparation"));
        }
        let end = crate::calculator_deadline::Deadline::after(self.adapter.deadline)?;
        let prepared = self
            .adapter
            .prepare_desktop(
                &self.calculator,
                call.recorded_reference(&self.route),
                call.arguments(),
                human,
                end,
            )
            .await?;
        let retained = match prepared {
            AgentdNotesPreparedObjective::Retained(_) => None,
            ready @ AgentdNotesPreparedObjective::Ready { .. } => {
                let submitted = ready.submit_once(end.remaining()?).await;
                // The transport receives only a remaining duration. Recheck the
                // original suspend-aware end before accepting its acknowledgement.
                // A late result leaves the original durable receipt available to
                // the read-only status path; it never authorizes another send.
                end.remaining().map_err(|_| {
                    invalid(
                        "original Desktop submission acknowledgement unknown after total deadline; reconcile the retained operation without resending",
                    )
                })?;
                Some(submitted?.retention == crate::AgentdNotesObservationRetention::Acknowledged)
            }
        };
        let mut result = self.observe_original(call).await?;
        result["sender_observation_retained"] = json!(retained);
        Ok(result)
    }

    pub(crate) fn validate_for(&self, config: &AgentdConfig) -> Result<(), AgentdError> {
        let writer = config
            .production_writer_host()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        let objective = config
            .desktop_objective()
            .ok_or_else(|| invalid("Desktop profile absent"))?;
        if self.adapter.identity != *config.identity()
            || !Arc::ptr_eq(&self.adapter.writer, &writer.writer())
            || objective.notes != *self.adapter.observer.target()
            || objective.calculator != *self.calculator.target()
            || objective.profile_digest != self.adapter.profile_digest
        {
            return Err(invalid(
                "Desktop runtime differs from original writer and exact targets",
            ));
        }
        self.adapter.check_available()
    }

    fn provenance(&self, call: &OriginalDesktopThreadItem) -> Value {
        json!({"kind":"original_core_dynamic_tool","profile":"organ.desktop.thread-tool.v1",
            "thread_id":self.route.thread_id,"app_server_session_id":self.route.app_server_session_id,
            "turn_id":call.turn_id(),"call_id":call.call_id(),"tool":call.tool(),
            "callback_sha256":call.callback_digest().to_string(),
            "model_tuple_sha256":self.adapter.bindings.model_tuple_digest.to_string()})
    }
}

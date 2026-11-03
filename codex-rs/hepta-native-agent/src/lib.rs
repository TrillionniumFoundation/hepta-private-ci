//! A bounded native agent loop with host-owned identity, persistence and tools.
//! No Codex core, app-server or session authority is created by this crate.

#![forbid(unsafe_code)]

mod context_policy;
mod context_projection;
mod events;
mod model_port;
mod responses;

pub use context_policy::CONTEXT_POLICY_VERSION;
pub use context_policy::ContextPolicy;
pub use context_policy::LEGACY_CONTEXT_POLICY_VERSION;
pub use context_projection::CONTEXT_PROJECTION_VERSION;

pub use events::NativeEvent;
pub use events::NativeEventSink;
pub use events::NativeTextDelta;

pub use model_port::ModelPort;

pub use responses::ModelEvent;
pub use responses::ModelRequest;
pub use responses::ModelTextDelta;
pub use responses::ObservedModelCompletion;
pub use responses::ObservedModelTerminal;
pub use responses::ResponsesModel;
pub use responses::ResponsesStream;

mod engine;
mod state;

pub use engine::NativeAgent;
pub use state::Limits;
pub use state::PendingTool;
pub use state::RunOutcome;
pub use state::ToolCall;
pub use state::ToolObservation;
pub use state::ToolPort;
pub use state::TurnBinding;
pub use state::TurnOwner;
pub use state::TurnState;

#[cfg(test)]
#[path = "engine_tests.rs"]
mod engine_tests;

pub use state::ToolAdmission;

mod runtime_execution_core;
pub use runtime_execution_core::canonical_runtime_intent_v1;

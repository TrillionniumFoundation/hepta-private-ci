//! Bounded native model/tool orchestration over existing Hepta owners.
//!
//! This crate stores no conversation, issues no authority, and launches no
//! process. The context/TaskFlow owner supplies a frozen request and atomically
//! commits observations with its cursor. Inference and effect owners retain
//! admission, cancellation and same-operation recovery responsibilities.

#![forbid(unsafe_code)]

#[cfg(feature = "context-v2")]
mod context;
mod runner;
#[cfg(feature = "taskflow-owner")]
mod taskflow_serde;
mod types;

pub use runner::run;
pub use types::EffectObservation;
pub use types::EffectOwner;
pub use types::Error;
pub use types::Frame;
pub use types::InferenceOwner;
pub use types::Limits;
pub use types::ModelEvent;
pub use types::ModelOutput;
pub use types::ModelRequest;
pub use types::ModelSession;
pub use types::Outcome;
pub use types::Phase;
pub use types::Result;
pub use types::StopObservation;
pub use types::ToolCall;
pub use types::Transition;
pub use types::TurnBinding;
pub use types::TurnOwner;
pub use types::Usage;

#[cfg(feature = "context-v2")]
pub use context::NativeContextInputV2;
#[cfg(feature = "context-v2")]
pub use context::PreparedNativeContextV2;
#[cfg(feature = "context-v2")]
pub use context::prepare_native_context_v2;

#[cfg(feature = "responses-api")]
mod responses_failure;
#[cfg(feature = "responses-api")]
pub use responses_failure::ResponsesFailure;
#[cfg(feature = "responses-api")]
pub use responses_failure::ResponsesFailureCategory;
#[cfg(feature = "responses-api")]
pub use responses_failure::ResponsesFailureStage;

#[cfg(feature = "responses-api")]
mod responses;
#[cfg(feature = "responses-api")]
pub use responses::ResponsesBridgeLimits;
#[cfg(feature = "responses-api")]
pub use responses::ResponsesBridgeStatus;
#[cfg(feature = "responses-api")]
pub use responses::ResponsesContinuation;
#[cfg(feature = "responses-api")]
pub use responses::ResponsesContinuationOwner;
#[cfg(feature = "responses-api")]
pub use responses::forward_responses_stream;

#[cfg(feature = "responses-api")]
mod responses_evidence;
#[cfg(feature = "responses-api")]
pub use responses_evidence::response_item_evidence;
#[cfg(feature = "responses-api")]
pub use responses_evidence::response_items_evidence;

#[cfg(feature = "managed-responses")]
mod managed_responses;
#[cfg(feature = "managed-responses")]
pub use managed_responses::ManagedResponsesAttempt;
#[cfg(feature = "managed-responses")]
pub use managed_responses::ManagedResponsesClient;
#[cfg(feature = "managed-responses")]
pub use managed_responses::ManagedResponsesObservation;

#[cfg(feature = "taskflow-owner")]
mod taskflow_owner;
#[cfg(feature = "taskflow-owner")]
pub use taskflow_owner::ObservedTaskFlowTurn;
#[cfg(feature = "taskflow-owner")]
pub use taskflow_owner::RetainedObservation;
#[cfg(feature = "taskflow-owner")]
pub use taskflow_owner::TaskFlowContextPreparer;
#[cfg(feature = "taskflow-owner")]
pub use taskflow_owner::TaskFlowTurnOwner;

#[cfg(feature = "automation-effects")]
mod automation_effects;
#[cfg(feature = "automation-effects")]
pub use automation_effects::AUTOMATION_STATUS_TOOL_NAME;
#[cfg(feature = "automation-effects")]
pub use automation_effects::AutomationStatusEffectOwner;
#[cfg(feature = "automation-effects")]
pub use automation_effects::PreboundAutomationStatusEffect;
#[cfg(feature = "automation-effects")]
pub use automation_effects::automation_status_effect_run_id;

//! One-process-per-workspace Hepta agent host.
//!
//! `agentd` binds exactly one fleet `AgentId`, embeds the existing Codex App
//! Server execution path, and exposes a small local lifecycle/control socket.
//! It does not implement a second runtime kernel or a fleet-wide message bus.

mod app_runtime;
mod automation;
mod client;
mod cognitive_context;
mod config;
mod control;
mod error;
mod event_buffer;
mod lane_b_runtime;
mod production_writer_host;
mod qualification_writer;
mod runtime;
mod state;

pub use client::AgentdClient;
pub use codex_hepta_agent_protocol::AGENTD_CONTROL_SCHEMA_VERSION;
pub use codex_hepta_agent_protocol::AgentdEvent;
pub use codex_hepta_agent_protocol::AgentdEventKind;
pub use codex_hepta_agent_protocol::AgentdMethod;
pub use codex_hepta_agent_protocol::AgentdPayload;
pub use codex_hepta_agent_protocol::AgentdRequest;
pub use codex_hepta_agent_protocol::AgentdResponse;
pub use codex_hepta_agent_protocol::CognitiveContextItem;
pub use codex_hepta_agent_protocol::CognitiveContextSnapshot;
pub use codex_hepta_agent_protocol::EventBatch;
pub use codex_hepta_agent_protocol::HealthSnapshot;
pub use codex_hepta_agent_protocol::LifecycleSnapshot;
pub use codex_hepta_agent_protocol::MAX_CONTROL_FRAME_BYTES;
pub use codex_hepta_agent_protocol::MAX_EVENT_BATCH;
pub use codex_hepta_agent_protocol::MAX_FEDERATION_CONTROL_LIST;
pub use codex_hepta_agent_protocol::MemoryFederationCapabilityId;
pub use codex_hepta_agent_protocol::MemoryFederationCapabilitySnapshot;
pub use codex_hepta_agent_protocol::MemoryFederationCapabilityState;
pub use codex_hepta_agent_protocol::MemoryFederationScopeKind;
pub use codex_hepta_agent_protocol::SessionIngress;
pub use codex_hepta_agent_protocol::SessionTransport;
pub use codex_hepta_automation::AutomationSchedule;
pub use codex_hepta_automation::AutomationTask;
pub use codex_hepta_automation::AutomationTaskDraft;
pub use codex_hepta_automation::AutomationTaskId;
pub use config::AgentdConfig;
pub use config::AgentdIdentity;
pub use config::HEPTA_AGENT_GENERATION_ENV;
pub use config::HEPTA_AGENT_HOME_ENV;
pub use config::HEPTA_AGENT_ID_ENV;
pub use config::HEPTA_AGENT_RUN_ROOT_ENV;
pub use error::AgentdError;
pub use lane_b_runtime::AgentRunCoordinator;
pub use lane_b_runtime::AgentRunError;
pub use lane_b_runtime::CancellationDisposition;
pub use lane_b_runtime::ContextAttachment;
pub use lane_b_runtime::RunPhase;
pub use lane_b_runtime::RunReceipt;
pub use lane_b_runtime::RunSnapshot;
pub use lane_b_runtime::RuntimeComposition;
pub use production_writer_host::AgentdProductionWriterHost;
pub use runtime::run;

use control::AgentdControlServer;
use event_buffer::EventBuffer;
use state::AgentdState;

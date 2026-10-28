//! Host-owned turn state and native tool observations.

use std::future::Future;
use std::time::Duration;

use anyhow::Result;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeReceiptV1;
use codex_hepta_types::RuntimeToolIntentV1;
use codex_hepta_types::StableId;
use serde_json::Value;

use crate::ModelRequest;

/// These are existing owner identities, never allocated by the model.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TurnBinding {
    pub thread_id: StableId,
    pub turn_id: StableId,
    pub operation_id: StableId,
    pub generation: Generation,
}

/// One explicitly bounded model/tool session.
#[derive(Clone, Debug)]
pub struct Limits {
    pub context_bytes: usize,
    pub output_tokens: u32,
    pub model_calls: usize,
    pub tool_calls: usize,
    pub tool_output_bytes: usize,
    pub model_timeout: Duration,
    pub tool_timeout: Duration,
    pub observation_interval: Duration,
}

/// A complete model proposal. Its operation identity comes from the host.
#[derive(Clone, Debug, PartialEq)]
pub struct ToolCall {
    pub call_id: String,
    pub name: String,
    pub arguments: Vec<u8>,
}

/// Final request bytes compiled and admitted by the host, not by the model.
#[derive(Clone, Debug)]
pub struct ToolAdmission {
    pub intent: RuntimeToolIntentV1,
    pub arguments: Vec<u8>,
}

/// Exact pending intent is retained across cancellation, timeouts and reconnects.
#[derive(Clone, Debug)]
pub struct PendingTool {
    pub call: ToolCall,
    pub intent: RuntimeToolIntentV1,
    pub arguments: Vec<u8>,
    pub submission_attempted: bool,
    pub cancel_requested: bool,
}

/// Snapshot owned and persisted by the embedding session owner.
#[derive(Clone, Debug)]
pub struct TurnState {
    pub binding: TurnBinding,
    pub context: Vec<Value>,
    pub model_calls: usize,
    pub tool_calls: usize,
    pub pending_model: Option<ModelRequest>,
    pub provider_response_id: Option<String>,
    pub queued_tools: Vec<ToolCall>,
    pub pending_tool: Option<PendingTool>,
    pub completed_call_ids: Vec<String>,
    pub final_answer: Option<String>,
    pub cancelled: bool,
    pub last_error: Option<String>,
    pub model_usage: Vec<Value>,
}

impl TurnState {
    pub fn new(binding: TurnBinding, input: String) -> Self {
        Self {
            binding,
            context: vec![serde_json::json!({"role":"user","content":input})],
            model_calls: 0,
            tool_calls: 0,
            pending_model: None,
            provider_response_id: None,
            queued_tools: Vec::new(),
            pending_tool: None,
            completed_call_ids: Vec::new(),
            final_answer: None,
            cancelled: false,
            last_error: None,
            model_usage: Vec::new(),
        }
    }
}

/// A job acceptance is deliberately distinct from a terminal receipt.
pub enum ToolObservation {
    Accepted,
    Terminal {
        receipt: RuntimeReceiptV1,
        stdout: Vec<u8>,
        stderr: Vec<u8>,
    },
}

/// Uses the existing jobs owner. observe/cancel never allocate another operation.
pub trait ToolPort: Send + Sync {
    fn execute_or_observe(
        &self,
        intent: &RuntimeToolIntentV1,
        arguments: &[u8],
    ) -> impl Future<Output = Result<ToolObservation>> + Send;

    fn observe(
        &self,
        intent: &RuntimeToolIntentV1,
    ) -> impl Future<Output = Result<ToolObservation>> + Send;

    fn cancel(&self, intent: &RuntimeToolIntentV1) -> impl Future<Output = Result<()>> + Send;
}

/// Existing host owns admission, generation, FinalUse and durable checkpoints.
/// Implementations must commit checkpoint before returning and reject stale
/// bindings. This trait is an in-process view, not a new wire or authority store.
pub trait TurnOwner: Send + Sync {
    fn verify_current(&self, binding: &TurnBinding) -> impl Future<Output = Result<()>> + Send;

    fn checkpoint(&self, state: &TurnState) -> impl Future<Output = Result<()>> + Send;

    fn admit_model(
        &self,
        binding: &TurnBinding,
        sequence: usize,
        exact_body: &[u8],
    ) -> impl Future<Output = Result<ModelRequest>> + Send;

    fn admit_tool(
        &self,
        binding: &TurnBinding,
        call: &ToolCall,
    ) -> impl Future<Output = Result<ToolAdmission>> + Send;
}

/// Pending means recovery is required; it is never a successful final answer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RunOutcome {
    Completed(String),
    Cancelled,
    PendingModel,
    PendingTool,
}

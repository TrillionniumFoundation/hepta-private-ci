use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio::sync::mpsc;

#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "taskflow-owner",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "taskflow-owner", serde(deny_unknown_fields))]
pub struct TurnBinding {
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::stable_id")
    )]
    pub run_id: StableId,
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::stable_id")
    )]
    pub turn_id: StableId,
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::generation")
    )]
    pub generation: Generation,
    /// Digest of the admitted request, including its objective and principal.
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::digest")
    )]
    pub admission_digest: Digest32,
    /// Original owner deadline; reconnecting must not reset the turn's budget.
    pub deadline_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "taskflow-owner",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "taskflow-owner", serde(deny_unknown_fields))]
pub struct ModelRequest {
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::stable_id")
    )]
    pub request_id: StableId,
    pub payload: Arc<str>,
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::digest")
    )]
    pub context_digest: Digest32,
    /// Exact count from the compiled-context tokenizer, before provider framing.
    pub input_tokens: u64,
    /// Caller-reserved upper bound including provider framing and tool schemas.
    /// Provider-reported input usage is charged independently of `input_tokens`.
    pub maximum_provider_input_tokens: u64,
    /// Local reservation/acceptance bound. A wire-level provider hard cap exists
    /// only when the selected inference owner can enforce one.
    pub maximum_output_tokens: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "taskflow-owner",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "taskflow-owner", serde(deny_unknown_fields))]
pub struct ToolCall {
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::stable_id")
    )]
    pub call_id: StableId,
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::stable_id")
    )]
    pub name: StableId,
    /// Complete arguments; the inference adapter assembles partial wire deltas.
    pub arguments: String,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
#[cfg_attr(
    feature = "taskflow-owner",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "taskflow-owner", serde(deny_unknown_fields))]
pub struct Usage {
    pub input_tokens: u64,
    pub output_tokens: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "taskflow-owner",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "taskflow-owner", serde(deny_unknown_fields))]
pub struct ModelOutput {
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::stable_id")
    )]
    pub request_id: StableId,
    /// Owner-retained full provider output, including opaque reasoning items.
    /// The context owner resolves this receipt when constructing continuation.
    #[cfg_attr(
        feature = "taskflow-owner",
        serde(with = "crate::taskflow_serde::digest")
    )]
    pub continuation_digest: Digest32,
    pub text: String,
    pub calls: Vec<ToolCall>,
    pub usage: Usage,
}

#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "taskflow-owner",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "taskflow-owner", serde(deny_unknown_fields))]
pub enum Phase {
    Model(ModelRequest),
    Tools { calls: Vec<ToolCall>, next: usize },
    Complete(ModelOutput),
    CancelRequested,
    Cancelled,
}

/// An owned view of the existing context/TaskFlow cursor, never a second store.
#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "taskflow-owner",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "taskflow-owner", serde(deny_unknown_fields))]
pub struct Frame {
    pub binding: TurnBinding,
    pub revision: u64,
    pub round: u32,
    pub consumed_tokens: u64,
    pub phase: Phase,
}

#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "taskflow-owner",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "taskflow-owner", serde(deny_unknown_fields))]
pub enum Transition {
    ModelCompleted(ModelOutput),
    ToolCompleted {
        #[cfg_attr(
            feature = "taskflow-owner",
            serde(with = "crate::taskflow_serde::digest")
        )]
        operation_key: Digest32,
        output: String,
    },
    CancelRequested,
    Cancelled,
}

pub enum ModelEvent {
    TextDelta(String),
    ToolCall(ToolCall),
    Completed {
        request_id: StableId,
        continuation_digest: Digest32,
        usage: Usage,
    },
}

pub enum ModelSession {
    Stream(mpsc::Receiver<Result<ModelEvent>>),
    Completed(ModelOutput),
    Unresolved,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EffectObservation {
    Completed(String),
    Unresolved,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StopObservation {
    Stopped,
    Unresolved,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Outcome {
    Completed(ModelOutput),
    Paused,
    Cancelled,
    CancellationPending,
}

#[derive(Clone, Debug)]
pub struct Limits {
    pub maximum_rounds: u32,
    pub maximum_total_tokens: u64,
    pub maximum_context_bytes: usize,
    pub maximum_output_bytes: usize,
    pub maximum_calls: usize,
    pub timeout: Duration,
    pub cancellation_timeout: Duration,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            maximum_rounds: 32,
            maximum_total_tokens: 128_000,
            maximum_context_bytes: 256 * 1024,
            maximum_output_bytes: 4096,
            maximum_calls: 16,
            timeout: Duration::from_secs(120),
            cancellation_timeout: Duration::from_secs(5),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("native agent limit exceeded: {0}")]
    Limit(&'static str),
    #[error("native agent owner contract rejected: {0}")]
    Contract(&'static str),
    #[error("owner operation failed: {0}")]
    Owner(String),
    #[cfg(feature = "responses-api")]
    #[error("Responses failure: {0}")]
    Responses(crate::ResponsesFailure),
}

pub type Result<T> = std::result::Result<T, Error>;

/// Context and TaskFlow authority. `commit` must durably compare-and-swap the
/// supplied revision, append the observation and advance the cursor atomically.
/// A model frame must freeze its payload until terminal observation. Preparing
/// subsequent frames reuses context compilation, memory and compaction owners;
/// mandatory instructions and unresolved calls must survive compaction.
pub trait TurnOwner: Send {
    fn load(&mut self, binding: &TurnBinding) -> impl Future<Output = Result<Frame>> + Send;
    /// Observe the original frame solely to stop its existing owners. This
    /// grants no model/tool dispatch or generation handoff. Stateful adapters
    /// may permit this under a live waiting/retry fence while normal load is
    /// blocked. Terminal or expired/reclaimed active owners must still refuse.
    fn load_for_cancel(
        &mut self,
        binding: &TurnBinding,
    ) -> impl Future<Output = Result<Frame>> + Send {
        self.load(binding)
    }

    fn commit(
        &mut self,
        previous: &Frame,
        transition: Transition,
    ) -> impl Future<Output = Result<Frame>> + Send;
}

/// Existing inference owner. Reopening the same binding/request must reconcile
/// its original dispatch. It may replay a complete result, but must never start
/// another provider call after ambiguous acceptance. Streams begin at byte zero;
/// a disconnected partial stream is not a terminal result. Before completion,
/// retain the full provider-native continuation in the owning store and bind
/// its receipt to the exact request. Text/tool projections cannot replace
/// opaque reasoning or other provider output required by the next request.
/// The inference owner retains actual terminal usage even when the loop rejects
/// a result for exceeding a reservation; rejected cost must never disappear.
pub trait InferenceOwner: Send {
    fn open_or_reconcile(
        &mut self,
        binding: &TurnBinding,
        request: &ModelRequest,
    ) -> impl Future<Output = Result<ModelSession>> + Send;
    fn cancel(
        &mut self,
        binding: &TurnBinding,
    ) -> impl Future<Output = Result<StopObservation>> + Send;
}

/// Existing effect owner. Authorization, durable admission and destination
/// deduplication remain here. An unresolved operation must be observed under the
/// same key; the loop neither grants final-use authority nor invents a retry key.
pub trait EffectOwner: Send {
    fn execute_or_observe(
        &mut self,
        binding: &TurnBinding,
        operation_key: Digest32,
        call: &ToolCall,
    ) -> impl Future<Output = Result<EffectObservation>> + Send;
    fn cancel(
        &mut self,
        binding: &TurnBinding,
    ) -> impl Future<Output = Result<StopObservation>> + Send;
}

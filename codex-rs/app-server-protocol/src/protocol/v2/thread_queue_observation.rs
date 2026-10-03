//! Finite read-only observations of original durable queue identities.
use super::ThreadSource;
use crate::JsonSchema;
use crate::TS;
use codex_experimental_api_macros::ExperimentalApi;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;

/// Exact durable observation; never reserves a queue row or resumes a thread.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadQueueObserveParams {
    pub thread_id: String,
    /// The protected scope observed before and after the read, without repair.
    pub expected_project_id: String,
    pub expected_cwd: AbsolutePathBuf,
    pub expected_thread_source: ThreadSource,
    pub client_user_message_id: String,
    pub expected_payload_sha256: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(rename_all = "camelCase", export_to = "v2/")]
pub enum ThreadQueueObservedTerminal {
    Completed,
    Failed,
    Interrupted,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS, ExperimentalApi)]
#[serde(tag = "type", rename_all = "camelCase")]
#[ts(tag = "type", rename_all = "camelCase", export_to = "v2/")]
pub enum ThreadQueueObserveOutcome {
    #[serde(rename_all = "camelCase")]
    #[ts(rename_all = "camelCase")]
    Pending {
        queued_submission_id: Option<String>,
    },
    #[serde(rename_all = "camelCase")]
    #[ts(rename_all = "camelCase")]
    Persisted {
        turn_id: String,
        terminal: Option<ThreadQueueObservedTerminal>,
    },
    Missing,
    Unknown,
    Cancelled,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS, ExperimentalApi)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadQueueObserveResponse {
    pub client_user_message_id: String,
    pub payload_sha256: String,
    pub outcome: ThreadQueueObserveOutcome,
}

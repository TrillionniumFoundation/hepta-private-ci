//! Bounded HMI attachment to one existing, owner-authorized App Server thread.
//!
//! The authenticated channel/Agentd owner supplies the binding and endpoint.
//! These values are identity checks, not a grant issuer. Core remains the only
//! conversation store and model/tool executor. Reattachment never replays audio
//! or implicitly resubmits an ambiguous request.

use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicI64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerRequestHandle;
use codex_app_server_client::TypedRequestError;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadQueueDeleteParams;
use codex_app_server_protocol::ThreadQueueDeleteResponse;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnInterruptResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_types::Digest32;
use codex_protocol::user_input::user_input_payload_sha256;
use serde::Deserialize;
use serde::Serialize;

const MAX_TEXT_BYTES: usize = 64 * 1024;
const MAX_ITEMS: usize = 32;
const MAX_SPEECH_BYTES: usize = 4096;

#[path = "hmi_events.rs"]
mod events;
#[path = "hmi_owner_types.rs"]
mod owner_types;
pub use owner_types::*;
#[path = "hmi_external.rs"]
mod external;
#[path = "hmi_owner.rs"]
mod owner;
#[path = "hmi_requests.rs"]
mod requests;
pub use owner::*;
#[path = "hmi_media_jsonl.rs"]
mod media_jsonl;
pub use media_jsonl::*;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HmiBindingV1 {
    pub principal_id: String,
    pub device_id: String,
    pub device_generation: u64,
    pub organ_id: String,
    pub logical_session_id: String,
    pub organ_generation: u64,
    pub thread_id: String,
    pub app_server_session_id: String,
    pub codex_home: String,
    pub app_server_version: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HmiError {
    Invalid(&'static str),
    Identity,
    Fenced,
    Busy,
    Deadline,
    Transport(String),
    Protocol(String),
}
impl fmt::Display for HmiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for HmiError {}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiOutputScopeV1 {
    pub principal_id: String,
    pub device_id: String,
    pub device_generation: u64,
    pub organ_id: String,
    pub logical_session_id: String,
    pub utterance_sequence: u64,
    pub utterance_id: Option<String>,
    pub organ_generation: u64,
    pub connection_id: u64,
    pub output_epoch: u64,
    pub turn_id: Option<String>,
}

/// One bounded request for the existing media owner's `speak` command.
/// This carries source identity, not a device grant or a playback receipt.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum HmiSpeechRequestV1 {
    Speak {
        scope: HmiOutputScopeV1,
        text: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum HmiTerminalStatusV1 {
    Completed,
    Failed,
    Interrupted,
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiTerminalV1 {
    pub status: HmiTerminalStatusV1,
    pub generated_text: String,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum HmiEventKindV1 {
    TurnStarted,
    TextDelta { item_id: String, delta: String },
    TextFinal { item_id: String, text: String },
    Terminal { outcome: HmiTerminalV1 },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiEventV1 {
    pub scope: HmiOutputScopeV1,
    pub kind: HmiEventKindV1,
}

#[derive(Debug)]
struct State {
    fenced: bool,
    epoch: u64,
    output_enabled: bool,
    cancel_requested: bool,
    queued_id: Option<String>,
    sequence: u64,
    pending: Option<(String, String)>,
    active_turn: Option<String>,
    items: Vec<(String, String)>,
    terminal: Option<HmiEventV1>,
    speech_taken: bool,
}

struct Shared {
    binding: HmiBindingV1,
    connection_id: u64,
    timeout: Duration,
    request_id: AtomicI64,
    state: Mutex<State>,
}

/// Cloneable narrow requests; the caller must retain the authenticated owner.
#[derive(Clone)]
pub struct HmiRequestsV1 {
    handle: RemoteAppServerRequestHandle,
    shared: Arc<Shared>,
}

/// Sole receiver for the bounded connection; one owner drains it continuously.
pub struct HmiEventsV1 {
    client: RemoteAppServerClient,
    shared: Arc<Shared>,
    ended: bool,
}

pub struct HmiConnectionV1 {
    pub requests: HmiRequestsV1,
    pub events: HmiEventsV1,
}

impl HmiConnectionV1 {
    /// Attach only to the exact existing thread. No thread/start or model request
    /// occurs here. The host must authenticate the endpoint and current grant.
    pub async fn connect(
        args: RemoteAppServerConnectArgs,
        binding: HmiBindingV1,
        event_capacity: usize,
        deadline: Duration,
    ) -> Result<Self, HmiError> {
        if binding.organ_generation == 0
            || binding.device_generation == 0
            || deadline.is_zero()
            || deadline > Duration::from_secs(60)
            || [
                &binding.principal_id,
                &binding.device_id,
                &binding.organ_id,
                &binding.logical_session_id,
                &binding.thread_id,
                &binding.app_server_session_id,
                &binding.codex_home,
                &binding.app_server_version,
            ]
            .iter()
            .any(|value| value.is_empty() || value.len() > 4096)
        {
            return Err(HmiError::Invalid("binding or deadline"));
        }
        let client = tokio::time::timeout(
            deadline,
            RemoteAppServerClient::connect_with_bounded_events(args, event_capacity),
        )
        .await
        .map_err(|_| HmiError::Deadline)?
        .map_err(|error| HmiError::Transport(error.to_string()))?;
        if client.codex_home() != Some(binding.codex_home.as_str())
            || client.server_version() != Some(binding.app_server_version.as_str())
        {
            let _ = tokio::time::timeout(deadline, client.shutdown()).await;
            return Err(HmiError::Identity);
        }
        let shared = Arc::new(Shared {
            binding,
            connection_id: client.connection_id(),
            timeout: deadline,
            request_id: AtomicI64::new(1),
            state: Mutex::new(State {
                fenced: false,
                epoch: 1,
                output_enabled: false,
                cancel_requested: false,
                queued_id: None,
                sequence: 0,
                pending: None,
                active_turn: None,
                items: Vec::new(),
                terminal: None,
                speech_taken: false,
            }),
        });
        let requests = HmiRequestsV1 {
            handle: client.request_handle(),
            shared: shared.clone(),
        };
        let response: Result<ThreadResumeResponse, HmiError> = requests
            .call(ClientRequest::ThreadResume {
                request_id: requests.id(),
                params: ThreadResumeParams {
                    thread_id: requests.shared.binding.thread_id.clone(),
                    exclude_turns: true,
                    ..Default::default()
                },
            })
            .await;
        let valid = response.as_ref().is_ok_and(|response| {
            response.thread.id == shared.binding.thread_id
                && response.thread.session_id == shared.binding.app_server_session_id
                && !response.thread.ephemeral
        });
        if !valid {
            let _ = tokio::time::timeout(deadline, client.shutdown()).await;
            return Err(response.err().unwrap_or(HmiError::Identity));
        }
        Ok(Self {
            requests,
            events: HmiEventsV1 {
                client,
                shared,
                ended: false,
            },
        })
    }

    /// Fence every old handle, reattach/resubscribe the same thread, and leave
    /// output closed until a fresh admission is explicitly observed. No replay.
    pub async fn reconnect(
        self,
        args: RemoteAppServerConnectArgs,
        event_capacity: usize,
    ) -> Result<Self, HmiError> {
        let binding = self.requests.shared.binding.clone();
        let deadline = self.requests.shared.timeout;
        self.requests.revoke()?;
        let _ = tokio::time::timeout(deadline, self.events.client.shutdown()).await;
        Self::connect(args, binding, event_capacity, deadline).await
    }
}

fn output_scope(shared: &Shared, state: &State) -> HmiOutputScopeV1 {
    HmiOutputScopeV1 {
        principal_id: shared.binding.principal_id.clone(),
        device_id: shared.binding.device_id.clone(),
        device_generation: shared.binding.device_generation,
        organ_id: shared.binding.organ_id.clone(),
        logical_session_id: shared.binding.logical_session_id.clone(),
        utterance_sequence: state.sequence,
        utterance_id: state
            .pending
            .as_ref()
            .map(|(client_id, _)| client_id.clone()),
        organ_generation: shared.binding.organ_generation,
        connection_id: shared.connection_id,
        output_epoch: state.epoch,
        turn_id: state.active_turn.clone(),
    }
}

fn terminal_is_known(state: &State) -> bool {
    state.terminal.as_ref().is_some_and(|event| {
        matches!(&event.kind,
        HmiEventKindV1::Terminal { outcome } if outcome.status != HmiTerminalStatusV1::Unknown)
    })
}

fn terminal(
    state: &mut State,
    scope: HmiOutputScopeV1,
    status: HmiTerminalStatusV1,
    error: Option<String>,
) -> HmiEventV1 {
    let outcome = HmiTerminalV1 {
        status,
        generated_text: state
            .items
            .iter()
            .map(|(_, text)| text.as_str())
            .collect::<Vec<_>>()
            .join("\n"),
        error: error.map(|text| text.chars().take(4096).collect()),
    };
    let event = HmiEventV1 {
        scope,
        kind: HmiEventKindV1::Terminal { outcome },
    };
    state.terminal = Some(event.clone());
    event
}

#[cfg(test)]
#[path = "hmi_tests.rs"]
mod tests;

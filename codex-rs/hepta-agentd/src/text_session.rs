//! One authenticated Agentd text route attached to its existing App Server.
//!
//! The independent human-facing host retains/signs envelopes. This client owns
//! only bounded, transient correlation: Agentd owns AuthBus admission and relay,
//! and Core owns the queue, conversation, tools, artifacts, and cancellation.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::atomic::AtomicI64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_client::RemoteAppServerRequestHandle;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::SortDirection;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadItemsListParams;
use codex_app_server_protocol::ThreadItemsListResponse;
use codex_app_server_protocol::ThreadQueueDeleteParams;
use codex_app_server_protocol::ThreadQueueDeleteResponse;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadTurnsListParams;
use codex_app_server_protocol::ThreadTurnsListResponse;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnInterruptResponse;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_contracts::AgentId;
use codex_protocol::user_input::user_input_payload_sha256;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdClient;
use crate::AuthBusTextIngress;
use crate::AuthBusTextStatus;

#[path = "text_session_events.rs"]
mod events;
#[path = "text_session_history.rs"]
mod history;
#[path = "text_session_requests.rs"]
mod requests;
pub use events::AgentdTextEvent;
pub use events::AgentdTextEvents;
pub use history::TextHistorySnapshot;
#[path = "text_session_worker.rs"]
mod worker;
pub use worker::AgentdTextWorker;
pub use worker::TextCommand;
pub use worker::TextPrepared;
pub use worker::TextSignerEndpoint;
pub use worker::TextWorkerEvent;
#[path = "text_session_auth.rs"]
mod auth;
pub use auth::TextOwnerReceipt;
pub(crate) use signer::TextUnsignedClosure;
#[path = "text_session_approvals.rs"]
mod approvals;
#[path = "text_session_signer.rs"]
mod signer;
pub use approvals::TextApproval;
pub use approvals::TextApprovalDecision;
pub use approvals::TextApprovalObservation;
pub use events::AgentdTextObservation;
#[path = "text_session_provider.rs"]
mod provider;
pub use provider::ProviderAccountDiagnostic;
pub use provider::ProviderLoginChallenge;
pub use provider::diagnose_existing_provider;
pub use provider::login_existing_provider;

const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_RETAINED: usize = 32;
const MAX_OBSERVATION_BYTES: usize = 256 * 1024;

/// Installed by the authenticated host, never accepted from a chat message.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct AgentdTextSessionConfig {
    pub control_socket: PathBuf,
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub thread_id: String,
    pub app_server_session_id: String,
    pub codex_home: PathBuf,
}

#[derive(Debug, thiserror::Error)]
pub enum TextSessionError {
    /// Only this request attempt is proven not to have written a byte. A
    /// previous ambiguous attempt must still be reconciled at the Root owner.
    #[error("text request was not transmitted: {0}")]
    NotTransmitted(String),
    #[error("text session is unavailable: {0}")]
    Unavailable(String),
    #[error("text session identity mismatch")]
    Identity,
    #[error("text session connection has been fenced; reconnect and reconcile")]
    Fenced,
    #[error("text session capacity or observation bound reached")]
    Capacity,
    #[error("text session request is not retained")]
    UnknownRequest,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TextReconciliation {
    pub message_id: String,
    pub delivery: Option<AuthBusTextStatus>,
    pub queue: ThreadQueueReconcileOutcome,
    /// An authoritative replacement snapshot, not additional streaming deltas.
    pub turn: Option<Turn>,
}

#[derive(Clone)]
struct Pending {
    envelope: AuthBusTextIngress,
    delivery_id: String,
    client_id: String,
    input: Vec<UserInput>,
    input_digest: String,
    turn_id: Option<String>,
    cancellation_requested: bool,
    terminal: bool,
    recovered: bool,
}

#[derive(Default, Clone)]
struct State {
    fenced: bool,
    pending: BTreeMap<String, Pending>,
    // Turns projected from full owner snapshots have no compatible delta
    // replay cursor. Keep refreshing their original full snapshots instead.
    snapshot_turns: BTreeMap<String, bool>,
    stream_bytes: BTreeMap<String, usize>,
    approvals: BTreeMap<String, approvals::PendingApproval>,
}

struct Shared {
    config: AgentdTextSessionConfig,
    control: AgentdClient,
    ingress_socket: PathBuf,
    connection_id: u64,
    request_id: AtomicI64,
    state: Mutex<State>,
}

impl Shared {
    fn state(&self) -> Result<MutexGuard<'_, State>, TextSessionError> {
        self.state.lock().map_err(|_| TextSessionError::Fenced)
    }
    fn current(&self) -> Result<MutexGuard<'_, State>, TextSessionError> {
        let state = self.state()?;
        if state.fenced {
            return Err(TextSessionError::Fenced);
        }
        Ok(state)
    }
}

#[derive(Clone)]
pub struct AgentdTextRequests {
    handle: RemoteAppServerRequestHandle,
    shared: Arc<Shared>,
}

pub struct AgentdTextSession {
    pub requests: AgentdTextRequests,
    pub events: AgentdTextEvents,
}

impl AgentdTextSession {
    /// Subscribes to one existing thread through Agentd's own session ingress.
    /// No thread, queue entry, signature, grant, or model call is created here.
    pub async fn connect(config: AgentdTextSessionConfig) -> Result<Self, TextSessionError> {
        if config.thread_id.is_empty()
            || config.thread_id.len() > 128
            || config.app_server_session_id.is_empty()
            || config.app_server_session_id.len() > 256
            || !config.codex_home.is_absolute()
        {
            return Err(TextSessionError::Identity);
        }
        let control = AgentdClient::new(
            config.control_socket.clone(),
            config.agent_id.clone(),
            config.spawn_generation,
        )
        .map_err(unavailable)?;
        let ingress = control.session_ingress().await.map_err(unavailable)?;
        let endpoint = RemoteAppServerEndpoint::UnixSocket {
            socket_path: ingress
                .socket_path
                .as_path()
                .try_into()
                .map_err(unavailable)?,
        };
        let client = tokio::time::timeout(
            REQUEST_TIMEOUT,
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint,
                    client_name: "hepta-authenticated-text-session".into(),
                    client_version: env!("CARGO_PKG_VERSION").into(),
                    experimental_api: true,
                    mcp_server_openai_form_elicitation: false,
                    opt_out_notification_methods: Vec::new(),
                    channel_capacity: 8,
                },
                /*event_channel_capacity*/ 128,
            ),
        )
        .await
        .map_err(unavailable)?
        .map_err(unavailable)?;
        if client.codex_home() != config.codex_home.to_str() {
            let _ = client.shutdown().await;
            return Err(TextSessionError::Identity);
        }
        let shared = Arc::new(Shared {
            config,
            control,
            ingress_socket: ingress.socket_path,
            connection_id: client.connection_id(),
            request_id: AtomicI64::new(1),
            state: Mutex::new(State::default()),
        });
        let requests = AgentdTextRequests {
            handle: client.request_handle(),
            shared: shared.clone(),
        };
        let response: ThreadResumeResponse = requests
            .call(ClientRequest::ThreadResume {
                request_id: requests.id(),
                params: ThreadResumeParams {
                    thread_id: shared.config.thread_id.clone(),
                    exclude_turns: true,
                    ..Default::default()
                },
            })
            .await?;
        if response.thread.id != shared.config.thread_id
            || response.thread.session_id != shared.config.app_server_session_id
            || response.thread.ephemeral
        {
            let _ = client.shutdown().await;
            return Err(TextSessionError::Identity);
        }
        Ok(Self {
            requests,
            events: AgentdTextEvents::start(client, shared),
        })
    }

    /// Fences old callbacks and keeps every exact signed identity. The caller
    /// supplies fresh installed generation data; pending inputs are looked up,
    /// never re-signed or implicitly submitted. Failure leaves the old owner
    /// fenced and its retained identities available for a subsequent attempt.
    pub async fn reattach(
        &self,
        config: AgentdTextSessionConfig,
    ) -> Result<Self, TextSessionError> {
        let old = &self.requests.shared.config;
        if config.agent_id != old.agent_id
            || config.thread_id != old.thread_id
            || config.app_server_session_id != old.app_server_session_id
            || config.codex_home != old.codex_home
            || config.spawn_generation < old.spawn_generation
        {
            return Err(TextSessionError::Identity);
        }
        let retained = {
            let mut state = self.requests.shared.state()?;
            state.fenced = true;
            let mut retained = state.pending.clone();
            for pending in retained.values_mut() {
                pending.recovered = true;
            }
            retained
        };
        let next = Self::connect(config).await?;
        next.requests.shared.state()?.pending = retained;
        Ok(next)
    }
}

fn unavailable(error: impl std::fmt::Display) -> TextSessionError {
    TextSessionError::Unavailable(error.to_string())
}

fn prepare(
    config: &AgentdTextSessionConfig,
    envelope: AuthBusTextIngress,
) -> Result<Pending, TextSessionError> {
    if envelope.body.thread_id != config.thread_id
        || envelope.body.spawn_generation == 0
        || envelope.body.spawn_generation > config.spawn_generation
    {
        return Err(TextSessionError::Identity);
    }
    let message = SignedMessage {
        claims: crate::authbus_text_claims(&config.agent_id, &envelope).map_err(unavailable)?,
        signature: crate::authbus_trust::hex_bytes(&envelope.signature_hex).map_err(unavailable)?,
    };
    let delivery_id = message.delivery_id().to_string();
    let input = vec![UserInput::Text {
        text: envelope.body.text.clone(),
        text_elements: Vec::new(),
    }];
    let core_input = input
        .iter()
        .cloned()
        .map(UserInput::into_core)
        .collect::<Vec<_>>();
    let input_digest = user_input_payload_sha256(&core_input).map_err(unavailable)?;
    Ok(Pending {
        envelope,
        client_id: format!("hepta.authbus:{delivery_id}"),
        delivery_id,
        input,
        input_digest,
        turn_id: None,
        cancellation_requested: false,
        terminal: false,
        recovered: false,
    })
}

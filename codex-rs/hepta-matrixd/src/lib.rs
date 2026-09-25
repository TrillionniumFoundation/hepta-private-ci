//! Transport-neutral Matrix-to-App-Server bridge for one Hepta workspace Agent.
//!
//! This crate owns neither Matrix synchronization nor durable inbox/outbox
//! storage.  It binds one Matrix room to one App Server project and one durable
//! Codex thread, then submits a canonical Matrix event through Codex's existing
//! persistent thread queue.  The remote adapter connects only through the
//! exact-generation `agentd` session ingress and uses a bounded event stream.
//!
//! Matrix events never implement an approval or cancellation authority here.

#![forbid(unsafe_code)]
#![recursion_limit = "256"]

/// Reusable state machine; does not install a second runtime owner.
pub mod send_observer;

mod config;
mod control;
mod runner;

use std::collections::BTreeMap;
use std::collections::HashSet;
use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::AtomicI64;
use std::sync::atomic::Ordering;

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_client::RemoteAppServerRequestHandle;
use codex_app_server_client::TypedRequestError;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::CommandExecutionApprovalDecision;
use codex_app_server_protocol::CommandExecutionRequestApprovalResponse;
use codex_app_server_protocol::FileChangeApprovalDecision;
use codex_app_server_protocol::FileChangeRequestApprovalResponse;
use codex_app_server_protocol::ProjectCreateParams;
use codex_app_server_protocol::ProjectCreateResponse;
use codex_app_server_protocol::ProjectRoot;
use codex_app_server_protocol::QueuedSubmission;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::SortDirection;
use codex_app_server_protocol::ThreadHistoryMode;
use codex_app_server_protocol::ThreadListCwdFilter;
use codex_app_server_protocol::ThreadListParams;
use codex_app_server_protocol::ThreadListResponse;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadSortKey;
use codex_app_server_protocol::ThreadSource;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnInterruptResponse;
use codex_app_server_protocol::UserInput;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::SessionTransport;
use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::LocalApprovalDecision;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::client_user_message_id;
use codex_hepta_matrix_protocol::room_project_idempotency_key;
use codex_hepta_matrix_store::PendingApprovalKind;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::sync::Semaphore;

mod runtime;

pub use config::HEPTA_MATRIX_ALLOWED_ROOMS_ENV;
pub use config::HEPTA_MATRIX_ALLOWED_SENDERS_ENV;
pub use config::HEPTA_MATRIX_BINDING_DIGEST_ENV;
pub use config::HEPTA_MATRIX_BINDING_REVISION_ENV;
pub use config::HEPTA_MATRIX_DEVICE_DISPLAY_NAME_ENV;
pub use config::HEPTA_MATRIX_DEVICE_ID_ENV;
pub use config::HEPTA_MATRIX_HOMESERVER_ENV;
pub use config::HEPTA_MATRIX_PASSWORD_ENV;
pub use config::HEPTA_MATRIX_PLANE_EPOCH_ENV;
pub use config::HEPTA_MATRIX_PROCESS_INCARNATION_ENV;
pub use config::HEPTA_MATRIX_RELEASE_ID_ENV;
pub use config::HEPTA_MATRIX_REQUIRE_EXPLICIT_MENTION_ENV;
pub use config::HEPTA_MATRIX_STORE_PASSPHRASE_ENV;
pub use config::HEPTA_MATRIX_SYNC_TIMELINE_LIMIT_ENV;
pub use config::HEPTA_MATRIX_SYNC_TIMEOUT_MS_ENV;
pub use config::HEPTA_MATRIX_USER_ID_ENV;
pub use config::MatrixdConfig;
pub use config::MatrixdConfigError;
pub use config::MatrixdCredentials;
pub use config::MatrixdProcessIdentity;
pub use runner::MatrixdRunError;
pub use runner::run;

pub use runtime::MatrixDispatchOutcome;
pub use runtime::MatrixEventProjection;
pub use runtime::MatrixRuntime;
pub use runtime::MatrixRuntimeBridge;
pub use runtime::MatrixRuntimeError;
pub use runtime::MatrixRuntimeFuture;
pub use runtime::MatrixRuntimeRecovery;

const BRIDGE_SCHEMA: &str = "hepta.matrix.bridge.v1";
const BRIDGE_THREAD_SOURCE: &str = "hepta.matrix";
const DEFAULT_PAGE_SIZE: u32 = 100;
const DEFAULT_COMMAND_CAPACITY: usize = 64;
const DEFAULT_EVENT_CAPACITY: usize = 512;
const MAX_RECONCILIATION_PAGES: usize = 1_024;
const JSON_RPC_INVALID_REQUEST_CODE: i64 = -32_600;

/// The strongest admission guarantee this bridge and Core queue jointly make.
///
/// This covers model-turn admission for one stable Matrix client message id,
/// not Matrix delivery or arbitrary external tool effects. Queue dispatch
/// waits for rollout persistence before deleting a row and, after a crash,
/// removes any stale duplicate row only when the durable client id and the
/// canonical digest of the complete ordered user input both match. Reusing a
/// client id for different content fails closed before a new queue admission.
pub const DELIVERY_GUARANTEE: DeliveryGuarantee =
    DeliveryGuarantee::ExactlyOncePersistedCoreAdmissionPerClientMessageId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeliveryGuarantee {
    ExactlyOncePersistedCoreAdmissionPerClientMessageId,
}

pub type BridgeFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, MatrixBridgeError>> + Send + 'a>>;

/// Narrow App Server surface consumed by the deterministic bridge core.
///
/// A durable Matrix store can use [`MatrixAppServerBridge`] with this trait
/// without depending on the remote socket implementation or on Matrix SDK
/// types. Thread discovery preserves opaque pagination cursors; exact message
/// admission is deliberately exposed only as one atomic reconcile RPC.
pub trait MatrixAppServerTransport: Send + Sync {
    fn create_project(&self, request: BridgeProjectCreate) -> BridgeFuture<'_, BridgeProject>;

    fn list_threads(&self, request: BridgeThreadList)
    -> BridgeFuture<'_, BridgePage<BridgeThread>>;

    fn start_thread(&self, request: BridgeThreadStart) -> BridgeFuture<'_, BridgeThread>;

    /// Single App Server correctness RPC. Implementations must not decompose
    /// this into queue/history scans followed by queue/add.
    fn reconcile_queue(
        &self,
        request: BridgeQueueReconcile,
    ) -> BridgeFuture<'_, BridgeQueueReconcileResponse>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BridgeProjectCreate {
    pub name: String,
    pub roots: Vec<AbsolutePathBuf>,
    pub metadata: BTreeMap<String, String>,
    pub idempotency_key: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BridgeProject {
    pub id: String,
    pub roots: Vec<AbsolutePathBuf>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BridgeThreadList {
    pub project_id: String,
    pub cwd: AbsolutePathBuf,
    pub cursor: Option<String>,
    pub limit: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BridgeThreadStart {
    pub project_id: String,
    pub cwd: AbsolutePathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BridgeThread {
    pub id: String,
    pub project_id: Option<String>,
    pub cwd: AbsolutePathBuf,
    pub ephemeral: bool,
    pub thread_source: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BridgeQueueReconcile {
    pub thread_id: String,
    pub input: Vec<UserInput>,
    pub client_user_message_id: String,
    pub expected_payload_sha256: String,
    pub mode: MatrixAdmissionMode,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BridgeQueueReconcileOutcome {
    Queued {
        queued_submission: BridgeQueuedSubmission,
        created: bool,
    },
    Persisted {
        turn_id: String,
    },
    Missing,
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BridgeQueueReconcileResponse {
    pub client_user_message_id: String,
    pub payload_sha256: Option<String>,
    pub outcome: BridgeQueueReconcileOutcome,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BridgeQueuedSubmission {
    pub id: String,
    pub client_user_message_id: String,
    /// Canonical digest of the complete ordered user input. A missing digest
    /// is readable for compatibility but cannot authorize reconciliation.
    pub payload_sha256: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BridgePage<T> {
    pub data: Vec<T>,
    pub next_cursor: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoomThreadBinding {
    pub project_id: String,
    pub thread_id: String,
    /// True when `thread/list` recovered the thread rather than this call
    /// issuing `thread/start`.
    pub recovered: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixSubmission {
    pub binding: RoomThreadBinding,
    pub client_user_message_id: String,
    pub state: MatrixSubmissionState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MatrixSubmissionState {
    Queued { queued_submission_id: String },
    ReconciledQueued { queued_submission_id: String },
    ReconciledTurn { turn_id: String },
}

/// Whether a bridge retry may create a new Core queue row when reconciliation
/// finds neither a queued submission nor a persisted turn.
///
/// A durable dispatch that already recorded `queued` or `admitted` must use
/// [`MatrixAdmissionMode::ReconcileOnly`].  Treating a missing Core record as
/// permission to submit again would weaken the exactly-once admission bound.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixAdmissionMode {
    AllowIfAbsent,
    ReconcileOnly,
}

#[derive(Clone, Debug)]
pub struct MatrixBridgeConfig {
    pub agent_id: AgentId,
    pub workspace_root: AbsolutePathBuf,
    pub page_size: u32,
}

impl MatrixBridgeConfig {
    pub fn new(agent_id: AgentId, workspace_root: AbsolutePathBuf) -> Self {
        Self {
            agent_id,
            workspace_root,
            page_size: DEFAULT_PAGE_SIZE,
        }
    }

    pub fn validate(&self) -> Result<(), MatrixBridgeError> {
        if self.page_size == 0 {
            return Err(MatrixBridgeError::Invalid(
                "Matrix bridge page size must be non-zero".to_string(),
            ));
        }
        Ok(())
    }
}

/// Deterministic room/thread and message-submission core.
///
/// The single permit is intentionally process-local. Product wiring must still
/// run a single fenced `matrixd` for one Agent generation; it is not a
/// distributed lock and never creates a central gateway.
pub struct MatrixAppServerBridge<T> {
    config: MatrixBridgeConfig,
    transport: T,
    operation: Semaphore,
}

impl<T> MatrixAppServerBridge<T>
where
    T: MatrixAppServerTransport,
{
    pub fn new(config: MatrixBridgeConfig, transport: T) -> Result<Self, MatrixBridgeError> {
        config.validate()?;
        Ok(Self {
            config,
            transport,
            operation: Semaphore::new(1),
        })
    }

    pub fn config(&self) -> &MatrixBridgeConfig {
        &self.config
    }

    pub fn transport(&self) -> &T {
        &self.transport
    }

    pub async fn ensure_room_thread(
        &self,
        room_id: &MatrixRoomId,
    ) -> Result<RoomThreadBinding, MatrixBridgeError> {
        let _operation = self.operation.acquire().await.map_err(|_| {
            MatrixBridgeError::Protocol("Matrix bridge operation gate closed".to_string())
        })?;
        self.ensure_room_thread_locked(room_id, /*expected_thread_id*/ None)
            .await
    }

    /// Recover an already-durable room/thread identity without creating a
    /// replacement when App Server has not materialized the first thread yet.
    ///
    /// `thread/list` intentionally omits a newly started thread until its
    /// first user message is materialized.  The Matrix durable store is the
    /// restart authority for the exact thread ID during that interval.  A
    /// caller supplying that ID must therefore reconcile it, never interpret
    /// an empty list as permission to start another thread.
    pub async fn reconcile_room_thread(
        &self,
        room_id: &MatrixRoomId,
        expected_thread_id: &str,
    ) -> Result<RoomThreadBinding, MatrixBridgeError> {
        if expected_thread_id.is_empty() {
            return Err(MatrixBridgeError::Invalid(
                "durable Matrix thread identity cannot be empty".to_string(),
            ));
        }
        let _operation = self.operation.acquire().await.map_err(|_| {
            MatrixBridgeError::Protocol("Matrix bridge operation gate closed".to_string())
        })?;
        self.ensure_room_thread_locked(room_id, Some(expected_thread_id))
            .await
    }

    pub async fn submit_matrix_event(
        &self,
        room_id: &MatrixRoomId,
        event_id: &MatrixEventId,
        input: Vec<UserInput>,
    ) -> Result<MatrixSubmission, MatrixBridgeError> {
        let _operation = self.operation.acquire().await.map_err(|_| {
            MatrixBridgeError::Protocol("Matrix bridge operation gate closed".to_string())
        })?;
        let binding = self
            .ensure_room_thread_locked(room_id, /*expected_thread_id*/ None)
            .await?;
        self.submit_matrix_event_on_binding_locked(
            room_id,
            event_id,
            input,
            &binding,
            MatrixAdmissionMode::AllowIfAbsent,
        )
        .await
    }

    /// Submit or reconcile one event against an already persisted exact room
    /// binding.  Runtime recovery uses `ReconcileOnly` after it has durably
    /// observed a Core queue/turn identity.
    pub(crate) async fn submit_matrix_event_on_binding(
        &self,
        room_id: &MatrixRoomId,
        event_id: &MatrixEventId,
        input: Vec<UserInput>,
        binding: &RoomThreadBinding,
        admission_mode: MatrixAdmissionMode,
    ) -> Result<MatrixSubmission, MatrixBridgeError> {
        let _operation = self.operation.acquire().await.map_err(|_| {
            MatrixBridgeError::Protocol("Matrix bridge operation gate closed".to_string())
        })?;
        self.submit_matrix_event_on_binding_locked(
            room_id,
            event_id,
            input,
            binding,
            admission_mode,
        )
        .await
    }

    async fn submit_matrix_event_on_binding_locked(
        &self,
        room_id: &MatrixRoomId,
        event_id: &MatrixEventId,
        input: Vec<UserInput>,
        binding: &RoomThreadBinding,
        admission_mode: MatrixAdmissionMode,
    ) -> Result<MatrixSubmission, MatrixBridgeError> {
        if input.is_empty() {
            return Err(MatrixBridgeError::Invalid(
                "Matrix event cannot submit empty user input".to_string(),
            ));
        }
        if !input
            .iter()
            .all(|item| matches!(item, UserInput::Text { .. }))
        {
            return Err(MatrixBridgeError::Invalid(
                "G4 Matrix admission accepts text input only".to_string(),
            ));
        }
        if binding.project_id.is_empty() || binding.thread_id.is_empty() {
            return Err(MatrixBridgeError::Protocol(
                "Matrix submission binding has an empty project or thread identity".to_string(),
            ));
        }
        let client_id = client_user_message_id(&self.config.agent_id, room_id, event_id);
        let payload_sha256 = bridge_user_input_payload_sha256(&input)?;
        let response = self
            .transport
            .reconcile_queue(BridgeQueueReconcile {
                thread_id: binding.thread_id.clone(),
                input,
                client_user_message_id: client_id.clone(),
                expected_payload_sha256: payload_sha256.clone(),
                mode: admission_mode,
            })
            .await?;
        if response.client_user_message_id != client_id {
            return Err(MatrixBridgeError::Protocol(
                "thread/queue/reconcile returned a mismatched client message identity".to_string(),
            ));
        }
        ensure_bridge_payload_digest(
            "thread/queue/reconcile response",
            &client_id,
            &payload_sha256,
            response.payload_sha256.as_deref(),
        )?;
        let state = match response.outcome {
            BridgeQueueReconcileOutcome::Queued {
                queued_submission,
                created,
            } => {
                if queued_submission.client_user_message_id != client_id
                    || queued_submission.id.is_empty()
                {
                    return Err(MatrixBridgeError::Protocol(
                        "thread/queue/reconcile returned a mismatched or empty queue identity"
                            .to_string(),
                    ));
                }
                ensure_bridge_payload_digest(
                    "thread/queue/reconcile queued submission",
                    &client_id,
                    &payload_sha256,
                    queued_submission.payload_sha256.as_deref(),
                )?;
                if created {
                    MatrixSubmissionState::Queued {
                        queued_submission_id: queued_submission.id,
                    }
                } else {
                    MatrixSubmissionState::ReconciledQueued {
                        queued_submission_id: queued_submission.id,
                    }
                }
            }
            BridgeQueueReconcileOutcome::Persisted { turn_id } => {
                if turn_id.is_empty() {
                    return Err(MatrixBridgeError::Protocol(
                        "thread/queue/reconcile returned an empty persisted turn identity"
                            .to_string(),
                    ));
                }
                MatrixSubmissionState::ReconciledTurn { turn_id }
            }
            BridgeQueueReconcileOutcome::Missing | BridgeQueueReconcileOutcome::Cancelled => {
                return Err(MatrixBridgeError::Protocol(format!(
                    "durable client message id {client_id} is missing or cancelled in Core reconciliation authority"
                )));
            }
        };
        Ok(MatrixSubmission {
            binding: binding.clone(),
            client_user_message_id: client_id,
            state,
        })
    }

    async fn ensure_room_thread_locked(
        &self,
        room_id: &MatrixRoomId,
        expected_thread_id: Option<&str>,
    ) -> Result<RoomThreadBinding, MatrixBridgeError> {
        let project_request = self.project_request(room_id);
        let project = self
            .transport
            .create_project(project_request.clone())
            .await?;
        validate_project(&project, &project_request)?;

        let mut cursor = None;
        let mut cursors = HashSet::new();
        let mut matches = Vec::new();
        let mut exhausted = false;
        for _ in 0..MAX_RECONCILIATION_PAGES {
            let page = self
                .transport
                .list_threads(BridgeThreadList {
                    project_id: project.id.clone(),
                    cwd: self.config.workspace_root.clone(),
                    cursor: cursor.clone(),
                    limit: self.config.page_size,
                })
                .await?;
            for thread in page.data {
                validate_thread(&thread, &project.id, &self.config.workspace_root)?;
                matches.push(thread);
            }
            let Some(next) = page.next_cursor else {
                exhausted = true;
                break;
            };
            if !cursors.insert(next.clone()) {
                return Err(MatrixBridgeError::Protocol(
                    "thread/list repeated a pagination cursor".to_string(),
                ));
            }
            cursor = Some(next);
        }
        if !exhausted {
            return Err(MatrixBridgeError::Protocol(
                "thread/list exceeded the reconciliation page bound".to_string(),
            ));
        }
        if let Some(expected_thread_id) = expected_thread_id {
            return match matches.as_slice() {
                [] => Ok(RoomThreadBinding {
                    project_id: project.id,
                    thread_id: expected_thread_id.to_string(),
                    recovered: true,
                }),
                [thread] if thread.id == expected_thread_id => Ok(RoomThreadBinding {
                    project_id: project.id,
                    thread_id: thread.id.clone(),
                    recovered: true,
                }),
                [thread] => Err(MatrixBridgeError::Protocol(format!(
                    "App Server Matrix room thread {} disagrees with durable thread {expected_thread_id}",
                    thread.id
                ))),
                _ => Err(MatrixBridgeError::Protocol(format!(
                    "Matrix room project {} has multiple active bridge threads",
                    project.id
                ))),
            };
        }

        match matches.as_slice() {
            [thread] => Ok(RoomThreadBinding {
                project_id: project.id,
                thread_id: thread.id.clone(),
                recovered: true,
            }),
            [] => {
                let thread = self
                    .transport
                    .start_thread(BridgeThreadStart {
                        project_id: project.id.clone(),
                        cwd: self.config.workspace_root.clone(),
                    })
                    .await?;
                validate_thread(&thread, &project.id, &self.config.workspace_root)?;
                Ok(RoomThreadBinding {
                    project_id: project.id,
                    thread_id: thread.id,
                    recovered: false,
                })
            }
            _ => Err(MatrixBridgeError::Protocol(format!(
                "Matrix room project {} has multiple active bridge threads",
                project.id
            ))),
        }
    }

    fn project_request(&self, room_id: &MatrixRoomId) -> BridgeProjectCreate {
        let key = room_project_idempotency_key(&self.config.agent_id, room_id);
        let suffix = key.rsplit('-').next().unwrap_or(key.as_str());
        let short_suffix = suffix.get(..16).unwrap_or(suffix);
        BridgeProjectCreate {
            name: format!("Hepta Matrix {short_suffix}"),
            roots: vec![self.config.workspace_root.clone()],
            metadata: BTreeMap::from([
                ("hepta.bridge".to_string(), BRIDGE_SCHEMA.to_string()),
                (
                    "hepta.agent_id".to_string(),
                    self.config.agent_id.as_str().to_string(),
                ),
                ("hepta.matrix.room_id".to_string(), room_id.to_string()),
            ]),
            idempotency_key: key,
        }
    }
}

fn validate_project(
    project: &BridgeProject,
    request: &BridgeProjectCreate,
) -> Result<(), MatrixBridgeError> {
    if project.id.is_empty()
        || project.roots != request.roots
        || project.metadata != request.metadata
    {
        return Err(MatrixBridgeError::Protocol(
            "project/create returned a project outside the exact Agent/room binding".to_string(),
        ));
    }
    Ok(())
}

fn validate_thread(
    thread: &BridgeThread,
    project_id: &str,
    workspace_root: &AbsolutePathBuf,
) -> Result<(), MatrixBridgeError> {
    if thread.id.is_empty()
        || thread.ephemeral
        || thread.project_id.as_deref() != Some(project_id)
        || &thread.cwd != workspace_root
        || thread.thread_source.as_deref() != Some(BRIDGE_THREAD_SOURCE)
    {
        return Err(MatrixBridgeError::Protocol(
            "App Server returned a thread outside the exact Matrix room binding".to_string(),
        ));
    }
    Ok(())
}

/// Exact-generation connection settings for one Agent's App Server ingress.
#[derive(Clone, Debug)]
pub struct MatrixAgentdConnectArgs {
    pub agentd_control_socket: PathBuf,
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub client_version: String,
    pub command_channel_capacity: usize,
    pub event_channel_capacity: usize,
}

impl MatrixAgentdConnectArgs {
    pub fn new(
        agentd_control_socket: PathBuf,
        agent_id: AgentId,
        spawn_generation: u64,
        client_version: impl Into<String>,
    ) -> Self {
        Self {
            agentd_control_socket,
            agent_id,
            spawn_generation,
            client_version: client_version.into(),
            command_channel_capacity: DEFAULT_COMMAND_CAPACITY,
            event_channel_capacity: DEFAULT_EVENT_CAPACITY,
        }
    }
}

pub struct ConnectedMatrixAppServer {
    pub transport: RemoteMatrixAppServerTransport,
    pub events: RemoteMatrixAppServerEvents,
}

/// Connects through `AgentdClient::session_ingress`; direct fleet-wide routing
/// or a central execution gateway is intentionally absent.
pub async fn connect_via_agentd(
    args: MatrixAgentdConnectArgs,
) -> Result<ConnectedMatrixAppServer, MatrixBridgeError> {
    if args.client_version.is_empty()
        || args.command_channel_capacity == 0
        || args.event_channel_capacity == 0
    {
        return Err(MatrixBridgeError::Invalid(
            "matrixd App Server connection requires non-empty version and bounded capacities"
                .to_string(),
        ));
    }
    let agentd = AgentdClient::new(
        args.agentd_control_socket,
        args.agent_id.clone(),
        args.spawn_generation,
    )?;
    let health = agentd.health().await?;
    if !health.ready || health.fenced {
        return Err(MatrixBridgeError::Invalid(
            "matrixd cannot attach to an unready or fenced agentd generation".to_string(),
        ));
    }
    let ingress = agentd.session_ingress().await?;
    if ingress.transport != SessionTransport::CodexAppServerWebsocketOverUds {
        return Err(MatrixBridgeError::Protocol(
            "agentd returned an unsupported session ingress transport".to_string(),
        ));
    }
    let socket_path = AbsolutePathBuf::from_absolute_path(&ingress.socket_path)?;
    let client = RemoteAppServerClient::connect_with_bounded_events(
        RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
            client_name: "hepta-matrixd".to_string(),
            client_version: args.client_version,
            experimental_api: true,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: args.command_channel_capacity,
        },
        args.event_channel_capacity,
    )
    .await?;
    let expected_home = health.home_root.to_string_lossy();
    if client.codex_home() != Some(expected_home.as_ref()) {
        let actual = client.codex_home().unwrap_or("<missing>").to_string();
        let _ = client.shutdown().await;
        return Err(MatrixBridgeError::Protocol(format!(
            "App Server home {actual} does not match Agent home {expected_home}"
        )));
    }
    let request_handle = client.request_handle();
    Ok(ConnectedMatrixAppServer {
        transport: RemoteMatrixAppServerTransport {
            request_handle,
            next_request_id: Arc::new(AtomicI64::new(1)),
        },
        events: RemoteMatrixAppServerEvents { client },
    })
}

#[derive(Clone)]
pub struct RemoteMatrixAppServerTransport {
    request_handle: RemoteAppServerRequestHandle,
    next_request_id: Arc<AtomicI64>,
}

impl RemoteMatrixAppServerTransport {
    fn request_id(&self) -> RequestId {
        RequestId::Integer(self.next_request_id.fetch_add(1, Ordering::Relaxed))
    }

    async fn request<T>(&self, request: ClientRequest) -> Result<T, MatrixBridgeError>
    where
        T: serde::de::DeserializeOwned,
    {
        self.request_handle
            .request_typed(request)
            .await
            .map_err(|error| MatrixBridgeError::AppServer(error.to_string()))
    }

    async fn interrupt_turn(
        &self,
        thread_id: String,
        turn_id: String,
    ) -> Result<(), MatrixBridgeError> {
        let response: Result<TurnInterruptResponse, TypedRequestError> = self
            .request_handle
            .request_typed(ClientRequest::TurnInterrupt {
                request_id: self.request_id(),
                params: TurnInterruptParams { thread_id, turn_id },
            })
            .await;
        match response {
            Ok(_) => Ok(()),
            Err(TypedRequestError::Server { method, source })
                if method == "turn/interrupt"
                    && source.code == JSON_RPC_INVALID_REQUEST_CODE
                    && source.data.is_none()
                    && source.message == "no active turn to interrupt" =>
            {
                // A repeated cancellation after the turn terminal event is a
                // safe idempotent no-op. No other server error is weakened.
                Ok(())
            }
            Err(error) => Err(MatrixBridgeError::AppServer(error.to_string())),
        }
    }

    /// Reattach this connection to an existing Core thread.
    ///
    /// App Server subscriptions are connection-scoped. A matrixd reconnect
    /// therefore has to resume each durable room thread before it can recover
    /// queued Matrix work; otherwise Core may complete a turn while no
    /// connection is subscribed to the thread notifications.
    pub(crate) async fn resume_thread(
        &self,
        thread_id: &str,
    ) -> Result<ThreadResumeResponse, MatrixBridgeError> {
        self.request(ClientRequest::ThreadResume {
            request_id: self.request_id(),
            params: ThreadResumeParams {
                thread_id: thread_id.to_string(),
                exclude_turns: true,
                ..ThreadResumeParams::default()
            },
        })
        .await
    }

    async fn resolve_approval(
        &self,
        request_id: RequestId,
        request_kind: PendingApprovalKind,
        decision: LocalApprovalDecision,
    ) -> Result<(), MatrixBridgeError> {
        let result = match request_kind {
            PendingApprovalKind::CommandExecution => {
                serde_json::to_value(CommandExecutionRequestApprovalResponse {
                    decision: command_approval_decision(decision),
                })
            }
            PendingApprovalKind::FileChange => {
                serde_json::to_value(FileChangeRequestApprovalResponse {
                    decision: file_change_approval_decision(decision),
                })
            }
        }
        .map_err(|error| MatrixBridgeError::Protocol(error.to_string()))?;
        self.request_handle
            .resolve_server_request(request_id, result)
            .await
            .map_err(MatrixBridgeError::Io)
    }

    async fn reject_server_request(
        &self,
        request_id: RequestId,
        code: i64,
        message: String,
    ) -> Result<(), MatrixBridgeError> {
        self.request_handle
            .reject_server_request(
                request_id,
                codex_app_server_protocol::JSONRPCErrorError {
                    code,
                    data: None,
                    message,
                },
            )
            .await
            .map_err(MatrixBridgeError::Io)
    }
}

fn command_approval_decision(decision: LocalApprovalDecision) -> CommandExecutionApprovalDecision {
    match decision {
        LocalApprovalDecision::Accept => CommandExecutionApprovalDecision::Accept,
        LocalApprovalDecision::AcceptForSession => {
            CommandExecutionApprovalDecision::AcceptForSession
        }
        LocalApprovalDecision::Decline => CommandExecutionApprovalDecision::Decline,
        LocalApprovalDecision::Cancel => CommandExecutionApprovalDecision::Cancel,
    }
}

fn file_change_approval_decision(decision: LocalApprovalDecision) -> FileChangeApprovalDecision {
    match decision {
        LocalApprovalDecision::Accept => FileChangeApprovalDecision::Accept,
        LocalApprovalDecision::AcceptForSession => FileChangeApprovalDecision::AcceptForSession,
        LocalApprovalDecision::Decline => FileChangeApprovalDecision::Decline,
        LocalApprovalDecision::Cancel => FileChangeApprovalDecision::Cancel,
    }
}

pub struct RemoteMatrixAppServerEvents {
    client: RemoteAppServerClient,
}

impl RemoteMatrixAppServerEvents {
    pub fn server_version(&self) -> Option<&str> {
        self.client.server_version()
    }

    pub fn codex_home(&self) -> Option<&str> {
        self.client.codex_home()
    }

    pub async fn next_event(&mut self) -> Option<AppServerEvent> {
        self.client.next_event().await
    }

    pub async fn shutdown(self) -> std::io::Result<()> {
        self.client.shutdown().await
    }
}

impl MatrixAppServerTransport for RemoteMatrixAppServerTransport {
    fn create_project(&self, request: BridgeProjectCreate) -> BridgeFuture<'_, BridgeProject> {
        Box::pin(async move {
            let response: ProjectCreateResponse = self
                .request(ClientRequest::ProjectCreate {
                    request_id: self.request_id(),
                    params: ProjectCreateParams {
                        name: request.name,
                        roots: request
                            .roots
                            .into_iter()
                            .map(|path| ProjectRoot { path })
                            .collect(),
                        metadata: Some(request.metadata),
                        idempotency_key: request.idempotency_key,
                    },
                })
                .await?;
            Ok(BridgeProject {
                id: response.project.id,
                roots: response
                    .project
                    .roots
                    .into_iter()
                    .map(|root| root.path)
                    .collect(),
                metadata: response.project.metadata,
            })
        })
    }

    fn list_threads(
        &self,
        request: BridgeThreadList,
    ) -> BridgeFuture<'_, BridgePage<BridgeThread>> {
        Box::pin(async move {
            let response: ThreadListResponse = self
                .request(ClientRequest::ThreadList {
                    request_id: self.request_id(),
                    params: ThreadListParams {
                        cursor: request.cursor,
                        limit: Some(request.limit),
                        sort_key: Some(ThreadSortKey::CreatedAt),
                        sort_direction: Some(SortDirection::Asc),
                        model_providers: None,
                        source_kinds: None,
                        archived: Some(false),
                        section_id: None,
                        project_id: Some(Some(request.project_id)),
                        cwd: Some(ThreadListCwdFilter::One(
                            request.cwd.as_path().to_string_lossy().into_owned(),
                        )),
                        use_state_db_only: false,
                        search_term: None,
                        parent_thread_id: None,
                        ancestor_thread_id: None,
                    },
                })
                .await?;
            Ok(BridgePage {
                data: response.data.into_iter().map(bridge_thread).collect(),
                next_cursor: response.next_cursor,
            })
        })
    }

    fn start_thread(&self, request: BridgeThreadStart) -> BridgeFuture<'_, BridgeThread> {
        Box::pin(async move {
            let cwd = request.cwd.as_path().to_string_lossy().into_owned();
            let response: ThreadStartResponse = self
                .request(ClientRequest::ThreadStart {
                    request_id: self.request_id(),
                    params: ThreadStartParams {
                        cwd: Some(cwd),
                        runtime_workspace_roots: Some(vec![request.cwd]),
                        ephemeral: Some(false),
                        history_mode: Some(ThreadHistoryMode::Paginated),
                        thread_source: Some(ThreadSource::Feature(
                            BRIDGE_THREAD_SOURCE.to_string(),
                        )),
                        project_id: Some(request.project_id),
                        ..Default::default()
                    },
                })
                .await?;
            Ok(bridge_thread(response.thread))
        })
    }

    fn reconcile_queue(
        &self,
        request: BridgeQueueReconcile,
    ) -> BridgeFuture<'_, BridgeQueueReconcileResponse> {
        Box::pin(async move {
            let response: ThreadQueueReconcileResponse = self
                .request(ClientRequest::ThreadQueueReconcile {
                    request_id: self.request_id(),
                    params: bridge_queue_reconcile_params(request),
                })
                .await?;
            bridge_queue_reconcile_response(response)
        })
    }
}

fn bridge_queue_reconcile_params(request: BridgeQueueReconcile) -> ThreadQueueReconcileParams {
    ThreadQueueReconcileParams {
        thread_id: request.thread_id,
        input: request.input,
        client_user_message_id: request.client_user_message_id,
        expected_payload_sha256: request.expected_payload_sha256,
        mode: match request.mode {
            MatrixAdmissionMode::AllowIfAbsent => ThreadQueueReconcileMode::AllowIfAbsent,
            MatrixAdmissionMode::ReconcileOnly => ThreadQueueReconcileMode::ReconcileOnly,
        },
    }
}

fn bridge_queue_reconcile_response(
    response: ThreadQueueReconcileResponse,
) -> Result<BridgeQueueReconcileResponse, MatrixBridgeError> {
    let outcome = match response.outcome {
        ThreadQueueReconcileOutcome::Queued {
            queued_submission,
            created,
        } => BridgeQueueReconcileOutcome::Queued {
            queued_submission: bridge_queued_submission(queued_submission)?,
            created,
        },
        ThreadQueueReconcileOutcome::Persisted { turn_id } => {
            BridgeQueueReconcileOutcome::Persisted { turn_id }
        }
        ThreadQueueReconcileOutcome::Missing => BridgeQueueReconcileOutcome::Missing,
        ThreadQueueReconcileOutcome::Cancelled => BridgeQueueReconcileOutcome::Cancelled,
    };
    Ok(BridgeQueueReconcileResponse {
        client_user_message_id: response.client_user_message_id,
        payload_sha256: Some(response.payload_sha256),
        outcome,
    })
}

fn bridge_thread(thread: codex_app_server_protocol::Thread) -> BridgeThread {
    BridgeThread {
        id: thread.id,
        project_id: thread.project_id,
        cwd: thread.cwd,
        ephemeral: thread.ephemeral,
        thread_source: match thread.thread_source {
            Some(ThreadSource::Feature(source)) => Some(source),
            _ => None,
        },
    }
}

fn bridge_queued_submission(
    queued: QueuedSubmission,
) -> Result<BridgeQueuedSubmission, MatrixBridgeError> {
    let payload_sha256 = bridge_user_input_payload_sha256(&queued.input)?;
    Ok(BridgeQueuedSubmission {
        id: queued.id,
        client_user_message_id: queued.client_user_message_id,
        payload_sha256: Some(payload_sha256),
    })
}

fn bridge_user_input_payload_sha256(input: &[UserInput]) -> Result<String, MatrixBridgeError> {
    let core_input = input
        .iter()
        .cloned()
        .map(UserInput::into_core)
        .collect::<Vec<_>>();
    user_input_payload_sha256(&core_input).map_err(|error| {
        MatrixBridgeError::Protocol(format!(
            "failed to canonicalize user input payload for reconciliation: {error}"
        ))
    })
}

fn ensure_bridge_payload_digest(
    source: &str,
    client_id: &str,
    expected_payload_sha256: &str,
    actual_payload_sha256: Option<&str>,
) -> Result<(), MatrixBridgeError> {
    let Some(actual_payload_sha256) = actual_payload_sha256.filter(|digest| !digest.is_empty())
    else {
        return Err(MatrixBridgeError::Protocol(format!(
            "{source} for client message id {client_id} has no canonical payload digest"
        )));
    };
    if actual_payload_sha256 != expected_payload_sha256 {
        return Err(MatrixBridgeError::Protocol(format!(
            "{source} for client message id {client_id} has payload digest {actual_payload_sha256}, expected {expected_payload_sha256}"
        )));
    }
    Ok(())
}

#[derive(Debug, thiserror::Error)]
pub enum MatrixBridgeError {
    #[error("invalid Matrix App Server bridge configuration: {0}")]
    Invalid(String),
    #[error("Matrix App Server protocol violation: {0}")]
    Protocol(String),
    #[error("Matrix App Server request failed: {0}")]
    AppServer(String),
    #[error(transparent)]
    Agentd(#[from] codex_hepta_agentd::AgentdError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

#[cfg(test)]
mod tests;

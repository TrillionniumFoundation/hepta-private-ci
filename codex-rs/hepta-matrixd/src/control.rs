use std::future::Future;
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_app_server_protocol::RequestId;
use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::LocalApprovalDecision;
use codex_hepta_matrix_protocol::MATRIXD_CONTROL_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MAX_MATRIXD_CONTROL_FRAME_BYTES;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::MatrixdFence;
use codex_hepta_matrix_protocol::MatrixdHealth;
use codex_hepta_matrix_protocol::MatrixdLifecycle;
use codex_hepta_matrix_protocol::MatrixdMethod;
use codex_hepta_matrix_protocol::MatrixdPayload;
use codex_hepta_matrix_protocol::MatrixdRequest;
use codex_hepta_matrix_protocol::MatrixdResponse;
use codex_hepta_matrix_protocol::MatrixdSnapshot;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::PendingApprovalKind;
use codex_uds::UnixListener;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
#[cfg(test)]
use tokio::sync::Mutex;
use tokio::sync::Semaphore;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::MatrixBridgeError;
use crate::RemoteMatrixAppServerTransport;

const CONNECTION_CAPACITY: usize = 32;
const IO_TIMEOUT: Duration = Duration::from_secs(2);
const MAX_ERROR_MESSAGE_CHARS: usize = 512;

pub(crate) type MatrixControlFuture<'a> =
    Pin<Box<dyn Future<Output = Result<(), MatrixBridgeError>> + Send + 'a>>;

pub(crate) trait MatrixControlTransport: Send + Sync {
    fn interrupt_turn(&self, thread_id: String, turn_id: String) -> MatrixControlFuture<'_>;

    fn resolve_approval(
        &self,
        request_id: RequestId,
        request_kind: PendingApprovalKind,
        decision: LocalApprovalDecision,
    ) -> MatrixControlFuture<'_>;
}

impl MatrixControlTransport for RemoteMatrixAppServerTransport {
    fn interrupt_turn(&self, thread_id: String, turn_id: String) -> MatrixControlFuture<'_> {
        Box::pin(async move {
            RemoteMatrixAppServerTransport::interrupt_turn(self, thread_id, turn_id).await
        })
    }

    fn resolve_approval(
        &self,
        request_id: RequestId,
        request_kind: PendingApprovalKind,
        decision: LocalApprovalDecision,
    ) -> MatrixControlFuture<'_> {
        Box::pin(async move {
            RemoteMatrixAppServerTransport::resolve_approval(
                self,
                request_id,
                request_kind,
                decision,
            )
            .await
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct MatrixdControlIdentity {
    pub agent_id: AgentId,
    pub release_id: String,
    pub fence: MatrixdFence,
    pub expected_mxid: MatrixUserId,
    pub active_rooms: Vec<MatrixRoomId>,
}

#[derive(Default)]
pub(crate) struct MatrixdConnectionState {
    agentd_connected: AtomicBool,
    matrix_sync_connected: AtomicBool,
    fenced: AtomicBool,
    draining: AtomicBool,
}

impl MatrixdConnectionState {
    pub(crate) fn set_agentd_connected(&self, connected: bool) {
        self.agentd_connected.store(connected, Ordering::Release);
    }

    pub(crate) fn set_matrix_sync_connected(&self, connected: bool) {
        self.matrix_sync_connected
            .store(connected, Ordering::Release);
    }

    pub(crate) fn set_fenced(&self) {
        self.fenced.store(true, Ordering::Release);
    }

    pub(crate) fn set_draining(&self) {
        self.draining.store(true, Ordering::Release);
    }

    fn health(&self) -> MatrixdHealth {
        let agentd_connected = self.agentd_connected.load(Ordering::Acquire);
        let matrix_sync_connected = self.matrix_sync_connected.load(Ordering::Acquire);
        let fenced = self.fenced.load(Ordering::Acquire);
        let draining = self.draining.load(Ordering::Acquire);
        let lifecycle = if fenced {
            MatrixdLifecycle::Fenced
        } else if draining {
            MatrixdLifecycle::Draining
        } else if agentd_connected && matrix_sync_connected {
            MatrixdLifecycle::Ready
        } else {
            MatrixdLifecycle::Degraded
        };
        MatrixdHealth {
            lifecycle,
            process_id: std::process::id(),
            agentd_connected,
            matrix_sync_connected,
            fenced,
        }
    }
}

pub(crate) struct MatrixdControlState {
    identity: MatrixdControlIdentity,
    store: MatrixDurableStore,
    transport: Arc<dyn MatrixControlTransport>,
    connections: Arc<MatrixdConnectionState>,
    mutation_gate: Semaphore,
}

impl MatrixdControlState {
    pub(crate) fn new(
        identity: MatrixdControlIdentity,
        store: MatrixDurableStore,
        transport: Arc<dyn MatrixControlTransport>,
        connections: Arc<MatrixdConnectionState>,
    ) -> Result<Self, MatrixdControlError> {
        identity.fence.validate()?;
        if identity.release_id.is_empty() || identity.active_rooms.is_empty() {
            return Err(MatrixdControlError::Invalid(
                "Matrix control identity is incomplete".to_string(),
            ));
        }
        Ok(Self {
            identity,
            store,
            transport,
            connections,
            mutation_gate: Semaphore::new(1),
        })
    }

    async fn response(&self, request: MatrixdRequest) -> MatrixdResponse {
        let request_id = request.request_id;
        let payload = match self.payload(request).await {
            Ok(payload) => payload,
            Err(error) => MatrixdPayload::Error {
                code: error.code().to_string(),
                message: bounded_message(&error.to_string()),
            },
        };
        MatrixdResponse {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id,
            agent_id: self.identity.agent_id.clone(),
            release_id: self.identity.release_id.clone(),
            binding_revision: self.identity.fence.binding_revision,
            binding_digest: self.identity.fence.binding_digest.clone(),
            attached_agent_generation: self.identity.fence.attached_agent_generation,
            process_incarnation: self.identity.fence.process_incarnation.clone(),
            plane_epoch: self.identity.fence.plane_epoch,
            payload,
        }
    }

    async fn payload(
        &self,
        request: MatrixdRequest,
    ) -> Result<MatrixdPayload, MatrixdControlRequestError> {
        request
            .validate()
            .map_err(|_| MatrixdControlRequestError::InvalidRequest)?;
        if request.agent_id != self.identity.agent_id {
            return Err(MatrixdControlRequestError::AccessDenied);
        }
        if let Some(fence) = request.fence.as_ref()
            && fence != &self.identity.fence
        {
            return Err(MatrixdControlRequestError::StaleFence);
        }

        match request.method {
            MatrixdMethod::Health => Ok(MatrixdPayload::Health(self.connections.health())),
            MatrixdMethod::Snapshot => self.snapshot().await,
            MatrixdMethod::Events {
                after_cursor,
                limit,
            } => {
                let page = self
                    .store
                    .read_control_events(after_cursor, usize::from(limit))
                    .await?;
                Ok(MatrixdPayload::Events(page.batch))
            }
            MatrixdMethod::CancelTurn { thread_id, turn_id } => {
                let _permit = self
                    .mutation_gate
                    .acquire()
                    .await
                    .map_err(|_| MatrixdControlRequestError::CorruptState)?;
                let snapshot = self.store.control_snapshot().await?;
                if snapshot.active_thread_id.as_deref() != Some(thread_id.as_str())
                    || snapshot.active_turn_id.as_deref() != Some(turn_id.as_str())
                {
                    return Err(MatrixdControlRequestError::Conflict);
                }
                self.transport.interrupt_turn(thread_id, turn_id).await?;
                Ok(MatrixdPayload::Accepted)
            }
            MatrixdMethod::ResolveApproval {
                approval_key,
                decision,
            } => {
                let _permit = self
                    .mutation_gate
                    .acquire()
                    .await
                    .map_err(|_| MatrixdControlRequestError::CorruptState)?;
                let now_ms = system_time_ms()?;
                let pending = self
                    .store
                    .pending_approval(&approval_key)
                    .await?
                    .ok_or(MatrixdControlRequestError::Conflict)?;
                if !pending.approval.allowed_decisions.contains(&decision) {
                    return Err(MatrixdControlRequestError::DecisionDenied);
                }
                let record = self
                    .store
                    .begin_pending_approval_resolution(
                        &approval_key,
                        self.identity.fence.attached_agent_generation,
                        &self.identity.fence.process_incarnation,
                        decision,
                        now_ms,
                    )
                    .await?;
                let request_id = serde_json::from_str::<RequestId>(&record.request_id_json)
                    .map_err(|_| MatrixdControlRequestError::CorruptState)?;
                self.transport
                    .resolve_approval(request_id, record.request_kind, decision)
                    .await?;
                let completion = self
                    .store
                    .complete_pending_approval_resolution(
                        &approval_key,
                        self.identity.fence.attached_agent_generation,
                        &self.identity.fence.process_incarnation,
                        decision,
                        system_time_ms()?,
                    )
                    .await;
                match completion {
                    Ok(_) => {}
                    Err(MatrixDurableError::Conflict)
                        if self.store.pending_approval(&approval_key).await?.is_none() =>
                    {
                        // The authoritative `serverRequest/resolved` event may
                        // win the race with this local completion after App
                        // Server accepted the response. Absence is terminal in
                        // that exact post-send window, not a failed resolve.
                    }
                    Err(error) => return Err(error.into()),
                }
                Ok(MatrixdPayload::Accepted)
            }
        }
    }

    async fn snapshot(&self) -> Result<MatrixdPayload, MatrixdControlRequestError> {
        let now_ms = system_time_ms()?;
        let metrics = self.store.queue_metrics(now_ms).await?;
        let control = self.store.control_snapshot().await?;
        let inbox_depth = metrics
            .pending_inbox_depth
            .saturating_add(metrics.pending_dispatch_depth);
        let oldest_inbox_age_ms = [metrics.oldest_inbox_age_ms, metrics.oldest_dispatch_age_ms]
            .into_iter()
            .flatten()
            .max();
        Ok(MatrixdPayload::Snapshot(MatrixdSnapshot {
            lifecycle: self.connections.health().lifecycle,
            expected_mxid: self.identity.expected_mxid.clone(),
            active_rooms: self.identity.active_rooms.clone(),
            inbox_depth: u32::try_from(inbox_depth).unwrap_or(u32::MAX),
            outbox_depth: u32::try_from(metrics.pending_outbox_depth).unwrap_or(u32::MAX),
            oldest_inbox_age_seconds: oldest_inbox_age_ms.map(|age| age / 1_000),
            oldest_outbox_age_seconds: metrics.oldest_outbox_age_ms.map(|age| age / 1_000),
            active_thread_id: control.active_thread_id,
            active_turn_id: control.active_turn_id,
            pending_approvals: control.pending_approvals,
            resync_required: false,
            event_cursor: control.cursor,
        }))
    }
}

pub(crate) struct MatrixdControlServer {
    listener: UnixListener,
    socket_path: PathBuf,
    state: Arc<MatrixdControlState>,
    cancellation: CancellationToken,
    connections: Arc<Semaphore>,
}

impl MatrixdControlServer {
    pub(crate) async fn bind(
        socket_path: PathBuf,
        state: Arc<MatrixdControlState>,
        cancellation: CancellationToken,
    ) -> Result<Self, MatrixdControlError> {
        prepare_socket(&socket_path).await?;
        let listener = UnixListener::bind(&socket_path).await?;
        set_owner_only(&socket_path).await?;
        Ok(Self {
            listener,
            socket_path,
            state,
            cancellation,
            connections: Arc::new(Semaphore::new(CONNECTION_CAPACITY)),
        })
    }

    pub(crate) async fn run(mut self) -> Result<(), MatrixdControlError> {
        loop {
            let stream = tokio::select! {
                _ = self.cancellation.cancelled() => return Ok(()),
                accepted = self.listener.accept() => accepted?,
            };
            let Ok(permit) = Arc::clone(&self.connections).try_acquire_owned() else {
                drop(stream);
                continue;
            };
            let state = Arc::clone(&self.state);
            tokio::spawn(async move {
                let _permit = permit;
                let _ = timeout(IO_TIMEOUT, serve_connection(stream, state)).await;
            });
        }
    }
}

impl Drop for MatrixdControlServer {
    fn drop(&mut self) {
        if let Err(error) = std::fs::remove_file(&self.socket_path)
            && error.kind() != ErrorKind::NotFound
        {
            eprintln!(
                "failed to remove matrixd control socket {}: {error}",
                self.socket_path.display()
            );
        }
    }
}

async fn serve_connection(
    stream: UnixStream,
    state: Arc<MatrixdControlState>,
) -> Result<(), MatrixdControlError> {
    stream.ensure_current_user_peer()?;
    let (reader, mut writer) = tokio::io::split(stream);
    let mut reader = BufReader::new(reader).take(MAX_MATRIXD_CONTROL_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = reader.read_until(b'\n', &mut frame).await?;
    if count == 0 || count as u64 > MAX_MATRIXD_CONTROL_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Err(MatrixdControlError::Invalid(
            "matrixd control request must be one bounded newline JSON frame".to_string(),
        ));
    }
    let request: MatrixdRequest = serde_json::from_slice(&frame)?;
    let response = state.response(request).await;
    let mut bytes = serde_json::to_vec(&response)?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_MATRIXD_CONTROL_FRAME_BYTES {
        return Err(MatrixdControlError::Invalid(
            "matrixd control response exceeded frame bound".to_string(),
        ));
    }
    writer.write_all(&bytes).await?;
    writer.shutdown().await?;
    Ok(())
}

async fn prepare_socket(socket_path: &Path) -> Result<(), MatrixdControlError> {
    let parent = socket_path.parent().ok_or_else(|| {
        MatrixdControlError::Invalid("matrixd control socket has no parent directory".to_string())
    })?;
    codex_uds::prepare_private_socket_directory(parent).await?;
    match UnixStream::connect(socket_path).await {
        Ok(_) => {
            return Err(MatrixdControlError::Io(std::io::Error::new(
                ErrorKind::AddrInUse,
                format!(
                    "matrixd control socket is already live at {}",
                    socket_path.display()
                ),
            )));
        }
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) if error.kind() == ErrorKind::ConnectionRefused => {}
        Err(_) if !socket_path.exists() => return Ok(()),
        Err(error) => return Err(error.into()),
    }
    if codex_uds::is_stale_socket_path(socket_path).await? {
        tokio::fs::remove_file(socket_path).await?;
        Ok(())
    } else {
        Err(MatrixdControlError::Io(std::io::Error::new(
            ErrorKind::AlreadyExists,
            format!(
                "matrixd control socket path is not stale: {}",
                socket_path.display()
            ),
        )))
    }
}

#[cfg(unix)]
async fn set_owner_only(path: &Path) -> Result<(), MatrixdControlError> {
    use std::os::unix::fs::PermissionsExt;

    tokio::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).await?;
    Ok(())
}

#[cfg(not(unix))]
async fn set_owner_only(_path: &Path) -> Result<(), MatrixdControlError> {
    Ok(())
}

fn system_time_ms() -> Result<u64, MatrixdControlRequestError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| MatrixdControlRequestError::Clock)?
        .as_millis();
    u64::try_from(millis).map_err(|_| MatrixdControlRequestError::Clock)
}

fn bounded_message(message: &str) -> String {
    message.chars().take(MAX_ERROR_MESSAGE_CHARS).collect()
}

#[derive(Debug, thiserror::Error)]
enum MatrixdControlRequestError {
    #[error("invalid Matrix control request")]
    InvalidRequest,
    #[error("Matrix control request belongs to another Agent")]
    AccessDenied,
    #[error("Matrix control request fence is stale")]
    StaleFence,
    #[error("Matrix approval decision is not available")]
    DecisionDenied,
    #[error("Matrix control request conflicts with current state")]
    Conflict,
    #[error("Matrix control state is corrupt")]
    CorruptState,
    #[error("system clock is outside the supported range")]
    Clock,
    #[error("Matrix durable control state rejected the request")]
    Store(#[from] MatrixDurableError),
    #[error("Matrix App Server control request failed")]
    AppServer(#[from] MatrixBridgeError),
}

impl MatrixdControlRequestError {
    fn code(&self) -> &'static str {
        match self {
            Self::InvalidRequest => "invalid_request",
            Self::AccessDenied => "access_denied",
            Self::StaleFence => "stale_fence",
            Self::DecisionDenied => "decision_denied",
            Self::Conflict => "conflict",
            Self::CorruptState => "corrupt_state",
            Self::Clock => "clock_error",
            Self::Store(MatrixDurableError::Conflict) => "conflict",
            Self::Store(MatrixDurableError::AccessDenied) => "access_denied",
            Self::Store(MatrixDurableError::Invalid) => "invalid_request",
            Self::Store(MatrixDurableError::Corrupt) => "corrupt_state",
            Self::Store(MatrixDurableError::Unavailable) => "store_unavailable",
            Self::AppServer(_) => "app_server_unavailable",
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum MatrixdControlError {
    #[error("invalid matrixd control server: {0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Protocol(#[from] codex_hepta_matrix_protocol::MatrixProtocolError),
}

#[cfg(test)]
mod tests {
    use std::error::Error;
    use std::fs;

    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_matrix_protocol::PendingApproval;
    use codex_hepta_matrix_store::MatrixDurableConfig;
    use codex_hepta_matrix_store::PendingApprovalDraft;
    use codex_hepta_paths::HeptaAgentLayout;
    use codex_hepta_paths::HeptaFleetRoot;
    use pretty_assertions::assert_eq;
    use tempfile::TempDir;
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncWriteExt;

    use super::*;

    type TestResult<T = ()> = Result<T, Box<dyn Error>>;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

    #[derive(Default)]
    struct FakeTransport {
        cancellations: Mutex<Vec<(String, String)>>,
        resolutions: Mutex<Vec<(RequestId, PendingApprovalKind, LocalApprovalDecision)>>,
    }

    struct ReconcileBeforeReturnTransport {
        store: MatrixDurableStore,
    }

    impl MatrixControlTransport for ReconcileBeforeReturnTransport {
        fn interrupt_turn(&self, _thread_id: String, _turn_id: String) -> MatrixControlFuture<'_> {
            Box::pin(async { Ok(()) })
        }

        fn resolve_approval(
            &self,
            request_id: RequestId,
            _request_kind: PendingApprovalKind,
            _decision: LocalApprovalDecision,
        ) -> MatrixControlFuture<'_> {
            Box::pin(async move {
                let request_id_json = serde_json::to_string(&request_id)
                    .map_err(|error| MatrixBridgeError::Protocol(error.to_string()))?;
                self.store
                    .reconcile_server_request_resolved(
                        &request_id_json,
                        "thread-1",
                        7,
                        "matrixd-incarnation-1",
                        12,
                    )
                    .await
                    .map_err(|error| MatrixBridgeError::Protocol(error.to_string()))?;
                Ok(())
            })
        }
    }

    impl MatrixControlTransport for FakeTransport {
        fn interrupt_turn(&self, thread_id: String, turn_id: String) -> MatrixControlFuture<'_> {
            Box::pin(async move {
                self.cancellations.lock().await.push((thread_id, turn_id));
                Ok(())
            })
        }

        fn resolve_approval(
            &self,
            request_id: RequestId,
            request_kind: PendingApprovalKind,
            decision: LocalApprovalDecision,
        ) -> MatrixControlFuture<'_> {
            Box::pin(async move {
                self.resolutions
                    .lock()
                    .await
                    .push((request_id, request_kind, decision));
                Ok(())
            })
        }
    }

    fn agent_id() -> TestResult<AgentId> {
        Ok(AgentId::parse(AGENT_ID)?)
    }

    fn layout(temp: &TempDir, agent_id: &AgentId) -> TestResult<HeptaAgentLayout> {
        let fleet_root = temp.path().join("fleet");
        fs::create_dir_all(&fleet_root)?;
        Ok(HeptaFleetRoot::parse(fleet_root.canonicalize()?)?
            .layout()
            .agent(agent_id))
    }

    fn fence() -> TestResult<MatrixdFence> {
        Ok(MatrixdFence {
            binding_revision: 1,
            binding_digest: Sha256Digest::parse(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )?,
            attached_agent_generation: 7,
            process_incarnation: "matrixd-incarnation-1".to_string(),
            plane_epoch: 9,
        })
    }

    fn identity() -> TestResult<MatrixdControlIdentity> {
        Ok(MatrixdControlIdentity {
            agent_id: agent_id()?,
            release_id: "release-1".to_string(),
            fence: fence()?,
            expected_mxid: MatrixUserId::parse("@agent:example.test")?,
            active_rooms: vec![MatrixRoomId::parse("!room:example.test")?],
        })
    }

    fn fenced_request(method: MatrixdMethod) -> TestResult<MatrixdRequest> {
        Ok(MatrixdRequest {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 1,
            agent_id: agent_id()?,
            fence: Some(fence()?),
            method,
        })
    }

    async fn state(
        temp: &TempDir,
        fake: Arc<FakeTransport>,
    ) -> TestResult<(Arc<MatrixdControlState>, Arc<MatrixdConnectionState>)> {
        let store =
            MatrixDurableStore::open(&layout(temp, &agent_id()?)?, MatrixDurableConfig::default())
                .await?;
        let connections = Arc::new(MatrixdConnectionState::default());
        Ok((
            Arc::new(MatrixdControlState::new(
                identity()?,
                store,
                fake,
                Arc::clone(&connections),
            )?),
            connections,
        ))
    }

    #[tokio::test]
    async fn stale_fence_never_reaches_mutation_transport() -> TestResult {
        let temp = TempDir::new()?;
        let fake = Arc::new(FakeTransport::default());
        let (state, _) = state(&temp, Arc::clone(&fake)).await?;
        let mut request = fenced_request(MatrixdMethod::CancelTurn {
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
        })?;
        request.fence.as_mut().expect("fence").plane_epoch += 1;
        let response = state.response(request).await;
        assert!(matches!(
            response.payload,
            MatrixdPayload::Error { ref code, .. } if code == "stale_fence"
        ));
        assert!(fake.cancellations.lock().await.is_empty());
        Ok(())
    }

    #[tokio::test]
    async fn cancel_requires_active_pair_and_duplicate_is_safe() -> TestResult {
        let temp = TempDir::new()?;
        let fake = Arc::new(FakeTransport::default());
        let (state, _) = state(&temp, Arc::clone(&fake)).await?;
        let rejected = state
            .response(fenced_request(MatrixdMethod::CancelTurn {
                thread_id: "thread-1".to_string(),
                turn_id: "turn-1".to_string(),
            })?)
            .await;
        assert!(matches!(
            rejected.payload,
            MatrixdPayload::Error { ref code, .. } if code == "conflict"
        ));
        assert!(fake.cancellations.lock().await.is_empty());

        state
            .store
            .record_turn_started("thread-1", "turn-1", 10)
            .await?;
        for request_id in [2, 3] {
            let mut request = fenced_request(MatrixdMethod::CancelTurn {
                thread_id: "thread-1".to_string(),
                turn_id: "turn-1".to_string(),
            })?;
            request.request_id = request_id;
            assert!(matches!(
                state.response(request).await.payload,
                MatrixdPayload::Accepted
            ));
        }
        assert_eq!(
            fake.cancellations.lock().await.as_slice(),
            &[
                ("thread-1".to_string(), "turn-1".to_string()),
                ("thread-1".to_string(), "turn-1".to_string())
            ]
        );
        Ok(())
    }

    #[tokio::test]
    async fn persisted_resolving_decision_is_the_only_crash_retry() -> TestResult {
        let temp = TempDir::new()?;
        let fake = Arc::new(FakeTransport::default());
        let (state, _) = state(&temp, Arc::clone(&fake)).await?;
        state
            .store
            .store_pending_approval(&PendingApprovalDraft {
                approval: PendingApproval {
                    approval_key: "approval-1".to_string(),
                    kind: "command_execution".to_string(),
                    thread_id: "thread-1".to_string(),
                    turn_id: "turn-1".to_string(),
                    summary: "Command approval requested; action: cargo test".to_string(),
                    created_at_ms: 10,
                    allowed_decisions: vec![
                        LocalApprovalDecision::Accept,
                        LocalApprovalDecision::Decline,
                    ],
                },
                request_id_json: "17".to_string(),
                request_kind: PendingApprovalKind::CommandExecution,
                attached_agent_generation: 7,
                process_incarnation: "matrixd-incarnation-1".to_string(),
            })
            .await?;
        state
            .store
            .begin_pending_approval_resolution(
                "approval-1",
                7,
                "matrixd-incarnation-1",
                LocalApprovalDecision::Accept,
                11,
            )
            .await?;

        let rejected = state
            .response(fenced_request(MatrixdMethod::ResolveApproval {
                approval_key: "approval-1".to_string(),
                decision: LocalApprovalDecision::Decline,
            })?)
            .await;
        assert!(matches!(
            rejected.payload,
            MatrixdPayload::Error { ref code, .. } if code == "conflict"
        ));
        assert!(fake.resolutions.lock().await.is_empty());

        let accepted = state
            .response(fenced_request(MatrixdMethod::ResolveApproval {
                approval_key: "approval-1".to_string(),
                decision: LocalApprovalDecision::Accept,
            })?)
            .await;
        assert!(matches!(accepted.payload, MatrixdPayload::Accepted));
        assert_eq!(
            fake.resolutions.lock().await.as_slice(),
            &[(
                RequestId::Integer(17),
                PendingApprovalKind::CommandExecution,
                LocalApprovalDecision::Accept,
            )]
        );
        assert!(state.store.pending_approval("approval-1").await?.is_none());
        Ok(())
    }

    #[tokio::test]
    async fn authoritative_resolved_event_may_win_local_completion_race() -> TestResult {
        let temp = TempDir::new()?;
        let store = MatrixDurableStore::open(
            &layout(&temp, &agent_id()?)?,
            MatrixDurableConfig::default(),
        )
        .await?;
        store
            .store_pending_approval(&PendingApprovalDraft {
                approval: PendingApproval {
                    approval_key: "approval-race".to_string(),
                    kind: "command_execution".to_string(),
                    thread_id: "thread-1".to_string(),
                    turn_id: "turn-1".to_string(),
                    summary: "Command approval requested; action: cargo test".to_string(),
                    created_at_ms: 10,
                    allowed_decisions: vec![LocalApprovalDecision::Accept],
                },
                request_id_json: "19".to_string(),
                request_kind: PendingApprovalKind::CommandExecution,
                attached_agent_generation: 7,
                process_incarnation: "matrixd-incarnation-1".to_string(),
            })
            .await?;
        let connections = Arc::new(MatrixdConnectionState::default());
        let state = MatrixdControlState::new(
            identity()?,
            store.clone(),
            Arc::new(ReconcileBeforeReturnTransport {
                store: store.clone(),
            }),
            connections,
        )?;

        let response = state
            .response(fenced_request(MatrixdMethod::ResolveApproval {
                approval_key: "approval-race".to_string(),
                decision: LocalApprovalDecision::Accept,
            })?)
            .await;
        assert!(matches!(response.payload, MatrixdPayload::Accepted));
        assert!(store.pending_approval("approval-race").await?.is_none());
        Ok(())
    }

    #[tokio::test]
    async fn health_tracks_real_task_state_and_owner_uds_serves_exact_identity() -> TestResult {
        // The product fleet root deliberately leaves Darwin `sun_path`
        // headroom. The SSD test harness uses a much deeper TMPDIR, so put
        // this socket-binding fixture under the canonical short temp root.
        let temp = tempfile::Builder::new()
            .prefix("hmx-control-")
            .tempdir_in("/tmp")?;
        let fake = Arc::new(FakeTransport::default());
        let (state, connections) = state(&temp, fake).await?;
        let socket = layout(&temp, &agent_id()?)?
            .matrixd_control_socket()
            .to_path_buf();
        let cancel = CancellationToken::new();
        let server =
            MatrixdControlServer::bind(socket.clone(), Arc::clone(&state), cancel.clone()).await?;
        let task = tokio::spawn(server.run());

        let mut stream = UnixStream::connect(&socket).await?;
        let request = MatrixdRequest {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 41,
            agent_id: agent_id()?,
            fence: None,
            method: MatrixdMethod::Health,
        };
        let mut bytes = serde_json::to_vec(&request)?;
        bytes.push(b'\n');
        stream.write_all(&bytes).await?;
        let mut reader = BufReader::new(stream);
        let mut response = Vec::new();
        reader.read_until(b'\n', &mut response).await?;
        let response: MatrixdResponse = serde_json::from_slice(&response)?;
        assert_eq!(response.release_id, "release-1");
        assert!(matches!(
            response.payload,
            MatrixdPayload::Health(MatrixdHealth {
                lifecycle: MatrixdLifecycle::Degraded,
                agentd_connected: false,
                matrix_sync_connected: false,
                ..
            })
        ));

        connections.set_agentd_connected(true);
        connections.set_matrix_sync_connected(true);
        assert_eq!(connections.health().lifecycle, MatrixdLifecycle::Ready);
        connections.set_fenced();
        assert_eq!(connections.health().lifecycle, MatrixdLifecycle::Fenced);
        cancel.cancel();
        task.await??;
        Ok(())
    }
}

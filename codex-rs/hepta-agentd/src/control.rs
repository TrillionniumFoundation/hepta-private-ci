use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_uds::UnixListener;
use codex_uds::UnixStream;
use tokio::io::AsyncWriteExt;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AGENTD_CONTROL_OVERLOAD_FRAME;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AgentdState;
use crate::MAX_CONTROL_FRAME_BYTES;
use crate::error::io_context;

#[path = "control_frames.rs"]
mod frames;

#[cfg(target_os = "linux")]
#[path = "control_source_capture.rs"]
pub(crate) mod source_capture;

const CONNECTION_CAPACITY: usize = 32;
const IO_TIMEOUT: Duration = Duration::from_secs(2);
const OVERLOAD_WRITE_TIMEOUT: Duration = Duration::from_millis(50);

/// Static host composition keeps finite Organ dispatch out of the full router.
/// Neither the request schema nor the peer chooses this profile.
trait ControlProfile {
    fn response(
        state: &AgentdState,
        request: crate::AgentdRequest,
    ) -> impl std::future::Future<Output = Result<AgentdResponse, AgentdError>> + Send;
}

struct FullControlProfile;
#[cfg(target_os = "linux")]
struct NotesControlProfile;

impl ControlProfile for FullControlProfile {
    async fn response(
        state: &AgentdState,
        request: crate::AgentdRequest,
    ) -> Result<AgentdResponse, AgentdError> {
        state
            .response(request.request_id, request.spawn_generation, request.method)
            .await
    }
}

#[cfg(target_os = "linux")]
impl ControlProfile for NotesControlProfile {
    async fn response(
        state: &AgentdState,
        request: crate::AgentdRequest,
    ) -> Result<AgentdResponse, AgentdError> {
        state
            .notes_response(request.request_id, request.spawn_generation, request.method)
            .await
    }
}

pub(crate) struct AgentdControlServer {
    listener: UnixListener,
    owned_socket_path: Option<PathBuf>,
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
    connections: Arc<Semaphore>,
    #[cfg(target_os = "linux")]
    source_capture_completion: Option<source_capture::OriginalControlCompletionV1>,
}

impl AgentdControlServer {
    pub(crate) async fn bind(
        socket_path: PathBuf,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<Self, AgentdError> {
        prepare_socket(&socket_path).await?;
        let listener = UnixListener::bind(&socket_path)
            .await
            .map_err(|error| io_context("bind agentd control socket", &socket_path, error))?;
        set_owner_only(&socket_path).await?;
        Ok(Self {
            listener,
            owned_socket_path: Some(socket_path),
            state,
            cancellation,
            connections: Arc::new(Semaphore::new(CONNECTION_CAPACITY)),
            #[cfg(target_os = "linux")]
            source_capture_completion: None,
        })
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn from_root_bound(
        socket: std::os::fd::OwnedFd,
        socket_path: &Path,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<Self, AgentdError> {
        let socket = crate::listen_root_bound_socket(socket, socket_path)?;
        let listener = UnixListener::from_inherited(socket, socket_path)?;
        Ok(Self {
            listener,
            owned_socket_path: None,
            state,
            cancellation,
            connections: Arc::new(Semaphore::new(CONNECTION_CAPACITY)),
            #[cfg(target_os = "linux")]
            source_capture_completion: None,
        })
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn original_source_capture_join(
        &mut self,
    ) -> Result<source_capture::OriginalControlJoinV1, AgentdError> {
        if self.source_capture_completion.is_some() {
            return Err(AgentdError::Invalid(
                "original control join was already selected".into(),
            ));
        }
        let (completion, join) = source_capture::original_control_join_v1();
        self.source_capture_completion = Some(completion);
        Ok(join)
    }

    pub(crate) async fn run(self) -> Result<(), AgentdError> {
        self.run_for::<FullControlProfile>().await
    }

    #[cfg(target_os = "linux")]
    pub(crate) async fn run_notes(self) -> Result<(), AgentdError> {
        self.run_for::<NotesControlProfile>().await
    }

    async fn run_for<P>(mut self) -> Result<(), AgentdError>
    where
        P: ControlProfile + 'static,
    {
        let mut connections = JoinSet::new();
        let mut failure = None;
        loop {
            let accepted = tokio::select! {
                biased;
                _ = self.cancellation.cancelled() => break,
                Some(completion) = connections.join_next(), if !connections.is_empty() => {
                    retain_connection_failure(&mut failure, completion);
                    continue;
                }
                accepted = self.listener.accept() => accepted,
            };
            let stream = match accepted {
                Ok(stream) => stream,
                Err(error) => {
                    failure.get_or_insert_with(|| error.into());
                    break;
                }
            };
            #[cfg(target_os = "linux")]
            if self.owned_socket_path.is_none()
                && stream.ensure_current_user_or_root_peer().is_err()
            {
                continue;
            }
            let Ok(permit) = Arc::clone(&self.connections).try_acquire_owned() else {
                let mut stream = stream;
                let _ = timeout(OVERLOAD_WRITE_TIMEOUT, async {
                    stream.write_all(AGENTD_CONTROL_OVERLOAD_FRAME).await?;
                    stream.shutdown().await
                })
                .await;
                continue;
            };
            let state = Arc::clone(&self.state);
            connections.spawn(async move {
                let _permit = permit;
                ControlConnection::<P>::serve_connection(stream, state).await
            });
        }
        // Stop admission, then join every already accepted request. Dropping a
        // required control task aborts its owned children; it never detaches
        // continuations that could outlive a claimed original-runtime drain.
        while let Some(completion) = connections.join_next().await {
            retain_connection_failure(&mut failure, completion);
        }
        if let Some(error) = failure {
            return Err(error);
        }
        #[cfg(target_os = "linux")]
        if let Some(completion) = self.source_capture_completion.take() {
            completion.acknowledge_original_control_completion()?;
        }
        Ok(())
    }
}

fn retain_connection_failure(
    failure: &mut Option<AgentdError>,
    completion: Result<Result<(), AgentdError>, tokio::task::JoinError>,
) {
    let error = match completion {
        Ok(Ok(())) => return,
        Ok(Err(error)) => error,
        Err(error) => {
            AgentdError::Protocol(format!("agentd control connection task failed: {error}"))
        }
    };
    if failure.is_none() {
        *failure = Some(error);
    }
}

impl Drop for AgentdControlServer {
    fn drop(&mut self) {
        let Some(path) = &self.owned_socket_path else {
            return;
        };
        if let Err(error) = std::fs::remove_file(path)
            && error.kind() != ErrorKind::NotFound
        {
            eprintln!(
                "failed to remove agentd control socket {}: {error}",
                path.display()
            );
        }
    }
}

struct ControlConnection<P>(std::marker::PhantomData<P>);

impl<P: ControlProfile> ControlConnection<P> {
    async fn serve_connection(
        stream: UnixStream,
        state: Arc<AgentdState>,
    ) -> Result<(), AgentdError> {
        let (reader, mut writer) = tokio::io::split(stream);
        let frame = frames::read_frame(reader).await?;
        let request: AgentdRequest = serde_json::from_slice(&frame)?;
        let circuit_admission = request.schema_version == AGENTD_CONTROL_SCHEMA_VERSION
            && state.circuit_task_enabled()
            && matches!(&request.method, crate::AgentdMethod::ObjectiveStart { .. });
        let response = if request.schema_version != AGENTD_CONTROL_SCHEMA_VERSION {
            error_response(
                &state,
                request.request_id,
                request.spawn_generation,
                "unsupported_schema",
                "unsupported agentd control schema",
            )
        } else {
            let request_id = request.request_id;
            let spawn_generation = request.spawn_generation;
            // An original Circuit admission keeps its connection permit until its
            // supervised owner and result publication finish. Losing a transport
            // ACK must not cancel the continuation after durable computation.
            // The installed task owner still authenticates RunStart and enforces
            // its admission, AuthBus expiry, Circuit budget and lifecycle bounds.
            let outcome = if circuit_admission {
                P::response(&state, request).await
            } else {
                timeout(IO_TIMEOUT, P::response(&state, request))
                    .await
                    .map_err(|_| {
                        AgentdError::Protocol("agentd control response timed out".into())
                    })?
            };
            match outcome {
                Ok(response) => response,
                Err(error) => error_response(
                    &state,
                    request_id,
                    spawn_generation,
                    "request_rejected",
                    &error.to_string(),
                ),
            }
        };
        let mut bytes = serde_json::to_vec(&response)?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES {
            return Err(AgentdError::Protocol(
                "agentd control response exceeded frame bound".to_string(),
            ));
        }
        let completed_circuit = circuit_admission
            && matches!(&response.payload, AgentdPayload::ObjectiveRun(receipt)
                if receipt.disposition.eq("circuit_succeeded"));
        match frames::write_frame(&mut writer, &bytes).await {
            // The original owner and all task postchecks already returned.
            // Losing only its terminal transport ACK cannot undo that work or
            // poison the joined control owner. No task is submitted again.
            Err(AgentdError::Io(error))
                if completed_circuit
                    && matches!(
                        error.kind(),
                        ErrorKind::BrokenPipe | ErrorKind::ConnectionReset
                    ) =>
            {
                Ok(())
            }
            result => result,
        }
    }
}

fn error_response(
    state: &AgentdState,
    request_id: u64,
    spawn_generation: u64,
    code: &str,
    message: &str,
) -> AgentdResponse {
    AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id,
        agent_id: state.identity().agent_id.clone(),
        spawn_generation: state.identity().spawn_generation,
        current_generation: spawn_generation,
        payload: AgentdPayload::Error {
            code: code.to_string(),
            message: bounded_message(message),
        },
    }
}

fn bounded_message(message: &str) -> String {
    message.chars().take(512).collect()
}

async fn prepare_socket(socket_path: &Path) -> Result<(), AgentdError> {
    let parent = socket_path.parent().ok_or_else(|| {
        AgentdError::Invalid("agentd control socket has no parent directory".to_string())
    })?;
    codex_uds::prepare_private_socket_directory(parent)
        .await
        .map_err(|error| io_context("prepare agentd control socket directory", parent, error))?;
    // Reject foreign entry types before connect's platform-specific errno.
    // This check never authorizes cleanup: live probing and the final stale
    // socket classification below remain mandatory.
    #[cfg(unix)]
    {
        use std::os::unix::fs::FileTypeExt;

        match tokio::fs::symlink_metadata(socket_path).await {
            Ok(metadata) if !metadata.file_type().is_socket() => {
                return Err(AgentdError::Io(std::io::Error::new(
                    ErrorKind::AlreadyExists,
                    format!(
                        "agentd control socket path is not a stale socket: {}",
                        socket_path.display()
                    ),
                )));
            }
            Ok(_) => {}
            Err(error) if error.kind() == ErrorKind::NotFound => {}
            Err(error) => {
                return Err(io_context(
                    "inspect agentd control socket entry",
                    socket_path,
                    error,
                ));
            }
        }
    }
    match UnixStream::connect(socket_path).await {
        Ok(_) => {
            return Err(AgentdError::Io(std::io::Error::new(
                ErrorKind::AddrInUse,
                format!(
                    "agentd control socket is already live at {}",
                    socket_path.display()
                ),
            )));
        }
        Err(error)
            if matches!(
                error.kind(),
                ErrorKind::NotFound | ErrorKind::ConnectionRefused
            ) => {}
        Err(error) => {
            return Err(io_context(
                /* operation */ "probe existing agentd control socket",
                /* path */ socket_path,
                /* source */ error,
            ));
        }
    }
    // Windows may refuse a missing rendezvous or report NotFound when following
    // an existing AF_UNIX entry. Inspect the entry itself before deciding that
    // cleanup is unnecessary; a dangling symlink is not an absent path.
    match tokio::fs::symlink_metadata(socket_path).await {
        Ok(_) => {}
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => {
            return Err(io_context(
                "inspect agentd control socket entry",
                socket_path,
                error,
            ));
        }
    }
    if codex_uds::is_stale_socket_path(socket_path)
        .await
        .map_err(|error| io_context("inspect stale agentd control socket", socket_path, error))?
    {
        tokio::fs::remove_file(socket_path).await.map_err(|error| {
            io_context("remove stale agentd control socket", socket_path, error)
        })?;
        Ok(())
    } else {
        Err(AgentdError::Io(std::io::Error::new(
            ErrorKind::AlreadyExists,
            format!(
                "agentd control socket path is not a stale socket: {}",
                socket_path.display()
            ),
        )))
    }
}

#[cfg(unix)]
async fn set_owner_only(path: &Path) -> Result<(), AgentdError> {
    use std::os::unix::fs::PermissionsExt;

    tokio::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .await
        .map_err(|error| {
            io_context(
                "set owner-only agentd control socket permissions",
                path,
                error,
            )
        })?;
    Ok(())
}

#[cfg(not(unix))]
async fn set_owner_only(_path: &Path) -> Result<(), AgentdError> {
    Ok(())
}

#[cfg(test)]
#[path = "control_socket_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "control_circuit_completion_test_support.rs"]
mod circuit_completion_test_support;

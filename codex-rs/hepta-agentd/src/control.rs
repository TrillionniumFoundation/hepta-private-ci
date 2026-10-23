use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_uds::UnixListener;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWrite;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::sync::Semaphore;
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
use crate::cognitive_context::CognitiveContextError;
use crate::cognitive_context_delivery::encode_control_frame;
use crate::cognitive_context_delivery::write_control_frame;
use crate::error::io_context;

const CONNECTION_CAPACITY: usize = 32;
const IO_TIMEOUT: Duration = Duration::from_secs(2);
const OVERLOAD_WRITE_TIMEOUT: Duration = Duration::from_millis(50);

pub(crate) struct AgentdControlServer {
    listener: UnixListener,
    socket_path: PathBuf,
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
    connections: Arc<Semaphore>,
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
            socket_path,
            state,
            cancellation,
            connections: Arc::new(Semaphore::new(CONNECTION_CAPACITY)),
        })
    }

    pub(crate) async fn run(mut self) -> Result<(), AgentdError> {
        loop {
            let stream = tokio::select! {
                _ = self.cancellation.cancelled() => return Ok(()),
                accepted = self.listener.accept() => accepted?,
            };
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
            tokio::spawn(async move {
                let _permit = permit;
                match timeout(IO_TIMEOUT, serve_connection(stream, state)).await {
                    Ok(Ok(())) => {}
                    Ok(Err(error)) => eprintln!("agentd control connection failed: {error}"),
                    Err(_) => eprintln!("agentd control connection timed out"),
                }
            });
        }
    }
}

impl Drop for AgentdControlServer {
    fn drop(&mut self) {
        if let Err(error) = std::fs::remove_file(&self.socket_path)
            && error.kind() != ErrorKind::NotFound
        {
            eprintln!(
                "failed to remove agentd control socket {}: {error}",
                self.socket_path.display()
            );
        }
    }
}

async fn serve_connection(stream: UnixStream, state: Arc<AgentdState>) -> Result<(), AgentdError> {
    let (reader, mut writer) = tokio::io::split(stream);
    let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = reader.read_until(b'\n', &mut frame).await?;
    if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Err(AgentdError::Protocol(
            "agentd control request must be one bounded newline JSON frame".to_string(),
        ));
    }
    let request: AgentdRequest = serde_json::from_slice(&frame)?;
    let (response, mut context) = if request.schema_version != AGENTD_CONTROL_SCHEMA_VERSION {
        (
            error_response(
                &state,
                request.request_id,
                request.spawn_generation,
                "unsupported_schema",
                "unsupported agentd control schema",
            ),
            None,
        )
    } else {
        match state
            .prepare_response(request.request_id, request.spawn_generation, request.method)
            .await
        {
            Ok(prepared) => (prepared.response, prepared.context),
            Err(error) => (
                error_response(
                    &state,
                    request.request_id,
                    request.spawn_generation,
                    "request_rejected",
                    &error.to_string(),
                ),
                None,
            ),
        }
    };
    let mut lease = ControlPublicationLease {
        state: &state,
        response: &response,
        keep: false,
    };
    let bytes = encode_control_frame(&response).map_err(AgentdError::Protocol)?;
    let confirmation = if let Some(publication) = &mut context {
        let confirmation = match publication
            .begin_intent(
                &response.agent_id,
                response.spawn_generation,
                response.request_id,
                &bytes,
            )
            .await
        {
            Ok(confirmation) => confirmation,
            Err(error) => {
                let code = if matches!(error, CognitiveContextError::RetrievalLearningUnavailable) {
                    "cognitive_retrieval_learning_unavailable"
                } else {
                    "cognitive_read_unavailable"
                };
                return write_prepublication_rejection(
                    &mut writer,
                    &response,
                    code,
                    &format!("context intent unavailable: {error:?}"),
                )
                .await;
            }
        };
        // The durable intent may now exist, but there has still been no socket
        // write. Any late owner/CURRENT/issuer/lifecycle failure leaves Unknown.
        if let Err(error) = state
            .revalidate_control_publication(&response, publication)
            .await
        {
            return write_prepublication_rejection(
                &mut writer,
                &response,
                "cognitive_read_unavailable",
                &error.to_string(),
            )
            .await;
        }
        confirmation
    } else {
        None
    };
    // After any successful complete write, failures are close/log only. Sending
    // an error frame here would contradict the bytes already accepted by IPC.
    write_control_frame(&mut writer, &bytes, confirmation)
        .await
        .map_err(AgentdError::Protocol)?;
    lease.keep = true;
    Ok(())
}

/// Before any response byte, preserve the existing typed failure contract. An
/// earlier durable intent remains Unknown and the original lease is retracted.
async fn write_prepublication_rejection<W: AsyncWrite + Unpin>(
    writer: &mut W,
    prepared: &AgentdResponse,
    code: &str,
    message: &str,
) -> Result<(), AgentdError> {
    let response = AgentdResponse {
        schema_version: prepared.schema_version,
        request_id: prepared.request_id,
        agent_id: prepared.agent_id.clone(),
        spawn_generation: prepared.spawn_generation,
        current_generation: prepared.current_generation,
        payload: AgentdPayload::Error {
            code: code.to_string(),
            message: bounded_message(message),
        },
    };
    let bytes = encode_control_frame(&response).map_err(AgentdError::Protocol)?;
    write_control_frame(writer, &bytes, None)
        .await
        .map_err(AgentdError::Protocol)
}

struct ControlPublicationLease<'a> {
    state: &'a AgentdState,
    response: &'a AgentdResponse,
    keep: bool,
}

impl Drop for ControlPublicationLease<'_> {
    fn drop(&mut self) {
        if !self.keep {
            // Includes cancellation of the outer timeout while a blocking
            // append continues. Such an append cannot confirm a socket write.
            self.state.retract_control_publication(self.response);
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
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) if error.kind() == ErrorKind::ConnectionRefused => {}
        Err(_error) if !socket_path.exists() => return Ok(()),
        Err(error) => {
            return Err(io_context(
                /* operation */ "probe existing agentd control socket",
                /* path */ socket_path,
                /* source */ error,
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

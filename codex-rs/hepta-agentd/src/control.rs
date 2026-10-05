use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_uds::UnixListener;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
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
    canary_reads: Arc<Semaphore>,
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
            canary_reads: Arc::new(Semaphore::new(1)),
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
            let canary_reads = Arc::clone(&self.canary_reads);
            tokio::spawn(async move {
                let _permit = permit;
                let _ = timeout(IO_TIMEOUT, serve_connection(stream, state, canary_reads)).await;
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

async fn serve_connection(
    mut stream: UnixStream,
    state: Arc<AgentdState>,
    canary_reads: Arc<Semaphore>,
) -> Result<(), AgentdError> {
    let root_peer = stream.ensure_peer_user(0);
    let mut frame = Vec::new();
    let count = {
        let mut reader = BufReader::new(&mut stream).take(MAX_CONTROL_FRAME_BYTES + 1);
        reader.read_until(b'\n', &mut frame).await?
    };
    if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Err(AgentdError::Protocol(
            "agentd control request must be one bounded newline JSON frame".to_string(),
        ));
    }
    let request: AgentdRequest = serde_json::from_slice(&frame)?;
    let requested_response_limit = crate::canary_operation_receipt::response_limit(&request.method);
    let root_only = matches!(
        &request.method,
        crate::AgentdMethod::NativeModelReceipt { .. }
            | crate::AgentdMethod::ResolveParameterAdmissionV1 { .. }
            | crate::AgentdMethod::RefreshParameterInputContextV2 { .. }
            | crate::AgentdMethod::PrepareParameterInputFromContextV2 { .. }
            | crate::AgentdMethod::PrepareParameterInputV1 { .. }
            | crate::AgentdMethod::PreparedGenerationV2 { .. }
            | crate::AgentdMethod::SelfIterationRoundStatus { .. }
            | crate::AgentdMethod::SelfIterationCurrentRound
            | crate::AgentdMethod::CanaryOperationReceipt { .. }
            | crate::AgentdMethod::PlasticityCompletedProposal { .. }
    );
    let authorized_root = root_peer.is_ok() && stream.ensure_peer_user(0).is_ok();
    let response_limit = if authorized_root {
        requested_response_limit
    } else {
        MAX_CONTROL_FRAME_BYTES
    };
    // Retain one whole-checkpoint inspection slot through encoding and write.
    // Ordinary methods retain their original capacity; denied peers take no slot.
    let canary_permit = if authorized_root
        && matches!(
            &request.method,
            crate::AgentdMethod::CanaryOperationReceipt { .. }
                | crate::AgentdMethod::PreparedGenerationV2 { .. }
                | crate::AgentdMethod::PlasticityCompletedProposal { .. }
        ) {
        Some(canary_reads.try_acquire_owned())
    } else {
        None
    };
    let response = if canary_permit.as_ref().is_some_and(Result::is_err) {
        error_response(
            &state,
            request.request_id,
            request.spawn_generation,
            "whole_receipt_read_busy",
            "original whole receipt inspection is busy",
        )
    } else if root_only && !authorized_root {
        error_response(
            &state,
            request.request_id,
            request.spawn_generation,
            "root_peer_required",
            if matches!(
                &request.method,
                crate::AgentdMethod::PlasticityCompletedProposal { .. }
            ) {
                "plasticity observation requires the actual Root kernel peer"
            } else if matches!(
                &request.method,
                crate::AgentdMethod::SelfIterationRoundStatus { .. }
                    | crate::AgentdMethod::SelfIterationCurrentRound
            ) {
                "round inspection requires the actual Root kernel peer"
            } else if matches!(
                &request.method,
                crate::AgentdMethod::ResolveParameterAdmissionV1 { .. }
                    | crate::AgentdMethod::RefreshParameterInputContextV2 { .. }
                    | crate::AgentdMethod::PrepareParameterInputFromContextV2 { .. }
                    | crate::AgentdMethod::PrepareParameterInputV1 { .. }
            ) {
                "parameter admission requires the actual Root kernel peer"
            } else {
                "native receipt inspection requires the actual Root kernel peer"
            },
        )
    } else if request.schema_version != AGENTD_CONTROL_SCHEMA_VERSION {
        error_response(
            &state,
            request.request_id,
            request.spawn_generation,
            "unsupported_schema",
            "unsupported agentd control schema",
        )
    } else {
        match state
            .response(request.request_id, request.spawn_generation, request.method)
            .await
        {
            Ok(response) => response,
            Err(error) => error_response(
                &state,
                request.request_id,
                request.spawn_generation,
                "request_rejected",
                &error.to_string(),
            ),
        }
    };
    let receipt_generation =
        (root_only && authorized_root && !matches!(&response.payload, AgentdPayload::Error { .. }))
            .then_some(response.current_generation);
    let bytes = if response_limit == MAX_CONTROL_FRAME_BYTES {
        encode_response(response)?
    } else {
        encode_response_with_limit(response, response_limit)?
    };
    if let Some(generation) = receipt_generation {
        stream.ensure_peer_user(0)?;
        if state.current_generation()? != generation {
            return Err(AgentdError::GenerationFenced(
                "receipt exporter generation changed".into(),
            ));
        }
    }
    stream.write_all(&bytes).await?;
    stream.shutdown().await?;
    drop(canary_permit);
    Ok(())
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

/// Retain the unchanged frame budget even when a legacy endpoint materializes
/// a large result. A bounded error preserves request identity instead of EOF.
fn encode_response(response: AgentdResponse) -> Result<Vec<u8>, AgentdError> {
    encode_response_with_limit(response, MAX_CONTROL_FRAME_BYTES)
}

fn encode_response_with_limit(
    mut response: AgentdResponse,
    limit: u64,
) -> Result<Vec<u8>, AgentdError> {
    let mut buffer = ControlFrameBuffer {
        bytes: Vec::with_capacity(MAX_CONTROL_FRAME_BYTES as usize),
        overflowed: false,
        limit: limit as usize,
    };
    if let Err(error) = serde_json::to_writer(&mut buffer, &response) {
        if !buffer.overflowed {
            return Err(error.into());
        }
        buffer.bytes.clear();
        buffer.overflowed = false;
        response.payload = AgentdPayload::Error {
            code: "response_too_large".into(),
            message: "response exceeds control frame; use the negotiated paginated endpoint".into(),
        };
        serde_json::to_writer(&mut buffer, &response)?;
    }
    buffer.bytes.push(b'\n');
    Ok(buffer.bytes)
}

struct ControlFrameBuffer {
    bytes: Vec<u8>,
    overflowed: bool,
    limit: usize,
}

impl std::io::Write for ControlFrameBuffer {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let remaining = self
            .limit
            .saturating_sub(1)
            .saturating_sub(self.bytes.len());
        if bytes.len() > remaining {
            self.overflowed = true;
            return Err(std::io::Error::other("control frame byte budget exceeded"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
#[path = "control_frame_tests.rs"]
mod frame_tests;

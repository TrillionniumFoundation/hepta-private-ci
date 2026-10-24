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
use crate::state::AgentdRuntimeProfile;
use crate::state::FullRuntimeOwners;
#[cfg(target_os = "linux")]
use crate::state::NativeCpuRuntimeOwners;

const CONNECTION_CAPACITY: usize = 32;
const IO_TIMEOUT: Duration = Duration::from_secs(2);
const OVERLOAD_WRITE_TIMEOUT: Duration = Duration::from_millis(50);

/// Static host composition keeps finite Organ dispatch out of the full router.
/// Neither the request schema nor the peer chooses this profile.
trait ControlProfile<S: AgentdRuntimeProfile> {
    fn response(
        state: &AgentdState<S>,
        request: crate::AgentdRequest,
    ) -> impl std::future::Future<Output = Result<AgentdResponse, AgentdError>> + Send;
}

struct FullControlProfile;
#[cfg(target_os = "linux")]
struct NotesControlProfile;
#[cfg(target_os = "linux")]
struct NativeCpuControlProfile;

impl ControlProfile<FullRuntimeOwners> for FullControlProfile {
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
impl ControlProfile<FullRuntimeOwners> for NotesControlProfile {
    async fn response(
        state: &AgentdState,
        request: crate::AgentdRequest,
    ) -> Result<AgentdResponse, AgentdError> {
        state
            .notes_response(request.request_id, request.spawn_generation, request.method)
            .await
    }
}

#[cfg(target_os = "linux")]
impl ControlProfile<NativeCpuRuntimeOwners> for NativeCpuControlProfile {
    async fn response(
        state: &AgentdState<NativeCpuRuntimeOwners>,
        request: crate::AgentdRequest,
    ) -> Result<AgentdResponse, AgentdError> {
        state
            .native_cpu_response(request.request_id, request.spawn_generation, request.method)
            .await
    }
}

pub(crate) struct AgentdControlServer<S: AgentdRuntimeProfile = FullRuntimeOwners> {
    listener: UnixListener,
    socket_path: PathBuf,
    state: Arc<AgentdState<S>>,
    cancellation: CancellationToken,
    connections: Arc<Semaphore>,
}

impl<S: AgentdRuntimeProfile> AgentdControlServer<S> {
    pub(crate) async fn bind(
        socket_path: PathBuf,
        state: Arc<AgentdState<S>>,
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

    async fn run_for<P: ControlProfile<S> + 'static>(mut self) -> Result<(), AgentdError> {
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
                let _ = timeout(IO_TIMEOUT, serve_connection::<P, S>(stream, state)).await;
            });
        }
    }
}

impl AgentdControlServer {
    pub(crate) async fn run(self) -> Result<(), AgentdError> {
        self.run_for::<FullControlProfile>().await
    }

    #[cfg(target_os = "linux")]
    pub(crate) async fn run_notes(self) -> Result<(), AgentdError> {
        self.run_for::<NotesControlProfile>().await
    }
}

#[cfg(target_os = "linux")]
impl AgentdControlServer<NativeCpuRuntimeOwners> {
    pub(crate) async fn run_native_cpu(self) -> Result<(), AgentdError> {
        self.run_for::<NativeCpuControlProfile>().await
    }
}

impl<S: AgentdRuntimeProfile> Drop for AgentdControlServer<S> {
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

async fn serve_connection<P: ControlProfile<S>, S: AgentdRuntimeProfile>(
    stream: UnixStream,
    state: Arc<AgentdState<S>>,
) -> Result<(), AgentdError> {
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
        match P::response(&state, request).await {
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
    writer.write_all(&bytes).await?;
    writer.shutdown().await?;
    Ok(())
}

fn error_response<S: AgentdRuntimeProfile>(
    state: &AgentdState<S>,
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

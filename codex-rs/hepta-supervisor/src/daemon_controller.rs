//! A separate enrolled service can request only ordinary fenced lifecycle work.

use std::os::unix::fs::PermissionsExt;

use tokio::net::UnixListener as PeerListener;
use tokio::net::UnixStream as PeerStream;

use super::*;
use crate::SupervisorControllerRequest;
use crate::controller_peer::ControllerPeerGate;

pub(super) struct ControllerServer {
    listener: PeerListener,
    socket_path: PathBuf,
    state: Arc<DaemonState<UnixProcessDriver>>,
    cancellation: CancellationToken,
    gate: Arc<ControllerPeerGate>,
}

impl ControllerServer {
    pub(super) async fn bind(
        socket_path: PathBuf,
        state: Arc<DaemonState<UnixProcessDriver>>,
        cancellation: CancellationToken,
        gate: ControllerPeerGate,
    ) -> Result<Self, SupervisorError> {
        prepare_socket(&socket_path).await?;
        let listener = PeerListener::bind(&socket_path)?;
        let parent = socket_path.parent().expect("prepared controller parent");
        let principal = gate.principal();
        for path in [parent, socket_path.as_path()] {
            let path = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())
                .map_err(|_| SupervisorError::Invalid("invalid controller path".into()))?;
            if unsafe { libc::chown(path.as_ptr(), libc::geteuid(), principal.gid) } != 0 {
                return Err(std::io::Error::last_os_error().into());
            }
        }
        std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o750))?;
        std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o660))?;
        Ok(Self {
            listener,
            socket_path,
            state,
            cancellation,
            gate: Arc::new(gate),
        })
    }

    pub(super) async fn run(self) -> Result<(), SupervisorError> {
        let capacity = Arc::new(Semaphore::new(CONNECTION_CAPACITY));
        let mut tasks = JoinSet::new();
        let result = loop {
            let stream = tokio::select! {
                _ = self.cancellation.cancelled() => break Ok(()),
                joined = tasks.join_next(), if !tasks.is_empty() => {
                    if matches!(joined, Some(Err(_))) {
                        break Err(SupervisorError::Invalid("controller connection failed".into()));
                    }
                    continue;
                },
                accepted = self.listener.accept() => match accepted {
                    Ok((stream, _)) => stream,
                    Err(error) => break Err(error.into()),
                },
            };
            if self.gate.verify(&stream).is_err() {
                continue;
            }
            let Ok(permit) = Arc::clone(&capacity).try_acquire_owned() else {
                continue;
            };
            let state = Arc::clone(&self.state);
            let gate = Arc::clone(&self.gate);
            tasks.spawn(async move {
                let _permit = permit;
                let _ = serve(stream, state, gate).await;
            });
        };
        tasks.abort_all();
        while tasks.join_next().await.is_some() {}
        result
    }
}

impl Drop for ControllerServer {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.socket_path);
    }
}

async fn serve(
    mut stream: PeerStream,
    state: Arc<DaemonState<UnixProcessDriver>>,
    gate: Arc<ControllerPeerGate>,
) -> Result<(), SupervisorError> {
    let mut frame = Vec::new();
    let count = timeout(IO_TIMEOUT, async {
        BufReader::new(&mut stream)
            .take(MAX_SUPERVISORD_CONTROL_FRAME_BYTES + 1)
            .read_until(b'\n', &mut frame)
            .await
    })
    .await
    .map_err(|_| std::io::Error::new(ErrorKind::TimedOut, "controller frame timed out"))??;
    if count == 0 || count as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Ok(());
    }
    gate.verify(&stream)?;
    let request: SupervisorControllerRequest = match serde_json::from_slice(&frame) {
        Ok(request) => request,
        Err(_) => return Ok(()),
    };
    let request = match request.owner_request() {
        Ok(request) => request,
        Err(_) => return Ok(()),
    };
    let payload = timeout(
        IO_TIMEOUT,
        execution::handle_with_request_id(Arc::clone(&state), request.request_id, request.method),
    )
    .await
    .unwrap_or_else(|_| {
        error_payload(
            "operation_indeterminate",
            "inspect the original durable receipt before retry",
            None,
        )
    });
    let response = SupervisordResponse {
        schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
        request_id: request.request_id,
        payload,
    };
    write_response(&mut stream, response).await
}

#[cfg(test)]
#[path = "daemon_controller_owner_tests.rs"]
mod owner_tests;
#[cfg(test)]
#[path = "daemon_controller_tests.rs"]
mod tests;

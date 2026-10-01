//! A separately enrolled desktop principal observes the existing lifecycle owner.
//! The wire decoder accepts only the three Robrix queries, and observations
//! never enter a lifecycle mutation lane or open a second fleet writer.

use std::os::unix::fs::PermissionsExt;

use serde::Deserialize;

use super::*;
use crate::robrix_protocol::MAX_ROBRIX_SUPERVISORD_RESPONSE_BYTES;
use crate::robrix_protocol::RobrixSupervisordRequest;
use crate::robrix_protocol::RobrixSupervisordResponse;

#[derive(Clone, Copy, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Principal {
    pub(crate) uid: u32,
    pub(crate) gid: u32,
}

pub(super) struct ObserverServer {
    listener: UnixListener,
    socket_path: PathBuf,
    state: Arc<DaemonState<UnixProcessDriver>>,
    cancellation: CancellationToken,
    principal: Principal,
}

impl ObserverServer {
    pub(super) async fn bind(
        socket_path: PathBuf,
        state: Arc<DaemonState<UnixProcessDriver>>,
        cancellation: CancellationToken,
        principal: Principal,
    ) -> Result<Self, SupervisorError> {
        prepare_socket(&socket_path).await?;
        let listener = UnixListener::bind(&socket_path).await?;
        // Keep the directory owned by the lifecycle owner. The observer can
        // connect but cannot redirect or replace this socket or the admin one.
        if principal.uid != unsafe { libc::geteuid() } {
            use std::ffi::CString;
            let parent = socket_path.parent().expect("prepared observer parent");
            for path in [parent, socket_path.as_path()] {
                let path = CString::new(path.as_os_str().as_encoded_bytes())
                    .map_err(|_| SupervisorError::Invalid("invalid observer path".into()))?;
                if unsafe { libc::chown(path.as_ptr(), libc::geteuid(), principal.gid) } != 0 {
                    return Err(std::io::Error::last_os_error().into());
                }
            }
            std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o750))?;
            std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o660))?;
        } else {
            set_owner_only(&socket_path).await?;
        }
        Ok(Self {
            listener,
            socket_path,
            state,
            cancellation,
            principal,
        })
    }

    pub(super) async fn run(mut self) -> Result<(), SupervisorError> {
        let capacity = Arc::new(Semaphore::new(CONNECTION_CAPACITY));
        let mut tasks = JoinSet::new();
        let result = loop {
            let stream = tokio::select! {
                _ = self.cancellation.cancelled() => break Ok(()),
                joined = tasks.join_next(), if !tasks.is_empty() => {
                    if matches!(joined, Some(Err(_))) {
                        break Err(SupervisorError::Invalid("observer connection failed".into()));
                    }
                    continue;
                },
                accepted = self.listener.accept() => match accepted {
                    Ok(stream) => stream,
                    Err(error) => break Err(error.into()),
                },
            };
            // Kernel identity precedes frame allocation and JSON decoding.
            if stream.ensure_peer_user(self.principal.uid).is_err() {
                continue;
            }
            let Ok(permit) = Arc::clone(&capacity).try_acquire_owned() else {
                continue;
            };
            let state = Arc::clone(&self.state);
            tasks.spawn(async move {
                let _permit = permit;
                let _ = timeout(IO_TIMEOUT, serve(stream, state)).await;
            });
        };
        tasks.abort_all();
        while tasks.join_next().await.is_some() {}
        result
    }
}

impl Drop for ObserverServer {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.socket_path);
    }
}

async fn serve(
    stream: UnixStream,
    state: Arc<DaemonState<UnixProcessDriver>>,
) -> Result<(), SupervisorError> {
    let (reader, mut writer) = tokio::io::split(stream);
    let mut reader = BufReader::new(reader).take(MAX_SUPERVISORD_CONTROL_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = reader.read_until(b'\n', &mut frame).await?;
    if count == 0 || count as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Ok(());
    }
    let request: RobrixSupervisordRequest = match serde_json::from_slice(&frame) {
        Ok(request) => request,
        Err(_) => return Ok(()),
    };
    if request.validate().is_err() {
        return Ok(());
    }
    let request: SupervisordRequest = request.into();
    let payload = state
        .execution
        .view
        .respond(
            &request.method,
            Instant::now(),
            state.observed_faults.load(Ordering::Relaxed),
        )
        .ok_or_else(|| SupervisorError::Invalid("observer query has no read projection".into()))?;
    let response = RobrixSupervisordResponse::try_from(SupervisordResponse {
        schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
        request_id: request.request_id,
        payload,
    })
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    response
        .validate(request.request_id)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let mut bytes = serde_json::to_vec(&response)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_ROBRIX_SUPERVISORD_RESPONSE_BYTES {
        return Err(SupervisorError::Invalid(
            "observer response exceeded frame bound".into(),
        ));
    }
    writer.write_all(&bytes).await?;
    writer.shutdown().await?;
    Ok(())
}

#[cfg(test)]
#[path = "daemon_observer_tests.rs"]
mod tests;

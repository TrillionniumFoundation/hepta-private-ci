//! A workload-readable endpoint whose decoder cannot represent a mutation.

use super::*;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    request_id: u64,
    method: Query,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
enum Query {
    RuntimeModuleSelection { module_id: String },
}

pub(super) struct SelectionServer {
    listener: UnixListener,
    socket_path: PathBuf,
    state: Arc<DaemonState<UnixProcessDriver>>,
    cancellation: CancellationToken,
    uid: u32,
}

impl SelectionServer {
    pub(super) async fn bind(
        socket_path: PathBuf,
        state: Arc<DaemonState<UnixProcessDriver>>,
        cancellation: CancellationToken,
        uid: u32,
        gid: u32,
    ) -> Result<Self, SupervisorError> {
        use std::os::unix::fs::PermissionsExt;
        prepare_socket(&socket_path).await?;
        let listener = UnixListener::bind(&socket_path).await?;
        let parent = socket_path.parent().expect("prepared socket parent");
        if uid != unsafe { libc::geteuid() } {
            use std::ffi::CString;
            for path in [parent, socket_path.as_path()] {
                let path = CString::new(path.as_os_str().as_encoded_bytes())
                    .map_err(|_| SupervisorError::Invalid("invalid socket path".into()))?;
                if unsafe { libc::chown(path.as_ptr(), 0, gid) } != 0 {
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
            uid,
        })
    }

    pub(super) async fn run(mut self) -> Result<(), SupervisorError> {
        let capacity = Arc::new(Semaphore::new(CONNECTION_CAPACITY));
        let mut tasks = JoinSet::new();
        loop {
            let stream = tokio::select! {
                _ = self.cancellation.cancelled() => break,
                joined = tasks.join_next(), if !tasks.is_empty() => { if matches!(joined, Some(Err(_))) { return Err(SupervisorError::Invalid("selection connection failed".into())); } continue; },
                accepted = self.listener.accept() => accepted?,
            };
            if stream.ensure_peer_user(self.uid).is_err() {
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
        }
        tasks.abort_all();
        while tasks.join_next().await.is_some() {}
        Ok(())
    }
}

impl Drop for SelectionServer {
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
    let mut bytes = Vec::new();
    let count = reader.read_until(b'\n', &mut bytes).await?;
    if count == 0 || count as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES || !bytes.ends_with(b"\n") {
        return Ok(());
    }
    let request: Request = match serde_json::from_slice(&bytes) {
        Ok(request) => request,
        Err(_) => return Ok(()),
    };
    if request.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION || request.request_id == 0 {
        return Ok(());
    }
    let Query::RuntimeModuleSelection { module_id } = request.method;
    if codex_hepta_agent_protocol::validate_runtime_module_id(&module_id).is_err() {
        return Ok(());
    }
    let payload = match state
        .runtime_modules
        .lock()
        .await
        .module_selection(&module_id)
    {
        Ok(selection) => SupervisordPayload::RuntimeModuleSelection { selection },
        Err(error) => error_payload("module_selection_unavailable", &error.to_string(), None),
    };
    write_response(
        &mut writer,
        SupervisordResponse {
            schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
            request_id: request.request_id,
            payload,
        },
    )
    .await
}

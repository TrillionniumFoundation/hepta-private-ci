//! One bounded enrollment per daemon startup, through a private local socket.
//! Grants bind prepared owner observations; execution does not disclose text.

use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_memory::MemoryCellQueryV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;
use tokio::net::UnixStream;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::native_memory_host_bootstrap::NativeMemoryProcessHost;
use crate::native_memory_host_session::SessionSlot;
use crate::native_memory_process_trust::string;

const FRAME_LIMIT: u64 = 1_048_576;
const IO_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    sequence: u64,
    command: Command,
}

#[derive(Deserialize)]
#[serde(tag = "method", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Status,
    Prepare {
        run_id: String,
        query: MemoryCellQueryV1,
    },
    Execute {
        prepared_id: String,
        grant: SignedFinalUseGrant,
    },
    Deliver,
    Revoke {
        update: SignedFinalUseRevocationUpdate,
    },
}

struct Shared {
    host: Arc<NativeMemoryProcessHost>,
    sequence: Mutex<u64>,
    session: SessionSlot,
    cancellation: CancellationToken,
}

pub(crate) struct NativeMemoryProcessControl {
    listener: UnixListener,
    socket: PathBuf,
    shared: Arc<Shared>,
    owner_uid: u32,
}

impl NativeMemoryProcessControl {
    pub fn bind(
        host: Arc<NativeMemoryProcessHost>,
        cancellation: CancellationToken,
    ) -> Result<Self, AgentdError> {
        let socket = host.descriptor.control_socket.clone();
        let home = std::fs::metadata(&host.identity.home_root)?;
        if home.mode() & 0o077 != 0 || socket.symlink_metadata().is_ok() {
            return Err(AgentdError::Invalid(
                "private unused current-control socket required".into(),
            ));
        }
        let listener = UnixListener::bind(&socket)?;
        std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600))?;
        Ok(Self {
            listener,
            socket,
            owner_uid: home.uid(),
            shared: Arc::new(Shared {
                host,
                sequence: Mutex::new(0),
                session: SessionSlot::new(cancellation.clone()),
                cancellation,
            }),
        })
    }

    pub async fn run(self) -> Result<(), AgentdError> {
        let capacity = Arc::new(Semaphore::new(4));
        let mut connections = JoinSet::new();
        loop {
            tokio::select! {
                _ = self.shared.cancellation.cancelled() => break,
                _ = connections.join_next(), if !connections.is_empty() => {},
                accepted = self.listener.accept() => {
                    let (stream, _) = accepted?;
                    if stream.peer_cred()?.uid() != self.owner_uid { continue; }
                    let Ok(permit) = Arc::clone(&capacity).try_acquire_owned() else { continue; };
                    let shared = Arc::clone(&self.shared);
                    connections.spawn(async move { let _permit = permit; let _ = serve(stream, shared).await; });
                }
            }
        }
        while connections.join_next().await.is_some() {}
        Ok(())
    }
}

impl Drop for NativeMemoryProcessControl {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.socket);
    }
}

async fn serve(mut stream: UnixStream, shared: Arc<Shared>) -> Result<(), String> {
    let mut bytes = Vec::new();
    tokio::time::timeout(
        IO_TIMEOUT,
        (&mut stream).take(FRAME_LIMIT + 1).read_to_end(&mut bytes),
    )
    .await
    .map_err(string)?
    .map_err(string)?;
    if bytes.len() as u64 > FRAME_LIMIT {
        return Err("current-control frame exceeds bound".into());
    }
    let request: Request = serde_json::from_slice(&bytes).map_err(string)?;
    if request.schema_version != 1 || request.sequence == 0 {
        return Err("current-control schema rejected".into());
    }
    let sequence = request.sequence;
    let replay = {
        let mut previous = shared.sequence.lock().map_err(string)?;
        let replay = sequence <= *previous;
        if !replay {
            *previous = sequence;
        }
        replay
    };
    if replay {
        return write_response(&mut stream, sequence, Err("control sequence replay".into())).await;
    }
    if shared.cancellation.is_cancelled() {
        return Err("current process runtime is closed".into());
    }
    // Delivery constructs bytes before its final asynchronous source check.
    // Writability is awaited first; a synchronous write immediately follows
    // revalidation, without another authorization gap introduced by this layer.
    if matches!(request.command, Command::Deliver) {
        return deliver(&mut stream, &shared, sequence).await;
    }
    let result = execute(request.command, sequence, &shared).await;
    write_response(&mut stream, sequence, result).await
}

async fn execute(command: Command, sequence: u64, shared: &Shared) -> Result<Value, String> {
    let host = &shared.host;
    if let Command::Revoke { update } = command {
        // Independent of the session lock, so a host can revoke while a worker
        // is awaiting source revalidation or decoding. The real owner fences it.
        host.ndu
            .lock()
            .map_err(string)?
            .apply_read_revocation_update(&update)
            .map_err(string)?;
        return Ok(
            json!({"revocation_applied": true, "authority_epoch": update.update.head.authority_epoch, "revision": update.update.head.revision}),
        );
    }
    let mut session = shared.session.claim()?;
    match command {
        Command::Status => Ok(json!({
            "daemon_pid": std::process::id(), "bootstrap_sha256": host.descriptor_sha256.to_string(),
            "attempted": session.attempted, "completed": session.result.is_some(),
            "trust_profile": "linux-local-compatibility-v1", "production_qualified": false,
        })),
        Command::Prepare { run_id, query } => {
            if session.prepared.is_some() || session.attempted || query.key != host.source.key {
                return Err("current session already enrolled or typed key differs".into());
            }
            let prepared = host
                .registration
                .host()
                .map_err(string)?
                .prepare_read(&run_id, query)
                .map_err(string)?;
            let prepared_id = Digest32::of_bytes(
                &serde_json::to_vec(&(
                    host.descriptor_sha256.to_string(),
                    std::process::id(),
                    sequence,
                    prepared.binding(),
                ))
                .map_err(string)?,
            )
            .to_string();
            let response = json!({"prepared_id": prepared_id, "binding": prepared.binding()});
            session.prepared = Some((prepared_id, prepared));
            Ok(response)
        }
        Command::Execute { prepared_id, grant } => {
            if session.attempted
                || session
                    .prepared
                    .as_ref()
                    .is_none_or(|(id, _)| id != &prepared_id)
            {
                return Err("unknown or consumed prepared read".into());
            }
            session.attempted = true;
            let (_, prepared) = session.prepared.take().ok_or("prepared read absent")?;
            let query = prepared.query().clone();
            let owner = host
                .registration
                .host()
                .map_err(string)?
                .open_shadow(
                    prepared,
                    &grant,
                    host.source(),
                    host.files()?,
                    host.descriptor.shadow.profile(&host.source.model)?,
                )
                .await
                .map_err(string)?;
            let result = owner.read(query).await.map_err(string)?;
            let response = json!({"execution_sha256": Digest32::of_bytes(&serde_json::to_vec(result.execution()).map_err(string)?).to_string(),
                "source_root": result.source().binding.source_content_sha256,
                "decoder_queries": result.execution().decoder_queries, "feature_forward_calls": result.execution().feature_forward_calls});
            session.result = Some((owner, result));
            Ok(response)
        }
        Command::Deliver | Command::Revoke { .. } => Err("invalid command state".into()),
    }
}

async fn deliver(stream: &mut UnixStream, shared: &Shared, sequence: u64) -> Result<(), String> {
    let session = shared.session.claim()?;
    let Some((owner, result)) = session.result.as_ref() else {
        return write_response(stream, sequence, Err("no completed current read".into())).await;
    };
    let observation = result.observation();
    let payload = json!({"execution": result.execution(), "source": result.source(),
        "tick_id": observation.tick_id.as_str(), "checkpoint_before": observation.checkpoint_before.to_string(),
        "checkpoint_after": observation.checkpoint_after.to_string(), "abstain": observation.abstain,
        "authority_grants_any": observation.authority.grants_any(),
        "context_binding": result.context_binding().map(|binding| binding.digest().to_string()),
        "production_qualified": false});
    let bytes = response_bytes(sequence, Ok(payload))?;
    tokio::time::timeout(IO_TIMEOUT, stream.writable())
        .await
        .map_err(string)?
        .map_err(string)?;
    let checked = owner.revalidate_delivery(result).await.map_err(string);
    if shared.cancellation.is_cancelled() {
        return Err("current process runtime is closed".into());
    }
    if let Err(error) = checked {
        return write_response(stream, sequence, Err(error)).await;
    }
    match stream.try_write(&bytes) {
        Ok(written) if written == bytes.len() => Ok(()),
        _ => Err("current delivery was not one complete nonblocking write".into()),
    }
}

fn response_bytes(sequence: u64, result: Result<Value, String>) -> Result<Vec<u8>, String> {
    let value = match result {
        Ok(payload) => {
            json!({"schema_version": 1, "sequence": sequence, "ok": true, "payload": payload})
        }
        Err(error) => {
            json!({"schema_version": 1, "sequence": sequence, "ok": false, "error": error.chars().take(2048).collect::<String>()})
        }
    };
    let bytes = serde_json::to_vec(&value).map_err(string)?;
    if bytes.len() as u64 > FRAME_LIMIT {
        return Err("current-control response exceeds bound".into());
    }
    Ok(bytes)
}

async fn write_response(
    stream: &mut UnixStream,
    sequence: u64,
    result: Result<Value, String>,
) -> Result<(), String> {
    tokio::time::timeout(
        IO_TIMEOUT,
        stream.write_all(&response_bytes(sequence, result)?),
    )
    .await
    .map_err(string)?
    .map_err(string)
}

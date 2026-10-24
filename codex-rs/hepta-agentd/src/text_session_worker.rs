//! Nonblocking native-UI boundary. The signer is an independently installed
//! owner service; no signing key, sequence allocator, or durable journal lives
//! in this worker. A host must authenticate the human before installing it.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::mpsc;
use std::thread;
use codex_hepta_types::Digest32;

use super::*;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TextSignerEndpoint {
    pub socket_path: PathBuf,
    pub owner_uid: u32,
    pub owner_pid: u32,
}

/// The private host deduplicates request_id with the exact owner/thread/text.
/// `lookup` MUST NOT sign or allocate a new sequence if the original is absent.
#[derive(Serialize)]
struct SignerRequest<'a> {
    schema_version: u32,
    operation: &'a str,
    request_id: &'a str,
    agent_id: &'a AgentId,
    spawn_generation: u64,
    thread_id: &'a str,
    text: &'a str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SignerResponse {
    schema_version: u32,
    request_id: String,
    envelope: AuthBusTextIngress,
}

#[derive(Clone, Debug)]
pub enum TextCommand {
    Submit { request_id: String, text: String },
    Interrupt { message_id: String },
    Reconcile { message_id: String },
    Reconnect,
}

/// A projection reference to the host-retained signed bytes. This contains no
/// signature/key and cannot authorize submission without the actual envelope.
#[derive(Clone, Debug)]
pub struct TextPrepared {
    pub host_reference: String,
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub payload_sha256: [u8; 32],
    pub envelope_sha256: [u8; 32],
    pub text: String,
}

#[derive(Clone, Debug)]
pub enum TextWorkerEvent {
    /// Connection identity only; never a readiness or authority attestation.
    Connected { connection_id: u64 },
    Prepared { connection_id: u64, reference: TextPrepared },
    Admission { connection_id: u64, request_id: String, message_id: String, status: AuthBusTextStatus },
    Notification(AgentdTextEvent),
    Reconciled { connection_id: u64, view: TextReconciliation },
    Unavailable { request_id: Option<String>, message: String },
}

/// A single bounded background worker for a native composition. Draw/IME only
/// call try_send/try_recv; dropping it closes its client and does not cancel a
/// durable turn. The original owner remains responsible for shutdown/recovery.
pub struct AgentdTextWorker {
    commands: tokio::sync::mpsc::Sender<TextCommand>,
    events: mpsc::Receiver<TextWorkerEvent>,
}

impl AgentdTextWorker {
    pub fn start(config: AgentdTextSessionConfig, signer: TextSignerEndpoint, waker: Arc<dyn Fn() + Send + Sync>) -> Result<Self, TextSessionError> {
        if !signer.socket_path.is_absolute() || signer.owner_pid == 0 { return Err(TextSessionError::Identity); }
        let (commands, receiver) = tokio::sync::mpsc::channel(8);
        let (sender, events) = mpsc::sync_channel(128);
        thread::Builder::new().name("hepta-text-session".into()).spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build();
            let result = match runtime {
                Ok(runtime) => {
                    let result = runtime.block_on(run(config, signer, receiver, &sender, &waker));
                    runtime.shutdown_timeout(Duration::from_secs(1));
                    result
                }
                Err(error) => Err(unavailable(error)),
            };
            if let Err(error) = result {
                let _ = sender.try_send(TextWorkerEvent::Unavailable { request_id: None, message: error.to_string() });
                waker();
            }
        }).map_err(unavailable)?;
        Ok(Self { commands, events })
    }

    pub fn try_send(&self, command: TextCommand) -> Result<(), TextSessionError> {
        self.commands.try_send(command).map_err(|_| TextSessionError::Capacity)
    }

    pub fn try_recv(&self) -> Result<Option<TextWorkerEvent>, TextSessionError> {
        match self.events.try_recv() {
            Ok(event) => Ok(Some(event)),
            Err(mpsc::TryRecvError::Empty) => Ok(None),
            Err(mpsc::TryRecvError::Disconnected) => Err(unavailable("text worker stopped")),
        }
    }
}

async fn run(config: AgentdTextSessionConfig, signer: TextSignerEndpoint, mut commands: tokio::sync::mpsc::Receiver<TextCommand>, output: &mpsc::SyncSender<TextWorkerEvent>, waker: &Arc<dyn Fn() + Send + Sync>) -> Result<(), TextSessionError> {
    let mut session = AgentdTextSession::connect(config.clone()).await?;
    let emit = |event| -> Result<(), TextSessionError> {
        output.try_send(event).map_err(|_| TextSessionError::Capacity)?;
        waker();
        Ok(())
    };
    emit(TextWorkerEvent::Connected { connection_id: session.requests.connection_id() })?;
    // A retained request maps to one exact human intent. An ambiguous signing
    // response is subsequently looked up, never reissued as a fresh signature.
    let mut intents = BTreeMap::<String, String>::new();
    let mut inflight = tokio::task::JoinSet::new();
    let mut stream_open = true;
    let mut poll = tokio::time::interval(Duration::from_millis(250));
    poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            event = session.events.next(), if stream_open => match event {
                Ok(Some(event)) => emit(TextWorkerEvent::Notification(event))?,
                Ok(None) => stream_open = false,
                Err(error) => {
                    stream_open = false;
                    emit(TextWorkerEvent::Unavailable { request_id: None, message: error.to_string() })?;
                }
            },
            result = inflight.join_next(), if !inflight.is_empty() => {
                match result.ok_or_else(|| unavailable("request task missing"))?.map_err(unavailable)? {
                    Ok(event) => emit(event)?,
                    Err((request_id, error)) => emit(TextWorkerEvent::Unavailable { request_id, message: error.to_string() })?,
                }
            },
            _ = poll.tick(), if inflight.is_empty() && stream_open => {
                let next = session.requests.shared.current()?.pending.values()
                    .find(|pending| (pending.cancellation_requested || pending.recovered) && !pending.terminal)
                    .map(|pending| pending.envelope.message_id.clone());
                if let Some(message_id) = next {
                    let requests = session.requests.clone();
                    inflight.spawn(async move {
                        requests.reconcile(&message_id).await
                            .map(|view| TextWorkerEvent::Reconciled { connection_id: requests.connection_id(), view })
                            .map_err(|error| (Some(message_id), error))
                    });
                }
            },
            command = commands.recv() => {
                let Some(command) = command else { break; };
                if inflight.len() >= 4 { emit(TextWorkerEvent::Unavailable { request_id: None, message: "text request capacity reached".into() })?; continue; }
                let interrupt_requested = matches!(&command, TextCommand::Interrupt { .. });
                match command {
                    TextCommand::Submit { request_id, text } => {
                        if request_id.is_empty() || request_id.len() > 192
                            || !request_id.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
                            || text.trim().is_empty() || text.len() > 8192 {
                            emit(TextWorkerEvent::Unavailable { request_id: Some(request_id), message: "invalid signed text intent".into() })?;
                            continue;
                        }
                        let lookup = if let Some(prior) = intents.get(&request_id) {
                            if prior != &text { emit(TextWorkerEvent::Unavailable { request_id: Some(request_id), message: "text intent identity conflict".into() })?; continue; }
                            true
                        } else {
                            if intents.len() >= MAX_RETAINED { return Err(TextSessionError::Capacity); }
                            intents.insert(request_id.clone(), text.clone());
                            false
                        };
                        let requests = session.requests.clone();
                        let signer = signer.clone();
                        let config = config.clone();
                        let prepared_output = output.clone();
                        let prepared_waker = waker.clone();
                        inflight.spawn(async move {
                            let result = async {
                                let envelope = signed_input(&signer, &config, &request_id, &text, lookup).await?;
                                let claims = crate::authbus_text_claims(&config.agent_id, &envelope).map_err(unavailable)?;
                                let envelope_bytes = serde_json::to_vec(&envelope).map_err(unavailable)?;
                                let reference = TextPrepared {
                                    host_reference: request_id.clone(), issuer_id: envelope.issuer_id.clone(), key_epoch: envelope.key_epoch,
                                    message_id: envelope.message_id.clone(), sequence: envelope.sequence, expires_at_ms: envelope.expires_at_ms,
                                    payload_sha256: *claims.payload_digest.as_array(),
                                    envelope_sha256: *Digest32::of_bytes(&envelope_bytes).as_array(), text: envelope.body.text.clone(),
                                };
                                prepared_output.try_send(TextWorkerEvent::Prepared { connection_id: requests.connection_id(), reference })
                                    .map_err(|_| TextSessionError::Capacity)?;
                                prepared_waker();
                                let message_id = envelope.message_id.clone();
                                let status = requests.submit_signed(envelope).await?;
                                Ok(TextWorkerEvent::Admission { connection_id: requests.connection_id(), request_id: request_id.clone(), message_id, status })
                            }.await;
                            result.map_err(|error| (Some(request_id), error))
                        });
                    }
                    TextCommand::Interrupt { message_id } | TextCommand::Reconcile { message_id } => {
                        let interrupt = interrupt_requested;
                        let requests = session.requests.clone();
                        inflight.spawn(async move {
                            let result = if interrupt { requests.interrupt(&message_id).await } else { requests.reconcile(&message_id).await };
                            result.map(|view| TextWorkerEvent::Reconciled { connection_id: requests.connection_id(), view })
                                .map_err(|error| (Some(message_id), error))
                        });
                    }
                    TextCommand::Reconnect => {
                        if !inflight.is_empty() { emit(TextWorkerEvent::Unavailable { request_id: None, message: "wait for retained requests before reconnect".into() })?; continue; }
                        let next = session.reattach(config.clone()).await?;
                        session.events.shutdown().await?;
                        session = next;
                        stream_open = true;
                        emit(TextWorkerEvent::Connected { connection_id: session.requests.connection_id() })?;
                        let ids = session.requests.shared.current()?.pending.keys().cloned().collect::<Vec<_>>();
                        for message_id in ids {
                            let view = session.requests.reconcile(&message_id).await?;
                            emit(TextWorkerEvent::Reconciled { connection_id: session.requests.connection_id(), view })?;
                        }
                    }
                }
            }
        }
    }
    session.requests.fence()?;
    inflight.abort_all();
    while inflight.join_next().await.is_some() {}
    session.events.shutdown().await
}

#[cfg(unix)]
async fn signed_input(endpoint: &TextSignerEndpoint, config: &AgentdTextSessionConfig, request_id: &str, text: &str, lookup: bool) -> Result<AuthBusTextIngress, TextSessionError> {
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    let work = async {
        let mut stream = tokio::net::UnixStream::connect(&endpoint.socket_path).await.map_err(unavailable)?;
        let peer = stream.peer_cred().map_err(unavailable)?;
        if peer.uid() != endpoint.owner_uid || peer.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(endpoint.owner_pid) {
            return Err(TextSessionError::Identity);
        }
        let mut bytes = serde_json::to_vec(&SignerRequest {
            schema_version: 1, operation: if lookup { "lookup" } else { "sign" }, request_id,
            agent_id: &config.agent_id, spawn_generation: config.spawn_generation,
            thread_id: &config.thread_id, text,
        }).map_err(unavailable)?;
        if bytes.len() > 32768 { return Err(TextSessionError::Capacity); }
        bytes.push(b'\n');
        stream.write_all(&bytes).await.map_err(unavailable)?;
        let mut reader = tokio::io::BufReader::new(stream).take(32769);
        let mut bytes = Vec::new();
        reader.read_until(b'\n', &mut bytes).await.map_err(unavailable)?;
        if bytes.len() > 32768 || !bytes.ends_with(b"\n") { return Err(TextSessionError::Capacity); }
        let response: SignerResponse = serde_json::from_slice(&bytes).map_err(unavailable)?;
        if response.schema_version != 1 || response.request_id != request_id
            || response.envelope.body.thread_id != config.thread_id
            || response.envelope.body.spawn_generation != config.spawn_generation
            || response.envelope.body.text != text
        { return Err(TextSessionError::Identity); }
        Ok(response.envelope)
    };
    tokio::time::timeout(REQUEST_TIMEOUT, work).await.map_err(unavailable)?
}

#[cfg(not(unix))]
async fn signed_input(_endpoint: &TextSignerEndpoint, _config: &AgentdTextSessionConfig, _request_id: &str, _text: &str, _lookup: bool) -> Result<AuthBusTextIngress, TextSessionError> {
    Err(unavailable("installed Unix signer transport is unavailable on this platform"))
}

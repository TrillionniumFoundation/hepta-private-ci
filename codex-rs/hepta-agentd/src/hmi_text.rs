//! Private text presentation port registered under the actual Agentd owner.
//! Signed input uses its existing AuthBus outbox and relay, never a second queue.
use crate::AgentdError;
use crate::AgentdState;
use crate::AuthBusTextIngress;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_codex_adapter::hmi::*;
use serde_json::Value;
use serde_json::json;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

#[path = "hmi_text_session.rs"]
mod session;
pub(super) type Bridge = HmiOwnerBridgeV1<TextAuthority, TextPort, NoAudio>;
pub(super) struct UiEnvelope {
    value: Value,
    guard: Option<UiGate>,
}
pub(super) enum UiKind {
    Output,
    Context,
}
pub(super) struct UiGate {
    requests: HmiRequestsV1,
    scope: HmiOutputScopeV1,
    authority: TextAuthority,
    kind: UiKind,
}
pub(super) type Sender = mpsc::Sender<UiEnvelope>;
pub(super) fn emit(tx: &Sender, value: Value) -> Result<(), AgentdError> {
    tx.try_send(UiEnvelope { value, guard: None })
        .map_err(|_| invalid("HMI UI receiver closed or full"))
}
pub(super) fn invalid(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(format!("HMI text: {message}"))
}

#[derive(Clone)]
pub(super) struct TextAuthority {
    state: Arc<AgentdState>,
    active: Arc<AtomicBool>,
    binding: HmiBindingV1,
}
impl HmiOwnerAuthorityV1 for TextAuthority {
    fn check_current(&self, binding: &HmiBindingV1) -> Result<(), HmiError> {
        let check = || -> Result<(), AgentdError> {
            if !self.active.load(Ordering::SeqCst) || binding != &self.binding {
                return Err(invalid("text owner fenced"));
            }
            self.state.refresh_generation()?;
            crate::authbus_ingress::require_ready(&self.state)?;
            let host = crate::authbus_ingress::attached(&self.state)?;
            let trust = host.trust(&self.state)?;
            let issuer = trust.issuer()?;
            if !trust.permits(&binding.thread_id)
                || issuer.issuer_id.as_str() != binding.principal_id
                || issuer.key_epoch.get() != binding.device_generation
                || self.state.identity().spawn_generation != binding.organ_generation
            {
                return Err(invalid(
                    "current issuer/thread/generation permission changed",
                ));
            }
            Ok(())
        };
        check().map_err(|e| HmiError::Transport(e.to_string()))
    }
}
pub(super) struct TextPort {
    connection: u64,
    tx: Sender,
}
impl HmiOwnerMediaV1 for TextPort {
    fn connection_id(&self) -> u64 {
        self.connection
    }
    fn capture_generation(&self) -> u64 {
        0
    }
    async fn verify_source(&self, _: &HmiCapturedAudioRefV1) -> Result<(), HmiError> {
        Err(HmiError::Invalid("text port has no captured audio"))
    }
    async fn attach_turn(&self, _: &HmiOutputScopeV1) -> Result<(), HmiError> {
        Ok(())
    }
    async fn speak(&self, _: HmiSpeechRequestV1) -> Result<HmiMediaPresentationV1, HmiError> {
        Err(HmiError::Invalid("text port has no speech authority"))
    }
    async fn retire_output(&self, epoch: u64) -> Result<(), HmiError> {
        emit(
            &self.tx,
            json!({"type":"outputRetired","connectionId":self.connection,"outputEpoch":epoch}),
        )
        .map_err(|e| HmiError::Transport(e.to_string()))
    }
    async fn revoke_capture(&self) -> Result<(), HmiError> {
        Ok(())
    } // No capture exists in this text-only port.
}
pub(super) struct NoAudio;
impl HmiOwnerObservationsV1 for NoAudio {
    async fn observe_final(
        &self,
        _: &HmiBindingV1,
        _: &HmiOwnerTranscriptV1,
        _: &str,
        _: &str,
        _: codex_app_server_protocol::ThreadQueueReconcileMode,
    ) -> Result<HmiObservationReceiptV1, HmiError> {
        Err(HmiError::Invalid(
            "AuthBus text is not a captured-audio observation ingress",
        ))
    }
}
pub(super) fn bridge(
    connection: &HmiConnectionV1,
    state: Arc<AgentdState>,
    active: Arc<AtomicBool>,
    tx: Sender,
) -> Result<Arc<Bridge>, AgentdError> {
    let authority = TextAuthority {
        state,
        active,
        binding: connection.requests.binding().clone(),
    };
    HmiOwnerBridgeV1::attach_text(
        connection.requests.clone(),
        authority,
        TextPort {
            connection: connection.requests.connection_id(),
            tx,
        },
        NoAudio,
    )
    .map(Arc::new)
    .map_err(invalid)
}
pub(super) fn authenticate(
    state: &AgentdState,
    request: &AuthBusTextIngress,
) -> Result<String, AgentdError> {
    state.refresh_generation()?;
    crate::authbus_ingress::require_ready(state)?;
    let host = crate::authbus_ingress::attached(state)?;
    let trust = host.trust(state)?;
    if !trust.permits(&request.body.thread_id)
        || request.body.spawn_generation != state.identity().spawn_generation
    {
        return Err(invalid(
            "signed text is outside current thread/generation permission",
        ));
    }
    let now = crate::authbus_ingress::now_ms()?;
    if request.expires_at_ms <= now || request.expires_at_ms.saturating_sub(now) > 300_000 {
        return Err(invalid("signed text expiry is invalid"));
    }
    let claims = crate::authbus_text_claims(&state.identity().agent_id, request)?;
    let scope = claims.scope_digest;
    let digest = claims.payload_digest;
    let message = SignedMessage {
        claims,
        signature: crate::authbus_trust::hex_bytes(&request.signature_hex)?,
    };
    let authenticated = message
        .authenticate(&trust.issuer()?, scope, digest, now)
        .map_err(invalid)?;
    Ok(authenticated.receipt().envelope_digest.to_string())
}

#[cfg(unix)]
pub(crate) async fn run(
    state: Arc<AgentdState>,
    active: Arc<AtomicBool>,
    cancel: CancellationToken,
) -> Result<(), AgentdError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    use tokio::io::AsyncWriteExt;
    use tokio::io::BufReader;
    let path = state.identity().run_root.join("hmi-text.sock");
    let mut listener = codex_uds::UnixListener::bind(&path).await?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let inode = std::fs::symlink_metadata(&path)?.ino();
    struct Cleanup {
        path: std::path::PathBuf,
        inode: u64,
        active: Arc<AtomicBool>,
    }
    impl Drop for Cleanup {
        fn drop(&mut self) {
            self.active.store(false, Ordering::SeqCst);
            if std::fs::symlink_metadata(&self.path).is_ok_and(|m| m.ino() == self.inode) {
                let _ = std::fs::remove_file(&self.path);
            }
        }
    }
    let _cleanup = Cleanup {
        path,
        inode,
        active: active.clone(),
    };
    loop {
        let socket = tokio::select! {_=cancel.cancelled()=>return Ok(()),connected=listener.accept()=>connected?};
        let (read, mut write) = tokio::io::split(socket);
        let mut read = BufReader::new(read);
        let (tx, mut rx) = mpsc::channel::<UiEnvelope>(32);
        let session_cancel = cancel.child_token();
        let writer_cancel = session_cancel.clone();
        // Both futures remain owned by this runtime task. Forced service
        // retirement drops its socket writer as well; no JoinHandle can detach.
        let writer = async move {
            let result = async {
                while let Some(envelope) = rx.recv().await {
                    if let Some(gate) = &envelope.guard {
                        let permitted = match gate.kind {
                            UiKind::Output => gate.requests.permits_output(&gate.scope),
                            UiKind::Context => gate.requests.permits_owner_context(&gate.scope),
                        }
                        .map_err(invalid)?;
                        if gate
                            .authority
                            .check_current(gate.requests.binding())
                            .is_err()
                            || !permitted
                        {
                            continue;
                        }
                    }
                    let mut bytes = serde_json::to_vec(&envelope.value)?;
                    if bytes.len() > 65_535 {
                        return Err(invalid("UI output exceeds 64 KiB"));
                    }
                    bytes.push(b'\n');
                    tokio::time::timeout(Duration::from_secs(2), async {
                        write.write_all(&bytes).await?;
                        write.flush().await
                    })
                    .await
                    .map_err(|_| invalid("UI output stalled"))??;
                }
                Ok::<(), AgentdError>(())
            }
            .await;
            writer_cancel.cancel();
            result
        };
        let session=async {
            let result=session::serve(&state,&active,&session_cancel,&mut read,&tx).await;
            if let Err(error)=&result {let _=emit(&tx,json!({"type":"sessionError","error":error.to_string()}));}
            drop(tx);result
        };
        tokio::pin!(writer,session);
        let result=tokio::select! {
            result=&mut session=>{
                if let other @ (Ok(Err(_))|Err(_))=tokio::time::timeout(Duration::from_secs(3),&mut writer).await {
                    eprintln!("HMI text writer ended without complete delivery: {other:?}");
                }
                result
            }
            writer_result=&mut writer=>{
                if let Err(error)=writer_result {eprintln!("HMI text writer failed: {error}");}
                tokio::time::timeout(Duration::from_secs(5),&mut session).await
                    .unwrap_or_else(|_|Err(invalid("session cleanup timed out; original admission remains unknown")))
            }
        };
        if let Err(error) = result {
            eprintln!("HMI text session: {error}");
        }
    }
}
#[cfg(not(unix))]
pub(crate) async fn run(
    _: Arc<AgentdState>,
    _: Arc<AtomicBool>,
    _: CancellationToken,
) -> Result<(), AgentdError> {
    Err(invalid("HMI text UDS requires Unix"))
}

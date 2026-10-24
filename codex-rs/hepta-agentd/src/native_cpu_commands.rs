//! Fixed Root control of the recovered original CPU writer. This channel
//! carries plans and observations only; K/D, authority and terminal state are
//! retained and validated by the original owners before any effect.
use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_memory::Hos2DeliveryId;
use codex_hepta_memory::Hos2Device;
use codex_hepta_memory::Hos2InstallOutcome;
use codex_hepta_memory::ProductionHos2Target;
use codex_hepta_memory::ProductionObjectiveSender;
use codex_hepta_memory::ProductionQueuedReceipt;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Command {
    Inspect,
    ReconcileRetained { occurrence_key: String },
    Prepare { operation: String, cap_ns: u64 },
    Dispatch { occurrence_key: String },
    Retire { through: Hos2DeliveryId },
    Window,
}

pub(super) struct Rpc {
    stream: UnixStream,
    guard: HostAuthorityPeerChannel,
    deadline: u64,
}
impl Rpc {
    pub(super) fn new(
        stream: UnixStream,
        peer: &CognitiveCheckpointPeerLifetime,
        pidfd: OwnedFd,
        deadline: u64,
    ) -> io::Result<Self> {
        let guard = HostAuthorityPeerChannel::from_stream(
            stream.try_clone()?,
            HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: peer.uid,
                    pid: peer.pid,
                },
                timeout: IO_TIMEOUT,
                lifetime: remaining(deadline)?,
                request_bound: 64 * 1024,
                response_bound: 64 * 1024,
            },
            pidfd,
        )
        .map_err(error)?;
        stream.set_read_timeout(Some(IO_TIMEOUT))?;
        stream.set_write_timeout(Some(IO_TIMEOUT))?;
        Ok(Self {
            stream,
            guard,
            deadline,
        })
    }
    pub(super) fn abort_stream(&self) -> io::Result<UnixStream> {
        self.stream.try_clone()
    }
    fn check(&self) -> io::Result<()> {
        remaining(self.deadline)?;
        self.guard.check_peer_lifetime().map_err(error)
    }
    pub(super) fn send<T: Serialize>(&mut self, value: &T) -> io::Result<()> {
        self.check()?;
        let bytes = serde_json::to_vec(value).map_err(error)?;
        if bytes.is_empty() || bytes.len() > 64 * 1024 {
            return Err(invalid("native observation bound"));
        }
        self.stream.write_all(&(bytes.len() as u32).to_be_bytes())?;
        self.stream.write_all(&bytes)?;
        self.check()
    }
    pub(super) fn read<T: serde::de::DeserializeOwned>(&mut self) -> io::Result<T> {
        self.check()?;
        let mut length = [0; 4];
        self.stream
            .set_read_timeout(Some(Duration::from_millis(100)))?;
        loop {
            self.check()?;
            match self.stream.read(&mut length[..1]) {
                Ok(1) => break,
                Ok(_) => {
                    return Err(io::Error::new(
                        io::ErrorKind::UnexpectedEof,
                        "native peer closed",
                    ));
                }
                Err(e)
                    if matches!(
                        e.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut
                    ) => {}
                Err(e) => return Err(e),
            }
        }
        self.stream
            .set_read_timeout(Some(Duration::from_millis(500)))?;
        self.stream.read_exact(&mut length[1..])?;
        let length = u32::from_be_bytes(length) as usize;
        if length == 0 || length > 64 * 1024 {
            return Err(invalid("native observation frame bound"));
        }
        let mut bytes = vec![0; length];
        self.stream.read_exact(&mut bytes)?;
        self.check()?;
        serde_json::from_slice(&bytes).map_err(error)
    }
    pub(super) fn call(&mut self, command: Command) -> io::Result<serde_json::Value> {
        self.send(&command)?;
        let value: serde_json::Value = self.read()?;
        if let Some(reason) = value.get("error") {
            return Err(invalid(format!("original owner refused: {reason}")));
        }
        Ok(value)
    }
}
impl Drop for Rpc {
    fn drop(&mut self) {
        let _ = self.stream.shutdown(Shutdown::Both);
    }
}

pub(super) struct Owner<T: codex_hepta_memory::CognitiveCheckpointTransport + 'static> {
    pub(super) host: Arc<crate::AgentdProductionWriterHost>,
    pub(super) device: Arc<crate::AgentdHos2Device>,
    pub(super) target: Arc<ProductionHos2Target>,
    pub(super) sender:
        ProductionObjectiveSender<codex_hepta_memory::ProtectedCognitiveCheckpoint<T>>,
    pub(super) root: Arc<crate::AgentdRootAuthoritySession>,
    pub(super) device_owner: codex_hepta_contracts::FinalUseAuthority,
    pub(super) notes_owner: codex_hepta_contracts::FinalUseAuthority,
    pub(super) bundle: crate::HostAuthorityPublicBootstrapV1,
    pub(super) queue: Option<ProductionQueuedReceipt>,
    pub(super) ingress: Arc<crate::native_cpu_ingress::NativeCpuIngress>,
}

pub(super) fn usage(device: &crate::AgentdHos2Device) -> io::Result<serde_json::Value> {
    let value = device.read_usage(1).map_err(error)?;
    Ok(
        serde_json::json!({"boot_id":value.boot_id,"observer_space_id":value.observer_space_id,
        "revision":value.revision,"sample_boottime_ns":value.sample_boottime_ns,
        "cumulative_cpu_ns":value.cumulative_cpu_ns,"window_start_ns":value.window_start_ns,
        "window_consumed_ns":value.window_consumed_ns,"active_cap_ns":value.active_cap_ns,
        "active_period_ns":value.active_period_ns,"event_sequence":value.event_sequence,
        "dropped_events":value.dropped_events,"heartbeat":platform::heartbeat()?}),
    )
}

impl<T: codex_hepta_memory::CognitiveCheckpointTransport + 'static> Owner<T> {
    pub(super) async fn run(mut self, mut rpc: Rpc) -> Result<(), crate::AgentdError> {
        self.ingress.attach_rpc(rpc.abort_stream()?)?;
        loop {
            if self.ingress.stopping() {
                return Ok(());
            }
            let received = tokio::task::spawn_blocking(move || {
                let command = rpc.read::<Command>();
                (rpc, command)
            })
            .await
            .map_err(|e| crate::AgentdError::Protocol(e.to_string()))?;
            rpc = received.0;
            let command = match received.1 {
                Ok(command) => command,
                Err(_) if self.ingress.stopping() => return Ok(()),
                Err(error) => return Err(error.into()),
            };
            let result = self.execute(command).await;
            if self.ingress.stopping() {
                return result.map(|_| ());
            }
            match result {
                Ok(value) => {
                    rpc = tokio::task::spawn_blocking(move || {
                        rpc.send(&value)?;
                        Ok::<_, io::Error>(rpc)
                    })
                    .await
                    .map_err(|e| crate::AgentdError::Protocol(e.to_string()))??;
                }
                Err(failure) => {
                    let message = serde_json::json!({"error":failure.to_string()});
                    let _ = tokio::task::spawn_blocking(move || rpc.send(&message)).await;
                    return Err(failure);
                }
            }
        }
    }
    async fn execute(&mut self, command: Command) -> Result<serde_json::Value, crate::AgentdError> {
        let fail = |e: String| crate::AgentdError::Protocol(e);
        let _mutation = if matches!(
            &command,
            Command::Prepare { .. } | Command::Dispatch { .. } | Command::Retire { .. }
        ) {
            Some(self.ingress.begin_mutation().await?)
        } else {
            None
        };
        let writer = self.host.writer();
        writer.verify_current_authority().await?;
        match command {
            Command::Inspect => {
                use std::os::unix::fs::MetadataExt;
                let lock = std::fs::metadata(
                    crate::authority_host_config::registered_identity(
                        &self.bundle.registered_identity,
                    )?
                    .layout
                    .writer_lock(),
                )?;
                let database = std::fs::metadata(writer.database_path())?;
                Ok(
                    serde_json::json!({"pid":std::process::id(),"agent_id":writer.owner_agent_id(),
                    "spawn_generation":self.bundle.writer.spawn_generation,
                    "issuer_key_sha256":codex_hepta_contracts::Sha256Digest::for_bytes(&self.bundle.issuer_key.verifying_key),
                    "writer_proof_sha256":self.bundle.writer_proof.sha256()?,
                    "device_frontier":self.device_owner.frontier().map_err(|e|fail(e.to_string()))?,
                    "notes_frontier":self.notes_owner.frontier().map_err(|e|fail(e.to_string()))?,
                    "owner_lock_device":lock.dev(),"owner_lock_inode":lock.ino(),
                    "store_device":database.dev(),"store_inode":database.ino(),
                    "usage":usage(&self.device)?}),
                )
            }

            Command::ReconcileRetained { occurrence_key } => {
                let (request, receipt, terminal) =
                    writer.retained_hos2_terminal(&occurrence_key).await?;
                // The exact request is recovered from the original ledger.
                // Query the same retained device/history owner; never install
                // again and never substitute current CPU cap for old D.
                let observed = match self.device.observe(&request).map_err(fail)? {
                    Hos2InstallOutcome::Observed(value) => value,
                    Hos2InstallOutcome::Contradiction(_) => {
                        return Err(fail(
                            "retained native request contradicts its original source".into(),
                        ));
                    }
                };
                let retained: serde_json::Value = serde_json::from_str(&terminal)?;
                if retained["observation"] != serde_json::to_value(&observed)? {
                    return Err(fail(
                        "actual old D differs from the original durable terminal".into(),
                    ));
                }
                writer.verify_current_authority().await?;
                Ok(
                    serde_json::json!({"pid":std::process::id(),"request_json":request.to_json().map_err(fail)?,
                    "receipt":receipt,"terminal_json":terminal,"usage":usage(&self.device)?}),
                )
            }
            Command::Prepare { operation, cap_ns } => {
                if self.queue.is_some()
                    || operation.is_empty()
                    || operation.len() > 64
                    || !operation
                        .bytes()
                        .all(|b| b.is_ascii_lowercase() || b == b'-')
                {
                    return Err(fail("native CPU command already pending or invalid".into()));
                }
                let sample = self.device.read_usage(1).map_err(fail)?;
                let delivery = writer
                    .next_hos2_delivery_candidate(sample.boot_id, sample.observer_space_id)
                    .await?;
                let request = self
                    .device
                    .install_request(delivery.sequence().map_err(fail)?, sample.revision, cap_ns)
                    .map_err(fail)?;
                if request.delivery != delivery {
                    return Err(fail("original candidate/native namespace differs".into()));
                }
                let payload = request.to_json().map_err(fail)?;
                let key = format!(
                    "native-cpu:{}:{}",
                    codex_hepta_contracts::Sha256Digest::for_bytes(&serde_json::to_vec(&delivery)?)
                        .as_str(),
                    operation
                );
                let intent = OperationIntentV1::new(
                    StableId::new(&key).map_err(|e| fail(e.to_string()))?,
                    StableId::new(writer.owner_agent_id().as_str())
                        .map_err(|e| fail(e.to_string()))?,
                    StableId::new(codex_hepta_memory::HOS2_DESTINATION_V1)
                        .map_err(|e| fail(e.to_string()))?,
                    Digest32::of_bytes(payload.as_bytes()),
                    request.scope_digest(),
                    Generation::new(self.root.authority().authority_epoch)
                        .map_err(|e| fail(e.to_string()))?,
                    None,
                )
                .map_err(|e| fail(e.to_string()))?;
                let receipt = writer
                    .prepare_operation(intent, codex_hepta_memory::HOS2_INSTALL_TOPIC_V1, payload)
                    .await?;
                let response = serde_json::json!({"operation":operation,"pid":std::process::id(),"occurrence_key":receipt.occurrence_key,
                    "request_json":receipt.payload_json,"payload_sha256":receipt.payload_sha256});
                self.queue = Some(receipt);
                Ok(response)
            }
            Command::Dispatch { occurrence_key } => {
                let queued = self
                    .queue
                    .as_ref()
                    .filter(|value| value.occurrence_key == occurrence_key)
                    .ok_or_else(|| {
                        fail(
                            "dispatch must reference the retained original queued operation".into(),
                        )
                    })?
                    .clone();
                let before = usage(&self.device)?;
                let receipt = self.host.dispatch_with_grant_provider(queued).await?;
                let after = usage(&self.device)?;
                self.sender
                    .acknowledge_owner_cut()
                    .await
                    .map_err(|e| fail(e.to_string()))?;
                self.queue.take();
                Ok(
                    serde_json::json!({"pid":std::process::id(),"receipt":receipt,"before":before,"after":after}),
                )
            }
            Command::Retire { through } => {
                let observation = writer.retire_hos2_through(&self.target, &through).await?;
                Ok(
                    serde_json::json!({"pid":std::process::id(),"delivery":through,"source_owner":writer.owner_agent_id(),
                    "source_generation":writer.generation(),"retired_through":observation.retired_through,
                    "next_sequence":observation.next_sequence}),
                )
            }
            Command::Window => {
                let first = usage(&self.device)?;
                tokio::time::sleep(Duration::from_millis(250)).await;
                let second = usage(&self.device)?;
                Ok(serde_json::json!({"pid":std::process::id(),"first":first,"second":second}))
            }
        }
    }
}

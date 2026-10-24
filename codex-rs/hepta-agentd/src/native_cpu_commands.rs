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

#[path = "native_cpu_prior_boot_observer.rs"]
mod prior_boot_observer;

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Command {
    Inspect,
    TransportObservation,
    ObservePreviousBoot {
        occurrence_key: String,
    },
    ReconcileRetained {
        occurrence_key: String,
    },
    Prepare {
        operation: String,
        cap_ns: u64,
    },
    Dispatch {
        occurrence_key: String,
    },
    DispatchCopyout {
        occurrence_key: String,
        hold_until_exit: bool,
    },
    ReconcileCopyout {
        occurrence_key: String,
    },
    Retire {
        through: Hos2DeliveryId,
    },
    Window,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StartupRetained {
    pub(super) occurrence_key: String,
    pub(super) topic: String,
    pub(super) payload_json: String,
    pub(super) state: codex_hepta_memory::LocalOutcomeState,
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
    pub(super) fn readable(&self) -> io::Result<bool> {
        use std::os::fd::AsRawFd;
        self.check()?;
        let mut poll = libc::pollfd {
            fd: self.stream.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: poll borrows exactly this one initialized descriptor record.
        let observed = unsafe { libc::poll(&mut poll, 1, 0) };
        // Capture errno before peer checks can issue unrelated syscalls.
        let failure = (observed < 0).then(io::Error::last_os_error);
        self.check()?;
        if let Some(failure) = failure {
            return Err(failure);
        }
        match (observed, poll.revents) {
            (0, 0) => Ok(false),
            (1, libc::POLLIN) => Ok(true),
            _ => Err(invalid(
                "authenticated observation channel is not readable or live",
            )),
        }
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
    // This consumes the one authenticated RPC. A successful crash scenario
    // never returns to this process or fabricates a completed dispatch reply.
    fn copyout_exit_boundary(
        mut self,
        occurrence_key: String,
    ) -> crate::hos2_device::AfterCopyoutFault {
        Box::new(move |diagnostic| {
            let observed = now().map_err(|e| e.to_string())?;
            let boundary_deadline = observed
                .checked_add(2_000_000_000)
                .ok_or("copyout boundary deadline overflow")?
                .min(self.deadline);
            self.stream
                .set_write_timeout(Some(
                    remaining(boundary_deadline).map_err(|e| e.to_string())?,
                ))
                .map_err(|e| e.to_string())?;
            self.send(
                &serde_json::json!({"phase":"copyout_fault_boundary","pid":std::process::id(),
                "occurrence_key":occurrence_key,"diagnostic":diagnostic,
                "observed_boottime_ns":observed,"pending_until_boottime_ns":boundary_deadline}),
            )
            .map_err(|e| e.to_string())?;
            loop {
                let left = remaining(boundary_deadline)
                    .map_err(|_| "actual copyout boundary elapsed before Manager exit")?;
                self.check().map_err(|e| e.to_string())?;
                self.stream
                    .set_read_timeout(Some(left.min(Duration::from_millis(50))))
                    .map_err(|e| e.to_string())?;
                let mut byte = [0_u8; 1];
                match self.stream.read(&mut byte) {
                    Err(e) if matches!(e.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut | io::ErrorKind::Interrupted) => {},
                    Err(e) => return Err(e.to_string()),
                    Ok(_) => return Err("copyout crash boundary requires actual Manager exit, not a Root reply or EOF".into()),
                }
            }
        })
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
    // Captured once through the original writer after recovery and before its
    // ordinary monitor is started. Later Inspect only copies this observation.
    pub(super) startup_retained: Vec<StartupRetained>,
    pub(super) kernel_bootstrap: Vec<u8>,
    pub(super) ingress: Arc<crate::native_cpu_ingress::NativeCpuIngress>,
}

pub(super) fn usage(device: &crate::AgentdHos2Device) -> io::Result<serde_json::Value> {
    if device.is_history_only() {
        // The original workload PID is only historical metadata for role5.
        // No CPU observation or heartbeat is attempted by this authority.
        return Ok(serde_json::Value::Null);
    }
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
            if let Command::DispatchCopyout {
                occurrence_key,
                hold_until_exit: true,
            } = command
            {
                let callback = rpc.copyout_exit_boundary(occurrence_key.clone());
                return match self.dispatch_copyout(occurrence_key, Some(callback)).await {
                    Err(failure) => Err(failure),
                    Ok(_) => Err(crate::AgentdError::Protocol(
                        "crash qualification returned from the original dispatch".into(),
                    )),
                };
            }
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
        if self.device.is_history_only()
            && matches!(
                &command,
                Command::Prepare { .. }
                    | Command::Dispatch { .. }
                    | Command::DispatchCopyout { .. }
                    | Command::Window
            )
        {
            return Err(fail(
                "history-only owner cannot admit, dispatch or observe CPU work".into(),
            ));
        }
        let _mutation = if matches!(
            &command,
            Command::Prepare { .. }
                | Command::Dispatch { .. }
                | Command::Retire { .. }
                | Command::ReconcileCopyout { .. }
        ) {
            Some(self.ingress.begin_mutation().await?)
        } else {
            None
        };
        let writer = self.host.writer();
        writer.verify_current_authority().await?;
        match command {
            Command::TransportObservation => self.transport_observation(),
            Command::ObservePreviousBoot { occurrence_key } => {
                self.observe_previous_boot(&occurrence_key).await
            }
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
                    "startup_retained":self.startup_retained,
                    "copyout":self.device.native_copyout_snapshot().map_err(fail)?,
                    "usage":usage(&self.device)?,"history_only":self.device.is_history_only(),
                    "kernel_bootstrap":self.kernel_bootstrap}),
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
            Command::DispatchCopyout {
                occurrence_key,
                hold_until_exit: false,
            } => self.dispatch_copyout(occurrence_key, None).await,
            Command::DispatchCopyout {
                hold_until_exit: true,
                ..
            } => Err(fail(
                "crash copyout must own its original authenticated RPC".into(),
            )),
            Command::ReconcileCopyout { occurrence_key } => {
                let before = writer
                    .retained_operation(&occurrence_key)
                    .await?
                    .ok_or_else(|| fail("original retained copyout operation is absent".into()))?;
                if before.topic != codex_hepta_memory::HOS2_INSTALL_TOPIC_V1 {
                    return Err(fail(
                        "copyout reconciliation requires the original HOS2 topic".into(),
                    ));
                }
                let before_calls = self.device.native_copyout_snapshot().map_err(fail)?;
                let reconciled = self
                    .host
                    .reconcile_for_destination(codex_hepta_memory::HOS2_DESTINATION_V1, 16)
                    .await?;
                let (request, receipt, terminal) =
                    writer.retained_hos2_terminal(&occurrence_key).await?;
                if request.to_json().map_err(fail)? != before.payload_json {
                    return Err(fail(
                        "original copyout K/D payload changed during observation".into(),
                    ));
                }
                let observed = match self.device.observe(&request).map_err(fail)? {
                    Hos2InstallOutcome::Observed(value) => value,
                    Hos2InstallOutcome::Contradiction(_) => {
                        return Err(fail(
                            "original copyout request contradicted its retained history".into(),
                        ));
                    }
                };
                let retained: serde_json::Value = serde_json::from_str(&terminal)?;
                if retained["observation"] != serde_json::to_value(&observed)? {
                    return Err(fail(
                        "actual old D differs from original reconciled terminal".into(),
                    ));
                }
                self.sender
                    .acknowledge_owner_cut()
                    .await
                    .map_err(|e| fail(e.to_string()))?;
                writer.verify_current_authority().await?;
                let after_calls = self.device.native_copyout_snapshot().map_err(fail)?;
                if after_calls.install_ioctl_count != before_calls.install_ioctl_count {
                    return Err(fail(
                        "observer-only copyout recovery dispatched an Install".into(),
                    ));
                }
                Ok(
                    serde_json::json!({"pid":std::process::id(),"request_json":request.to_json().map_err(fail)?,
                    "receipt":receipt,"terminal_json":terminal,"usage":usage(&self.device)?,
                    "before_state":before.state,"before_payload_json":before.payload_json,
                    "reconciled_count":reconciled,"copyout":after_calls}),
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
    async fn dispatch_copyout(
        &mut self,
        occurrence_key: String,
        after_fault: Option<crate::hos2_device::AfterCopyoutFault>,
    ) -> Result<serde_json::Value, crate::AgentdError> {
        if self.device.is_history_only() {
            return Err(crate::AgentdError::Protocol(
                "history-only owner cannot dispatch CPU work".into(),
            ));
        }
        let fail = |e: String| crate::AgentdError::Protocol(e);
        let _mutation = self.ingress.begin_mutation().await?;
        self.host.writer().verify_current_authority().await?;
        let queued = self
            .queue
            .as_ref()
            .filter(|value| value.occurrence_key == occurrence_key)
            .ok_or_else(|| {
                fail(
                    "copyout dispatch must reference the retained original queued operation".into(),
                )
            })?
            .clone();
        let request = codex_hepta_memory::Hos2InstallBudgetV1::from_json(&queued.payload_json)
            .map_err(fail)?;
        let before = usage(&self.device)?;
        let initial = self.device.native_copyout_snapshot().map_err(fail)?;
        if initial.armed
            || initial.install_ioctl_count != 0
            || initial.selected_ioctl_count != 0
            || initial.efault_count != 0
            || initial.last.is_some()
        {
            return Err(fail(
                "copyout acceptance selects exactly the first original Install once".into(),
            ));
        }
        let requires_exit = after_fault.is_some();
        self.device
            .arm_native_copyout_fault(&request, after_fault)
            .map_err(fail)?;
        let receipt = self.host.dispatch_with_grant_provider(queued).await?;
        if requires_exit {
            return Err(fail(
                "Manager survived its bounded real-copyout crash boundary".into(),
            ));
        }
        let snapshot = self.device.native_copyout_snapshot().map_err(fail)?;
        let diagnostic = snapshot
            .last
            .as_ref()
            .ok_or_else(|| fail("actual selected ioctl diagnostic absent".into()))?;
        if snapshot.armed
            || snapshot.install_ioctl_count != 1
            || snapshot.selected_ioctl_count != 1
            || snapshot.efault_count != 1
            || diagnostic.syscall_return != -1
            || diagnostic.errno != Some(libc::EFAULT)
            || diagnostic.request_bytes != 96
            || diagnostic.response_capacity != 128
            || receipt.state != codex_hepta_memory::LocalOutcomeState::Indeterminate
            || receipt.target_disposition
                != codex_hepta_memory::ProductionTargetDisposition::Indeterminate
            || receipt.target_receipt.is_some()
            || receipt.external_effect
            || receipt.request.occurrence_key != occurrence_key
            || receipt.request.payload_json != request.to_json().map_err(fail)?
        {
            return Err(fail(
                "actual copyout did not preserve the original Indeterminate dispatch receipt"
                    .into(),
            ));
        }
        self.sender
            .acknowledge_owner_cut()
            .await
            .map_err(|e| fail(e.to_string()))?;
        self.queue.take();
        Ok(
            serde_json::json!({"pid":std::process::id(),"receipt":receipt,"before":before,
            "after":usage(&self.device)?,"copyout":snapshot}),
        )
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ReleaseAck {
    pub(super) schema_version: u32,
    pub(super) operation: String,
    pub(super) receipt_sha256: codex_hepta_contracts::Sha256Digest,
    pub(super) current: codex_hepta_memory::CognitiveCheckpointReceipt,
}

pub(super) fn finish_release(
    mut rpc: Rpc,
    receipt: codex_hepta_memory::ProductionLeaseReceipt,
) -> io::Result<()> {
    if receipt.state != "released" || receipt.external_effect {
        return Err(invalid(
            "original native writer did not return a complete release",
        ));
    }
    let expected = codex_hepta_contracts::Sha256Digest::for_bytes(
        &serde_json::to_vec(&receipt).map_err(error)?,
    );
    rpc.send(&receipt)?;
    let ack: ReleaseAck = rpc.read()?;
    if ack.schema_version != 1
        || ack.operation != "runtime.native-cpu.release-observed.v1"
        || ack.receipt_sha256 != expected
        || ack.current.head.phase != codex_hepta_memory::CognitiveCheckpointPhase::Current
        || ack.current.head.owner_agent_id != receipt.owner_agent_id
        || ack.current.head.writer_binding.lease_id != receipt.lease_id
        || ack.current.head.writer_binding.generation != receipt.generation
        || ack.current.head.writer_binding.authority_epoch != receipt.authority_epoch
        || ack.current.head.writer_binding.owner_epoch != receipt.owner_epoch
        || ack.current.head.writer_binding.authority_grant_digest != receipt.authority_grant_digest
    {
        return Err(invalid(
            "Root did not acknowledge this actual original release and Current",
        ));
    }
    Ok(())
}

//! Explicitly selected cross-repository qualification, never default startup.

use super::*;
use crate::AgentdNotesChannel;
use codex_hepta_memory::NotesPrivateChannel;
use pretty_assertions::assert_eq;
use std::io::BufRead;
use std::io::BufReader;
use std::os::fd::OwnedFd;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;

#[derive(Default)]
struct NotesReplyLossProbe {
    lose_next_reply: AtomicBool,
    effect_attempts: AtomicUsize,
    complete_fault_writes: AtomicUsize,
    observed_applied: Mutex<Option<Vec<u8>>>,
    retirement_response: Mutex<Option<Vec<u8>>>,
}

/// Test-only wrapper around the real application descriptors. Normal traffic
/// uses the original channel unchanged. Fault injection writes the complete
/// original frame, reads no effect receipt, closes the stream, and reports an
/// ambiguous result. Recovery always delegates to the real independent lane.
struct NotesLocalChannel {
    original: AgentdNotesChannel,
    fault_effect: Mutex<UnixStream>,
    probe: Arc<NotesReplyLossProbe>,
}

impl NotesLocalChannel {
    fn new(
        effect: UnixStream,
        recovery: UnixDatagram,
        probe: Arc<NotesReplyLossProbe>,
    ) -> std::io::Result<Self> {
        let original = AgentdNotesChannel::from_private_channels(effect.try_clone()?, recovery)?;
        Ok(Self {
            original,
            fault_effect: Mutex::new(effect),
            probe,
        })
    }
}

impl NotesPrivateChannel for NotesLocalChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        self.probe.effect_attempts.fetch_add(1, Ordering::SeqCst);
        if !self.probe.lose_next_reply.swap(false, Ordering::SeqCst) {
            return self.original.exchange(request);
        }
        let write = (|| -> std::io::Result<()> {
            let mut stream = self
                .fault_effect
                .lock()
                .map_err(|_| std::io::Error::other("fixture effect lock"))?;
            stream.set_write_timeout(Some(Duration::from_secs(2)))?;
            stream.write_all(&(request.len() as u32).to_be_bytes())?;
            stream.write_all(request)?;
            self.probe
                .complete_fault_writes
                .fetch_add(1, Ordering::SeqCst);
            Ok(())
        })();
        // shutdown affects the duplicated endpoint as well. No fixture code
        // reads, supplies, or constructs an application receipt on this path.
        self.original.invalidate();
        write.map_err(|error| error.to_string())?;
        Err(
            "explicit test fault: complete effect frame written; reply unread; stream closed"
                .to_string(),
        )
    }

    fn invalidate(&self) {
        self.original.invalidate();
    }

    fn recovery_handle(&self) -> Result<Arc<dyn codex_hepta_memory::NotesRecoveryChannel>, String> {
        self.original.recovery_handle()
    }

    fn recovery_exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        let response = self.original.recovery_exchange(request)?;
        // Retain only bounded copies of actual recovery traffic for assertions;
        // the original writer receives these exact bytes from the application.
        let query: serde_json::Value =
            serde_json::from_slice(request).map_err(|error| error.to_string())?;
        let reply: serde_json::Value =
            serde_json::from_slice(&response).map_err(|error| error.to_string())?;
        if query["action"] == "observe" && reply["result"]["status"] == "applied" {
            *self
                .probe
                .observed_applied
                .lock()
                .map_err(|error| error.to_string())? = Some(response.clone());
        } else if query["action"] == "acknowledge_terminal" {
            *self
                .probe
                .retirement_response
                .lock()
                .map_err(|error| error.to_string())? = Some(response.clone());
        }
        Ok(response)
    }
}

struct OwnedSession {
    child: Child,
    socket: PathBuf,
    instance: Option<String>,
}

impl OwnedSession {
    fn wait_for_notes_layout(&self, identity: &NotesTargetIdentity) -> Result<u64, Box<dyn Error>> {
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            let exchange_deadline = deadline.min(Instant::now() + Duration::from_secs(2));
            let remaining = || {
                exchange_deadline
                    .checked_duration_since(Instant::now())
                    .filter(|left| !left.is_zero())
                    .ok_or_else(|| {
                        std::io::Error::new(
                            std::io::ErrorKind::TimedOut,
                            "owned-Session readiness deadline",
                        )
                    })
            };
            remaining()?;
            let mut channel = UnixStream::connect(&self.socket)?;
            channel.set_write_timeout(Some(remaining()?))?;
            channel.write_all(b"{\"type\":\"snapshot\"}\n")?;
            let mut response = Vec::new();
            loop {
                channel.set_read_timeout(Some(remaining()?))?;
                let mut bytes = [0_u8; 4_096];
                let count = match channel.read(&mut bytes) {
                    Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                    result => result?,
                };
                if count == 0 || response.len() + count > 65_536 {
                    return Err("invalid owned-Session readiness response".into());
                }
                response.extend_from_slice(&bytes[..count]);
                if response.ends_with(b"\n") {
                    break;
                }
            }
            remaining()?;
            let snapshot: serde_json::Value = serde_json::from_slice(&response)?;
            if snapshot["type"] != "snapshot"
                || snapshot["session_instance"].as_str() != Some(identity.session_instance.as_str())
            {
                return Err("owned-Session readiness identity mismatch".into());
            }
            let tasks = snapshot["tasks"]
                .as_array()
                .ok_or("owned-Session readiness lacks task inventory")?;
            if tasks.len() != 1 {
                return Err("owned-Session readiness requires only its initial Notes task".into());
            }
            let task = &tasks[0];
            let destination = &task["notes_destination"];
            if identity.task_id != 1
                || task["id"].as_u64() != Some(identity.task_id)
                || task["app"] != "notes"
                || task["workspace"] != "build"
                || task["state"] != "running"
                || destination["incarnation"].as_str() != Some(identity.incarnation.as_str())
                || destination["original_owner_registered"].as_bool() != Some(true)
            {
                return Err("owned-Session readiness target or bootstrap ACK mismatch".into());
            }
            if let Some(first_frame) = task["ui_first_frame_unix_ms"].as_u64()
                && destination["channel"] == "app_layout_observed"
            {
                return Ok(first_frame);
            }
            let left = deadline
                .checked_duration_since(Instant::now())
                .filter(|left| !left.is_zero())
                .ok_or("owned Notes layout timed out")?;
            std::thread::sleep(Duration::from_millis(50).min(left));
        }
    }

    fn cancel_notes(&self) -> Result<(), Box<dyn Error>> {
        let instance = self
            .instance
            .as_ref()
            .ok_or("Session identity not accepted")?;
        let mut channel = UnixStream::connect(&self.socket)?;
        channel.set_read_timeout(Some(Duration::from_secs(2)))?;
        channel.set_write_timeout(Some(Duration::from_secs(2)))?;
        let request = serde_json::to_vec(
            &serde_json::json!({"type":"cancel","id":1,"expected_instance":instance}),
        )?;
        channel.write_all(&request)?;
        channel.write_all(b"\n")?;
        let mut response = Vec::new();
        BufReader::new(channel)
            .take(65_537)
            .read_until(b'\n', &mut response)?;
        if response.len() > 65_536 || !response.ends_with(b"\n") {
            return Err("invalid owned-Session cleanup response".into());
        }
        let response: serde_json::Value = serde_json::from_slice(&response)?;
        if response["type"] == "error" {
            return Err("owned Session refused Notes cleanup".into());
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        let children = format!(
            "/proc/{}/task/{}/children",
            self.child.id(),
            self.child.id()
        );
        loop {
            if fs::read_to_string(&children)?.trim().is_empty() {
                return Ok(());
            }
            if Instant::now() >= deadline {
                return Err("Session did not reap its Notes child".into());
            }
            std::thread::sleep(Duration::from_millis(25));
        }
    }
}

impl Drop for OwnedSession {
    fn drop(&mut self) {
        let _ = self.cancel_notes();
        // This child was created in its own process group and has not been
        // reaped, so the group id remains tied to this test-owned Session.
        // The fallback also stops its own App if an assertion failed before
        // normal public-IPC cleanup. It cannot reach the enclosing Xvfb/host.
        if let Ok(group) = libc::pid_t::try_from(self.child.id()) {
            // SAFETY: signal targets only the freshly created retained child
            // group; no ambient pid or externally supplied group is accepted.
            unsafe {
                libc::kill(-group, libc::SIGKILL);
            }
        }
        let _ = self.child.wait();
    }
}

#[tokio::test]
#[ignore = "requires an explicitly isolated Xvfb and pinned companion Session/App binaries"]
async fn notes_actual_ui_original_owner_roundtrip() -> Result<(), Box<dyn Error>> {
    if std::env::var("TRILL_NOTES_PROBE_ISOLATED").as_deref() != Ok("1")
        || std::env::var_os("DISPLAY").is_none()
    {
        return Err(
            "qualification requires an owned isolated Xvfb and TRILL_NOTES_PROBE_ISOLATED=1".into(),
        );
    }
    let selected = PathBuf::from(
        std::env::var_os("HEPTA_NOTES_SESSION_BIN")
            .ok_or("HEPTA_NOTES_SESSION_BIN must name the pinned companion binary")?,
    );
    if !selected.is_absolute() {
        return Err("Session binary path must be absolute".into());
    }
    let session_binary = selected.canonicalize()?;
    let app_binary = session_binary.with_file_name("trill-app-window");
    if !session_binary.is_file() || !app_binary.is_file() {
        return Err("both companion binaries must exist in the selected build directory".into());
    }
    let session_sha256 = Sha256Digest::for_bytes(&fs::read(&session_binary)?);
    let app_sha256 = Sha256Digest::for_bytes(&fs::read(&app_binary)?);
    let NotesHostFixture {
        directory,
        config,
        host,
        operations,
        issuer,
        final_use,
        primary_device,
    } = notes_host_fixture().await?;
    let runtime = directory.path().join("ui-runtime");
    fs::create_dir(&runtime)?;
    fs::set_permissions(&runtime, fs::Permissions::from_mode(0o700))?;
    let (parent, child_channel) = UnixDatagram::pair()?;
    let inherited: OwnedFd = child_channel.into();
    let logs = fs::File::create(directory.path().join("session.log"))?;
    let mut command = Command::new(&session_binary);
    command
        .arg("--notes-bootstrap-stdin")
        .stdin(Stdio::from(inherited))
        .stdout(Stdio::from(logs.try_clone()?))
        .stderr(Stdio::from(logs))
        .env("XDG_RUNTIME_DIR", &runtime)
        .env("XDG_STATE_HOME", directory.path().join("notes-state"))
        .env_remove("WAYLAND_DISPLAY")
        .process_group(0);
    for (key, _) in std::env::vars_os() {
        if key.to_string_lossy().starts_with("TRILL_HEPTA_") {
            command.env_remove(key);
        }
    }
    let mut session = OwnedSession {
        child: command.spawn()?,
        socket: runtime.join("trillionnium-ui/session.sock"),
        instance: None,
    };
    let reply_loss = Arc::new(NotesReplyLossProbe::default());
    let channel_probe = reply_loss.clone();
    let (operations, identity) = operations
        .with_notes_from_session_test_channel(
            &config,
            &host,
            parent,
            final_use,
            move |effect, recovery| {
                Ok(
                    Arc::new(NotesLocalChannel::new(effect, recovery, channel_probe)?)
                        as Arc<dyn NotesPrivateChannel>,
                )
            },
        )
        .await?;
    session.instance = Some(identity.session_instance.clone());
    let (host, _) = operations.attach(Arc::new(host)).await?;
    // Private attachment precedes the App's first event-loop iteration. Wait
    // for that same live target's layout before starting the unchanged bounded
    // effect exchange; readiness itself neither grants nor dispatches anything.
    let first_frame_unix_ms = session.wait_for_notes_layout(&identity)?;
    let text = "Hepta original writer -> live Notes / 中文";
    let payload = serde_json::to_string(&serde_json::json!({
        "schema_version":1,"action":"replace_note","operation_id":"notes-real-ui-fixture",
        "destination_id":identity.destination_id(),"target":identity,"expected_revision":0,"text":text
    }))?;
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(config.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = host
        .writer()
        .prepare_operation(intent, NOTES_REPLACE_TOPIC_V1, payload.clone())
        .await?;
    let binding = host
        .writer()
        .final_use_binding(&queued, &identity.destination_id())
        .await?;
    // The injected test provider's refusal must happen before target entry.
    // The later real application's previous_revision=0 confirms no earlier
    // model mutation was smuggled through that refused attempt.
    issuer.enabled.store(false, Ordering::SeqCst);
    assert!(
        host.dispatch_to_with_grant_provider(&identity.destination_id(), queued.clone())
            .await
            .is_err()
    );
    assert_eq!(
        host.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Queued
    );
    issuer.enabled.store(true, Ordering::SeqCst);
    let receipt = host
        .dispatch_to_with_grant_provider(&identity.destination_id(), queued.clone())
        .await?;
    assert_eq!(receipt.state, LocalOutcomeState::Committed);
    assert_eq!(receipt.request.payload_json, payload);
    assert_eq!(
        host.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        *issuer.binding.lock().map_err(|error| error.to_string())?,
        Some(binding)
    );
    let application: serde_json::Value = serde_json::from_str(
        receipt
            .target_receipt
            .as_ref()
            .ok_or("missing actual application receipt")?,
    )?;
    assert_eq!(
        application,
        serde_json::json!({
            "schema_version":1,"target":identity,"operation_id":"notes-real-ui-fixture",
            "payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
            "result":{"status":"applied","previous_revision":0,"revision":1,
                "text_sha256":Sha256Digest::for_bytes(text.as_bytes()).as_str()}
        })
    );
    // A second actual edit proves the original writer's durable receipt ACK
    // released the first pending slot. No app-side receipt is overwritten.
    let second_text = "Hepta durable receipt retired -> second live Notes revision / 中文";
    let second_payload = serde_json::to_string(&serde_json::json!({
        "schema_version":1,"action":"replace_note","operation_id":"notes-real-ui-fixture-second",
        "destination_id":identity.destination_id(),"target":identity,"expected_revision":1,"text":second_text
    }))?;
    let second_intent = notes_operation_intent(
        &identity,
        &second_payload,
        StableId::new(config.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )?;
    let second_queued = host
        .writer()
        .prepare_operation(
            second_intent,
            NOTES_REPLACE_TOPIC_V1,
            second_payload.clone(),
        )
        .await?;
    let second_receipt = host
        .dispatch_to_with_grant_provider(&identity.destination_id(), second_queued.clone())
        .await?;
    assert_eq!(second_receipt.state, LocalOutcomeState::Committed);
    let second_application: serde_json::Value = serde_json::from_str(
        second_receipt
            .target_receipt
            .as_ref()
            .ok_or("missing second actual app receipt")?,
    )?;
    assert_eq!(
        second_application,
        serde_json::json!({
            "schema_version":1,"target":identity,"operation_id":"notes-real-ui-fixture-second",
            "payload_sha256":Sha256Digest::for_bytes(second_payload.as_bytes()).as_str(),
            "result":{"status":"applied","previous_revision":1,"revision":2,
                "text_sha256":Sha256Digest::for_bytes(second_text.as_bytes()).as_str()}
        })
    );
    assert_eq!(
        host.writer().status(&second_queued.occurrence_key).await?,
        LocalOutcomeState::Committed
    );
    // The third edit uses the same original writer, grant provider, FinalUse
    // authority and live document. Lose the complete effect reply, then recover
    // only through the separate real application observation channel.
    let third_text = "Hepta real lost reply -> original durable recovery / 中文";
    let third_payload = serde_json::to_string(&serde_json::json!({
        "schema_version":1,"action":"replace_note","operation_id":"notes-real-ui-fixture-lost-reply",
        "destination_id":identity.destination_id(),"target":identity,"expected_revision":2,"text":third_text
    }))?;
    let third_intent = notes_operation_intent(
        &identity,
        &third_payload,
        StableId::new(config.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )?;
    let third_queued = host
        .writer()
        .prepare_operation(third_intent, NOTES_REPLACE_TOPIC_V1, third_payload.clone())
        .await?;
    reply_loss.lose_next_reply.store(true, Ordering::SeqCst);
    let lost_reply = host
        .dispatch_to_with_grant_provider(&identity.destination_id(), third_queued.clone())
        .await?;
    assert_eq!(lost_reply.state, LocalOutcomeState::Indeterminate);
    assert!(lost_reply.target_receipt.is_none());
    assert_eq!(
        host.writer().status(&third_queued.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(reply_loss.effect_attempts.load(Ordering::SeqCst), 3);
    assert_eq!(reply_loss.complete_fault_writes.load(Ordering::SeqCst), 1);
    let grants_before_reconciliation = issuer.requests.load(Ordering::SeqCst);
    assert_eq!(grants_before_reconciliation, 4);
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        host.reconcile(/*limit*/ 8).await?;
        let state = host.writer().status(&third_queued.occurrence_key).await?;
        let retired = reply_loss
            .retirement_response
            .lock()
            .map_err(|error| error.to_string())?
            .clone();
        let retired = retired
            .as_deref()
            .map(serde_json::from_slice::<serde_json::Value>)
            .transpose()?;
        if state == LocalOutcomeState::Committed
            && retired.as_ref().is_some_and(|reply| {
                reply["operation_id"] == third_queued.occurrence_key
                    && matches!(
                        reply["status"].as_str(),
                        Some("released" | "already_released")
                    )
            })
        {
            break;
        }
        if Instant::now() >= deadline {
            return Err("real application lost-reply recovery or durable ACK timed out".into());
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    assert_eq!(
        reply_loss.effect_attempts.load(Ordering::SeqCst),
        3,
        "recovery cannot replay an effect"
    );
    assert_eq!(
        issuer.requests.load(Ordering::SeqCst),
        grants_before_reconciliation,
        "recovery cannot request another grant"
    );
    let recovered_bytes = reply_loss
        .observed_applied
        .lock()
        .map_err(|error| error.to_string())?
        .clone()
        .ok_or("missing actual application recovery receipt")?;
    let recovered_application: serde_json::Value = serde_json::from_slice(&recovered_bytes)?;
    assert_eq!(
        recovered_application,
        serde_json::json!({
            "schema_version":1,"target":identity,"operation_id":"notes-real-ui-fixture-lost-reply",
            "payload_sha256":Sha256Digest::for_bytes(third_payload.as_bytes()).as_str(),
            "result":{"status":"applied","previous_revision":2,"revision":3,
                "text_sha256":Sha256Digest::for_bytes(third_text.as_bytes()).as_str()}
        })
    );
    let retired_bytes = reply_loss
        .retirement_response
        .lock()
        .map_err(|error| error.to_string())?
        .clone()
        .ok_or("missing actual retirement response")?;
    let recovered_retirement: serde_json::Value = serde_json::from_slice(&retired_bytes)?;
    assert_eq!(
        recovered_retirement["target"],
        serde_json::to_value(&identity)?
    );
    assert_eq!(
        recovered_retirement["operation_id"],
        third_queued.occurrence_key
    );
    assert_eq!(
        recovered_retirement["payload_sha256"],
        Sha256Digest::for_bytes(third_payload.as_bytes()).as_str()
    );
    assert_eq!(
        recovered_retirement["receipt_sha256"],
        Sha256Digest::for_bytes(&recovered_bytes).as_str()
    );
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    let evidence = serde_json::json!({
        "schema_version":1,"profile":"test-issuer-original-owner-real-session-notes",
        "production_authority":false,"native_kernel_qualified":false,"pixels_qualified":false,
        "session_sha256":session_sha256.as_str(),"app_sha256":app_sha256.as_str(),
        "ui_first_frame_unix_ms":first_frame_unix_ms,
        "source_state":receipt.state,"application_receipt":application,
        "second_application_receipt":second_application,"receipt_capacity_reused_after_durable_ack":true,
        "bootstrap_schema_version":2,"recovery_transport":"private_unix_datagram",
        "lost_reply_initial_source_state":lost_reply.state,
        "lost_reply_recovered_source_state":host.writer().status(&third_queued.occurrence_key).await?,
        "recovered_application_receipt":recovered_application,
        "recovered_application_receipt_utf8":std::str::from_utf8(&recovered_bytes)?,
        "recovered_retirement_response":recovered_retirement,
        "recovered_receipt_sha256":Sha256Digest::for_bytes(&recovered_bytes).as_str(),
        "complete_frame_written_then_effect_stream_closed":true,
        "effect_reply_read_by_fault_fixture":false,"effect_dispatch_attempts":3,
        "injected_complete_frame_writes":reply_loss.complete_fault_writes.load(Ordering::SeqCst),
        "recovery_effect_replay":false,"recovery_requested_new_grant":false,
        "issuer_requests":issuer.requests.load(Ordering::SeqCst),
        "source_recovery_anchor":host.writer().recovery_anchor().await?
    });
    if let Some(path) = std::env::var_os("HEPTA_NOTES_QUALIFICATION_OUTPUT") {
        fs::write(path, serde_json::to_vec_pretty(&evidence)?)?;
    }
    eprintln!("HEPTA_NOTES_ACTUAL_UI_QUALIFICATION={evidence}");
    session.cancel_notes()?;
    Ok(())
}

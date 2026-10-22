//! Explicitly selected cross-repository qualification, never default startup.

use super::*;
use pretty_assertions::assert_eq;
use std::io::BufRead;
use std::io::BufReader;
use std::os::fd::OwnedFd;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;

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
    let (operations, identity) = operations
        .with_notes_from_session(&config, &host, parent, final_use)
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
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    let evidence = serde_json::json!({
        "schema_version":1,"profile":"test-issuer-original-owner-real-session-notes",
        "production_authority":false,"native_kernel_qualified":false,"pixels_qualified":false,
        "session_sha256":session_sha256.as_str(),"app_sha256":app_sha256.as_str(),
        "ui_first_frame_unix_ms":first_frame_unix_ms,
        "source_state":receipt.state,"application_receipt":application,
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

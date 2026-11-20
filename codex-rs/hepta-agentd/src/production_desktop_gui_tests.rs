//! Actual isolated Xvfb, stock application, Session, original writer and FinalUse.
//! The explicit test issuer and source cut remain qualification inputs.
use super::*;
use codex_hepta_memory::DesktopCapture;
use codex_hepta_memory::DesktopPrivateChannel;
use pretty_assertions::assert_eq;
use std::io::BufRead;
use std::io::BufReader;
use std::os::fd::OwnedFd;
use std::os::unix::process::CommandExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;

struct Owned(Child);
impl Drop for Owned {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_some() {
            return;
        }
        // Each child below creates its own process group, never the user's desktop.
        unsafe {
            libc::kill(-(self.0.id() as i32), libc::SIGKILL);
        }
        let _ = self.0.wait();
    }
}
struct QualificationLogs {
    root: std::path::PathBuf,
    destination: std::path::PathBuf,
}
impl Drop for QualificationLogs {
    fn drop(&mut self) {
        let _ = fs::create_dir_all(&self.destination);
        for name in [
            "xvfb.log",
            "xmessage.log",
            "session.log",
            "session-stderr.log",
        ] {
            let _ = fs::copy(self.root.join(name), self.destination.join(name));
        }
    }
}
struct ReplyLoss {
    inner: crate::desktop_channel::AgentdDesktopEffectChannel,
    entries: AtomicUsize,
}
impl DesktopPrivateChannel for ReplyLoss {
    fn exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, String> {
        self.entries.fetch_add(1, Ordering::SeqCst);
        let _actual_reply = self.inner.exchange(bytes)?;
        // Qualification fault after the real reply reaches this wrapper but
        // before the original owner receives it. Recovery uses the separate FD.
        self.inner.invalidate();
        Err("qualification: actual effect response withheld from owner".into())
    }
    fn invalidate(&self) {
        self.inner.invalidate();
    }
}

#[tokio::test]
#[ignore = "requires explicitly pinned Session, Xvfb, xmessage and xdotool"]
async fn desktop_actual_x11_original_owner_refusal_injection_observation_and_application_exit()
-> Result<(), Box<dyn Error>> {
    let session_bin = std::env::var("HEPTA_DESKTOP_SESSION_BIN")?;
    let output = std::path::PathBuf::from(std::env::var("HEPTA_DESKTOP_QUALIFICATION_OUTPUT")?);
    let NotesHostFixture {
        directory,
        config,
        host,
        issuer,
        final_use,
        ..
    } = notes_host_fixture().await?;
    let root = directory.path();
    let _logs = QualificationLogs {
        root: root.to_path_buf(),
        destination: output.with_extension("artifacts"),
    };
    let mut server = Owned(
        Command::new("Xvfb")
            .args([
                "-displayfd",
                "1",
                "-screen",
                "0",
                "1280x900x24",
                "-nolisten",
                "tcp",
                "-ac",
            ])
            .stdout(Stdio::piped())
            .stderr(fs::File::create(root.join("xvfb.log"))?)
            .process_group(0)
            .spawn()?,
    );
    let server_stdout = server.0.stdout.take().ok_or("Xvfb stdout")?;
    let mut poll = libc::pollfd {
        fd: server_stdout.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    // SAFETY: poll borrows one live initialized descriptor for a bounded wait.
    if unsafe { libc::poll(&mut poll, 1, 5000) } != 1 {
        return Err("Xvfb readiness timeout".into());
    }
    let mut number = String::new();
    BufReader::new(server_stdout).read_line(&mut number)?;
    let number: u32 = number.trim().parse()?;
    let display = format!(":{number}");
    let mut app = Owned(
        Command::new("xmessage")
            .args([
                "-name",
                "HeptaOriginalDesktopOwner",
                "-buttons",
                "Done:7",
                "-default",
                "Done",
                "Original owner authorized input",
            ])
            .env("DISPLAY", &display)
            .env_remove("WAYLAND_DISPLAY")
            .stdout(Stdio::null())
            .stderr(fs::File::create(root.join("xmessage.log"))?)
            .process_group(0)
            .spawn()?,
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    let window = loop {
        let result = Command::new("xdotool")
            .args([
                "search",
                "--onlyvisible",
                "--name",
                "^HeptaOriginalDesktopOwner$",
            ])
            .env("DISPLAY", &display)
            .output()?;
        if result.status.success() {
            let first = std::str::from_utf8(&result.stdout)?
                .lines()
                .next()
                .ok_or("window id")?;
            break first.parse::<u32>()?;
        }
        if Instant::now() >= deadline {
            return Err("stock application window missing".into());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    };
    if !Command::new("xdotool")
        .args(["windowfocus", "--sync", &window.to_string()])
        .env("DISPLAY", &display)
        .status()?
        .success()
    {
        return Err("owned application focus".into());
    }
    let runtime = root.join("desktop-runtime");
    fs::create_dir(&runtime)?;
    fs::set_permissions(&runtime, fs::Permissions::from_mode(0o700))?;
    let (bootstrap, child_bootstrap) = UnixDatagram::pair()?;
    let x11 = UnixStream::connect(format!("/tmp/.X11-unix/X{number}"))?;
    let x11fd = x11.as_raw_fd();
    let mut command = Command::new(&session_bin);
    command
        .args([
            "--desktop-bootstrap-stdin",
            "--desktop-x11-fd",
            &x11fd.to_string(),
            "--desktop-x11-server-pid",
            &server.0.id().to_string(),
            "--desktop-window",
            &window.to_string(),
        ])
        .env("XDG_RUNTIME_DIR", &runtime)
        .env_remove("DISPLAY")
        .env_remove("WAYLAND_DISPLAY")
        .stdin(Stdio::from(OwnedFd::from(child_bootstrap)))
        .stdout(fs::File::create(root.join("session.log"))?)
        .stderr(fs::File::create(root.join("session-stderr.log"))?)
        .process_group(0);
    // SAFETY: after fork only fcntl runs; x11fd is retained through spawn. The
    // descriptor is inherited only by this owned trusted Session bootstrap.
    unsafe {
        command.pre_exec(move || {
            if libc::fcntl(x11fd, libc::F_SETFD, 0) < 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let _session = Owned(command.spawn()?);
    drop(x11);
    let mut probe = None;
    let (target, offer) =
        crate::desktop_bootstrap::receive_desktop_session_with_channel(bootstrap, |inner| {
            let value = Arc::new(ReplyLoss {
                inner,
                entries: AtomicUsize::new(0),
            });
            probe = Some(value.clone());
            value
        })
        .map_err(|error| format!("actual Session descriptor bootstrap: {error}"))?;
    let observer = target.observation_channel();
    let host = host.attach_target(final_use, Arc::new(target), issuer.clone())?;
    let capture = serde_json::to_vec(
        &serde_json::json!({"schema_version":1,"action":"capture","target":offer.target,"request_id":"4".repeat(32)}),
    )?;
    let screenshot = DesktopCapture::parse_exact(
        &codex_hepta_memory::DesktopObservationChannel::exchange(observer.as_ref(), &capture)?,
    )?;
    assert_eq!(screenshot.window_id, window);
    assert_eq!(screenshot.input_sequence, 0);
    issuer.invalid_first_signature.store(true, Ordering::SeqCst);
    for (id, refused) in [
        ("desktop-signature-refused", true),
        ("desktop-original-return", false),
    ] {
        let payload = serde_json::to_string(
            &serde_json::json!({"schema_version":1,"action":"input","operation_id":id,"destination_id":offer.destination_id,"target":offer.target,"expected_sequence":0,"expected_window":window,"events":[{"kind":"key","keycode":36,"pressed":true},{"kind":"key","keycode":36,"pressed":false}]}),
        )?;
        let intent = desktop_operation_intent(
            &offer.target,
            &payload,
            StableId::new(config.identity().agent_id.as_str())?,
            Generation::new(1)?,
        )?;
        let queued = host
            .writer()
            .prepare_operation(intent, DESKTOP_INPUT_TOPIC_V1, payload.clone())
            .await?;
        let receipt = host.dispatch_with_grant_provider(queued).await;
        if refused {
            assert!(matches!(
                receipt,
                Err(crate::AgentdError::ProductionWriter(
                    codex_hepta_memory::ProductionWriterError::FinalUse(
                        codex_hepta_contracts::FinalUseError::InvalidSignature
                    )
                ))
            ));
            assert_eq!(probe.as_ref().unwrap().entries.load(Ordering::SeqCst), 0);
            assert!(app.0.try_wait()?.is_none());
        } else {
            let receipt = receipt?;
            assert_eq!(receipt.state, LocalOutcomeState::Indeterminate);
            assert_eq!(probe.as_ref().unwrap().entries.load(Ordering::SeqCst), 1);
            // The separate invalid-signature operation is also nonterminal;
            // query both retained operations without granting either a retry.
            host.reconcile(2).await?;
            assert_eq!(
                host.writer().status(id).await?,
                LocalOutcomeState::Committed
            );
            let query = serde_json::to_vec(
                &serde_json::json!({"schema_version":1,"action":"observe","target":offer.target,"operation_id":id,"payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str()}),
            )?;
            let response = observer.exchange(&query)?;
            let response: serde_json::Value = serde_json::from_slice(&response)?;
            assert_eq!(
                response["result"]["effect_semantics"],
                "x11_server_injected"
            );
        }
    }
    let until = Instant::now() + Duration::from_secs(5);
    let app_exit = loop {
        if let Some(status) = app.0.try_wait()? {
            break status.code();
        }
        if Instant::now() > until {
            return Err("stock xmessage did not independently exit".into());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    };
    assert_eq!(app_exit, Some(7));
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 2);
    drop(observer);
    host.close().await?;
    fs::write(
        output,
        serde_json::to_vec_pretty(
            &serde_json::json!({"schema_version":1,"result":"passed","production_authority":false,"issuer":"explicit qualification fixture","source_current_cut":"fixture captured; not production independent cut","actual_xvfb":true,"actual_session":true,"actual_stock_xmessage":true,"source_sqlite_terminal":"committed","receipt_semantics":"x11_server_injected","independent_application_exit":7,"invalid_signature_effect_entries":0,"authorized_effect_entries":1,"lost_reply":"test wrapper withheld actual native reply from original owner","recovery":"independent observation FD; no replay or new grant","session_sha256":Sha256Digest::for_bytes(&fs::read(&session_bin)?).as_str(),"capture":{"width":screenshot.width,"height":screenshot.height,"sha256":screenshot.sha256}}),
        )?,
    )?;
    Ok(())
}

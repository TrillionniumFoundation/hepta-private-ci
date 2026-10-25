//! Real companion process failure with the original reopened SQLite owner.
//! Only authority and deliberate reply loss are fixtures; every application
//! receipt/retirement response comes from the actual independent helper.
use super::*;
use crate::AgentdNotesPreviousRecoveryLaunch;
use crate::notes_recovery_process::ProcessRecoveryChannel;
use codex_hepta_memory::NotesRecoveryChannel;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;
use std::path::Path;

struct LoseFirstRetirementReply {
    original: Arc<ProcessRecoveryChannel>,
    dropped: AtomicBool,
    observed: Mutex<Option<Vec<u8>>>,
    acknowledgements: Mutex<Vec<Vec<u8>>>,
}

impl NotesRecoveryChannel for LoseFirstRetirementReply {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        let reply = self.original.exchange(request)?;
        let query: serde_json::Value =
            serde_json::from_slice(request).map_err(|e| e.to_string())?;
        if query["action"] == "observe" {
            *self.observed.lock().map_err(|e| e.to_string())? = Some(reply.clone());
        }
        if query["action"] == "acknowledge_terminal" {
            self.acknowledgements
                .lock()
                .map_err(|e| e.to_string())?
                .push(reply.clone());
            if !self.dropped.swap(true, Ordering::SeqCst) {
                // The helper already fsynced retirement and returned its real
                // reply. Lose only that reply; never synthesize application data.
                return Err("explicit fixture loses the durably persisted retirement reply".into());
            }
        }
        Ok(reply)
    }
}

fn start_durable_session(
    binary: &Path,
    root: &Path,
    state: &Path,
    name: &str,
) -> Result<(OwnedSession, UnixDatagram), Box<dyn Error>> {
    let runtime = root.join(format!("runtime-{name}"));
    fs::create_dir(&runtime)?;
    fs::set_permissions(&runtime, fs::Permissions::from_mode(0o700))?;
    let (parent, child) = UnixDatagram::pair()?;
    let log = fs::File::create(root.join(format!("{name}.log")))?;
    let mut command = Command::new(binary);
    command
        .arg("--notes-bootstrap-stdin")
        .stdin(Stdio::from(OwnedFd::from(child)))
        .stdout(Stdio::from(log.try_clone()?))
        .stderr(Stdio::from(log))
        .env("XDG_RUNTIME_DIR", &runtime)
        .env("TRILL_NOTES_STATE_DIR", state)
        .env("XDG_STATE_HOME", root.join(format!("xdg-state-{name}")))
        .env_remove("WAYLAND_DISPLAY")
        .process_group(0);
    for (key, _) in std::env::vars_os() {
        if key.to_string_lossy().starts_with("TRILL_HEPTA_")
            || key.to_string_lossy().starts_with("TRILL_UI_CHAT_")
        {
            command.env_remove(key);
        }
    }
    Ok((
        OwnedSession {
            child: command.spawn()?,
            socket: runtime.join("trillionnium-ui/session.sock"),
            instance: None,
        },
        parent,
    ))
}

fn snapshot(session: &OwnedSession) -> Result<serde_json::Value, Box<dyn Error>> {
    let mut stream = UnixStream::connect(&session.socket)?;
    stream.set_write_timeout(Some(Duration::from_secs(2)))?;
    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
    stream.write_all(b"{\"type\":\"snapshot\"}\n")?;
    let mut bytes = Vec::new();
    BufReader::new(stream)
        .take(65_537)
        .read_until(b'\n', &mut bytes)?;
    if bytes.len() > 65_536 || !bytes.ends_with(b"\n") {
        return Err("invalid original Session snapshot".into());
    }
    let value: serde_json::Value = serde_json::from_slice(&bytes)?;
    if value["type"] != "snapshot"
        || value["session_instance"].as_str() != session.instance.as_deref()
    {
        return Err("original Session snapshot identity mismatch".into());
    }
    Ok(value)
}

fn retained_app_pidfd(
    session: &OwnedSession,
    target: &NotesTargetIdentity,
) -> Result<OwnedFd, Box<dyn Error>> {
    let value = snapshot(session)?;
    let tasks = value["tasks"].as_array().ok_or("original task inventory")?;
    if tasks.len() != 1
        || tasks[0]["id"].as_u64() != Some(target.task_id)
        || tasks[0]["notes_destination"]["incarnation"] != target.incarnation
        || tasks[0]["state"] != "running"
    {
        return Err("original live Notes target mismatch".into());
    }
    let pid = i32::try_from(tasks[0]["pid"].as_u64().ok_or("original Notes pid")?)?;
    // SAFETY: pidfd_open opens a process handle and does not signal it.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if fd < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: a new nonnegative descriptor is owned by this scope.
    let fd = unsafe { OwnedFd::from_raw_fd(i32::try_from(fd)?) };
    let children = fs::read_to_string(format!("/proc/{0}/task/{0}/children", session.child.id()))?;
    if !children
        .split_whitespace()
        .any(|child| child == pid.to_string())
    {
        return Err("Notes process is not this retained Session's child".into());
    }
    Ok(fd)
}

fn kill_and_observe_reap(session: &OwnedSession, app: OwnedFd) -> Result<(), Box<dyn Error>> {
    // SAFETY: only the independently retained pidfd of this test-owned Session
    // child is signaled. No unrelated PID or ambient application is selected.
    let result = unsafe {
        libc::syscall(
            libc::SYS_pidfd_send_signal,
            app.as_raw_fd(),
            libc::SIGKILL,
            std::ptr::null::<libc::siginfo_t>(),
            0,
        )
    };
    if result != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        // Original Snapshot handling reaps the actual child. Signal delivery
        // or an absent executable alone cannot prove the incarnation lock free.
        let value = snapshot(session)?;
        if matches!(
            value["tasks"][0]["state"].as_str(),
            Some("failed" | "completed" | "cancelled")
        ) {
            let children =
                fs::read_to_string(format!("/proc/{0}/task/{0}/children", session.child.id()))?;
            if children.trim().is_empty() {
                return Ok(());
            }
        }
        if Instant::now() >= deadline {
            return Err("original Session did not reap its killed Notes child".into());
        }
        std::thread::sleep(Duration::from_millis(25));
    }
}

fn document_path(root: &Path, target: &NotesTargetIdentity) -> PathBuf {
    root.join(format!(
        "{}-{}-{}",
        target.session_instance, target.task_id, target.incarnation
    ))
    .join("document.json")
}

fn read_document(path: &Path) -> Result<serde_json::Value, Box<dyn Error>> {
    let bytes = fs::read(path)?;
    if bytes.is_empty() || bytes.len() > 16 * 1024 {
        return Err("actual document bound".into());
    }
    Ok(serde_json::from_slice(&bytes)?)
}

#[tokio::test]
#[ignore = "requires explicitly isolated Xvfb and pinned durable Session/App/recovery binaries"]
async fn notes_actual_app_crash_original_owner_reopen_and_helper_ack_restart()
-> Result<(), Box<dyn Error>> {
    if std::env::var("TRILL_NOTES_PROBE_ISOLATED").as_deref() != Ok("1")
        || std::env::var_os("DISPLAY").is_none()
    {
        return Err("requires isolated Xvfb and TRILL_NOTES_PROBE_ISOLATED=1".into());
    }
    let selected = PathBuf::from(
        std::env::var_os("HEPTA_NOTES_SESSION_BIN").ok_or("pinned Session binary required")?,
    );
    if !selected.is_absolute() {
        return Err("absolute companion path required".into());
    }
    let session_binary = selected.canonicalize()?;
    let app_binary = session_binary.with_file_name("trill-app-window");
    let helper_binary = session_binary.with_file_name("trill-notes-recovery");
    let session_sha = Sha256Digest::for_bytes(&fs::read(&session_binary)?);
    let app_sha = Sha256Digest::for_bytes(&fs::read(&app_binary)?);
    let helper_sha = Sha256Digest::for_bytes(&fs::read(&helper_binary)?);
    let NotesHostFixture {
        directory,
        config,
        host,
        operations,
        issuer,
        final_use,
        primary_device,
    } = notes_host_fixture().await?;
    let state = directory.path().join("durable-notes");
    let authority = operations.authority.clone();
    let verifier = operations.verifier.clone();
    let lease = operations.lease_id.clone();
    let generation = operations.lease_generation;
    let (mut old_session, bootstrap) =
        start_durable_session(&session_binary, directory.path(), &state, "old-session")?;
    let effect_probe = Arc::new(NotesReplyLossProbe::default());
    let probe = effect_probe.clone();
    let (operations, old) = operations
        .with_notes_from_session_test_channel(
            &config,
            &host,
            bootstrap,
            final_use.clone(),
            move |effect, recovery| {
                Ok(Arc::new(NotesLocalChannel::new(effect, recovery, probe)?)
                    as Arc<dyn NotesPrivateChannel>)
            },
        )
        .await?;
    old_session.instance = Some(old.session_instance.clone());
    let (host, _) = operations.attach(Arc::new(host)).await?;
    let old_first_frame = old_session.wait_for_notes_layout(&old)?;
    let app_pidfd = retained_app_pidfd(&old_session, &old)?;
    let operation_id = "notes-real-crash-original-owner";
    let text = "Original Hepta owner survives Notes crash / 中文";
    let payload = serde_json::to_string(
        &serde_json::json!({"schema_version":1,"action":"replace_note",
        "operation_id":operation_id,"destination_id":old.destination_id(),"target":old,
        "expected_revision":0,"text":text}),
    )?;
    let intent = notes_operation_intent(
        &old,
        &payload,
        StableId::new(config.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = host
        .writer()
        .prepare_operation(intent, NOTES_REPLACE_TOPIC_V1, payload.clone())
        .await?;
    effect_probe.lose_next_reply.store(true, Ordering::SeqCst);
    let lost = host
        .dispatch_to_with_grant_provider(&old.destination_id(), queued.clone())
        .await?;
    assert_eq!(lost.state, LocalOutcomeState::Indeterminate);
    assert!(lost.target_receipt.is_none());
    let old_document = document_path(&state, &old);
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let document = read_document(&old_document)?;
        if document["revision"] == 1 && document["pending_receipt"]["operation_id"] == operation_id
        {
            break;
        }
        if Instant::now() >= deadline {
            return Err("actual Notes checkpoint did not retain the lost effect receipt".into());
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    kill_and_observe_reap(&old_session, app_pidfd)?;
    assert_eq!(effect_probe.effect_attempts.load(Ordering::SeqCst), 1);
    assert_eq!(effect_probe.complete_fault_writes.load(Ordering::SeqCst), 1);
    let issuer_requests = issuer.requests.load(Ordering::SeqCst);
    assert_eq!(issuer_requests, 1);
    issuer.enabled.store(false, Ordering::SeqCst);

    // Close every handle to the original writer/store, then recover from its
    // independently retained exact current cut with the same fixture verifier.
    let cut = host.writer().recovery_anchor().await?;
    let runtime = host.cognitive_runtime();
    let store = runtime
        .available_store()
        .ok_or("original available store")?
        .clone();
    drop(host);
    drop(runtime);
    let store = Arc::try_unwrap(store).map_err(|_| "original read-side store is still retained")?;
    store.close().await;
    let reopened = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        authority,
        verifier,
        lease,
        generation,
    )
    .await?;
    assert_eq!(
        reopened.writer().status(operation_id).await?,
        LocalOutcomeState::Indeterminate
    );
    let (mut current_session, bootstrap) =
        start_durable_session(&session_binary, directory.path(), &state, "current-session")?;
    let (host, current, observer) = reopened
        .attach_notes_from_session_with_observer(bootstrap, final_use, issuer.clone())
        .await?;
    current_session.instance = Some(current.session_instance.clone());
    let current_first_frame = current_session.wait_for_notes_layout(&current)?;
    assert_ne!(old, current);
    let current_document = document_path(&state, &current);
    let fresh = fs::read(&current_document)?;
    assert_eq!(read_document(&current_document)?["revision"], 0);
    assert!(
        observer
            .previous_recovery_target(host.writer().as_ref())
            .await?
            .is_none(),
        "a fresh application must not invent a historical attachment"
    );

    let launch = AgentdNotesPreviousRecoveryLaunch {
        helper: helper_binary.clone(),
        helper_sha256: helper_sha.clone(),
        state_directory: state.clone(),
        previous_target: old.clone(),
        operation_id: operation_id.into(),
    };
    let process = Arc::new(ProcessRecoveryChannel::prepare(launch)?);
    let traffic = Arc::new(LoseFirstRetirementReply {
        original: process.clone(),
        dropped: AtomicBool::new(false),
        observed: Mutex::new(None),
        acknowledgements: Mutex::new(Vec::new()),
    });
    let host = host
        .attach_explicit_previous_notes_recovery(
            &current,
            old.clone(),
            operation_id,
            traffic.clone(),
        )
        .await?;
    process.start()?;
    assert_eq!(
        host.destination_count(),
        1,
        "the old target is never a dispatcher"
    );
    assert!(!host.has_destination(&old.destination_id()));
    assert!(
        process.exchange(payload.as_bytes()).is_err(),
        "recovery capability cannot execute original bytes"
    );
    assert_eq!(
        host.reconcile_for_destination(&current.destination_id(), 1)
            .await?,
        1
    );
    assert_eq!(
        host.writer().status(operation_id).await?,
        LocalOutcomeState::Committed
    );
    assert!(traffic.dropped.load(Ordering::SeqCst));
    let retired = read_document(&old_document)?;
    assert!(retired["pending_receipt"].is_null());
    assert_eq!(retired["retired_receipt"]["operation_id"], operation_id);
    assert_eq!(retired["revision"], 1);
    assert_eq!(retired["text"], text);

    process.kill_and_reap_for_test()?;
    assert_eq!(
        host.reconcile_for_destination(&current.destination_id(), 1)
            .await?,
        0
    );
    assert_eq!(process.starts_for_test(), 2);
    let observed = traffic
        .observed
        .lock()
        .map_err(|e| e.to_string())?
        .clone()
        .ok_or("actual helper receipt")?;
    let actual: serde_json::Value = serde_json::from_slice(&observed)?;
    assert_eq!(
        actual,
        serde_json::json!({"schema_version":1,"target":old,"operation_id":operation_id,
        "payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
        "result":{"status":"applied","previous_revision":0,"revision":1,"text_sha256":Sha256Digest::for_bytes(text.as_bytes()).as_str()}})
    );
    let acknowledgements = traffic
        .acknowledgements
        .lock()
        .map_err(|e| e.to_string())?
        .clone();
    assert_eq!(acknowledgements.len(), 2);
    let acks = acknowledgements
        .iter()
        .map(|raw| serde_json::from_slice::<serde_json::Value>(raw))
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(acks[0]["status"], "released");
    assert_eq!(acks[1]["status"], "already_released");
    for ack in &acks {
        assert_eq!(ack["target"], serde_json::to_value(&old)?);
        assert_eq!(ack["operation_id"], operation_id);
        assert_eq!(
            ack["payload_sha256"],
            Sha256Digest::for_bytes(payload.as_bytes()).as_str()
        );
        assert_eq!(
            ack["receipt_sha256"],
            Sha256Digest::for_bytes(&observed).as_str()
        );
    }
    assert_eq!(
        fs::read(&current_document)?,
        fresh,
        "old recovery cannot change the fresh incarnation"
    );
    assert_eq!(read_document(&old_document)?, retired);
    assert_eq!(issuer.requests.load(Ordering::SeqCst), issuer_requests);
    assert_eq!(effect_probe.effect_attempts.load(Ordering::SeqCst), 1);
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    assert!(
        host.dispatch_to_with_grant_provider(&old.destination_id(), queued)
            .await
            .is_err()
    );
    let evidence = serde_json::json!({"schema_version":1,"profile":"test-authority-original-sqlite-owner-real-notes-crash",
        "production_authority":false,"native_kernel_qualified":false,"power_loss_qualified":false,"pixels_qualified":false,
        "session_sha256":session_sha.as_str(),"app_sha256":app_sha.as_str(),"recovery_helper_sha256":helper_sha.as_str(),
        "old_target":old,"current_target":current,"operation_id":operation_id,
        "old_first_frame_unix_ms":old_first_frame,"current_first_frame_unix_ms":current_first_frame,
        "actual_app_sigkill_and_original_session_reap":true,"original_writer_closed_and_exact_cut_reopened":true,
        "effect_reply_lost":true,"original_source_before_recovery":LocalOutcomeState::Indeterminate,
        "original_source_after_recovery":host.writer().status(operation_id).await?,
        "original_application_receipt":actual,"application_receipt_utf8":std::str::from_utf8(&observed)?,
        "durable_retirement_reply_lost":true,"helper_starts":process.starts_for_test(),"retirement_responses":acks,
        "fresh_incarnation_unchanged":true,"effect_dispatches":1,"issuer_requests":issuer_requests,
        "old_dispatcher_registered":false,"source_cut_before_owner_reopen":cut,
        "source_cut_after_recovery":host.writer().recovery_anchor().await?});
    if let Some(path) = std::env::var_os("HEPTA_NOTES_CRASH_QUALIFICATION_OUTPUT") {
        let path = PathBuf::from(path);
        fs::write(&path, serde_json::to_vec_pretty(&evidence)?)?;
        fs::copy(
            directory.path().join("old-session.log"),
            path.with_extension("old-session.log"),
        )?;
        fs::copy(
            directory.path().join("current-session.log"),
            path.with_extension("current-session.log"),
        )?;
    }
    eprintln!("HEPTA_NOTES_CRASH_OWNER_QUALIFICATION={evidence}");
    drop(host);
    drop(traffic);
    drop(process);
    current_session.cancel_notes()?;
    Ok(())
}

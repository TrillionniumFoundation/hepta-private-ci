//! Cross-repository crash recovery using the original writer and real App.
use super::*;
use codex_hepta_memory::ProductionNotesTarget;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

fn fresh_nonce() -> Result<String, Box<dyn Error>> {
    let mut bytes = [0_u8; 16];
    fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn start_session(
    directory: &std::path::Path,
    name: &str,
    document: &std::path::Path,
    document_flag: &str,
) -> Result<(OwnedSession, UnixDatagram), Box<dyn Error>> {
    let binary = PathBuf::from(
        std::env::var_os("HEPTA_NOTES_SESSION_BIN").ok_or("HEPTA_NOTES_SESSION_BIN required")?,
    );
    if !binary.is_absolute()
        || std::env::var("TRILL_NOTES_PROBE_ISOLATED").as_deref() != Ok("1")
        || std::env::var_os("DISPLAY").is_none()
    {
        return Err("requires isolated Xvfb and absolute pinned Session binary".into());
    }
    let runtime = directory.join(name);
    fs::create_dir(&runtime)?;
    fs::set_permissions(&runtime, fs::Permissions::from_mode(0o700))?;
    let (parent, child) = UnixDatagram::pair()?;
    let inherited: OwnedFd = child.into();
    let log = fs::File::create(directory.join(format!("{name}.log")))?;
    let child = Command::new(binary)
        .arg("--notes-bootstrap-v2-stdin")
        .arg(document_flag)
        .arg(document)
        .stdin(Stdio::from(inherited))
        .stdout(Stdio::from(log.try_clone()?))
        .stderr(Stdio::from(log))
        .env("XDG_RUNTIME_DIR", &runtime)
        .env_remove("WAYLAND_DISPLAY")
        .process_group(0)
        .spawn()?;
    Ok((
        OwnedSession {
            child,
            socket: runtime.join("trillionnium-ui/session.sock"),
            instance: None,
            log: directory.join(format!("{name}.log")),
        },
        parent,
    ))
}

#[tokio::test]
#[ignore = "requires an explicitly isolated Xvfb and pinned companion Session/App binaries"]
async fn notes_actual_app_sigkill_original_owner_clean_reopen() -> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory,
        config,
        host,
        operations,
        issuer,
        final_use,
        primary_device,
    } = notes_host_fixture().await?;
    let authority = operations.authority.clone();
    let verifier = operations.verifier.clone();
    let document = directory.path().join("crash-document.json");
    let (mut session, bootstrap) = start_session(
        directory.path(),
        "before-crash",
        &document,
        "--notes-new-document",
    )?;
    let probe = Arc::new(NotesReplyLossProbe::default());
    let fixture_probe = Arc::clone(&probe);
    let captured = Arc::new(Mutex::new(None::<Arc<dyn NotesPrivateChannel>>));
    let fixture_channel = Arc::clone(&captured);
    let (operations, identity) = operations
        .with_notes_from_session_test_channel(
            &config,
            &host,
            bootstrap,
            final_use,
            move |effect, recovery| {
                let channel: Arc<dyn NotesPrivateChannel> =
                    Arc::new(NotesLocalChannel::new(effect, recovery, fixture_probe)?);
                *fixture_channel
                    .lock()
                    .map_err(|_| AgentdError::Invalid("fixture lock".into()))? =
                    Some(Arc::clone(&channel));
                Ok(channel)
            },
        )
        .await?;
    session.instance = Some(identity.session_instance.clone());
    session.wait_for_notes_layout(&identity)?;
    let (host, _) = operations.attach(Arc::new(host)).await?;
    let channel = captured
        .lock()
        .map_err(|error| error.to_string())?
        .take()
        .ok_or("no channel")?;
    let observer = ProductionNotesTarget::new(identity.clone(), channel)?.document_observer()?;
    let text = "actual durable Notes survives SIGKILL / 中文";
    let payload = serde_json::to_string(&serde_json::json!({
        "schema_version":1,"action":"replace_note","operation_id":"notes-actual-crash",
        "destination_id":identity.destination_id(),"target":identity,"expected_revision":0,"text":text
    }))?;
    let operation = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(config.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = host
        .writer()
        .prepare_operation(operation, NOTES_REPLACE_TOPIC_V1, payload.clone())
        .await?;
    probe.lose_next_reply.store(true, Ordering::SeqCst);
    let result = host
        .dispatch_to_with_grant_provider(&identity.destination_id(), queued.clone())
        .await?;
    assert_eq!(result.state, LocalOutcomeState::Indeterminate);
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let nonce = fresh_nonce()?;
        let state = observer.observe_document(&nonce)?;
        if state.revision == 1 {
            assert_eq!(state.text_sha256, Sha256Digest::for_bytes(text.as_bytes()));
            break;
        }
        if Instant::now() > deadline {
            return Err("actual App did not persist before crash".into());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    // SIGKILL the retained test-created process group before any graceful exit.
    let group = libc::pid_t::try_from(session.child.id())?;
    // SAFETY: this test created and still retains this unreaped child group.
    assert_eq!(unsafe { libc::kill(-group, libc::SIGKILL) }, 0);
    session.instance = None;
    drop(session);
    drop(observer);
    let writer = host.writer();
    let current_cut = writer.recovery_anchor().await?;
    drop(host);
    let writer = Arc::try_unwrap(writer).map_err(|_| "original writer is still shared")?;
    writer.close().await?;
    // This is a qualification-only captured cut. Production must supply its
    // independent current cut and verified writer authority, never copy this.
    let reopened = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&current_cut),
        authority,
        verifier,
        "notes-host-source",
        /*lease_generation*/ 1,
    )
    .await?;
    assert_eq!(
        reopened.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    let (mut session, bootstrap) = start_session(
        directory.path(),
        "after-crash",
        &document,
        "--notes-document",
    )?;
    let recovered = reopened
        .recover_notes_from_session(bootstrap, &identity, &queued.occurrence_key)
        .await?;
    assert_ne!(recovered.current_identity, identity);
    session.instance = Some(recovered.current_identity.session_instance.clone());
    session.wait_for_notes_layout(&recovered.current_identity)?;
    let readback = recovered
        .current_target
        .document_observer()?
        .observe_document(&fresh_nonce()?)?;
    assert_eq!(
        (readback.revision, &readback.text_sha256),
        (1, &Sha256Digest::for_bytes(text.as_bytes()))
    );
    let grants_before = issuer.requests.load(Ordering::SeqCst);
    assert_eq!(
        reopened
            .writer()
            .reconcile_target_batch(&recovered.previous_target, /*limit*/ 8)
            .await?,
        1
    );
    assert_eq!(
        reopened.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(issuer.requests.load(Ordering::SeqCst), grants_before);
    assert_eq!(probe.effect_attempts.load(Ordering::SeqCst), 1);
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    // Metadata retirement is safely repeatable after source terminality.
    reopened
        .writer()
        .retire_notes_receipt(&recovered.previous_target, &queued.occurrence_key)
        .await?;
    let evidence = serde_json::json!({
        "profile":"test-issuer-original-owner-real-app-sigkill-reopen", "production_authority":false,
        "app_sigkill":true,"original_source_cleanly_closed_and_reopened":true,"old_target":identity,
        "new_target":recovered.current_identity,"revision":readback.revision,
        "text_sha256":readback.text_sha256.as_str(),"source_state":"committed",
        "effect_attempts":1,"recovery_grants_requested":0,"recovery_effect_replay":false,
        "source_current_cut_captured_by_fixture":true,
        "source_recovery_anchor":reopened.writer().recovery_anchor().await?
    });
    if let Some(path) = std::env::var_os("HEPTA_NOTES_CRASH_QUALIFICATION_OUTPUT") {
        fs::write(path, serde_json::to_vec_pretty(&evidence)?)?;
    }
    eprintln!("HEPTA_NOTES_CRASH_QUALIFICATION={evidence}");
    session.cancel_notes()?;
    Ok(())
}

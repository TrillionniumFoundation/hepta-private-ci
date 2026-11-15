//! Explicit delay-transport qualification over an actual isolated Notes App.
//! A frame already written into one FIFO cannot be overtaken by this fence.
//! The sole delayed frame below is withheld before touching the actual App FD.

use super::*;
use pretty_assertions::assert_eq;

#[derive(Default)]
struct FenceDelayProbe {
    hold_next: AtomicBool,
    precontact_invalidation: AtomicBool,
    held: Mutex<Option<Vec<u8>>>,
    dispatch_attempts: AtomicUsize,
    app_effect_exchanges: AtomicUsize,
    held_invalidations: AtomicUsize,
    late_deliveries: AtomicUsize,
}

struct FenceDelayChannel {
    original: AgentdNotesChannel,
    probe: Arc<FenceDelayProbe>,
}

impl FenceDelayChannel {
    fn new(
        effect: UnixStream,
        recovery: UnixDatagram,
        probe: Arc<FenceDelayProbe>,
    ) -> std::io::Result<Self> {
        Ok(Self {
            original: AgentdNotesChannel::from_private_channels(effect, recovery)?,
            probe,
        })
    }

    /// Release the exact previously authorized owned bytes, as a test-only
    /// late transport delivery. This does not request or consume a new grant.
    fn release_held(&self, expected: &[u8]) -> Result<Vec<u8>, String> {
        let raw = self
            .probe
            .held
            .lock()
            .map_err(|_| "held Notes test frame lock".to_string())?
            .take()
            .ok_or_else(|| "no held original Notes test frame".to_string())?;
        if raw != expected {
            return Err("held Notes frame differs from original authorized bytes".into());
        }
        self.probe.late_deliveries.fetch_add(1, Ordering::SeqCst);
        self.probe
            .app_effect_exchanges
            .fetch_add(1, Ordering::SeqCst);
        let response = self.original.exchange(&raw);
        if response.is_err() {
            self.original.invalidate();
        }
        response
    }
}

impl NotesPrivateChannel for FenceDelayChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        self.probe.dispatch_attempts.fetch_add(1, Ordering::SeqCst);
        if self.probe.hold_next.swap(false, Ordering::SeqCst) {
            let mut held = self
                .probe
                .held
                .lock()
                .map_err(|_| "held Notes test frame lock".to_string())?;
            if held.is_some() {
                return Err("test delay slot already occupied".into());
            }
            *held = Some(request.to_vec());
            self.probe
                .precontact_invalidation
                .store(true, Ordering::SeqCst);
            return Err(
                "explicit test delay: original authorized frame has not touched the App FD".into(),
            );
        }
        self.probe
            .app_effect_exchanges
            .fetch_add(1, Ordering::SeqCst);
        self.original.exchange(request)
    }

    fn invalidate(&self) {
        // This exception belongs only to the explicit pre-contact fault. The
        // physical App stream has neither bytes nor a reply from that attempt.
        // Every ordinary ambiguous I/O path retains real invalidation.
        if self
            .probe
            .precontact_invalidation
            .swap(false, Ordering::SeqCst)
        {
            self.probe.held_invalidations.fetch_add(1, Ordering::SeqCst);
        } else {
            self.original.invalidate();
        }
    }

    fn recovery_handle(&self) -> Result<Arc<dyn codex_hepta_memory::NotesRecoveryChannel>, String> {
        self.original.recovery_handle()
    }

    fn recovery_exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        self.original.recovery_exchange(request)
    }
}

#[tokio::test]
#[ignore = "requires explicitly isolated Xvfb and pinned fence-capable companion Session/App"]
async fn notes_actual_ui_authorized_fence_excludes_delayed_original() -> Result<(), Box<dyn Error>>
{
    if std::env::var("TRILL_NOTES_PROBE_ISOLATED").as_deref() != Ok("1")
        || std::env::var_os("DISPLAY").is_none()
    {
        return Err("fence qualification requires its own isolated Xvfb".into());
    }
    let selected = PathBuf::from(
        std::env::var_os("HEPTA_NOTES_SESSION_BIN")
            .ok_or("HEPTA_NOTES_SESSION_BIN must select the pinned companion")?,
    );
    if !selected.is_absolute() {
        return Err("Session binary path must be absolute".into());
    }
    let session_binary = selected.canonicalize()?;
    let app_binary = session_binary.with_file_name("trill-app-window");
    let session_sha256 = Sha256Digest::for_bytes(&fs::read(&session_binary)?);
    let app_sha256 = Sha256Digest::for_bytes(&fs::read(&app_binary)?);
    let mut cases = Vec::new();
    for delayed in [true, false] {
        let NotesHostFixture {
            directory,
            config,
            host,
            operations,
            issuer,
            final_use,
            primary_device,
        } = notes_host_fixture().await?;
        let runtime = directory.path().join("ui-fence-runtime");
        fs::create_dir(&runtime)?;
        fs::set_permissions(&runtime, fs::Permissions::from_mode(0o700))?;
        let (parent, child_channel) = UnixDatagram::pair()?;
        let inherited: OwnedFd = child_channel.into();
        let logs = fs::File::create(directory.path().join("fence-session.log"))?;
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
        let probe = Arc::new(FenceDelayProbe::default());
        probe.hold_next.store(delayed, Ordering::SeqCst);
        let channel_probe = Arc::clone(&probe);
        let retained_channel = Arc::new(Mutex::new(None));
        let installed = Arc::clone(&retained_channel);
        let (operations, identity) = operations
            .with_notes_from_session_test_channel(
                &config,
                &host,
                parent,
                final_use,
                move |effect, recovery| {
                    let channel =
                        Arc::new(FenceDelayChannel::new(effect, recovery, channel_probe)?);
                    *installed
                        .lock()
                        .map_err(|_| std::io::Error::other("fence test channel lock"))? =
                        Some(Arc::clone(&channel));
                    Ok(channel as Arc<dyn NotesPrivateChannel>)
                },
            )
            .await?;
        let channel = retained_channel
            .lock()
            .map_err(|error| error.to_string())?
            .take()
            .ok_or("missing real fence test channel")?;
        let observer = crate::AgentdNotesDocumentObserver::new(
            codex_hepta_memory::ProductionNotesTarget::new(identity.clone(), channel.clone())?
                .document_observer(),
        );
        session.instance = Some(identity.session_instance.clone());
        let (host, _) = operations.attach(Arc::new(host)).await?;
        let first_frame = session.wait_for_notes_layout(&identity)?;
        let before = observer.observe_document()?;
        assert_eq!(
            before,
            codex_hepta_memory::NotesDocumentState {
                target: identity.clone(),
                revision: 0,
                text_sha256: Sha256Digest::for_bytes(b""),
                receipt_pending: false,
            }
        );
        let operation_id = if delayed {
            "notes-fence-delayed-original"
        } else {
            "notes-fence-applied-original"
        };
        let cancellation_id = if delayed {
            "notes-fence-before-original"
        } else {
            "notes-fence-after-applied"
        };
        let text = "original authorized text / 取消先赢时不得出现";
        let payload = serde_json::to_string(&serde_json::json!({
            "schema_version":1,"action":"replace_note","operation_id":operation_id,
            "destination_id":identity.destination_id(),"target":identity,"expected_revision":0,"text":text
        }))?;
        let intent = notes_operation_intent(
            &identity,
            &payload,
            StableId::new(config.identity().agent_id.as_str())?,
            Generation::new(1)?,
        )?;
        let original = host
            .writer()
            .prepare_operation(intent, NOTES_REPLACE_TOPIC_V1, payload.clone())
            .await?;
        let original_result = host
            .dispatch_to_with_grant_provider(&identity.destination_id(), original.clone())
            .await?;
        assert_eq!(
            original_result.state,
            if delayed {
                LocalOutcomeState::Indeterminate
            } else {
                LocalOutcomeState::Committed
            }
        );
        assert_eq!(issuer.requests.load(Ordering::SeqCst), 1);
        assert_eq!(probe.dispatch_attempts.load(Ordering::SeqCst), 1);
        assert_eq!(
            probe.app_effect_exchanges.load(Ordering::SeqCst),
            if delayed { 0 } else { 1 }
        );
        let cancellation = host
            .writer()
            .prepare_notes_cancellation(&original.occurrence_key, cancellation_id)
            .await?;
        let cancellation_result = host
            .dispatch_to_with_grant_provider(&identity.destination_id(), cancellation.clone())
            .await?;
        let cancellation_receipt: serde_json::Value = serde_json::from_str(
            cancellation_result
                .target_receipt
                .as_deref()
                .or(cancellation_result.target_reason.as_deref())
                .ok_or("missing actual fence response")?,
        )?;
        let retained = host
            .writer()
            .retained_operation(&cancellation.occurrence_key)
            .await?
            .ok_or("missing original cancellation operation")?;
        let expected_result = if delayed {
            serde_json::json!({"status":"fenced","original_operation_id":operation_id,
                "original_payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
                "previous_revision":0,"revision":1,"text_sha256":Sha256Digest::for_bytes(b"").as_str()})
        } else {
            serde_json::json!({"status":"not_fenced","reason":"revision_conflict","current_revision":1})
        };
        assert_eq!(
            cancellation_receipt,
            serde_json::json!({"schema_version":1,"target":identity,"operation_id":cancellation_id,
                "payload_sha256":Sha256Digest::for_bytes(retained.payload_json.as_bytes()).as_str(),
                "result":expected_result})
        );
        assert_eq!(
            cancellation_result.state,
            if delayed {
                LocalOutcomeState::Committed
            } else {
                LocalOutcomeState::Rejected
            }
        );
        assert_eq!(retained.topic, codex_hepta_memory::NOTES_FENCE_TOPIC_V1);
        let grants_before_late = issuer.requests.load(Ordering::SeqCst);
        assert_eq!(grants_before_late, 2);
        let late_response = if delayed {
            let raw = channel.release_held(payload.as_bytes())?;
            let response: serde_json::Value = serde_json::from_slice(&raw)?;
            assert_eq!(
                response,
                serde_json::json!({"schema_version":1,"target":identity,"operation_id":operation_id,
                    "payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
                    "result":{"status":"not_applied","reason":"revision_conflict","current_revision":1}})
            );
            Some(response)
        } else {
            None
        };
        let current = observer.observe_document()?;
        assert_eq!(current.target, identity);
        assert_eq!(current.revision, 1);
        assert_eq!(
            current.text_sha256,
            Sha256Digest::for_bytes(if delayed { b"" } else { text.as_bytes() })
        );
        assert_eq!(
            host.writer().status(&original.occurrence_key).await?,
            original_result.state
        );
        assert_eq!(
            host.writer().status(&cancellation.occurrence_key).await?,
            cancellation_result.state
        );
        assert_eq!(
            (
                probe.dispatch_attempts.load(Ordering::SeqCst),
                probe.app_effect_exchanges.load(Ordering::SeqCst),
                probe.held_invalidations.load(Ordering::SeqCst),
                probe.late_deliveries.load(Ordering::SeqCst),
                issuer.requests.load(Ordering::SeqCst),
                primary_device.installs.load(Ordering::SeqCst)
            ),
            (
                2,
                2,
                if delayed { 1 } else { 0 },
                if delayed { 1 } else { 0 },
                2,
                0
            )
        );
        cases.push(serde_json::json!({
            "case":if delayed {"fence_before_delayed_original"} else {"apply_before_fence"},
            "target":identity,"ui_first_frame_unix_ms":first_frame,
            "original_payload":serde_json::from_str::<serde_json::Value>(&payload)?,
            "original_payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
            "original_source_state":original_result.state,"original_application_receipt":original_result.target_receipt,
            "cancellation_payload":serde_json::from_str::<serde_json::Value>(&retained.payload_json)?,
            "cancellation_source_state":cancellation_result.state,"cancellation_application_receipt":cancellation_receipt,
            "late_original_response":late_response,
            "current_document":{"target":current.target,"revision":current.revision,
                "text_sha256":current.text_sha256.as_str(),"receipt_pending":current.receipt_pending},
            "original_frame_initially_written_to_app_fd":!delayed,
            "authorized_dispatch_attempts":probe.dispatch_attempts.load(Ordering::SeqCst),
            "actual_app_effect_exchanges":probe.app_effect_exchanges.load(Ordering::SeqCst),
            "precontact_fault_invalidations":probe.held_invalidations.load(Ordering::SeqCst),
            "late_transport_deliveries":probe.late_deliveries.load(Ordering::SeqCst),
            "issuer_requests":issuer.requests.load(Ordering::SeqCst),
            "late_delivery_requested_new_grant":issuer.requests.load(Ordering::SeqCst)!=grants_before_late,
            "recovery_lane_executed_fence":false,"source_anchor":host.writer().recovery_anchor().await?
        }));
        session.cancel_notes()?;
    }
    let evidence = serde_json::json!({
        "schema_version":1,"profile":"fixture-authority-actual-app-precontact-delay-fence",
        "production_authority":false,"full_model_handler_qualified":false,"native_kernel_qualified":false,"pixels_qualified":false,
        "physical_fifo_reordering_qualified":false,"cold_recovery_qualified":false,
        "delay_profile":"Test-only first original payload is held before any actual App FD write; normal I/O errors retain real invalidation. Later release delivers the same previously authorized owned bytes without a new grant. Frames already written into the FIFO cannot be overtaken.",
        "session_sha256":session_sha256.as_str(),"app_sha256":app_sha256.as_str(),"cases":cases
    });
    if let Some(path) = std::env::var_os("HEPTA_NOTES_FENCE_QUALIFICATION_OUTPUT") {
        fs::write(path, serde_json::to_vec_pretty(&evidence)?)?;
    }
    eprintln!("HEPTA_NOTES_ACTUAL_FENCE_QUALIFICATION={evidence}");
    Ok(())
}

//! Original SQLite owner and FinalUse integration over a real socketpair.
//! The normal test uses an explicit fixture issuer and application model. An
//! ignored cross-repo test additionally launches a pinned real Session/App;
//! neither profile supplies production authority or native-kernel evidence.

use super::*;
use codex_hepta_memory::NOTES_REPLACE_TOPIC_V1;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::notes_operation_intent;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;

#[path = "notes_objective_tests.rs"]
mod objective_tests;

#[path = "notes_objective_composition_tests.rs"]
mod composition_tests;

struct NotesHostFixture {
    directory: tempfile::TempDir,
    config: AgentdConfig,
    host: AgentdProductionWriterHost,
    operations: AgentdProductionOperationRuntimeConfig,
    issuer: Arc<ExternalTestIssuer>,
    final_use: FinalUseAuthority,
    primary_device: Arc<HostTestDevice>,
}

async fn notes_host_fixture() -> Result<NotesHostFixture, Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c061")?;
    let record = registry.register(AgentManifest::new(
        owner.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &owner,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let config = AgentdConfig::load(
        fleet_path,
        owner.clone(),
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;
    // Qualification-only creation of the initial database. Product bootstrap
    // must authenticate its independently retained current cut instead.
    let store = CognitiveStore::open(&config.identity().layout).await?;
    let cut = store.recovery_anchor().await?;
    store.close().await;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"notes-host-source-fixture"),
        /*authority_epoch*/ 13,
        /*owner_epoch*/ 17,
        /*lease_expires_at_unix_seconds*/ 4_000_000_000,
        ProductionAuthorityToken::from_verified_bytes(b"notes-host-fixture-token".to_vec())?,
    )?;
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        |lease: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
            if &lease.agent_id != expected
                || lease.grant_digest != Sha256Digest::for_bytes(b"notes-host-source-fixture")
            {
                return Err("source authority fixture mismatch".to_string());
            }
            Ok(())
        },
    );
    let host = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        authority.clone(),
        verifier.clone(),
        "notes-host-source",
        /*lease_generation*/ 1,
    )
    .await?;
    let issuer = Arc::new(ExternalTestIssuer {
        key: SigningKey::from_bytes(&[58; 32]),
        enabled: AtomicBool::new(true),
        invalid_first_signature: AtomicBool::new(false),
        requests: AtomicUsize::new(0),
        binding: Mutex::new(None),
    });
    let final_use_path = root.join("final-use");
    fs::create_dir(&final_use_path)?;
    fs::set_permissions(&final_use_path, fs::Permissions::from_mode(0o700))?;
    let final_use = FinalUseAuthority::open_state_dir(
        &final_use_path,
        "hos2-host-external-fixture".to_string(),
        issuer.key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 19,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let primary_device = Arc::new(HostTestDevice::default());
    let operations = AgentdProductionOperationRuntimeConfig::new(
        authority,
        verifier,
        "notes-host-source".to_string(),
        /*lease_generation*/ 1,
        final_use.clone(),
        Arc::new(ProductionHos2Target::new(primary_device.clone())),
        issuer.clone(),
        Duration::from_millis(20),
    );
    Ok(NotesHostFixture {
        directory,
        config,
        host,
        operations,
        issuer,
        final_use,
        primary_device,
    })
}

#[tokio::test]
async fn notes_recovered_writer_persists_lost_reply_and_retires_without_replay()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory: _directory,
        config,
        host,
        operations,
        issuer,
        final_use,
        primary_device,
    } = notes_host_fixture().await?;
    let owner = config.identity().agent_id.clone();
    let (missing_provider_bootstrap, _missing_provider_peer) = UnixDatagram::pair()?;
    assert!(
        host.clone()
            .attach_additional_notes_from_session(missing_provider_bootstrap, final_use.clone())
            .await
            .is_err()
    );
    let wrong_owner = AgentdProductionOperationRuntimeConfig::new(
        operations.authority.clone(),
        operations.verifier.clone(),
        "notes-host-source".to_string(),
        /*lease_generation*/ 2,
        final_use.clone(),
        Arc::new(ProductionHos2Target::new(primary_device.clone())),
        issuer.clone(),
        Duration::from_millis(20),
    );
    let (wrong_owner_bootstrap, _wrong_owner_peer) = UnixDatagram::pair()?;
    assert!(
        wrong_owner
            .with_notes_from_session(&config, &host, wrong_owner_bootstrap, final_use.clone())
            .await
            .is_err()
    );
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 0);
    let identity = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let destination = identity.destination_id();
    let (owner_bootstrap, session_bootstrap) = UnixDatagram::pair()?;
    session_bootstrap.set_read_timeout(Some(Duration::from_secs(4)))?;
    let (source_channel, mut application) = UnixStream::pair()?;
    let (recovery_source, recovery_application) = UnixDatagram::pair()?;
    recovery_application.set_read_timeout(Some(Duration::from_secs(10)))?;
    application.set_read_timeout(Some(Duration::from_secs(10)))?;
    application.set_write_timeout(Some(Duration::from_secs(10)))?;
    let entries = Arc::new(AtomicUsize::new(0));
    let peer_entries = entries.clone();
    let peer_identity = identity.clone();
    let peer = std::thread::spawn(move || -> Result<Vec<String>, String> {
        let offer = serde_json::to_vec(&serde_json::json!({
            "schema_version":2,"action":"offer_notes_target","target":peer_identity,
            "destination_id":peer_identity.destination_id()
        }))
        .map_err(|error| error.to_string())?;
        let mut vector = libc::iovec {
            iov_base: offer.as_ptr().cast_mut().cast(),
            iov_len: offer.len(),
        };
        let mut control = [0_usize; 4];
        // SAFETY: this test sends one borrowed live descriptor with a bounded
        // JSON datagram. All pointers remain live throughout sendmsg.
        let sent = unsafe {
            let mut message: libc::msghdr = mem::zeroed();
            message.msg_iov = &mut vector;
            message.msg_iovlen = 1;
            message.msg_control = control.as_mut_ptr().cast();
            message.msg_controllen =
                libc::CMSG_SPACE((2 * mem::size_of::<libc::c_int>()) as u32) as usize;
            let header = libc::CMSG_FIRSTHDR(&message);
            (*header).cmsg_level = libc::SOL_SOCKET;
            (*header).cmsg_type = libc::SCM_RIGHTS;
            (*header).cmsg_len =
                libc::CMSG_LEN((2 * mem::size_of::<libc::c_int>()) as u32) as usize;
            libc::CMSG_DATA(header)
                .cast::<libc::c_int>()
                .write(source_channel.as_raw_fd());
            libc::CMSG_DATA(header)
                .cast::<libc::c_int>()
                .add(1)
                .write(recovery_source.as_raw_fd());
            libc::sendmsg(session_bootstrap.as_raw_fd(), &message, libc::MSG_NOSIGNAL)
        };
        if sent != offer.len() as isize {
            return Err("fixture bootstrap send failed".to_string());
        }
        drop(source_channel);
        drop(recovery_source);
        let mut ack = [0_u8; 1024];
        let size = session_bootstrap
            .recv(&mut ack)
            .map_err(|error| error.to_string())?;
        let ack: serde_json::Value =
            serde_json::from_slice(&ack[..size]).map_err(|error| error.to_string())?;
        assert_eq!(
            ack,
            serde_json::json!({"schema_version":2,"action":"notes_target_registration",
            "target":peer_identity,"destination_id":peer_identity.destination_id(),"status":"attached"})
        );
        drop(session_bootstrap);
        let mut applied = Vec::new();
        for revision in 0..2_u64 {
            let mut prefix = [0; 4];
            application
                .read_exact(&mut prefix)
                .map_err(|error| error.to_string())?;
            let mut payload = vec![0; u32::from_be_bytes(prefix) as usize];
            application
                .read_exact(&mut payload)
                .map_err(|error| error.to_string())?;
            let request: serde_json::Value =
                serde_json::from_slice(&payload).map_err(|error| error.to_string())?;
            assert_eq!(
                request["target"],
                serde_json::to_value(&peer_identity).map_err(|error| error.to_string())?
            );
            assert_eq!(request["expected_revision"], revision);
            let text = request["text"]
                .as_str()
                .ok_or("fixture missing text")?
                .to_string();
            applied.push(text.clone());
            peer_entries.fetch_add(1, Ordering::SeqCst);
            let response = serde_json::to_vec(&serde_json::json!({
                "schema_version":1,"target":peer_identity,
                "operation_id":request["operation_id"],
                "payload_sha256":Sha256Digest::for_bytes(&payload).as_str(),
                "result":{"status":"applied","previous_revision":revision,
                    "revision":revision + 1,"text_sha256":Sha256Digest::for_bytes(text.as_bytes()).as_str()}
            })).map_err(|error| error.to_string())?;
            if revision == 0 {
                application
                    .write_all(&(response.len() as u32).to_be_bytes())
                    .map_err(|error| error.to_string())?;
                application
                    .write_all(&response)
                    .map_err(|error| error.to_string())?;
            } else {
                // A real lost effect reply must not close the independent
                // observation lane or cause a second effect entry.
                application
                    .shutdown(std::net::Shutdown::Both)
                    .map_err(|error| error.to_string())?;
                let mut bytes = [0_u8; 8192];
                let length = recovery_application
                    .recv(&mut bytes)
                    .map_err(|error| error.to_string())?;
                let query: serde_json::Value =
                    serde_json::from_slice(&bytes[..length]).map_err(|error| error.to_string())?;
                assert_eq!(query["action"], "observe");
                assert_eq!(query["operation_id"], request["operation_id"]);
                assert_eq!(
                    query["payload_sha256"],
                    Sha256Digest::for_bytes(&payload).as_str()
                );
                recovery_application
                    .send(&response)
                    .map_err(|error| error.to_string())?;
            }
            let mut bytes = [0_u8; 8192];
            let attempts = if revision == 0 { 1 } else { 2 };
            for attempt in 0..attempts {
                let length = recovery_application
                    .recv(&mut bytes)
                    .map_err(|error| error.to_string())?;
                let ack: serde_json::Value =
                    serde_json::from_slice(&bytes[..length]).map_err(|error| error.to_string())?;
                assert_eq!(ack["action"], "acknowledge_terminal");
                assert_eq!(ack["operation_id"], request["operation_id"]);
                assert_eq!(
                    ack["payload_sha256"],
                    Sha256Digest::for_bytes(&payload).as_str()
                );
                assert_eq!(
                    ack["receipt_sha256"],
                    Sha256Digest::for_bytes(&response).as_str()
                );
                if revision == 1 && attempt == 0 {
                    continue;
                } // lose only retirement ACK
                let reply = serde_json::to_vec(&serde_json::json!({
                    "schema_version":1, "target":peer_identity, "operation_id":ack["operation_id"],
                    "payload_sha256":ack["payload_sha256"], "receipt_sha256":ack["receipt_sha256"],
                    "status":if attempt == 0 { "released" } else { "already_released" }
                }))
                .map_err(|error| error.to_string())?;
                recovery_application
                    .send(&reply)
                    .map_err(|error| error.to_string())?;
            }
        }
        Ok(applied)
    });
    let (operations, registered_identity) = operations
        .with_notes_from_session(&config, &host, owner_bootstrap, final_use)
        .await?;
    let (host, _) = operations.attach(Arc::new(host)).await?;
    assert_eq!(registered_identity, identity);
    assert_eq!(host.destination_count(), 2);
    let mut receipts = Vec::new();
    for revision in 0..2_u64 {
        let payload = serde_json::to_string(&serde_json::json!({
            "schema_version":1,"action":"replace_note","operation_id":format!("notes-host-{revision}"),
            "destination_id":destination,"target":identity,"expected_revision":revision,
            "text":format!("authorized model revision {}", revision + 1)
        }))?;
        let intent = notes_operation_intent(
            &identity,
            &payload,
            StableId::new(owner.as_str())?,
            Generation::new(1)?,
        )?;
        let queued = host
            .writer()
            .prepare_operation(intent, NOTES_REPLACE_TOPIC_V1, payload)
            .await?;
        let binding = host
            .writer()
            .final_use_binding(&queued, &destination)
            .await?;
        if revision == 0 {
            assert!(
                host.dispatch_to_with_grant_provider("absent-destination", queued.clone())
                    .await
                    .is_err()
            );
            assert_eq!(issuer.requests.load(Ordering::SeqCst), 0);
            assert_eq!(entries.load(Ordering::SeqCst), 0);
        }
        let receipt = host
            .dispatch_to_with_grant_provider(&destination, queued.clone())
            .await?;
        assert_eq!(
            *issuer.binding.lock().map_err(|error| error.to_string())?,
            Some(binding)
        );
        assert_eq!(
            host.writer().status(&queued.occurrence_key).await?,
            receipt.state
        );
        receipts.push(receipt);
    }
    assert_eq!(receipts[0].state, LocalOutcomeState::Committed);
    assert!(receipts[0].target_receipt.is_some());
    assert_eq!(receipts[1].state, LocalOutcomeState::Indeterminate);
    assert!(receipts[1].target_receipt.is_none());
    host.reconcile(32).await?;
    assert_eq!(
        host.writer().status("notes-host-1").await?,
        LocalOutcomeState::Committed
    );
    host.reconcile(32).await?;
    assert_eq!(
        peer.join().expect("application model thread")?,
        vec![
            "authorized model revision 1".to_string(),
            "authorized model revision 2".to_string()
        ]
    );
    assert_eq!(host.reauthorize_pending(32).await?, 0);
    assert_eq!(
        host.writer().status("notes-host-1").await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(entries.load(Ordering::SeqCst), 2);
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 2);
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    Ok(())
}

#[path = "production_notes_gui_tests.rs"]
mod gui_tests;

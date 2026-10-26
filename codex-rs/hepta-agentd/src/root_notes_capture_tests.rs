//! Public retained serving and capture with explicit Root fixture authority.
//! The five-lane publisher is a controlled libtest child, not original Agentd.
use super::*;
use crate::PreparedHostAuthoritySession;
use crate::StoppedHostNotesSession;
use crate::authority_host_service::notes_capture_peer::Peer;
use codex_hepta_memory::ObjectiveSenderWriterFence;
use pretty_assertions::assert_eq;
use std::io;
use std::thread::JoinHandle;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct CaptureFixture {
    public: PublicFixture,
    _runtime: tempfile::TempDir,
    early: HostNotesRecoveryPredecessor,
    prepared: Option<PreparedHostAuthoritySession>,
    peer: Peer,
    current: CognitiveCheckpointReceipt,
    sequence: u64,
}

impl CaptureFixture {
    async fn new(target: NotesTargetIdentity) -> Self {
        let (child, peer) = Peer::spawn();
        let original = OriginalFixture::with_predecessor(
            FixtureLayout::OriginalHostBind(original_bind()),
            FixturePredecessor::Retained {
                publisher: Publisher::capture(child),
                target,
            },
        )
        .await;
        let mut public = PublicFixture::from_original(original);
        let early = public.previous.take().unwrap();
        let runtime =
            tempfile::tempdir_in(std::env::var_os("HEPTA_NOTES_SESSION_RUNTIME_ROOT").unwrap())
                .unwrap();
        let directory = File::open(runtime.path()).unwrap();
        // SAFETY: only this new test runtime directory gets the dedicated group.
        assert_eq!(unsafe { libc::fchown(directory.as_raw_fd(), 0, 60001) }, 0);
        std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o2710)).unwrap();
        public.config.sockets = HostAuthoritySocketPaths {
            observation: runtime.path().join("observe.sock"),
            issuer: runtime.path().join("issuer.sock"),
            checkpoint: runtime.path().join("checkpoint.sock"),
            device_frontier: Some(runtime.path().join("device.sock")),
            notes_frontier: Some(runtime.path().join("notes.sock")),
        };
        public.config_path = public._root.path().join("successor-lanes-config.json");
        write_json(&public.config_path, &public.config);
        let mut old_config = public.config.clone();
        old_config.writer = Some(early.writer.clone());
        old_config.timeout_ms = 5_000;
        let mut old_registration = public.registration.clone();
        let lifetime = &early.checkpoint.head.peer_lifetime;
        old_registration.peer_pid = lifetime.pid;
        old_registration.boot_id = lifetime.boot_id.clone();
        old_registration.process_start_ticks = lifetime.process_start_ticks;
        old_registration.publisher_epoch = early.checkpoint.head.publisher_epoch;
        old_registration.registered_identity.spawn_generation = early.writer.spawn_generation;
        let config_path = public._root.path().join("old-config.json");
        let registration_path = public._root.path().join("old-registration.json");
        write_json(&config_path, &old_config);
        write_json(&registration_path, &old_registration);
        let prepared = PreparedHostAuthoritySession::open(
            &config_path,
            &registration_path,
            process::pidfd(&public._old.child),
        )
        .unwrap();
        let current = early.checkpoint.clone();
        Self {
            public,
            _runtime: runtime,
            early,
            prepared: Some(prepared),
            peer,
            current,
            sequence: 0,
        }
    }

    fn prepare_fixed_notes(&mut self) -> PreparedHostAuthoritySession {
        self.prepared
            .take()
            .unwrap()
            .with_registered_notes_from_session(
                &self.early.notes_target,
                self.early.notes_lifetime_ms,
            )
            .unwrap()
    }

    fn start(
        &mut self,
        prepared: PreparedHostAuthoritySession,
    ) -> JoinHandle<io::Result<StoppedHostNotesSession>> {
        let worker = std::thread::spawn(move || prepared.serve_retained_notes());
        let sockets = &self.public.config.sockets;
        self.peer.connect(&[
            sockets.observation.clone(),
            sockets.issuer.clone(),
            sockets.checkpoint.clone(),
            sockets.device_frontier.clone().unwrap(),
            sockets.notes_frontier.clone().unwrap(),
        ]);
        self.exchange(CognitiveCheckpointCommand::ReadHead);
        assert_eq!(self.current, self.early.checkpoint);
        worker
    }

    fn exchange(&mut self, command: CognitiveCheckpointCommand) {
        self.sequence += 1;
        let head = &self.current.head;
        let writer = &head.writer_binding;
        let proposal = (command == CognitiveCheckpointCommand::PreparePublication).then(|| {
            CognitiveCheckpointProposal {
                cut: head.last_current.clone(),
                writer_fence: ObjectiveSenderWriterFence {
                    owner_agent_id: head.owner_agent_id.clone(),
                    lease_id: writer.lease_id.clone(),
                    lease_sha256: Sha256Digest::for_bytes(
                        b"explicit controlled checkpoint peer fixture",
                    ),
                    generation: writer.generation,
                    authority_epoch: writer.authority_epoch,
                    owner_epoch: writer.owner_epoch,
                    authority_grant_digest: writer.authority_grant_digest.clone(),
                    fencing_token_digest: writer.fencing_token_digest.clone(),
                    expires_at_unix_seconds: writer.expires_at_unix_seconds,
                },
            }
        });
        let reply = self.peer.exchange(CognitiveCheckpointRequest {
            schema_version: 1,
            operation: OPERATION.into(),
            request_id: format!("{:016x}{:016x}", head.publisher_epoch, self.sequence),
            expected: (command != CognitiveCheckpointCommand::ReadHead)
                .then(|| self.current.token.clone()),
            command,
            proposal,
        });
        assert_eq!(reply.status, CognitiveCheckpointStatus::Ack);
        self.current = CognitiveCheckpointReceipt {
            head: reply.head.unwrap(),
            token: reply.token.unwrap(),
        };
    }

    fn stop_service(
        &mut self,
        worker: JoinHandle<io::Result<StoppedHostNotesSession>>,
    ) -> StoppedHostNotesSession {
        self.peer.close_with_error();
        let stopped = worker.join().unwrap().unwrap();
        assert!(
            stopped.serve_result().is_err(),
            "the injected invalid frame must remain an error"
        );
        assert!(self.public._old.child.try_wait().unwrap().is_none());
        for path in [
            &self.public.config.sockets.observation,
            &self.public.config.sockets.issuer,
            &self.public.config.sockets.checkpoint,
            self.public.config.sockets.device_frontier.as_ref().unwrap(),
            self.public.config.sockets.notes_frontier.as_ref().unwrap(),
        ] {
            assert!(
                !path.exists(),
                "the joined original service must release its listeners"
            );
        }
        stopped
    }

    fn wait_expiry(&self) {
        let until = Instant::now() + Duration::from_secs(15);
        // Scheduling only. The production capture uses its original protected
        // clock and independently rechecks the complete millisecond expiry.
        while SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis()
            < u128::from(self.early.writer.authority_lease.expires_at_unix_ms) + 100
        {
            assert!(Instant::now() < until, "fixture lease expiry deadline");
            std::thread::sleep(Duration::from_millis(10));
        }
    }

    fn refuse_unchanged(&self, stopped: &mut StoppedHostNotesSession) {
        let before = snapshot_original(&self.public.config, "root-authority-leases-v1");
        assert!(stopped.try_capture_predecessor().is_err());
        assert_eq!(
            snapshot_original(&self.public.config, "root-authority-leases-v1"),
            before
        );
    }

    fn capture_unchanged(
        &self,
        stopped: &mut StoppedHostNotesSession,
    ) -> HostNotesRecoveryPredecessor {
        let before = snapshot_original(&self.public.config, "root-authority-leases-v1");
        let captured = stopped.try_capture_predecessor().unwrap();
        assert_eq!(
            snapshot_original(&self.public.config, "root-authority-leases-v1"),
            before
        );
        assert_eq!(
            (
                &captured.writer,
                &captured.writer_proof,
                &captured.checkpoint,
                &captured.notes_target,
                captured.notes_lifetime_ms
            ),
            (
                &self.early.writer,
                &self.early.writer_proof,
                &self.current,
                &self.early.notes_target,
                self.early.notes_lifetime_ms
            )
        );
        self.refuse_unchanged(stopped);
        captured
    }
}

fn target() -> NotesTargetIdentity {
    NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 7,
        incarnation: "2".repeat(32),
    }
}

fn receipt(name: &str, assertions: serde_json::Value) {
    write_json(
        &output().join(name),
        &serde_json::json!({
            "schema":"hepta.notes-stopped-capture-fixture.v1", "passed":true,
            "production_authority":false, "actual_agentd_owner":false, "activation_sent":false,
            "effect_dispatched":false, "app_window_qualified":false, "root_cold_restart":false,
            "serve_retained_api_executed":true, "five_lanes_connected":true,
            "all_started_lane_workers_joined":true, "serve_error_observed":true,
            "original_state_checked":true, "assertions":assertions,
        }),
    );
}

#[tokio::test]
#[ignore = "explicit private Root bind and frozen controlled five-lane peer ELF"]
async fn root_notes_capture_requires_actual_exit_and_full_expiry() {
    let mut f = CaptureFixture::new(target()).await;
    let prepared = f.prepare_fixed_notes();
    let worker = f.start(prepared);
    let mut stopped = f.stop_service(worker);
    f.refuse_unchanged(&mut stopped);
    f.public._old.stop();
    assert!(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis()
            < u128::from(f.early.writer.authority_lease.expires_at_unix_ms)
    );
    f.refuse_unchanged(&mut stopped);
    f.wait_expiry();
    f.capture_unchanged(&mut stopped);
    let mut live = CaptureFixture::new(target()).await;
    let prepared = live.prepare_fixed_notes();
    let worker = live.start(prepared);
    let mut stopped = live.stop_service(worker);
    live.wait_expiry();
    live.refuse_unchanged(&mut stopped);
    live.public._old.stop();
    live.capture_unchanged(&mut stopped);
    receipt(
        "capture-retirement.json",
        serde_json::json!({
            "live_publisher_refused":true, "dead_unexpired_refused":true, "live_expired_refused":true,
            "same_stopped_object_retry_passed":true, "repeated_capture_refused":true,
        }),
    );
}

#[tokio::test]
#[ignore = "explicit private Root bind, frozen five-lane peer, and pinned actual Session/App/Xvfb"]
async fn root_notes_capture_actual_sessions_retains_latest_current_once() {
    let mut old_session = ActualSession::spawn("capture-actual-old");
    let actual_target = serde_json::from_value(old_session.reserved["target"].clone()).unwrap();
    let mut f = CaptureFixture::new(actual_target).await;
    let (producer, mut reader) = deployment();
    let prepared = f
        .prepared
        .take()
        .unwrap()
        .with_notes_startup_from_session(
            &f.public.profile_path,
            old_session.channel.try_clone().unwrap(),
            old_session.pidfd.try_clone().unwrap(),
            producer,
        )
        .unwrap();
    assert_eq!(
        read_sealed(&mut reader)["startup_release"]["target"],
        old_session.reserved["target"]
    );
    let mut bootstrap = prepared.seal_bootstrap(f.public.consumers.path()).unwrap();
    assert_eq!(
        read_sealed(&mut bootstrap)["checkpoint"],
        serde_json::to_value(&f.early.checkpoint.head).unwrap()
    );
    let worker = f.start(prepared);
    for command in [
        CognitiveCheckpointCommand::BeginWrites,
        CognitiveCheckpointCommand::PreparePublication,
        CognitiveCheckpointCommand::CommitPublication,
    ] {
        f.exchange(command);
    }
    assert_ne!(f.current, f.early.checkpoint);
    let mut stopped = f.stop_service(worker);
    f.public._old.stop();
    old_session.stop();
    f.wait_expiry();
    let captured = f.capture_unchanged(&mut stopped);
    let stale = HostNotesRecoveryPredecessor {
        writer: captured.writer.clone(),
        writer_proof: captured.writer_proof.clone(),
        checkpoint: f.early.checkpoint.clone(),
        notes_target: captured.notes_target.clone(),
        notes_lifetime_ms: captured.notes_lifetime_ms,
    };
    let before = snapshot_original(&f.public.config, "root-authority-leases-v1");
    assert!(
        PreparedHostNotesRecovery::open(
            &f.public.config_path,
            &f.public.registration_path,
            f.public.owner_pidfd.try_clone().unwrap(),
            stale
        )
        .is_err()
    );
    assert_eq!(
        snapshot_original(&f.public.config, "root-authority-leases-v1"),
        before
    );
    f.public.previous = Some(captured);
    let mut recovery = f.public.open();
    let mut successor = ActualSession::spawn("capture-actual-new");
    let (producer, mut reader) = deployment();
    recovery
        .reserve_session(
            &f.public.profile_path,
            successor.channel.try_clone().unwrap(),
            successor.pidfd.try_clone().unwrap(),
            producer,
        )
        .unwrap();
    recovery.advance().unwrap();
    let after = snapshot_original(&f.public.config, "root-authority-leases-v1");
    recovery.advance().unwrap();
    let prepared = recovery.finish().unwrap();
    assert_eq!(
        read_sealed(&mut reader)["startup_release"]["target"],
        successor.reserved["target"]
    );
    let mut bootstrap = prepared.seal_bootstrap(f.public.consumers.path()).unwrap();
    assert_eq!(
        read_sealed(&mut bootstrap)["checkpoint"],
        serde_json::to_value(&after.1).unwrap()
    );
    assert_eq!(
        snapshot_original(&f.public.config, "root-authority-leases-v1"),
        after
    );
    assert_eq!(after.1.last_current, before.1.last_current);
    assert_eq!(after.1.counter, before.1.counter + 1);
    assert_eq!((&after.2, &after.3), (&before.2, &before.3));
    successor.assert_waiting();
    receipt(
        "capture-actual-sessions.json",
        serde_json::json!({
            "actual_old_session_reserved":true, "actual_old_session_reaped":true,
            "actual_new_session_reserved":true, "original_checkpoint_cycle_executed":true,
            "latest_current_captured":true, "early_bootstrap_rejected":true,
            "repeated_capture_refused":true, "public_recovery_repeated_unchanged":true,
            "successor_deployment_and_bootstrap_sealed":true,
            "old_binaries":old_session.binaries, "new_binaries":successor.binaries,
        }),
    );
}

#[tokio::test]
#[ignore = "explicit private Root bind and frozen controlled five-lane peer ELF"]
async fn root_notes_capture_refuses_noncurrent_and_foreign_heads() {
    for phase in ["dirty", "publishing", "fenced", "foreign_owner"] {
        let mut f = CaptureFixture::new(target()).await;
        let prepared = f.prepare_fixed_notes();
        let worker = f.start(prepared);
        if phase != "foreign_owner" {
            f.exchange(CognitiveCheckpointCommand::BeginWrites);
            if phase == "publishing" {
                f.exchange(CognitiveCheckpointCommand::PreparePublication);
            }
            if phase == "fenced" {
                f.exchange(CognitiveCheckpointCommand::FencePublisher);
            }
        }
        let mut stopped = f.stop_service(worker);
        f.public._old.stop();
        f.wait_expiry();
        if phase == "foreign_owner" {
            let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
                RootAuthorityDirectory::open(
                    f.public.config.checkpoint_state_dir.as_ref().unwrap(),
                )
                .unwrap(),
                STORE_OWNER.into(),
            )
            .unwrap();
            let before = store.load(STORE_OWNER).unwrap();
            let mut changed = before.clone();
            changed.owner_agent_id =
                AgentId::parse("00000000-0000-4000-8000-00000000c073").unwrap();
            store
                .compare_and_set(STORE_OWNER, &before, &changed)
                .unwrap();
        }
        f.refuse_unchanged(&mut stopped);
        f.refuse_unchanged(&mut stopped);
    }
    receipt(
        "capture-head-refusals.json",
        serde_json::json!({
            "dirty_refused":true, "publishing_refused":true, "fenced_refused":true,
            "foreign_owner_refused":true, "repeated_failure_unchanged":true,
        }),
    );
}

#[tokio::test]
#[ignore = "explicit private Root bind and frozen controlled five-lane peer ELF"]
async fn root_notes_capture_refuses_changed_policy_and_proof() {
    for drift in ["target", "lifetime", "proof"] {
        let mut f = CaptureFixture::new(target()).await;
        let prepared = f.prepare_fixed_notes();
        let worker = f.start(prepared);
        let mut stopped = f.stop_service(worker);
        f.public._old.stop();
        f.wait_expiry();
        // Deliberate hostile protected-state fixture injection, not another
        // authority owner or an alternate policy registration API.
        let store = HostAuthorityFrontierStore::<serde_json::Value>::open(
            RootAuthorityDirectory::open(&f.public.config.state_dir.join("issuer")).unwrap(),
            "local-final-use-issuer".into(),
        )
        .unwrap();
        let before = store.load("local-final-use-issuer").unwrap();
        let mut changed = before.clone();
        match drift {
            "target" => {
                let next = NotesTargetIdentity {
                    incarnation: "4".repeat(32),
                    ..target()
                };
                changed["policies"][0]["destination_id"] = next.destination_id().into();
                changed["policies"][0]["scope_sha256"] =
                    serde_json::to_value(next.scope_digest().into_array()).unwrap();
            }
            "lifetime" => changed["policies"][0]["lifetime_ms"] = 2_000.into(),
            "proof" => changed["writer_authorization"]["signature_hex"] = "00".repeat(64).into(),
            _ => unreachable!(),
        }
        store
            .compare_and_set("local-final-use-issuer", &before, &changed)
            .unwrap();
        f.refuse_unchanged(&mut stopped);
        f.refuse_unchanged(&mut stopped);
    }
    receipt(
        "capture-owner-refusals.json",
        serde_json::json!({
            "changed_target_refused":true, "changed_lifetime_refused":true,
            "changed_proof_refused":true, "repeated_failure_unchanged":true,
        }),
    );
}

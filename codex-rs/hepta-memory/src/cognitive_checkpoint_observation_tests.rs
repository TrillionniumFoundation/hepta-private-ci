//! Real owner/read-only SQLite and subprocess regressions. Protected receipt
//! bytes are explicit test-host fixtures, not a root-service qualification.

use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn observed_current_receipt_reads_the_peer_without_mutating_or_reopening_writes() {
    let fixture = ManagedFixture::new().await;
    fixture
        .sender()
        .retain_before_send(request())
        .await
        .unwrap();
    let expected = fixture.peer.receipt.lock().unwrap().clone();
    let commands = fixture.peer.commands.lock().unwrap().len();
    let anchor = fixture.writer.recovery_anchor().await.unwrap();
    assert_eq!(expected.head.phase, CognitiveCheckpointPhase::Current);
    assert_eq!(
        fixture.checkpoint.observed_current_receipt().await.unwrap(),
        expected
    );
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), expected);
    assert_eq!(fixture.peer.commands.lock().unwrap().len(), commands + 1);
    assert_eq!(
        fixture.peer.commands.lock().unwrap().last(),
        Some(&CognitiveCheckpointCommand::ReadHead)
    );
    assert_eq!(fixture.writer.recovery_anchor().await.unwrap(), anchor);
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert!(!fixture.writer.checkpoint_fenced());

    // Normal writer entry changes the original peer to Dirty. A cached prior
    // Current must not be exposed as a new authenticated observation.
    fixture
        .writer
        .admit("observed-current-dirty", "fixture", "{}")
        .await
        .unwrap();
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Dirty
    );
    let commands = fixture.peer.commands.lock().unwrap().len();
    assert!(fixture.checkpoint.observed_current_receipt().await.is_err());
    assert_eq!(fixture.peer.commands.lock().unwrap().len(), commands);
}

#[tokio::test]
async fn observed_current_receipt_rejects_an_actual_changed_head_and_keeps_its_coordinator() {
    let fixture = ManagedFixture::new().await;
    fixture
        .sender()
        .retain_before_send(request())
        .await
        .unwrap();
    let expected = fixture.peer.receipt.lock().unwrap().clone();
    {
        let mut peer = fixture.peer.receipt.lock().unwrap();
        peer.head.counter += 1;
        peer.token = token_for(&peer.head);
    }
    let commands = fixture.peer.commands.lock().unwrap().len();
    assert!(fixture.checkpoint.observed_current_receipt().await.is_err());
    assert_eq!(
        fixture.peer.commands.lock().unwrap().len(),
        commands + 1,
        "must read the actual peer instead of returning the cached receipt"
    );
    *fixture.peer.receipt.lock().unwrap() = expected.clone();
    assert_eq!(
        fixture.checkpoint.observed_current_receipt().await.unwrap(),
        expected,
        "a changed response must not replace the original coordinator receipt"
    );
    assert!(!fixture.store.commit_gate.commit_allowed());
}

async fn poll_without_mutating_current(fixture: &ManagedFixture, ticket: &ObjectiveSenderTicket) {
    let sender = fixture.sender();
    let before = fixture.peer.receipt.lock().unwrap().clone();
    assert_eq!(before.head.phase, CognitiveCheckpointPhase::Current);
    for _ in 0..3 {
        assert!(
            sender
                .retained_page(ObjectiveSenderRetainedPosition::Beginning)
                .await
                .is_ok()
        );
        assert!(sender.snapshot(ticket).await.is_ok());
        assert!(sender.snapshot_acknowledged(ticket).await.is_ok());
        assert!(sender.recover_pending(request()).await.is_ok());
        assert!(fixture.writer.status("observation-status").await.is_ok());
        assert!(
            fixture
                .writer
                .retained_operation("missing-operation")
                .await
                .unwrap()
                .is_none()
        );
        assert_eq!(
            fixture.store.recovery_anchor().await.unwrap(),
            before.head.last_current
        );
    }
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), before);
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert!(!fixture.writer.checkpoint_fenced());
}

#[tokio::test]
async fn protected_checkpoint_read_only_polling_preserves_current_and_rejects_writes() {
    let fixture = ManagedFixture::new().await;
    fixture
        .writer
        .admit("observation-status", "test", "{}")
        .await
        .unwrap();
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    poll_without_mutating_current(&fixture, &ticket).await;
    let before = fixture.peer.receipt.lock().unwrap().clone();
    let mut connections = Vec::new();
    for _ in 0..5 {
        connections.push(fixture.store.observation_pool().acquire().await.unwrap());
    }
    for mut connection in connections {
        // READONLY is an open flag, not a caller promise or mutable PRAGMA.
        sqlx::query("PRAGMA query_only=OFF")
            .execute(&mut *connection)
            .await
            .unwrap();
        sqlx::query("BEGIN IMMEDIATE")
            .execute(&mut *connection)
            .await
            .unwrap();
        assert!(
            sqlx::query("CREATE TABLE observer_write_probe (v INTEGER)")
                .execute(&mut *connection)
                .await
                .is_err()
        );
        sqlx::query("ROLLBACK")
            .execute(&mut *connection)
            .await
            .unwrap();
        connection.close().await.unwrap();
    }
    // Force a replacement; its physical open flags and rejecting commit hook
    // must be installed again before returning it to any observer.
    assert!(
        sqlx::query("CREATE TABLE observer_replacement_probe (v INTEGER)")
            .execute(fixture.store.observation_pool())
            .await
            .is_err()
    );
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), before);
    assert_eq!(
        fixture.store.recovery_anchor().await.unwrap(),
        before.head.last_current
    );
}

#[cfg(unix)]
mod crash {
    use super::*;
    use codex_hepta_paths::HeptaFleetRoot;
    use pretty_assertions::assert_eq;
    use std::fs::File;
    use std::path::PathBuf;
    use std::process::Child;
    use std::process::Command;
    use std::process::Stdio;

    const CHILD: &str = "production_writer::objective_sender::protected_checkpoint_tests::observation_tests::crash::protected_checkpoint_observation_subprocess_fixture";
    const ROOT_ENV: &str = "HEPTA_CHECKPOINT_OBSERVATION_TEST_ROOT";

    struct ChildGuard(Option<Child>);

    impl Drop for ChildGuard {
        fn drop(&mut self) {
            if let Some(mut child) = self.0.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }

    #[test]
    #[ignore = "controlled subprocess fixture; invoked by its parent with a private root"]
    fn protected_checkpoint_observation_subprocess_fixture() {
        let root = PathBuf::from(std::env::var_os(ROOT_ENV).expect("private fixture root"));
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(async {
                let fixture =
                    ManagedFixture::in_directory(tempfile::TempDir::new_in(&root).unwrap()).await;
                fixture
                    .writer
                    .admit("observation-status", "test", "{}")
                    .await
                    .unwrap();
                let sender = fixture.sender();
                let ticket = sender.retain_before_send(request()).await.unwrap();
                let receipt = fixture.peer.receipt.lock().unwrap().clone();
                // The harness retains the protocol peer's Current receipt before
                // any polling. It never derives a replacement cut from SQLite.
                let evidence = (fixture._temp.path().join("fleet"), receipt);
                let receipt_path = root.join("test-host-current.json");
                std::fs::write(&receipt_path, serde_json::to_vec(&evidence).unwrap()).unwrap();
                File::open(&receipt_path).unwrap().sync_all().unwrap();
                File::open(&root).unwrap().sync_all().unwrap();
                poll_without_mutating_current(&fixture, &ticket).await;
                std::fs::write(root.join("ready-for-kill"), b"ready").unwrap();
                // Keep the actual owner, pools and exclusive recovery guard live.
                // The parent kills this controlled process; no destructor closes
                // SQLite, releases its guard, or rewrites the retained receipt.
                loop {
                    std::thread::park();
                }
            });
    }

    #[tokio::test]
    async fn protected_checkpoint_current_recovers_after_polling_and_process_kill_without_replay() {
        let root = tempfile::TempDir::new().unwrap();
        let mut child = ChildGuard(Some(
            Command::new(std::env::current_exe().unwrap())
                .args(["--exact", CHILD, "--ignored", "--nocapture"])
                .env(ROOT_ENV, root.path())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .unwrap(),
        ));
        let deadline = tokio::time::Instant::now() + Duration::from_secs(30);
        while !root.path().join("ready-for-kill").exists() {
            if let Some(status) = child.0.as_mut().unwrap().try_wait().unwrap() {
                let output = child.0.take().unwrap().wait_with_output().unwrap();
                panic!(
                    "child exited before polling: {status}: {}",
                    String::from_utf8_lossy(&output.stderr)
                );
            }
            assert!(
                tokio::time::Instant::now() < deadline,
                "child did not reach its controlled kill point"
            );
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        child.0.as_mut().unwrap().kill().unwrap();
        assert!(
            !child
                .0
                .take()
                .unwrap()
                .wait_with_output()
                .unwrap()
                .status
                .success()
        );
        let (fleet, retained): (PathBuf, CognitiveCheckpointReceipt) = serde_json::from_slice(
            &std::fs::read(root.path().join("test-host-current.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(retained.head.phase, CognitiveCheckpointPhase::Current);
        let owner = crate::cognitive_test_support::agent_id(OWNER);
        let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
        let verifier = Arc::new(TestVerifier::new());
        let store = crate::CognitiveStore::open_with_recovery(
            &layout,
            crate::CognitiveRecoveryRequirement::ExactCurrentCut(&retained.head.last_current),
            &authority(&owner, 87),
            verifier.as_ref(),
        )
        .await
        .expect("original exact-cut recovery from the pre-poll retained test-host receipt");
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                authority(&owner, 87),
                verifier.clone(),
                LEASE,
                1,
            )
            .await
            .unwrap(),
        );
        let sender = writer
            .objective_sender(
                Arc::new(TestCheckpoint::new(verifier)),
                Duration::from_secs(2),
            )
            .unwrap();
        assert!(matches!(
            sender.retain_before_send(request()).await,
            Err(ObjectiveSenderError::AlreadyRetained)
        ));
        let recovered = sender.recover_pending(request()).await.unwrap();
        assert!(sender.snapshot(&recovered).await.is_ok());
        assert!(matches!(
            sender.mark_send_started(&recovered).await,
            Err(ObjectiveSenderError::SendPermissionUnavailable)
        ));
    }
}

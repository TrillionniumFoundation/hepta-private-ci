use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::*;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("fixture generation")
}

fn config(path: &std::path::Path) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(path.to_path_buf()).unwrap())
}

fn intent() -> PreparedIntent {
    PreparedIntent {
        operation_id: stable_id("operation:durable:1"),
        owner_id: stable_id("agent:owner:1"),
        scope_digest: Digest32::of_bytes(b"scope"),
        payload_digest: Digest32::of_bytes(b"payload"),
        destination: stable_id("cognitive.store"),
        expected_predecessor: Some(Digest32::of_bytes(b"predecessor")),
        owner_generation: generation(3),
        authority_epoch: generation(9),
    }
}

async fn prepare(store: &DurableOperationStore) -> DurableOperationRecord {
    store.prepare_intent(intent(), b"payload".to_vec()).await.unwrap()
}

#[tokio::test]
async fn prepare_rejects_payload_digest_drift_before_mutation() {
    let temp = TempDir::new().unwrap();
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .unwrap();
    assert_eq!(
        store
            .prepare_intent(intent(), b"payload-drift".to_vec())
            .await,
        Err(OperationError::InvalidDigest("operation payload binding"))
    );
    assert!(store.get(&intent().operation_id).await.unwrap().is_none());
}

async fn claim(store: &DurableOperationStore, lease_ms: i64) -> DispatchLease {
    store
        .claim_outbox(
            &intent().operation_id,
            generation(3),
            generation(9),
            &stable_id("worker:one"),
            lease_ms,
        )
        .await
        .unwrap()
}

#[tokio::test]
async fn prepare_commits_ledger_and_outbox_atomically_and_reopens_idempotently() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let store = DurableOperationStore::open(&sqlite).await.unwrap();
    sqlx::query(
        "CREATE TRIGGER fixture_outbox_failure BEFORE INSERT ON cross_owner_outbox
         BEGIN SELECT RAISE(ABORT, 'fixture disk failure'); END",
    )
    .execute(&store.pool)
    .await
    .unwrap();
    assert!(store.prepare_intent(intent(), b"payload".to_vec()).await.is_err());
    let ledger_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM operation_ledger")
        .fetch_one(&store.pool)
        .await
        .unwrap();
    let outbox_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cross_owner_outbox")
        .fetch_one(&store.pool)
        .await
        .unwrap();
    assert_eq!((ledger_count, outbox_count), (0, 0));
    sqlx::query("DROP TRIGGER fixture_outbox_failure")
        .execute(&store.pool)
        .await
        .unwrap();
    let prepared = prepare(&store).await;
    store.pool.close().await;

    let reopened = DurableOperationStore::open(&sqlite).await.unwrap();
    assert_eq!(prepare(&reopened).await, prepared);
    let mut drift = intent();
    drift.payload_digest = Digest32::of_bytes(b"changed");
    assert_eq!(
        reopened.prepare_intent(drift, b"changed".to_vec()).await,
        Err(OperationError::Conflict(intent().operation_id))
    );
}

#[tokio::test]
async fn expired_claim_takeover_uses_a_higher_fence_and_old_lease_stays_stale() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let first = DurableOperationStore::open(&sqlite).await.unwrap();
    let second = DurableOperationStore::open(&sqlite).await.unwrap();
    prepare(&first).await;
    let original = first
        .claim_outbox(
            &intent().operation_id,
            generation(3),
            generation(9),
            &stable_id("worker:old"),
            1,
        )
        .await
        .unwrap();
    assert_eq!(
        second
            .claim_outbox(
                &intent().operation_id,
                generation(3),
                generation(9),
                &stable_id("worker:new"),
                60_000,
            )
            .await,
        Err(OperationError::Unavailable)
    );
    tokio::time::sleep(Duration::from_millis(5)).await;
    let recovered = second
        .claim_outbox(
            &intent().operation_id,
            generation(3),
            generation(9),
            &stable_id("worker:new"),
            60_000,
        )
        .await
        .unwrap();
    assert!(recovered.fence() > original.fence());
    assert!(matches!(
        first.renew_outbox(&original, 60_000).await,
        Err(OperationError::StaleLease)
    ));
}

#[tokio::test]
async fn owner_handoff_fences_pending_workers_and_dispatched_work_requires_reconciliation() {
    let temp = TempDir::new().unwrap();
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .unwrap();
    prepare(&store).await;
    let old = claim(&store, 60_000).await;
    let handed = store
        .handoff_owner(
            &intent().operation_id,
            generation(3),
            generation(4),
            generation(10),
        )
        .await
        .unwrap();
    assert_eq!(handed.state, DurableOperationState::Pending);
    assert!(matches!(
        store
            .record_dispatch_started(&old, Digest32::of_bytes(b"dispatch"))
            .await,
        Err(OperationError::StaleGeneration)
    ));

    let new_lease = store
        .claim_outbox(
            &intent().operation_id,
            generation(4),
            generation(10),
            &stable_id("worker:new-owner"),
            60_000,
        )
        .await
        .unwrap();
    store
        .record_dispatch_started(&new_lease, Digest32::of_bytes(b"dispatch"))
        .await
        .unwrap();
    assert!(matches!(
        store
            .claim_outbox(
                &intent().operation_id,
                generation(4),
                generation(10),
                &stable_id("worker:blind-retry"),
                60_000,
            )
            .await,
        Err(OperationError::Unavailable)
    ));
    let handed_again = store
        .handoff_owner(
            &intent().operation_id,
            generation(4),
            generation(5),
            generation(11),
        )
        .await
        .unwrap();
    assert_eq!(handed_again.state, DurableOperationState::Indeterminate);
    let terminal = store
        .observe_terminal(
            &intent().operation_id,
            ReconciliationOutcome::Applied,
            Digest32::of_bytes(b"observed-terminal"),
            generation(5),
            generation(11),
        )
        .await
        .unwrap();
    assert_eq!(terminal.state, DurableOperationState::Applied);
}

#[tokio::test]
async fn transport_ack_is_not_terminal_and_terminal_replay_is_exact() {
    let temp = TempDir::new().unwrap();
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .unwrap();
    prepare(&store).await;
    let lease = claim(&store, 60_000).await;
    store
        .record_dispatch_started(&lease, Digest32::of_bytes(b"dispatch"))
        .await
        .unwrap();
    let ack = Digest32::of_bytes(b"transport-accepted");
    let acknowledged = store.acknowledge_transport(&lease, ack).await.unwrap();
    assert_eq!(acknowledged.state, DurableOperationState::Dispatched);
    assert_eq!(store.acknowledge_transport(&lease, ack).await.unwrap(), acknowledged);
    assert!(matches!(
        store
            .acknowledge_transport(&lease, Digest32::of_bytes(b"changed-ack"))
            .await,
        Err(OperationError::Conflict(_))
    ));

    let evidence = Digest32::of_bytes(b"terminal-evidence");
    let terminal = store
        .observe_terminal(
            &intent().operation_id,
            ReconciliationOutcome::Applied,
            evidence,
            generation(3),
            generation(9),
        )
        .await
        .unwrap();
    assert_eq!(
        store
            .observe_terminal(
                &intent().operation_id,
                ReconciliationOutcome::Applied,
                evidence,
                generation(3),
                generation(9),
            )
            .await
            .unwrap(),
        terminal
    );
    assert!(matches!(
        store
            .observe_terminal(
                &intent().operation_id,
                ReconciliationOutcome::NotApplied,
                evidence,
                generation(3),
                generation(9),
            )
            .await,
        Err(OperationError::Terminal)
    ));
}

#[tokio::test]
async fn lost_ack_remains_indeterminate_until_terminal_reconciliation() {
    let temp = TempDir::new().unwrap();
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .unwrap();
    prepare(&store).await;
    let lease = claim(&store, 60_000).await;
    store
        .record_dispatch_started(&lease, Digest32::of_bytes(b"dispatch"))
        .await
        .unwrap();

    let indeterminate = store
        .mark_indeterminate(&lease, Digest32::of_bytes(b"ack-lost"))
        .await
        .unwrap();
    assert_eq!(indeterminate.state, DurableOperationState::Indeterminate);
    assert!(matches!(
        store
            .claim_outbox(
                &intent().operation_id,
                generation(3),
                generation(9),
                &stable_id("worker:blind-retry"),
                60_000,
            )
            .await,
        Err(OperationError::Unavailable)
    ));

    let terminal = store
        .observe_terminal(
            &intent().operation_id,
            ReconciliationOutcome::Applied,
            Digest32::of_bytes(b"destination-observed-applied"),
            generation(3),
            generation(9),
        )
        .await
        .unwrap();
    assert_eq!(terminal.state, DurableOperationState::Applied);
}

#[tokio::test]
async fn terminal_outbox_compaction_preserves_ledger_identity_and_prevents_resurrection() {
    let temp = TempDir::new().unwrap();
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .unwrap();
    prepare(&store).await;
    let lease = claim(&store, 60_000).await;
    store
        .record_dispatch_started(&lease, Digest32::of_bytes(b"dispatch"))
        .await
        .unwrap();
    let terminal = store
        .observe_terminal(
            &intent().operation_id,
            ReconciliationOutcome::Applied,
            Digest32::of_bytes(b"terminal"),
            generation(3),
            generation(9),
        )
        .await
        .unwrap();
    sqlx::query(
        "UPDATE cross_owner_outbox SET terminal_at_ms = 1
         WHERE operation_id = ?",
    )
    .bind(intent().operation_id.as_str())
    .execute(&store.pool)
    .await
    .unwrap();
    assert_eq!(store.compact_terminal_outbox().await.unwrap(), 1);
    assert_eq!(store.prepare_intent(intent(), b"payload".to_vec()).await.unwrap(), terminal);
    let outbox_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cross_owner_outbox WHERE operation_id = ?",
    )
    .bind(intent().operation_id.as_str())
    .fetch_one(&store.pool)
    .await
    .unwrap();
    assert_eq!(outbox_count, 0);
}

#[tokio::test]
async fn missing_schema_guard_fails_closed_on_reopen() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let store = DurableOperationStore::open(&sqlite).await.unwrap();
    sqlx::query("DROP TRIGGER cross_owner_outbox_active_no_delete")
        .execute(&store.pool)
        .await
        .unwrap();
    store.pool.close().await;
    assert!(matches!(
        DurableOperationStore::open(&sqlite).await,
        Err(OperationError::Corrupt(_))
    ));
}

#[tokio::test]
#[ignore = "subprocess crash fixture"]
async fn crash_after_dispatch_child() {
    let home = std::path::PathBuf::from(
        std::env::var_os("HEPTA_OPERATIONS_CRASH_HOME").expect("crash home"),
    );
    let store = DurableOperationStore::open(&config(&home)).await.unwrap();
    prepare(&store).await;
    let lease = claim(&store, 60_000).await;
    store
        .record_dispatch_started(&lease, Digest32::of_bytes(b"dispatch-before-crash"))
        .await
        .unwrap();
    std::fs::write(home.join("dispatch-committed"), b"yes").unwrap();
    std::process::exit(73);
}

#[tokio::test]
async fn actual_process_crash_after_dispatch_reopens_without_resend() {
    let temp = TempDir::new().unwrap();
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "durable::tests::crash_after_dispatch_child",
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_OPERATIONS_CRASH_HOME", temp.path())
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(73));
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .unwrap();
    assert_eq!(
        store.get(&intent().operation_id).await.unwrap().unwrap().state,
        DurableOperationState::Dispatched
    );
    assert!(matches!(
        store
            .claim_outbox(
                &intent().operation_id,
                generation(3),
                generation(9),
                &stable_id("worker:retry"),
                60_000,
            )
            .await,
        Err(OperationError::Unavailable)
    ));
}

#[cfg(unix)]
mod final_use_vertical_slice {
    use std::collections::BTreeSet;
    use std::fs::OpenOptions;
    use std::io::ErrorKind;
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;

    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;

    struct DurableDestination {
        directory: TempDir,
    }

    impl DurableDestination {
        fn new() -> Self {
            Self {
                directory: TempDir::new().unwrap(),
            }
        }

        fn apply_once(&self, envelope: &DispatchEnvelope, payload: &[u8]) -> EffectObservation {
            assert_eq!(Digest32::of_bytes(payload), envelope.payload_digest);
            let path = self
                .directory
                .path()
                .join(format!("{}.receipt", envelope.semantic_digest));
            let receipt = format!(
                "{}\n{}\n{}\n",
                envelope.operation_id, envelope.semantic_digest, envelope.payload_digest
            );
            let mut stored = receipt.into_bytes();
            stored.extend_from_slice(payload);
            let evidence = Digest32::of_bytes(&stored);
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(mut file) => {
                    file.write_all(&stored).unwrap();
                    file.sync_all().unwrap();
                    std::fs::File::open(self.directory.path())
                        .unwrap()
                        .sync_all()
                        .unwrap();
                }
                Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                    assert_eq!(std::fs::read(&path).unwrap(), stored);
                }
                Err(error) => panic!("destination write failed: {error}"),
            }
            EffectObservation::Terminal {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: evidence,
            }
        }

        fn receipt_count(&self) -> usize {
            std::fs::read_dir(self.directory.path()).unwrap().count()
        }
    }

    fn authority_for(
        binding: &codex_hepta_contracts::FinalUseBinding,
    ) -> (FinalUseAuthority, SignedFinalUseGrant, TempDir) {
        let signer = SigningKey::from_bytes(&[47; 32]);
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 9,
            grant_id: "operation-grant".into(),
            nonce: [5; 32],
            binding: binding.clone(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let signature = signer.sign(&grant.signing_bytes().unwrap()).to_bytes().to_vec();
        let directory = TempDir::new().unwrap();
        std::fs::set_permissions(
            directory.path(),
            std::fs::Permissions::from_mode(0o700),
        )
        .unwrap();
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "security-owner".into(),
            signer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .unwrap();
        (
            authority,
            SignedFinalUseGrant { grant, signature },
            directory,
        )
    }

    #[tokio::test]
    async fn dispatch_once_consumes_final_use_at_the_effect_boundary() {
        let temp = TempDir::new().unwrap();
        let store = DurableOperationStore::open(&config(temp.path()))
            .await
            .unwrap();
        prepare(&store).await;
        let lease = claim(&store, 60_000).await;
        let destination = DurableDestination::new();
        let binding = lease.envelope().final_use_binding();
        let (authority, grant, _authority_home) = authority_for(&binding);
        let terminal = store
            .dispatch_once(
                &lease,
                Digest32::of_bytes(b"dispatch"),
                &authority,
                &grant,
                |envelope, payload| destination.apply_once(envelope, payload),
            )
            .await
            .unwrap();
        assert_eq!(terminal.state, DurableOperationState::Applied);
        assert_eq!(destination.receipt_count(), 1);

        // Destination-owned semantic dedupe is independent of source-side
        // dispatch suppression: observing the same semantic identity again is
        // idempotent and does not create a second terminal effect.
        assert!(matches!(
            destination.apply_once(lease.envelope(), lease.payload()),
            EffectObservation::Terminal {
                outcome: ReconciliationOutcome::Applied,
                ..
            }
        ));
        assert_eq!(destination.receipt_count(), 1);
    }
}

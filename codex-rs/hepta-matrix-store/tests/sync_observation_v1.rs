use std::fs;
use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncDecisionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixSyncResultV2;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use sqlx::SqlitePool;
use tempfile::TempDir;

use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixEventId;
use codex_hepta_matrix_store::MatrixRoomId;
use codex_hepta_matrix_store::MatrixSnapshot;
use codex_hepta_matrix_store::MatrixSyncCheckpoint;
use codex_hepta_matrix_store::MatrixSyncUnchangedRequestV1;
use codex_hepta_matrix_store::MatrixSyncUnchangedResultV1;
use codex_hepta_matrix_store::MatrixUserId;
use codex_hepta_matrix_store::RoomBindingDraft;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

struct Fixture {
    _temp: TempDir,
    layout: HeptaAgentLayout,
    store: MatrixDurableStore,
    pool: SqlitePool,
    room: MatrixRoomId,
}

impl Fixture {
    async fn new() -> TestResult<Self> {
        let temp = TempDir::new()?;
        let root = temp.path().join("fleet");
        fs::create_dir(&root)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let layout = HeptaFleetRoot::parse(root.canonicalize()?)?
            .layout()
            .agent(&agent);
        let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
        let room = MatrixRoomId::parse("!observation:example.test")?;
        store
            .bind_room(&RoomBindingDraft {
                room_id: room.clone(),
                agent_user_id: MatrixUserId::parse("@agent:example.test")?,
                expected_revision: None,
                generation: 1,
                changed_at_ms: 1,
            })
            .await?;
        // The normal shim opens this test's already initialized temporary DB.
        // This precondition is fixture setup, not a path-based recovery guard.
        let path = store.path();
        assert!(fs::symlink_metadata(path)?.file_type().is_file());
        let parent = path
            .parent()
            .ok_or_else(|| std::io::Error::other("fixture parent missing"))?;
        let parent = AbsolutePathBuf::try_from(parent.to_path_buf())?;
        let pool = SqliteConfig::new_for_testing(parent)
            .open_durable_evidence_pool(path)
            .await?;
        Ok(Self {
            _temp: temp,
            layout,
            store,
            pool,
            room,
        })
    }

    fn request(&self) -> MatrixSyncUnchangedRequestV1 {
        MatrixSyncUnchangedRequestV1 {
            owner_agent_id: self.store.owner_agent_id().clone(),
            checkpoint_revision: 1,
            checkpoint_generation: 1,
            expected_next_batch: "s1".to_string(),
            observed_next_batch: "s1".to_string(),
        }
    }

    fn initial_decision(&self) -> TestResult<MatrixSyncDecisionV2> {
        Ok(MatrixSyncDecisionV2::Commit {
            batch: MatrixSyncBatchV2 {
                schema_version: 2,
                operation_id: "initial".to_string(),
                checkpoint_revision: 1,
                checkpoint_generation: 1,
                expected_next_batch: None,
                next_batch: "s1".to_string(),
                observed_at_ms: 20,
                mutations: vec![MatrixSyncMutationV2 {
                    source_event_id: MatrixEventId::parse("$initial")?,
                    room_id: self.room.clone(),
                    sender: MatrixUserId::parse("@owner:example.test")?,
                    binding_revision: 1,
                    generation: 1,
                    origin_server_ts_ms: 10,
                    received_at_ms: 11,
                    body: MatrixSyncMutationBodyV2::Timeline {
                        event_type: "m.room.message".to_string(),
                        payload: b"preserved".to_vec(),
                    },
                }],
            },
        })
    }
}

async fn evidence(
    store: &MatrixDurableStore,
    pool: &SqlitePool,
) -> TestResult<(
    MatrixSnapshot,
    Option<MatrixSyncCheckpoint>,
    Vec<(String, i64)>,
)> {
    let counters = sqlx::query_as(
        "SELECT 'mutations', COUNT(*) FROM matrix_sync_mutations_v2
         UNION ALL SELECT 'decisions', COUNT(*) FROM matrix_sync_decisions_v2
         UNION ALL SELECT 'outcomes', COUNT(*) FROM matrix_sync_decision_outcomes_v2
         UNION ALL SELECT 'changes', COUNT(*) FROM change_log
         UNION ALL SELECT 'sequence.' || name, seq FROM sqlite_sequence
         ORDER BY 1",
    )
    .fetch_all(pool)
    .await?;
    Ok((
        store.snapshot(/*now_ms*/ 100, /*limit*/ 100).await?,
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?,
        counters,
    ))
}

#[tokio::test]
async fn repeated_observations_preserve_all_durable_evidence_and_survive_reopen() -> TestResult {
    let fixture = Fixture::new().await?;
    let decision = fixture.initial_decision()?;
    let committed = fixture.store.apply_sync_decision_v2(&decision).await?;
    let before = evidence(&fixture.store, &fixture.pool).await?;
    let expected = MatrixSyncUnchangedResultV1::Verified {
        checkpoint: before.1.clone().expect("checkpoint"),
    };
    for _ in 0..32 {
        assert_eq!(
            fixture
                .store
                .verify_unchanged_sync_v1(&fixture.request())
                .await?,
            expected
        );
    }
    assert_eq!(evidence(&fixture.store, &fixture.pool).await?, before);
    assert_eq!(
        fixture.store.lookup_sync_decision_v2("initial").await?,
        Some(committed)
    );
    fixture.store.close().await;
    let reopened =
        MatrixDurableStore::open(&fixture.layout, MatrixDurableConfig::default()).await?;
    assert_eq!(
        reopened
            .verify_unchanged_sync_v1(&fixture.request())
            .await?,
        expected
    );
    assert_eq!(evidence(&reopened, &fixture.pool).await?, before);
    reopened.close().await;
    fixture.pool.close().await;
    Ok(())
}

#[tokio::test]
async fn absent_stale_or_malformed_caller_fences_never_become_unchanged_success() -> TestResult {
    let fixture = Fixture::new().await?;
    let before = evidence(&fixture.store, &fixture.pool).await?;
    assert_eq!(
        fixture
            .store
            .verify_unchanged_sync_v1(&fixture.request())
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(evidence(&fixture.store, &fixture.pool).await?, before);
    fixture
        .store
        .apply_sync_decision_v2(&fixture.initial_decision()?)
        .await?;
    let before = evidence(&fixture.store, &fixture.pool).await?;
    let mut rejected = vec![(fixture.request(), MatrixDurableError::Invalid); 8];
    rejected[0].0.owner_agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")?;
    rejected[0].1 = MatrixDurableError::AccessDenied;
    rejected[1].0.checkpoint_revision = 2;
    rejected[1].1 = MatrixDurableError::AccessDenied;
    rejected[2].0.checkpoint_generation = 2;
    rejected[2].1 = MatrixDurableError::AccessDenied;
    rejected[3].0.expected_next_batch = "stale".to_string();
    rejected[3].0.observed_next_batch = "stale".to_string();
    rejected[3].1 = MatrixDurableError::Conflict;
    rejected[4].0.observed_next_batch = "changed".to_string();
    rejected[5].0.checkpoint_revision = 0;
    rejected[6].0.expected_next_batch.clear();
    rejected[7].0.observed_next_batch = "x".repeat(4097);
    for (request, error) in rejected {
        assert_eq!(
            fixture.store.verify_unchanged_sync_v1(&request).await,
            Err(error)
        );
        assert_eq!(evidence(&fixture.store, &fixture.pool).await?, before);
    }
    // A once-current caller token cannot reuse an earlier verified observation.
    let MatrixSyncDecisionV2::Commit { mut batch } = fixture.initial_decision()? else {
        unreachable!()
    };
    batch.operation_id = "advance".to_string();
    batch.expected_next_batch = Some("s1".to_string());
    batch.next_batch = "s2".to_string();
    batch.mutations.clear();
    fixture
        .store
        .apply_sync_decision_v2(&MatrixSyncDecisionV2::Commit { batch })
        .await?;
    let before = evidence(&fixture.store, &fixture.pool).await?;
    assert_eq!(
        fixture
            .store
            .verify_unchanged_sync_v1(&fixture.request())
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(evidence(&fixture.store, &fixture.pool).await?, before);
    fixture.store.close().await;
    fixture.pool.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn observation_serializes_after_a_checkpoint_writer_and_rejects_the_old_token() -> TestResult
{
    let fixture = Fixture::new().await?;
    fixture
        .store
        .apply_sync_decision_v2(&fixture.initial_decision()?)
        .await?;
    // The hostile writer has a separate pool; the owner already has a free
    // connection from its initial commit, so a deferred WAL read could pass.
    let mut writer = fixture.pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query("UPDATE matrix_sync_checkpoint SET next_batch = 's2', updated_at_ms = 30 WHERE singleton = 1")
        .execute(&mut *writer).await?;
    let request = fixture.request();
    let observer_store = fixture.store.clone();
    let (sender, receiver) = mpsc::channel();
    let observer = tokio::spawn(async move {
        sender
            .send(observer_store.verify_unchanged_sync_v1(&request).await)
            .expect("receiver");
    });
    assert!(matches!(
        receiver.recv_timeout(Duration::from_millis(100)),
        Err(mpsc::RecvTimeoutError::Timeout)
    ));
    writer.commit().await?;
    assert_eq!(
        receiver.recv_timeout(Duration::from_secs(2))?,
        Err(MatrixDurableError::Conflict)
    );
    observer.await?;
    let mut current = fixture.request();
    current.expected_next_batch = "s2".to_string();
    current.observed_next_batch = "s2".to_string();
    let checkpoint = fixture
        .store
        .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
        .await?
        .expect("advanced checkpoint");
    assert_eq!(
        fixture.store.verify_unchanged_sync_v1(&current).await?,
        MatrixSyncUnchangedResultV1::Verified { checkpoint }
    );
    fixture.store.close().await;
    fixture.pool.close().await;
    Ok(())
}

#[tokio::test]
async fn every_ordinary_journal_ceiling_refuses_idle_readiness_without_breaking_v2_replay()
-> TestResult {
    // Test-only hostile fixture writers operate exclusively on each owned
    // temporary database. They are not a production recovery or cleanup path.
    for boundary in [
        "decision-reserve",
        "decision-full",
        "mutation-reserve",
        "outcome-reserve",
    ] {
        let fixture = Fixture::new().await?;
        let initial = fixture.initial_decision()?;
        let committed = fixture.store.apply_sync_decision_v2(&initial).await?;
        match boundary {
            "decision-reserve" | "decision-full" => {
                let seq = if boundary == "decision-reserve" {
                    61_440_i64
                } else {
                    65_536
                };
                sqlx::query(
                    "INSERT INTO matrix_sync_decisions_v2 (
                    decision_seq, operation_id, decision_kind, decision_sha256, schema_version,
                    checkpoint_revision, checkpoint_generation, expected_next_batch, next_batch,
                    retained_next_batch, outcome_count
                 ) VALUES (?, 'capacity', 'cancel', ?, 2, 1, 1, 's1', NULL, 's1', 0)",
                )
                .bind(seq)
                .bind("0".repeat(64))
                .execute(&fixture.pool)
                .await?;
            }
            "mutation-reserve" => {
                sqlx::query("INSERT INTO matrix_sync_mutations_v2 (
                    ledger_seq, source_event_id, room_id, sender_user_id, mutation_kind,
                    mutation_sha256, binding_revision, generation, origin_server_ts_ms, received_at_ms
                 ) VALUES (61441, '$capacity', ?, '@owner:example.test', 'timeline', ?, 1, 1, 10, 11)")
                    .bind(fixture.room.as_str()).bind("0".repeat(64))
                    .execute(&fixture.pool).await?;
            }
            "outcome-reserve" => {
                // A complete second decision keeps the native startup verifier
                // satisfied while its sequence records lifetime budget usage.
                sqlx::query(
                    "INSERT INTO matrix_sync_decisions_v2 (
                    decision_seq, operation_id, decision_kind, decision_sha256, schema_version,
                    checkpoint_revision, checkpoint_generation, expected_next_batch, next_batch,
                    retained_next_batch, outcome_count
                 ) VALUES (2, 'capacity', 'commit', ?, 2, 1, 1, 's1', 's1', NULL, 1)",
                )
                .bind("0".repeat(64))
                .execute(&fixture.pool)
                .await?;
                sqlx::query(
                    "INSERT INTO matrix_sync_decision_outcomes_v2 (
                    outcome_seq, decision_seq, outcome_index, source_event_id, disposition
                 ) VALUES (33550337, 2, 0, '$initial', 'duplicate')",
                )
                .execute(&fixture.pool)
                .await?;
            }
            _ => unreachable!(),
        }
        let before = evidence(&fixture.store, &fixture.pool).await?;
        assert_eq!(
            fixture
                .store
                .verify_unchanged_sync_v1(&fixture.request())
                .await?,
            MatrixSyncUnchangedResultV1::CapacityExhausted
        );
        assert_eq!(
            fixture.store.apply_sync_decision_v2(&initial).await?,
            committed
        );
        assert_eq!(evidence(&fixture.store, &fixture.pool).await?, before);
        if boundary != "decision-full" {
            let MatrixSyncDecisionV2::Commit { mut batch } = fixture.initial_decision()? else {
                unreachable!()
            };
            batch.operation_id = "reserved-deletion".to_string();
            batch.expected_next_batch = Some("s1".to_string());
            batch.next_batch = "s2".to_string();
            batch.mutations[0].source_event_id = MatrixEventId::parse("$redaction")?;
            batch.mutations[0].body = MatrixSyncMutationBodyV2::Redaction {
                target_event_id: MatrixEventId::parse("$missing")?,
            };
            assert!(matches!(
                fixture
                    .store
                    .apply_sync_decision_v2(&MatrixSyncDecisionV2::Commit { batch })
                    .await?,
                MatrixSyncResultV2::Committed { .. }
            ));
        }
        fixture.store.close().await;
        let reopened =
            MatrixDurableStore::open(&fixture.layout, MatrixDurableConfig::default()).await?;
        assert_eq!(reopened.apply_sync_decision_v2(&initial).await?, committed);
        reopened.close().await;
        fixture.pool.close().await;
    }
    Ok(())
}

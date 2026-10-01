use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::SqlitePool;
use tempfile::TempDir;

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::cognitive_model::MAX_SOURCE_BYTES;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

async fn raw_budget_pool(temp: &TempDir) -> SqlitePool {
    let home = AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute SQLite home");
    SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(&temp.path().join("budget.sqlite3"))
        .await
        .expect("raw budget fixture pool")
}

fn assert_budget_error(result: Result<(), CognitiveStoreError>) {
    assert!(
        matches!(result, Err(CognitiveStoreError::Invalid(message)) if message.contains("startup row/byte bounds")),
        "oversized logical state must be rejected before materialization"
    );
}

async fn logical_counts(store: &CognitiveStore) -> Vec<(&'static str, i64)> {
    let mut transaction = store.pool.begin().await.expect("count snapshot");
    let verified = super::super::schema::verify_schema(&mut transaction)
        .await
        .expect("compiled count schema");
    let mut counts = Vec::with_capacity(verified.tables.len());
    for table in verified.tables {
        // The names come exclusively from exact compiled-schema admission.
        let mut query = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT COUNT(*) FROM \"");
        query.push(table).push("\"");
        let count = query
            .build_query_scalar::<i64>()
            .fetch_one(&mut *transaction)
            .await
            .expect("logical table count");
        counts.push((table, count));
    }
    transaction.commit().await.expect("close count snapshot");
    counts
}

#[tokio::test]
async fn legal_source_appends_stop_atomically_at_reopen_budget_and_replay_at_capacity() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(90);
    let owner_layout = layout(&temp, &owner);
    let first = CognitiveStore::open(&owner_layout)
        .await
        .expect("first writer");
    let second = CognitiveStore::open(&owner_layout)
        .await
        .expect("independent second writer");
    let access = CognitiveAccess::agent_private(owner);
    let mut draft = source(CognitiveScope::AgentPrivate, "capacity-0", "evidence");
    // Every payload obeys the public source API's actual 1 MiB ceiling. Do not
    // lower the production budget or bypass its write path to reach capacity.
    draft.content = vec![b'x'; MAX_SOURCE_BYTES];
    let max_attempts = usize::try_from(MAX_BYTES).expect("positive byte budget") / MAX_SOURCE_BYTES;
    let mut accepted = 0_i64;
    let mut last_committed = None;
    let mut rejected = false;
    for index in 0..=max_attempts {
        draft.event_key = format!("capacity-{index}");
        let writer = if index % 2 == 0 { &first } else { &second };
        match writer.append_source(&access, &draft).await {
            Ok(receipt) => {
                accepted += 1;
                last_committed = Some((draft.clone(), receipt));
            }
            Err(error) => {
                assert_budget_error(Err(error));
                rejected = true;
                break;
            }
        }
    }
    assert!(
        rejected,
        "legal writes must stop before crossing the startup budget"
    );
    assert!(accepted > 0, "capacity fixture must commit ordinary writes");
    // Fill the residual byte budget with legal Memory-sized sources so the
    // sealed composite below reaches the budget gate with a valid exact
    // Source/Memory binding, rather than failing its input-size contract.
    draft.content = vec![b'x'; crate::cognitive_model::MAX_MEMORY_BYTES];
    for index in 0..=max_attempts {
        draft.event_key = format!("capacity-residual-{index}");
        let writer = if index % 2 == 0 { &first } else { &second };
        match writer.append_source(&access, &draft).await {
            Ok(receipt) => {
                accepted += 1;
                last_committed = Some((draft.clone(), receipt));
            }
            Err(error) => {
                assert_budget_error(Err(error));
                break;
            }
        }
        assert!(index < max_attempts, "residual budget must be exhausted");
    }
    let counts = logical_counts(&first).await;
    assert_eq!(
        counts.iter().find(|(table, _)| *table == "source_ledger"),
        Some(&("source_ledger", accepted)),
        "rejected append must leave no extra source row"
    );
    let anchor = first
        .recovery_anchor()
        .await
        .expect("admitted boundary cut");
    let (last_draft, last_receipt) = last_committed.expect("committed source");
    assert_eq!(
        second
            .append_source(&access, &last_draft)
            .await
            .expect("exact replay at capacity"),
        last_receipt
    );
    assert_budget_error(second.append_source(&access, &draft).await.map(|_| ()));
    assert_eq!(logical_counts(&first).await, counts);
    assert_eq!(
        second
            .recovery_anchor()
            .await
            .expect("unchanged boundary cut"),
        anchor,
        "rejected retry and exact replay must preserve all owner data"
    );
    first.pool.close().await;
    second.pool.close().await;
    drop(first);
    drop(second);
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("all acknowledged appends must remain reopenable");
    assert_eq!(logical_counts(&reopened).await, counts);
    assert_eq!(
        reopened
            .append_source(&access, &last_draft)
            .await
            .expect("exact replay after reopen"),
        last_receipt
    );
    // The sealed production composite must reject the same exhaustion only
    // after rolling back source, Memory, facts, FTS and operation provenance.
    let authority = crate::ProductionAuthorityLease::from_verified_parts(
        reopened.owner_agent_id().clone(),
        codex_hepta_contracts::Sha256Digest::for_bytes(b"capacity qualification grant"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_secs()
            + 3_600,
        crate::ProductionAuthorityToken::from_verified_bytes(
            b"capacity qualification token".to_vec(),
        )
        .expect("token"),
    )
    .expect("qualification authority");
    let verifier = |_authority: &crate::ProductionAuthorityLease,
                    _owner: &codex_hepta_contracts::AgentId| Ok(());
    let writer = std::sync::Arc::new(
        crate::ProductionDurableWriter::open_with_live_verifier(
            reopened.clone(),
            authority,
            std::sync::Arc::new(verifier),
            "capacity:production",
            /*generation*/ 1,
        )
        .await
        .expect("live writer within remaining capacity"),
    );
    let capability = writer
        .cognitive_mutation_capability()
        .expect("sealed capability");
    let before_production = logical_counts(&reopened).await;
    let before_anchor = reopened
        .recovery_anchor()
        .await
        .expect("production boundary anchor");
    let memory = crate::MemoryDraft {
        stable_key: "capacity:production-memory".to_string(),
        revision: crate::MemoryRevisionDraft {
            scope: CognitiveScope::AgentPrivate,
            content: "x".repeat(crate::cognitive_model::MAX_MEMORY_BYTES),
            verification: crate::MemoryVerification::Verified,
            lifecycle: crate::MemoryLifecycleState::Active,
            valid_from_unix_seconds: 100,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        },
    };
    let facts = crate::KgFactSetDraft::default();
    for _ in 0..2 {
        let result = crate::ProductionCognitiveMutation::remember_with_kg(
            &capability,
            &access,
            &draft,
            &memory,
            &facts,
        )
        .await;
        assert!(matches!(result,
            Err(crate::ProductionCognitiveMutationError::Store(CognitiveStoreError::Invalid(message)))
            if message.contains("startup row/byte bounds")
        ));
        assert_eq!(logical_counts(&reopened).await, before_production);
        assert_eq!(
            reopened
                .recovery_anchor()
                .await
                .expect("rejected composite anchor"),
            before_anchor
        );
    }
    drop(capability);
    drop(writer);
    reopened.pool.close().await;
    drop(reopened);
    let after_production = CognitiveStore::open(&owner_layout)
        .await
        .expect("rejected production mutation preserves reopen");
    assert_eq!(logical_counts(&after_production).await, before_production);
    assert_eq!(
        after_production
            .recovery_anchor()
            .await
            .expect("reopened production anchor"),
        before_anchor
    );
    after_production.pool.close().await;
}

#[tokio::test]
async fn admission_accumulates_rows_and_bytes_across_tables() {
    let temp = TempDir::new().expect("temp dir");
    let pool = raw_budget_pool(&temp).await;
    let mut connection = pool.acquire().await.expect("connection");
    // Small aggregate fixtures isolate admission without allocating the
    // production byte budget. Names remain from the compiled table inventory.
    sqlx::query(
        "CREATE TABLE cognitive_local_events(payload BLOB);
         CREATE TABLE cognitive_local_outbox(payload BLOB);
         INSERT INTO cognitive_local_events VALUES (zeroblob(100));
         INSERT INTO cognitive_local_outbox VALUES (zeroblob(100));",
    )
    .execute(&mut *connection)
    .await
    .expect("seed tables");
    let tables = ["cognitive_local_events", "cognitive_local_outbox"];
    assert_budget_error(
        verify_tables(
            &mut connection,
            &tables,
            Budget {
                remaining_rows: 1,
                remaining_bytes: 4096,
            },
        )
        .await,
    );
    assert_budget_error(
        verify_tables(
            &mut connection,
            &tables,
            Budget {
                remaining_rows: 4,
                remaining_bytes: 200,
            },
        )
        .await,
    );
    verify_tables(
        &mut connection,
        &tables,
        Budget {
            remaining_rows: 2,
            remaining_bytes: 4096,
        },
    )
    .await
    .expect("exact row budget must remain usable");
    drop(connection);
    pool.close().await;
}

#[tokio::test]
async fn admission_rejects_production_row_limit_before_fetching_history() {
    let temp = TempDir::new().expect("temp dir");
    let pool = raw_budget_pool(&temp).await;
    let mut connection = pool.acquire().await.expect("connection");
    sqlx::query(
        "CREATE TABLE cognitive_local_events(payload BLOB);
         WITH RECURSIVE rows(n) AS (
             SELECT 1 UNION ALL SELECT n + 1 FROM rows WHERE n < 262145
         ) INSERT INTO cognitive_local_events SELECT NULL FROM rows;",
    )
    .execute(&mut *connection)
    .await
    .expect("seed oversized row count");
    assert_budget_error(
        verify_tables(
            &mut connection,
            &["cognitive_local_events"],
            Budget::default(),
        )
        .await,
    );
    drop(connection);
    pool.close().await;
}

#[tokio::test]
async fn admission_rejects_single_oversized_row_before_fetching_payload() {
    let temp = TempDir::new().expect("temp dir");
    let pool = raw_budget_pool(&temp).await;
    let mut connection = pool.acquire().await.expect("connection");
    sqlx::query("CREATE TABLE cognitive_local_events(payload BLOB)")
        .execute(&mut *connection)
        .await
        .expect("table");
    sqlx::query("INSERT INTO cognitive_local_events VALUES (zeroblob(?))")
        .bind(MAX_ROW_BYTES)
        .execute(&mut *connection)
        .await
        .expect("seed oversized framed row");
    assert_budget_error(
        verify_tables(
            &mut connection,
            &["cognitive_local_events"],
            Budget::default(),
        )
        .await,
    );
    drop(connection);
    pool.close().await;
}

#[tokio::test]
async fn ordinary_open_admits_budget_before_integrity_and_content_materialization() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(88);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    store
        .append_source(
            &CognitiveAccess::agent_private(owner.clone()),
            &source(CognitiveScope::AgentPrivate, "budget", "evidence"),
        )
        .await
        .expect("source");
    // Save the exact guard from an admitted compiled schema before tampering.
    let guard: String =
        sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = 'source_ledger_no_update'")
            .fetch_one(&store.pool)
            .await
            .expect("compiled guard");
    let mut transaction = store.pool.begin().await.expect("tamper transaction");
    sqlx::query(
        "DROP TRIGGER source_ledger_no_update;
         PRAGMA ignore_check_constraints = ON;
         UPDATE source_ledger SET content = zeroblob(2097152);
         PRAGMA ignore_check_constraints = OFF;",
    )
    .execute(&mut *transaction)
    .await
    .expect("oversized owner row");
    sqlx::query(sqlx::AssertSqlSafe(guard.as_str()))
        .execute(&mut *transaction)
        .await
        .expect("restore exact admitted immutable guard");
    transaction.commit().await.expect("commit tamper");
    store.pool.close().await;
    drop(store);
    match CognitiveStore::open(&layout(&temp, &owner)).await {
        Err(error) => assert_budget_error(Err(error)),
        Ok(_) => panic!("oversized owner state must not reopen"),
    }
}

#[tokio::test]
async fn each_journal_validator_admits_its_own_snapshot_before_loading_chains() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(89);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let mut connection = store.pool.acquire().await.expect("connection");
    sqlx::query("PRAGMA ignore_check_constraints = ON")
        .execute(&mut *connection)
        .await
        .expect("allow oversized adversarial payload");
    sqlx::query(
        "INSERT INTO cognitive_local_events (
            lease_id, event_sequence, event_id, occurrence_key, owner_agent_id,
            generation, fencing_token, event_kind, payload_json, payload_sha256,
            previous_sha256, event_sha256, recorded_at_unix_seconds
         ) VALUES ('budget-lease', 1, 'budget-event', 'budget-occurrence', ?,
            1, 'budget-fence', 'admitted', CAST(zeroblob(2097152) AS TEXT), ?, ?, ?, 0)",
    )
    .bind(owner.as_str())
    .bind("0".repeat(64))
    .bind("0".repeat(64))
    .bind("0".repeat(64))
    .execute(&mut *connection)
    .await
    .expect("oversized event in exact compiled schema");
    sqlx::query("PRAGMA ignore_check_constraints = OFF")
        .execute(&mut *connection)
        .await
        .expect("restore check policy");
    drop(connection);
    assert_budget_error(
        crate::local_lease_outbox::verify_local_lease_outbox(&store.pool, &owner).await,
    );
    assert_budget_error(
        crate::logical_turn_registry::verify_logical_turn_registry(&store.pool, &owner).await,
    );
    assert_budget_error(
        crate::local_compact_executor::verify_local_compact_events(&store.pool, &owner).await,
    );
    store.pool.close().await;
}

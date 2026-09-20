use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::GOVERNANCE_SCHEMA_VERSION;
use codex_hepta_contracts::GovernanceDecision;
use codex_hepta_contracts::GovernanceDecisionRecord;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::GovernanceReceipt;
use codex_hepta_contracts::HandlerOutcome;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_contracts::PolicyStamp;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::ToolAction;
use codex_hepta_contracts::ToolActionSource;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn action_for(call_id: &str, payload: &[u8]) -> ToolAction {
    ToolAction {
        schema_version: GOVERNANCE_SCHEMA_VERSION,
        action_id: ActionId::for_tool_call("thread-1", "turn-1", call_id),
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        call_id: call_id.to_string(),
        tool_name: "exec_command".to_string(),
        source: ToolActionSource::Direct,
        payload_sha256: Sha256Digest::for_bytes(payload),
    }
}

fn decision(phase: PolicyPhase, payload: &[u8]) -> GovernanceDecisionRecord {
    decision_for("call-1", phase, payload)
}

fn decision_for(call_id: &str, phase: PolicyPhase, payload: &[u8]) -> GovernanceDecisionRecord {
    GovernanceDecisionRecord::new(
        action_for(call_id, payload),
        phase,
        GovernanceMode::Shadow,
        PolicyStamp::new("hepta.test.v1", 1, b"allow"),
        GovernanceDecision::Allow,
    )
}

#[tokio::test]
async fn append_is_idempotent_and_survives_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let admission = decision(PolicyPhase::Admission, b"original");
    let authorization = decision(PolicyPhase::Authorization, b"effective");
    let receipt = GovernanceReceipt::new(
        admission.clone(),
        Some(authorization.clone()),
        true,
        HandlerOutcome::HandlerCompleted {
            reported_success: true,
        },
    );

    assert_eq!(
        store.append_decision(&admission).await.expect("admission"),
        AppendDisposition::Inserted
    );
    assert_eq!(
        store.append_decision(&admission).await.expect("replay"),
        AppendDisposition::AlreadyPresent
    );
    assert_eq!(
        store
            .append_decision(&authorization)
            .await
            .expect("authorization"),
        AppendDisposition::Inserted
    );
    assert_eq!(store.pending_action_count().await.expect("pending"), 1);
    assert_eq!(
        store.append_receipt(&receipt).await.expect("receipt"),
        AppendDisposition::Inserted
    );
    assert_eq!(store.pending_action_count().await.expect("terminal"), 0);
    drop(store);

    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen evidence");
    let stored = reopened
        .get_receipt(&receipt.receipt_id)
        .await
        .expect("read receipt")
        .expect("stored receipt");
    assert_eq!(stored.receipt, receipt);
}

#[tokio::test]
async fn conflicting_identity_never_overwrites_evidence() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let original = decision(PolicyPhase::Admission, b"first");
    let conflict = decision(PolicyPhase::Admission, b"second");

    store
        .append_decision(&original)
        .await
        .expect("insert original");
    let error = store
        .append_decision(&conflict)
        .await
        .expect_err("conflict must fail");
    assert!(matches!(error, EvidenceError::IdempotencyConflict { .. }));
    assert_eq!(store.pending_action_count().await.expect("pending"), 1);
}

#[tokio::test]
async fn receipt_requires_its_exact_decisions() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let receipt = GovernanceReceipt::new(
        decision(PolicyPhase::Admission, b"input"),
        None,
        false,
        HandlerOutcome::Blocked,
    );

    let error = store
        .append_receipt(&receipt)
        .await
        .expect_err("missing decision must fail");
    assert!(matches!(error, EvidenceError::Corrupt(_)));
    assert_eq!(store.pending_action_count().await.expect("pending"), 0);
}

#[tokio::test]
async fn concurrent_exact_replay_produces_one_immutable_row() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("first evidence pool");
    let second = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("second evidence pool");
    let record = decision(PolicyPhase::Admission, b"concurrent");

    let (left, right) = tokio::join!(
        first.append_decision(&record),
        second.append_decision(&record)
    );
    let dispositions = [left.expect("left append"), right.expect("right append")];
    assert!(dispositions.contains(&AppendDisposition::Inserted));
    assert!(dispositions.contains(&AppendDisposition::AlreadyPresent));

    let raw = sqlite
        .open_durable_evidence_pool(first.path())
        .await
        .expect("raw evidence pool");
    let delete_error = sqlx::query("DELETE FROM governance_decisions")
        .execute(&raw)
        .await
        .expect_err("append-only trigger must reject deletion");
    assert!(
        delete_error
            .to_string()
            .contains("governance decisions are immutable")
    );
}

#[tokio::test]
async fn concurrent_conflict_preserves_exactly_one_valid_record() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("first evidence pool");
    let second = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("second evidence pool");
    let left_record = decision(PolicyPhase::Admission, b"left");
    let right_record = decision(PolicyPhase::Admission, b"right");

    let (left, right) = tokio::join!(
        first.append_decision(&left_record),
        second.append_decision(&right_record)
    );
    let inserted = usize::from(matches!(left, Ok(AppendDisposition::Inserted)))
        + usize::from(matches!(right, Ok(AppendDisposition::Inserted)));
    let conflicts = usize::from(matches!(
        left,
        Err(EvidenceError::IdempotencyConflict { .. })
    )) + usize::from(matches!(
        right,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    assert_eq!(inserted, 1);
    assert_eq!(conflicts, 1);

    let stored = first
        .get_action_evidence(&left_record.action.action_id)
        .await
        .expect("read surviving decision")
        .admission
        .expect("one admission survives");
    assert!(stored == left_record || stored == right_record);
}

#[tokio::test]
async fn malformed_receipt_binding_is_rejected_before_insert() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let admission = decision_for("call-1", PolicyPhase::Admission, b"one");
    let authorization = decision_for("call-2", PolicyPhase::Authorization, b"two");
    store.append_decision(&admission).await.expect("admission");
    store
        .append_decision(&authorization)
        .await
        .expect("authorization");
    let malformed = GovernanceReceipt::new(
        admission,
        Some(authorization),
        true,
        HandlerOutcome::HandlerCompleted {
            reported_success: true,
        },
    );

    let error = store
        .append_receipt(&malformed)
        .await
        .expect_err("cross-action authorization must fail");
    assert!(matches!(error, EvidenceError::InvalidRecord(_)));
    assert_eq!(store.pending_action_count().await.expect("pending"), 2);
}

#[tokio::test]
async fn swapped_phase_and_invalid_schema_are_rejected() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let authorization = decision(PolicyPhase::Authorization, b"input");
    store
        .append_decision(&authorization)
        .await
        .expect("authorization row");
    let swapped = GovernanceReceipt::new(authorization, None, false, HandlerOutcome::Blocked);
    assert!(matches!(
        store
            .append_receipt(&swapped)
            .await
            .expect_err("authorization cannot substitute for admission"),
        EvidenceError::InvalidRecord(_)
    ));

    let mut invalid_schema = decision_for("call-2", PolicyPhase::Admission, b"input");
    invalid_schema.action.schema_version = GOVERNANCE_SCHEMA_VERSION + 1;
    assert!(matches!(
        store
            .append_decision(&invalid_schema)
            .await
            .expect_err("invalid schema must fail"),
        EvidenceError::InvalidRecord(_)
    ));
}

#[tokio::test]
async fn corrupted_stored_digest_fails_closed() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let admission = decision(PolicyPhase::Admission, b"input");
    let authorization = decision(PolicyPhase::Authorization, b"effective");
    let receipt = GovernanceReceipt::new(
        admission.clone(),
        Some(authorization.clone()),
        true,
        HandlerOutcome::HandlerCompleted {
            reported_success: true,
        },
    );
    store.append_decision(&admission).await.expect("admission");
    store
        .append_decision(&authorization)
        .await
        .expect("authorization");
    store.append_receipt(&receipt).await.expect("receipt");

    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    sqlx::query("DROP TRIGGER governance_receipts_no_update")
        .execute(&raw)
        .await
        .expect("disable immutable trigger for corruption simulation");
    sqlx::query("UPDATE governance_receipts SET payload_sha256 = ? WHERE receipt_id = ?")
        .bind("0".repeat(64))
        .bind(receipt.receipt_id.as_str())
        .execute(&raw)
        .await
        .expect("simulate digest corruption");

    let error = store
        .get_receipt(&receipt.receipt_id)
        .await
        .expect_err("corruption must fail closed");
    assert!(matches!(error, EvidenceError::Corrupt(_)));
}

#[tokio::test]
async fn noncanonical_stored_json_fails_closed_even_with_matching_digest() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let admission = decision(PolicyPhase::Admission, b"input");
    store.append_decision(&admission).await.expect("admission");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    let original: String =
        sqlx::query_scalar("SELECT payload_json FROM governance_decisions WHERE decision_id = ?")
            .bind(admission.decision_id.as_str())
            .fetch_one(&raw)
            .await
            .expect("stored JSON");
    let noncanonical = format!("{original} ");
    let digest = Sha256Digest::for_bytes(noncanonical.as_bytes());
    sqlx::query("DROP TRIGGER governance_decisions_no_update")
        .execute(&raw)
        .await
        .expect("disable update trigger for corruption simulation");
    sqlx::query(
        "UPDATE governance_decisions
         SET payload_json = ?, payload_sha256 = ? WHERE decision_id = ?",
    )
    .bind(noncanonical)
    .bind(digest.as_str())
    .bind(admission.decision_id.as_str())
    .execute(&raw)
    .await
    .expect("simulate JSON corruption");

    assert!(matches!(
        store
            .get_action_evidence(&admission.action.action_id)
            .await
            .expect_err("noncanonical JSON must fail closed"),
        EvidenceError::Corrupt(_)
    ));
}

#[tokio::test]
async fn corrupted_projection_schema_and_phase_are_classified_as_corrupt() {
    for corruption in ["schema", "phase"] {
        let temp = TempDir::new().expect("temp dir");
        let sqlite = sqlite_config(&temp);
        let store = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("open evidence");
        let admission = decision(PolicyPhase::Admission, b"input");
        store.append_decision(&admission).await.expect("admission");
        let raw = sqlite
            .open_durable_evidence_pool(store.path())
            .await
            .expect("raw evidence pool");
        sqlx::query("DROP TRIGGER governance_decisions_no_update")
            .execute(&raw)
            .await
            .expect("disable update trigger for corruption simulation");
        if corruption == "schema" {
            let mut connection = raw.acquire().await.expect("raw connection");
            sqlx::query("PRAGMA ignore_check_constraints = ON")
                .execute(&mut *connection)
                .await
                .expect("allow corruption simulation");
            sqlx::query("UPDATE governance_decisions SET schema_version = 2 WHERE decision_id = ?")
                .bind(admission.decision_id.as_str())
                .execute(&mut *connection)
                .await
                .expect("simulate schema corruption");
        } else {
            sqlx::query(
                "UPDATE governance_decisions SET phase = 'authorization' WHERE decision_id = ?",
            )
            .bind(admission.decision_id.as_str())
            .execute(&raw)
            .await
            .expect("simulate phase corruption");
        }

        assert!(matches!(
            store
                .get_action_evidence(&admission.action.action_id)
                .await
                .expect_err("projection corruption must fail closed"),
            EvidenceError::Corrupt(_)
        ));
    }
}

#[tokio::test]
async fn receipt_read_rejects_decision_material_that_drifted_after_commit() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let admission = decision(PolicyPhase::Admission, b"input");
    let authorization = decision(PolicyPhase::Authorization, b"effective");
    let receipt = GovernanceReceipt::new(
        admission.clone(),
        Some(authorization.clone()),
        true,
        HandlerOutcome::HandlerCompleted {
            reported_success: true,
        },
    );
    store.append_decision(&admission).await.expect("admission");
    store
        .append_decision(&authorization)
        .await
        .expect("authorization");
    store.append_receipt(&receipt).await.expect("receipt");

    let mut drifted = authorization;
    drifted.policy.revision += 1;
    let payload = crate::canonical::canonical_json(&drifted).expect("canonical decision");
    let payload_json = String::from_utf8(payload.clone()).expect("UTF-8 JSON");
    let digest = Sha256Digest::for_bytes(&payload);
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    sqlx::query("DROP TRIGGER governance_decisions_no_update")
        .execute(&raw)
        .await
        .expect("disable update trigger for corruption simulation");
    sqlx::query(
        "UPDATE governance_decisions
         SET payload_json = ?, payload_sha256 = ? WHERE decision_id = ?",
    )
    .bind(payload_json)
    .bind(digest.as_str())
    .bind(drifted.decision_id.as_str())
    .execute(&raw)
    .await
    .expect("simulate cross-record drift");

    assert!(matches!(
        store
            .get_receipt(&receipt.receipt_id)
            .await
            .expect_err("receipt must match authoritative decision rows"),
        EvidenceError::Corrupt(_)
    ));
}

#[tokio::test]
async fn immutable_triggers_reject_updates_and_deletes_for_both_tables() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let admission = decision(PolicyPhase::Admission, b"input");
    let receipt = GovernanceReceipt::new(admission.clone(), None, false, HandlerOutcome::Blocked);
    store.append_decision(&admission).await.expect("admission");
    store.append_receipt(&receipt).await.expect("receipt");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");

    for statement in [
        "UPDATE governance_decisions SET recorded_at_ms = recorded_at_ms + 1",
        "DELETE FROM governance_decisions",
        "UPDATE governance_receipts SET recorded_at_ms = recorded_at_ms + 1",
        "DELETE FROM governance_receipts",
    ] {
        let error = sqlx::query(statement)
            .execute(&raw)
            .await
            .expect_err("immutable table mutation must fail");
        assert!(error.to_string().contains("immutable"));
    }
}

#[tokio::test]
async fn composite_foreign_key_rejects_cross_action_receipt_projection() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let admission = decision(PolicyPhase::Admission, b"input");
    store.append_decision(&admission).await.expect("admission");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    let error = sqlx::query(
        "INSERT INTO governance_receipts (
            receipt_id, action_id, thread_id, turn_id, call_id,
            admission_decision_id, admission_phase,
            authorization_decision_id, authorization_phase,
            schema_version, payload_json, payload_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, 'admission', NULL, NULL, 1, '{}', ?, 0)",
    )
    .bind(format!("receipt:v1:{}", "a".repeat(64)))
    .bind(format!("tool:v1:{}", "b".repeat(64)))
    .bind("thread-1")
    .bind("turn-1")
    .bind("call-1")
    .bind(admission.decision_id.as_str())
    .bind("0".repeat(64))
    .execute(&raw)
    .await
    .expect_err("decision and receipt action ids must share one binding");
    assert!(error.to_string().contains("FOREIGN KEY constraint failed"));
}

#[tokio::test]
async fn open_classifies_non_database_file_as_corrupt() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    std::fs::write(
        sqlite.home().join("hepta_evidence_2.sqlite"),
        b"this is not a SQLite database",
    )
    .expect("write NOTADB fixture");

    let error = match HeptaEvidenceStore::open(&sqlite).await {
        Ok(_) => panic!("NOTADB evidence file must be rejected"),
        Err(error) => error,
    };
    assert!(matches!(error, EvidenceError::Corrupt(_)));
}

#[tokio::test]
async fn open_existing_read_only_does_not_create_a_missing_store() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let evidence_path = sqlite.home().join("hepta_evidence_2.sqlite");
    assert!(!evidence_path.exists());

    let error = match HeptaEvidenceStore::open_existing_read_only(&sqlite).await {
        Ok(_) => panic!("a diagnostic read must not create the evidence store"),
        Err(error) => error,
    };
    assert!(matches!(error, EvidenceError::Unavailable(_)));
    assert!(!evidence_path.exists());
}

#[tokio::test]
async fn open_existing_read_only_reads_a_complete_store_without_mutating_it() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let writable = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("compose evidence store");
    let ledger_before: Vec<(i64, String, bool, Vec<u8>)> = sqlx::query_as(
        "SELECT version, description, success, checksum
         FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(&writable.pool)
    .await
    .expect("read migration ledger before diagnostic open");

    let read_only = HeptaEvidenceStore::open_existing_read_only(&sqlite)
        .await
        .expect("open existing evidence store read-only");
    assert_eq!(
        read_only.summary().await.expect("read summary"),
        Default::default()
    );
    let write_error = read_only
        .append_decision(&decision(PolicyPhase::Admission, b"read-only"))
        .await
        .expect_err("the diagnostic pool must reject evidence writes");
    assert!(matches!(write_error, EvidenceError::Unavailable(_)));
    let ledger_after: Vec<(i64, String, bool, Vec<u8>)> = sqlx::query_as(
        "SELECT version, description, success, checksum
         FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(&read_only.pool)
    .await
    .expect("read migration ledger after diagnostic open");
    assert_eq!(ledger_after, ledger_before);
    assert_eq!(
        read_only
            .pending_action_count()
            .await
            .expect("read governance count"),
        0
    );

    read_only.pool.close().await;
    writable.pool.close().await;
}

#[tokio::test]
async fn open_existing_read_only_rejects_a_partial_ledger_without_migrating_it() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("compose evidence store");
    let evidence_path = store.path().to_path_buf();
    store.pool.close().await;

    let raw = sqlite
        .open_durable_evidence_pool(&evidence_path)
        .await
        .expect("open raw evidence pool");
    let latest_version: i64 = sqlx::query_scalar("SELECT MAX(version) FROM _sqlx_migrations")
        .fetch_one(&raw)
        .await
        .expect("read latest migration");
    sqlx::query("DELETE FROM _sqlx_migrations WHERE version = ?")
        .bind(latest_version)
        .execute(&raw)
        .await
        .expect("remove latest migration ledger entry");
    let ledger_count_before: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM _sqlx_migrations")
        .fetch_one(&raw)
        .await
        .expect("count partial ledger");
    raw.close().await;

    let error = match HeptaEvidenceStore::open_existing_read_only(&sqlite).await {
        Ok(_) => panic!("a partial evidence lineage must fail closed"),
        Err(error) => error,
    };
    assert!(matches!(error, EvidenceError::Corrupt(_)));

    let raw = sqlite
        .open_durable_evidence_pool(&evidence_path)
        .await
        .expect("reopen raw evidence pool");
    let ledger_count_after: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM _sqlx_migrations")
        .fetch_one(&raw)
        .await
        .expect("count ledger after rejected diagnostic open");
    assert_eq!(ledger_count_after, ledger_count_before);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM _sqlx_migrations WHERE version = ?",)
            .bind(latest_version)
            .fetch_one(&raw)
            .await
            .expect("check that the missing migration was not installed"),
        0
    );
    raw.close().await;
}

#[test]
fn lineage_two_preserves_reserved_migration_checksums() {
    let migrator = sqlx::migrate!("./migrations");
    let checksum = |version| {
        migrator
            .migrations
            .iter()
            .find(|migration| migration.version == version)
            .unwrap_or_else(|| panic!("missing reserved migration {version}"))
            .checksum
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    };

    assert_eq!(
        checksum(4),
        "e28610023f8b4f754cf742c256d00b6cafe2ff77f5c6366e4a4201c771a35d3df4b52957f316ecbcf899191f62442452"
    );
    assert_eq!(
        checksum(5),
        "6a6b54d6e8b599c1e11c131e64245c36c46694a7a722c8130b50d4f3a3400281bd1d1a27116c349e34f00c96feb9f24a"
    );
    assert_eq!(
        checksum(6),
        "2707b5d484e7a9b8a518bcd05b415ddc0757bb095a0049545e71ffcb158c7b775e9fccef5eeca47ca4c6e1f5216b1ad4"
    );
}

#[tokio::test]
async fn open_does_not_touch_frozen_lineage_with_channel_0004() {
    // SHA-384 of frozen vNext's 0004_channel_evidence.sql. The clean series
    // must never inspect or migrate this ledger through its own migration set.
    const FROZEN_VNEXT_0004_SHA384: [u8; 48] = [
        0x18, 0x68, 0xfe, 0x81, 0xe9, 0xfb, 0x69, 0xe4, 0x0f, 0x94, 0x9a, 0xe8, 0x8b, 0x4f, 0x34,
        0x75, 0xc7, 0xf8, 0x0d, 0xec, 0xa8, 0x52, 0x54, 0xa5, 0xcc, 0x3a, 0x42, 0xbc, 0x6c, 0x0d,
        0x0e, 0xcb, 0x6e, 0x03, 0x45, 0xab, 0x42, 0x42, 0x9f, 0x31, 0x8e, 0x37, 0xcd, 0x0f, 0x2b,
        0xeb, 0xb9, 0x7f,
    ];

    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let legacy_path = sqlite.home().join("hepta_evidence_1.sqlite");
    let legacy = sqlite
        .open_durable_evidence_pool(&legacy_path)
        .await
        .expect("open frozen evidence lineage");
    sqlx::query(
        "CREATE TABLE _sqlx_migrations (
            version BIGINT PRIMARY KEY,
            description TEXT NOT NULL,
            installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            success BOOLEAN NOT NULL,
            checksum BLOB NOT NULL,
            execution_time BIGINT NOT NULL
        )",
    )
    .execute(&legacy)
    .await
    .expect("create frozen migration ledger");
    sqlx::query(
        "INSERT INTO _sqlx_migrations (
            version, description, success, checksum, execution_time
         ) VALUES (4, 'channel evidence', TRUE, ?, 0)",
    )
    .bind(FROZEN_VNEXT_0004_SHA384.as_slice())
    .execute(&legacy)
    .await
    .expect("record frozen vNext migration 0004");
    sqlx::query("CREATE TABLE channel_delivery_intents (attempt_id TEXT PRIMARY KEY)")
        .execute(&legacy)
        .await
        .expect("create frozen vNext marker table");
    legacy.close().await;
    let legacy_before = std::fs::read(&legacy_path).expect("read frozen evidence before open");

    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open clean evidence lineage");
    assert_eq!(
        store.path(),
        sqlite.home().join("hepta_evidence_2.sqlite").as_path()
    );
    assert!(store.path().is_file());
    drop(store);

    let legacy_after = std::fs::read(&legacy_path).expect("read frozen evidence after open");
    assert_eq!(legacy_after, legacy_before);
}

#[tokio::test]
async fn open_classifies_migration_checksum_mismatch_as_corrupt() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    sqlx::query("UPDATE _sqlx_migrations SET checksum = ? WHERE version = 1")
        .bind(vec![0_u8; 48])
        .execute(&raw)
        .await
        .expect("corrupt migration checksum");
    raw.close().await;
    drop(store);

    let error = match HeptaEvidenceStore::open(&sqlite).await {
        Ok(_) => panic!("migration checksum mismatch must be rejected"),
        Err(error) => error,
    };
    assert!(matches!(error, EvidenceError::Corrupt(_)));
}

#[tokio::test]
async fn open_rejects_missing_immutable_trigger_even_when_quick_check_is_ok() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    sqlx::query("DROP TRIGGER governance_receipts_no_delete")
        .execute(&raw)
        .await
        .expect("drop immutable trigger");
    let quick_check: String = sqlx::query_scalar("PRAGMA quick_check(1)")
        .fetch_one(&raw)
        .await
        .expect("quick check");
    assert_eq!(quick_check, "ok");
    raw.close().await;
    drop(store);

    let error = match HeptaEvidenceStore::open(&sqlite).await {
        Ok(_) => panic!("missing immutable trigger must be rejected"),
        Err(error) => error,
    };
    assert!(matches!(error, EvidenceError::Corrupt(_)));
}

#[tokio::test]
async fn open_requires_reserved_lineage_immutable_triggers() {
    for (trigger, statement) in [
        (
            "memory_mutation_shadow_no_delete",
            "DROP TRIGGER memory_mutation_shadow_no_delete",
        ),
        (
            "channel_ingress_receipts_no_delete",
            "DROP TRIGGER channel_ingress_receipts_no_delete",
        ),
    ] {
        let temp = TempDir::new().expect("temp dir");
        let sqlite = sqlite_config(&temp);
        let store = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("open evidence");
        let raw = sqlite
            .open_durable_evidence_pool(store.path())
            .await
            .expect("raw evidence pool");
        sqlx::query(statement)
            .execute(&raw)
            .await
            .expect("drop reserved immutable trigger");
        let quick_check: String = sqlx::query_scalar("PRAGMA quick_check(1)")
            .fetch_one(&raw)
            .await
            .expect("quick check");
        assert_eq!(quick_check, "ok");
        raw.close().await;
        drop(store);

        let error = match HeptaEvidenceStore::open(&sqlite).await {
            Ok(_) => panic!("missing reserved trigger {trigger} must be rejected"),
            Err(error) => error,
        };
        assert!(matches!(error, EvidenceError::Corrupt(_)));
    }
}

#[tokio::test]
async fn open_rejects_foreign_key_violation_even_when_quick_check_is_ok() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("open evidence");
    let admission = decision(PolicyPhase::Admission, b"input");
    store.append_decision(&admission).await.expect("admission");
    let raw = sqlite
        .open_durable_evidence_pool(store.path())
        .await
        .expect("raw evidence pool");
    {
        let mut connection = raw.acquire().await.expect("raw connection");
        sqlx::query("PRAGMA foreign_keys = OFF")
            .execute(&mut *connection)
            .await
            .expect("disable foreign keys for corruption simulation");
        sqlx::query(
            "INSERT INTO governance_receipts (
                receipt_id, action_id, thread_id, turn_id, call_id,
                admission_decision_id, admission_phase,
                authorization_decision_id, authorization_phase,
                schema_version, payload_json, payload_sha256, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, 'admission', NULL, NULL, 1, '{}', ?, 0)",
        )
        .bind(format!("receipt:v1:{}", "c".repeat(64)))
        .bind(format!("tool:v1:{}", "d".repeat(64)))
        .bind("thread-1")
        .bind("turn-1")
        .bind("call-1")
        .bind(admission.decision_id.as_str())
        .bind("0".repeat(64))
        .execute(&mut *connection)
        .await
        .expect("insert broken foreign-key fixture");
    }
    let quick_check: String = sqlx::query_scalar("PRAGMA quick_check(1)")
        .fetch_one(&raw)
        .await
        .expect("quick check");
    assert_eq!(quick_check, "ok");
    raw.close().await;
    drop(store);

    let error = match HeptaEvidenceStore::open(&sqlite).await {
        Ok(_) => panic!("foreign-key violation must be rejected"),
        Err(error) => error,
    };
    assert!(matches!(error, EvidenceError::Corrupt(_)));
}

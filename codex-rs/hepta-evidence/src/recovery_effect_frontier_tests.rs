use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn intent() -> ProviderEffectIntent {
    ProviderEffectIntent::new(
        ProviderEffectKey::for_operation("provider", "run", "step").expect("stable key"),
        Sha256Digest::for_bytes(b"exact effect payload"),
    )
}

#[tokio::test]
async fn recovery_snapshot_commits_intent_unknown_and_original_operation_receipt() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let before = store.recovery_snapshot().await.expect("empty snapshot");
    let intent = intent();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("prepare");
    let prepared = store.recovery_snapshot().await.expect("prepared snapshot");
    assert_ne!(
        prepared, before,
        "prepared effect must participate in recovery admission"
    );

    store
        .mark_provider_effect_indeterminate(&intent.key, "lost_response")
        .await
        .expect("unknown");
    let unknown = store.recovery_snapshot().await.expect("unknown snapshot");
    assert_ne!(
        unknown, prepared,
        "uncertainty must not disappear behind the same checkpoint"
    );
    let completed = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"original provider operation"),
        ProviderEffectAckStatus::Completed,
    );
    store
        .append_provider_effect_ack_from_source(&completed, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("reconcile original operation");
    let resolved = store.recovery_snapshot().await.expect("receipt snapshot");
    assert_ne!(
        resolved, unknown,
        "receipt must be included without changing logical identity"
    );
    assert_eq!(
        resolved.qualification_frontier_sha256,
        before.qualification_frontier_sha256
    );
    assert_eq!(
        resolved.authbus_replay_frontier_sha256,
        before.authbus_replay_frontier_sha256
    );
    assert_eq!(resolved.migration_set_sha256, before.migration_set_sha256);
    assert_eq!(
        store.recovery_snapshot().await.expect("stable read"),
        resolved
    );
}

#[tokio::test]
async fn recovery_snapshot_distinguishes_a_valid_effect_only_database_rollback() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.expect("open");
    store
        .bind_recovery_store_id("store:effects")
        .await
        .expect("store identity");
    let old_snapshot = store.recovery_snapshot().await.expect("old snapshot");
    let database = store.path().to_path_buf();
    store.close().await;
    let backup = temp.path().join("before-effects.sqlite");
    std::fs::copy(&database, &backup).expect("old database image");

    let store = HeptaEvidenceStore::open(&sqlite).await.expect("reopen");
    let intent = intent();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("prepare");
    store
        .mark_provider_effect_indeterminate(&intent.key, "dispatch_result_unknown")
        .await
        .expect("retain unknown effect");
    let current_snapshot = store
        .recovery_snapshot()
        .await
        .expect("current external checkpoint input");
    store.close().await;
    std::fs::copy(&backup, &database).expect("restore old but structurally valid image");

    let restored = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("structural check accepts old image");
    assert_eq!(
        restored
            .get_provider_effect(&intent.key)
            .await
            .expect("effect lookup"),
        None
    );
    let restored_snapshot = restored
        .recovery_snapshot()
        .await
        .expect("restored snapshot");
    assert_eq!(restored_snapshot, old_snapshot);
    assert_ne!(
        restored_snapshot, current_snapshot,
        "an independently retained current checkpoint must refuse the old effect image"
    );
}

#[tokio::test]
async fn recovery_snapshot_commits_ack_provenance_and_cross_table_order() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let intent = intent();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("prepare");
    let accepted = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"provider operation"),
        ProviderEffectAckStatus::Accepted,
    );
    store
        .append_provider_effect_ack(&accepted)
        .await
        .expect("dispatch receipt");
    let before = store
        .recovery_snapshot()
        .await
        .expect("dispatch checkpoint");
    sqlx::query("DROP TRIGGER provider_effect_acknowledgements_no_update")
        .execute(&store.pool)
        .await
        .expect("model imported database mutation");
    // Provenance and timestamp are not part of record_sha256. They must be
    // committed separately even with identical canonical ACK bytes/row count.
    sqlx::query("UPDATE provider_effect_acknowledgements SET source = 'status_lookup'")
        .execute(&store.pool)
        .await
        .expect("change provenance only");
    let source_changed = store
        .recovery_snapshot()
        .await
        .expect("changed source checkpoint");
    assert_ne!(source_changed, before);
    sqlx::query("UPDATE provider_effect_acknowledgements SET recorded_at_ms = recorded_at_ms + 1")
        .execute(&store.pool)
        .await
        .expect("change ordering only");
    assert_ne!(
        store
            .recovery_snapshot()
            .await
            .expect("changed order checkpoint"),
        source_changed
    );
}

#[tokio::test]
async fn recovery_snapshot_commits_effect_history_after_the_first_page() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    for index in 0..256 {
        let intent = ProviderEffectIntent::new(
            ProviderEffectKey::for_operation("provider", "run", &format!("step:{index}"))
                .expect("stable key"),
            Sha256Digest::for_bytes(b"exact effect payload"),
        );
        store
            .append_provider_effect_intent(&intent)
            .await
            .expect("prepare");
    }
    let first_page = store.recovery_snapshot().await.expect("first page");
    store
        .append_provider_effect_intent(&intent())
        .await
        .expect("next page");
    assert_ne!(
        store.recovery_snapshot().await.expect("complete snapshot"),
        first_page,
        "a later page must not be omitted from the recovery commitment"
    );
}

#[tokio::test]
async fn recovery_snapshot_refuses_changed_json_with_retained_record_digests() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let intent = intent();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .mark_provider_effect_indeterminate(&intent.key, "lost_response")
        .await
        .expect("unknown");
    let ack = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"original operation"),
        ProviderEffectAckStatus::Completed,
    );
    store
        .append_provider_effect_ack_from_source(&ack, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("receipt");
    let before = store.recovery_snapshot().await.expect("valid snapshot");
    for (table, select_sql, drop_trigger_sql, corrupt_sql, restore_sql) in [
        (
            "provider_effect_intents",
            "SELECT payload_json FROM provider_effect_intents",
            "DROP TRIGGER provider_effect_intents_no_update",
            "UPDATE provider_effect_intents SET payload_json = '{}'",
            "UPDATE provider_effect_intents SET payload_json = ?",
        ),
        (
            "provider_effect_acknowledgements",
            "SELECT payload_json FROM provider_effect_acknowledgements",
            "DROP TRIGGER provider_effect_acknowledgements_no_update",
            "UPDATE provider_effect_acknowledgements SET payload_json = '{}'",
            "UPDATE provider_effect_acknowledgements SET payload_json = ?",
        ),
        (
            "provider_effect_uncertainties",
            "SELECT payload_json FROM provider_effect_uncertainties",
            "DROP TRIGGER provider_effect_uncertainties_no_update",
            "UPDATE provider_effect_uncertainties SET payload_json = '{}'",
            "UPDATE provider_effect_uncertainties SET payload_json = ?",
        ),
    ] {
        let original: String = sqlx::query_scalar(select_sql)
            .fetch_one(&store.pool)
            .await
            .expect("original payload");
        sqlx::query(drop_trigger_sql)
            .execute(&store.pool)
            .await
            .expect("model post-open imported mutation");
        sqlx::query(corrupt_sql)
            .execute(&store.pool)
            .await
            .expect("retain digest but replace JSON");
        assert!(
            matches!(
                store.recovery_snapshot().await,
                Err(EvidenceError::Corrupt(_))
            ),
            "snapshot trusted a retained {table} digest without checking its bytes"
        );
        sqlx::query(restore_sql)
            .bind(original)
            .execute(&store.pool)
            .await
            .expect("restore original bytes");
        assert_eq!(
            store.recovery_snapshot().await.expect("restored snapshot"),
            before
        );
    }
}

#[tokio::test]
async fn recovery_snapshot_refuses_effect_projection_drift_with_retained_payloads() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let intent = intent();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("intent");
    store
        .mark_provider_effect_indeterminate(&intent.key, "lost_response")
        .await
        .expect("unknown");
    let ack = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"original operation"),
        ProviderEffectAckStatus::Completed,
    );
    store
        .append_provider_effect_ack_from_source(&ack, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("receipt");
    let before = store.recovery_snapshot().await.expect("valid snapshot");
    sqlx::query("DROP TRIGGER provider_effect_intents_no_update")
        .execute(&store.pool)
        .await
        .expect("model post-open intent mutation");
    sqlx::query("DROP TRIGGER provider_effect_acknowledgements_no_update")
        .execute(&store.pool)
        .await
        .expect("model post-open ACK mutation");
    sqlx::query("DROP TRIGGER provider_effect_uncertainties_no_update")
        .execute(&store.pool)
        .await
        .expect("model post-open uncertainty mutation");
    let mut unrefused = Vec::new();
    macro_rules! check_projection {
        ($projection:literal, $select:literal, $update:literal, $changed:expr) => {{
            let original: String = sqlx::query_scalar($select)
                .fetch_one(&store.pool)
                .await
                .expect("original projection");
            sqlx::query($update)
                .bind($changed)
                .execute(&store.pool)
                .await
                .expect("alter projection without changing JSON or digest");
            if !matches!(
                store.recovery_snapshot().await,
                Err(EvidenceError::Corrupt(_))
            ) {
                unrefused.push($projection);
            }
            sqlx::query($update)
                .bind(original)
                .execute(&store.pool)
                .await
                .expect("restore original projection");
            assert_eq!(
                store.recovery_snapshot().await.expect("restored snapshot"),
                before
            );
        }};
    }
    let changed_digest = Sha256Digest::for_bytes(b"changed projection");
    check_projection!(
        "intent payload",
        "SELECT payload_sha256 FROM provider_effect_intents",
        "UPDATE provider_effect_intents SET payload_sha256 = ?",
        changed_digest.as_str()
    );
    check_projection!(
        "ACK payload",
        "SELECT payload_sha256 FROM provider_effect_acknowledgements",
        "UPDATE provider_effect_acknowledgements SET payload_sha256 = ?",
        changed_digest.as_str()
    );
    check_projection!(
        "ACK operation",
        "SELECT provider_operation_id_sha256 FROM provider_effect_acknowledgements",
        "UPDATE provider_effect_acknowledgements SET provider_operation_id_sha256 = ?",
        changed_digest.as_str()
    );
    check_projection!(
        "ACK status",
        "SELECT status FROM provider_effect_acknowledgements",
        "UPDATE provider_effect_acknowledgements SET status = ?",
        "accepted"
    );
    check_projection!(
        "uncertainty payload",
        "SELECT payload_sha256 FROM provider_effect_uncertainties",
        "UPDATE provider_effect_uncertainties SET payload_sha256 = ?",
        changed_digest.as_str()
    );
    check_projection!(
        "uncertainty reason",
        "SELECT reason_code FROM provider_effect_uncertainties",
        "UPDATE provider_effect_uncertainties SET reason_code = ?",
        "different_reason"
    );
    assert!(
        unrefused.is_empty(),
        "snapshot trusted drift in these projections: {unrefused:?}"
    );
}

#[tokio::test]
async fn recovery_snapshot_refuses_canonical_ack_bound_to_a_different_payload() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    let intent = intent();
    store
        .append_provider_effect_intent(&intent)
        .await
        .expect("authoritative intent");
    let ack = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"original operation"),
        ProviderEffectAckStatus::Completed,
    );
    store
        .append_provider_effect_ack_from_source(&ack, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("receipt");
    let substituted_intent =
        ProviderEffectIntent::new(intent.key, Sha256Digest::for_bytes(b"substituted payload"));
    let substituted_ack = ProviderEffectAck::new(
        substituted_intent.key.clone(),
        substituted_intent.payload_sha256.clone(),
        ack.provider_operation_id_sha256,
        ProviderEffectAckStatus::Completed,
    );
    substituted_ack
        .validate_for(&substituted_intent)
        .expect("canonical ACK valid for its substituted intent");
    let payload = crate::canonical::canonical_json(&substituted_ack).expect("canonical ACK");
    let record_sha256 = Sha256Digest::for_bytes(&payload);
    let payload_json = String::from_utf8(payload).expect("canonical UTF-8");
    sqlx::query("DROP TRIGGER provider_effect_acknowledgements_no_update")
        .execute(&store.pool)
        .await
        .expect("model imported ACK");
    sqlx::query(
        "UPDATE provider_effect_acknowledgements
         SET payload_sha256 = ?, payload_json = ?, record_sha256 = ?",
    )
    .bind(substituted_ack.payload_sha256.as_str())
    .bind(payload_json)
    .bind(record_sha256.as_str())
    .execute(&store.pool)
    .await
    .expect("all ACK projections and its digest match the new canonical payload");
    assert!(
        matches!(
            store.recovery_snapshot().await,
            Err(EvidenceError::Corrupt(_))
        ),
        "snapshot accepted a canonical ACK for a different authoritative payload"
    );
}

#[tokio::test]
async fn recovery_snapshot_refuses_orphan_effect_observations() {
    let mut unrefused = Vec::new();
    for kind in ["ack", "uncertainty"] {
        let temp = TempDir::new().expect("temp dir");
        let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open");
        let intent = intent();
        store
            .append_provider_effect_intent(&intent)
            .await
            .expect("intent");
        if kind == "ack" {
            let ack = ProviderEffectAck::new(
                intent.key.clone(),
                intent.payload_sha256.clone(),
                Sha256Digest::for_bytes(b"original operation"),
                ProviderEffectAckStatus::Completed,
            );
            store
                .append_provider_effect_ack_from_source(&ack, ProviderEffectAckSource::StatusLookup)
                .await
                .expect("receipt");
        } else {
            store
                .mark_provider_effect_indeterminate(&intent.key, "lost_response")
                .await
                .expect("unknown");
        }
        let mut connection = store.pool.acquire().await.expect("import connection");
        sqlx::query("PRAGMA foreign_keys = OFF")
            .execute(&mut *connection)
            .await
            .expect("model import without foreign-key enforcement");
        sqlx::query("DROP TRIGGER provider_effect_intents_no_delete")
            .execute(&mut *connection)
            .await
            .expect("model imported intent loss");
        sqlx::query("DELETE FROM provider_effect_intents")
            .execute(&mut *connection)
            .await
            .expect("remove only authoritative intent");
        sqlx::query("PRAGMA foreign_keys = ON")
            .execute(&mut *connection)
            .await
            .expect("restore connection enforcement");
        drop(connection);
        if !matches!(
            store.recovery_snapshot().await,
            Err(EvidenceError::Corrupt(detail)) if detail.contains("authoritative intent")
        ) {
            unrefused.push(kind);
        }
    }
    assert!(
        unrefused.is_empty(),
        "snapshot trusted orphan observations: {unrefused:?}"
    );
}

async fn remove_effect_sequence_primary_key(store: &HeptaEvidenceStore) {
    // Keep the schema replacement atomic and on one pooled connection.
    let mut transaction = store.pool.begin().await.expect("schema import transaction");
    sqlx::query(
        "CREATE TABLE imported_provider_effect_intents AS
         SELECT * FROM provider_effect_intents",
    )
    .execute(&mut *transaction)
    .await
    .expect("model imported schema without a sequence primary key");
    // Retain the referenced effect key so foreign-key checks remain valid
    // while the imported table permits these sequence corruption controls.
    sqlx::query(
        "CREATE UNIQUE INDEX imported_provider_effect_intents_key
         ON imported_provider_effect_intents(effect_key)",
    )
    .execute(&mut *transaction)
    .await
    .expect("retain the authoritative intent association key");
    sqlx::query("DROP TABLE provider_effect_intents")
        .execute(&mut *transaction)
        .await
        .expect("replace original table");
    sqlx::query("ALTER TABLE imported_provider_effect_intents RENAME TO provider_effect_intents")
        .execute(&mut *transaction)
        .await
        .expect("restore table name");
    transaction.commit().await.expect("commit imported schema");
}

#[tokio::test]
async fn recovery_snapshot_refuses_repeated_effect_sequence_after_schema_drift() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open");
    store
        .append_provider_effect_intent(&intent())
        .await
        .expect("first intent");
    let other_intent = ProviderEffectIntent::new(
        ProviderEffectKey::for_operation("provider", "run", "other_step")
            .expect("other stable key"),
        Sha256Digest::for_bytes(b"other payload"),
    );
    store
        .append_provider_effect_intent(&other_intent)
        .await
        .expect("second intent");
    remove_effect_sequence_primary_key(&store).await;
    sqlx::query("UPDATE provider_effect_intents SET seq = 1 WHERE seq = 2")
        .execute(&store.pool)
        .await
        .expect("repeat a sequence without changing either valid intent payload");
    assert!(
        matches!(
            store.recovery_snapshot().await,
            Err(EvidenceError::Corrupt(detail)) if detail.contains("repeated sequence")
        ),
        "snapshot accepted a repeated sequence within an effect page"
    );
}

#[tokio::test]
async fn recovery_snapshot_refuses_repeated_effect_sequence_at_page_boundary() {
    let mut unrefused = Vec::new();
    for (label, last_sequence) in [("ordinary", 256_i64), ("maximum", i64::MAX)] {
        let temp = TempDir::new().expect("temp dir");
        let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open");
        for index in 0..257 {
            let intent = ProviderEffectIntent::new(
                ProviderEffectKey::for_operation("provider", "run", &format!("boundary:{index}"))
                    .expect("stable key"),
                Sha256Digest::for_bytes(b"exact effect payload"),
            );
            store
                .append_provider_effect_intent(&intent)
                .await
                .expect("intent");
        }
        remove_effect_sequence_primary_key(&store).await;
        sqlx::query("UPDATE provider_effect_intents SET seq = ? WHERE seq = 256")
            .bind(last_sequence)
            .execute(&store.pool)
            .await
            .expect("set one boundary sequence");
        store
            .recovery_snapshot()
            .await
            .expect("all 257 unique positive sequences remain valid");
        sqlx::query("UPDATE provider_effect_intents SET seq = ? WHERE seq = 257")
            .bind(last_sequence)
            .execute(&store.pool)
            .await
            .expect("repeat the sequence across the page boundary");
        if !matches!(
            store.recovery_snapshot().await,
            Err(EvidenceError::Corrupt(detail)) if detail.contains("repeated sequence")
        ) {
            unrefused.push(label);
        }
    }
    assert!(
        unrefused.is_empty(),
        "snapshot skipped repeated sequences at these page boundaries: {unrefused:?}"
    );
}

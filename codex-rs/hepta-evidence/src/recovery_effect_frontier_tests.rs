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
    for table in [
        "provider_effect_intents",
        "provider_effect_acknowledgements",
        "provider_effect_uncertainties",
    ] {
        let original: String = sqlx::query_scalar(&format!("SELECT payload_json FROM {table}"))
            .fetch_one(&store.pool)
            .await
            .expect("original payload");
        sqlx::query(&format!("DROP TRIGGER {table}_no_update"))
            .execute(&store.pool)
            .await
            .expect("model post-open imported mutation");
        sqlx::query(&format!("UPDATE {table} SET payload_json = '{{}}'"))
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
        sqlx::query(&format!("UPDATE {table} SET payload_json = ?"))
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

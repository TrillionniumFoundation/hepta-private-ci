use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::ProviderEffectState;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use super::*;

struct NoDispatch;

impl ProviderEffectAdapter for NoDispatch {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        panic!("migration must not grant another provider dispatch")
    }

    fn lookup<'a>(
        &'a self,
        _: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        panic!("migration must not invent a provider lookup")
    }
}

#[tokio::test]
async fn observation_migration_preserves_effect_rows_sequences_and_consumed_boundary() {
    let temp = tempfile::TempDir::new().expect("temp dir");
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    );
    let path = sqlite.home().join(EVIDENCE_DATABASE_LINEAGE);
    let pool = sqlite
        .open_durable_evidence_pool(&path)
        .await
        .expect("legacy pool");
    MIGRATOR
        .run_to(/*target*/ 15, &pool)
        .await
        .expect("original migrations only");
    let legacy = HeptaEvidenceStore {
        pool,
        path,
        provider_effect_boundary_lock: Arc::new(tokio::sync::Mutex::new(())),
    };
    legacy
        .bind_recovery_store_id("store:observation-migration")
        .await
        .expect("store identity");
    let intent = ProviderEffectIntent::new(
        ProviderEffectKey::for_operation("provider", "migration", "step").expect("stable key"),
        Sha256Digest::for_bytes(b"original immutable payload"),
    );
    let accepted = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"original provider operation"),
        ProviderEffectAckStatus::Accepted,
    );
    legacy
        .append_provider_effect_intent(&intent)
        .await
        .expect("original intent");
    legacy
        .append_provider_effect_ack(&accepted)
        .await
        .expect("original dispatch ACK");
    legacy
        .mark_provider_effect_indeterminate(&intent.key, "response_lost")
        .await
        .expect("original unknown");
    // Unused allocation gaps are still part of the allocator's durable floor.
    sqlx::query("UPDATE sqlite_sequence SET seq = seq + 100 WHERE name IN ('provider_effect_acknowledgements', 'provider_effect_uncertainties')")
        .execute(&legacy.pool).await.expect("retain allocator gaps");
    let before = legacy
        .get_provider_effect(&intent.key)
        .await
        .expect("read old effect")
        .expect("old effect");
    let old_snapshot = legacy
        .recovery_snapshot()
        .await
        .expect("old checkpoint input");
    let old_allocators: Vec<(String, i64)> =
        sqlx::query_as("SELECT name, seq FROM sqlite_sequence ORDER BY name")
            .fetch_all(&legacy.pool)
            .await
            .expect("old allocator floors");
    let old_migrations: Vec<(i64, String, Vec<u8>)> = sqlx::query_as(
        "SELECT version, description, checksum FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(&legacy.pool)
    .await
    .expect("old migration ledger");
    legacy.close().await;

    let migrated = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("ordinary open runs new migration");
    assert_eq!(
        migrated
            .get_provider_effect(&intent.key)
            .await
            .expect("migrated effect")
            .expect("effect"),
        before
    );
    assert_eq!(
        migrated
            .recovery_store_id()
            .await
            .expect("retained store id")
            .as_deref(),
        Some("store:observation-migration")
    );
    let new_allocators: Vec<(String, i64)> =
        sqlx::query_as("SELECT name, seq FROM sqlite_sequence ORDER BY name")
            .fetch_all(&migrated.pool)
            .await
            .expect("migrated allocator floors");
    assert_eq!(new_allocators, old_allocators);
    let new_migrations: Vec<(i64, String, Vec<u8>)> = sqlx::query_as(
        "SELECT version, description, checksum FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(&migrated.pool)
    .await
    .expect("migrated ledger");
    assert_eq!(
        &new_migrations[..old_migrations.len()],
        old_migrations.as_slice()
    );
    assert_eq!(new_migrations.last().expect("new migration").0, 16);
    let new_snapshot = migrated
        .recovery_snapshot()
        .await
        .expect("new checkpoint input");
    assert_ne!(
        new_snapshot, old_snapshot,
        "old signed checkpoint cannot match the migrated store"
    );
    let mut compared = new_snapshot.clone();
    compared.migration_set_sha256 = old_snapshot.migration_set_sha256.clone();
    assert_eq!(
        compared, old_snapshot,
        "migration changed original effect history"
    );
    let refusal = migrated
        .dispatch_provider_effect_qualification(&NoDispatch, &intent)
        .await
        .expect("existing effect remains fenced");
    assert!(!refusal.dispatch_attempted);
    assert!(!refusal.dispatch_claimed);
    assert_eq!(refusal.state, ProviderEffectState::Indeterminate);

    migrated
        .append_provider_effect_ack_from_source(&accepted, ProviderEffectAckSource::StatusLookup)
        .await
        .expect("new observation resolves the original operation");
    let observed = migrated
        .get_provider_effect(&intent.key)
        .await
        .expect("new observation")
        .expect("effect");
    assert_eq!(observed.state(), ProviderEffectState::Accepted);
    let last = observed.acknowledgements.last().expect("new ACK");
    assert!(
        last.seq
            > old_allocators
                .iter()
                .find(|(name, _)| name == "provider_effect_acknowledgements")
                .expect("old floor")
                .1
    );
    migrated.close().await;
    let reopened = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("reopen migrated history");
    assert_eq!(
        reopened
            .get_provider_effect(&intent.key)
            .await
            .expect("reopened effect")
            .expect("effect"),
        observed
    );
}

#[tokio::test]
async fn observation_schema_rejects_reintroduced_content_deduplication() {
    for statement in [
        "CREATE UNIQUE INDEX imported_effect_ack_dedup ON provider_effect_acknowledgements(effect_key, provider_operation_id_sha256, status, payload_sha256)",
        "CREATE UNIQUE INDEX imported_effect_unknown_dedup ON provider_effect_uncertainties(effect_key, payload_sha256, reason_code)",
    ] {
        let temp = tempfile::TempDir::new().expect("temp dir");
        let sqlite = SqliteConfig::new_for_testing(
            AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
        );
        let store = HeptaEvidenceStore::open(&sqlite)
            .await
            .expect("open evidence");
        sqlx::query(statement)
            .execute(&store.pool)
            .await
            .expect("introduce schema drift");
        store.close().await;
        assert!(matches!(HeptaEvidenceStore::open(&sqlite).await,
            Err(EvidenceError::Corrupt(detail)) if detail.contains("content-unique index")));
    }
}

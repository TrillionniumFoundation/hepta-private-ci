use std::sync::Arc;
use std::time::Duration;

use tempfile::TempDir;
use tokio::sync::Notify;

use super::*;
use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

#[tokio::test]
async fn schema_change_after_admission_cannot_change_the_integrity_query_snapshot() {
    let temp = TempDir::new().expect("temp directory");
    let owner = agent_id(106);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("owner store");
    let admitted = Arc::new(Notify::new());
    let resume = Arc::new(Notify::new());
    let pending_pool = store.pool.clone();
    let pending_owner = owner.clone();
    let pending_admitted = Arc::clone(&admitted);
    let pending_resume = Arc::clone(&resume);
    let pending = tokio::spawn(async move {
        let mut transaction = pending_pool.begin().await.map_err(unavailable)?;
        admit_snapshot(&mut transaction).await?;
        pending_admitted.notify_one();
        pending_resume.notified().await;
        // This is the actual reopen query phase, including quick_check, FK
        // checks, migration rows and metadata. It retains the admitted cut.
        verify_admitted_snapshot(&mut transaction, &pending_owner).await?;
        let probe_exists: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM sqlite_schema WHERE name = 'cognitive_verifier_probe')",
        )
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok::<_, CognitiveStoreError>(probe_exists)
    });
    tokio::time::timeout(Duration::from_secs(10), admitted.notified())
        .await
        .expect("the real verification snapshot must be admitted");
    // Harmless DDL commits through another pooled SQLite connection. No
    // malicious expression is needed to prove that the catalog has advanced.
    tokio::time::timeout(
        Duration::from_secs(10),
        sqlx::query("CREATE VIEW cognitive_verifier_probe AS SELECT 1 AS value")
            .execute(&store.pool),
    )
    .await
    .expect("concurrent DDL must finish")
    .expect("harmless view committed after admission");
    resume.notify_one();
    assert!(
        !tokio::time::timeout(Duration::from_secs(10), pending)
            .await
            .expect("integrity queries must finish")
            .expect("verification task")
            .expect("the original admitted snapshot remains valid")
    );
    // The next independently admitted snapshot sees and rejects the new view.
    assert!(matches!(
        verify_store(&store.pool, &owner).await,
        Err(CognitiveStoreError::Corrupt(message))
            if message.contains("unregistered cognitive executable schema")
    ));
    store.pool.close().await;
}

#[tokio::test]
async fn every_independent_verifier_admits_schema_before_its_first_domain_query() {
    let temp = TempDir::new().expect("temp directory");
    let owner = agent_id(107);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("owner store");
    sqlx::query("CREATE VIEW cognitive_verifier_probe AS SELECT 1 AS value")
        .execute(&store.pool)
        .await
        .expect("harmless unregistered schema");
    let results = [
        integrity::verify_ledger_contents(&store.pool).await,
        verify_revision_fact_digests(&store.pool, &owner).await,
        verify_current_projection_contents(&store.pool, &owner).await,
        crate::logical_turn_registry::verify_logical_turn_registry(&store.pool, &owner).await,
        crate::local_lease_outbox::verify_local_lease_outbox(&store.pool, &owner).await,
        crate::local_compact_executor::verify_local_compact_events(&store.pool, &owner).await,
    ];
    for result in results {
        assert!(matches!(
            result,
            Err(CognitiveStoreError::Corrupt(message))
                if message.contains("unregistered cognitive executable schema")
        ));
    }
    store.pool.close().await;
}

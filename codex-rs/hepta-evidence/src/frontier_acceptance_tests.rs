use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::EvidenceAcceptedFrontierV1;
use super::EvidenceFrontierAcceptanceDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn accepted(generation: u64, marker: &[u8]) -> EvidenceAcceptedFrontierV1 {
    EvidenceAcceptedFrontierV1 {
        store_id: "store:kernel-evidence".to_string(),
        frontier_generation: generation,
        frontier_sha256: Sha256Digest::for_bytes(marker),
        backend_identity_sha256: Sha256Digest::for_bytes(b"backend-identity"),
        accepted_at_unix_ms: 1_900_000_000_000 + generation,
    }
}

#[tokio::test]
async fn acceptance_is_monotonic_and_exact_duplicates_are_noops() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence store");
    let first = accepted(7, b"frontier-seven");
    assert_eq!(
        store
            .accept_recovery_frontier(&first)
            .await
            .expect("accept first frontier"),
        EvidenceFrontierAcceptanceDisposition::Inserted
    );
    assert_eq!(
        store
            .accept_recovery_frontier(&first)
            .await
            .expect("re-admit exact frontier"),
        EvidenceFrontierAcceptanceDisposition::AlreadyPresent
    );
    assert_eq!(
        store
            .latest_accepted_frontier(&first.store_id)
            .await
            .expect("read latest accepted frontier"),
        Some(first.clone())
    );

    let next = accepted(9, b"frontier-nine");
    assert_eq!(
        store
            .accept_recovery_frontier(&next)
            .await
            .expect("accept later independently published frontier"),
        EvidenceFrontierAcceptanceDisposition::Inserted
    );
    assert_eq!(
        store
            .latest_accepted_frontier(&next.store_id)
            .await
            .expect("read advanced frontier"),
        Some(next)
    );
}

#[tokio::test]
async fn rollback_and_same_generation_identity_changes_fail_closed() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence store");
    let current = accepted(5, b"frontier-five");
    store
        .accept_recovery_frontier(&current)
        .await
        .expect("accept current frontier");

    let rollback = accepted(4, b"frontier-four");
    assert!(matches!(
        store.accept_recovery_frontier(&rollback).await,
        Err(EvidenceError::InvalidRecord(message)) if message.contains("rolls back")
    ));

    let conflicting = accepted(5, b"different-frontier-five");
    assert!(matches!(
        store.accept_recovery_frontier(&conflicting).await,
        Err(EvidenceError::IdempotencyConflict { .. })
    ));
    assert_eq!(
        store
            .latest_accepted_frontier(&current.store_id)
            .await
            .expect("read unchanged frontier"),
        Some(current)
    );
}

#[tokio::test]
async fn accepted_frontier_history_is_database_immutable() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence store");
    store
        .accept_recovery_frontier(&accepted(1, b"frontier-one"))
        .await
        .expect("accept frontier");

    let update = sqlx::query(
        "UPDATE evidence_frontier_acceptance
         SET frontier_sha256 = ?
         WHERE store_id = ?",
    )
    .bind(Sha256Digest::for_bytes(b"tampered").as_str())
    .bind("store:kernel-evidence")
    .execute(&store.pool)
    .await;
    assert!(update.is_err());

    let delete = sqlx::query(
        "DELETE FROM evidence_frontier_acceptance WHERE store_id = ?",
    )
    .bind("store:kernel-evidence")
    .execute(&store.pool)
    .await;
    assert!(delete.is_err());
    assert!(
        store
            .latest_accepted_frontier("store:kernel-evidence")
            .await
            .expect("read immutable row")
            .is_some()
    );
}

#[tokio::test]
async fn a_database_cannot_be_rebound_to_another_recovery_store() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence store");
    store
        .accept_recovery_frontier(&accepted(1, b"frontier-one"))
        .await
        .expect("bind first store");
    let other = EvidenceAcceptedFrontierV1 {
        store_id: "store:other-evidence".to_string(),
        frontier_generation: 1,
        frontier_sha256: Sha256Digest::for_bytes(b"other-frontier"),
        backend_identity_sha256: Sha256Digest::for_bytes(b"backend-identity"),
        accepted_at_unix_ms: 1_900_000_000_001,
    };
    assert!(matches!(
        store.accept_recovery_frontier(&other).await,
        Err(EvidenceError::IdempotencyConflict { record_id })
            if record_id == "evidence_recovery_identity"
    ));
}

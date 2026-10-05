use super::*;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

async fn fixture() -> (TempDir, HeptaEvidenceStore, EvidenceAcceptedFrontierV1) {
    let temp = TempDir::new().expect("temp");
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute"),
    );
    let store = HeptaEvidenceStore::open(&config).await.expect("store");
    store
        .bind_recovery_store_id("store:atomic")
        .await
        .expect("enroll");
    let accepted = EvidenceAcceptedFrontierV1 {
        store_id: "store:atomic".to_string(),
        frontier_generation: 1,
        frontier_sha256: Sha256Digest::for_bytes(b"frontier-1"),
        backend_identity_sha256: Sha256Digest::for_bytes(b"backend"),
        accepted_at_unix_ms: 1,
    };
    (temp, store, accepted)
}

async fn mutate_replay(store: &HeptaEvidenceStore) {
    sqlx::query(
        "INSERT INTO authbus_replay_sequences
        (issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest)
        VALUES ('issuer:atomic', ?, 'subject:atomic', ?, ?, ?)",
    )
    .bind(1_u64.to_be_bytes().to_vec())
    .bind(vec![1_u8; 32])
    .bind(1_u64.to_be_bytes().to_vec())
    .bind(vec![2_u8; 32])
    .execute(&store.pool)
    .await
    .expect("replay mutation");
}

#[tokio::test]
async fn atomic_acceptance_rejects_mutation_after_snapshot_without_recording_acceptance() {
    let (_temp, store, accepted) = fixture().await;
    let snapshot = store
        .authenticated_recovery_snapshot()
        .await
        .expect("snapshot");
    mutate_replay(&store).await;
    assert!(
        store
            .accept_recovery_frontier_at_snapshot(&accepted, &snapshot)
            .await
            .is_err()
    );
    assert!(
        store
            .latest_accepted_frontier("store:atomic")
            .await
            .expect("read")
            .is_none()
    );
}

#[tokio::test]
async fn identical_retry_revalidates_snapshot_instead_of_reusing_old_acceptance() {
    let (_temp, store, accepted) = fixture().await;
    let snapshot = store
        .authenticated_recovery_snapshot()
        .await
        .expect("snapshot");
    assert_eq!(
        store
            .accept_recovery_frontier_at_snapshot(&accepted, &snapshot)
            .await
            .expect("accept"),
        EvidenceFrontierAcceptanceDisposition::Inserted
    );
    assert_eq!(
        store
            .accept_recovery_frontier_at_snapshot(&accepted, &snapshot)
            .await
            .expect("retry"),
        EvidenceFrontierAcceptanceDisposition::AlreadyPresent
    );
    mutate_replay(&store).await;
    assert!(
        store
            .accept_recovery_frontier_at_snapshot(&accepted, &snapshot)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn atomic_acceptance_rejects_legacy_snapshot_and_backend_substitution() {
    let (_temp, store, accepted) = fixture().await;
    let legacy = store.recovery_snapshot().await.expect("legacy");
    assert!(
        store
            .accept_recovery_frontier_at_snapshot(&accepted, &legacy)
            .await
            .is_err()
    );
    let snapshot = store
        .authenticated_recovery_snapshot()
        .await
        .expect("snapshot");
    store
        .accept_recovery_frontier_at_snapshot(&accepted, &snapshot)
        .await
        .expect("accept");
    let mut substituted = accepted;
    substituted.frontier_generation = 2;
    substituted.backend_identity_sha256 = Sha256Digest::for_bytes(b"replacement");
    assert!(
        store
            .accept_recovery_frontier_at_snapshot(&substituted, &snapshot)
            .await
            .is_err()
    );
}

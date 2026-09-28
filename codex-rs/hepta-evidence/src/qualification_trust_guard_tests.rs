use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::*;
use crate::EvidenceAcceptedFrontierV1;
use crate::EvidenceTrustGenerationAcceptanceV1;
use crate::HeptaEvidenceStore;

async fn open(temp: &TempDir) -> HeptaEvidenceStore {
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    );
    HeptaEvidenceStore::open(&config)
        .await
        .expect("migrated store")
}

async fn accept(
    store: &HeptaEvidenceStore,
    generation: u64,
    digest: &Sha256Digest,
    predecessor: Option<Sha256Digest>,
) {
    let frontier = EvidenceAcceptedFrontierV1 {
        store_id: "store:guard".to_string(),
        frontier_generation: generation,
        frontier_sha256: Sha256Digest::for_bytes(&generation.to_be_bytes()),
        backend_identity_sha256: Sha256Digest::for_bytes(b"backend:guard"),
        accepted_at_unix_ms: generation * 100,
    };
    let trust = EvidenceTrustGenerationAcceptanceV1 {
        store_id: frontier.store_id.clone(),
        agent_id: "agent:guard".to_string(),
        registry_generation: generation,
        registry_sha256: digest.clone(),
        predecessor_sha256: predecessor,
        accepted_frontier_generation: frontier.frontier_generation,
        accepted_frontier_sha256: frontier.frontier_sha256.clone(),
        backend_identity_sha256: frontier.backend_identity_sha256.clone(),
        accepted_at_unix_ms: frontier.accepted_at_unix_ms,
    };
    let snapshot = store
        .authenticated_recovery_snapshot()
        .await
        .expect("snapshot");
    store
        .accept_production_generation_at_snapshot(&frontier, &snapshot, &trust)
        .await
        .expect("atomic production acceptance");
}

async fn allowed(
    store: &HeptaEvidenceStore,
    generation: Option<u64>,
    digest: Option<&Sha256Digest>,
) -> bool {
    let mut transaction = store.pool.begin().await.expect("read epoch");
    let result = require_admitted_trust(&mut transaction, generation, digest).await;
    transaction.rollback().await.expect("finish read epoch");
    result.is_ok()
}

#[tokio::test]
async fn accepted_trust_cannot_downgrade_to_legacy_or_unaccepted_generation() {
    let temp = TempDir::new().expect("temp");
    let store = open(&temp).await;
    assert!(allowed(&store, None, None).await);
    store
        .bind_recovery_store_id("store:guard")
        .await
        .expect("enroll");
    let first = Sha256Digest::for_bytes(b"trust:one");
    accept(&store, 1, &first, None).await;
    assert!(allowed(&store, Some(1), Some(&first)).await);
    assert!(!allowed(&store, None, None).await);
    assert!(!allowed(&store, Some(2), Some(&first)).await);
    assert!(!allowed(&store, Some(1), Some(&Sha256Digest::for_bytes(b"other"))).await);
    assert!(!allowed(&store, Some(1), None).await);
    assert!(!allowed(&store, None, Some(&first)).await);
    store.close().await;
}

#[tokio::test]
async fn restored_old_file_cannot_undo_durable_trust_rotation_after_reopen() {
    let temp = TempDir::new().expect("temp");
    let store = open(&temp).await;
    store
        .bind_recovery_store_id("store:guard")
        .await
        .expect("enroll");
    let first = Sha256Digest::for_bytes(b"trust:one");
    let second = Sha256Digest::for_bytes(b"trust:two");
    accept(&store, 1, &first, None).await;
    accept(&store, 2, &second, Some(first.clone())).await;
    store.close().await;
    let reopened = open(&temp).await;
    assert!(!allowed(&reopened, Some(1), Some(&first)).await);
    assert!(allowed(&reopened, Some(2), Some(&second)).await);
    reopened.close().await;
}

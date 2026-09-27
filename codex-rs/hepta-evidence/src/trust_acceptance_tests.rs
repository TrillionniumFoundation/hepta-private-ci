use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::*;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn frontier(
    generation: u64,
    digest: Sha256Digest,
    backend: Sha256Digest,
    accepted_at: u64,
) -> EvidenceAcceptedFrontierV1 {
    EvidenceAcceptedFrontierV1 {
        store_id: "store:trust".to_string(),
        frontier_generation: generation,
        frontier_sha256: digest,
        backend_identity_sha256: backend,
        accepted_at_unix_ms: accepted_at,
    }
}

fn trust(
    generation: u64,
    digest: Sha256Digest,
    predecessor: Option<Sha256Digest>,
    frontier: &EvidenceAcceptedFrontierV1,
) -> EvidenceTrustGenerationAcceptanceV1 {
    EvidenceTrustGenerationAcceptanceV1 {
        store_id: frontier.store_id.clone(),
        agent_id: "agent:trust".to_string(),
        registry_generation: generation,
        registry_sha256: digest,
        predecessor_sha256: predecessor,
        accepted_frontier_generation: frontier.frontier_generation,
        accepted_frontier_sha256: frontier.frontier_sha256.clone(),
        backend_identity_sha256: frontier.backend_identity_sha256.clone(),
        accepted_at_unix_ms: frontier.accepted_at_unix_ms,
    }
}

#[tokio::test]
async fn trust_rotation_is_monotonic_and_atomic_with_frontier_acceptance() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&config(&temp)).await.expect("open store");
    store
        .bind_recovery_store_id("store:trust")
        .await
        .expect("enroll store");
    let snapshot = store
        .authenticated_recovery_snapshot()
        .await
        .expect("authenticated snapshot");
    let backend = Sha256Digest::for_bytes(b"backend:trust");
    let trust_one_digest = Sha256Digest::for_bytes(b"trust:generation:1");
    let frontier_one = frontier(
        1,
        Sha256Digest::for_bytes(b"frontier:trust:1"),
        backend.clone(),
        100,
    );
    let trust_one = trust(1, trust_one_digest.clone(), None, &frontier_one);
    let inserted = store
        .accept_production_generation_at_snapshot(&frontier_one, &snapshot, &trust_one)
        .await
        .expect("accept first generation");
    assert_eq!(inserted.trust, EvidenceTrustAcceptanceDisposition::Inserted);
    assert_eq!(
        inserted.frontier,
        EvidenceFrontierAcceptanceDisposition::Inserted
    );
    let retry = store
        .accept_production_generation_at_snapshot(&frontier_one, &snapshot, &trust_one)
        .await
        .expect("idempotent acceptance");
    assert_eq!(
        retry.trust,
        EvidenceTrustAcceptanceDisposition::AlreadyPresent
    );
    assert_eq!(
        retry.frontier,
        EvidenceFrontierAcceptanceDisposition::AlreadyPresent
    );

    let frontier_two = frontier(
        2,
        Sha256Digest::for_bytes(b"frontier:trust:2"),
        backend.clone(),
        200,
    );
    let skipped = trust(
        3,
        Sha256Digest::for_bytes(b"trust:generation:3"),
        Some(trust_one_digest.clone()),
        &frontier_two,
    );
    assert!(
        store
            .accept_production_generation_at_snapshot(&frontier_two, &snapshot, &skipped)
            .await
            .is_err(),
        "trust generations cannot skip"
    );
    assert_eq!(
        store
            .latest_accepted_frontier("store:trust")
            .await
            .expect("frontier read")
            .expect("accepted frontier")
            .frontier_generation,
        1,
        "failed trust rotation must roll back the frontier insert"
    );

    let trust_two_digest = Sha256Digest::for_bytes(b"trust:generation:2");
    let trust_two = trust(
        2,
        trust_two_digest,
        Some(trust_one_digest.clone()),
        &frontier_two,
    );
    store
        .accept_production_generation_at_snapshot(&frontier_two, &snapshot, &trust_two)
        .await
        .expect("accept linked rotation");
    assert_eq!(
        store
            .latest_accepted_trust_generation("store:trust")
            .await
            .expect("trust read")
            .expect("accepted trust")
            .registry_generation,
        2
    );

    let frontier_three = frontier(
        3,
        Sha256Digest::for_bytes(b"frontier:trust:3"),
        backend,
        300,
    );
    let rollback = trust(1, trust_one_digest, None, &frontier_three);
    assert!(
        store
            .accept_production_generation_at_snapshot(&frontier_three, &snapshot, &rollback)
            .await
            .is_err(),
        "old trust cannot be restored under a newer frontier"
    );
}

#[tokio::test]
async fn trust_and_frontier_must_share_exact_backend_and_identity() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&config(&temp)).await.expect("open store");
    store
        .bind_recovery_store_id("store:trust")
        .await
        .expect("enroll store");
    let snapshot = store
        .authenticated_recovery_snapshot()
        .await
        .expect("snapshot");
    let accepted = frontier(
        1,
        Sha256Digest::for_bytes(b"frontier"),
        Sha256Digest::for_bytes(b"backend:a"),
        100,
    );
    let mut trust = trust(
        1,
        Sha256Digest::for_bytes(b"trust"),
        None,
        &accepted,
    );
    trust.backend_identity_sha256 = Sha256Digest::for_bytes(b"backend:b");
    assert!(
        store
            .accept_production_generation_at_snapshot(&accepted, &snapshot, &trust)
            .await
            .is_err()
    );
    assert!(
        store
            .latest_accepted_trust_generation("store:trust")
            .await
            .expect("trust read")
            .is_none()
    );
    assert!(
        store
            .latest_accepted_frontier("store:trust")
            .await
            .expect("frontier read")
            .is_none()
    );
}

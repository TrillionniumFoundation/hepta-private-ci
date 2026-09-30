use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use tempfile::TempDir;

use super::FederationPeerPools;
use super::MAX_INTEGRITY_AGE;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::FederatedMemoryReader;
use crate::FederatedRevalidationStatus;
use crate::FederationConsumerAccess;
use crate::FederationGrantRequest;
use crate::FederationGrantScope;
use crate::FederationRevalidationDrift;
use crate::ForgetMemoryDraft;
use crate::MemoryDraft;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

#[tokio::test]
async fn concurrent_discovery_reuses_one_pool_and_observes_live_revocation() {
    let temp = TempDir::new().expect("temp dir");
    let owner_layout = layout(&temp, &agent_id(70));
    let consumer_id = agent_id(71);
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let owner_access = CognitiveAccess::agent_private(owner_layout.agent_id().clone());
    let consumer_workspace = workspace("cached-consumer");
    let grant = owner
        .grant_federated_recall(
            &owner_access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(
                    CognitiveScope::AgentPrivate,
                    consumer_workspace.clone(),
                ),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant");
    let pools = FederationPeerPools::default();
    let (first, second) = tokio::join!(pools.get(&owner_layout), pools.get(&owner_layout));
    let first = first.expect("first peer");
    assert!(Arc::ptr_eq(&first, &second.expect("second peer")));
    assert!(Arc::ptr_eq(
        &first,
        &pools.get(&owner_layout).await.expect("reused peer")
    ));
    let reader = FederatedMemoryReader::discover_cached(&pools, &owner_layout, &consumer_id, 150)
        .await
        .expect("discover")
        .pop()
        .expect("reader");
    owner
        .revoke_federated_recall(&owner_access, &grant, 151)
        .await
        .expect("revoke");
    assert!(
        FederatedMemoryReader::discover_cached(&pools, &owner_layout, &consumer_id, 152)
            .await
            .expect("fresh grant query")
            .is_empty()
    );
    let access = FederationConsumerAccess::new(consumer_id, consumer_workspace);
    assert!(matches!(
        reader
            .retrieve(&access, &RetrievalRequest::new("fact", 152))
            .await,
        Err(crate::CognitiveStoreError::AccessDenied(_))
    ));
    assert!(Arc::ptr_eq(
        &first,
        &pools
            .get(&owner_layout)
            .await
            .expect("revocation retains pool")
    ));
}

#[tokio::test]
async fn cached_reader_revalidates_deleted_memory_before_send() {
    let temp = TempDir::new().expect("temp dir");
    let owner_layout = layout(&temp, &agent_id(72));
    let consumer_id = agent_id(73);
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let owner_access = CognitiveAccess::agent_private(owner_layout.agent_id().clone());
    let citation = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "cache-fact",
                "A cached pool must still observe a withdrawn fact.",
            ),
        )
        .await
        .expect("source");
    let memory = owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "cache-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "A cached pool must still observe a withdrawn fact.",
                    citation.clone(),
                ),
            },
        )
        .await
        .expect("memory");
    let consumer_workspace = workspace("deleted-consumer");
    owner
        .grant_federated_recall(
            &owner_access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(
                    CognitiveScope::AgentPrivate,
                    consumer_workspace.clone(),
                ),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant");
    let pools = FederationPeerPools::default();
    let reader = FederatedMemoryReader::discover_cached(&pools, &owner_layout, &consumer_id, 150)
        .await
        .expect("discover")
        .pop()
        .expect("reader");
    let access = FederationConsumerAccess::new(consumer_id, consumer_workspace);
    let prepared = reader
        .retrieve(&access, &RetrievalRequest::new("withdrawn fact", 150))
        .await
        .expect("retrieve")
        .candidates
        .pop()
        .expect("candidate")
        .revalidation;
    owner
        .forget_memory(
            &owner_access,
            &memory.id.memory_id,
            1,
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "explicit withdrawal".to_string(),
                valid_from_unix_seconds: 151,
                citations: vec![citation],
            },
        )
        .await
        .expect("forget");
    assert_eq!(
        reader
            .revalidate(&access, &prepared, 152)
            .await
            .expect("send revalidation"),
        FederatedRevalidationStatus::Stale(FederationRevalidationDrift::Memory)
    );
    assert!(
        reader
            .retrieve(&access, &RetrievalRequest::new("withdrawn fact", 152))
            .await
            .expect("retrieve after deletion")
            .candidates
            .is_empty()
    );
}

#[tokio::test]
async fn integrity_maintenance_quarantines_and_readmits_a_repaired_store() {
    let temp = TempDir::new().expect("temp dir");
    let owner_layout = layout(&temp, &agent_id(74));
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let pools = FederationPeerPools::default();
    let peer = pools.get(&owner_layout).await.expect("admitted peer");
    // A migration receipt mutation changes no file identity or schema cookie.
    // Reuse performs bounded identity queries; full semantic checks belong to
    // admission and maintenance, rather than repeating on every request.
    sqlx::query("UPDATE _sqlx_migrations SET success = 0 WHERE version = 1")
        .execute(&owner.pool)
        .await
        .expect("corrupt migration receipt");
    assert!(Arc::ptr_eq(
        &peer,
        &pools.get(&owner_layout).await.expect("same admitted pool")
    ));
    assert!(
        pools
            .maintain(std::slice::from_ref(&owner_layout), Duration::from_secs(10))
            .await
            .is_err()
    );
    assert!(peer.owner.pool.is_closed());
    assert!(peer.validate().await.is_err());
    assert!(pools.get(&owner_layout).await.is_err());
    sqlx::query("UPDATE _sqlx_migrations SET success = 1 WHERE version = 1")
        .execute(&owner.pool)
        .await
        .expect("repair migration receipt");
    assert!(pools.get(&owner_layout).await.is_err());
    assert_eq!(
        pools
            .maintain(std::slice::from_ref(&owner_layout), Duration::from_secs(10))
            .await
            .expect("readmit repaired store"),
        1
    );
    assert!(!Arc::ptr_eq(
        &peer,
        &pools.get(&owner_layout).await.expect("new admitted pool")
    ));
}

#[tokio::test]
async fn expired_integrity_admission_requires_complete_maintenance() {
    let temp = TempDir::new().expect("temp dir");
    let owner_layout = layout(&temp, &agent_id(75));
    let _owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let pools = FederationPeerPools::default();
    let peer = pools.get(&owner_layout).await.expect("peer");
    *peer.verified_at.lock().expect("verification clock") = Instant::now() - MAX_INTEGRITY_AGE;
    assert!(peer.validate().await.is_err());
    assert!(pools.get(&owner_layout).await.is_err());
    assert_eq!(
        pools
            .maintain(std::slice::from_ref(&owner_layout), Duration::from_secs(10))
            .await
            .expect("refresh integrity"),
        1
    );
    pools.get(&owner_layout).await.expect("refreshed peer");
}

#[cfg(unix)]
#[tokio::test]
async fn recovered_active_generation_invalidates_old_handles_and_reopens_exact_target() {
    use std::os::unix::fs::PermissionsExt;
    let temp = TempDir::new().expect("temp dir");
    let owner_layout = layout(&temp, &agent_id(76));
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let pools = FederationPeerPools::default();
    let old = pools.get(&owner_layout).await.expect("original peer");
    let candidate = owner_layout
        .cognitive_root()
        .join(format!("cognitive_recovered_v1_{}.sqlite3", "a".repeat(64)));
    sqlx::query("VACUUM INTO ?")
        .bind(candidate.to_string_lossy().as_ref())
        .execute(&owner.pool)
        .await
        .expect("consistent replacement generation");
    std::fs::set_permissions(&candidate, std::fs::Permissions::from_mode(0o600))
        .expect("private target");
    crate::cognitive_store::publish_active_database(owner_layout.cognitive_root(), &candidate)
        .expect("publish recovery pointer");
    assert!(old.validate().await.is_err());
    let current = pools
        .get(&owner_layout)
        .await
        .expect("current recovered generation");
    assert_eq!(current.owner.path(), candidate);
    assert!(!Arc::ptr_eq(&old, &current));
    assert!(old.owner.pool.is_closed());
}

#[cfg(unix)]
#[tokio::test]
async fn replacing_the_same_database_path_invalidates_an_open_connection() {
    let temp = TempDir::new().expect("temp dir");
    let owner_layout = layout(&temp, &agent_id(77));
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let pools = FederationPeerPools::default();
    let old = pools.get(&owner_layout).await.expect("original peer");
    let replacement = owner_layout.cognitive_root().join("replacement.sqlite3");
    sqlx::query("VACUUM INTO ?")
        .bind(replacement.to_string_lossy().as_ref())
        .execute(&owner.pool)
        .await
        .expect("replacement copy");
    owner.pool.close().await;
    std::fs::rename(&replacement, owner.path()).expect("atomic replacement");
    assert!(old.validate().await.is_err());
    let new = pools.get(&owner_layout).await.expect("replacement peer");
    assert!(!Arc::ptr_eq(&old, &new));
    assert!(old.owner.pool.is_closed());
}

#[tokio::test]
async fn schema_changes_require_readmission_and_removed_enrollment_closes_readers() {
    let temp = TempDir::new().expect("temp dir");
    let owner_layout = layout(&temp, &agent_id(78));
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let pools = FederationPeerPools::default();
    let old = pools.get(&owner_layout).await.expect("peer");
    sqlx::query("DROP INDEX memory_federation_consumer_heads")
        .execute(&owner.pool)
        .await
        .expect("change schema");
    assert!(old.validate().await.is_err());
    assert!(pools.get(&owner_layout).await.is_err());
    assert!(
        pools
            .maintain(std::slice::from_ref(&owner_layout), Duration::from_secs(10))
            .await
            .is_err()
    );
    assert_eq!(
        pools
            .maintain(&[], Duration::from_secs(1))
            .await
            .expect("remove enrollment"),
        0
    );
    assert!(pools.slots.lock().expect("slots").is_empty());
    assert!(old.owner.pool.is_closed());
}

#[tokio::test]
async fn maintenance_deadline_includes_waiting_for_a_busy_admission() {
    let pools = FederationPeerPools::default();
    let temp = TempDir::new().expect("temp dir");
    let owner_layout = layout(&temp, &agent_id(79));
    let slot = pools.slot(owner_layout.agent_id()).expect("slot");
    let _busy = slot.lock().await;
    let result = tokio::time::timeout(
        Duration::from_secs(1),
        pools.maintain(
            std::slice::from_ref(&owner_layout),
            Duration::from_millis(5),
        ),
    )
    .await
    .expect("bounded maintenance");
    assert!(result.is_err());
}

#[test]
fn residency_rejects_more_owners_without_allocating_more_slots() {
    let pools = FederationPeerPools::default();
    for owner in 0..super::MAX_RESIDENT_PEERS {
        pools
            .slot(&agent_id(u8::try_from(owner).expect("fixture owner")))
            .expect("bounded slot");
    }
    assert!(pools.slot(&agent_id(250)).is_err());
    assert_eq!(
        pools.slots.lock().expect("slots").len(),
        super::MAX_RESIDENT_PEERS
    );
}

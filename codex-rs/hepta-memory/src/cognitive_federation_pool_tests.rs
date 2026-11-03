use super::*;

use tempfile::TempDir;

use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::workspace;

struct Fixture {
    _temp: TempDir,
    owner_layout: HeptaAgentLayout,
    owner: CognitiveStore,
    owner_access: CognitiveAccess,
    consumer_id: AgentId,
    grant: FederationGrantRequest,
    reader: FederatedMemoryReader,
}

async fn fixture() -> Fixture {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(230);
    let consumer_id = agent_id(231);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout).await.expect("owner");
    let owner_access = CognitiveAccess::agent_private(owner_id);
    let grant = FederationGrantRequest {
        consumer_agent_id: consumer_id.clone(),
        scope: FederationGrantScope::new(CognitiveScope::AgentPrivate, workspace("pool-authority")),
        effective_at_unix_seconds: 100,
        expires_at_unix_seconds: 1_000,
    };
    owner
        .grant_federated_recall(&owner_access, &grant)
        .await
        .expect("grant");
    let reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("discover")
        .pop()
        .expect("reader");
    Fixture {
        _temp: temp,
        owner_layout,
        owner,
        owner_access,
        consumer_id,
        grant,
        reader,
    }
}

#[tokio::test]
async fn federation_pool_revalidation_reads_new_revoke_and_regrant_commits() {
    let f = fixture().await;
    let before = f
        .reader
        .rediscover_current(&f.owner_layout, &f.consumer_id, 150)
        .await
        .expect("current discovery");
    assert_eq!(before.len(), 1);
    #[cfg(unix)]
    assert!(Arc::ptr_eq(&f.reader.owner, &before[0].owner));
    assert_eq!(before[0].capability(), f.reader.capability());

    f.owner
        .revoke_federated_recall(&f.owner_access, f.reader.capability(), 151)
        .await
        .expect("committed revoke");
    assert!(
        f.reader
            .rediscover_current(&f.owner_layout, &f.consumer_id, 152)
            .await
            .expect("fresh revoked discovery")
            .is_empty()
    );
    let renewed = f
        .owner
        .grant_federated_recall(&f.owner_access, &f.grant)
        .await
        .expect("committed regrant");
    let after = f
        .reader
        .rediscover_current(&f.owner_layout, &f.consumer_id, 153)
        .await
        .expect("fresh regranted discovery");
    assert_eq!(after.len(), 1);
    assert_eq!(after[0].capability(), &renewed);
    assert!(renewed.generation() > f.reader.capability().generation());
    #[cfg(unix)]
    assert!(Arc::ptr_eq(&f.reader.owner, &after[0].owner));
}

#[tokio::test]
async fn federation_pool_revalidation_rechecks_schema_on_the_reused_connection() {
    let f = fixture().await;
    sqlx::query("DROP TRIGGER memory_federation_events_no_update")
        .execute(&f.owner.pool)
        .await
        .expect("simulate schema corruption");
    assert!(matches!(
        f.reader
            .rediscover_current(&f.owner_layout, &f.consumer_id, 150)
            .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

#[cfg(unix)]
#[tokio::test]
async fn federation_pool_revalidation_rejects_replaced_database_path() {
    let f = fixture().await;
    f.owner.close().await;
    let path = f.reader.owner.path();
    let replacement = path.with_extension("replacement");
    std::fs::copy(path, &replacement).expect("real replacement file");
    let before = capture_file_identity(path).expect("original file identity");
    std::fs::rename(&replacement, path).expect("replace pathname while old reader remains open");
    assert_ne!(
        capture_file_identity(path).expect("new file identity"),
        before
    );
    assert!(matches!(
        f.reader
            .rediscover_current(&f.owner_layout, &f.consumer_id, 150)
            .await,
        Err(CognitiveStoreError::Unavailable(_))
    ));
}

#[cfg(unix)]
#[tokio::test]
async fn federation_pool_revalidation_rejects_redirected_database_path() {
    let f = fixture().await;
    f.owner.close().await;
    let path = f.reader.owner.path();
    let moved = path.with_extension("retained");
    std::fs::rename(path, &moved).expect("retain actual original file");
    std::os::unix::fs::symlink(&moved, path).expect("replace database path with a redirect");
    assert!(matches!(
        f.reader
            .rediscover_current(&f.owner_layout, &f.consumer_id, 150)
            .await,
        Err(CognitiveStoreError::Invalid(_))
    ));
}

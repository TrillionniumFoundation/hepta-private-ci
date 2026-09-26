use super::FederatedReadSession;
use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use std::fs::OpenOptions;
use std::time::Duration;
use tempfile::TempDir;

#[tokio::test]
async fn cancelled_federation_session_retains_generation_until_connection_close() {
    let temp = TempDir::new().expect("temp dir");
    let layout = layout(&temp, &agent_id(196));
    let owner = CognitiveStore::open(&layout).await.expect("owner");
    let generation = CognitiveStore::bind_current_read_generation(&layout).expect("read fence");
    let session = FederatedReadSession::open(&layout, generation)
        .await
        .expect("read session");
    let pool = session.owner.pool.clone();
    let connection = pool.acquire().await.expect("in-flight SQLite connection");
    let recovery_fence = OpenOptions::new()
        .read(true)
        .write(true)
        .open(layout.cognitive_root().join(".cognitive-generation.lock"))
        .expect("existing fence");
    drop(session);
    assert!(
        recovery_fence.try_lock().is_err(),
        "cancellation must retain the read fence while SQLite is active"
    );
    drop(connection);
    pool.close().await;
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if recovery_fence.try_lock().is_ok() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("closed connection releases recovery fence");
    recovery_fence.unlock().expect("release recovery fence");
    owner.pool.close().await;
}

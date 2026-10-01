use super::*;
use crate::thread_state::ConnectionCapabilities;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn ephemeral_retention_survives_disconnect_and_returns_capacity_only_on_teardown()
-> anyhow::Result<()> {
    let server = start_mock_server().await;
    let original = test_codex()
        .with_config(|config| config.ephemeral = true)
        .build(&server)
        .await?;
    let other = test_codex()
        .with_config(|config| config.ephemeral = true)
        .build(&server)
        .await?;
    let manager = ThreadStateManager {
        // One permit exercises the same bounded acquisition/release path
        // without creating 33 full model runtimes in the fixture.
        ephemeral_retention_capacity: RetentionCapacity(Arc::new(Semaphore::new(1))),
        ..Default::default()
    };
    let connection = ConnectionId(1);
    let thread_id = original.session_configured.thread_id;
    let other_id = other.session_configured.thread_id;
    manager
        .connection_initialized(connection, ConnectionCapabilities::default())
        .await;
    for id in [thread_id, other_id] {
        assert!(manager.try_add_connection_to_thread(id, connection).await);
    }
    let watcher = manager
        .subscribe_to_ephemeral_retention(thread_id)
        .await
        .ok_or_else(|| anyhow::anyhow!("original watcher missing"))?;
    manager
        .retain_ephemeral_runtime(thread_id, &original.codex, connection, "original".into())
        .await
        .map_err(anyhow::Error::msg)?;
    manager
        .retain_ephemeral_runtime(thread_id, &original.codex, connection, "original".into())
        .await
        .map_err(anyhow::Error::msg)?;
    assert!(
        manager
            .retain_ephemeral_runtime(thread_id, &other.codex, connection, "original".into())
            .await
            .is_err()
    );
    assert!(
        manager
            .retain_ephemeral_runtime(thread_id, &original.codex, connection, "another".into())
            .await
            .is_err()
    );
    assert!(
        manager
            .retain_ephemeral_runtime(other_id, &other.codex, connection, "other".into())
            .await
            .is_err(),
        "capacity must reject before a new native effect can be admitted"
    );
    manager.remove_connection(connection).await;
    assert!(
        watcher
            .borrow()
            .as_ref()
            .is_some_and(|weak| weak.ptr_eq(&Arc::downgrade(&original.codex)))
    );
    assert_eq!(
        manager.ephemeral_retention_capacity.0.available_permits(),
        0
    );
    assert!(
        manager
            .retain_ephemeral_runtime(other_id, &other.codex, connection, "other".into())
            .await
            .is_err(),
        "a closed connection cannot install retention"
    );
    manager.remove_thread_state(thread_id).await;
    assert_eq!(
        manager.ephemeral_retention_capacity.0.available_permits(),
        1
    );
    manager
        .connection_initialized(connection, ConnectionCapabilities::default())
        .await;
    assert!(
        manager
            .try_add_connection_to_thread(other_id, connection)
            .await
    );
    manager
        .retain_ephemeral_runtime(other_id, &other.codex, connection, "other".into())
        .await
        .map_err(anyhow::Error::msg)?;
    original.codex.shutdown_and_wait().await?;
    other.codex.shutdown_and_wait().await?;
    manager.remove_thread_state(other_id).await;
    assert_eq!(
        manager.ephemeral_retention_capacity.0.available_permits(),
        1
    );
    Ok(())
}

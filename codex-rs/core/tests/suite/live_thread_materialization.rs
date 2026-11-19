use std::sync::Arc;

use anyhow::Result;
use codex_features::Feature;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_thread_store::ListTurnsParams;
use codex_thread_store::PersistContext;
use codex_thread_store::ReadThreadParams;
use codex_thread_store::SortDirection;
use codex_thread_store::StoredTurnItemsView;
use codex_thread_store::ThreadStoreError;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn materialize_thread_repairs_metadata_after_store_only_persist() -> Result<()> {
    let server = start_mock_server().await;
    let test = test_codex()
        .with_history_mode(ThreadHistoryMode::Paginated)
        .with_config(|config| {
            config
                .features
                .disable(Feature::BackgroundPaginatedRolloutMigration)
                .expect("disable background metadata repair for the partial-state fixture");
        })
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let state_db = test
        .codex
        .state_db()
        .expect("original thread metadata store");
    let path = test
        .codex
        .rollout_path()
        .expect("original live rollout path");
    assert!(!path.exists());
    assert!(state_db.get_thread(thread_id).await?.is_none());

    // Reproduce the interrupted boundary through the original store writer: JSONL and its
    // projection exist, but the live owner's pending create metadata has not been committed.
    test.thread_store
        .persist_thread(thread_id, PersistContext::Standard)
        .await?;
    assert!(path.exists());
    assert!(state_db.get_thread(thread_id).await?.is_none());
    let stored = test
        .thread_store
        .read_thread(ReadThreadParams {
            thread_id,
            include_archived: true,
            include_history: false,
        })
        .await?;
    assert_eq!(stored.history_mode, ThreadHistoryMode::Paginated);
    let params = ListTurnsParams {
        thread_id,
        include_archived: true,
        cursor: None,
        page_size: 5,
        sort_direction: SortDirection::Desc,
        items_view: StoredTurnItemsView::NotLoaded,
    };
    assert!(matches!(
        test.thread_store.list_turns(params.clone()).await,
        Err(ThreadStoreError::Unsupported {
            operation: "list_turns"
        })
    ));
    let canonical_bytes = tokio::fs::read(&path).await?;

    for _ in 0..2 {
        test.codex.materialize_thread().await?;
        let metadata = state_db
            .get_thread(thread_id)
            .await?
            .expect("owner metadata committed");
        assert_eq!(metadata.history_mode, ThreadHistoryMode::Paginated);
        let page = test.thread_store.list_turns(params.clone()).await?;
        assert_eq!(
            (
                page.turns.is_empty(),
                page.next_cursor,
                page.backwards_cursor
            ),
            (true, None, None)
        );
        assert_eq!(tokio::fs::read(&path).await?, canonical_bytes);
        assert!(Arc::ptr_eq(
            &test.codex,
            &test.thread_manager.get_thread(thread_id).await?
        ));
        assert_eq!(
            test.codex.session_configured().session_id,
            test.session_configured.session_id
        );
    }
    let requests = server
        .received_requests()
        .await
        .expect("mock request recorder");
    let response_requests = requests
        .iter()
        .filter(|request| request.method == "POST" && request.url.path().ends_with("/responses"))
        .count();
    assert_eq!(response_requests, 0);
    test.codex.shutdown_and_wait().await?;
    Ok(())
}

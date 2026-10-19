use super::*;
use crate::ThreadStore;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn bounded_history_rejects_huge_items_and_cumulative_bytes_without_partial_pages() {
    let (_home, store, thread_id) = store_with_mode(ThreadHistoryMode::Paginated).await;
    let db = history_db(&store).await;
    insert_turn(
        db,
        thread_id,
        "t",
        /*rollout_ordinal*/ 1,
        "completed",
        /*error_json*/ None,
        /*first_user_item_id*/ None,
        /*final_agent_item_id*/ None,
    )
    .await;
    insert_item(db, thread_id, "t", "i", /*rollout_ordinal*/ 2).await;
    let params = turn_params(
        thread_id,
        /*cursor*/ None,
        /*page_size*/ 1,
        SortDirection::Desc,
        StoredTurnItemsView::NotLoaded,
    );
    let initial = store
        .list_full_turns_bounded(params.clone())
        .await
        .expect("complete page");
    assert_eq!(initial.turns.len(), 1);
    assert_eq!(initial.turns[0].1.len(), 1);
    // UTF-8 bytes, not SQLite's character length, must determine the budget.
    sqlx::query("UPDATE thread_items SET item_json = ?")
        .bind("界".repeat(100_000))
        .execute(db)
        .await
        .expect("oversize item");
    assert!(matches!(
        store.list_full_turns_bounded(params.clone()).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "budgetExceeded"
        })
    ));
    sqlx::query("DELETE FROM thread_items")
        .execute(db)
        .await
        .expect("clear items");
    for ordinal in 2..=23 {
        insert_item(db, thread_id, "t", &format!("i-{ordinal}"), ordinal).await;
    }
    // Each row fits the single-row budget; the sum exceeds the request budget.
    sqlx::query("UPDATE thread_items SET item_json = ?")
        .bind("x".repeat(200_000))
        .execute(db)
        .await
        .expect("large bounded rows");
    assert!(matches!(
        store.list_full_turns_bounded(params).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "budgetExceeded"
        })
    ));
}

#[tokio::test]
async fn bounded_history_shares_row_budget_across_turns_and_rejects_pagination_bypass() {
    let (_home, store, thread_id) = store_with_mode(ThreadHistoryMode::Paginated).await;
    let db = history_db(&store).await;
    for (turn, start) in [("a", 1), ("b", 2000)] {
        insert_turn(
            db,
            thread_id,
            turn,
            start,
            "completed",
            /*error_json*/ None,
            /*first_user_item_id*/ None,
            /*final_agent_item_id*/ None,
        )
        .await;
        for ordinal in start + 1..start + 601 {
            insert_item(db, thread_id, turn, &format!("i-{ordinal}"), ordinal).await;
        }
    }
    let params = turn_params(
        thread_id,
        /*cursor*/ None,
        /*page_size*/ 2,
        SortDirection::Asc,
        StoredTurnItemsView::NotLoaded,
    );
    assert!(matches!(
        store.list_full_turns_bounded(params.clone()).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "budgetExceeded"
        })
    ));
    let mut one_turn = params;
    one_turn.page_size = 1;
    let first = store
        .list_full_turns_bounded(one_turn.clone())
        .await
        .expect("bounded first turn");
    assert_eq!(first.turns[0].1.len(), 600);
    one_turn.cursor = first.next_cursor;
    let second = store
        .list_full_turns_bounded(one_turn.clone())
        .await
        .expect("bounded second turn");
    assert_eq!(second.turns[0].0.turn_id, "b");
    // More than 1024 items within one turn cannot hide behind a one-turn page limit.
    for ordinal in 2700..3200 {
        insert_item(db, thread_id, "b", &format!("i-{ordinal}"), ordinal).await;
    }
    assert!(matches!(
        store.list_full_turns_bounded(one_turn).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "budgetExceeded"
        })
    ));
}

#[tokio::test]
async fn bounded_history_counts_turn_errors_and_refuses_legacy_before_rollout_read() {
    let (_home, store, thread_id) = store_with_mode(ThreadHistoryMode::Paginated).await;
    let db = history_db(&store).await;
    let error = format!(
        r#"{{"message":"{}","codexErrorInfo":null,"additionalDetails":null}}"#,
        "x".repeat(300_000)
    );
    insert_turn(
        db,
        thread_id,
        "t",
        /*rollout_ordinal*/ 1,
        "failed",
        Some(&error),
        /*first_user_item_id*/ None,
        /*final_agent_item_id*/ None,
    )
    .await;
    let params = turn_params(
        thread_id,
        /*cursor*/ None,
        /*page_size*/ 1,
        SortDirection::Desc,
        StoredTurnItemsView::NotLoaded,
    );
    assert!(matches!(
        store.list_full_turns_bounded(params).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "budgetExceeded"
        })
    ));
    // This fixture has no rollout file. A legacy fallback would fail opening it.
    let (_home, store, thread_id) = store_with_mode(ThreadHistoryMode::Legacy).await;
    let params = turn_params(
        thread_id,
        /*cursor*/ None,
        /*page_size*/ 1,
        SortDirection::Desc,
        StoredTurnItemsView::NotLoaded,
    );
    assert!(matches!(
        store.list_full_turns_bounded(params).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "unsupportedHistory"
        })
    ));
}

#[tokio::test]
async fn bounded_history_rejects_compressed_and_oversized_headers_without_replay() {
    let (home, store, thread_id) = store_with_mode(ThreadHistoryMode::Paginated).await;
    let path = rollout_path(home.path(), thread_id);
    let compressed = path.with_extension("jsonl.zst");
    fs::write(
        &compressed,
        zstd::stream::encode_all(
            fs::read(&path).expect("header").as_slice(),
            /*level*/ 0,
        )
        .expect("compress"),
    )
    .expect("compressed file");
    fs::remove_file(&path).expect("retire plain representation");
    let params = turn_params(
        thread_id,
        /*cursor*/ None,
        /*page_size*/ 1,
        SortDirection::Desc,
        StoredTurnItemsView::NotLoaded,
    );
    assert!(matches!(
        store.list_full_turns_bounded(params.clone()).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "unsupportedHistory"
        })
    ));
    fs::write(&path, vec![b'x'; 64 * 1024 + 1]).expect("oversized first line");
    assert!(matches!(
        store.list_full_turns_bounded(params).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "budgetExceeded"
        })
    ));
}

#[tokio::test]
async fn bounded_history_accepts_exact_byte_boundary_but_rejects_one_more_byte() {
    let (_home, store, thread_id) = store_with_mode(ThreadHistoryMode::Paginated).await;
    let db = history_db(&store).await;
    insert_turn(
        db,
        thread_id,
        "t",
        /*rollout_ordinal*/ 1,
        "completed",
        /*error_json*/ None,
        /*first_user_item_id*/ None,
        /*final_agent_item_id*/ None,
    )
    .await;
    for ordinal in 2..18 {
        let id = format!("i-{ordinal}");
        insert_item(db, thread_id, "t", &id, ordinal).await;
        // The single turn consumes 1 + 9 bytes. Include IDs in each exact row budget.
        let bytes = 256 * 1024 - 1 - id.len() - if ordinal == 17 { 10 } else { 0 };
        sqlx::query("UPDATE thread_items SET item_json = ? WHERE item_id = ?")
            .bind("x".repeat(bytes))
            .bind(id)
            .execute(db)
            .await
            .expect("boundary payload");
    }
    let params = turn_params(
        thread_id,
        /*cursor*/ None,
        /*page_size*/ 1,
        SortDirection::Desc,
        StoredTurnItemsView::NotLoaded,
    );
    assert_eq!(
        store
            .list_full_turns_bounded(params.clone())
            .await
            .expect("exact boundary")
            .turns[0]
            .1
            .len(),
        16
    );
    sqlx::query("UPDATE thread_items SET item_json = item_json || 'x' WHERE item_id = 'i-17'")
        .execute(db)
        .await
        .expect("one more byte");
    assert!(matches!(
        store.list_full_turns_bounded(params).await,
        Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "budgetExceeded"
        })
    ));
}

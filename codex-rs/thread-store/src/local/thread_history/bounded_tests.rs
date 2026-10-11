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

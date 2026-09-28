use super::*;
use std::collections::BTreeSet;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;
const THREAD: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

async fn fixture() -> TestResult<(tempfile::TempDir, AutomationStore)> {
    let temp = tempfile::tempdir()?;
    let owner = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?;
    let store = AutomationStore::open_root(temp.path().join("owner"), owner).await?;
    Ok((temp, store))
}

async fn create(store: &AutomationStore, prompt: &str, created: u64) -> TestResult<AutomationTask> {
    Ok(store
        .create_task(&AutomationTaskDraft::new(
            THREAD,
            prompt,
            AutomationSchedule::Once,
            4_000_000_000_000,
            created,
        ))
        .await?)
}

#[tokio::test]
async fn keyset_pages_cover_large_tied_history_without_offset_or_frame_growth() -> TestResult {
    let (_temp, store) = fixture().await?;
    for index in 0..256 {
        create(
            &store,
            &format!("bounded record {index} {}", "x".repeat(300)),
            index / 8 + 1,
        )
        .await?;
    }
    let expected = store.list_tasks(256).await?;
    assert!(serde_json::to_vec(&expected)?.len() > 65_536);
    let mut after = None;
    let mut actual = Vec::new();
    let mut pages = 0;
    loop {
        let page = store.list_task_page_v1(256, after, 4096).await?;
        assert!(page.tasks.len() <= MAX_PAGE_ROWS);
        assert!(serde_json::to_vec(&page)?.len() <= 4096);
        assert!(!page.tasks.is_empty());
        assert!(page.tasks.first().is_some_and(|task| {
            after.is_none_or(|cursor| AutomationTaskCursorV1::from_task(task) > cursor)
        }));
        after = page.next_cursor;
        actual.extend(page.tasks);
        pages += 1;
        assert!(pages <= 256);
        if after.is_none() {
            break;
        }
    }
    assert_eq!(actual, expected);
    assert_eq!(
        actual
            .iter()
            .map(|task| task.task_id)
            .collect::<BTreeSet<_>>()
            .len(),
        256
    );
    let plan = sqlx::query(
        "EXPLAIN QUERY PLAN SELECT task_id, prompt FROM automation_tasks
         WHERE (created_at_ms, task_id) > (?, ?) ORDER BY created_at_ms, task_id LIMIT ?",
    )
    .bind(10_i64)
    .bind(expected[64].task_id.to_string())
    .bind(33_i64)
    .fetch_all(&store.pool)
    .await?;
    let details = plan
        .iter()
        .map(|row| row.try_get::<String, _>("detail"))
        .collect::<Result<Vec<_>, _>>()?
        .join("\n");
    assert!(
        details.contains("automation_tasks_listing_idx"),
        "{details}"
    );
    assert!(!details.contains("TEMP B-TREE"), "{details}");
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn byte_budget_counts_escaping_and_rejects_unsplittable_items() -> TestResult {
    let (_temp, store) = fixture().await?;
    for _ in 0..3 {
        create(&store, &"\n\t\"\\".repeat(100), 1).await?;
    }
    let page = store.list_task_page_v1(3, None, 1700).await?;
    assert_eq!(page.tasks.len(), 1);
    assert!(page.next_cursor.is_some());
    assert!(serde_json::to_vec(&page)?.len() <= 1700);
    let huge = create(&store, &"\n".repeat(32 * 1024), 2).await?;
    let previous = store.list_tasks(3).await?.pop().ok_or("missing fixture")?;
    assert_eq!(
        store
            .list_task_page_v1(
                1,
                Some(AutomationTaskCursorV1::from_task(&previous)),
                60 * 1024
            )
            .await,
        Err(AutomationError::PageItemTooLarge)
    );
    assert!(store.task(huge.task_id).await?.is_some());
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn cursor_survives_owner_updates_and_reopen_without_reordering() -> TestResult {
    let (temp, store) = fixture().await?;
    for time in 1..=6 {
        create(&store, "retained row", time).await?;
    }
    let first = store.list_task_page_v1(2, None, 4096).await?;
    let after = first.next_cursor.ok_or("continuation")?;
    store.cancel_task(after.task_id, 100).await?;
    let expected = store.list_tasks(6).await?;
    let owner = store.owner_agent_id.clone();
    store.close().await;
    let store = AutomationStore::open_root(temp.path().join("owner"), owner).await?;
    let tail = store.list_task_page_v1(6, Some(after), 4096).await?;
    assert_eq!(tail.tasks, expected[2..]);
    assert!(tail.next_cursor.is_none());
    for (limit, bytes) in [(0, 4096), (1025, 4096), (1, 0), (1, 65_537)] {
        assert_eq!(
            store.list_task_page_v1(limit, None, bytes).await,
            Err(AutomationError::Invalid)
        );
    }
    assert_eq!(
        store
            .list_task_page_v1(
                1,
                Some(AutomationTaskCursorV1 {
                    created_at_ms: u64::MAX,
                    task_id: after.task_id,
                }),
                4096
            )
            .await,
        Err(AutomationError::Invalid)
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn missing_listing_index_is_rejected_instead_of_unbounded_fallback() -> TestResult {
    let (temp, store) = fixture().await?;
    let owner = store.owner_agent_id.clone();
    sqlx::query("DROP INDEX automation_tasks_listing_idx")
        .execute(&store.pool)
        .await?;
    store.close().await;
    assert!(matches!(
        AutomationStore::open_root(temp.path().join("owner"), owner).await,
        Err(AutomationError::Corrupt)
    ));
    Ok(())
}

#[tokio::test]
async fn substituted_index_cannot_advertise_the_listing_contract() -> TestResult {
    for replacement in [
        "CREATE INDEX automation_tasks_listing_idx ON automation_tasks(created_at_ms, task_id) WHERE state = 'completed'",
        "CREATE UNIQUE INDEX automation_tasks_listing_idx ON automation_tasks(created_at_ms, task_id)",
        "CREATE INDEX automation_tasks_listing_idx ON automation_tasks(created_at_ms DESC, task_id)",
        "CREATE INDEX automation_tasks_listing_idx ON automation_tasks(created_at_ms, task_id COLLATE NOCASE)",
        "CREATE INDEX automation_tasks_listing_idx ON automation_tasks(created_at_ms, task_id, state)",
        "CREATE INDEX automation_tasks_listing_idx ON unrelated_tasks(created_at_ms, task_id)",
    ] {
        let (temp, store) = fixture().await?;
        let owner = store.owner_agent_id.clone();
        sqlx::query("DROP INDEX automation_tasks_listing_idx")
            .execute(&store.pool)
            .await?;
        sqlx::query("CREATE TABLE unrelated_tasks(created_at_ms INTEGER, task_id TEXT)")
            .execute(&store.pool)
            .await?;
        sqlx::query(replacement).execute(&store.pool).await?;
        store.close().await;
        assert!(
            matches!(
                AutomationStore::open_root(temp.path().join("owner"), owner).await,
                Err(AutomationError::Corrupt)
            ),
            "accepted substituted index: {replacement}"
        );
    }
    Ok(())
}

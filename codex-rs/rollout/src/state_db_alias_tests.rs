use super::list_thread_ids_db;
use super::list_threads_db;
use crate::list::SortDirection;
use crate::list::ThreadSortKey;
use chrono::Utc;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionSource;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_state::ThreadMetadataBuilder;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::os::unix::fs::symlink;

async fn query_ids(
    runtime: &StateRuntime,
    requested: &SqliteConfig,
) -> (Option<Vec<ThreadId>>, Option<Vec<ThreadId>>) {
    let ids = list_thread_ids_db(
        Some(runtime),
        requested,
        /*page_size*/ 10,
        /*cursor*/ None,
        ThreadSortKey::CreatedAt,
        &[],
        /*model_providers*/ None,
        /*archived_only*/ false,
        "alias-regression",
    )
    .await;
    let page = list_threads_db(
        Some(runtime),
        requested,
        /*page_size*/ 10,
        /*cursor*/ None,
        ThreadSortKey::CreatedAt,
        SortDirection::Desc,
        &[],
        /*model_providers*/ None,
        /*cwd_filters*/ None,
        /*relation_filter*/ None,
        /*archived*/ false,
        /*section*/ None,
        /*project_id*/ None,
        /*search_term*/ None,
    )
    .await;
    (
        ids,
        page.map(|page| page.items.into_iter().map(|item| item.id).collect()),
    )
}

#[tokio::test]
async fn sqlite_home_alias_queries_the_bound_runtime_and_retargeting_is_rejected()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let configured_home = root.path().join("owned");
    let runtime = StateRuntime::init(
        SqliteConfig::new_for_testing(configured_home.as_path().abs()),
        "test-provider".to_string(),
    )
    .await?;
    let alias = root.path().join("alias");
    symlink(runtime.sqlite().home(), &alias)?;
    let requested = SqliteConfig::new_for_testing(alias.as_path().abs());
    let rollout = root.path().join("rollout.jsonl");
    std::fs::write(&rollout, b"")?;
    let thread_id = ThreadId::new();
    let mut metadata = ThreadMetadataBuilder::new(thread_id, rollout, Utc::now(), SessionSource::Cli)
        .build("test-provider");
    metadata.preview = Some("alias regression".to_string());
    runtime.upsert_thread(&metadata).await?;
    assert_eq!(
        query_ids(runtime.as_ref(), &requested).await,
        (Some(vec![thread_id]), Some(vec![thread_id]))
    );

    let other = root.path().join("other");
    std::fs::create_dir(&other)?;
    let sentinel = other.join("sentinel");
    std::fs::write(&sentinel, b"untouched")?;
    std::fs::remove_file(&alias)?;
    symlink(&other, &alias)?;
    assert_eq!(query_ids(runtime.as_ref(), &requested).await, (None, None));
    assert_eq!(runtime.get_thread(thread_id).await?, Some(metadata));
    assert_eq!(std::fs::read(&sentinel)?, b"untouched");

    std::fs::remove_file(&alias)?;
    assert_eq!(query_ids(runtime.as_ref(), &requested).await, (None, None));
    runtime.close().await;
    Ok(())
}

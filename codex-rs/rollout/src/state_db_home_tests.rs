use super::list_thread_ids_db;
use super::list_threads_db;
use crate::list::SortDirection;
use crate::list::ThreadSortKey;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionSource;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_state::ThreadMetadata;
use codex_state::ThreadMetadataBuilder;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::fs;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::symlink;

async fn assert_metadata_queries(
    runtime: &StateRuntime,
    requested: &SqliteConfig,
    expected: Option<&ThreadMetadata>,
) {
    let ids = list_thread_ids_db(
        Some(runtime),
        requested,
        /*page_size*/ 10,
        /*cursor*/ None,
        ThreadSortKey::CreatedAt,
        &[],
        /*model_providers*/ None,
        /*archived_only*/ false,
        "home-alias-regression",
    )
    .await;
    assert_eq!(ids, expected.map(|metadata| vec![metadata.id]));
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
    assert_eq!(
        page.map(|page| page.items),
        expected.map(|metadata| vec![metadata.clone()])
    );
}

#[tokio::test]
async fn metadata_queries_accept_current_home_alias_and_reject_retargeted_or_missing_home()
-> anyhow::Result<()> {
    let fixture = tempfile::tempdir()?;
    let real_home = fixture.path().join("real-home");
    fs::DirBuilder::new().mode(0o700).create(&real_home)?;
    let alias = fixture.path().join("requested-home");
    symlink(&real_home, &alias)?;
    let requested = SqliteConfig::new_for_testing(alias.as_path().abs());
    let runtime = StateRuntime::init(requested.clone(), "test-provider".to_string()).await?;
    assert_ne!(runtime.sqlite(), &requested);

    // Only the index contains metadata. An invalid placeholder outside the
    // sessions tree cannot supply it through a rollout scan or JSON parsing.
    let rollout_path = runtime.sqlite().home().join("index-only-record.jsonl");
    let rollout_bytes = b"not a rollout record\n";
    fs::write(&rollout_path, rollout_bytes)?;
    let mut metadata = ThreadMetadataBuilder::new(
        ThreadId::new(),
        rollout_path.clone(),
        codex_utils_time::Timestamp::now(),
        SessionSource::Cli,
    )
    .build("test-provider");
    metadata.title = "metadata retained only in the index".to_string();
    runtime.upsert_thread(&metadata).await?;

    assert_metadata_queries(&runtime, &requested, Some(&metadata)).await;
    assert_metadata_queries(&runtime, runtime.sqlite(), Some(&metadata)).await;

    let other_home = fixture.path().join("other-home");
    fs::DirBuilder::new().mode(0o700).create(&other_home)?;
    let other = SqliteConfig::new_for_testing(other_home.as_path().abs());
    assert_metadata_queries(&runtime, &other, None).await;
    fs::remove_file(&alias)?;
    symlink(&other_home, &alias)?;
    assert_metadata_queries(&runtime, &requested, None).await;
    assert!(!other.state_db_path().exists());

    fs::remove_file(&alias)?;
    assert_metadata_queries(&runtime, &requested, None).await;
    symlink(fixture.path().join("missing-home"), &alias)?;
    assert_metadata_queries(&runtime, &requested, None).await;

    // Failed associations neither remove metadata nor redirect the retained
    // runtime. The exact config still queries the original, already-open DB.
    assert_eq!(
        runtime.get_thread(metadata.id).await?,
        Some(metadata.clone())
    );
    assert_metadata_queries(&runtime, runtime.sqlite(), Some(&metadata)).await;
    assert_eq!(fs::read(&rollout_path)?, rollout_bytes);
    runtime.close().await;
    Ok(())
}

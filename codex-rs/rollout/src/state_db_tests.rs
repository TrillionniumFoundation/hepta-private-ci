#![allow(warnings, clippy::all)]

use super::*;
use crate::RolloutLine;
use crate::list::parse_cursor;
use chrono::DateTime;
use chrono::NaiveDateTime;
use chrono::Timelike;
use chrono::Utc;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SessionMeta;
use codex_protocol::protocol::SessionMetaLine;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_protocol::protocol::UserMessageEvent;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::path::Path;
use tempfile::TempDir;

#[test]
fn cursor_to_anchor_normalizes_timestamp_format() {
    let ts_str = "2026-01-27T12-34-56";
    let cursor = parse_cursor(ts_str).expect("cursor should parse");
    let anchor = cursor_to_anchor(Some(&cursor)).expect("anchor should parse");

    let naive =
        NaiveDateTime::parse_from_str(ts_str, "%Y-%m-%dT%H-%M-%S").expect("ts should parse");
    let expected_ts = DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc)
        .with_nanosecond(0)
        .expect("nanosecond");

    assert_eq!(anchor.ts, expected_ts);
    assert_eq!(anchor.id, None);
}

#[test]
fn cursor_to_anchor_preserves_recency_tie_breaker() {
    let id = ThreadId::from_string("00000000-0000-0000-0000-000000000123")
        .expect("thread id should parse");
    let token = format!("2026-01-27T12:34:56Z|{id}");
    let cursor = parse_cursor(&token).expect("cursor should parse");
    let anchor = cursor_to_anchor(Some(&cursor)).expect("anchor should parse");

    assert_eq!(anchor.id, Some(id));
    assert_eq!(
        serde_json::to_string(&cursor).expect("cursor should serialize"),
        format!("\"{token}\"")
    );
}

/// A runtime for another SQLite home must not be queried or clean up rows when
/// a caller supplies a mismatched configuration.
#[tokio::test]
async fn list_threads_db_rejects_mismatched_sqlite_config_without_cleanup() -> anyhow::Result<()> {
    let root = TempDir::new().expect("temp dir");
    let runtime_sqlite = codex_state::SqliteConfig::new_for_testing(
        root.path().join("runtime-sqlite").as_path().abs(),
    );
    let requested_sqlite = codex_state::SqliteConfig::new_for_testing(
        root.path().join("requested-sqlite").as_path().abs(),
    );
    let runtime =
        codex_state::StateRuntime::init(runtime_sqlite, "test-provider".to_string()).await?;
    let thread_id = ThreadId::new();
    let metadata = ThreadMetadataBuilder::new(
        thread_id,
        root.path().join("missing-rollout.jsonl"),
        Utc::now(),
        SessionSource::Cli,
    )
    .build("test-provider");
    runtime.upsert_thread(&metadata).await?;

    let page = list_threads_db(
        Some(runtime.as_ref()),
        &requested_sqlite,
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

    assert!(page.is_none());
    assert_eq!(runtime.get_thread(thread_id).await?, Some(metadata));
    Ok(())
}

async fn assert_index_reads(
    runtime: &codex_state::StateRuntime,
    requested: &SqliteConfig,
    expected: Option<Vec<ThreadId>>,
) -> anyhow::Result<()> {
    let ids = list_thread_ids_db(
        Some(runtime),
        requested,
        /*page_size*/ 10,
        /*cursor*/ None,
        ThreadSortKey::CreatedAt,
        &[],
        /*model_providers*/ None,
        /*archived_only*/ false,
        "native-home-alias-regression",
    )
    .await;
    assert_eq!(ids, expected);
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
        page.map(|page| page
            .items
            .into_iter()
            .map(|item| item.id)
            .collect::<Vec<_>>()),
        expected,
    );
    Ok(())
}

#[tokio::test]
async fn index_reads_accept_config_before_native_home_canonicalization() -> anyhow::Result<()> {
    let home = TempDir::new()?;
    let requested = SqliteConfig::new_for_testing(home.path().abs());
    let runtime =
        codex_state::StateRuntime::init(requested.clone(), "test-provider".to_string()).await?;
    let rollout = home.path().join("existing-rollout.jsonl");
    tokio::fs::write(&rollout, b"{}\n").await?;
    let thread_id = ThreadId::new();
    let mut metadata =
        ThreadMetadataBuilder::new(thread_id, rollout, Utc::now(), SessionSource::Cli)
            .build("test-provider");
    metadata.first_user_message = Some("indexed user message".to_string());
    metadata.preview = metadata.first_user_message.clone();
    runtime.upsert_thread(&metadata).await?;

    assert_index_reads(&runtime, &requested, Some(vec![thread_id])).await?;
    assert_eq!(runtime.get_thread(thread_id).await?, Some(metadata));
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn index_reads_accept_same_home_alias_but_reject_retargeted_or_missing_alias()
-> anyhow::Result<()> {
    let root = TempDir::new()?;
    let runtime = codex_state::StateRuntime::init(
        SqliteConfig::new_for_testing(root.path().join("runtime").as_path().abs()),
        "test-provider".to_string(),
    )
    .await?;
    let alias = root.path().join("configured-home");
    std::os::unix::fs::symlink(runtime.sqlite().home(), &alias)?;
    let requested = SqliteConfig::new_for_testing(alias.as_path().abs());
    assert_ne!(runtime.sqlite(), &requested);
    let rollout = root.path().join("existing-rollout.jsonl");
    tokio::fs::write(&rollout, b"{}\n").await?;
    let thread_id = ThreadId::new();
    let mut metadata =
        ThreadMetadataBuilder::new(thread_id, rollout, Utc::now(), SessionSource::Cli)
            .build("test-provider");
    metadata.first_user_message = Some("indexed user message".to_string());
    metadata.preview = metadata.first_user_message.clone();
    runtime.upsert_thread(&metadata).await?;

    assert_index_reads(&runtime, &requested, Some(vec![thread_id])).await?;
    std::fs::remove_file(&alias)?;
    let other = root.path().join("other-home");
    std::fs::create_dir(&other)?;
    std::os::unix::fs::symlink(&other, &alias)?;
    assert_index_reads(&runtime, &requested, /*expected*/ None).await?;
    std::fs::remove_file(&alias)?;
    assert_index_reads(&runtime, &requested, /*expected*/ None).await?;
    assert_eq!(runtime.get_thread(thread_id).await?, Some(metadata));
    Ok(())
}

#[tokio::test]
async fn try_init_waits_for_concurrent_startup_backfill() -> anyhow::Result<()> {
    let home = TempDir::new().expect("temp dir");
    let runtime = codex_state::StateRuntime::init(
        codex_state::SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
    )
    .await?;
    let claimed = runtime.try_claim_backfill(/*lease_seconds*/ 60).await?;
    assert!(claimed);
    let runtime_for_completion = runtime.clone();
    let complete_backfill = tokio::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_millis(25)).await;
        runtime_for_completion
            .mark_backfill_complete(/*last_watermark*/ None)
            .await
    });

    let initialized = try_init_with_roots_and_backfill_lease(
        home.path().to_path_buf(),
        codex_state::SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
        /*backfill_lease_seconds*/ 60,
    )
    .await?;
    complete_backfill.await??;
    assert_eq!(
        initialized.get_backfill_state().await?.status,
        codex_state::BackfillStatus::Complete
    );

    Ok(())
}

#[tokio::test]
async fn try_init_times_out_waiting_for_stuck_startup_backfill() -> anyhow::Result<()> {
    let home = TempDir::new().expect("temp dir");
    let runtime = codex_state::StateRuntime::init(
        codex_state::SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
    )
    .await?;
    let claimed = runtime.try_claim_backfill(/*lease_seconds*/ 60).await?;
    assert!(claimed);

    let result = try_init_with_roots_and_backfill_lease(
        home.path().to_path_buf(),
        codex_state::SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
        /*backfill_lease_seconds*/ 60,
    )
    .await;
    let err = match result {
        Ok(_) => panic!("state db init should not wait forever for incomplete backfill"),
        Err(err) => err,
    };
    assert!(
        err.to_string()
            .contains("timed out waiting for state db backfill"),
        "unexpected error: {err}"
    );

    Ok(())
}

#[tokio::test]
async fn reconcile_rollout_preserves_existing_explicit_title() -> anyhow::Result<()> {
    let home = TempDir::new().expect("temp dir");
    let thread_id = ThreadId::new();
    let rollout_path =
        write_rollout_with_user_message(home.path(), thread_id, "Hey", ThreadHistoryMode::Legacy)?;
    let runtime = codex_state::StateRuntime::init(
        codex_state::SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
    )
    .await?;

    let mut metadata =
        metadata::extract_metadata_from_rollout(rollout_path.as_path(), "test-provider")
            .await?
            .metadata;
    assert_eq!(metadata.title, "Hey");
    assert_eq!(metadata.first_user_message.as_deref(), Some("Hey"));
    metadata.title = "math".to_string();
    runtime.upsert_thread(&metadata).await?;

    reconcile_rollout(
        Some(runtime.as_ref()),
        rollout_path.as_path(),
        "test-provider",
        /*builder*/ None,
        &[],
        /*archived_only*/ Some(false),
        /*new_thread_memory_mode*/ None,
    )
    .await;

    let persisted = runtime
        .get_thread(thread_id)
        .await?
        .expect("thread should exist");
    assert_eq!(persisted.title, "math");
    assert_eq!(persisted.first_user_message.as_deref(), Some("Hey"));
    Ok(())
}

#[tokio::test]
async fn filesystem_repair_preserves_existing_rollout_path() -> anyhow::Result<()> {
    let home = TempDir::new().expect("temp dir");
    let thread_id = ThreadId::new();
    let initial_rollout_path = write_rollout_with_user_message(
        home.path(),
        thread_id,
        "Old",
        ThreadHistoryMode::Paginated,
    )?;
    let old_rollout_path = initial_rollout_path
        .with_file_name(format!("rollout-2026-06-01T14-26-25-{thread_id}_old.jsonl"));
    std::fs::rename(initial_rollout_path, old_rollout_path.as_path())?;
    let active_rollout_path = write_rollout_with_user_message(
        home.path(),
        thread_id,
        "Current",
        ThreadHistoryMode::Paginated,
    )?;
    let runtime = codex_state::StateRuntime::init(
        codex_state::SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
    )
    .await?;
    let active_metadata =
        metadata::extract_metadata_from_rollout(active_rollout_path.as_path(), "test-provider")
            .await?
            .metadata;
    runtime.upsert_thread(&active_metadata).await?;
    let active_metadata = runtime
        .get_thread(thread_id)
        .await?
        .expect("thread should exist");

    read_repair_rollout_path(
        Some(runtime.as_ref()),
        Some(thread_id),
        /*archived_only*/ None,
        old_rollout_path.as_path(),
    )
    .await;
    assert_eq!(
        runtime.get_thread(thread_id).await?,
        Some(active_metadata.clone())
    );

    reconcile_rollout(
        Some(runtime.as_ref()),
        old_rollout_path.as_path(),
        "test-provider",
        /*builder*/ None,
        &[],
        /*archived_only*/ None,
        /*new_thread_memory_mode*/ None,
    )
    .await;
    assert_eq!(runtime.get_thread(thread_id).await?, Some(active_metadata));
    Ok(())
}

#[tokio::test]
async fn reconcile_rollout_preserves_existing_paginated_memory_mode() -> anyhow::Result<()> {
    let home = TempDir::new().expect("temp dir");
    let thread_id = ThreadId::new();
    let rollout_path = write_rollout_with_user_message(
        home.path(),
        thread_id,
        "Hey",
        ThreadHistoryMode::Paginated,
    )?;
    let runtime = codex_state::StateRuntime::init(
        codex_state::SqliteConfig::new_for_testing(home.path().abs()),
        "test-provider".to_string(),
    )
    .await?;

    reconcile_rollout(
        Some(runtime.as_ref()),
        rollout_path.as_path(),
        "test-provider",
        /*builder*/ None,
        &[],
        /*archived_only*/ None,
        /*new_thread_memory_mode*/ None,
    )
    .await;
    assert!(
        runtime
            .set_thread_memory_mode(thread_id, "disabled")
            .await?
    );

    reconcile_rollout(
        Some(runtime.as_ref()),
        rollout_path.as_path(),
        "test-provider",
        /*builder*/ None,
        &[],
        /*archived_only*/ None,
        /*new_thread_memory_mode*/ None,
    )
    .await;

    assert_eq!(
        runtime.get_thread_memory_mode(thread_id).await?.as_deref(),
        Some("disabled")
    );
    Ok(())
}

fn write_rollout_with_user_message(
    home: &Path,
    thread_id: ThreadId,
    message: &str,
    history_mode: ThreadHistoryMode,
) -> anyhow::Result<std::path::PathBuf> {
    let dir = home.join("sessions/2026/06/01");
    std::fs::create_dir_all(dir.as_path())?;
    let path = dir.join(format!("rollout-2026-06-01T14-26-25-{thread_id}.jsonl"));
    let lines = [
        RolloutLine {
            timestamp: "2026-06-01T14:26:25Z".to_string(),
            ordinal: None,
            item: RolloutItem::SessionMeta(SessionMetaLine {
                meta: SessionMeta {
                    session_id: thread_id.into(),
                    id: thread_id,
                    forked_from_id: None,
                    parent_thread_id: None,
                    timestamp: "2026-06-01T14:26:25Z".to_string(),
                    cwd: home.to_path_buf(),
                    originator: "test".to_string(),
                    cli_version: "test".to_string(),
                    source: SessionSource::Cli,
                    thread_source: None,
                    agent_nickname: None,
                    agent_role: None,
                    agent_path: None,
                    model_provider: Some("test-provider".to_string()),
                    base_instructions: None,
                    dynamic_tools: None,
                    selected_capability_roots: Vec::new(),
                    memory_mode: None,
                    history_mode,
                    history_base: None,
                    subagent_history_start_ordinal: None,
                    multi_agent_version: None,
                    context_window: None,
                },
                git: None,
            }),
        },
        RolloutLine {
            timestamp: "2026-06-01T14:26:26Z".to_string(),
            ordinal: None,
            item: RolloutItem::EventMsg(EventMsg::UserMessage(UserMessageEvent {
                message: message.to_string(),
                ..Default::default()
            })),
        },
    ];
    let jsonl = lines
        .iter()
        .map(serde_json::to_string)
        .collect::<Result<Vec<_>, _>>()?
        .join("\n");
    std::fs::write(path.as_path(), format!("{jsonl}\n"))?;
    Ok(path)
}

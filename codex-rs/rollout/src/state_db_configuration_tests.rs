use super::list_thread_ids_db;
use super::list_threads_db;
use crate::SortDirection;
use crate::ThreadSortKey;
use chrono::Utc;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionSource;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_state::ThreadMetadataBuilder;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::fs;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::symlink;

#[tokio::test]
async fn original_sqlite_alias_keeps_authoritative_listing_after_alias_replacement()
-> anyhow::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let original = root.join("original");
    let replacement = root.join("replacement");
    let alias = root.join("configured");
    let unknown_alias = root.join("unknown-alias");
    for path in [&original, &replacement] {
        fs::DirBuilder::new().mode(0o700).create(path)?;
    }
    symlink(&original, &alias)?;
    symlink(&original, &unknown_alias)?;
    let requested = SqliteConfig::new_for_testing(alias.as_path().abs());
    let runtime = StateRuntime::init(requested.clone(), "test-provider".to_string()).await?;
    assert_eq!(runtime.sqlite().home(), original);
    let thread_id = ThreadId::new();
    let rollout = root.join("retained-rollout.jsonl");
    fs::write(&rollout, b"retained rollout")?;
    let mut metadata =
        ThreadMetadataBuilder::new(thread_id, rollout, Utc::now(), SessionSource::Cli)
            .build("test-provider");
    metadata.first_user_message = Some("retained original owner".to_string());
    metadata.preview = metadata.first_user_message.clone();
    runtime.upsert_thread(&metadata).await?;
    let retained = runtime.get_thread(thread_id).await?.ok_or_else(|| {
        std::io::Error::other("the original runtime must retain the inserted thread")
    })?;

    for retarget in [false, true] {
        if retarget {
            fs::remove_file(&alias)?;
            symlink(&replacement, &alias)?;
        }
        for config in [&requested, runtime.sqlite()] {
            let page = list_threads_db(
                Some(runtime.as_ref()),
                config,
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
            .await
            .ok_or_else(|| std::io::Error::other("initialized configuration must match"))?;
            assert_eq!(page.items, vec![retained.clone()]);
            assert_eq!(
                list_thread_ids_db(
                    Some(runtime.as_ref()),
                    config,
                    /*page_size*/ 10,
                    /*cursor*/ None,
                    ThreadSortKey::CreatedAt,
                    &[],
                    /*model_providers*/ None,
                    /*archived_only*/ false,
                    "configured-home-binding",
                )
                .await,
                Some(vec![thread_id])
            );
        }
    }
    for path in [&replacement, &unknown_alias] {
        let other = SqliteConfig::new_for_testing(path.as_path().abs());
        assert!(!runtime.matches_sqlite_config(&other));
        assert_eq!(
            list_thread_ids_db(
                Some(runtime.as_ref()),
                &other,
                /*page_size*/ 10,
                /*cursor*/ None,
                ThreadSortKey::CreatedAt,
                &[],
                /*model_providers*/ None,
                /*archived_only*/ false,
                "unbound-home-rejection",
            )
            .await,
            None
        );
    }
    assert_eq!(fs::read_dir(&replacement)?.count(), 0);
    assert_eq!(runtime.get_thread(thread_id).await?, Some(retained));
    Ok(())
}

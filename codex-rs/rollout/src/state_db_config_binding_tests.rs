use super::try_init;
use crate::RolloutConfig;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::path::Path;

fn config_for(codex_home: &Path, sqlite_home: &Path) -> RolloutConfig {
    RolloutConfig {
        codex_home: codex_home.to_path_buf(),
        sqlite: SqliteConfig::new_for_testing(sqlite_home.abs()),
        cwd: codex_home.to_path_buf(),
        model_provider_id: "test-provider".to_string(),
        generate_memories: false,
    }
}

#[tokio::test]
async fn failed_initialization_preserves_requested_config() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let sqlite_home = root.path().join("not-a-directory");
    std::fs::write(&sqlite_home, "cannot hold a state database")?;
    let mut config = config_for(root.path(), &sqlite_home);
    let requested = config.clone();

    assert!(try_init(&mut config).await.is_err());
    assert_eq!(config, requested);
    Ok(())
}

#[cfg(unix)]
mod unix {
    use super::*;
    use crate::SortDirection;
    use crate::ThreadSortKey;
    use crate::state_db::get_state_db;
    use crate::state_db::list_threads_db;
    use chrono::Utc;
    use codex_protocol::ThreadId;
    use codex_protocol::protocol::SessionSource;
    use codex_state::StateRuntime;
    use codex_state::ThreadMetadataBuilder;
    use pretty_assertions::assert_eq;
    use std::os::unix::fs::symlink;

    async fn listed_ids(runtime: &StateRuntime, sqlite: &SqliteConfig) -> Option<Vec<ThreadId>> {
        list_threads_db(
            Some(runtime),
            sqlite,
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
        .map(|page| page.items.into_iter().map(|thread| thread.id).collect())
    }

    #[tokio::test]
    async fn initialized_config_keeps_original_pool_after_alias_retarget() -> anyhow::Result<()> {
        let root = tempfile::tempdir()?;
        let original_home = tempfile::tempdir_in(root.path())?;
        let redirected_home = tempfile::tempdir_in(root.path())?;
        let configured_home = root.path().join("configured-sqlite");
        symlink(original_home.path(), &configured_home)?;
        let mut config = config_for(root.path(), &configured_home);
        let requested = config.clone();
        let runtime = try_init(&mut config).await?;
        let mut expected = requested.clone();
        expected.sqlite = runtime.sqlite().clone();
        assert_eq!(config, expected);
        assert_eq!(config.sqlite.home(), original_home.path().canonicalize()?);

        let rollout_path = root.path().join("thread.jsonl");
        std::fs::write(&rollout_path, "")?;
        let thread_id = ThreadId::new();
        let mut original_metadata =
            ThreadMetadataBuilder::new(thread_id, rollout_path, Utc::now(), SessionSource::Cli)
                .build("test-provider");
        original_metadata.first_user_message = Some("original pool thread".to_string());
        original_metadata.preview = original_metadata.first_user_message.clone();
        runtime.upsert_thread(&original_metadata).await?;

        std::fs::remove_file(&configured_home)?;
        symlink(redirected_home.path(), &configured_home)?;

        assert_eq!(
            listed_ids(&runtime, &config.sqlite).await,
            Some(vec![thread_id])
        );
        assert!(listed_ids(&runtime, &requested.sqlite).await.is_none());
        assert!(!redirected_home.path().join("queue-dispatch-locks").exists());

        // Both initializations received identical alias text, but their frozen
        // pool identities must remain distinct after that alias is retargeted.
        let mut redirected_config = requested;
        let redirected_runtime = try_init(&mut redirected_config).await?;
        assert_eq!(
            redirected_config.sqlite.home(),
            redirected_home.path().canonicalize()?
        );
        assert_ne!(config.sqlite, redirected_config.sqlite);
        let mut redirected_metadata = original_metadata.clone();
        redirected_metadata.title = "redirected pool".to_string();
        redirected_runtime
            .upsert_thread(&redirected_metadata)
            .await?;

        assert!(
            listed_ids(&redirected_runtime, &config.sqlite)
                .await
                .is_none()
        );
        assert!(
            listed_ids(&runtime, &redirected_config.sqlite)
                .await
                .is_none()
        );
        assert_eq!(
            runtime.get_thread(thread_id).await?,
            Some(original_metadata)
        );
        assert_eq!(
            redirected_runtime.get_thread(thread_id).await?,
            Some(redirected_metadata)
        );
        assert_eq!(
            listed_ids(&runtime, &config.sqlite).await,
            Some(vec![thread_id])
        );
        assert_eq!(
            listed_ids(&redirected_runtime, &redirected_config.sqlite).await,
            Some(vec![thread_id])
        );
        Ok(())
    }

    #[tokio::test]
    async fn opening_ready_database_binds_its_frozen_config() -> anyhow::Result<()> {
        let root = tempfile::tempdir()?;
        let sqlite_home = tempfile::tempdir_in(root.path())?;
        let configured_home = root.path().join("configured-sqlite");
        symlink(sqlite_home.path(), &configured_home)?;
        let mut owner_config = config_for(root.path(), &configured_home);
        let mut read_config = owner_config.clone();
        let owner_runtime = try_init(&mut owner_config).await?;
        let read_runtime = get_state_db(&mut read_config)
            .await
            .ok_or_else(|| anyhow::anyhow!("ready state database should open"))?;

        assert_eq!(read_config, owner_config);
        assert_eq!(read_runtime.sqlite(), owner_runtime.sqlite());
        std::fs::remove_file(&configured_home)?;
        assert_eq!(
            listed_ids(&read_runtime, &read_config.sqlite).await,
            Some(Vec::new())
        );
        Ok(())
    }
}

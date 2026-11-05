use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::PermissionsExt;

use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionSource;
use codex_rollout::SortDirection;
use codex_rollout::ThreadSortKey;
use codex_rollout::state_db::list_threads_db;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_state::ThreadMetadataBuilder;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::init_state_db;
use crate::config::ConfigBuilder;

async fn list_bound_title(
    runtime: &StateRuntime,
    sqlite: &SqliteConfig,
) -> Option<codex_state::ThreadsPage> {
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
        /*search_term*/ Some("bound title"),
    )
    .await
}

#[tokio::test]
async fn initial_alias_binding_keeps_sqlite_listing_on_the_retained_owner() -> anyhow::Result<()> {
    let root = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let home = root.path().canonicalize()?;
    let sqlite_home = home.join("sqlite");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&sqlite_home)?;
    let alias = home.join("sqlite-alias");
    std::os::unix::fs::symlink(&sqlite_home, &alias)?;
    let mut config = ConfigBuilder::default()
        .codex_home(home.clone())
        .build()
        .await?;
    config.sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(&alias)?);
    let original_alias = config.sqlite.clone();

    let runtime = init_state_db(&mut config)
        .await
        .ok_or_else(|| anyhow::anyhow!("state runtime should initialize"))?;
    assert_eq!(&config.sqlite, runtime.sqlite());
    assert_eq!(config.sqlite.home(), sqlite_home.as_path());
    assert_eq!(config.codex_home.as_path(), home.as_path());
    assert_ne!(config.sqlite, original_alias);

    let thread_id = ThreadId::new();
    let rollout_path = home.join("retained-rollout.jsonl");
    std::fs::write(&rollout_path, "")?;
    let mut metadata = ThreadMetadataBuilder::new(
        thread_id,
        rollout_path,
        chrono::Utc::now(),
        SessionSource::Cli,
    )
    .build(&config.model_provider_id);
    metadata.title = "bound title".to_string();
    // Global listing requires a nonempty preview, derived from the first message.
    metadata.first_user_message = Some("retained user message".to_string());
    runtime.upsert_thread(&metadata).await?;
    let retained = runtime.get_thread(thread_id).await?;
    assert!(retained.is_some());
    let page = list_bound_title(runtime.as_ref(), &config.sqlite)
        .await
        .ok_or_else(|| anyhow::anyhow!("bound SQLite listing should remain available"))?;
    assert_eq!(
        page.items.iter().map(|item| item.id).collect::<Vec<_>>(),
        vec![thread_id]
    );

    // Retargeting the original spelling must not redirect an established owner,
    // nor make that unbound spelling acceptable to the strict listing guard.
    let replacement_home = home.join("replacement");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&replacement_home)?;
    std::fs::remove_file(&alias)?;
    std::os::unix::fs::symlink(&replacement_home, &alias)?;
    assert!(
        list_bound_title(runtime.as_ref(), &original_alias)
            .await
            .is_none()
    );
    let page = list_bound_title(runtime.as_ref(), &config.sqlite)
        .await
        .ok_or_else(|| anyhow::anyhow!("retained SQLite listing should remain available"))?;
    assert_eq!(
        page.items.iter().map(|item| item.id).collect::<Vec<_>>(),
        vec![thread_id]
    );
    assert_eq!(runtime.get_thread(thread_id).await?, retained);
    assert!(!original_alias.state_db_path().exists());
    runtime.close().await;
    Ok(())
}

#[tokio::test]
async fn failed_initialization_keeps_the_requested_sqlite_config() -> anyhow::Result<()> {
    let root = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let home = root.path().canonicalize()?;
    let blocking_file = home.join("sqlite-file");
    std::fs::write(&blocking_file, "original blocking file")?;
    let mut config = ConfigBuilder::default().codex_home(home).build().await?;
    config.sqlite =
        SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(&blocking_file)?);
    let requested = config.sqlite.clone();

    assert!(init_state_db(&mut config).await.is_none());
    assert_eq!(config.sqlite, requested);
    assert_eq!(
        std::fs::read_to_string(&blocking_file)?,
        "original blocking file"
    );
    Ok(())
}

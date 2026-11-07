use super::SqliteConfig;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[tokio::test]
async fn refused_commit_keeps_reused_pool_readable_without_reopening_write_gate()
-> anyhow::Result<()> {
    let home = unique_temp_dir();
    std::fs::create_dir(&home)?;
    let home = scopeguard::guard(home, |home| {
        let _ = std::fs::remove_dir_all(home);
    });
    let canonical_home = home.canonicalize()?;
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(canonical_home.clone())?);
    let commit_allowed = Arc::new(AtomicBool::new(/*v*/ true));
    let guard = Arc::clone(&commit_allowed);
    let pool = sqlite
        .open_durable_evidence_pool_guarded(
            &canonical_home.join("refused-commit.sqlite3"),
            move || guard.load(Ordering::Acquire),
        )
        .await?;
    sqlx::query("CREATE TABLE guarded_effect (value INTEGER NOT NULL)")
        .execute(&pool)
        .await?;

    // Hold the other four handles so the next checkout must reuse or replace
    // the one connection whose transaction is rejected at the commit hook.
    let mut held = Vec::new();
    for _ in 0..4 {
        held.push(pool.acquire().await?);
    }
    let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query("INSERT INTO guarded_effect VALUES (7)")
        .execute(&mut *transaction)
        .await?;
    commit_allowed.store(/*val*/ false, Ordering::Release);
    assert!(transaction.commit().await.is_err());

    let mut observation = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("read transaction must remain available after a refused commit");
    let values: Vec<i64> = sqlx::query_scalar("SELECT value FROM guarded_effect ORDER BY value")
        .fetch_all(&mut *observation)
        .await?;
    assert_eq!(values, Vec::<i64>::new());
    observation.rollback().await?;

    // Replacement connections must retain the same rejecting owner guard.
    assert!(
        sqlx::query("INSERT INTO guarded_effect VALUES (9)")
            .execute(&pool)
            .await
            .is_err()
    );
    let values: Vec<i64> = sqlx::query_scalar("SELECT value FROM guarded_effect ORDER BY value")
        .fetch_all(&pool)
        .await?;
    assert_eq!(values, Vec::<i64>::new());
    assert!(!commit_allowed.load(Ordering::Acquire));
    drop(held);
    pool.close().await;
    Ok(())
}

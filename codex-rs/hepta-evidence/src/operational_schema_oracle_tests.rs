use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

enum GuardMutation {
    Disabled,
    Commented,
    QuotedWhitespace,
}

fn config(temp: &tempfile::TempDir) -> TestResult<SqliteConfig> {
    Ok(SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(
        temp.path().canonicalize()?,
    )?))
}

async fn require_corrupt_reopen(sqlite: &SqliteConfig) -> TestResult {
    match HeptaEvidenceStore::open_existing_read_only(sqlite).await {
        Err(EvidenceError::Corrupt(_)) => Ok(()),
        Err(error) => Err(format!("expected schema corruption, got {error}").into()),
        Ok(store) => {
            store.close().await;
            Err("read-only startup admitted a disabled operational guard".into())
        }
    }
}

#[tokio::test]
async fn read_only_reopen_rejects_disabled_and_commented_operational_guards() -> TestResult {
    for name in [
        "evidence_trust_acceptance_no_update",
        "evidence_trust_acceptance_no_delete",
        "evidence_publication_owner_no_delete",
        "evidence_publication_batches_no_delete",
        "evidence_publication_intents_no_delete",
    ] {
        for mutation in [
            GuardMutation::Disabled,
            GuardMutation::Commented,
            GuardMutation::QuotedWhitespace,
        ] {
            let temp = tempfile::tempdir()?;
            let sqlite = config(&temp)?;
            let store = HeptaEvidenceStore::open(&sqlite).await?;
            let original: String =
                sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
                    .bind(name)
                    .fetch_one(&store.pool)
                    .await?;
            let weakened = match mutation {
                GuardMutation::Commented => original
                    .replacen("SELECT RAISE(", "/* SELECT RAISE(", /*count*/ 1)
                    .replacen(");", "); */ SELECT 1;", /*count*/ 1),
                GuardMutation::Disabled => {
                    original.replacen("\nBEGIN", "\nWHEN 0\nBEGIN", /*count*/ 1)
                }
                GuardMutation::QuotedWhitespace => original.replace("evidence ", "evidence  "),
            };
            assert_ne!(original, weakened);
            let mut transaction = store.pool.begin_with("BEGIN IMMEDIATE").await?;
            sqlx::query(sqlx::AssertSqlSafe(format!("DROP TRIGGER {name}")))
                .execute(&mut *transaction)
                .await?;
            sqlx::query(sqlx::AssertSqlSafe(weakened))
                .execute(&mut *transaction)
                .await?;
            transaction.commit().await?;
            let quick_check: String = sqlx::query_scalar("PRAGMA quick_check")
                .fetch_one(&store.pool)
                .await?;
            assert_eq!(quick_check, "ok");
            store.close().await;
            require_corrupt_reopen(&sqlite).await?;
        }
    }
    Ok(())
}

#[tokio::test]
async fn read_only_reopen_rejects_comment_preserved_table_check() -> TestResult {
    let temp = tempfile::tempdir()?;
    let sqlite = config(&temp)?;
    let store = HeptaEvidenceStore::open(&sqlite).await?;
    let original: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'evidence_publication_owner'",
    )
    .fetch_one(&store.pool)
    .await?;
    let weakened = original.replace(
        "owner_generation INTEGER NOT NULL CHECK (owner_generation > 0)",
        "owner_generation INTEGER NOT NULL \
         /* owner_generation INTEGER NOT NULL CHECK (owner_generation > 0) */",
    );
    assert_ne!(original, weakened);
    let mut connection = store.pool.acquire().await?;
    sqlx::query("PRAGMA writable_schema = ON")
        .execute(&mut *connection)
        .await?;
    sqlx::query("UPDATE sqlite_schema SET sql = ? WHERE name = 'evidence_publication_owner'")
        .bind(weakened)
        .execute(&mut *connection)
        .await?;
    sqlx::query("PRAGMA writable_schema = OFF")
        .execute(&mut *connection)
        .await?;
    drop(connection);
    store.close().await;
    require_corrupt_reopen(&sqlite).await
}

#[tokio::test]
async fn legitimate_operational_layout_and_backfill_trigger_reopen() -> TestResult {
    let temp = tempfile::tempdir()?;
    let sqlite = config(&temp)?;
    let store = HeptaEvidenceStore::open(&sqlite).await?;
    let name = "evidence_trust_acceptance_no_delete";
    let original: String = sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
        .bind(name)
        .fetch_one(&store.pool)
        .await?;
    let equivalent = original.replace('\n', "\n \t");
    let mut transaction = store.pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query(sqlx::AssertSqlSafe(format!("DROP TRIGGER {name}")))
        .execute(&mut *transaction)
        .await?;
    sqlx::query(sqlx::AssertSqlSafe(equivalent))
        .execute(&mut *transaction)
        .await?;
    transaction.commit().await?;
    store.close().await;
    let reopened = HeptaEvidenceStore::open_existing_read_only(&sqlite).await?;
    reopened.close().await;
    Ok(())
}

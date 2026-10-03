use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

#[derive(Debug)]
enum GuardMutation {
    Disabled,
    Commented,
}

const GOVERNANCE_GUARDS: [&str; 4] = [
    "governance_decisions_no_update",
    "governance_decisions_no_delete",
    "governance_receipts_no_update",
    "governance_receipts_no_delete",
];
const PROVIDER_GUARDS: [&str; 4] = [
    "provider_invocation_intents_no_update",
    "provider_invocation_intents_no_delete",
    "provider_invocation_terminals_no_update",
    "provider_invocation_terminals_no_delete",
];

async fn rejects_disabled_guards(names: &[&str]) -> TestResult {
    for name in names {
        for alteration in [GuardMutation::Disabled, GuardMutation::Commented] {
            let temp = tempfile::tempdir()?;
            let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(
                temp.path().canonicalize()?,
            )?);
            let store = HeptaEvidenceStore::open(&sqlite).await?;
            let original: String =
                sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
                    .bind(name)
                    .fetch_one(&store.pool)
                    .await?;
            let weakened = match alteration {
                GuardMutation::Disabled => {
                    original.replacen("\nBEGIN", "\nWHEN 0\nBEGIN", /*count*/ 1)
                }
                GuardMutation::Commented => original
                    .replacen("SELECT RAISE(", "/* SELECT RAISE(", /*count*/ 1)
                    .replacen(");", "); */ SELECT 1;", /*count*/ 1),
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
            let quick: String = sqlx::query_scalar("PRAGMA quick_check")
                .fetch_one(&store.pool)
                .await?;
            assert_eq!(quick, "ok");
            store.close().await;
            match HeptaEvidenceStore::open_existing_read_only(&sqlite).await {
                Err(EvidenceError::Corrupt(_)) => {}
                Err(error) => return Err(format!("wrong {name} error: {error}").into()),
                Ok(reopened) => {
                    reopened.close().await;
                    return Err(format!("startup admitted {name} with {alteration:?}").into());
                }
            }
        }
    }
    Ok(())
}

#[tokio::test]
async fn governance_immutable_guards_reject_disabled_definitions() -> TestResult {
    rejects_disabled_guards(&GOVERNANCE_GUARDS).await
}

#[tokio::test]
async fn provider_immutable_guards_reject_disabled_definitions() -> TestResult {
    rejects_disabled_guards(&PROVIDER_GUARDS).await
}

#[tokio::test]
async fn legacy_immutable_guards_preserve_legitimate_layout_and_later_migrations() -> TestResult {
    let temp = tempfile::tempdir()?;
    let sqlite =
        SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().canonicalize()?)?);
    let store = HeptaEvidenceStore::open(&sqlite).await?;
    for name in GOVERNANCE_GUARDS.into_iter().chain(PROVIDER_GUARDS) {
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
    }
    store.close().await;
    let reopened = HeptaEvidenceStore::open_existing_read_only(&sqlite).await?;
    reopened.close().await;
    Ok(())
}

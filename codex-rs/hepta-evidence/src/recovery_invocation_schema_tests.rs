use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::Connection;
use sqlx::SqliteConnection;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::recovery_invocation_schema::verify;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

const INTENT_KEYS: &str = "CREATE TABLE provider_invocation_intents (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL UNIQUE,
    request_binding_id TEXT NOT NULL,
    UNIQUE(attempt_id, request_binding_id)
);";
const TERMINAL_KEYS: &str = "CREATE TABLE provider_invocation_terminals (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    attempt_id TEXT NOT NULL UNIQUE
);";

async fn key_connection(intents: &str, terminals: &str) -> Result<SqliteConnection> {
    let mut connection = SqliteConnection::connect("sqlite::memory:").await?;
    sqlx::raw_sql(&format!("{intents}\n{terminals}"))
        .execute(&mut connection)
        .await?;
    Ok(connection)
}

#[tokio::test]
async fn recovery_invocation_schema_accepts_current_migration_keys() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let config =
        SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf())?);
    let store = HeptaEvidenceStore::open(&config).await?;
    let mut transaction = store.pool.begin().await?;
    verify(&mut transaction).await?;
    transaction.commit().await?;
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn recovery_invocation_schema_refuses_non_rowid_or_composite_sequences() -> Result<()> {
    for (table, original) in [
        ("provider_invocation_intents", INTENT_KEYS),
        ("provider_invocation_terminals", TERMINAL_KEYS),
    ] {
        let sequence = "seq INTEGER PRIMARY KEY AUTOINCREMENT";
        let cases = [
            ("missing", original.replace(sequence, "seq INTEGER")),
            (
                "nullable non-rowid",
                original.replace(sequence, "seq INT PRIMARY KEY"),
            ),
            (
                "descending inline primary key",
                original.replace(sequence, "seq INTEGER PRIMARY KEY DESC"),
            ),
            (
                "composite",
                original
                    .replace(sequence, "seq INTEGER NOT NULL")
                    .replace("\n);", ",\n    PRIMARY KEY(seq, attempt_id)\n);"),
            ),
            (
                "without rowid",
                original
                    .replace(sequence, "seq INTEGER PRIMARY KEY")
                    .replace("\n);", "\n) WITHOUT ROWID;"),
            ),
        ];
        for (case, altered) in cases {
            let (intents, terminals) = if table == "provider_invocation_intents" {
                (altered.as_str(), TERMINAL_KEYS)
            } else {
                (INTENT_KEYS, altered.as_str())
            };
            let mut connection = key_connection(intents, terminals).await?;
            assert!(
                matches!(
                    verify(&mut connection).await,
                    Err(EvidenceError::Corrupt(_))
                ),
                "accepted {table}: {case}"
            );
        }
    }
    Ok(())
}

#[tokio::test]
async fn recovery_invocation_schema_requires_exact_unconditional_column_uniqueness() -> Result<()> {
    #[derive(Clone, Copy, Debug)]
    enum Replacement {
        Missing,
        NonUnique,
        Partial,
        Expression,
        ExtraColumn,
        OtherCollation,
    }
    let intents = INTENT_KEYS
        .replace(
            "attempt_id TEXT NOT NULL UNIQUE",
            "attempt_id TEXT NOT NULL",
        )
        .replace(",\n    UNIQUE(attempt_id, request_binding_id)", "");
    let terminals = TERMINAL_KEYS.replace("TEXT NOT NULL UNIQUE", "TEXT NOT NULL");
    let required: [(&str, &str, &[&str]); 4] = [
        (
            "intent_attempt",
            "provider_invocation_intents",
            &["attempt_id"],
        ),
        (
            "intent_pair",
            "provider_invocation_intents",
            &["attempt_id", "request_binding_id"],
        ),
        (
            "terminal_receipt",
            "provider_invocation_terminals",
            &["receipt_id"],
        ),
        (
            "terminal_attempt",
            "provider_invocation_terminals",
            &["attempt_id"],
        ),
    ];
    for (name, table, columns) in required {
        for replacement in [
            Replacement::Missing,
            Replacement::NonUnique,
            Replacement::Partial,
            Replacement::Expression,
            Replacement::ExtraColumn,
            Replacement::OtherCollation,
        ] {
            let mut connection = key_connection(&intents, &terminals).await?;
            for (index, owner, keys) in required {
                sqlx::query(&format!(
                    "CREATE UNIQUE INDEX {index} ON {owner} ({})",
                    keys.join(", ")
                ))
                .execute(&mut connection)
                .await?;
            }
            // Establish a real accepted control before replacing exactly one
            // key with a structure that cannot supply its original guarantee.
            verify(&mut connection).await?;
            sqlx::query(&format!("DROP INDEX {name}"))
                .execute(&mut connection)
                .await?;
            let keys = columns.join(", ");
            let replacement_sql = match replacement {
                Replacement::Missing => None,
                Replacement::NonUnique => Some(format!("CREATE INDEX {name} ON {table} ({keys})")),
                Replacement::Partial => Some(format!(
                    "CREATE UNIQUE INDEX {name} ON {table} ({keys}) WHERE seq > 0"
                )),
                Replacement::Expression => {
                    let mut keys: Vec<_> = columns.iter().map(ToString::to_string).collect();
                    keys[0] = format!("lower({})", keys[0]);
                    Some(format!(
                        "CREATE UNIQUE INDEX {name} ON {table} ({})",
                        keys.join(", ")
                    ))
                }
                Replacement::ExtraColumn => Some(format!(
                    "CREATE UNIQUE INDEX {name} ON {table} ({keys}, seq)"
                )),
                Replacement::OtherCollation => {
                    let mut keys: Vec<_> = columns.iter().map(ToString::to_string).collect();
                    keys[0] = format!("{} COLLATE NOCASE", keys[0]);
                    Some(format!(
                        "CREATE UNIQUE INDEX {name} ON {table} ({})",
                        keys.join(", ")
                    ))
                }
            };
            if let Some(sql) = replacement_sql {
                sqlx::query(&sql).execute(&mut connection).await?;
            }
            assert!(
                matches!(
                    verify(&mut connection).await,
                    Err(EvidenceError::Corrupt(_))
                ),
                "accepted {name}: {replacement:?}"
            );
        }
    }
    Ok(())
}

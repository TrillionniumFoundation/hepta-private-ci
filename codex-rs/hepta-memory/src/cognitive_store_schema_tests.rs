#[cfg(unix)]
use std::collections::BTreeMap;
#[cfg(unix)]
use std::ffi::OsString;
#[cfg(unix)]
use std::path::Path;

#[cfg(unix)]
use codex_hepta_contracts::AgentId;
#[cfg(unix)]
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use sqlx::SqlitePool;
use sqlx::sqlite::SqlitePoolOptions;
use tempfile::TempDir;

use super::super::CognitiveStore;
use super::super::CognitiveStoreError;
use super::super::MIGRATOR;
use super::super::verify_store;
use super::MIGRATIONS_SCHEMA;
#[cfg(unix)]
use crate::CognitiveRecoveryError;
#[cfg(unix)]
use crate::CognitiveRecoveryRequirement;
#[cfg(unix)]
use crate::ProductionAuthorityLease;
#[cfg(unix)]
use crate::ProductionAuthorityToken;
#[cfg(unix)]
use crate::ProductionAuthorityVerifier;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

#[derive(Clone, Copy, Debug)]
enum SchemaAttack {
    RequiredCheck,
    UnregisteredCheck,
    MigrationCheck,
    OwnerTrigger,
    MigrationTrigger,
    ShadowCheck,
}

const ATTACKS: [SchemaAttack; 6] = [
    SchemaAttack::RequiredCheck,
    SchemaAttack::UnregisteredCheck,
    SchemaAttack::MigrationCheck,
    SchemaAttack::OwnerTrigger,
    SchemaAttack::MigrationTrigger,
    SchemaAttack::ShadowCheck,
];

impl SchemaAttack {
    fn rejection(self) -> &'static str {
        match self {
            Self::RequiredCheck => "schema definition oracle mismatch",
            Self::UnregisteredCheck => "unregistered cognitive table",
            Self::MigrationCheck => "migration ledger schema mismatch",
            Self::OwnerTrigger => "unregistered cognitive executable schema",
            Self::MigrationTrigger => "unregistered cognitive migration ledger executable schema",
            Self::ShadowCheck => "compiled cognitive schema definition oracle mismatch",
        }
    }

    async fn install(self, pool: &SqlitePool) {
        // These fixed hostile expressions fail with SQLITE_TOOBIG if executed.
        // zeroblob is lazy, so the regression never allocates a giant payload.
        let sql = match self {
            Self::RequiredCheck => {
                "PRAGMA writable_schema = ON;
                 UPDATE sqlite_schema SET sql = replace(sql,
                    'CHECK (singleton = 1)',
                    'CHECK (length(zeroblob(9223372036854775807)) = 0)')
                 WHERE name = 'cognitive_meta';
                 PRAGMA writable_schema = OFF;"
            }
            Self::UnregisteredCheck => {
                "CREATE TABLE sqliteXunexpected_owner_table (
                    value INTEGER CHECK (length(zeroblob(9223372036854775807)) = 0)
                 );
                 PRAGMA ignore_check_constraints = ON;
                 INSERT INTO sqliteXunexpected_owner_table VALUES (1);
                 PRAGMA ignore_check_constraints = OFF;"
            }
            Self::MigrationCheck => {
                "PRAGMA writable_schema = ON;
                 UPDATE sqlite_schema SET sql = replace(sql,
                    'execution_time BIGINT NOT NULL',
                    'execution_time BIGINT NOT NULL CHECK (length(zeroblob(9223372036854775807)) = 0)')
                 WHERE name = '_sqlx_migrations';
                 PRAGMA writable_schema = OFF;"
            }
            Self::OwnerTrigger => {
                "CREATE TRIGGER unexpected_meta_insert BEFORE INSERT ON cognitive_meta
                 BEGIN SELECT length(zeroblob(9223372036854775807)); END;"
            }
            Self::MigrationTrigger => {
                "CREATE TRIGGER unexpected_migration_insert BEFORE INSERT ON _sqlx_migrations
                 BEGIN SELECT length(zeroblob(9223372036854775807)); END;"
            }
            Self::ShadowCheck => {
                "PRAGMA writable_schema = ON;
                 UPDATE sqlite_schema SET sql = replace(sql,
                    'block BLOB)',
                    'block BLOB CHECK (length(zeroblob(9223372036854775807)) = 0))')
                 WHERE name = 'memory_fts_data';
                 PRAGMA writable_schema = OFF;"
            }
        };
        sqlx::raw_sql(sql)
            .execute(pool)
            .await
            .expect("install fixed resource attack without evaluating it");
    }
}

#[tokio::test]
async fn pinned_sqlx_migrator_independently_matches_migration_schema_oracle() {
    let pool = SqlitePoolOptions::new()
        .max_connections(/*max*/ 1)
        .connect("sqlite::memory:")
        .await
        .expect("independent SQLite");
    MIGRATOR.run(&pool).await.expect("compiled migrator");
    let actual: String =
        sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = '_sqlx_migrations'")
            .fetch_one(&pool)
            .await
            .expect("actual SQLx-created migration definition");
    assert_eq!(actual, MIGRATIONS_SCHEMA);
    pool.close().await;
}

#[tokio::test]
async fn ordinary_open_and_verification_reject_schema_resources_before_evaluation() {
    for attack in ATTACKS {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(89);
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("trusted seed");
        attack.install(&store.pool).await;
        assert!(
            matches!(verify_store(&store.pool, &owner).await,
                Err(CognitiveStoreError::Corrupt(message)) if message.contains(attack.rejection())),
            "schema rejection must precede executable integrity scans: {attack:?}"
        );
        assert!(
            matches!(store.recovery_anchor().await,
                Err(CognitiveStoreError::Corrupt(message)) if message.contains(attack.rejection())),
            "an attacked schema cannot mint an owner witness: {attack:?}"
        );
        store.pool.close().await;
        drop(store);
        assert!(
            matches!(CognitiveStore::open(&layout(&temp, &owner)).await,
                Err(CognitiveStoreError::Corrupt(message)) if message.contains(attack.rejection())),
            "schema rejection must precede migration/owner writes: {attack:?}"
        );
    }
}

#[cfg(unix)]
struct Verifier;

#[cfg(unix)]
impl ProductionAuthorityVerifier for Verifier {
    fn verify(
        &self,
        _authority: &ProductionAuthorityLease,
        _expected_agent: &AgentId,
    ) -> Result<(), String> {
        Ok(())
    }
}

#[cfg(unix)]
fn source_bytes(root: &Path) -> BTreeMap<OsString, Vec<u8>> {
    std::fs::read_dir(root)
        .expect("source directory")
        .map(|entry| {
            let entry = entry.expect("source entry");
            (
                entry.file_name(),
                std::fs::read(entry.path()).expect("source bytes"),
            )
        })
        .collect()
}

#[cfg(unix)]
#[tokio::test]
async fn write_and_read_only_recovery_reject_schema_resources_without_source_mutation() {
    for attack in ATTACKS {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(90);
        let owner_layout = layout(&temp, &owner);
        let store = CognitiveStore::open(&owner_layout)
            .await
            .expect("trusted seed");
        let anchor = store
            .recovery_anchor()
            .await
            .expect("independent valid cut");
        attack.install(&store.pool).await;
        store.pool.close().await;
        drop(store);
        let before = source_bytes(owner_layout.cognitive_root());
        let authority = ProductionAuthorityLease::from_verified_parts(
            owner.clone(),
            Sha256Digest::for_bytes(b"schema-resource recovery grant"),
            1,
            1,
            u64::MAX,
            ProductionAuthorityToken::from_verified_bytes(b"schema-resource fence".to_vec())
                .expect("token"),
        )
        .expect("authority");
        assert!(
            matches!(CognitiveStore::open_with_recovery(
                &owner_layout,
                CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
                &authority,
                &Verifier,
            ).await,
                Err(CognitiveRecoveryError::Indeterminate(message)) if message.contains(attack.rejection())),
            "write recovery must reject before integrity evaluation: {attack:?}"
        );
        assert_eq!(source_bytes(owner_layout.cognitive_root()), before);
        assert!(
            matches!(CognitiveStore::open_read_only_recovery(
                &owner_layout,
                CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            ).await,
                Err(CognitiveRecoveryError::Indeterminate(message)) if message.contains(attack.rejection())),
            "read-only recovery must reject before integrity evaluation: {attack:?}"
        );
        assert_eq!(source_bytes(owner_layout.cognitive_root()), before);
    }
}

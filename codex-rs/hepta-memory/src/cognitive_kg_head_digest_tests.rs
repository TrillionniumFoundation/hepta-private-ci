use pretty_assertions::assert_eq;
use sqlx::Row;
use sqlx::Sqlite;
use tempfile::TempDir;

use super::ProjectionHead;
use super::input_head_rows_digest;
use super::input_heads_digest;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

#[tokio::test]
async fn borrowed_sqlite_head_rows_preserve_the_complete_reference_digest() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(/*suffix*/ 110);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let scopes = [
        CognitiveScope::AgentPrivate.projection_key(),
        CognitiveScope::WorkspacePrivate {
            workspace_sha256: workspace("borrowed head digest"),
        }
        .projection_key(),
    ];

    for count in [0_usize, 1, 512] {
        let bound = i64::try_from(count).expect("bounded fixture");
        let rows = sqlx::query(
            "WITH RECURSIVE numbers(n) AS (
                 SELECT 0 WHERE ? > 0
                 UNION ALL SELECT n + 1 FROM numbers WHERE n + 1 < ?
             )
             SELECT printf('memory:v%d:%064x', 1 + n % 2, n + 1) AS memory_id,
                    1 + n % 32 AS revision,
                    printf('%064x', 1000 + n) AS content_sha256,
                    CASE WHEN n % 2 = 0 THEN 'verified' ELSE 'provisional' END AS verification,
                    CASE WHEN n % 3 = 0 THEN 'tombstoned' ELSE 'active' END AS lifecycle,
                    printf('%064x', 2000 + n) AS fact_set_sha256,
                    n % 5 AS entity_count, n % 7 AS relation_count,
                    n % 5 AS actual_entity_count, n % 7 AS actual_relation_count
             FROM numbers ORDER BY memory_id",
        )
        .bind(bound)
        .bind(bound)
        .fetch_all(&store.pool)
        .await
        .expect("real ordered SQLite rows");
        let mut reference = (0..count)
            .map(|index| ProjectionHead {
                memory_id: format!("memory:v{}:{:064x}", 1 + index % 2, index + 1),
                revision: i64::try_from(1 + index % 32).expect("bounded revision"),
                content_sha256: format!("{:064x}", 1000 + index),
                verification: if index % 2 == 0 {
                    "verified"
                } else {
                    "provisional"
                }
                .to_string(),
                lifecycle: if index % 3 == 0 {
                    "tombstoned"
                } else {
                    "active"
                }
                .to_string(),
                fact_set_sha256: format!("{:064x}", 2000 + index),
            })
            .collect::<Vec<_>>();
        reference.sort_by(|left, right| left.memory_id.cmp(&right.memory_id));
        assert_eq!(rows.len(), reference.len());
        for scope in &scopes {
            assert_eq!(
                input_head_rows_digest(scope, &rows).expect("checked row digest"),
                input_heads_digest(scope, &reference),
                "{count} heads in {scope}"
            );
        }
    }
}

#[tokio::test]
async fn borrowed_sqlite_head_rows_reject_incomplete_receipts_and_invalid_actual_values() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(/*suffix*/ 111);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let corrupt = [
        (
            "missing immutable receipt",
            sqlx::query::<Sqlite>(
                "SELECT 'memory', 1, 'content', 'verified', 'active', NULL, 0, 0, 0, 0",
            ),
        ),
        (
            "declared entity count differs",
            sqlx::query::<Sqlite>(
                "SELECT 'memory', 1, 'content', 'verified', 'active', printf('%064x', 1), 1, 0, 0, 0",
            ),
        ),
        (
            "declared relation count differs",
            sqlx::query::<Sqlite>(
                "SELECT 'memory', 1, 'content', 'verified', 'active', printf('%064x', 1), 0, 0, 0, 1",
            ),
        ),
    ];
    for (label, query) in corrupt {
        let row = query.fetch_one(&store.pool).await.expect("SQLite row");
        assert!(
            matches!(
                input_head_rows_digest("agent_private", &[row]),
                Err(CognitiveStoreError::Corrupt(_))
            ),
            "{label}"
        );
    }
    for malformed in [
        "a".repeat(63),
        "a".repeat(65),
        "A".repeat(64),
        "g".repeat(64),
    ] {
        let row = sqlx::query("SELECT 'memory', 1, 'content', 'verified', 'active', ?, 0, 0, 0, 0")
            .bind(&malformed)
            .fetch_one(&store.pool)
            .await
            .expect("malformed digest SQLite row");
        assert!(matches!(
            input_head_rows_digest("agent_private", &[row]),
            Err(CognitiveStoreError::Corrupt(_))
        ));
    }
    let invalid_values = [
        (
            "missing selected count column",
            sqlx::query::<Sqlite>(
                "SELECT 'memory', 1, 'content', 'verified', 'active', printf('%064x', 1), 0, 0, 0",
            ),
        ),
        (
            "INTEGER digest",
            sqlx::query::<Sqlite>(
                "SELECT 'memory', 1, 'content', 'verified', 'active', 1, 0, 0, 0, 0",
            ),
        ),
        (
            "BLOB text field",
            sqlx::query::<Sqlite>(
                "SELECT X'6d656d6f7279', 1, 'content', 'verified', 'active', printf('%064x', 1), 0, 0, 0, 0",
            ),
        ),
        (
            "invalid UTF-8 text field",
            sqlx::query::<Sqlite>(
                "SELECT CAST(X'ff00fe' AS TEXT), 1, 'content', 'verified', 'active', printf('%064x', 1), 0, 0, 0, 0",
            ),
        ),
        (
            "TEXT revision",
            sqlx::query::<Sqlite>(
                "SELECT 'memory', '1', 'content', 'verified', 'active', printf('%064x', 1), 0, 0, 0, 0",
            ),
        ),
    ];
    for (label, query) in invalid_values {
        let row = query.fetch_one(&store.pool).await.expect("SQLite row");
        assert!(
            matches!(
                input_head_rows_digest("agent_private", &[row]),
                Err(CognitiveStoreError::Unavailable(_))
            ),
            "{label}"
        );
    }
}

async fn reference_heads(store: &CognitiveStore, scope: &CognitiveScope) -> Vec<ProjectionHead> {
    let (scope_kind, workspace_sha256) = scope.database_parts();
    sqlx::query(
        "SELECT r.memory_id, r.revision, r.content_sha256,
                r.verification, r.lifecycle, s.fact_set_sha256
         FROM memory_heads h
         JOIN memory_revisions r ON r.memory_id = h.memory_id AND r.revision = h.revision
         JOIN kg_revision_fact_sets s
           ON s.memory_id = r.memory_id AND s.memory_revision = r.revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
         ORDER BY r.memory_id",
    )
    .bind(store.owner_agent_id.as_str())
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_all(&store.pool)
    .await
    .expect("reference heads")
    .into_iter()
    .map(|row| ProjectionHead {
        memory_id: row.try_get("memory_id").expect("memory id"),
        revision: row.try_get("revision").expect("revision"),
        content_sha256: row.try_get("content_sha256").expect("content digest"),
        verification: row.try_get("verification").expect("verification"),
        lifecycle: row.try_get("lifecycle").expect("lifecycle"),
        fact_set_sha256: row.try_get("fact_set_sha256").expect("fact digest"),
    })
    .collect()
}

#[tokio::test]
async fn borrowed_head_digest_public_corrections_reopen_with_independently_rebuilt_scope_digests() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(/*suffix*/ 112);
    let store_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&store_layout).await.expect("store");
    let private_access = CognitiveAccess::agent_private(owner.clone());
    let workspace_sha256 = workspace("digest scope");
    let workspace_scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_sha256.clone(),
    };
    let workspace_access = CognitiveAccess::workspace_private(owner, workspace_sha256);
    let mut receipts = Vec::new();
    for (access, scope, key, content) in [
        (
            &private_access,
            CognitiveScope::AgentPrivate,
            "z",
            "Private initial.",
        ),
        (
            &workspace_access,
            workspace_scope.clone(),
            "z",
            "Workspace initial.",
        ),
        (
            &private_access,
            CognitiveScope::AgentPrivate,
            "a",
            "Private second head.",
        ),
    ] {
        receipts.push(
            store
                .remember_with_kg(
                    access,
                    &source(scope.clone(), key, content),
                    &MemoryDraft {
                        stable_key: key.to_string(),
                        revision: MemoryRevisionDraft {
                            scope,
                            content: content.to_string(),
                            verification: MemoryVerification::Verified,
                            lifecycle: MemoryLifecycleState::Active,
                            valid_from_unix_seconds: 100,
                            valid_to_unix_seconds: None,
                            citations: Vec::new(),
                        },
                    },
                    &KgFactSetDraft::default(),
                )
                .await
                .expect("scoped public remember"),
        );
    }
    let content = "Private corrected.";
    let corrected = store
        .correct_with_kg(
            &private_access,
            &receipts[0].memory.id.memory_id,
            receipts[0].memory.id.revision,
            &source(CognitiveScope::AgentPrivate, "correction", content),
            &MemoryRevisionDraft {
                scope: CognitiveScope::AgentPrivate,
                content: content.to_string(),
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 100,
                valid_to_unix_seconds: None,
                citations: Vec::new(),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("public correction with retained history");
    for (scope, expected) in [
        (&CognitiveScope::AgentPrivate, &corrected.projection),
        (&workspace_scope, &receipts[1].projection),
    ] {
        let heads = reference_heads(&store, scope).await;
        assert_eq!(
            expected.input_heads_sha256,
            input_heads_digest(&scope.projection_key(), &heads)
        );
    }
    let anchor = store.recovery_anchor().await.expect("exact anchor");
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&store_layout)
        .await
        .expect("independent reopen digest verification");
    assert_eq!(
        reopened.recovery_anchor().await.expect("reopened anchor"),
        anchor
    );
    assert_eq!(
        reopened
            .latest_memory(&private_access, &corrected.memory.id.memory_id)
            .await
            .expect("private corrected head"),
        corrected.memory
    );
    assert_eq!(
        reopened
            .latest_memory(&workspace_access, &receipts[1].memory.id.memory_id)
            .await
            .expect("workspace head"),
        receipts[1].memory
    );
    for (scope, expected) in [
        (&CognitiveScope::AgentPrivate, &corrected.projection),
        (&workspace_scope, &receipts[1].projection),
    ] {
        assert_eq!(
            expected.input_heads_sha256,
            input_heads_digest(
                &scope.projection_key(),
                &reference_heads(&reopened, scope).await
            )
        );
    }
}

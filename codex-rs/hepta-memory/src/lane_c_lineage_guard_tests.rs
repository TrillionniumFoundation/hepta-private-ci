use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::MemoryDraft;
use crate::MemoryVerification;
use crate::StableMemoryId;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

#[tokio::test]
async fn owner_metadata_guard_rejects_oversized_and_missing_metadata_before_text_projection() {
    enum Attack {
        MemoryId,
        CitedSourceId,
        SourceOwner,
        MissingSource,
        OtherWorkspaceSourceId,
    }
    for attack in [
        Attack::MemoryId,
        Attack::CitedSourceId,
        Attack::SourceOwner,
        Attack::MissingSource,
        Attack::OtherWorkspaceSourceId,
    ] {
        let temp = TempDir::new().unwrap();
        let owner = agent_id(/*suffix*/ 119);
        let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
        let access = CognitiveAccess::agent_private(owner.clone());
        let scope = CognitiveScope::AgentPrivate;
        let citation = store
            .append_source(&access, &source(scope.clone(), "metadata", "evidence"))
            .await
            .unwrap();
        let memory = store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: "metadata".to_string(),
                    revision: memory_revision(scope.clone(), "fact", citation.clone()),
                },
            )
            .await
            .unwrap();
        let oversized = "x".repeat(1024 * 1024);
        match attack {
            Attack::MemoryId => {
                sqlx::query("INSERT INTO memory_revisions SELECT ?, revision, owner_agent_id, scope_kind, workspace_sha256, content, content_sha256, verification, lifecycle, tombstone_reason, valid_from_unix_seconds, valid_to_unix_seconds, supersedes_revision, recorded_at_unix_seconds FROM memory_revisions WHERE memory_id = ? AND revision = 1")
                    .bind(&oversized).bind(memory.id.memory_id.as_str()).execute(&store.pool).await.unwrap();
                sqlx::query("INSERT INTO memory_heads VALUES (?, 1)")
                    .bind(&oversized)
                    .execute(&store.pool)
                    .await
                    .unwrap();
            }
            Attack::CitedSourceId | Attack::SourceOwner => {
                let (source_id, source_owner) = match attack {
                    Attack::CitedSourceId => (oversized.as_str(), owner.as_str()),
                    Attack::SourceOwner => ("source:oversized-owner", oversized.as_str()),
                    Attack::MemoryId | Attack::MissingSource | Attack::OtherWorkspaceSourceId => {
                        unreachable!()
                    }
                };
                sqlx::query("INSERT INTO source_ledger SELECT ?, source_revision, ?, scope_kind, workspace_sha256, source_kind, content, content_sha256, observed_at_unix_seconds, recorded_at_unix_seconds FROM source_ledger WHERE source_id = ?")
                    .bind(source_id).bind(source_owner).bind(citation.source_id.as_str()).execute(&store.pool).await.unwrap();
                sqlx::query("INSERT INTO memory_citations VALUES (?, 1, 1, ?, 1)")
                    .bind(memory.id.memory_id.as_str())
                    .bind(source_id)
                    .execute(&store.pool)
                    .await
                    .unwrap();
            }
            Attack::MissingSource => {
                let mut connection = store.pool.acquire().await.unwrap();
                sqlx::query("PRAGMA foreign_keys = OFF")
                    .execute(&mut *connection)
                    .await
                    .unwrap();
                sqlx::query("INSERT INTO memory_citations VALUES (?, 1, 1, 'source:missing', 1)")
                    .bind(memory.id.memory_id.as_str())
                    .execute(&mut *connection)
                    .await
                    .unwrap();
                sqlx::query("PRAGMA foreign_keys = ON")
                    .execute(&mut *connection)
                    .await
                    .unwrap();
            }
            Attack::OtherWorkspaceSourceId => {
                sqlx::query("INSERT INTO source_ledger SELECT ?, source_revision, owner_agent_id, 'workspace_private', ?, source_kind, content, content_sha256, observed_at_unix_seconds, recorded_at_unix_seconds FROM source_ledger WHERE source_id = ?")
                    .bind(&oversized).bind(workspace("overflow-other-workspace").as_str())
                    .bind(citation.source_id.as_str()).execute(&store.pool).await.unwrap();
            }
        }
        let results = [
            store
                .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
                .await
                .map(|_| ()),
            store
                .lane_c_snapshot(&access, &scope, /*now_unix_seconds*/ 300)
                .await
                .map(|_| ()),
            store
                .lane_c_snapshot_page(
                    &access, &scope, /*now_unix_seconds*/ 300, /*maximum_heads*/ 1,
                    /*after*/ None,
                )
                .await
                .map(|_| ()),
        ];
        for result in results {
            assert!(
                matches!(result, Err(CognitiveStoreError::Corrupt(reason)) if reason.contains("metadata boundary"))
            );
        }
    }
}

#[tokio::test]
async fn excluded_head_eligibility_tampering_changes_exact_lineage_binding() {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 120);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "excluded", "evidence"))
        .await
        .unwrap();
    let mut revision = memory_revision(scope.clone(), "future head", citation);
    revision.verification = MemoryVerification::Provisional;
    revision.valid_from_unix_seconds = 400;
    let memory = store
        .create_memory(
            &access,
            &MemoryDraft {
                stable_key: "excluded".to_string(),
                revision,
            },
        )
        .await
        .unwrap();
    let mut expected = store
        .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
        .await
        .unwrap();
    // Only this adversarial fixture disables an immutable-table trigger to
    // simulate post-open tampering without changing any revision/frontier.
    sqlx::query("DROP TRIGGER memory_revisions_no_update")
        .execute(&store.pool)
        .await
        .unwrap();
    for statement in [
        "UPDATE memory_revisions SET verification = 'verified' WHERE memory_id = ?",
        "UPDATE memory_revisions SET valid_from_unix_seconds = 500 WHERE memory_id = ?",
    ] {
        sqlx::query(statement)
            .bind(memory.id.memory_id.as_str())
            .execute(&store.pool)
            .await
            .unwrap();
        let current = store
            .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
            .await
            .unwrap();
        assert_eq!(current.owner_cut(), expected.owner_cut());
        assert_eq!(
            (
                current.source_head_count(),
                current.excluded_head_count(),
                current.records().len()
            ),
            (1, 1, 0)
        );
        assert_ne!(
            current.source_head_manifest_digest(),
            expected.source_head_manifest_digest()
        );
        assert_ne!(
            current.source_binding_digest(),
            expected.source_binding_digest()
        );
        assert!(matches!(
            store
                .revalidate_lane_c_lineage(
                    &access, &scope, &expected, /*now_unix_seconds*/ 300
                )
                .await,
            Err(CognitiveStoreError::Conflict(_))
        ));
        expected = current;
    }
}

#[tokio::test]
async fn pages_and_lineage_reject_missing_dangling_regressed_or_foreign_scope_heads() {
    enum Attack {
        Missing,
        Dangling,
        Regressed,
        ForeignScope,
    }
    for attack in [
        Attack::Missing,
        Attack::Dangling,
        Attack::Regressed,
        Attack::ForeignScope,
    ] {
        let temp = TempDir::new().unwrap();
        let owner = agent_id(/*suffix*/ 121);
        let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
        let access = CognitiveAccess::agent_private(owner);
        let scope = CognitiveScope::AgentPrivate;
        let citation = store
            .append_source(&access, &source(scope.clone(), "head", "evidence"))
            .await
            .unwrap();
        let memory = store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: "head".to_string(),
                    revision: memory_revision(scope.clone(), "v1", citation.clone()),
                },
            )
            .await
            .unwrap();
        store
            .correct_memory(
                &access,
                &memory.id.memory_id,
                memory.id.revision,
                &memory_revision(scope.clone(), "v2", citation),
            )
            .await
            .unwrap();
        let mut connection = store.pool.acquire().await.unwrap();
        sqlx::query("PRAGMA foreign_keys = OFF")
            .execute(&mut *connection)
            .await
            .unwrap();
        let statement = match attack {
            Attack::Missing => "DELETE FROM memory_heads WHERE memory_id = ?",
            Attack::Dangling => "UPDATE memory_heads SET revision = 3 WHERE memory_id = ?",
            Attack::Regressed => "UPDATE memory_heads SET revision = 1 WHERE memory_id = ?",
            Attack::ForeignScope => {
                sqlx::query("INSERT INTO memory_revisions SELECT memory_id, 3, owner_agent_id, 'workspace_private', ?, content, content_sha256, verification, lifecycle, tombstone_reason, valid_from_unix_seconds, valid_to_unix_seconds, 2, recorded_at_unix_seconds FROM memory_revisions WHERE memory_id = ? AND revision = 2")
                    .bind(workspace("other-head-scope").as_str()).bind(memory.id.memory_id.as_str()).execute(&mut *connection).await.unwrap();
                "UPDATE memory_heads SET revision = 3 WHERE memory_id = ?"
            }
        };
        sqlx::query(statement)
            .bind(memory.id.memory_id.as_str())
            .execute(&mut *connection)
            .await
            .unwrap();
        sqlx::query("PRAGMA foreign_keys = ON")
            .execute(&mut *connection)
            .await
            .unwrap();
        drop(connection);
        let results = [
            store
                .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
                .await
                .map(|_| ()),
            store
                .lane_c_snapshot(&access, &scope, /*now_unix_seconds*/ 300)
                .await
                .map(|_| ()),
            store
                .lane_c_snapshot_page(
                    &access, &scope, /*now_unix_seconds*/ 300, /*maximum_heads*/ 1,
                    /*after*/ None,
                )
                .await
                .map(|_| ()),
        ];
        for result in results {
            assert!(
                matches!(result, Err(CognitiveStoreError::Corrupt(reason)) if reason.contains("metadata boundary"))
            );
        }
    }
}

enum OrphanReference {
    Head,
    Citation,
}

async fn assert_post_open_orphan_reference_rejected(attack: OrphanReference) {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(/*suffix*/ 122);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(&access, &source(scope.clone(), "orphan-guard", "evidence"))
        .await
        .unwrap();
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "healthy-orphan-guard".to_string(),
                revision: memory_revision(scope.clone(), "healthy fact", citation.clone()),
            },
        )
        .await
        .unwrap();
    let healthy_lineage = store
        .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
        .await
        .unwrap();
    let healthy_snapshot = store
        .lane_c_snapshot(&access, &scope, /*now_unix_seconds*/ 300)
        .await
        .unwrap();
    let healthy_page = store
        .lane_c_snapshot_page(
            &access, &scope, /*now_unix_seconds*/ 300, /*maximum_heads*/ 1,
            /*after*/ None,
        )
        .await
        .unwrap();
    assert_eq!(healthy_lineage.owner_cut(), &healthy_snapshot);
    assert_eq!(healthy_page.records(), healthy_lineage.current_heads());
    assert_eq!(healthy_lineage.current_heads().len(), 1);

    // A normative, bounded owner ID has no revision. The attack changes only
    // its physical reference after open admission, not the legitimate memory.
    let orphan = StableMemoryId::for_key(&owner, &scope, "orphan-metadata");
    let mut connection = store.pool.acquire().await.unwrap();
    sqlx::query("PRAGMA foreign_keys = OFF")
        .execute(&mut *connection)
        .await
        .unwrap();
    match attack {
        OrphanReference::Head => {
            sqlx::query("INSERT INTO memory_heads (memory_id, revision) VALUES (?, 1)")
                .bind(orphan.as_str())
                .execute(&mut *connection)
                .await
                .unwrap();
        }
        OrphanReference::Citation => {
            sqlx::query("INSERT INTO memory_citations (memory_id, memory_revision, ordinal, source_id, source_revision) VALUES (?, 1, 0, ?, 1)")
                .bind(orphan.as_str()).bind(citation.source_id.as_str())
                .execute(&mut *connection).await.unwrap();
        }
    }
    sqlx::query("PRAGMA foreign_keys = ON")
        .execute(&mut *connection)
        .await
        .unwrap();
    let foreign_keys: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
        .fetch_one(&mut *connection)
        .await
        .unwrap();
    let violations: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM pragma_foreign_key_check")
        .fetch_one(&mut *connection)
        .await
        .unwrap();
    assert_eq!((foreign_keys, violations), (1, 1));
    drop(connection);

    let results = [
        store
            .lane_c_lineage(&access, &scope, /*now_unix_seconds*/ 300)
            .await
            .map(|_| ()),
        store
            .lane_c_snapshot(&access, &scope, /*now_unix_seconds*/ 300)
            .await
            .map(|_| ()),
        store
            .lane_c_snapshot_page(
                &access, &scope, /*now_unix_seconds*/ 300, /*maximum_heads*/ 1,
                /*after*/ None,
            )
            .await
            .map(|_| ()),
    ];
    assert_eq!(results.map(|result| matches!(
        result, Err(CognitiveStoreError::Corrupt(reason)) if reason.contains("metadata boundary")
    )), [true; 3]);
}

#[tokio::test]
async fn post_open_orphan_head_references_are_rejected_by_all_lane_c_readers() {
    assert_post_open_orphan_reference_rejected(OrphanReference::Head).await;
}

#[tokio::test]
async fn post_open_orphan_citation_references_are_rejected_by_all_lane_c_readers() {
    assert_post_open_orphan_reference_rejected(OrphanReference::Citation).await;
}

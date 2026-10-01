use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::*;
use crate::cognitive_kg_store::graph_source_vector_digest_tx;

async fn frontier_with_reference(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &str,
    scope: &CognitiveScope,
    snapshot: Digest32,
) -> (Digest32, i64) {
    let digest = graph_source_vector_digest_tx(transaction, owner, scope, snapshot)
        .await
        .expect("production graph source vector");
    let (scope_kind, workspace_sha256) = scope.database_parts();
    // Deduplicate citation identities independently of the production EXISTS
    // query and force the reference through actual source rows.
    let cited_sources = sqlx::query_scalar(
        "SELECT COUNT(*) FROM (
             SELECT c.source_id, c.source_revision FROM memory_citations c
             JOIN source_ledger s NOT INDEXED
               ON s.source_id = c.source_id AND s.source_revision = c.source_revision
             WHERE s.owner_agent_id = ? AND s.scope_kind = ? AND s.workspace_sha256 IS ?
             GROUP BY c.source_id, c.source_revision
         )",
    )
    .bind(owner)
    .bind(scope_kind)
    .bind(workspace_sha256)
    .fetch_one(&mut **transaction)
    .await
    .expect("independent cited-source frontier");
    (digest, cited_sources)
}

#[tokio::test]
async fn source_cover_index_preserves_cited_cuts_across_scopes_owners_and_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let scopes = [
        CognitiveScope::AgentPrivate,
        CognitiveScope::WorkspacePrivate {
            workspace_sha256: workspace("source-frontier-a"),
        },
        CognitiveScope::WorkspacePrivate {
            workspace_sha256: workspace("source-frontier-b"),
        },
    ];
    let facts = KgFactSetDraft {
        entities: vec![
            KgEntityFactDraft {
                key: "ada".to_string(),
                entity_type: "person".to_string(),
                label: "Ada Lovelace".to_string(),
            },
            KgEntityFactDraft {
                key: "engine".to_string(),
                entity_type: "machine".to_string(),
                label: "Analytical Engine".to_string(),
            },
        ],
        relations: vec![KgRelationFactDraft {
            key: "documented".to_string(),
            from_entity_key: "ada".to_string(),
            to_entity_key: "engine".to_string(),
            relation: "documented".to_string(),
        }],
    };
    // Each owner uses its own admitted physical database. Foreign local-owner
    // rows are never introduced as supposedly valid owner state.
    for (owner, foreign_owner) in [
        (agent_id(111), agent_id(112)),
        (agent_id(112), agent_id(111)),
    ] {
        let owner_layout = layout(&temp, &owner);
        let store = CognitiveStore::open(&owner_layout).await.expect("store");
        let mut cuts = Vec::new();
        for scope in &scopes {
            let access = match scope {
                CognitiveScope::AgentPrivate => CognitiveAccess::agent_private(owner.clone()),
                CognitiveScope::WorkspacePrivate { workspace_sha256 } => {
                    CognitiveAccess::workspace_private(owner.clone(), workspace_sha256.clone())
                }
            };
            let shared = source(scope.clone(), "shared-source", "Ada documented the engine.");
            let original = store
                .append_source(&access, &shared)
                .await
                .expect("initial standalone source");
            let mut memories = Vec::new();
            for stable_key in ["first", "second"] {
                let receipt = store
                    .remember_with_kg(
                        &access,
                        &shared,
                        &MemoryDraft {
                            stable_key: stable_key.to_string(),
                            revision: active_revision(
                                scope.clone(),
                                "Shared evidence",
                                /*valid_from*/ 100,
                            ),
                        },
                        &facts,
                    )
                    .await
                    .expect("two memories cite the same source");
                assert_eq!(receipt.source, original);
                memories.push(receipt);
            }
            let shared_cut =
                load_generation(&store, scope, memories[1].projection.generation.get()).await;
            store
                .append_source(
                    &access,
                    &source(scope.clone(), "uncited-source", "Uncited evidence"),
                )
                .await
                .expect("uncited source append");
            let mut transaction = store.pool.begin().await.expect("uncited cut transaction");
            assert_eq!(
                frontier_with_reference(
                    &mut transaction,
                    owner.as_str(),
                    scope,
                    shared_cut.source_snapshot_digest
                )
                .await,
                (shared_cut.generation_vector_digest, 1)
            );
            transaction.commit().await.expect("uncited cut read commit");

            let corrected = store
                .correct_with_kg(
                    &access,
                    &memories[0].memory.id.memory_id,
                    memories[0].memory.id.revision,
                    &source(scope.clone(), "correction-source", "Corrected evidence"),
                    &active_revision(scope.clone(), "Corrected evidence", /*valid_from*/ 200),
                    &facts,
                )
                .await
                .expect("source-backed correction");
            let cut = load_generation(&store, scope, corrected.projection.generation.get()).await;
            assert_eq!((cut.nodes.len(), cut.edges.len()), (2, 1));
            cuts.push((scope.clone(), cut));
        }

        let mut transaction = store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .expect("index comparison fence");
        let plan: Vec<(i64, i64, i64, String)> = sqlx::query_as(
            "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM source_ledger s
             WHERE s.owner_agent_id = ? AND s.scope_kind = ? AND s.workspace_sha256 IS ?
               AND EXISTS (SELECT 1 FROM memory_citations c
                           WHERE c.source_id = s.source_id AND c.source_revision = s.source_revision)",
        )
        .bind(owner.as_str())
        .bind("agent_private")
        .bind(Option::<&str>::None)
        .fetch_all(&mut *transaction)
        .await
        .expect("cited-source query plan");
        assert!(plan.iter().any(|(_, _, _, detail)| {
            detail.contains("COVERING INDEX source_ledger_scope_frontier")
        }));
        let mut indexed = Vec::new();
        for (scope, cut) in &cuts {
            let own = frontier_with_reference(
                &mut transaction,
                owner.as_str(),
                scope,
                cut.source_snapshot_digest,
            )
            .await;
            assert_eq!(own, (cut.generation_vector_digest, 2));
            let foreign = frontier_with_reference(
                &mut transaction,
                foreign_owner.as_str(),
                scope,
                cut.source_snapshot_digest,
            )
            .await;
            assert_eq!(foreign.1, 0);
            indexed.push((own, foreign));
        }
        // Transactional DDL exposes the old plan on the identical row snapshot;
        // rollback restores the compiled index before any public owner operation.
        sqlx::query("DROP INDEX source_ledger_scope_frontier")
            .execute(&mut *transaction)
            .await
            .expect("unindexed reference plan");
        let mut unindexed = Vec::new();
        for (scope, cut) in &cuts {
            unindexed.push((
                frontier_with_reference(
                    &mut transaction,
                    owner.as_str(),
                    scope,
                    cut.source_snapshot_digest,
                )
                .await,
                frontier_with_reference(
                    &mut transaction,
                    foreign_owner.as_str(),
                    scope,
                    cut.source_snapshot_digest,
                )
                .await,
            ));
        }
        assert_eq!(indexed, unindexed);
        transaction
            .rollback()
            .await
            .expect("restore compiled index");
        store.pool.close().await;
        drop(store);

        let reopened = CognitiveStore::open(&owner_layout)
            .await
            .expect("reopen indexed owner");
        for (scope, expected) in cuts {
            assert_eq!(
                load_generation(&reopened, &scope, expected.generation.get()).await,
                expected
            );
            assert_full_publication_history(&reopened, &scope).await;
            let mut transaction = reopened
                .pool
                .begin()
                .await
                .expect("reopened cut transaction");
            assert_eq!(
                frontier_with_reference(
                    &mut transaction,
                    owner.as_str(),
                    &scope,
                    expected.source_snapshot_digest
                )
                .await,
                (expected.generation_vector_digest, 2)
            );
            transaction
                .commit()
                .await
                .expect("reopened cut read commit");
        }
        reopened.pool.close().await;
    }
}

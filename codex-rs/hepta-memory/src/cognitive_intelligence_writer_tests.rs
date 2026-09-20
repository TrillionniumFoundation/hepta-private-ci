use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::ForgetMemoryDraft;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::LedgerSourceKind;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::SourceDraft;
use crate::cognitive_intelligence_writer::canonical_entity_id;
use crate::cognitive_kg_store::MAX_PROJECTION_SCOPES;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::workspace;

fn source(event_key: &str, content: &str) -> SourceDraft {
    SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: event_key.to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 100,
    }
}

fn revision(content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

fn facts(first_label: &str, second_key: &str) -> KgFactSetDraft {
    KgFactSetDraft {
        entities: vec![
            KgEntityFactDraft {
                key: "ada".to_string(),
                entity_type: "person".to_string(),
                label: first_label.to_string(),
            },
            KgEntityFactDraft {
                key: second_key.to_string(),
                entity_type: "project".to_string(),
                label: second_key.to_string(),
            },
        ],
        relations: vec![KgRelationFactDraft {
            key: "contributes".to_string(),
            from_entity_key: "ada".to_string(),
            to_entity_key: second_key.to_string(),
            relation: "contributes_to".to_string(),
        }],
    }
}

#[tokio::test]
async fn product_writer_atomically_remembers_corrects_forgets_and_blocks_resurrection() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(31);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let first_content = "Ada contributes to the analytical engine.";
    let first = store
        .remember_with_kg(
            &access,
            &source("remember", first_content),
            &MemoryDraft {
                stable_key: "ada-project".to_string(),
                revision: revision(first_content),
            },
            &facts("Ada Lovelace", "analytical engine"),
        )
        .await
        .expect("remember with KG");
    assert_eq!(first.projection.generation.get(), 1);
    assert_eq!(first.projection.node_count, 2);
    assert_eq!(first.projection.edge_count, 1);

    let corrected_content = "Ada contributes to the Bernoulli algorithm.";
    let corrected = store
        .correct_with_kg(
            &access,
            &first.memory.id.memory_id,
            1,
            &source("correct", corrected_content),
            &revision(corrected_content),
            &facts("Ada Lovelace", "bernoulli algorithm"),
        )
        .await
        .expect("correct with KG");
    assert_eq!(corrected.projection.generation.get(), 2);
    assert_eq!(corrected.memory.id.revision, 2);
    assert_eq!(corrected.projection.node_count, 2);
    assert_eq!(corrected.projection.edge_count, 1);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_revision_fact_sets")
            .fetch_one(&store.pool)
            .await
            .expect("fact-set count"),
        2
    );

    let sources_before_stale: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM source_ledger")
        .fetch_one(&store.pool)
        .await
        .expect("source count before stale CAS");
    let stale_content = "A stale correction must not leave an observation.";
    let stale = store
        .correct_with_kg(
            &access,
            &first.memory.id.memory_id,
            1,
            &source("stale-correction", stale_content),
            &revision(stale_content),
            &KgFactSetDraft::default(),
        )
        .await
        .expect_err("stale CAS must fail");
    assert!(matches!(stale, CognitiveStoreError::Conflict(_)));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM source_ledger")
            .fetch_one(&store.pool)
            .await
            .expect("stale source rollback"),
        sources_before_stale
    );

    let forgotten = store
        .forget_with_kg(
            &access,
            &first.memory.id.memory_id,
            2,
            &source("forget", "explicit forget"),
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "explicit forget".to_string(),
                valid_from_unix_seconds: 300,
                citations: Vec::new(),
            },
        )
        .await
        .expect("forget with KG");
    assert_eq!(forgotten.projection.generation.get(), 3);
    assert_eq!(forgotten.projection.entity_count, 0);
    assert_eq!(forgotten.projection.relation_count, 0);
    assert_eq!(forgotten.projection.node_count, 0);
    assert_eq!(forgotten.projection.edge_count, 0);
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM kg_nodes n JOIN kg_projection p
               ON p.projection_scope = n.projection_scope
              AND p.generation = n.generation",
        )
        .fetch_one(&store.pool)
        .await
        .expect("current node count"),
        0
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_revision_entities")
            .fetch_one(&store.pool)
            .await
            .expect("immutable history"),
        4
    );

    let sources_before: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM source_ledger")
        .fetch_one(&store.pool)
        .await
        .expect("source count");
    let error = store
        .correct_with_kg(
            &access,
            &first.memory.id.memory_id,
            3,
            &source("resurrect", "Ada returns."),
            &revision("Ada returns."),
            &KgFactSetDraft::default(),
        )
        .await
        .expect_err("tombstone cannot be resurrected");
    assert!(matches!(error, CognitiveStoreError::Conflict(_)));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM source_ledger")
            .fetch_one(&store.pool)
            .await
            .expect("source rollback"),
        sources_before
    );
}

#[tokio::test]
async fn projection_scope_limit_rolls_back_new_scope_but_allows_existing_scope_generation() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(30);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let agent_access = CognitiveAccess::agent_private(owner.clone());
    let first_content = "scope-limit seed";
    let first = store
        .remember_with_kg(
            &agent_access,
            &source("scope-limit-seed-source", first_content),
            &MemoryDraft {
                stable_key: "scope-limit-seed-memory".to_string(),
                revision: revision(first_content),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("seed existing projection scope");
    assert_eq!(first.projection.generation.get(), 1);

    let additional_scopes =
        i64::try_from(MAX_PROJECTION_SCOPES - 1).expect("projection scope limit fits i64");
    sqlx::query(
        "WITH digits(value) AS (
             VALUES (0), (1), (2), (3), (4), (5), (6), (7), (8), (9)
         ), scope_numbers(value) AS (
             SELECT ones.value + 10 * tens.value + 100 * hundreds.value
                    + 1000 * thousands.value
             FROM digits ones
             CROSS JOIN digits tens
             CROSS JOIN digits hundreds
             CROSS JOIN digits thousands
         )
         INSERT INTO kg_projection (projection_scope, generation)
         SELECT 'workspace_private:' || printf('%064x', value), 0
         FROM scope_numbers WHERE value < ?",
    )
    .bind(additional_scopes)
    .execute(&store.pool)
    .await
    .expect("seed test-only projection scope pointers under the exact insert trigger");
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_projection")
            .fetch_one(&store.pool)
            .await
            .expect("projection scope count"),
        i64::try_from(MAX_PROJECTION_SCOPES).expect("projection scope limit fits i64")
    );

    let counts_before = (
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM source_ledger")
            .fetch_one(&store.pool)
            .await
            .expect("source count"),
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory count"),
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_revision_fact_sets")
            .fetch_one(&store.pool)
            .await
            .expect("fact-set count"),
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_projection")
            .fetch_one(&store.pool)
            .await
            .expect("projection count"),
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_projection_generation_receipts")
            .fetch_one(&store.pool)
            .await
            .expect("projection receipt count"),
    );
    let workspace_sha256 = workspace("scope-limit-new-workspace");
    let workspace_scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_sha256.clone(),
    };
    let workspace_content = "must roll back at projection scope limit";
    let new_scope_error = store
        .remember_with_kg(
            &CognitiveAccess::workspace_private(owner.clone(), workspace_sha256),
            &SourceDraft {
                scope: workspace_scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "scope-limit-new-source".to_string(),
                content: workspace_content.as_bytes().to_vec(),
                observed_at_unix_seconds: 200,
            },
            &MemoryDraft {
                stable_key: "scope-limit-new-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: workspace_scope,
                    content: workspace_content.to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 200,
                    valid_to_unix_seconds: None,
                    citations: Vec::new(),
                },
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect_err("new projection scope must fail at the hard limit");
    assert!(matches!(
        new_scope_error,
        CognitiveStoreError::Invalid(message)
            if message.contains("10000-projection-scope limit")
    ));
    let counts_after = (
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM source_ledger")
            .fetch_one(&store.pool)
            .await
            .expect("source rollback count"),
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory rollback count"),
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_revision_fact_sets")
            .fetch_one(&store.pool)
            .await
            .expect("fact-set rollback count"),
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_projection")
            .fetch_one(&store.pool)
            .await
            .expect("projection rollback count"),
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_projection_generation_receipts")
            .fetch_one(&store.pool)
            .await
            .expect("projection receipt rollback count"),
    );
    assert_eq!(counts_after, counts_before);

    let corrected_content = "scope-limit existing scope correction";
    let corrected = store
        .correct_with_kg(
            &agent_access,
            &first.memory.id.memory_id,
            1,
            &source("scope-limit-correct-source", corrected_content),
            &revision(corrected_content),
            &KgFactSetDraft::default(),
        )
        .await
        .expect("existing projection scope may still advance");
    assert_eq!(corrected.projection.generation.get(), 2);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_projection")
            .fetch_one(&store.pool)
            .await
            .expect("existing scope does not add a pointer"),
        i64::try_from(MAX_PROJECTION_SCOPES).expect("projection scope limit fits i64")
    );

    sqlx::query(
        "INSERT INTO kg_projection (projection_scope, generation)
         VALUES ('workspace_private:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', 0)",
    )
    .execute(&store.pool)
    .await
    .expect("inject one test-only over-limit projection pointer");
    drop(store);
    let reopen_error = match CognitiveStore::open(&layout(&temp, &owner)).await {
        Ok(_) => panic!("over-limit projection pointers must fail reopen"),
        Err(error) => error,
    };
    assert!(
        matches!(
            reopen_error,
            CognitiveStoreError::Corrupt(ref message)
                if message.contains("10000-projection-scope limit")
        ),
        "unexpected reopen error: {reopen_error:?}"
    );
}

#[tokio::test]
async fn canonical_entity_keeps_multiple_occurrences_and_conflict_rolls_everything_back() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(32);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    for (stable_key, event_key, content) in [
        ("ada-engine", "source-engine", "Ada worked on Engine."),
        ("ada-notes", "source-notes", "Ada wrote Notes."),
    ] {
        store
            .remember_with_kg(
                &access,
                &source(event_key, content),
                &MemoryDraft {
                    stable_key: stable_key.to_string(),
                    revision: revision(content),
                },
                &KgFactSetDraft {
                    entities: vec![KgEntityFactDraft {
                        key: "ada".to_string(),
                        entity_type: "person".to_string(),
                        label: "Ada Lovelace".to_string(),
                    }],
                    relations: Vec::new(),
                },
            )
            .await
            .expect("same canonical entity support");
    }
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM kg_projection_node_entities i
             JOIN kg_projection p ON p.projection_scope = i.projection_scope
                                 AND p.generation = i.generation",
        )
        .fetch_one(&store.pool)
        .await
        .expect("current canonical occurrences"),
        2
    );
    let generation_before: i64 = sqlx::query_scalar(
        "SELECT generation FROM kg_projection WHERE projection_scope = 'agent_private'",
    )
    .fetch_one(&store.pool)
    .await
    .expect("generation");
    let sources_before: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM source_ledger")
        .fetch_one(&store.pool)
        .await
        .expect("sources");
    let error = store
        .remember_with_kg(
            &access,
            &source("source-conflict", "Ada alias."),
            &MemoryDraft {
                stable_key: "ada-alias".to_string(),
                revision: revision("Ada alias."),
            },
            &KgFactSetDraft {
                entities: vec![KgEntityFactDraft {
                    key: "ada".to_string(),
                    entity_type: "person".to_string(),
                    label: "Augusta Ada King".to_string(),
                }],
                relations: Vec::new(),
            },
        )
        .await
        .expect_err("conflicting canonical label must fail closed");
    assert!(matches!(error, CognitiveStoreError::Conflict(_)));
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM source_ledger")
            .fetch_one(&store.pool)
            .await
            .expect("source rollback"),
        sources_before
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT generation FROM kg_projection WHERE projection_scope = 'agent_private'",
        )
        .fetch_one(&store.pool)
        .await
        .expect("generation rollback"),
        generation_before
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM memory_heads")
            .fetch_one(&store.pool)
            .await
            .expect("head rollback"),
        2
    );
}

#[tokio::test]
async fn canonical_fact_order_and_identity_are_bound_to_a_hard_coded_oracle() {
    let owner = agent_id(33);
    let expected_entity_id = canonical_entity_id(&owner, &CognitiveScope::AgentPrivate, "ada");
    assert_eq!(
        expected_entity_id,
        "kg-entity:v1:02f3f72c0f1d3d18ce289249cb2dbbd0743553f1faf3bf74e4d8f0851342e48d"
    );
    let mut digests = Vec::new();
    for reversed in [false, true] {
        let temp = TempDir::new().expect("temp dir");
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("store");
        let access = CognitiveAccess::agent_private(owner.clone());
        let mut fact_set = facts("Ada Lovelace", "analytical engine");
        if reversed {
            fact_set.entities.reverse();
        }
        let content = "Ada contributes to the analytical engine.";
        let receipt = store
            .remember_with_kg(
                &access,
                &source("oracle-source", content),
                &MemoryDraft {
                    stable_key: "oracle-memory".to_string(),
                    revision: revision(content),
                },
                &fact_set,
            )
            .await
            .expect("oracle write");
        digests.push(receipt.projection.fact_set_sha256.as_str().to_string());
    }
    assert_eq!(digests[0], digests[1]);
    assert_eq!(
        digests[0],
        "8139a76f7892fe487fd9f05818ba28180e706bb1715d27b3b98b1e372305e91f"
    );
}

async fn seeded_store(temp: &TempDir, owner: &codex_hepta_contracts::AgentId) -> CognitiveStore {
    let store = CognitiveStore::open(&layout(temp, owner))
        .await
        .expect("seed store");
    let access = CognitiveAccess::agent_private(owner.clone());
    let content = "Ada contributes to the analytical engine.";
    store
        .remember_with_kg(
            &access,
            &source("seed-source", content),
            &MemoryDraft {
                stable_key: "seed-memory".to_string(),
                revision: revision(content),
            },
            &facts("Ada Lovelace", "analytical engine"),
        )
        .await
        .expect("seed write");
    store
}

#[tokio::test]
async fn projection_and_fact_receipts_survive_clean_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(34);
    let store = seeded_store(&temp, &owner).await;
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("verified reopen");
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT generation FROM kg_projection WHERE projection_scope = 'agent_private'",
        )
        .fetch_one(&reopened.pool)
        .await
        .expect("durable generation"),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM kg_revision_fact_sets")
            .fetch_one(&reopened.pool)
            .await
            .expect("durable fact set"),
        1
    );
}

#[tokio::test]
async fn reopen_rejects_same_name_permissive_trigger_and_fts_count_tampering() {
    let trigger_temp = TempDir::new().expect("temp dir");
    let trigger_owner = agent_id(35);
    let trigger_store = seeded_store(&trigger_temp, &trigger_owner).await;
    let mut trigger_connection = trigger_store
        .pool
        .acquire()
        .await
        .expect("trigger connection");
    sqlx::query("DROP TRIGGER kg_nodes_no_delete")
        .execute(&mut *trigger_connection)
        .await
        .expect("drop protected trigger");
    sqlx::query("CREATE TRIGGER kg_nodes_no_delete BEFORE DELETE ON kg_nodes BEGIN SELECT 1; END")
        .execute(&mut *trigger_connection)
        .await
        .expect("install permissive same-name trigger");
    drop(trigger_connection);
    trigger_store.pool.close().await;
    drop(trigger_store);
    assert!(matches!(
        CognitiveStore::open(&layout(&trigger_temp, &trigger_owner)).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));

    let fts_temp = TempDir::new().expect("temp dir");
    let fts_owner = agent_id(36);
    let fts_store = seeded_store(&fts_temp, &fts_owner).await;
    sqlx::query("DELETE FROM kg_entity_fts")
        .execute(&fts_store.pool)
        .await
        .expect("tamper FTS rows");
    fts_store.pool.close().await;
    drop(fts_store);
    assert!(matches!(
        CognitiveStore::open(&layout(&fts_temp, &fts_owner)).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));

    let pointer_temp = TempDir::new().expect("temp dir");
    let pointer_owner = agent_id(39);
    let pointer_store = seeded_store(&pointer_temp, &pointer_owner).await;
    let monotonic_sql: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'kg_projection_generation_monotonic'",
    )
    .fetch_one(&pointer_store.pool)
    .await
    .expect("monotonic trigger SQL");
    let receipt_sql: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'kg_projection_current_receipt_on_update'",
    )
    .fetch_one(&pointer_store.pool)
    .await
    .expect("receipt trigger SQL");
    let mut pointer_connection = pointer_store
        .pool
        .acquire()
        .await
        .expect("pointer connection");
    sqlx::query("DROP TRIGGER kg_projection_generation_monotonic")
        .execute(&mut *pointer_connection)
        .await
        .expect("drop monotonic trigger");
    sqlx::query("DROP TRIGGER kg_projection_current_receipt_on_update")
        .execute(&mut *pointer_connection)
        .await
        .expect("drop receipt trigger");
    sqlx::query("UPDATE kg_projection SET generation = 0")
        .execute(&mut *pointer_connection)
        .await
        .expect("tamper current pointer");
    sqlx::query(sqlx::AssertSqlSafe(monotonic_sql.as_str()))
        .execute(&mut *pointer_connection)
        .await
        .expect("restore monotonic trigger");
    sqlx::query(sqlx::AssertSqlSafe(receipt_sql.as_str()))
        .execute(&mut *pointer_connection)
        .await
        .expect("restore receipt trigger");
    drop(pointer_connection);
    pointer_store.pool.close().await;
    drop(pointer_store);
    assert!(matches!(
        CognitiveStore::open(&layout(&pointer_temp, &pointer_owner)).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

#[tokio::test]
async fn reopen_rejects_fact_count_and_canonical_digest_tampering() {
    let count_temp = TempDir::new().expect("temp dir");
    let count_owner = agent_id(37);
    let count_store = seeded_store(&count_temp, &count_owner).await;
    let fact_set_trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'kg_revision_fact_sets_no_update'",
    )
    .fetch_one(&count_store.pool)
    .await
    .expect("fact-set trigger SQL");
    let mut count_connection = count_store.pool.acquire().await.expect("count connection");
    sqlx::query("DROP TRIGGER kg_revision_fact_sets_no_update")
        .execute(&mut *count_connection)
        .await
        .expect("drop fact-set trigger");
    sqlx::query("UPDATE kg_revision_fact_sets SET entity_count = entity_count + 1")
        .execute(&mut *count_connection)
        .await
        .expect("tamper fact count");
    sqlx::query(sqlx::AssertSqlSafe(fact_set_trigger.as_str()))
        .execute(&mut *count_connection)
        .await
        .expect("restore exact fact-set trigger");
    drop(count_connection);
    count_store.pool.close().await;
    drop(count_store);
    assert!(matches!(
        CognitiveStore::open(&layout(&count_temp, &count_owner)).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));

    let digest_temp = TempDir::new().expect("temp dir");
    let digest_owner = agent_id(38);
    let digest_store = seeded_store(&digest_temp, &digest_owner).await;
    let entity_trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'kg_revision_entities_no_update'",
    )
    .fetch_one(&digest_store.pool)
    .await
    .expect("entity trigger SQL");
    let mut digest_connection = digest_store
        .pool
        .acquire()
        .await
        .expect("digest connection");
    sqlx::query("DROP TRIGGER kg_revision_entities_no_update")
        .execute(&mut *digest_connection)
        .await
        .expect("drop entity trigger");
    sqlx::query("UPDATE kg_revision_entities SET label = label || ' tampered'")
        .execute(&mut *digest_connection)
        .await
        .expect("tamper fact payload");
    sqlx::query(sqlx::AssertSqlSafe(entity_trigger.as_str()))
        .execute(&mut *digest_connection)
        .await
        .expect("restore exact entity trigger");
    drop(digest_connection);
    digest_store.pool.close().await;
    drop(digest_store);
    assert!(matches!(
        CognitiveStore::open(&layout(&digest_temp, &digest_owner)).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

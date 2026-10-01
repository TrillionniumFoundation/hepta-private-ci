use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::CognitiveStore;
use crate::RetrievalChannel;
use crate::RetrievalRequest;
use crate::cognitive_store::open_v2_test_pool;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

#[tokio::test]
async fn migrated_legacy_memory_is_readable_retrievable_and_correctable_without_rewriting_its_id() {
    let temp = TempDir::new().expect("temp directory");
    let owner = agent_id(/*suffix*/ 109);
    let owner_layout = layout(&temp, &owner);
    let pool = open_v2_test_pool(&owner_layout)
        .await
        .expect("actual compiled migration-v2 fixture");
    let legacy_id = format!("memory:v1:{}", "2".repeat(64));
    let mut seed = pool.begin().await.expect("fixture transaction");
    let mut citations = Vec::new();
    for (revision, event_key, content, valid_from, supersedes) in [
        (1_i64, "legacy-first", "Legacy amber draft.", 100_i64, None),
        (
            2_i64,
            "legacy-second",
            "Legacy cobalt observation.",
            200_i64,
            Some(1_i64),
        ),
    ] {
        let source_id = SourceEventId::for_event(
            &owner,
            &CognitiveScope::AgentPrivate,
            LedgerSourceKind::ExplicitMemoryDirective,
            event_key,
        );
        let content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
        sqlx::query(
            "INSERT INTO source_ledger (
                source_id, source_revision, owner_agent_id, scope_kind,
                workspace_sha256, source_kind, content, content_sha256,
                observed_at_unix_seconds, recorded_at_unix_seconds
             ) VALUES (?, 1, ?, 'agent_private', NULL,
                       'explicit_memory_directive', ?, ?, ?, ?)",
        )
        .bind(source_id.as_str())
        .bind(owner.as_str())
        .bind(content.as_bytes())
        .bind(content_sha256.as_str())
        .bind(valid_from)
        .bind(valid_from + 1)
        .execute(&mut *seed)
        .await
        .expect("independent historical source");
        sqlx::query(
            "INSERT INTO memory_revisions (
                memory_id, revision, owner_agent_id, scope_kind,
                workspace_sha256, content, content_sha256, verification,
                lifecycle, tombstone_reason, valid_from_unix_seconds,
                valid_to_unix_seconds, supersedes_revision,
                recorded_at_unix_seconds
             ) VALUES (?, ?, ?, 'agent_private', NULL, ?, ?, 'verified',
                       'active', NULL, ?, NULL, ?, ?)",
        )
        .bind(&legacy_id)
        .bind(revision)
        .bind(owner.as_str())
        .bind(content)
        .bind(content_sha256.as_str())
        .bind(valid_from)
        .bind(supersedes)
        .bind(valid_from + 1)
        .execute(&mut *seed)
        .await
        .expect("contiguous immutable historical memory revision");
        sqlx::query(
            "INSERT INTO memory_citations (
                memory_id, memory_revision, ordinal, source_id, source_revision
             ) VALUES (?, ?, 0, ?, 1)",
        )
        .bind(&legacy_id)
        .bind(revision)
        .bind(source_id.as_str())
        .execute(&mut *seed)
        .await
        .expect("exact historical source citation");
        sqlx::query("INSERT INTO memory_fts (memory_id, revision, content) VALUES (?, ?, ?)")
            .bind(&legacy_id)
            .bind(revision)
            .bind(content)
            .execute(&mut *seed)
            .await
            .expect("FTS preserves every immutable historical revision");
        citations.push(SourceRevisionId::new(source_id));
    }
    sqlx::query("INSERT INTO memory_heads (memory_id, revision) VALUES (?, 2)")
        .bind(&legacy_id)
        .execute(&mut *seed)
        .await
        .expect("latest historical head");
    seed.commit().await.expect("complete fixture commit");
    pool.close().await;
    drop(pool);

    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("valid historical owner migrates through the current lineage");
    let memory_id = StableMemoryId::parse(&legacy_id).expect("public legacy parser");
    assert_eq!(memory_id.as_str(), legacy_id);
    let access = CognitiveAccess::agent_private(owner);
    let expected_head = MemoryRevisionRecord {
        id: MemoryRevisionId {
            memory_id: memory_id.clone(),
            revision: 2,
        },
        scope: CognitiveScope::AgentPrivate,
        content: "Legacy cobalt observation.".to_string(),
        content_sha256: Sha256Digest::for_bytes(b"Legacy cobalt observation."),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 200,
        valid_to_unix_seconds: None,
        supersedes_revision: Some(1),
        citations: vec![citations[1].clone()],
    };
    assert_eq!(
        store
            .latest_memory(&access, &memory_id)
            .await
            .expect("public latest memory"),
        expected_head
    );
    let query = RetrievalRequest::new("cobalt", /*now_unix_seconds*/ 500);
    let initial = store
        .retrieve_memory_candidates(&access, &query)
        .await
        .expect("actual ranked retrieval parses the migrated legacy ID");
    let candidate = initial
        .candidates
        .iter()
        .find(|candidate| candidate.memory.id.memory_id == memory_id)
        .expect("legacy memory was retrieved");
    assert_eq!(candidate.memory, expected_head);
    assert!(candidate.channels.contains(&RetrievalChannel::MemoryFts));
    let historical_match = store
        .retrieve_memory_candidates(
            &access,
            &RetrievalRequest::new("amber", /*now_unix_seconds*/ 500),
        )
        .await
        .expect("historical FTS rows are filtered through the current head");
    assert!(historical_match.candidates.iter().all(|candidate| {
        candidate.memory.id.revision == 2
            && !candidate.channels.contains(&RetrievalChannel::MemoryFts)
    }));

    let content = "Legacy cobalt corrected evidence.";
    let mut correction_source = source(CognitiveScope::AgentPrivate, "legacy-correction", content);
    correction_source.observed_at_unix_seconds = 300;
    let corrected = store
        .correct_with_kg(
            &access,
            &memory_id,
            /*expected_revision*/ 2,
            &correction_source,
            &MemoryRevisionDraft {
                scope: CognitiveScope::AgentPrivate,
                content: content.to_string(),
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 300,
                valid_to_unix_seconds: None,
                citations: Vec::new(),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("public correction preserves the legacy identity and binds a real source");
    let expected_source = SourceRevisionId::new(SourceEventId::for_event(
        access.agent_id(),
        &CognitiveScope::AgentPrivate,
        LedgerSourceKind::ExplicitMemoryDirective,
        "legacy-correction",
    ));
    let expected_corrected = MemoryRevisionRecord {
        id: MemoryRevisionId {
            memory_id: memory_id.clone(),
            revision: 3,
        },
        content: content.to_string(),
        content_sha256: Sha256Digest::for_bytes(content.as_bytes()),
        valid_from_unix_seconds: 300,
        supersedes_revision: Some(2),
        citations: vec![expected_source.clone()],
        ..expected_head
    };
    assert_eq!(corrected.memory, expected_corrected);
    assert_eq!(corrected.source, expected_source);
    let fresh_content = "Fresh current identity.";
    let created = store
        .remember_with_kg(
            &access,
            &source(CognitiveScope::AgentPrivate, "fresh-v2", fresh_content),
            &MemoryDraft {
                stable_key: "fresh-v2".to_string(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: fresh_content.to_string(),
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
        .expect("new public writes still create v2 identities");
    assert!(
        created
            .memory
            .id
            .memory_id
            .as_str()
            .starts_with("memory:v2:")
    );
    let explanation = store
        .explain_memory_head(&access, &memory_id)
        .await
        .expect("real correction citation");
    assert_eq!(explanation.memory, corrected.memory);
    assert_eq!(explanation.citations.len(), 1);
    assert_eq!(explanation.citations[0].id, corrected.source);
    assert_eq!(explanation.citations[0].content, correction_source.content);
    let before_reopen = store
        .retrieve_memory_candidates(&access, &query)
        .await
        .expect("corrected ranked retrieval");
    let candidate = before_reopen
        .candidates
        .iter()
        .find(|candidate| candidate.memory.id.memory_id == memory_id)
        .expect("corrected legacy retrieval");
    assert_eq!(candidate.memory, corrected.memory);
    assert!(candidate.channels.contains(&RetrievalChannel::MemoryFts));
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("corrected legacy owner reopens");
    assert_eq!(
        reopened
            .latest_memory(&access, &memory_id)
            .await
            .expect("reopened memory"),
        corrected.memory
    );
    assert_eq!(
        reopened
            .explain_memory_head(&access, &memory_id)
            .await
            .expect("reopened complete citation"),
        explanation
    );
    assert_eq!(
        reopened
            .retrieve_memory_candidates(&access, &query)
            .await
            .expect("reopened ranked retrieval"),
        before_reopen
    );
    reopened.pool.close().await;
}

#[test]
fn legacy_memory_acceptance_retains_exact_prefix_and_lowercase_digest_bounds() {
    for prefix in ["memory:v1:", "memory:v2:"] {
        for digest in [
            String::new(),
            "ab".to_string(),
            "a".repeat(63),
            "a".repeat(65),
            "A".repeat(64),
            "g".repeat(64),
        ] {
            assert!(StableMemoryId::parse(format!("{prefix}{digest}")).is_err());
        }
    }
    for prefix in [
        "memory:v0:",
        "memory:v3:",
        "source:v1:",
        "memory:v1",
        "memory:v2::",
    ] {
        assert!(StableMemoryId::parse(format!("{prefix}{}", "a".repeat(64))).is_err());
    }
}

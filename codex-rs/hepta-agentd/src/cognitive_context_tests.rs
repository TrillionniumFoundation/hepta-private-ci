use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::StableId;

use super::PagedRetrievalOwnerCutV1;
use super::now_seconds;
use super::read;
use super::revalidate;

#[path = "cognitive_context_budget_tests.rs"]
mod budget;

#[test]
fn encoded_read_budget_unavailability_is_local_not_store_failure() {
    let error = super::map_read_ids_error(
        codex_hepta_cognitive_read::ReadIdsError::EncodedResultTooLarge {
            actual: 9,
            maximum: 8,
        },
    );
    assert!(matches!(
        error,
        super::CognitiveContextError::ReadUnavailable(_)
    ));
}
#[path = "cognitive_context_hnmf_tests.rs"]
mod hnmf;

#[tokio::test]
async fn context_reads_real_owner_content_and_removes_committed_tombstones() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let fleet = std::fs::canonicalize(&fleet).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "context-test".to_string(),
                content: b"verified lemon orchard".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "orchard".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "verified lemon orchard".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation.clone()],
                },
            },
        )
        .await
        .unwrap();
    let context = read(&store, &owner, 1, "lemon", 4, None).await.unwrap();
    assert_eq!(context.items.len(), 1);
    assert!(context.plan.as_ref().unwrap().read_allowed);
    assert_eq!(context.items[0].memory_id, memory.id.memory_id.as_str());
    assert_eq!(context.items[0].content, "verified lemon orchard");
    let current = revalidate(
        &store,
        &owner,
        crate::cognitive_context::CognitiveContextRevalidationInput {
            snapshot_digest: &context.snapshot_digest,
            read_digest: &context.read_digest,
            omitted_records: context.omitted_records,
            items: &context.items,
            plan: context.plan.as_ref(),
        },
        None,
    )
    .await
    .unwrap();
    assert_eq!(current.snapshot_digest, context.snapshot_digest);
    assert_eq!(current.read_digest, context.read_digest);
    assert_eq!(
        usize::from(current.verified_item_count),
        context.items.len()
    );
    let mut tampered_plan = context.plan.clone().unwrap();
    tampered_plan.evaluated_context_digest = "22".repeat(32);
    assert!(
        revalidate(
            &store,
            &owner,
            crate::cognitive_context::CognitiveContextRevalidationInput {
                snapshot_digest: &context.snapshot_digest,
                read_digest: &context.read_digest,
                omitted_records: context.omitted_records,
                items: &context.items,
                plan: Some(&tampered_plan),
            },
            None,
        )
        .await
        .is_err(),
        "a substituted ordered-context digest must fail final-use validation"
    );
    assert!(
        revalidate(
            &store,
            &owner,
            crate::cognitive_context::CognitiveContextRevalidationInput {
                snapshot_digest: &context.snapshot_digest,
                read_digest: &"11".repeat(32),
                omitted_records: context.omitted_records,
                items: &context.items,
                plan: context.plan.as_ref(),
            },
            None,
        )
        .await
        .is_err(),
        "a forged read receipt must fail final-use validation"
    );
    store
        .forget_memory(
            &access,
            &memory.id.memory_id,
            1,
            &ForgetMemoryDraft {
                scope,
                reason: "withdrawn".to_string(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    assert!(
        revalidate(
            &store,
            &owner,
            crate::cognitive_context::CognitiveContextRevalidationInput {
                snapshot_digest: &context.snapshot_digest,
                read_digest: &context.read_digest,
                omitted_records: context.omitted_records,
                items: &context.items,
                plan: context.plan.as_ref(),
            },
            None,
        )
        .await
        .is_err(),
        "a committed tombstone must invalidate the historical read receipt"
    );
    let withdrawn = read(&store, &owner, 1, "lemon", 4, None).await.unwrap();
    assert!(withdrawn.items.is_empty());
    assert!(!withdrawn.plan.as_ref().unwrap().read_allowed);
    assert_ne!(withdrawn.snapshot_digest, context.snapshot_digest);
    let other = AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap();
    assert!(read(&store, &other, 1, "lemon", 4, None).await.is_err());
}

#[tokio::test]
async fn final_use_binds_complete_owner_cut_not_only_selected_memory_bytes() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let fleet = std::fs::canonicalize(&fleet).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000121").unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "cut-binding-memory-source".to_string(),
                content: b"verified owner cut binding marker".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "cut-binding-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "verified owner cut binding marker".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .unwrap();

    let context = read(&store, &owner, 1, "binding marker", 4, None)
        .await
        .unwrap();
    assert_eq!(context.items.len(), 1);
    let selected_ids = context
        .items
        .iter()
        .map(|item| StableId::new(item.memory_id.as_str()).unwrap())
        .collect::<Vec<_>>();
    let before =
        PagedRetrievalOwnerCutV1::acquire(&store, &access, &scope, 200, selected_ids.clone())
            .await
            .unwrap();
    assert_eq!(
        before.snapshot().snapshot_digest.to_string(),
        context.snapshot_digest
    );

    // Advance an owner frontier without changing any selected memory head. A
    // final-use binding that only compared selected snapshot bytes would miss
    // this drift even though the declared coherent owner cut changed.
    store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "cut-binding-unrelated-source".to_string(),
                content: b"unrelated source frontier advance".to_vec(),
                observed_at_unix_seconds: 150,
            },
        )
        .await
        .unwrap();
    let after = PagedRetrievalOwnerCutV1::acquire(&store, &access, &scope, 200, selected_ids)
        .await
        .unwrap();
    assert_eq!(
        after.snapshot().snapshot_digest,
        before.snapshot().snapshot_digest,
        "selected memory snapshot must remain identical so the regression isolates owner-cut drift"
    );
    assert_ne!(after.cut_digest(), before.cut_digest());

    assert!(
        revalidate(
            &store,
            &owner,
            crate::cognitive_context::CognitiveContextRevalidationInput {
                snapshot_digest: &context.snapshot_digest,
                read_digest: &context.read_digest,
                omitted_records: context.omitted_records,
                items: &context.items,
                plan: context.plan.as_ref(),
            },
            None,
        )
        .await
        .is_err(),
        "source/KG/tombstone frontier drift must stale the final-use packet even when selected heads are unchanged"
    );
}

#[tokio::test]
async fn context_reads_a_candidate_beyond_the_first_owner_page() {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let fleet = std::fs::canonicalize(&fleet).unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000122").unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let mut seeded = Vec::new();

    for index in 0..96_u32 {
        let token = format!("retrievalpagetoken{index:03}");
        let citation = store
            .append_source(
                &access,
                &SourceDraft {
                    scope: scope.clone(),
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: format!("paged-source-{index:03}"),
                    content: token.as_bytes().to_vec(),
                    observed_at_unix_seconds: 100,
                },
            )
            .await
            .unwrap();
        let receipt = store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: format!("paged-memory-{index:03}"),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content: token.clone(),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 100,
                        valid_to_unix_seconds: None,
                        citations: vec![citation],
                    },
                },
            )
            .await
            .unwrap();
        seeded.push((receipt.id.memory_id.as_str().to_string(), token));
    }

    seeded.sort_by(|left, right| left.0.cmp(&right.0));
    let (target_id, target_token) = seeded.last().unwrap();
    let context = read(&store, &owner, 1, target_token, 4, None)
        .await
        .unwrap();
    // Retrieval also has a Recency channel: an exact lexical match does not
    // imply that the other three requested slots are empty. Compare the full
    // bounded projection with the declared RRF ordering over owner facts, then require
    // the beyond-first-page target to survive that projection exactly once.
    let observation = store
        .observe_memory_retrieval(
            &access,
            &RetrievalRequest::new(target_token, now_seconds().unwrap()),
        )
        .await
        .unwrap();
    let mut ranked = observation.candidates().iter().collect::<Vec<_>>();
    // Owner observations are identity ordered, not the public context ranking.
    // Independently apply the baseline RRF score and stable identity tie-breaks.
    ranked.sort_by_key(|candidate| {
        (
            std::cmp::Reverse(candidate.reciprocal_rank_score),
            candidate.revalidation.memory.memory_id.as_str(),
            candidate.revalidation.memory.revision,
        )
    });
    let expected = ranked
        .into_iter()
        .take(4)
        .map(|candidate| {
            let id = candidate.revalidation.memory.memory_id.as_str();
            seeded
                .iter()
                .find(|(memory_id, _)| memory_id == id)
                .unwrap()
                .clone()
        })
        .collect::<Vec<_>>();
    let actual = context
        .items
        .iter()
        .map(|item| (item.memory_id.clone(), item.content.clone()))
        .collect::<Vec<_>>();
    assert_eq!(actual, expected);
    assert_eq!(
        actual
            .iter()
            .filter(|(id, text)| id == target_id && text == target_token)
            .count(),
        1
    );
    assert_eq!(context.items.len(), 4);
    // Lexical and Recency channels are combined by RRF. The first item must
    // match the independent complete ranking, not an assumed lexical winner.
    assert_eq!(context.items[0].memory_id, expected[0].0);
    assert_eq!(context.items[0].content, expected[0].1);
    let single = read(&store, &owner, 1, target_token, 1, None)
        .await
        .unwrap();
    assert_eq!(single.items, vec![context.items[0].clone()]);
    revalidate(
        &store,
        &owner,
        crate::cognitive_context::CognitiveContextRevalidationInput {
            snapshot_digest: &context.snapshot_digest,
            read_digest: &context.read_digest,
            omitted_records: context.omitted_records,
            items: &context.items,
            plan: context.plan.as_ref(),
        },
        None,
    )
    .await
    .unwrap();
}

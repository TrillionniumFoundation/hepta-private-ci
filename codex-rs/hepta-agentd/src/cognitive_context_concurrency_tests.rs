use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::StableMemoryId;
use codex_hepta_types::ProbabilityQ32;
use tokio::sync::Notify;

use crate::CurrentMemoryRetrievalContext;
use crate::cognitive_context::CognitiveContextError;
use crate::cognitive_context::read_with_retrieval_context;
use crate::cognitive_context::read_with_retrieval_context_and_learning;
use crate::cognitive_context::revalidate_with_retrieval_context;

struct GatedContext {
    owner: AgentId,
    context: RetrievalExecutionContextV1,
    gate_call: usize,
    calls: AtomicUsize,
    entered: Arc<Notify>,
    release: Arc<Notify>,
}

impl CurrentMemoryRetrievalContext for GatedContext {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        if owner != &self.owner || body_generation != 1 {
            return Err("wrong retrieval host identity".to_string());
        }
        if self.calls.fetch_add(1, Ordering::SeqCst) == self.gate_call {
            self.entered.notify_one();
            // The provider is called on spawn_blocking, so the async test can
            // commit a real owner mutation while this exact binding is held.
            tokio::runtime::Handle::current()
                .block_on(tokio::time::timeout(
                    Duration::from_secs(20),
                    self.release.notified(),
                ))
                .map_err(|_| "controlled retrieval provider was not released".to_string())?;
        }
        Ok(self.context.clone())
    }
}

fn provider(
    owner: &AgentId,
    context: &RetrievalExecutionContextV1,
    gate_call: usize,
) -> (
    Arc<dyn CurrentMemoryRetrievalContext>,
    Arc<Notify>,
    Arc<Notify>,
) {
    let entered = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    (
        Arc::new(GatedContext {
            owner: owner.clone(),
            context: context.clone(),
            gate_call,
            calls: AtomicUsize::new(0),
            entered: Arc::clone(&entered),
            release: Arc::clone(&release),
        }),
        entered,
        release,
    )
}

async fn wait_for_gate(entered: &Notify) {
    tokio::time::timeout(Duration::from_secs(10), entered.notified())
        .await
        .expect("the pending owner read must reach its controlled await");
}

#[derive(Clone, Copy)]
enum OwnerChange {
    Correction,
    Tombstone,
}

async fn commit_selected_change(
    store: &CognitiveStore,
    owner: &AgentId,
    context: &RetrievalExecutionContextV1,
    change: OwnerChange,
) {
    let access = CognitiveAccess::agent_private(owner.clone());
    let selected_id = StableMemoryId::parse(
        context.engram_snapshot.nodes[0].support[0]
            .record_id
            .as_str(),
    )
    .unwrap();
    let current = store.read_memory_head(&access, &selected_id).await.unwrap();
    let changed = match change {
        OwnerChange::Correction => store
            .correct_memory(
                &access,
                &selected_id,
                current.id.revision,
                &MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "corrected lemon second".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: current.citations,
                },
            )
            .await
            .unwrap(),
        OwnerChange::Tombstone => store
            .forget_memory(
                &access,
                &selected_id,
                current.id.revision,
                &ForgetMemoryDraft {
                    scope: CognitiveScope::AgentPrivate,
                    reason: "withdrawn during the pending context read".to_string(),
                    valid_from_unix_seconds: 100,
                    citations: current.citations,
                },
            )
            .await
            .unwrap(),
    };
    assert_eq!(changed.id.revision, current.id.revision + 1);
}

#[tokio::test]
async fn final_use_rejects_owner_commit_during_unchanged_retrieval_binding_await() {
    for (suffix, change) in [
        (135, OwnerChange::Correction),
        (136, OwnerChange::Tombstone),
    ] {
        let (_temp, store, owner, context, _) = super::hnmf::fixture(suffix).await;
        let (stable, _, _) = provider(&owner, &context, usize::MAX);
        let snapshot =
            read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&stable))
                .await
                .unwrap();
        assert_eq!(snapshot.items.len(), 1);
        let (current, entered, release) = provider(&owner, &context, 0);
        let pending_store = store.clone();
        let pending_owner = owner.clone();
        let pending = tokio::spawn(async move {
            revalidate_with_retrieval_context(
                &pending_store,
                &pending_owner,
                &snapshot.snapshot_digest,
                &snapshot.read_digest,
                snapshot.omitted_records,
                &snapshot.items,
                snapshot.plan.as_ref(),
                None,
                1,
                Some(&current),
            )
            .await
        });
        wait_for_gate(&entered).await;
        commit_selected_change(&store, &owner, &context, change).await;
        release.notify_one();
        assert!(matches!(
            pending.await.unwrap(),
            Err(CognitiveContextError::Store(CognitiveStoreError::Conflict(
                _
            )))
        ));
    }
}

#[tokio::test]
async fn publication_rejects_owner_commit_during_unchanged_retrieval_binding_await() {
    for (suffix, change) in [
        (137, OwnerChange::Correction),
        (138, OwnerChange::Tombstone),
    ] {
        let (_temp, store, owner, context, _) = super::hnmf::fixture(suffix).await;
        // Gate only the final currentness check, after the earlier owner check.
        let (current, entered, release) = provider(&owner, &context, 1);
        let pending_store = store.clone();
        let pending_owner = owner.clone();
        let pending = tokio::spawn(async move {
            read_with_retrieval_context(
                &pending_store,
                &pending_owner,
                1,
                "lemon",
                4,
                None,
                Some(&current),
            )
            .await
        });
        wait_for_gate(&entered).await;
        commit_selected_change(&store, &owner, &context, change).await;
        release.notify_one();
        assert!(matches!(
            pending.await.unwrap(),
            Err(CognitiveContextError::Store(CognitiveStoreError::Conflict(
                _
            )))
        ));
    }
}

#[tokio::test]
async fn publication_rejects_tombstone_committed_during_learning_sink_await() {
    let (_temp, store, owner, context, _) = super::hnmf::fixture(139).await;
    let (_learning_temp, gate) =
        crate::cognitive_retrieval_learning::test_support::gated_sink().await;
    let (current, _, _) = provider(&owner, &context, usize::MAX);
    let pending_store = store.clone();
    let pending_owner = owner.clone();
    let sink = Arc::clone(&gate.sink);
    let recorded_sink = Arc::clone(&sink);
    let pending = tokio::spawn(async move {
        read_with_retrieval_context_and_learning(
            &pending_store,
            &pending_owner,
            1,
            "lemon",
            4,
            None,
            Some(&current),
            Some(&sink),
            Some(139),
        )
        .await
    });
    // The actual append has reached the real writer mutex, after the provider
    // and ranker checks. Keep it pending until the normal owner commit finishes.
    wait_for_gate(&gate.append_entered).await;
    commit_selected_change(&store, &owner, &context, OwnerChange::Tombstone).await;
    gate.release().await;
    assert!(matches!(
        pending.await.unwrap(),
        Err(CognitiveContextError::Store(CognitiveStoreError::Conflict(
            _
        )))
    ));
    assert_prepublication_assignment(&recorded_sink);
}

fn assert_prepublication_assignment(sink: &crate::CognitiveRetrievalLearningSink) {
    let assignments = crate::cognitive_retrieval_learning::test_support::assignments(sink);
    assert_eq!(assignments.len(), 1);
    let assignment = &assignments[0];
    assert_eq!(assignment.selected_candidate_indices.len(), 1);
    assert_eq!(
        (
            assignment.delivered_candidate_indices.as_slice(),
            assignment.context_exposed,
            assignment.published_context_digest,
            assignment.downstream_policy_digest,
            assignment.delivery_propensity,
        ),
        (&[][..], false, None, None, ProbabilityQ32::ONE),
    );
}

#[tokio::test]
async fn successful_context_records_assignment_without_claiming_consumer_exposure() {
    let (_temp, store, owner, context, _) = super::hnmf::fixture(140).await;
    let (_learning_temp, sink) = crate::cognitive_retrieval_learning::test_support::sink();
    let sink = Arc::new(sink);
    let (current, _, _) = provider(&owner, &context, usize::MAX);
    let snapshot = read_with_retrieval_context_and_learning(
        &store,
        &owner,
        1,
        "lemon",
        4,
        None,
        Some(&current),
        Some(&sink),
        Some(140),
    )
    .await
    .unwrap();
    assert_eq!(snapshot.items.len(), 1);
    assert_prepublication_assignment(&sink);
}

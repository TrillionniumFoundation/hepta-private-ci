//! TaskFlow state restrictions and cancellation retain the original SQLite fixtures.

use super::fixture::*;
use codex_hepta_agent_loop::*;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio_util::sync::CancellationToken;

#[tokio::test]
async fn cancellation_intent_and_acknowledgement_survive_separate_reopens() {
    let fixture = Fixture::new();
    let (store, fence, binding) = fixture.store().await;
    let calls = Arc::new(AtomicUsize::new(0));
    let mut owner = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        binding.clone(),
        request(0),
        Limits::default(),
        Compiler::new(&calls),
    )
    .await
    .expect("owner");
    let frame = owner.load(&binding).await.expect("initial");
    let pending = owner
        .commit(&frame, Transition::CancelRequested)
        .await
        .expect("intent only");
    assert_eq!(pending.phase, Phase::CancelRequested);
    drop(owner);
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen intent");
    let mut owner = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        binding.clone(),
        request(0),
        Limits::default(),
        Compiler::new(&calls),
    )
    .await
    .expect("reattach");
    assert_eq!(owner.load(&binding).await.expect("pending"), pending);
    let stopped = owner
        .commit(&pending, Transition::Cancelled)
        .await
        .expect("separate owner acknowledgement");
    assert_eq!(stopped.phase, Phase::Cancelled);
    transition(
        &store,
        &fence,
        TaskFlowTransition::Cancel {
            reason: "acknowledged".into(),
        },
    )
    .await;
    drop(owner);
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen terminal");
    let mut owner = TaskFlowTurnOwner::open(
        &store,
        fence,
        binding.clone(),
        request(0),
        Limits::default(),
        Compiler::new(&calls),
    )
    .await
    .expect("terminal observer");
    assert_eq!(
        owner.load(&binding).await.expect("retained cancellation"),
        stopped
    );
    assert_eq!(owner.observe().await.expect("history").history.len(), 2);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn terminal_taskflow_with_active_native_frame_cannot_dispatch() {
    let fixture = Fixture::new();
    let (store, fence, binding) = fixture.store().await;
    let calls = Arc::new(AtomicUsize::new(0));
    let mut owner = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        binding.clone(),
        request(0),
        Limits::default(),
        Compiler::new(&calls),
    )
    .await
    .expect("owner");
    transition(
        &store,
        &fence,
        TaskFlowTransition::Succeed {
            output_digest: Sha256Digest::for_bytes(b"other workflow result"),
        },
    )
    .await;
    assert!(matches!(
        owner
            .observe()
            .await
            .expect("read-only historical frame")
            .frame
            .phase,
        Phase::Model(_)
    ));
    let mut inference = Inference::default();
    let mut effects = Effects::default();
    assert!(
        run(
            &mut owner,
            &mut inference,
            &mut effects,
            &binding,
            &Limits::default(),
            &CancellationToken::new()
        )
        .await
        .is_err()
    );
    assert_eq!(inference.opens, 0);
    assert!(effects.keys.is_empty());
    let stop = CancellationToken::new();
    stop.cancel();
    assert!(
        run(
            &mut owner,
            &mut inference,
            &mut effects,
            &binding,
            &Limits::default(),
            &stop
        )
        .await
        .is_err()
    );
    assert_eq!(inference.cancels, 0);
    assert_eq!(effects.cancels, 0);
    assert!(
        owner
            .observe()
            .await
            .expect("terminal cursor unchanged")
            .history
            .is_empty()
    );
}

#[tokio::test]
async fn waiting_retry_and_indeterminate_taskflow_states_cannot_dispatch() {
    for state in [
        TaskFlowTransition::Wait {
            token: "owned-wait".into(),
            resume_node: None,
        },
        TaskFlowTransition::Retry {
            retry_at_ms: clock() + 60_000,
        },
        TaskFlowTransition::Indeterminate {
            reason: "ambiguous original activity".into(),
        },
    ] {
        let fixture = Fixture::new();
        let (store, fence, binding) = fixture.store().await;
        let calls = Arc::new(AtomicUsize::new(0));
        let mut owner = TaskFlowTurnOwner::open(
            &store,
            fence.clone(),
            binding.clone(),
            request(0),
            Limits::default(),
            Compiler::new(&calls),
        )
        .await
        .expect("owner");
        transition(&store, &fence, state).await;
        assert!(matches!(
            owner
                .observe()
                .await
                .expect("retained observation")
                .frame
                .phase,
            Phase::Model(_)
        ));
        let mut inference = Inference::default();
        let mut effects = Effects::default();
        assert!(
            run(
                &mut owner,
                &mut inference,
                &mut effects,
                &binding,
                &Limits::default(),
                &CancellationToken::new()
            )
            .await
            .is_err()
        );
        assert_eq!(inference.opens, 0);
        assert!(effects.keys.is_empty());
    }
}

#[tokio::test]
async fn cancellation_stops_original_owners_from_wait_retry_and_indeterminate() {
    for state in [
        TaskFlowTransition::Wait {
            token: "cancel-wait".into(),
            resume_node: None,
        },
        TaskFlowTransition::Retry {
            retry_at_ms: clock() + 60_000,
        },
        TaskFlowTransition::Indeterminate {
            reason: "cancel original unresolved activity".into(),
        },
    ] {
        let fixture = Fixture::new();
        let (store, fence, binding) = fixture.store().await;
        let calls = Arc::new(AtomicUsize::new(0));
        let mut owner = TaskFlowTurnOwner::open(
            &store,
            fence.clone(),
            binding.clone(),
            request(0),
            Limits::default(),
            Compiler::new(&calls),
        )
        .await
        .expect("owner");
        transition(&store, &fence, state).await;
        let stop = CancellationToken::new();
        stop.cancel();
        let mut inference = Inference::default();
        let mut effects = Effects::default();
        assert_eq!(
            run(
                &mut owner,
                &mut inference,
                &mut effects,
                &binding,
                &Limits::default(),
                &stop
            )
            .await
            .expect("stop original owners under exact live fence"),
            Outcome::Cancelled
        );
        assert_eq!(inference.opens, 0);
        assert!(effects.keys.is_empty());
        assert_eq!(inference.cancels, 1);
        assert_eq!(effects.cancels, 1);
        let saved = owner
            .observe()
            .await
            .expect("two retained cancellation observations");
        assert_eq!(
            saved
                .history
                .iter()
                .map(|row| &row.transition)
                .collect::<Vec<_>>(),
            vec![&Transition::CancelRequested, &Transition::Cancelled]
        );
        assert_eq!(saved.frame.phase, Phase::Cancelled);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

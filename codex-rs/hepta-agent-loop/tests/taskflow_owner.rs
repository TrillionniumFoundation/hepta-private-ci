#![cfg(feature = "taskflow-owner")]
#![allow(
    clippy::expect_used,
    reason = "isolated qualification fixtures fail loudly"
)]

use codex_hepta_agent_loop::*;
use codex_hepta_automation::AutomationStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[path = "support/taskflow_fixture.rs"]
mod fixture;
#[path = "support/taskflow_state_tests.rs"]
mod state_tests;
#[cfg(feature = "context-v2")]
#[path = "support/taskflow_v2_fixture.rs"]
mod v2_fixture;
use fixture::*;

#[tokio::test]
async fn actual_taskflow_reopen_preserves_observations_usage_and_frozen_context() {
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
    .expect("attach original turn");
    let (previous, key) = pending_tool(&mut owner, &binding).await;
    assert!(
        owner
            .commit(
                &previous,
                Transition::ToolCompleted {
                    operation_key: Digest32::of_bytes(b"wrong key"),
                    output: "result".into()
                }
            )
            .await
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let transition = Transition::ToolCompleted {
        operation_key: key,
        output: "result".into(),
    };
    let next = owner
        .commit(&previous, transition.clone())
        .await
        .expect("atomic observed successor");
    assert_eq!(next.consumed_tokens, 12);
    assert_eq!(next.round, 1);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        owner
            .commit(&previous, transition.clone())
            .await
            .expect("lost acknowledgement replay"),
        next
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    drop(owner);
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("same database reopened");
    let mut owner = TaskFlowTurnOwner::open(
        &reopened,
        fence,
        binding.clone(),
        request(0),
        Limits::default(),
        Compiler::new(&calls),
    )
    .await
    .expect("same original request");
    assert_eq!(owner.load(&binding).await.expect("frozen successor"), next);
    let observed = owner.observe().await.expect("observed history");
    assert_eq!(observed.history.len(), 2);
    assert_eq!(observed.history[1].transition, transition);
    assert!(observed.history[1].prepared_next.is_some());
    assert_eq!(observed.cursor.revision, 3);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    #[cfg(feature = "context-v2")]
    if let Phase::Model(request) = next.phase {
        assert_eq!(request.payload.as_ref(), "systemresult");
    }
}

#[tokio::test]
async fn initial_binding_deadline_request_generation_and_limits_cannot_be_rewritten() {
    let fixture = Fixture::new();
    let (store, fence, binding) = fixture.store().await;
    let calls = Arc::new(AtomicUsize::new(0));
    TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        binding.clone(),
        request(0),
        Limits::default(),
        Compiler::new(&calls),
    )
    .await
    .expect("original");
    let mut changed = binding.clone();
    changed.deadline_unix_ms += 1;
    assert!(
        TaskFlowTurnOwner::open(
            &store,
            fence.clone(),
            changed,
            request(0),
            Limits::default(),
            Compiler::new(&calls)
        )
        .await
        .is_err()
    );
    let mut changed = binding.clone();
    changed.generation = Generation::new(2).expect("generation");
    assert!(
        TaskFlowTurnOwner::open(
            &store,
            fence.clone(),
            changed,
            request(0),
            Limits::default(),
            Compiler::new(&calls)
        )
        .await
        .is_err()
    );
    assert!(
        TaskFlowTurnOwner::open(
            &store,
            fence.clone(),
            binding.clone(),
            request(1),
            Limits::default(),
            Compiler::new(&calls)
        )
        .await
        .is_err()
    );
    let mut limits = Limits::default();
    limits.maximum_total_tokens += 1;
    assert!(
        TaskFlowTurnOwner::open(
            &store,
            fence,
            binding,
            request(0),
            limits,
            Compiler::new(&calls)
        )
        .await
        .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn competing_successors_have_one_durable_winner_and_replay_does_not_advance() {
    let fixture = Fixture::new();
    let (store, fence, binding) = fixture.store().await;
    let calls = Arc::new(AtomicUsize::new(0));
    let mut left = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        binding.clone(),
        request(0),
        Limits::default(),
        Compiler::new(&calls),
    )
    .await
    .expect("left");
    let mut right = TaskFlowTurnOwner::open(
        &store,
        fence,
        binding.clone(),
        request(0),
        Limits::default(),
        Compiler::new(&calls),
    )
    .await
    .expect("right");
    let initial = left.load(&binding).await.expect("initial");
    let a = Transition::ModelCompleted(output("left", Vec::new()));
    let b = Transition::ModelCompleted(output("right", Vec::new()));
    let (one, two) = tokio::join!(
        left.commit(&initial, a.clone()),
        right.commit(&initial, b.clone())
    );
    assert_eq!(usize::from(one.is_ok()) + usize::from(two.is_ok()), 1);
    let (winner, transition) = match (one, two) {
        (Ok(frame), Err(_)) => (frame, a),
        (Err(_), Ok(frame)) => (frame, b),
        _ => unreachable!("one winner"),
    };
    assert_eq!(
        left.commit(&initial, transition)
            .await
            .expect("exact replay"),
        winner
    );
    let observed = left.observe().await.expect("one committed successor");
    assert_eq!(observed.history.len(), 1);
    assert_eq!(observed.cursor.revision, 2);
}

#[tokio::test]
async fn invalid_compiler_request_is_rejected_before_corrupting_the_owned_cursor() {
    let fixture = Fixture::new();
    let (store, fence, binding) = fixture.store().await;
    let calls = Arc::new(AtomicUsize::new(0));
    let mut compiler = Compiler::new(&calls);
    compiler.repeat_initial = true;
    let mut owner = TaskFlowTurnOwner::open(
        &store,
        fence,
        binding.clone(),
        request(0),
        Limits::default(),
        compiler,
    )
    .await
    .expect("owner");
    let (previous, key) = pending_tool(&mut owner, &binding).await;
    assert!(
        owner
            .commit(
                &previous,
                Transition::ToolCompleted {
                    operation_key: key,
                    output: "result".into()
                }
            )
            .await
            .is_err()
    );
    assert_eq!(
        owner.load(&binding).await.expect("original remains valid"),
        previous
    );
    assert_eq!(
        owner
            .observe()
            .await
            .expect("retained original")
            .history
            .len(),
        1
    );
}

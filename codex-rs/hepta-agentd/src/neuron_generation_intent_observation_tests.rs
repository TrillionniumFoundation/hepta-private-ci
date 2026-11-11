use std::fs;
use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::neuron_generation_channel_v2;
use super::spawn_neuron_generation_service;
use super::support::*;

fn retained(fixture: &Fixture) -> (Vec<u8>, Vec<u8>, usize, usize, usize, u64) {
    let signals = &fixture.control.signals;
    (
        checked(fs::read(
            fixture.directory.path().join("generation-journal"),
        )),
        checked(fs::read(
            fixture.directory.path().join("generation-witness"),
        )),
        signals.calls.load(Ordering::SeqCst),
        signals.reads.load(Ordering::SeqCst),
        signals.cancellations.load(Ordering::SeqCst),
        fixture.ticks.load(Ordering::SeqCst),
    )
}

#[tokio::test]
async fn bounded_owner_observes_original_receipt_cost_and_rejects_fenced_reads() {
    let mut fixture = Fixture::new().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let original = request("exact-owner-receipt", fixture.config.initial.clone());
    let intent = checked(original.intent());
    let before = retained(&fixture);
    let missing = checked(handle.observe_intent(intent.clone()).await);
    assert!(missing.is_missing());
    assert_eq!(retained(&fixture), before);
    fixture
        .control
        .signals
        .lose_response
        .store(/*val*/ true, Ordering::SeqCst);
    assert_eq!(
        handle.step(original.clone()).await,
        Err(CellGenerationErrorV2::Unavailable)
    );
    let before = retained(&fixture);
    let pending = checked(handle.observe_intent(intent.clone()).await);
    assert_eq!(pending.pending_request(), Some(&original));
    assert_eq!(pending.receipt(), None);
    assert_eq!(pending.pending_output(), None);
    assert_eq!(retained(&fixture), before);
    fixture
        .control
        .signals
        .readable
        .store(/*val*/ true, Ordering::SeqCst);
    let receipt = checked(handle.reconcile(checked(original.digest())).await);
    checked(
        handle
            .record_cost(CellCostEntryV2 {
                event_id: Digest32::of_bytes(b"later-migration").into_array(),
                identity: cost().identity(),
                stage: CellCostStageV2::Migration,
                outcome: CellCostOutcomeV2::Failed,
                accounting: CellCostAccountingV2::Exclusive,
                metrics: CellCostMetricsV2 {
                    cpu_micros: Some(11),
                    ..CellCostMetricsV2::default()
                },
            })
            .await,
    );
    let ledger = checked(handle.task_cost().await);
    assert_ne!(ledger, receipt.cost);
    let before = retained(&fixture);
    let observed = checked(handle.observe_intent(intent.clone()).await);
    assert_eq!(observed.receipt(), Some(&receipt));
    assert_eq!(observed.pending_request(), None);
    assert_eq!(observed.scope(), &original.predecessor.scope);
    let output = checked(observed.pending_output().cloned().ok_or("committed output"));
    assert_eq!(output.operation_id, receipt.operation_id);
    assert_eq!(output.request_digest, receipt.request_digest);
    assert_eq!(
        handle.observe_intent(intent.clone()).await,
        Ok(observed.clone())
    );
    assert_eq!(checked(handle.task_cost().await), ledger);
    assert_eq!(retained(&fixture), before);
    tasks.shutdown().await;

    // This is a cold reopen, not a cross-owner Circuit takeover assertion.
    fixture.reopen_state().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 2,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let before = retained(&fixture);
    assert_eq!(handle.observe_intent(intent.clone()).await, Ok(observed));
    let mut changed = intent.clone();
    changed.input_digest = [99; 32];
    assert_eq!(
        handle.observe_intent(changed).await,
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(retained(&fixture), before);
    fixture.state().mark_fenced();
    assert!(handle.observe_intent(intent).await.is_err());
    tasks.shutdown().await;
    assert_eq!(retained(&fixture), before);
}

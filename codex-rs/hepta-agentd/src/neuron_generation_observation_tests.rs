use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use pretty_assertions::assert_eq;

use super::support::Fixture;
use super::support::checked;
use super::support::cost;
use super::support::host;
use super::support::poll_pending;
use super::support::request;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_service::spawn_neuron_generation_service;

#[tokio::test]
async fn owner_observation_rpc_retains_unknown_work_cost_and_delivery_across_reopen() {
    let mut fixture = Fixture::new().await;
    let journal = fixture.journal();
    let initial = checked(journal.observe_generation());
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        journal,
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    assert_eq!(handle.observe_generation().await, Ok(initial.clone()));
    let planning = CellCostEntryV2 {
        event_id: [71; 32],
        identity: cost().identity(),
        stage: CellCostStageV2::Planning,
        outcome: CellCostOutcomeV2::Succeeded,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(17),
            ..CellCostMetricsV2::default()
        },
    };
    checked(handle.record_cost(planning.clone()).await);
    let planned = checked(handle.observe_generation().await);
    assert_eq!(planned.cost().entries(), std::slice::from_ref(&planning));
    assert_eq!(planned.snapshot(), initial.snapshot());
    assert_ne!(planned.owner_checkpoint(), initial.owner_checkpoint());
    checked(handle.record_cost(planning.clone()).await);
    assert_eq!(handle.observe_generation().await, Ok(planned.clone()));
    let mut wrong_task = planning.clone();
    wrong_task.event_id = [72; 32];
    wrong_task.identity.task_digest = [73; 32];
    assert_eq!(
        handle.record_cost(wrong_task).await,
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(handle.observe_generation().await, Ok(planned.clone()));

    fixture
        .control
        .signals
        .lose_response
        .store(true, Ordering::SeqCst);
    let req = request("unknown-observation", planned.snapshot().clone());
    let mut step = Box::pin(handle.step(req.clone()));
    poll_pending(step.as_mut());
    let mut observe = Box::pin(handle.observe_generation());
    poll_pending(observe.as_mut());
    let (result, observed) = tokio::join!(step, observe);
    assert_eq!(result, Err(CellGenerationErrorV2::Unavailable));
    let pending = checked(observed);
    assert_eq!(
        pending.pending_request_digest(),
        Some(checked(req.digest()))
    );
    assert_eq!(pending.cost(), planned.cost());
    assert_eq!(pending.snapshot(), planned.snapshot());
    assert!(!pending.is_terminal());
    assert_eq!(pending.complete_metrics(), None);
    checked(handle.cancel(checked(req.digest())).await);
    let cancelled = checked(handle.observe_generation().await);
    assert_eq!(
        cancelled.pending_request_digest(),
        pending.pending_request_digest()
    );
    assert_ne!(cancelled.digest(), pending.digest());
    tasks.shutdown().await;
    drop(handle);
    fixture.reopen_state().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    assert_eq!(handle.observe_generation().await, Ok(cancelled));
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.control.signals.reads.load(Ordering::SeqCst), 0);
    fixture
        .control
        .signals
        .readable
        .store(true, Ordering::SeqCst);
    let receipt = checked(handle.reconcile(checked(req.digest())).await);
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Cancelled);
    let settled = checked(handle.observe_generation().await);
    assert_eq!(settled.pending_request_digest(), None);
    assert_eq!(settled.pending_output(), None);
    assert_eq!(settled.snapshot().prefix, initial.snapshot().prefix);
    assert_eq!(settled.cost().entries().first(), Some(&planning));
    assert_eq!(checked(settled.cost().summary()).cpu_micros.known_sum, 7);
    assert_eq!(settled.complete_metrics(), None);

    fixture
        .control
        .signals
        .lose_response
        .store(false, Ordering::SeqCst);
    let next = request("next-observation", settled.snapshot().clone());
    checked(handle.step(next.clone()).await);
    let delivered = checked(handle.observe_generation().await);
    let chunk = checked(
        delivered
            .pending_output()
            .cloned()
            .ok_or("committed output"),
    );
    assert_eq!(delivered.pending_request_digest(), None);
    assert_eq!(chunk.request_digest, checked(next.digest()));
    assert_eq!(chunk.bytes, delivered.snapshot().prefix);
    checked(handle.acknowledge(chunk, [81; 32], cost()).await);
    let acknowledged = checked(handle.observe_generation().await);
    assert_eq!(acknowledged.pending_output(), None);
    assert_eq!(acknowledged.snapshot(), delivered.snapshot());
    assert_eq!(acknowledged.cost(), delivered.cost());
    assert_ne!(acknowledged.digest(), delivered.digest());
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 2);
    tasks.shutdown().await;
}

#[tokio::test]
async fn planned_step_rejects_changed_cost_cut_and_replays_only_exact_recorded_work() {
    let fixture = Fixture::new().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        fixture.control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    ));
    let (mut tasks, lifetime) = host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let original = checked(handle.observe_generation().await);
    let req = request("planned-original", original.snapshot().clone());
    let planning = CellCostEntryV2 {
        event_id: [91; 32],
        identity: cost().identity(),
        stage: CellCostStageV2::Planning,
        outcome: CellCostOutcomeV2::Succeeded,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(19),
            ..CellCostMetricsV2::default()
        },
    };
    let mut intervening = planning.clone();
    intervening.event_id = [92; 32];
    checked(handle.record_cost(intervening).await);
    let changed = checked(handle.observe_generation().await);
    assert_eq!(changed.snapshot(), original.snapshot());
    assert_eq!(
        handle
            .step_planned(original.owner_checkpoint(), planning.clone(), req.clone())
            .await,
        Err(CellGenerationErrorV2::Conflict)
    );
    let stale = checked(handle.observe_generation().await);
    assert_eq!(stale.snapshot(), changed.snapshot());
    assert!(stale.cost().entries().contains(&planning));
    assert_ne!(stale.owner_checkpoint(), changed.owner_checkpoint());
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 0);
    let changed = stale;

    let mut expired = request("planned-expired", changed.snapshot().clone());
    expired.deadline_micros = 15;
    let mut retained = planning.clone();
    retained.event_id = [93; 32];
    assert_eq!(
        handle
            .step_planned(
                changed.owner_checkpoint(),
                retained.clone(),
                expired.clone()
            )
            .await,
        Err(CellGenerationErrorV2::Deadline)
    );
    let partial = checked(handle.observe_generation().await);
    assert!(partial.cost().entries().contains(&retained));
    assert_eq!(partial.pending_request_digest(), None);
    assert_eq!(
        handle
            .step_planned(changed.owner_checkpoint(), retained, expired)
            .await,
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(handle.observe_generation().await, Ok(partial.clone()));
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 0);
    let changed = partial;
    let mut planning = planning;
    planning.event_id = [94; 32];

    fixture
        .control
        .signals
        .lose_response
        .store(true, Ordering::SeqCst);
    assert_eq!(
        handle
            .step_planned(changed.owner_checkpoint(), planning.clone(), req.clone())
            .await,
        Err(CellGenerationErrorV2::Unavailable)
    );
    let pending = checked(handle.observe_generation().await);
    assert_eq!(
        pending.pending_request_digest(),
        Some(checked(req.digest()))
    );
    assert_eq!(
        pending
            .cost()
            .entries()
            .iter()
            .filter(|entry| *entry == &planning)
            .count(),
        1
    );
    assert_eq!(
        handle
            .step_planned(changed.owner_checkpoint(), planning.clone(), req.clone())
            .await,
        Err(CellGenerationErrorV2::Pending)
    );
    assert_eq!(handle.observe_generation().await, Ok(pending.clone()));
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    let mut extra_attempt = planning.clone();
    extra_attempt.event_id = [95; 32];
    assert_eq!(
        handle
            .step_planned(
                changed.owner_checkpoint(),
                extra_attempt.clone(),
                req.clone()
            )
            .await,
        Err(CellGenerationErrorV2::Conflict)
    );
    let retained_extra = checked(handle.observe_generation().await);
    assert!(retained_extra.cost().entries().contains(&extra_attempt));
    assert_eq!(retained_extra.snapshot(), pending.snapshot());
    assert_eq!(
        retained_extra.pending_request_digest(),
        pending.pending_request_digest()
    );
    let pending = retained_extra;
    let mut forged_charge = planning.clone();
    forged_charge.metrics.wall_micros = Some(0);
    assert_eq!(
        handle
            .step_planned(changed.owner_checkpoint(), forged_charge, req.clone())
            .await,
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(fixture.control.signals.reads.load(Ordering::SeqCst), 1);
    assert_eq!(handle.observe_generation().await, Ok(pending));

    fixture
        .control
        .signals
        .readable
        .store(true, Ordering::SeqCst);
    let receipt = checked(
        handle
            .step_planned(changed.owner_checkpoint(), planning.clone(), req.clone())
            .await,
    );
    let committed = checked(handle.observe_generation().await);
    assert_eq!(committed.pending_request_digest(), None);
    assert_eq!(
        handle
            .step_planned(changed.owner_checkpoint(), planning.clone(), req)
            .await,
        Ok(receipt)
    );
    assert_eq!(handle.observe_generation().await, Ok(committed.clone()));
    assert_eq!(
        committed
            .cost()
            .entries()
            .iter()
            .filter(|entry| *entry == &planning)
            .count(),
        1
    );
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.control.signals.reads.load(Ordering::SeqCst), 2);
    tasks.shutdown().await;
}

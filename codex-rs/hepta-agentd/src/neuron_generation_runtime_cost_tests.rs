use std::fs;
use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellCostTotalV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use pretty_assertions::assert_eq;

use super::support::Fixture;
use super::support::checked;
use super::support::cost;
use super::support::host;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_service::spawn_neuron_generation_service;

#[tokio::test]
async fn service_appends_exact_costs_without_filling_missing_metrics_or_double_counting() {
    let fixture = Fixture::new().await;
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
        lifetime,
    ));
    let training = CellCostEntryV2 {
        event_id: [80; 32],
        identity: cost().identity(),
        stage: CellCostStageV2::Training,
        outcome: CellCostOutcomeV2::Failed,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(30),
            ..CellCostMetricsV2::default()
        },
    };
    let mut wrong_task = training.clone();
    wrong_task.identity.task_digest = [81; 32];
    assert_eq!(
        handle.record_cost(wrong_task).await,
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    let mut wrong_source = training.clone();
    wrong_source.identity.source_digest = [82; 32];
    assert_eq!(
        handle.record_cost(wrong_source).await,
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(checked(handle.task_cost().await), cost());
    checked(handle.record_cost(training.clone()).await);
    let path = fixture.directory.path().join("generation-journal");
    let after_training = checked(fs::read(&path));
    checked(handle.record_cost(training.clone()).await);
    let mut conflicting = training.clone();
    conflicting.metrics.wall_micros = Some(31);
    assert_eq!(
        handle.record_cost(conflicting).await,
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(checked(fs::read(&path)), after_training);

    let envelope = CellCostEntryV2 {
        event_id: [83; 32],
        accounting: CellCostAccountingV2::InclusiveEnvelope {
            exclusive_event_ids: vec![training.event_id],
        },
        metrics: CellCostMetricsV2 {
            wall_micros: Some(90),
            ..CellCostMetricsV2::default()
        },
        ..training.clone()
    };
    let mut oversized = envelope.clone();
    oversized.accounting = CellCostAccountingV2::InclusiveEnvelope {
        exclusive_event_ids: vec![training.event_id; 257],
    };
    assert_eq!(
        handle.record_cost(oversized).await,
        Err(CellGenerationErrorV2::Capacity)
    );
    checked(handle.record_cost(envelope.clone()).await);
    let mut expected = cost();
    checked(expected.record(training));
    checked(expected.record(envelope));
    let observed = checked(handle.task_cost().await);
    assert_eq!(observed, expected);
    let summary = checked(observed.summary());
    assert_eq!(
        summary.wall_work_micros,
        CellCostTotalV2 {
            known_sum: 30,
            unknown_entries: 0
        }
    );
    assert_eq!(
        (summary.cpu_micros, summary.energy_microjoules),
        (
            CellCostTotalV2 {
                known_sum: 0,
                unknown_entries: 1
            },
            CellCostTotalV2 {
                known_sum: 0,
                unknown_entries: 1
            }
        )
    );
    assert_eq!(fixture.control.signals.calls.load(Ordering::SeqCst), 0);
    tasks.shutdown().await;
    drop(handle);
    let reopened = fixture.journal();
    assert_eq!(checked(reopened.task_cost()), &expected);
}

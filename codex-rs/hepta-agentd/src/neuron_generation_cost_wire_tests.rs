//! Cost coverage and unknown measurements survive journal replay and control JSON.

use std::fs;
use std::sync::atomic::Ordering;

use codex_hepta_agent_protocol::GenerationControlRequestV1 as Request;
use codex_hepta_agent_protocol::GenerationControlResponseV1 as Response;
use codex_hepta_agent_protocol::GenerationCostTotalV1;
use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::Serving;
use super::TestResult;

fn expected(cost: &CellTaskCostV2) -> TestResult<Response> {
    // The native enum's canonical serde names and all summary fields form an
    // independent expectation for the control codec, including later stages.
    let mut value = serde_json::to_value(cost.summary()?)?;
    value["task_digest"] = serde_json::to_value(cost.identity().task_digest)?;
    value["source_digest"] = serde_json::to_value(cost.identity().source_digest)?;
    value["ledger_digest"] = serde_json::to_value(
        Digest32::of_parts(&[
            b"hepta.agentd.generation-cost.v1\0",
            &serde_json::to_vec(cost)?,
        ])
        .into_array(),
    )?;
    Ok(Response::Cost(Box::new(serde_json::from_value(value)?)))
}

#[tokio::test]
async fn acquisition_and_migration_costs_roundtrip_without_hiding_unknowns_or_double_charge()
-> TestResult {
    let mut fixture = Fixture::new().await;
    let empty = fixture.journal().task_cost()?.clone();
    let serving = Serving::start(&fixture).await?;
    let observed = serving.client.generation(Request::Cost {}).await?;
    assert_eq!(observed, expected(&empty)?);
    let Response::Cost(summary) = observed else {
        unreachable!()
    };
    assert!(summary.missing_stages.contains(&"model_acquisition".into()));
    assert!(summary.missing_stages.contains(&"migration".into()));
    serving.finish().await?;

    let mut journal = fixture.journal();
    let identity = journal.task_cost()?.identity();
    for entry in [
        CellCostEntryV2 {
            event_id: [101; 32],
            identity,
            stage: CellCostStageV2::ModelAcquisition,
            outcome: CellCostOutcomeV2::Failed,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(17),
                cpu_micros: Some(11),
                storage_read_bytes: Some(4096),
                communication_bytes: Some(128),
                ..CellCostMetricsV2::default()
            },
        },
        CellCostEntryV2 {
            event_id: [102; 32],
            identity,
            stage: CellCostStageV2::Migration,
            outcome: CellCostOutcomeV2::Unknown,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(23),
                storage_write_bytes: Some(3072),
                storage_byte_micros: Some(60),
                ..CellCostMetricsV2::default()
            },
        },
        CellCostEntryV2 {
            event_id: [103; 32],
            identity,
            stage: CellCostStageV2::Migration,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::InclusiveEnvelope {
                exclusive_event_ids: vec![[101; 32], [102; 32]],
            },
            metrics: CellCostMetricsV2 {
                wall_micros: Some(10_000),
                cpu_micros: Some(10_000),
                energy_microjoules: Some(10_000),
                storage_read_bytes: Some(10_000),
                storage_write_bytes: Some(10_000),
                storage_byte_micros: Some(10_000),
                communication_bytes: Some(10_000),
            },
        },
    ] {
        journal.record_cost(entry)?;
    }
    let charged = journal.task_cost()?.clone();
    drop(journal);
    let journal_bytes = fs::read(fixture.directory.path().join("generation-journal"))?;
    let witness_bytes = fs::read(fixture.directory.path().join("generation-witness"))?;
    fixture.reopen_state().await;
    let reopened = Serving::start(&fixture).await?;
    let observed = reopened.client.generation(Request::Cost {}).await?;
    assert_eq!(observed, expected(&charged)?);
    assert_eq!(
        reopened.client.generation(Request::Cost {}).await?,
        observed
    );
    let Response::Cost(summary) = observed else {
        unreachable!()
    };
    assert_eq!(
        (
            summary.exclusive_entries,
            summary.inclusive_envelopes,
            summary.unsuccessful_entries,
            summary.unknown_outcome_entries
        ),
        (2, 1, 1, 1)
    );
    assert_eq!(
        summary.wall_work_micros,
        GenerationCostTotalV1 {
            known_sum: 40,
            unknown_entries: 0
        }
    );
    assert_eq!(
        summary.cpu_micros,
        GenerationCostTotalV1 {
            known_sum: 11,
            unknown_entries: 1
        }
    );
    assert_eq!(
        summary.energy_microjoules,
        GenerationCostTotalV1 {
            known_sum: 0,
            unknown_entries: 2
        }
    );
    assert!(!summary.missing_stages.contains(&"model_acquisition".into()));
    assert!(!summary.missing_stages.contains(&"migration".into()));
    assert_eq!(
        fs::read(fixture.directory.path().join("generation-journal"))?,
        journal_bytes
    );
    assert_eq!(
        fs::read(fixture.directory.path().join("generation-witness"))?,
        witness_bytes
    );
    assert_eq!(
        [
            fixture.control.signals.calls.load(Ordering::SeqCst),
            fixture.control.signals.reads.load(Ordering::SeqCst),
            fixture.control.signals.cancellations.load(Ordering::SeqCst)
        ],
        [0; 3]
    );
    reopened.finish().await
}

use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence::GenerationEpisodeErrorV1;
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellTaskCostV2;
use pretty_assertions::assert_eq;

use super::support as host;
use crate::append_neuron_generation_outcome_v1;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_service::spawn_neuron_generation_service;
use host::checked;

#[path = "neuron_generation_episode_test_support.rs"]
mod support;
use support::LedgerFixture;
use support::TerminalControl;
use support::append_decision;
use support::digest;
use support::freeze;
use support::request;
use support::signed_request;

#[tokio::test]
async fn real_actor_delivery_and_cold_reopen_append_one_authenticated_outcome() {
    let mut fixture = host::Fixture::new().await;
    let frozen = freeze(&mut fixture);
    let control = TerminalControl::new(fixture.directory.path());
    let ledger_fixture = LedgerFixture::new();
    let mut writer = ledger_fixture.writer(false);
    let decision = append_decision(&mut writer, &frozen);
    let ledger_before = ledger_fixture.bytes();
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        control.clone(),
        fixture.clock(),
        4,
    ));
    let (mut tasks, lifetime) = host::host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let req = request(&fixture);
    checked(handle.step(req.clone()).await);
    let undelivered = checked(handle.observe_generation().await);
    assert!(undelivered.snapshot().stopped);
    assert!(!undelivered.is_terminal());
    let premature = signed_request(&writer, &frozen, None, decision.chain_digest);
    assert!(matches!(
        append_neuron_generation_outcome_v1(&handle, &mut writer, &frozen, premature, 50).await,
        Err(GenerationEpisodeErrorV1::Binding(
            "generation not settled and delivered"
        ))
    ));
    assert_eq!(ledger_fixture.bytes(), ledger_before);
    let chunk = checked(undelivered.pending_output().cloned().ok_or("outbox"));
    let ack_cost = checked(CellTaskCostV2::new(undelivered.cost().identity()));
    checked(handle.acknowledge(chunk, [91; 32], ack_cost).await);
    let observed = checked(handle.observe_generation().await);
    assert!(observed.is_terminal());
    assert_eq!(observed.complete_metrics(), None);
    let outcome = signed_request(&writer, &frozen, Some(&observed), decision.chain_digest);
    let appended = checked(
        append_neuron_generation_outcome_v1(&handle, &mut writer, &frozen, outcome.clone(), 50)
            .await,
    );
    assert_eq!(appended.disposition, AppendDisposition::Appended);
    assert_eq!(checked(writer.records()).len(), 2);
    let ledger_after = ledger_fixture.bytes();
    let generation_after = checked(std::fs::read(
        fixture.directory.path().join("generation-journal"),
    ));
    tasks.shutdown().await;
    drop(handle);
    drop(writer);
    fixture.reopen_state().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        control.clone(),
        fixture.clock(),
        4,
    ));
    let (mut tasks, lifetime) = host::host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let mut writer = ledger_fixture.writer(true);
    assert_eq!(handle.observe_generation().await, Ok(observed));
    let replay = checked(
        append_neuron_generation_outcome_v1(&handle, &mut writer, &frozen, outcome, 50).await,
    );
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(replay.chain_digest, appended.chain_digest);
    assert_eq!(checked(writer.records()).len(), 2);
    assert_eq!(ledger_fixture.bytes(), ledger_after);
    assert_eq!(
        checked(std::fs::read(
            fixture.directory.path().join("generation-journal")
        )),
        generation_after
    );
    assert_eq!(control.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
}

#[tokio::test]
async fn fresh_actor_cut_rejects_old_signed_support_without_a_ledger_mutation() {
    let mut fixture = host::Fixture::new().await;
    let frozen = freeze(&mut fixture);
    let control = TerminalControl::new(fixture.directory.path());
    let ledger_fixture = LedgerFixture::new();
    let mut writer = ledger_fixture.writer(false);
    let decision = append_decision(&mut writer, &frozen);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        control.clone(),
        fixture.clock(),
        4,
    ));
    let (mut tasks, lifetime) = host::host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    checked(handle.step(request(&fixture)).await);
    let outbox = checked(handle.observe_generation().await);
    let chunk = checked(outbox.pending_output().cloned().ok_or("outbox"));
    checked(
        handle
            .acknowledge(
                chunk,
                [92; 32],
                checked(CellTaskCostV2::new(outbox.cost().identity())),
            )
            .await,
    );
    let sampled = checked(handle.observe_generation().await);
    let stale = signed_request(&writer, &frozen, Some(&sampled), decision.chain_digest);
    let ledger_before = ledger_fixture.bytes();
    let head_before = checked(writer.snapshot());
    checked(
        handle
            .record_cost(CellCostEntryV2 {
                event_id: digest("late-recovery").into_array(),
                identity: sampled.cost().identity(),
                stage: CellCostStageV2::Recovery,
                outcome: CellCostOutcomeV2::Succeeded,
                accounting: CellCostAccountingV2::Exclusive,
                metrics: CellCostMetricsV2::default(),
            })
            .await,
    );
    let current = checked(handle.observe_generation().await);
    assert_eq!(current.snapshot(), sampled.snapshot());
    assert_ne!(current.owner_checkpoint(), sampled.owner_checkpoint());
    assert!(matches!(
        append_neuron_generation_outcome_v1(&handle, &mut writer, &frozen, stale, 50).await,
        Err(GenerationEpisodeErrorV1::Binding(
            "generation outcome identity"
        ))
    ));
    assert_eq!(checked(writer.snapshot()), head_before);
    assert_eq!(ledger_fixture.bytes(), ledger_before);
    let valid = signed_request(&writer, &frozen, Some(&current), decision.chain_digest);
    let mut bad_signature = valid.clone();
    bad_signature.evidence.signature[0] ^= 1;
    assert!(
        append_neuron_generation_outcome_v1(&handle, &mut writer, &frozen, bad_signature, 50,)
            .await
            .is_err()
    );
    assert_eq!(checked(writer.snapshot()), head_before);
    assert_eq!(ledger_fixture.bytes(), ledger_before);
    let receipt = checked(
        append_neuron_generation_outcome_v1(&handle, &mut writer, &frozen, valid, 50).await,
    );
    assert_eq!(receipt.disposition, AppendDisposition::Appended);
    assert_eq!(checked(writer.records()).len(), 2);
    assert_eq!(control.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
}

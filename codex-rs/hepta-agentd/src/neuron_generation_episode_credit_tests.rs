use codex_hepta_intelligence::OutcomeCreditClosureErrorV2;
use codex_hepta_learning_ledger::CausalV2Error;
use codex_hepta_types::FixedQ32;

use super::*;
use crate::append_neuron_generation_outcome_credit_v1;
use pretty_assertions::assert_eq;
use support::signed_closure;

#[tokio::test]
async fn actor_terminal_credit_recovers_partial_commit_without_executing_again() {
    let mut fixture = host::Fixture::new().await;
    let frozen = freeze(&mut fixture);
    let control = TerminalControl::new(fixture.directory.path());
    let ledger_fixture = LedgerFixture::new();
    let mut writer = ledger_fixture.writer(/*reopen*/ false);
    let decision = append_decision(&mut writer, &frozen);
    let before = ledger_bytes(&mut writer);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    ));
    let (mut tasks, lifetime) = host::host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    checked(handle.step(request(&fixture)).await);
    let undelivered = checked(handle.observe_generation().await);
    let premature = signed_closure(
        &writer,
        signed_request(
            &writer,
            &frozen,
            /*observation*/ None,
            decision.chain_digest,
        ),
    );
    assert!(matches!(
        append_neuron_generation_outcome_credit_v1(
            &handle,
            &mut writer,
            &frozen,
            premature,
            /*now*/ 50,
        )
        .await,
        Err(GenerationEpisodeErrorV1::Binding(
            "generation not settled and delivered"
        ))
    ));
    assert_eq!(ledger_bytes(&mut writer), before);
    let chunk = checked(undelivered.pending_output().cloned().ok_or("outbox"));
    checked(
        handle
            .acknowledge(
                chunk,
                [93; 32],
                checked(CellTaskCostV2::new(undelivered.cost().identity())),
            )
            .await,
    );
    let observed = checked(handle.observe_generation().await);
    let original = signed_closure(
        &writer,
        signed_request(&writer, &frozen, Some(&observed), decision.chain_digest),
    );

    let mut invalid = original.clone();
    invalid.credit.conservation_residual = FixedQ32::from_raw(1);
    assert!(matches!(
        append_neuron_generation_outcome_credit_v1(
            &handle,
            &mut writer,
            &frozen,
            invalid,
            /*now*/ 50,
        )
        .await,
        Err(GenerationEpisodeErrorV1::Outcome(
            OutcomeCreditClosureErrorV2::InvalidCredit(CausalV2Error::CreditConservation)
        ))
    ));
    assert_eq!(ledger_bytes(&mut writer), before);

    let mut bad_signature = original.clone();
    bad_signature.credit_evidence.signature[0] ^= 1;
    let partial = match append_neuron_generation_outcome_credit_v1(
        &handle,
        &mut writer,
        &frozen,
        bad_signature,
        /*now*/ 50,
    )
    .await
    {
        Err(GenerationEpisodeErrorV1::Outcome(OutcomeCreditClosureErrorV2::Credit {
            outcome,
            ..
        })) => outcome,
        other => panic!("expected durable outcome and rejected credit: {other:?}"),
    };
    assert_eq!(partial.disposition, AppendDisposition::Appended);
    assert_eq!(checked(writer.records()).len(), 2);
    tasks.shutdown().await;
    drop(handle);
    drop(writer);
    let generation_after = checked(std::fs::read(
        fixture.directory.path().join("generation-journal"),
    ));
    fixture.reopen_state().await;
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
    ));
    let (mut tasks, lifetime) = host::host();
    checked(spawn_neuron_generation_service(
        &mut tasks,
        bootstrap,
        Arc::clone(fixture.state()),
        lifetime.clone(),
    ));
    let mut writer = ledger_fixture.writer(/*reopen*/ true);
    assert_eq!(handle.observe_generation().await, Ok(observed));
    let recovered = checked(
        append_neuron_generation_outcome_credit_v1(
            &handle,
            &mut writer,
            &frozen,
            original.clone(),
            /*now*/ 50,
        )
        .await,
    );
    assert_eq!(
        recovered.outcome.disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(recovered.outcome.chain_digest, partial.chain_digest);
    assert_eq!(recovered.credit.disposition, AppendDisposition::Appended);
    assert!(!recovered.authority.grants_any());
    assert_eq!(checked(writer.records()).len(), 3);
    let after = ledger_bytes(&mut writer);
    let replay = checked(
        append_neuron_generation_outcome_credit_v1(
            &handle,
            &mut writer,
            &frozen,
            original,
            /*now*/ 50,
        )
        .await,
    );
    assert_eq!(
        replay.credit.disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.closure_digest, recovered.closure_digest);
    assert_eq!(ledger_bytes(&mut writer), after);
    assert_eq!(control.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
    drop(handle);
    assert_eq!(
        checked(std::fs::read(
            fixture.directory.path().join("generation-journal")
        )),
        generation_after
    );
}

#[tokio::test]
async fn actor_terminal_credit_rejects_stale_owner_cut_before_both_appends() {
    let mut fixture = host::Fixture::new().await;
    let frozen = freeze(&mut fixture);
    let control = TerminalControl::new(fixture.directory.path());
    let ledger_fixture = LedgerFixture::new();
    let mut writer = ledger_fixture.writer(/*reopen*/ false);
    let decision = append_decision(&mut writer, &frozen);
    let (handle, bootstrap) = checked(neuron_generation_channel_v2(
        &fixture.identity,
        fixture.journal(),
        control.clone(),
        fixture.clock(),
        /*capacity*/ 4,
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
    checked(
        handle
            .acknowledge(
                checked(outbox.pending_output().cloned().ok_or("outbox")),
                [94; 32],
                checked(CellTaskCostV2::new(outbox.cost().identity())),
            )
            .await,
    );
    let sampled = checked(handle.observe_generation().await);
    let stale = signed_closure(
        &writer,
        signed_request(&writer, &frozen, Some(&sampled), decision.chain_digest),
    );
    checked(
        handle
            .record_cost(CellCostEntryV2 {
                event_id: digest("post-sample-recovery").into_array(),
                identity: sampled.cost().identity(),
                stage: CellCostStageV2::Recovery,
                outcome: CellCostOutcomeV2::Succeeded,
                accounting: CellCostAccountingV2::Exclusive,
                metrics: CellCostMetricsV2::default(),
            })
            .await,
    );
    let before = ledger_bytes(&mut writer);
    assert!(matches!(
        append_neuron_generation_outcome_credit_v1(
            &handle,
            &mut writer,
            &frozen,
            stale,
            /*now*/ 50,
        )
        .await,
        Err(GenerationEpisodeErrorV1::Binding(
            "generation outcome identity"
        ))
    ));
    assert_eq!(ledger_bytes(&mut writer), before);
    let current = checked(handle.observe_generation().await);
    let fresh = signed_closure(
        &writer,
        signed_request(&writer, &frozen, Some(&current), decision.chain_digest),
    );
    let closed = checked(
        append_neuron_generation_outcome_credit_v1(
            &handle,
            &mut writer,
            &frozen,
            fresh,
            /*now*/ 50,
        )
        .await,
    );
    assert_eq!(closed.outcome.disposition, AppendDisposition::Appended);
    assert_eq!(closed.credit.disposition, AppendDisposition::Appended);
    assert_eq!(control.calls.load(Ordering::SeqCst), 1);
    tasks.shutdown().await;
}

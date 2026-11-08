use pretty_assertions::assert_eq;

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;

use codex_hepta_intelligence::OutcomeCreditClosureErrorV2;
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;
use crate::circuit_credit::circuit_learning_run_id_v1;

#[path = "circuit_credit_ledger_test_support.rs"]
mod ledger_support;
use ledger_support::LedgerFixture;
use ledger_support::append_decision;
use ledger_support::closure;

struct ExecutedCircuit {
    store: AutomationStore,
    runtime: AgentdCircuitCellOwnerV1<CellPartitionOwnerV1, Model, Encoder>,
    inputs: BTreeMap<u64, CellStepInputV1>,
    calls: Arc<AtomicUsize>,
    _directory: tempfile::TempDir,
}

async fn apply_run(
    store: &AutomationStore,
    run: &StableId,
    fence: &TaskFlowFence,
    command: &str,
    now_ms: u64,
    event: CircuitEventV2,
) -> CircuitCommandReceiptV2 {
    let current = checked(store.bounded_circuit_run(run.as_str()).await).expect("run");
    checked(
        store
            .apply_bounded_circuit_command(&CircuitCommandV2 {
                run_id: run.to_string(),
                command_id: command.to_string(),
                fence: fence.clone(),
                expected_revision: current.revision(),
                now_ms,
                event,
            })
            .await,
    )
}

async fn execute(owner: AgentId, run: &StableId, objective: Digest32) -> ExecutedCircuit {
    let directory = checked(tempfile::tempdir());
    let fence = checked(TaskFlowFence::new(
        owner.clone(),
        "owner",
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        "fence",
    ));
    let layout = checked(HeptaFleetRoot::parse(directory.path().join("fleet")))
        .layout()
        .agent(&owner);
    let store = checked(AutomationStore::open(&layout).await);
    let (definition, bindings) = configuration();
    let mut input = input(run.as_str());
    input.scope.agent_id = id(owner.as_str());
    input.objective_digest = objective;
    checked(
        store
            .create_bounded_circuit_run(
                &definition,
                &CircuitStartV2 {
                    run_id: run.to_string(),
                    scope_digest: checked(circuit_cell_scope_digest_v1(&input.scope)),
                    input_digest: Sha256Digest::for_bytes(&input.observation),
                    created_at_ms: 10,
                    lease_duration_ms: 500,
                },
                &fence,
            )
            .await,
    );
    let advanced = apply_run(
        &store,
        run,
        &fence,
        "advance",
        /*now_ms*/ 11,
        CircuitEventV2::Advance { quantum: 1 },
    )
    .await;
    let dispatch = &advanced.dispatches[0];
    input.operation_id = checked(circuit_cell_operation_id_v1(dispatch));
    let mut state = checked(CellPartitionOwnerV1::new(
        /*max_partitions*/ 2, /*max_receipts_per_partition*/ 4,
    ));
    checked(state.admit(
        input.scope.clone(),
        &bindings[0].cell,
        d("frontier"),
        /*writer_epoch*/ 1,
    ));
    let admission = checked(
        store
            .claim_circuit_computation(&CircuitComputationClaimV2 {
                run_id: run.to_string(),
                activation_id: dispatch.activation_id,
                command_id: "claim".to_string(),
                fence: fence.clone(),
                expected_revision: advanced.run.revision(),
                now_ms: 13,
                execution_request_digest: checked(Sha256Digest::parse(
                    checked(canonical_cell_step_request_digest_v1(
                        &bindings[0].cell,
                        &input,
                    ))
                    .to_string(),
                )),
            })
            .await,
    );
    let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = model.calls.clone();
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        state,
        model,
        Encoder,
    );
    let result = checked(runtime.execute(admission, input.clone(), time));
    apply_run(
        &store,
        run,
        &fence,
        "complete",
        /*now_ms*/ 22,
        CircuitEventV2::Complete {
            completion: result.completion,
        },
    )
    .await;
    apply_run(
        &store,
        run,
        &fence,
        "exit",
        /*now_ms*/ 23,
        CircuitEventV2::Advance { quantum: 1 },
    )
    .await;
    ExecutedCircuit {
        store,
        runtime,
        inputs: BTreeMap::from([(dispatch.activation_id, input)]),
        calls,
        _directory: directory,
    }
}

#[tokio::test]
async fn signed_credit_rejects_cross_owner_ledger_episode_before_any_append() {
    let mut ledger = LedgerFixture::new("ledger-A");
    let owner = fence().owner_agent_id;
    let episode = id("episode-A");
    let run = checked(circuit_learning_run_id_v1(&ledger.writer, &owner, &episode));
    append_decision(&mut ledger.writer, &run, &episode);
    let original = execute(owner.clone(), &run, d("objective")).await;
    let support = checked(
        original
            .runtime
            .terminal_credit_support(&original.store, run.as_str(), &original.inputs)
            .await,
    );

    let foreign_owner = checked(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13"));
    let foreign = execute(foreign_owner, &run, d("objective")).await;
    let foreign_support = checked(
        foreign
            .runtime
            .terminal_credit_support(&foreign.store, run.as_str(), &foreign.inputs)
            .await,
    );
    let before = ledger.bytes();
    let signed = closure(&ledger.writer, &run, &episode, &foreign_support);
    assert!(matches!(
        foreign
            .runtime
            .append_terminal_credit(
                &foreign.store,
                &foreign.inputs,
                &mut ledger.writer,
                signed,
                /*now*/ 50
            )
            .await,
        Err(CircuitCreditErrorV1::Binding(
            "ledger/owner/episode execution identity"
        ))
    ));
    assert_eq!(ledger.bytes(), before);

    let mut other_ledger = LedgerFixture::new("ledger-B");
    // This is a valid independently signed Decision with the same run and
    // episode bytes in a different authorized ledger domain.
    append_decision(&mut other_ledger.writer, &run, &episode);
    let before = other_ledger.bytes();
    let signed = closure(&other_ledger.writer, &run, &episode, &support);
    assert!(matches!(
        original
            .runtime
            .append_terminal_credit(
                &original.store,
                &original.inputs,
                &mut other_ledger.writer,
                signed,
                /*now*/ 50
            )
            .await,
        Err(CircuitCreditErrorV1::Binding(
            "ledger/owner/episode execution identity"
        ))
    ));
    assert_eq!(other_ledger.bytes(), before);

    let before = ledger.bytes();
    let signed = closure(&ledger.writer, &run, &id("episode-B"), &support);
    assert!(matches!(
        original
            .runtime
            .append_terminal_credit(
                &original.store,
                &original.inputs,
                &mut ledger.writer,
                signed,
                /*now*/ 50
            )
            .await,
        Err(CircuitCreditErrorV1::Binding(
            "ledger/owner/episode execution identity"
        ))
    ));
    assert_eq!(ledger.bytes(), before);

    let mut legacy_ledger = LedgerFixture::new("legacy-ledger");
    let legacy_run = id("run-1");
    append_decision(&mut legacy_ledger.writer, &legacy_run, &episode);
    let legacy = execute(owner.clone(), &legacy_run, d("objective")).await;
    let legacy_support = checked(
        legacy
            .runtime
            .terminal_credit_support(&legacy.store, legacy_run.as_str(), &legacy.inputs)
            .await,
    );
    let before_legacy = legacy_ledger.bytes();
    let legacy_signed = closure(
        &legacy_ledger.writer,
        &legacy_run,
        &episode,
        &legacy_support,
    );
    assert!(matches!(
        legacy
            .runtime
            .append_terminal_credit(
                &legacy.store,
                &legacy.inputs,
                &mut legacy_ledger.writer,
                legacy_signed,
                /*now*/ 50
            )
            .await,
        Err(CircuitCreditErrorV1::Binding(
            "ledger/owner/episode execution identity"
        ))
    ));
    assert_eq!(legacy_ledger.bytes(), before_legacy);

    let wrong_objective = execute(owner, &run, d("unrelated-objective")).await;
    let wrong_support = checked(
        wrong_objective
            .runtime
            .terminal_credit_support(
                &wrong_objective.store,
                run.as_str(),
                &wrong_objective.inputs,
            )
            .await,
    );
    let signed = closure(&ledger.writer, &run, &episode, &wrong_support);
    assert!(matches!(
        wrong_objective
            .runtime
            .append_terminal_credit(
                &wrong_objective.store,
                &wrong_objective.inputs,
                &mut ledger.writer,
                signed,
                /*now*/ 50
            )
            .await,
        Err(CircuitCreditErrorV1::Binding(
            "executed objective differs from ledger"
        ))
    ));
    assert_eq!(ledger.bytes(), before);

    let signed = closure(&ledger.writer, &run, &episode, &support);
    let mut bad = signed.clone();
    bad.credit_evidence.signature[0] ^= 1;
    assert!(matches!(
        original
            .runtime
            .append_terminal_credit(
                &original.store,
                &original.inputs,
                &mut ledger.writer,
                bad,
                /*now*/ 50
            )
            .await,
        Err(CircuitCreditErrorV1::Closure(
            OutcomeCreditClosureErrorV2::Credit { .. }
        ))
    ));
    assert_eq!(checked(ledger.writer.records()).len(), 2);
    let committed = checked(
        original
            .runtime
            .append_terminal_credit(
                &original.store,
                &original.inputs,
                &mut ledger.writer,
                signed.clone(),
                /*now*/ 50,
            )
            .await,
    );
    let before = ledger.bytes();
    let replay = checked(
        original
            .runtime
            .append_terminal_credit(
                &original.store,
                &original.inputs,
                &mut ledger.writer,
                signed,
                /*now*/ 50,
            )
            .await,
    );
    let mut expected = committed;
    expected.outcome.disposition = AppendDisposition::IdempotentReplay;
    expected.credit.disposition = AppendDisposition::IdempotentReplay;
    assert_eq!(replay, expected);
    assert_eq!(ledger.bytes(), before);
    assert_eq!(
        (
            checked(ledger.writer.records()).len(),
            original.calls.load(Ordering::SeqCst)
        ),
        (3, 1)
    );
    original.store.close().await;
    foreign.store.close().await;
    wrong_objective.store.close().await;
    legacy.store.close().await;
}

use std::collections::BTreeMap;
use codex_hepta_types::Digest32;

use super::*;
use crate::CircuitCellCausalRecordV1;

#[tokio::test]
async fn causal_readback_joins_original_clocks_and_survives_circuit_reopen_without_contact() {
    let (definition, bindings) = configuration();
    let (directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    let inputs = BTreeMap::from([(dispatch.activation_id, request.clone())]);
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = model.calls.clone();
    let reads = model.reads.clone();
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings.clone())),
        native_owner(&bindings), model, Encoder,
    );
    let executed = checked(runtime.execute(admission, request.clone(), time));
    // A Cell commit alone is not a consumed Circuit completion.
    assert!(runtime.committed_causal_records(&store, "run-1", &inputs).await.is_err());
    apply(&store, "complete", /*now_ms*/ 400, CircuitEventV2::Complete {
        completion: executed.completion.clone(),
    }).await;
    let trace = checked(store.bounded_circuit_committed_trace("run-1").await).expect("trace");
    let activation = &trace.run().activations()[&dispatch.activation_id];
    let expected = vec![CircuitCellCausalRecordV1 {
        circuit_run_id: "run-1".to_string(),
        activation_id: dispatch.activation_id,
        causal_parents: activation.causal_parents.clone(),
        circuit_history_digest: trace.history_digest().clone(),
        circuit_input_digest: activation.input_digest.clone(),
        circuit_ready_at_ms: activation.ready_at_ms,
        circuit_times: CircuitComputationTimesV2 {
            claimed_at_ms: Some(13), completed_at_ms: Some(400),
        },
        scope: request.scope.clone(),
        generation: bindings[0].cell.runtime.generation.get(),
        definition_digest: checked(bindings[0].cell.semantic_digest()),
        bundle_digest: executed.decision.bundle_digest,
        source_frontier: request.source_frontier,
        cell_requested_at_micros: request.monotonic_micros,
        observation_digest: Digest32::of_bytes(&request.observation),
        semantic_request_digest: executed.decision.semantic_request_digest,
        selected_candidate: executed.decision.selected_candidate,
        checkpoint_before: executed.decision.checkpoint_before,
        checkpoint_after: executed.decision.checkpoint_after,
        model_output_digest: executed.decision.model_output_digest,
        computation_outcome: executed.completion.outcome,
    }];
    let before = checked(runtime.state_owner().snapshot(&request.scope));
    assert_eq!(checked(runtime.committed_causal_records(&store, "run-1", &inputs).await), expected);
    store.close().await;
    let layout = checked(HeptaFleetRoot::parse(directory.path().join("fleet")))
        .layout().agent(&fence().owner_agent_id);
    let reopened = checked(AutomationStore::open(&layout).await);
    assert_eq!(checked(runtime.committed_causal_records(&reopened, "run-1", &inputs).await), expected);
    assert_eq!(checked(runtime.state_owner().snapshot(&request.scope)), before);
    assert_eq!((calls.load(Ordering::SeqCst), reads.load(Ordering::SeqCst)), (1, 0));
    reopened.close().await;
}

#[tokio::test]
async fn causal_readback_refuses_substituted_inputs_and_absent_cell_owner_history() {
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    let inputs = BTreeMap::from([(dispatch.activation_id, request.clone())]);
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition.clone(), bindings.clone())),
        native_owner(&bindings), Model::new(/*latency*/ 20, /*lose_response*/ false), Encoder,
    );
    let executed = checked(runtime.execute(admission, request, time));
    apply(&store, "complete", /*now_ms*/ 22, CircuitEventV2::Complete {
        completion: executed.completion,
    }).await;
    assert!(runtime.committed_causal_records(&store, "run-1", &BTreeMap::new()).await.is_err());
    enum Substitution { Observation, Candidates, Source, Clock }
    for change in [Substitution::Observation, Substitution::Candidates, Substitution::Source, Substitution::Clock] {
        let mut substituted = inputs.clone();
        let input = substituted.get_mut(&dispatch.activation_id).expect("input");
        match change {
            Substitution::Observation => input.observation.push(1),
            Substitution::Candidates => input.candidates[0].allowed = !input.candidates[0].allowed,
            Substitution::Source => input.source_frontier = d("different-source"),
            Substitution::Clock => input.monotonic_micros += 1,
        }
        assert!(runtime.committed_causal_records(&store, "run-1", &substituted).await.is_err());
    }
    let empty = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings.clone())),
        native_owner(&bindings), Model::new(/*latency*/ 20, /*lose_response*/ false), Encoder,
    );
    assert!(empty.committed_causal_records(&store, "run-1", &inputs).await.is_err());
    store.close().await;
}

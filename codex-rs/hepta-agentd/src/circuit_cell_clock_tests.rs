use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn single_entry_retains_measured_host_wait_for_original_request_readback() {
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let model = Model::new(/*latency*/ 20, /*lose_response*/ true);
    let calls = model.calls.clone();
    let reads = model.reads.clone();
    let owner = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        model,
        Encoder,
    );
    let mut samples = [20, 21, 41].into_iter();
    assert!(
        runtime
            .execute(admission, request.clone(), || {
                let now = samples.next().expect("three samples before native error");
                CircuitCellTimeV1 {
                    circuit_millis: now,
                    cell_micros: now,
                }
            })
            .is_err()
    );
    let pending = checked(runtime.state_owner().pending_inference(&request.scope))
        .expect("failed response retains original admission");
    assert_eq!(pending.host_queue_age_micros, Some(20));
    let recovery = checked(
        store
            .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 50)
            .await,
    );
    let recovered = checked(runtime.execute(recovery, request, || CircuitCellTimeV1 {
        circuit_millis: 70,
        cell_micros: 70,
    }));
    assert_eq!(recovered.decision.cost.queue_age_micros, 23);
    assert_eq!(recovered.completion.actual_work, 20);
    assert_eq!(
        (calls.load(Ordering::SeqCst), reads.load(Ordering::SeqCst)),
        (1, 1)
    );
    assert_eq!(
        checked(
            runtime
                .state_owner()
                .pending_inference(&recovered.decision.scope)
        ),
        None
    );
    store.close().await;
}

#[tokio::test]
async fn either_clock_regression_after_admission_prevents_contact_and_retains_hold() {
    for circuit_regression in [true, false] {
        let (definition, bindings) = configuration();
        let (_directory, store, dispatch) = create_run(&definition).await;
        let request = request(&dispatch);
        let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
        let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
        let calls = model.calls.clone();
        let reads = model.reads.clone();
        let owner = native_owner(&bindings);
        let mut runtime = AgentdCircuitCellOwnerV1::new(
            checked(CircuitCellRegistryV1::new(definition, bindings)),
            owner,
            model,
            Encoder,
        );
        let before = checked(runtime.state_owner().snapshot(&request.scope));
        let mut phase = 0;
        let rejected = runtime.execute(admission, request.clone(), || {
            let regressed = phase == 2;
            let now = CircuitCellTimeV1 {
                circuit_millis: if regressed && circuit_regression {
                    20
                } else {
                    20 + phase
                },
                cell_micros: if regressed && !circuit_regression {
                    20
                } else {
                    20 + phase
                },
            };
            phase += 1;
            now
        });
        assert_eq!(rejected, Err(CircuitCellErrorV1::ReconciliationRequired));
        let pending = checked(runtime.state_owner().pending_inference(&request.scope))
            .expect("original durable admission");
        assert_eq!(pending.host_queue_age_micros, None);
        assert_eq!(
            checked(runtime.state_owner().snapshot(&request.scope)),
            before
        );
        let recovery = checked(
            store
                .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 30)
                .await,
        );
        assert_eq!(
            runtime.execute(recovery, request, || CircuitCellTimeV1 {
                circuit_millis: 40,
                cell_micros: 40,
            }),
            Err(CircuitCellErrorV1::Cell(
                CellExecutionError::UnmeasuredQueueCost
            ))
        );
        assert_eq!(
            (calls.load(Ordering::SeqCst), reads.load(Ordering::SeqCst)),
            (0, 0)
        );
        store.close().await;
    }
}

use pretty_assertions::assert_eq;

use super::*;

struct DelayingOwners<'a> {
    current: CellRepresentationUseV1,
    calls: Cell<usize>,
    now: &'a Cell<u64>,
}

impl CircuitCellRepresentationResolverV1 for DelayingOwners<'_> {
    fn current_use(
        &self,
        scope: &CellScopeV1,
    ) -> Result<CellRepresentationUseV1, CellExecutionError> {
        assert_eq!(scope, &self.current.scope);
        let call = self.calls.get() + 1;
        self.calls.set(call);
        if call == 3 {
            // The post-admission owner read consumes the remaining Circuit
            // lease while the separately checked Cell clock remains valid.
            self.now.set(510);
        }
        Ok(self.current.clone())
    }
}

#[tokio::test]
async fn represented_dispatch_checks_its_circuit_clock_after_the_final_owner_resolution() {
    let (backend, projected, current) = projected_input();
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch, request) = projected_run(&definition, &projected).await;
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let model = Model::new(20, false);
    let calls = model.calls.clone();
    let state = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)), state, model, Encoder,
    );
    let now = Cell::new(20);
    let resolver = DelayingOwners { current, calls: Cell::new(0), now: &now };
    assert!(matches!(runtime.execute_representation(admission, request.clone(),
        CircuitCellRepresentationUseV1 { backend: &backend, input: &projected, resolver: &resolver },
        || CircuitCellTimeV1 { circuit_millis: now.get(), cell_micros: 20 }),
        Err(CircuitCellErrorV1::Cell(CellExecutionError::Backend(NeuronModelError::Rejected)))));
    assert_eq!(resolver.calls.get(), 3);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert!(checked(runtime.state_owner().pending_inference(&request.scope)).is_some());
    assert_eq!(checked(store.bounded_circuit_run("run-1").await).expect("original run")
        .budget().reserved(), 2_000);
    store.close().await;
}

#[tokio::test]
async fn represented_outer_guard_refuses_rollback_after_the_typed_contact_clock() {
    for final_sample in [
        CircuitCellTimeV1 { circuit_millis: 24, cell_micros: 14 },
        CircuitCellTimeV1 { circuit_millis: 26, cell_micros: 14 },
        CircuitCellTimeV1 { circuit_millis: 24, cell_micros: 16 },
    ] {
        let (backend, projected, current) = projected_input();
        let (definition, bindings) = configuration();
        let (_directory, store, dispatch, request) = projected_run(&definition, &projected).await;
        let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
        let model = Model::new(20, false);
        let calls = model.calls.clone();
        let state = native_owner(&bindings);
        let mut runtime = AgentdCircuitCellOwnerV1::new(
            checked(CircuitCellRegistryV1::new(definition, bindings)), state, model, Encoder,
        );
        let resolver = CurrentOwners { current, calls: Cell::new(0), stale_on: usize::MAX };
        // Cell clock: initial 10 -> before-infer 11 -> typed admission 12 ->
        // typed contact 15 -> outer guard 14. Also isolate each clock's rollback.
        let mut samples = [
            CircuitCellTimeV1 { circuit_millis: 20, cell_micros: 10 },
            CircuitCellTimeV1 { circuit_millis: 21, cell_micros: 11 },
            CircuitCellTimeV1 { circuit_millis: 22, cell_micros: 12 },
            CircuitCellTimeV1 { circuit_millis: 25, cell_micros: 15 },
            final_sample,
        ].into_iter();
        let mut clock_calls = 0;
        assert!(matches!(runtime.execute_representation(admission, request.clone(),
            CircuitCellRepresentationUseV1 { backend: &backend, input: &projected, resolver: &resolver },
            || {
                clock_calls += 1;
                samples.next().unwrap_or(CircuitCellTimeV1 { circuit_millis: 30, cell_micros: 20 })
            }),
            Err(CircuitCellErrorV1::Cell(CellExecutionError::Backend(NeuronModelError::Rejected)))));
        assert_eq!(clock_calls, 5);
        assert_eq!(resolver.calls.get(), 3);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        let pending = checked(runtime.state_owner().pending_inference(&request.scope))
            .expect("original admission remains pending");
        assert_eq!(pending.operation_id, request.operation_id);
        assert_eq!(pending.admitted_at_micros, 12);
        assert_eq!(checked(store.bounded_circuit_run("run-1").await).expect("original run")
            .budget().reserved(), 2_000);
        store.close().await;
    }
}

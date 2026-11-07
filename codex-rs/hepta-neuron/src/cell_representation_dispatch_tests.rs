use pretty_assertions::assert_eq;
use std::cell::Cell;

use super::*;

fn fixture() -> (
    RegisteredCellBackendV1,
    CellNativeRepresentationInputV1,
    CellRepresentationUseV1,
) {
    let backend = native_backend(2);
    let source = f32_source(&[1.0, 0.5, 0.0]);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1]));
    let negotiation = negotiated(&backend, &source, &selection);
    let current = current(&negotiation.producer, &negotiation.consumer);
    let representation = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &source,
        &current,
        &selection,
    ));
    (backend, representation, current)
}

struct ChangingOwners {
    current: CellRepresentationUseV1,
    calls: Cell<usize>,
    stale_on: usize,
}

impl CellRepresentationResolverV1 for ChangingOwners {
    fn current_use(
        &self,
        scope: &CellScopeV1,
    ) -> Result<CellRepresentationUseV1, CellExecutionError> {
        assert_eq!(scope, &self.current.scope);
        let call = self.calls.get() + 1;
        self.calls.set(call);
        let mut current = self.current.clone();
        if call >= self.stale_on {
            current.consumer.contract_digest = d("qualification-withdrawn");
        }
        Ok(current)
    }
}

#[test]
fn ordinary_entry_inference_and_batch_cannot_dispatch_a_stale_sealed_representation() {
    let (backend, representation, mut current) = fixture();
    let mut state = owner(&backend);
    let input = request(&representation);
    // Two preparations are still unadmitted. Neither is a permission to ignore
    // later endpoint changes or to use a dispatch path with no live resolver.
    let first = ready(checked(backend.enter_representation(
        &state,
        &representation,
        &current,
        input.clone(),
        10,
    )));
    let second = ready(checked(backend.enter_representation(
        &state,
        &representation,
        &current,
        input.clone(),
        10,
    )));
    current.producer.generation = checked(Generation::new(3));
    assert_eq!(
        representation.validate_current_use(&backend, &current),
        Err(CellExecutionError::StaleSource)
    );
    assert!(matches!(
        prepare_cell_step(
            &backend.registration().definition,
            &state,
            &representation,
            input.clone(),
            10
        ),
        Err(CellExecutionError::EncodingMismatch)
    ));
    assert!(matches!(
        enter_cell_step(
            &backend.registration().definition,
            &state,
            &representation,
            input.clone(),
            10
        ),
        Err(CellExecutionError::EncodingMismatch)
    ));
    // A permissive custom encoder also cannot route the reserved protocol into
    // the generic pipeline. The check is not an encoder convention.
    assert!(matches!(
        prepare_cell_step(
            &backend.registration().definition,
            &state,
            &crate::cell_test_support::Encoder,
            input.clone(),
            10
        ),
        Err(CellExecutionError::EncodingMismatch)
    ));
    let mut model = RecordedControl::new();
    assert!(matches!(
        infer_cell(first, &mut state, &mut model, 11),
        Err(CellExecutionError::EncodingMismatch)
    ));
    let mut queue = checked(CellBatchQueueV1::new(2, 1));
    assert_eq!(
        queue.enqueue(second, 11),
        Err(CellExecutionError::EncodingMismatch)
    );
    assert_eq!(queue.observation().queued, 0);
    assert_eq!(queue.observation().retained_payload_bytes, 0);
    assert_eq!(checked(state.pending_inference(&input.scope)), None);
    assert_eq!(model.executions, 0);
}

#[test]
fn typed_inference_checks_current_owners_before_and_after_durable_admission() {
    for stale_on in [1, 2, usize::MAX] {
        let (backend, representation, current) = fixture();
        let mut state = owner(&backend);
        let input = request(&representation);
        let prepared = ready(checked(backend.enter_representation(
            &state,
            &representation,
            &current,
            input.clone(),
            10,
        )));
        let resolver = ChangingOwners {
            current,
            calls: Cell::new(0),
            stale_on,
        };
        let mut model = RecordedControl::new();
        let result = backend.infer_representation(
            &mut state,
            &representation,
            prepared,
            &resolver,
            &mut model,
            || 11,
        );
        if stale_on == usize::MAX {
            let receipt = checked(commit_cell_step(
                &mut state,
                checked(decide_cell(checked(result), 12)),
                13,
            ));
            assert_eq!(
                receipt.authority,
                codex_hepta_types::AuthorityPosture::DENY_ALL
            );
            assert_eq!((model.executions, resolver.calls.get()), (1, 2));
            assert_eq!(checked(state.pending_inference(&input.scope)), None);
        } else {
            if stale_on == 1 {
                assert!(matches!(
                    result,
                    Err(CellExecutionError::IncompatibleBundle)
                ));
            } else {
                assert!(matches!(
                    result,
                    Err(CellExecutionError::Backend(NeuronModelError::Rejected))
                ));
            }
            assert_eq!((model.executions, resolver.calls.get()), (0, stale_on));
            let pending = checked(state.pending_inference(&input.scope));
            assert_eq!(pending.is_some(), stale_on == 2);
            if stale_on == 2 {
                assert!(matches!(
                    backend.recover_representation(
                        &state,
                        &representation,
                        input.clone(),
                        &mut model,
                        12,
                    ),
                    Err(CellExecutionError::InferencePending)
                ));
                assert_eq!(checked(state.pending_inference(&input.scope)), pending);
                assert_eq!(
                    (model.executions, model.reads, resolver.calls.get()),
                    (0, 1, 2)
                );
            }
        }
    }
}

#[test]
fn typed_inference_refuses_a_plain_preparation_without_sealed_context() {
    let (backend, representation, current) = fixture();
    let mut state = owner(&backend);
    let input = input("run1");
    let prepared = checked(prepare_cell_step(
        &backend.registration().definition,
        &state,
        &crate::cell_test_support::Encoder,
        input.clone(),
        10,
    ));
    let resolver = ChangingOwners {
        current,
        calls: Cell::new(0),
        stale_on: usize::MAX,
    };
    let mut model = RecordedControl::new();
    assert!(matches!(
        backend.infer_representation(
            &mut state,
            &representation,
            prepared,
            &resolver,
            &mut model,
            || 11,
        ),
        Err(CellExecutionError::EncodingMismatch)
    ));
    assert_eq!((model.executions, resolver.calls.get()), (0, 0));
    assert_eq!(checked(state.pending_inference(&input.scope)), None);
}

#[path = "cell_representation_clock_tests.rs"]
mod clock;

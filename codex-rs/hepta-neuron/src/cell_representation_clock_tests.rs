use std::cell::Cell;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;

struct DelayingResolver<'a> {
    current: &'a CellRepresentationUseV1,
    calls: Cell<usize>,
    now: &'a Cell<u64>,
    delay_on: usize,
    changed_time: u64,
}

impl CellRepresentationResolverV1 for DelayingResolver<'_> {
    fn current_use(
        &self,
        scope: &CellScopeV1,
    ) -> Result<CellRepresentationUseV1, CellExecutionError> {
        assert_eq!(scope, &self.current.scope);
        let call = self.calls.get() + 1;
        self.calls.set(call);
        if call == self.delay_on {
            self.now.set(self.changed_time);
        }
        Ok(self.current.clone())
    }
}

#[test]
fn typed_cell_clock_is_read_after_owner_resolution_and_bounds_later_decision_time() {
    for (delay_on, changed_time) in [(1, 100), (2, 100), (2, 10), (2, 12)] {
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
        let now = Cell::new(11);
        let resolver = DelayingResolver {
            current: &current,
            calls: Cell::new(0),
            now: &now,
            delay_on,
            changed_time,
        };
        let mut model = RecordedControl::new();
        let result = backend.infer_representation(
            &mut state,
            &representation,
            prepared,
            &resolver,
            &mut model,
            || now.get(),
        );
        if changed_time == 12 {
            // The result cannot be backdated before the actual contact sample.
            assert!(matches!(
                decide_cell(checked(result), 11),
                Err(CellExecutionError::DeadlineExceeded)
            ));
            assert_eq!(model.executions, 1);
        } else {
            if delay_on == 1 {
                assert!(matches!(result, Err(CellExecutionError::DeadlineExceeded)));
            } else {
                assert!(matches!(
                    result,
                    Err(CellExecutionError::Backend(NeuronModelError::Rejected))
                ));
            }
            assert_eq!(model.executions, 0);
        }
        assert_eq!(resolver.calls.get(), delay_on);
        let pending = checked(state.pending_inference(&input.scope));
        assert_eq!(pending.is_some(), delay_on == 2);
        if let Some(pending) = pending {
            assert_eq!(pending.operation_id, input.operation_id);
            assert_eq!(pending.admitted_at_micros, 11);
        }
    }
}

struct AdmissionClockOwner<'a> {
    state: CellPartitionOwnerV1,
    now: &'a Cell<u64>,
}

impl CellStateOwnerV1 for AdmissionClockOwner<'_> {
    fn admit_inference(
        &mut self,
        admission: CellInferenceAdmissionV1,
    ) -> Result<(), CellExecutionError> {
        self.state.admit_inference(admission)?;
        // Simulate elapsed time inside the durable owner call, after its write.
        self.now.set(100);
        Ok(())
    }

    fn pending_inference(
        &self,
        scope: &CellScopeV1,
    ) -> Result<Option<CellInferenceAdmissionV1>, CellExecutionError> {
        self.state.pending_inference(scope)
    }

    fn lookup(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        semantic_request_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.state
            .lookup(scope, operation_id, semantic_request_digest)
    }

    fn snapshot(&self, scope: &CellScopeV1) -> Result<CellOwnerSnapshotV1, CellExecutionError> {
        self.state.snapshot(scope)
    }

    fn commit(
        &mut self,
        proposal: CellStateProposalV1,
        now_micros: u64,
    ) -> Result<CellDecisionReceiptV1, CellExecutionError> {
        self.state.commit(proposal, now_micros)
    }

    fn reconcile(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        operation_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.state.reconcile(scope, operation_id, operation_digest)
    }
}

#[test]
fn typed_cell_clock_refuses_contact_after_slow_admission_and_keeps_the_original_pending() {
    let (backend, representation, current) = fixture();
    let now = Cell::new(11);
    let mut state = AdmissionClockOwner {
        state: owner(&backend),
        now: &now,
    };
    let input = request(&representation);
    let prepared = ready(checked(backend.enter_representation(
        &state,
        &representation,
        &current,
        input.clone(),
        10,
    )));
    let mut model = RecordedControl::new();
    assert!(matches!(
        backend.infer_representation(
            &mut state,
            &representation,
            prepared,
            &CurrentRepresentationOwners(&current),
            &mut model,
            || now.get(),
        ),
        Err(CellExecutionError::Backend(NeuronModelError::Rejected))
    ));
    let pending = checked(state.pending_inference(&input.scope)).expect("original admission");
    assert_eq!(pending.admitted_at_micros, 11);
    assert_eq!(pending.operation_id, input.operation_id);
    assert_eq!(model.executions, 0);
    assert!(matches!(
        backend.recover_representation(&state, &representation, input.clone(), &mut model, 101,),
        Err(CellExecutionError::InferencePending)
    ));
    assert_eq!(
        checked(state.pending_inference(&input.scope)),
        Some(pending)
    );
    assert_eq!((model.executions, model.reads), (0, 1));
}

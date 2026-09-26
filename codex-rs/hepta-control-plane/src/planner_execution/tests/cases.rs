#[test]
fn granted_request_reaches_executor_and_persists_complete_evidence_chain() {
    let root = TempRoot::new("success");
    let (receipt, requests) = request_set(1);
    let mut store = open_store_with_decision(&root, &receipt);
    let authority = GrantAuthority::default();
    let executor = FixtureExecutor::new(vec![TerminalDispositionV1::Succeeded]);
    let reconciler = FixtureReconciler {
        calls: 0,
        disposition: ReconciliationDispositionV1::Succeeded,
    };
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        authority,
        executor,
        reconciler,
    );
    let batch = must(coordinator.execute_request_set(&requests, 1_200));
    assert!(batch.complete);
    assert!(!batch.partial_execution);
    assert!(matches!(
        batch.outcomes.as_slice(),
        [PlannerRequestOutcomeV1::Succeeded { .. }]
    ));
    let (authority, executor, _) = coordinator.into_ports();
    assert_eq!(authority.calls, 1);
    assert_eq!(executor.calls, 1);
    assert_eq!(must(store.entries()).len(), 1);
    assert!(!must(store.backup_bytes()).is_empty());
}

#[test]
fn denial_is_terminal_and_executor_is_never_called() {
    let root = TempRoot::new("denied");
    let (receipt, requests) = request_set(1);
    let mut store = open_store_with_decision(&root, &receipt);
    let executor = FixtureExecutor::new(vec![TerminalDispositionV1::Succeeded]);
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        DenyAuthority,
        executor,
        FixtureReconciler {
            calls: 0,
            disposition: ReconciliationDispositionV1::Failed,
        },
    );
    let batch = must(coordinator.execute_request_set(&requests, 1_200));
    assert!(!batch.complete);
    assert!(matches!(
        batch.outcomes.as_slice(),
        [PlannerRequestOutcomeV1::Denied { .. }]
    ));
    let (_, executor, _) = coordinator.into_ports();
    assert_eq!(executor.calls, 0);
}

#[test]
fn final_payload_drift_is_rejected_before_executor_dispatch() {
    let root = TempRoot::new("payload-drift");
    let (receipt, requests) = request_set(1);
    let mut store = open_store_with_decision(&root, &receipt);
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        GrantAuthority {
            calls: 0,
            tamper_payload: true,
        },
        FixtureExecutor::new(vec![TerminalDispositionV1::Succeeded]),
        FixtureReconciler {
            calls: 0,
            disposition: ReconciliationDispositionV1::Failed,
        },
    );
    assert_eq!(
        coordinator
            .execute_request_set(&requests, 1_200)
            .expect_err("payload drift must fail closed"),
        PlannerExecutionError::GrantBindingMismatch
    );
    let (_, executor, _) = coordinator.into_ports();
    assert_eq!(executor.calls, 0);
}

#[test]
fn indeterminate_effect_requires_signed_reconciliation() {
    let root = TempRoot::new("reconcile");
    let (receipt, requests) = request_set(1);
    let mut store = open_store_with_decision(&root, &receipt);
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        GrantAuthority::default(),
        FixtureExecutor::new(vec![TerminalDispositionV1::Indeterminate]),
        FixtureReconciler {
            calls: 0,
            disposition: ReconciliationDispositionV1::Succeeded,
        },
    );
    let batch = must(coordinator.execute_request_set(&requests, 1_200));
    let pending = match batch.outcomes.as_slice() {
        [PlannerRequestOutcomeV1::Indeterminate(value)] => value.clone(),
        other => panic!("unexpected outcomes: {other:?}"),
    };
    let reconciled = must(coordinator.reconcile(&pending, 1_300));
    assert_eq!(
        reconciled.disposition,
        ReconciliationDispositionV1::Succeeded
    );
    let (_, _, reconciler) = coordinator.into_ports();
    assert_eq!(reconciler.calls, 1);
    assert!(must(store.body(reconciled.reconciliation_digest)).is_some());
}

#[test]
fn batch_stops_after_indeterminate_and_reports_prior_partial_execution() {
    let root = TempRoot::new("partial");
    let (receipt, requests) = request_set(2);
    let mut store = open_store_with_decision(&root, &receipt);
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        GrantAuthority::default(),
        FixtureExecutor::new(vec![
            TerminalDispositionV1::Succeeded,
            TerminalDispositionV1::Indeterminate,
        ]),
        FixtureReconciler {
            calls: 0,
            disposition: ReconciliationDispositionV1::StillIndeterminate,
        },
    );
    let batch = must(coordinator.execute_request_set(&requests, 1_200));
    assert!(!batch.complete);
    assert!(batch.partial_execution);
    assert_eq!(batch.outcomes.len(), 2);
}

#[test]
fn authority_indeterminate_never_dispatches_effect() {
    let root = TempRoot::new("authority-indeterminate");
    let (receipt, requests) = request_set(1);
    let mut store = open_store_with_decision(&root, &receipt);
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        IndeterminateAuthority,
        FixtureExecutor::new(vec![TerminalDispositionV1::Succeeded]),
        FixtureReconciler {
            calls: 0,
            disposition: ReconciliationDispositionV1::Failed,
        },
    );
    let batch = must(coordinator.execute_request_set(&requests, 1_200));
    assert!(matches!(
        batch.outcomes.as_slice(),
        [PlannerRequestOutcomeV1::Indeterminate(PlannerIndeterminateV1 {
            stage: IndeterminateStageV1::Authority,
            ..
        })]
    ));
    let (_, executor, _) = coordinator.into_ports();
    assert_eq!(executor.calls, 0);
}

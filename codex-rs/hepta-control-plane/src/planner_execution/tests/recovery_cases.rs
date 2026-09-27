#[test]
fn successful_request_cannot_be_dispatched_twice_after_reopen() {
    let root = TempRoot::new("no-redispatch");
    let (receipt, requests) = request_set(1);
    {
        let mut store = open_store_with_decision(&root, &receipt);
        let mut coordinator = PlannerExecutionCoordinatorV1::new(
            &mut store,
            GrantAuthority::default(),
            FixtureExecutor::new(vec![TerminalDispositionV1::Succeeded]),
            FixtureReconciler { calls: 0, disposition: ReconciliationDispositionV1::Succeeded },
        );
        assert!(must(coordinator.execute_request_set_with_clock(&requests, || Ok(1_200))).complete);
        assert!(matches!(
            coordinator.execute_request_set_with_clock(&requests, || Ok(1_200)),
            Err(PlannerExecutionError::RecoveryRequired { .. })
        ));
        let (authority, executor, _) = coordinator.into_ports();
        assert_eq!((authority.calls, executor.calls), (1, 1));
    }
    let mut store = must(PlannerStoreV1::open(&root.0));
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        GrantAuthority::default(),
        FixtureExecutor::new(vec![]),
        FixtureReconciler { calls: 0, disposition: ReconciliationDispositionV1::Succeeded },
    );
    let discovered = must(coordinator.discover_reconciliation_candidates());
    assert_eq!(discovered.len(), 1);
    assert!(matches!(
        coordinator.execute_request_set_with_clock(&requests, || Ok(1_200)),
        Err(PlannerExecutionError::RecoveryRequired { .. })
    ));
    let (authority, executor, _) = coordinator.into_ports();
    assert_eq!((authority.calls, executor.calls), (0, 0));
}

struct LostExecutor;

impl PlannerEffectExecutorV1 for LostExecutor {
    fn execute(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &VerifiedExecutionGrantV1,
        _now_micros: u64,
    ) -> Result<SignedTerminalObservationV1, String> {
        Err("acknowledgement lost after dispatch".to_string())
    }
}

#[test]
fn transport_failure_is_indeterminate_and_can_be_reconciled_after_expiry() {
    let root = TempRoot::new("lost-ack");
    let (receipt, requests) = request_set(1);
    let mut store = open_store_with_decision(&root, &receipt);
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        GrantAuthority::default(),
        LostExecutor,
        FixtureReconciler { calls: 0, disposition: ReconciliationDispositionV1::Succeeded },
    );
    let batch = must(coordinator.execute_request_set_with_clock(&requests, || Ok(1_200)));
    let [PlannerRequestOutcomeV1::Indeterminate(pending)] = batch.outcomes.as_slice() else {
        panic!("lost acknowledgement must not become failure/success");
    };
    assert!(batch.partial_execution);
    let mut changed = pending.clone();
    changed.final_payload_digest = digest("different-payload");
    assert_eq!(
        coordinator.reconcile(&changed, pending.expires_at_micros + 1),
        Err(PlannerExecutionError::ReconciliationBindingMismatch)
    );
    let terminal = must(coordinator.reconcile(pending, pending.expires_at_micros + 1));
    assert_eq!(terminal.disposition, ReconciliationDispositionV1::Succeeded);
    let (_, _, reconciler) = coordinator.into_ports();
    assert_eq!(reconciler.calls, 1, "forged pending must not reach the port");
}

#[test]
fn current_clock_is_checked_again_after_durable_grant() {
    let root = TempRoot::new("expiry-before-execution");
    let (receipt, requests) = request_set(1);
    let expiry = requests.requests()[0].expires_at_micros;
    let mut store = open_store_with_decision(&root, &receipt);
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        GrantAuthority::default(),
        FixtureExecutor::new(vec![]),
        FixtureReconciler { calls: 0, disposition: ReconciliationDispositionV1::Failed },
    );
    let mut times = [1_200, 1_200, 1_200, 1_200, expiry].into_iter();
    assert_eq!(
        coordinator.execute_request_set_with_clock(&requests, || Ok(times.next().unwrap_or(expiry))),
        Err(PlannerExecutionError::GrantExpired)
    );
    let (authority, executor, _) = coordinator.into_ports();
    assert_eq!(authority.calls, 1);
    assert_eq!(executor.calls, 0);
}

#[test]
fn clock_reversal_rejects_before_authority() {
    let root = TempRoot::new("clock-reversal");
    let (receipt, requests) = request_set(1);
    let mut store = open_store_with_decision(&root, &receipt);
    let mut coordinator = PlannerExecutionCoordinatorV1::new(
        &mut store,
        GrantAuthority::default(),
        FixtureExecutor::new(vec![]),
        FixtureReconciler { calls: 0, disposition: ReconciliationDispositionV1::Failed },
    );
    let mut times = [1_200, 1_199].into_iter();
    assert_eq!(
        coordinator.execute_request_set_with_clock(&requests, || Ok(times.next().unwrap_or(1_199))),
        Err(PlannerExecutionError::RequestExpired)
    );
    let (authority, executor, _) = coordinator.into_ports();
    assert_eq!((authority.calls, executor.calls), (0, 0));
}

#[test]
fn recovery_request_decoder_rejects_every_truncation_and_trailing_bytes() {
    let (_, requests) = request_set(1);
    let request = &requests.requests()[0];
    let bytes = canonical_grant_request_body(request);
    let reopened = must(decode_grant_request_body(&bytes));
    assert_eq!(grant_request_digest(&reopened), grant_request_digest(request));
    for offset in 0..bytes.len() {
        assert!(decode_grant_request_body(&bytes[..offset]).is_err());
    }
    let mut trailing = bytes;
    trailing.push(0);
    assert!(decode_grant_request_body(&trailing).is_err());
}

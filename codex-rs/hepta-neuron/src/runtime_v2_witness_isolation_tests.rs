use std::sync::atomic::AtomicBool;

#[derive(Clone, Default)]
struct IntermittentWitness {
    current: Arc<Mutex<Option<JournalAnchor>>>,
    current_unavailable: Arc<AtomicBool>,
    compare_and_swap_unavailable: Arc<AtomicBool>,
}

impl IntermittentWitness {
    fn set_current_unavailable(&self, unavailable: bool) {
        self.current_unavailable
            .store(unavailable, Ordering::SeqCst);
    }

    fn set_compare_and_swap_unavailable(&self, unavailable: bool) {
        self.compare_and_swap_unavailable
            .store(unavailable, Ordering::SeqCst);
    }
}

impl AnchorWitnessStore for IntermittentWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        if self.current_unavailable.load(Ordering::SeqCst) {
            return Err(WitnessStoreError::Unavailable);
        }
        self.current
            .lock()
            .map(|value| *value)
            .map_err(|_| WitnessStoreError::Unavailable)
    }

    fn admit_new_anchor(&self, expected: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
        if self.current()? == expected {
            Ok(())
        } else {
            Err(WitnessStoreError::Conflict)
        }
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if self.current_unavailable.load(Ordering::SeqCst)
            || self
                .compare_and_swap_unavailable
                .load(Ordering::SeqCst)
        {
            return Err(WitnessStoreError::Unavailable);
        }
        let mut current = self
            .current
            .lock()
            .map_err(|_| WitnessStoreError::Unavailable)?;
        if *current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        *current = Some(next);
        Ok(())
    }
}

fn bootstrap_with_intermittent_witness(
    fixture: &Fixture,
    witness: IntermittentWitness,
) -> NeuronRuntimeV2<IntermittentWitness> {
    let native = native_config();
    let config = runtime_config(&native);
    let body = body_bundle(native.generation);
    let (store_context, index_context) = contexts(&native, &config, &body);
    checked(NeuronRuntimeV2::bootstrap(
        &fixture.store(),
        &fixture.index(),
        native,
        scope(),
        config,
        body,
        store_context,
        index_context,
        witness,
    ))
}

#[test]
fn witness_publication_outage_does_not_hide_committed_truth_or_guarded_use() {
    let fixture = Fixture::new();
    let witness = IntermittentWitness::default();
    let mut runtime = bootstrap_with_intermittent_witness(&fixture, witness.clone());
    let request = input();
    let execute_calls = Arc::new(AtomicUsize::new(0));
    let mut model = ValidModel {
        execute_calls: Arc::clone(&execute_calls),
    };

    witness.set_compare_and_swap_unavailable(true);
    assert!(matches!(
        runtime.tick_guarded(&mut model, request.clone(), &mut Allow),
        Err(NeuronRuntimeV2Error::Witness(
            WitnessStoreError::Unavailable
        ))
    ));
    assert_eq!(execute_calls.load(Ordering::SeqCst), 1);

    match checked(runtime.query_input_operation(&request)) {
        NeuronOperationStatusV2::Committed {
            witness_acknowledged,
            ..
        } => assert!(!witness_acknowledged),
        status => panic!("expected committed local truth, got {status:?}"),
    }
    assert!(checked(runtime.query_result_guarded(&request, &mut Allow)).is_some());
    assert!(matches!(
        runtime.reconcile(),
        Err(NeuronRuntimeV2Error::Witness(
            WitnessStoreError::Unavailable
        ))
    ));
}

#[test]
fn provider_recovery_remains_reachable_during_witness_read_outage() {
    let fixture = Fixture::new();
    let witness = IntermittentWitness::default();
    let mut runtime = bootstrap_with_intermittent_witness(&fixture, witness.clone());
    let request = input();
    let input_digest = checked(request.semantic_digest());
    let key = NeuronOperationKeyV2 {
        tick_id: request.tick_id.clone(),
        input_semantic_digest: input_digest,
    };
    checked(runtime.index.prepare(key.clone(), None));
    checked(runtime.index.mark_dispatched(&key));

    let execute_calls = Arc::new(AtomicUsize::new(0));
    let reconcile_calls = Arc::new(AtomicUsize::new(0));
    let mut model = RecoverableModel {
        execute_calls: Arc::clone(&execute_calls),
        reconcile_calls: Arc::clone(&reconcile_calls),
    };
    witness.set_current_unavailable(true);

    assert!(matches!(
        runtime.recover_operation(&mut model, &request),
        Err(NeuronRuntimeV2Error::Witness(
            WitnessStoreError::Unavailable
        ))
    ));
    assert_eq!(execute_calls.load(Ordering::SeqCst), 0);
    assert_eq!(reconcile_calls.load(Ordering::SeqCst), 1);
    match checked(runtime.query_input_operation(&request)) {
        NeuronOperationStatusV2::Committed {
            witness_acknowledged,
            ..
        } => assert!(!witness_acknowledged),
        status => panic!("expected recovered committed truth, got {status:?}"),
    }
}

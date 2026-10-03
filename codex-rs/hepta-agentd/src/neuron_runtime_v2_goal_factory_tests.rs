use super::*;
use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;

struct ScopeFactory {
    handles: Mutex<BTreeMap<Digest32, AgentdNeuronHandleV2>>,
    calls: AtomicUsize,
}
impl AgentdNeuronGoalScopeFactoryV3 for ScopeFactory {
    fn open_goal_scope(
        &self,
        identity: &crate::AgentdIdentity,
        record: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        invocation: &crate::AgentdIntelligenceInvocationV1,
        stage: &CanonicalPortInputV1,
        expected: &AgentdNeuronGoalScopeV3,
    ) -> Result<AgentdNeuronHandleV2, crate::AgentdError> {
        invocation.validate(identity, record)?;
        assert_eq!(stage.objective_digest, record.snapshot.objective_digest);
        assert_eq!(
            expected.identity.model_generation,
            invocation.request.snapshot.body_generation().get()
        );
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.handles
            .lock()
            .expect("factory")
            .remove(&stage.objective_digest)
            .ok_or_else(|| crate::AgentdError::Invalid("fixture did not supply this scope".into()))
    }
}

fn invocation(
    mut value: crate::intelligence_product::tests::Fixture,
    host: &Arc<AgentdNeuronRuntimeV2Host>,
    identity: crate::AgentdIdentity,
    body: Digest32,
) -> (AgentdDeferredNeuronInvocationV2, CanonicalPortInputV1) {
    let mut record = crate::canonical_abstain_provider::tests::durable_record(&value);
    record.runtime_body_digest = body;
    value.inputs.run_identity = Some(
        crate::AgentdIntelligenceRunIdentityV1::from_run_start(&identity, &record)
            .expect("durable RunStart"),
    );
    let utility = evaluate_candidates_with_policy(
        value.inputs.utility_contributions.clone(),
        value.inputs.utility_profile.clone(),
        value.inputs.utility_scalarization.clone(),
        value.inputs.utility_policy.clone(),
    )
    .expect("actual NDU");
    let stage = CanonicalPortInputV1 {
        run_id: value.request.run_id.clone(),
        snapshot_digest: value.request.snapshot.digest(),
        objective_digest: value.request.snapshot.objective_digest(),
        candidate_set_digest: codex_hepta_agent_components::intelligence::build_legal_candidates(
            value.request.legal_candidates.clone(),
        )
        .expect("candidates")
        .candidate_set_digest,
        predecessor_digest: utility.evaluation_digest_v2,
        budget_micros: 30_000_000,
        stage: CanonicalStageV1::NeuralSignalCollected,
    };
    let deferred = host
        .defer(
            identity,
            record,
            crate::AgentdIntelligenceInvocationV1 {
                request: value.request,
                inputs: value.inputs,
            },
        )
        .expect("defer");
    (deferred, stage)
}

#[test]
fn sole_product_host_rolls_two_compiled_goals_without_changing_the_model_generation() {
    let one = crate::intelligence_product::tests::fixture_for_request("goal.one");
    let two = crate::intelligence_product::tests::fixture_for_request("goal.two");
    assert_ne!(
        one.request.snapshot.objective_digest(),
        two.request.snapshot.objective_digest()
    );
    let generation = one.request.snapshot.body_generation().get();
    let directory = tempfile::tempdir().expect("control");
    let identity =
        crate::canonical_abstain_provider::tests::identity(directory.path(), generation - 1);
    let subject = StableId::new(identity.agent_id.as_str()).expect("subject");
    let (old, training_material) =
        lock_metrics_tests::parameter_checkpoint_fixture_for_subject_and_objective(
            generation,
            subject.clone(),
            Digest32::of_bytes(b"installed historical goal"),
        );
    let (first, first_material) =
        lock_metrics_tests::parameter_checkpoint_fixture_for_subject_and_objective(
            generation,
            subject.clone(),
            one.request.snapshot.objective_digest(),
        );
    let (second, second_material) =
        lock_metrics_tests::parameter_checkpoint_fixture_for_subject_and_objective(
            generation,
            subject,
            two.request.snapshot.objective_digest(),
        );
    let first_scope = AgentdNeuronGoalScopeV3::capture(2, &first.handle).expect("first scope");
    let provider = Arc::new(StageProvider {
        template: first.input.clone(),
        calls: AtomicUsize::new(0),
        observed: Mutex::new(None),
        advance: Mutex::new(None),
    });
    let factory = Arc::new(ScopeFactory {
        handles: Mutex::new(BTreeMap::from([
            (
                one.request.snapshot.objective_digest(),
                first.handle.clone(),
            ),
            (
                two.request.snapshot.objective_digest(),
                second.handle.clone(),
            ),
        ])),
        calls: AtomicUsize::new(0),
    });
    let body = old.handle.body_bundle_digest().expect("body");
    let host = AgentdNeuronRuntimeV2Config::new(
        old.handle.clone(),
        directory.path().join("controller.json"),
        provider.clone(),
    )
    .expect("configuration")
    .with_goal_scope_factory_v3(
        AgentdNeuronGoalScopeV3::capture(1, &old.handle).expect("initial scope"),
        factory.clone(),
    )
    .expect("Goal mode")
    .start()
    .expect("sole product host");
    let (run, stage) = invocation(one, &host, identity.clone(), body);
    assert_eq!(provider.calls.load(Ordering::SeqCst), 0);
    let first_receipt = run.execute(&stage, &mut Allow).expect("first actual stage");
    assert_eq!(first_receipt.next_anchor.sequence, 1);
    assert_eq!(
        host.controller
            .goal_scope_state_v3()
            .expect("first state")
            .active_scope,
        first_scope
    );
    assert!(
        host.prepare_parameter_checkpoint_observation(&training_material)
            .is_err(),
        "registered training scope is not rewritten into actual Goal1"
    );
    let first_facts = host
        .parameter_serving_scope_observation()
        .expect("original Goal1 facts");
    assert_eq!(first_facts.3, first_material.scope);
    assert_eq!(first_facts.4, Some(2));
    assert_ne!(
        first_facts.3.objective_digest,
        training_material.scope.objective_digest
    );
    assert_eq!(
        host.prepare_parameter_checkpoint_observation(&first_material)
            .expect("Goal1 checkpoint")
            .0,
        first_receipt.next_anchor
    );
    assert_eq!(
        host.prepare_parameter_checkpoint_observation(&first_material)
            .expect("Goal1 ordinal")
            .2,
        first_facts.4
    );
    let (run, stage) = invocation(two, &host, identity, body);
    let second_receipt = run
        .execute(&stage, &mut Allow)
        .expect("second actual stage");
    assert_eq!(second_receipt.next_anchor.sequence, 1);
    let state = host.controller.goal_scope_state_v3().expect("second state");
    assert_eq!(
        state.active_scope,
        AgentdNeuronGoalScopeV3::capture(3, &second.handle).expect("second scope")
    );
    assert_eq!(state.active_scope.identity.model_generation, generation);
    let before = [
        std::fs::read(&second_material.generation_store).expect("store"),
        std::fs::read(&second_material.runtime_index).expect("index"),
        std::fs::read(&second_material.witness).expect("witness"),
        std::fs::read(directory.path().join("controller.json")).expect("controller"),
    ];
    let second_facts = host
        .parameter_serving_scope_observation()
        .expect("original Goal2 facts");
    assert_eq!(second_facts.3, second_material.scope);
    assert_eq!(second_facts.4, Some(3));
    assert_ne!(
        second_facts.3.objective_digest,
        first_facts.3.objective_digest
    );
    assert!(
        host.prepare_parameter_checkpoint_observation(&training_material)
            .is_err()
    );
    assert!(
        host.prepare_parameter_checkpoint_observation(&first_material)
            .is_err(),
        "retired Goal1 cannot supply current Goal2 eligibility"
    );
    assert_eq!(
        host.prepare_parameter_checkpoint_observation(&second_material)
            .expect("whole Goal2 checkpoint")
            .0,
        second_receipt.next_anchor
    );
    assert_eq!(
        host.prepare_parameter_checkpoint_observation(&second_material)
            .expect("Goal2 ordinal")
            .2,
        second_facts.4
    );
    assert_eq!(
        [
            std::fs::read(&second_material.generation_store).expect("store"),
            std::fs::read(&second_material.runtime_index).expect("index"),
            std::fs::read(&second_material.witness).expect("witness"),
            std::fs::read(directory.path().join("controller.json")).expect("controller")
        ],
        before
    );

    assert_eq!(
        host.controller
            .query_goal_scope_operation_v3(
                &first_scope,
                &first_receipt.key.tick_id,
                first_receipt.key.input_semantic_digest
            )
            .expect("old exact receipt"),
        NeuronOperationStatusV2::Committed {
            commit: Box::new(first_receipt),
            witness_acknowledged: true
        }
    );
    assert!(
        first
            .handle
            .prepare(first.input.tick_id.clone(), body, first.input.clone())
            .is_err()
    );
    assert_eq!(factory.calls.load(Ordering::SeqCst), 2);
    assert_eq!(provider.calls.load(Ordering::SeqCst), 2);
    assert_eq!(old.calls.load(Ordering::SeqCst), 0);
    assert_eq!(first.calls.load(Ordering::SeqCst), 1);
    assert_eq!(second.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn factory_unavailable_and_wrong_model_leave_the_original_goal_serving_without_encoding() {
    let value = crate::intelligence_product::tests::fixture_for_request("goal.unavailable");
    let objective = value.request.snapshot.objective_digest();
    let generation = value.request.snapshot.body_generation().get();
    let directory = tempfile::tempdir().expect("control");
    let identity =
        crate::canonical_abstain_provider::tests::identity(directory.path(), generation - 1);
    let subject = StableId::new(identity.agent_id.as_str()).expect("subject");
    let old = lock_metrics_tests::runtime_fixture_for_subject_and_objective(
        generation,
        Duration::ZERO,
        Duration::ZERO,
        subject.clone(),
        Digest32::of_bytes(b"installed old scope"),
    );
    let wrong = lock_metrics_tests::runtime_fixture_for_subject_and_objective(
        generation + 1,
        Duration::ZERO,
        Duration::ZERO,
        subject,
        objective,
    );
    let provider = Arc::new(StageProvider {
        template: old.input.clone(),
        calls: AtomicUsize::new(0),
        observed: Mutex::new(None),
        advance: Mutex::new(None),
    });
    let factory = Arc::new(ScopeFactory {
        handles: Mutex::new(BTreeMap::new()),
        calls: AtomicUsize::new(0),
    });
    let body = old.handle.body_bundle_digest().expect("body");
    let host = AgentdNeuronRuntimeV2Config::new(
        old.handle.clone(),
        directory.path().join("controller.json"),
        provider.clone(),
    )
    .expect("configuration")
    .with_goal_scope_factory_v3(
        AgentdNeuronGoalScopeV3::capture(1, &old.handle).expect("scope"),
        factory.clone(),
    )
    .expect("Goal mode")
    .start()
    .expect("host");
    let before = host.controller.goal_scope_state_v3().expect("state");
    let (run, stage) = invocation(value, &host, identity, body);
    assert!(matches!(
        run.execute(&stage, &mut Allow),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::Unavailable
        ))
    ));
    assert_eq!(
        host.controller.goal_scope_state_v3().expect("state"),
        before
    );
    factory
        .handles
        .lock()
        .expect("factory")
        .insert(objective, wrong.handle.clone());
    assert!(matches!(
        run.execute(&stage, &mut Allow),
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::BindingMismatch
        ))
    ));
    assert_eq!(
        host.controller.goal_scope_state_v3().expect("state"),
        before
    );
    assert_eq!(provider.calls.load(Ordering::SeqCst), 0);
    assert_eq!(old.calls.load(Ordering::SeqCst), 0);
    assert_eq!(wrong.calls.load(Ordering::SeqCst), 0);
}

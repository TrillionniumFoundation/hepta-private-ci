use super::*;

fn goal_fixture(ordinal: u64) -> Harness {
    let mut h = Harness::new();
    let goal = digest(&format!("scope-goal-{ordinal}"));
    h.tick.objective_digest = goal;
    h.cell.request.objective_digest = goal;
    h
}

#[test]
fn goal_scope_cold_archive_keeps_model_one_full_receipts_and_bounded_hot_owners() {
    let fixtures = (1..=8).map(goal_fixture).collect::<Vec<_>>();
    let path = fixtures[0].root.path().join("scope-control.json");
    let mut handles = Vec::new();
    let mut scopes = Vec::new();
    let mut commits = Vec::new();
    let first = scope_owner(&fixtures[0], fixtures[0].tick.objective_digest);
    let first_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &first));
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            first_scope.clone(),
            first.clone(),
            std::iter::empty(),
            &path,
        ),
    );
    handles.push(first);
    scopes.push(first_scope);
    checked(controller.start());
    for (index, fixture) in fixtures.iter().enumerate() {
        if index != 0 {
            checked(controller.begin_quiesce());
            checked(controller.seal());
            let next = scope_owner(fixture, fixture.tick.objective_digest);
            scopes.push(checked(AgentdNeuronGoalScopeV3::capture(
                index as u64 + 1,
                &next,
            )));
            checked(controller.reload_goal_scope_v3(&scopes[index - 1], next.clone()));
            handles.push(next);
        }
        commits.push(checked(
            fixture
                .prepared(&controller)
                .execute(&fixture.input(), &mut fixture.allow()),
        ));
        assert_eq!(checked(controller.active_generation()), 1);
        assert!(
            checked(controller.goal_scope_topology_v3())
                .control
                .retained_scopes
                .len()
                <= MAX_RETAINED_NEURON_GENERATION_OWNERS_V2
        );
    }
    let expected = NeuronOperationStatusV2::Committed {
        commit: Box::new(commits[0].clone()),
        witness_acknowledged: true,
    };
    assert_eq!(
        checked(controller.query_goal_scope_operation_v3(
            &scopes[0],
            &fixtures[0].tick.tick_id,
            commits[0].key.input_semantic_digest
        )),
        expected
    );
    let topology = checked(controller.goal_scope_topology_v3());
    assert_eq!(topology.cold.scope_count, 5);
    assert_eq!(topology.control.retained_scopes, scopes[5..7]);
    assert!(matches!(
        handles[0].operational_snapshot(),
        Err(AgentdNeuronControlErrorV2::NotServing)
    ));
    assert!(checked(std::fs::metadata(&path)).len() < 4096);
    checked(controller.shutdown());
    drop(controller);
    drop(handles);
    let live = checked(read_agentd_neuron_live_goal_scope_state_v3(&path));
    assert_eq!(live.retained_scopes, scopes[5..7]);
    let retained = (5..7)
        .map(|index| {
            (
                scopes[index].clone(),
                scope_owner(&fixtures[index], fixtures[index].tick.objective_digest),
            )
        })
        .collect::<Vec<_>>();
    let reopened = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            scopes[7].clone(),
            scope_owner(&fixtures[7], fixtures[7].tick.objective_digest),
            retained,
            &path,
        ),
    );
    checked(reopened.restart_stopped());
    assert_eq!(
        checked(reopened.query_goal_scope_operation_v3(
            &scopes[0],
            &fixtures[0].tick.tick_id,
            commits[0].key.input_semantic_digest
        )),
        expected
    );
    let mut foreign = scopes[0].clone();
    foreign.identity.objective_digest = scopes[1].identity.objective_digest;
    assert!(
        reopened
            .query_goal_scope_operation_v3(
                &foreign,
                &fixtures[0].tick.tick_id,
                commits[0].key.input_semantic_digest
            )
            .is_err()
    );
    for fixture in &fixtures {
        assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
    }
    let blob = path
        .parent()
        .expect("parent")
        .join("neuron-generation-archives/scope-1.archive");
    let mut bytes = checked(std::fs::read(&blob));
    bytes[20] ^= 1;
    checked(std::fs::write(&blob, bytes));
    assert!(
        reopened
            .query_goal_scope_operation_v3(
                &scopes[0],
                &fixtures[0].tick.tick_id,
                commits[0].key.input_semantic_digest
            )
            .is_err()
    );
}

#[test]
fn goal_scope_archive_before_hot_removal_recovers_exact_identity_and_retires_old_writer() {
    let first = goal_fixture(1);
    let second = goal_fixture(2);
    let old = scope_owner(&first, first.tick.objective_digest);
    let next = scope_owner(&second, second.tick.objective_digest);
    let old_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &old));
    let next_scope = checked(AgentdNeuronGoalScopeV3::capture(2, &next));
    let path = first.root.path().join("scope-control.json");
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            old_scope.clone(),
            old.clone(),
            std::iter::empty(),
            &path,
        ),
    );
    checked(controller.start());
    let commit = checked(
        first
            .prepared(&controller)
            .execute(&first.input(), &mut first.allow()),
    );
    checked(controller.begin_quiesce());
    checked(controller.seal());
    checked(controller.reload_goal_scope_v3(&old_scope, next.clone()));
    {
        let mut state = checked(controller.lock_state());
        let archive = checked(old.owner.export_archive_control());
        checked(
            state
                .archives
                .as_mut()
                .expect("archive owner")
                .commit_goal_scope_v3(&old_scope, &archive),
        );
    }
    drop(controller);
    assert!(
        checked(read_agentd_neuron_live_goal_scope_state_v3(&path))
            .retained_scopes
            .is_empty()
    );
    let recovered = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            next_scope,
            next,
            [(old_scope.clone(), old.clone())],
            &path,
        ),
    );
    checked(recovered.start());
    assert!(matches!(
        old.operational_snapshot(),
        Err(AgentdNeuronControlErrorV2::NotServing)
    ));
    assert_eq!(
        checked(recovered.query_goal_scope_operation_v3(
            &old_scope,
            &first.tick.tick_id,
            commit.key.input_semantic_digest
        )),
        NeuronOperationStatusV2::Committed {
            commit: Box::new(commit),
            witness_acknowledged: true
        }
    );
    assert_eq!(
        checked(recovered.goal_scope_topology_v3()).cold.scope_count,
        1
    );
    assert_eq!(first.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn goal_scope_archive_storage_pressure_keeps_sealed_predecessor_and_all_truth() {
    let fixtures = (1..=4).map(goal_fixture).collect::<Vec<_>>();
    let path = fixtures[0].root.path().join("scope-control.json");
    let first = scope_owner(&fixtures[0], fixtures[0].tick.objective_digest);
    let mut active_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &first));
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_with_archive_policy_v3(
            active_scope.clone(),
            first,
            std::iter::empty(),
            &path,
            AgentdNeuronArchivePolicyV1 {
                maximum_total_bytes: 1,
            },
        ),
    );
    checked(controller.start());
    for index in 1..=2 {
        checked(controller.begin_quiesce());
        checked(controller.seal());
        let next = scope_owner(&fixtures[index], fixtures[index].tick.objective_digest);
        checked(controller.reload_goal_scope_v3(&active_scope, next.clone()));
        active_scope = checked(AgentdNeuronGoalScopeV3::capture(index as u64 + 1, &next));
    }
    checked(controller.begin_quiesce());
    checked(controller.seal());
    let before = checked(std::fs::read(&path));
    let next = scope_owner(&fixtures[3], fixtures[3].tick.objective_digest);
    assert!(matches!(
        controller.reload_goal_scope_v3(&active_scope, next.clone()),
        Err(AgentdNeuronControlErrorV2::StoragePressure)
    ));
    assert_eq!(checked(std::fs::read(&path)), before);
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Sealed
    );
    assert_eq!(
        checked(controller.goal_scope_topology_v3())
            .cold
            .scope_count,
        0
    );
    assert_eq!(
        checked(controller.goal_scope_state_v3())
            .retained_scopes
            .len(),
        2
    );
    assert!(!next.lifecycle_gate_snapshot().0);
}

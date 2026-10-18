use super::*;

fn goal(ordinal: u64) -> Harness {
    let mut fixture = Harness::new();
    let objective = digest(&format!("reload-goal-{ordinal}"));
    fixture.tick.objective_digest = objective;
    fixture.cell.request.objective_digest = objective;
    fixture
}

#[test]
fn interrupted_goal_reload_cold_reopens_only_full_old_or_full_completed_topology() {
    let fixtures = [goal(1), goal(2), goal(3)];
    let owners = fixtures
        .iter()
        .map(|h| scope_owner(h, h.tick.objective_digest))
        .collect::<Vec<_>>();
    let scopes = owners
        .iter()
        .enumerate()
        .map(|(index, owner)| checked(AgentdNeuronGoalScopeV3::capture(index as u64 + 1, owner)))
        .collect::<Vec<_>>();
    let path = fixtures[0].root.path().join("reload-control.json");
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            scopes[0].clone(),
            owners[0].clone(),
            std::iter::empty(),
            &path,
        ),
    );
    checked(controller.start());
    let first_commit = checked(
        fixtures[0]
            .prepared(&controller)
            .execute(&fixtures[0].input(), &mut fixtures[0].allow()),
    );
    checked(controller.begin_quiesce());
    checked(controller.seal());
    checked(controller.reload_goal_scope_v3(&scopes[0], owners[1].clone()));
    let second_commit = checked(
        fixtures[1]
            .prepared(&controller)
            .execute(&fixtures[1].input(), &mut fixtures[1].allow()),
    );
    checked(controller.begin_quiesce());
    checked(controller.seal());
    let interrupted = checked(AgentdNeuronGoalScopeStateV3::new(
        AgentdNeuronLifecycleStateV2::Reloading,
        scopes[1].clone(),
        vec![scopes[0].clone()],
        Some(scopes[2].clone()),
    ));
    // The production codec records the real cut after Reloading is durable
    // and before the successor is published. Release every physical writer.
    checked(write_agentd_neuron_goal_scope_state_v3(&path, &interrupted));
    drop(controller);
    drop(owners);
    let store_bytes = fixtures
        .iter()
        .map(|h| checked(std::fs::read(h.root.path().join("generation.hptngs02"))))
        .collect::<Vec<_>>();
    let old_active = scope_owner(&fixtures[1], fixtures[1].tick.objective_digest);
    let old_retained = scope_owner(&fixtures[0], fixtures[0].tick.objective_digest);
    let old = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            scopes[1].clone(),
            old_active.clone(),
            [(scopes[0].clone(), old_retained)],
            &path,
        ),
    );
    assert_eq!(checked(old.state()), AgentdNeuronLifecycleStateV2::Sealed);
    let old_state = checked(read_agentd_neuron_goal_scope_state_v3(&path));
    assert_eq!(old_state.active_scope, scopes[1]);
    assert_eq!(old_state.retained_scopes, scopes[..1]);
    assert_eq!(old_state.reload_target_scope, None);
    assert!(!old_active.lifecycle_gate_snapshot().0);
    assert!(old.start().is_err());
    drop(old);
    drop(old_active);
    checked(write_agentd_neuron_goal_scope_state_v3(&path, &interrupted));
    let completed_active = scope_owner(&fixtures[2], fixtures[2].tick.objective_digest);
    let completed_retained = fixtures[..2]
        .iter()
        .zip(&scopes)
        .map(|(h, scope)| (scope.clone(), scope_owner(h, h.tick.objective_digest)))
        .collect::<Vec<_>>();
    let completed = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            scopes[2].clone(),
            completed_active.clone(),
            completed_retained,
            &path,
        ),
    );
    assert_eq!(
        checked(completed.state()),
        AgentdNeuronLifecycleStateV2::Starting
    );
    assert!(!completed_active.lifecycle_gate_snapshot().0);
    checked(completed.start());
    let completed_state = checked(read_agentd_neuron_goal_scope_state_v3(&path));
    assert_eq!(completed_state.active_scope, scopes[2]);
    assert_eq!(completed_state.retained_scopes, scopes[..2]);
    assert_eq!(completed_state.reload_target_scope, None);
    assert_eq!(checked(completed.active_generation()), 1);
    for (index, commit) in [first_commit, second_commit].into_iter().enumerate() {
        assert_eq!(
            checked(completed.query_goal_scope_operation_v3(
                &scopes[index],
                &fixtures[index].tick.tick_id,
                commit.key.input_semantic_digest,
            )),
            NeuronOperationStatusV2::Committed {
                commit: Box::new(commit),
                witness_acknowledged: true
            }
        );
        assert_eq!(fixtures[index].calls.load(Ordering::SeqCst), 1);
    }
    assert_eq!(fixtures[2].calls.load(Ordering::SeqCst), 0);
    for (h, before) in fixtures.iter().zip(store_bytes) {
        assert_eq!(
            checked(std::fs::read(h.root.path().join("generation.hptngs02"))),
            before
        );
    }
}

#[test]
fn interrupted_goal_reload_rejects_missing_or_mutated_full_topology_without_fencing() {
    let fixtures = [goal(1), goal(2), goal(3)];
    let owners = fixtures
        .iter()
        .map(|h| scope_owner(h, h.tick.objective_digest))
        .collect::<Vec<_>>();
    let scopes = owners
        .iter()
        .enumerate()
        .map(|(index, owner)| checked(AgentdNeuronGoalScopeV3::capture(index as u64 + 1, owner)))
        .collect::<Vec<_>>();
    let path = fixtures[0].root.path().join("reload-control.json");
    let state = checked(AgentdNeuronGoalScopeStateV3::new(
        AgentdNeuronLifecycleStateV2::Reloading,
        scopes[1].clone(),
        vec![scopes[0].clone()],
        Some(scopes[2].clone()),
    ));
    checked(write_agentd_neuron_goal_scope_state_v3(&path, &state));
    let before = checked(std::fs::read(&path));
    for retained in [
        Vec::new(),
        vec![(scopes[0].clone(), owners[0].clone())],
        vec![(scopes[1].clone(), owners[1].clone())],
    ] {
        assert!(
            AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
                scopes[2].clone(),
                owners[2].clone(),
                retained,
                &path,
            )
            .is_err()
        );
        assert_eq!(checked(std::fs::read(&path)), before);
    }
    for field in 0..5 {
        let mut foreign = scopes[2].clone();
        match field {
            0 => foreign.identity.model_generation = 2,
            1 => foreign.identity.subject_scope_digest = digest("foreign-subject"),
            2 => foreign.identity.objective_digest = digest("foreign-goal"),
            3 => foreign.identity.runtime_configuration_digest = digest("foreign-runtime"),
            _ => foreign.identity.body_bundle_digest = digest("foreign-body"),
        }
        assert!(
            AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
                foreign,
                owners[2].clone(),
                [
                    (scopes[0].clone(), owners[0].clone()),
                    (scopes[1].clone(), owners[1].clone())
                ],
                &path,
            )
            .is_err()
        );
        assert_eq!(checked(std::fs::read(&path)), before);
    }
    for owner in &owners {
        assert!(owner.lifecycle_gate_snapshot().0);
    }
    for h in &fixtures {
        assert_eq!(h.calls.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn reloading_scope_requires_each_original_header_and_never_bootstraps_missing_history() {
    let fixtures = [goal(1), goal(2), goal(3)];
    let owners = fixtures
        .iter()
        .map(|h| scope_owner(h, h.tick.objective_digest))
        .collect::<Vec<_>>();
    let scopes = owners
        .iter()
        .enumerate()
        .map(|(index, owner)| checked(AgentdNeuronGoalScopeV3::capture(index as u64 + 1, owner)))
        .collect::<Vec<_>>();
    let control_path = fixtures[0].root.path().join("reload-control.json");
    let state = checked(AgentdNeuronGoalScopeStateV3::new(
        AgentdNeuronLifecycleStateV2::Reloading,
        scopes[1].clone(),
        vec![scopes[0].clone()],
        Some(scopes[2].clone()),
    ));
    checked(write_agentd_neuron_goal_scope_state_v3(
        &control_path,
        &state,
    ));
    let control_before = checked(std::fs::read(&control_path));
    drop(owners);
    for h in &fixtures {
        let store_path = h.root.path().join("generation.hptngs02");
        let index_path = h.root.path().join("index.hptngi02");
        let store_before = checked(std::fs::read(&store_path));
        let index_before = checked(std::fs::read(&index_path));
        let mut journal_scope = scope();
        journal_scope.objective_digest = h.tick.objective_digest;
        let (mut store_context, mut index_context) = contexts(&h.native, &h.config, &h.body);
        store_context.scope = journal_scope;
        index_context.scope = journal_scope;
        for missing in [false, true] {
            if missing {
                checked(std::fs::remove_file(&store_path));
            } else {
                checked(std::fs::write(&store_path, &store_before[..4]));
            }
            let recovered = NeuronRuntimeV2::recover(
                &store_path,
                &index_path,
                h.native.clone(),
                journal_scope,
                h.config.clone(),
                h.body.clone(),
                store_context.clone(),
                index_context.clone(),
                h.witness.clone(),
            );
            assert!(recovered.is_err());
            if missing {
                assert!(!store_path.exists());
            } else {
                assert_eq!(checked(std::fs::read(&store_path)), store_before[..4]);
            }
            assert_eq!(checked(std::fs::read(&index_path)), index_before);
            assert_eq!(checked(std::fs::read(&control_path)), control_before);
            // This restores only the fault-injected private test fixture.
            checked(std::fs::write(&store_path, &store_before));
        }
        let mut foreign = store_context.clone();
        foreign.scope.objective_digest = digest("wrong-header-goal");
        assert!(
            codex_hepta_agent_components::neuron::FileNeuronGenerationStoreV2::open_existing(
                &store_path,
                foreign
            )
            .is_err()
        );
        assert_eq!(checked(std::fs::read(&store_path)), store_before);
        assert_eq!(h.calls.load(Ordering::SeqCst), 0);
    }
}

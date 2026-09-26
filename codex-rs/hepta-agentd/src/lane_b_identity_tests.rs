use super::*;

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.identity".to_string(),
        supervisor_generation: 41,
        agentd_generation: 42,
        configuration_digest: digest('1'),
        ports_digest: digest('2'),
        max_active_runs: 8,
    }
}

fn snapshot(run_id: &str) -> RunSnapshot {
    let composition = composition();
    RunSnapshot {
        run_id: run_id.to_string(),
        request_digest: digest('3'),
        objective_digest: digest('4'),
        body_digest: digest('5'),
        artifact_set_digest: digest('6'),
        authority_epoch: 7,
        generation: composition.agentd_generation,
        fence_digest: composition.expected_run_fence_digest(),
        deadline_ms: 10_000,
    }
}

#[test]
fn distinct_launch_and_runtime_generations_admit_only_the_exact_fence() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let admitted = coordinator
        .start_run(100, snapshot("run.current"))
        .expect("current generation");
    assert_eq!(admitted.generation, 42);

    let mut stale = snapshot("run.stale");
    stale.generation = 41;
    stale.fence_digest = run_fence_digest("agent.identity", 41, 41);
    assert_eq!(
        coordinator.start_run(100, stale),
        Err(AgentRunError::InvalidCompositionIdentity(
            "agentd generation"
        ))
    );

    let mut forged = snapshot("run.forged");
    forged.fence_digest = digest('9');
    assert_eq!(
        coordinator.start_run(100, forged),
        Err(AgentRunError::InvalidCompositionIdentity("run fence"))
    );
}

#[test]
fn runtime_generation_binding_is_monotonic() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agentd_generation: 41,
        ..composition()
    })
    .expect("compose starting generation");
    coordinator
        .bind_agentd_generation(42)
        .expect("enter Running");
    assert_eq!(coordinator.composition().agentd_generation, 42);
    assert_eq!(
        coordinator.bind_agentd_generation(41),
        Err(AgentRunError::InvalidGeneration)
    );
}

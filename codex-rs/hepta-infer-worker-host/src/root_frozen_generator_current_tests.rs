use super::*;

// The original supervisor wire fixture carries full health and control fence.
// These are pure check inputs, never a RootAdmittedFleetPeer constructor.
fn fixture() -> Result<(SupervisordHealth, SupervisordAgentStatus)> {
    let fence = serde_json::json!({
        "agent_id":"00000000-0000-4000-8000-000000000001",
        "supervisor_epoch":"00000000-0000-4000-8000-000000000002",
        "lifecycle":"running", "lifecycle_generation":11,
        "spawn_generation":10,"runtime_generation":11,
        "current_release":"linux-original-agent", "previous_release":null,
        "release_change_pending":false,"state_digest":"a".repeat(64)
    });
    let health = serde_json::from_value(serde_json::json!({
        "ready":true,"supervisor_epoch":fence["supervisor_epoch"],
        "process_id":std::process::id(),"registered_agents":1,"observed_faults":0
    }))?;
    let agent = serde_json::from_value(serde_json::json!({
        "agent_id":fence["agent_id"],"lifecycle":"running","lifecycle_generation":11,
        "active":true,"healthy":true,"process_id":101,
        "spawn_generation":10,"runtime_generation":11,
        "current_release":"linux-original-agent","previous_release":null,
        "release_change_pending":false,"control_fence":fence,
        "matrix":{"configured":false,"active":false,"healthy":false,"degraded":false,
            "process_id":null,"attached_agent_generation":null,"binding_revision":null,
            "restart_attempt":0,"last_error":null}
    }))?;
    Ok((health, agent))
}

#[test]
fn current_agent_requires_exact_pid_ready_owner_and_complete_fence() -> Result<()> {
    let (health, agent) = fixture()?;
    let id = agent.agent_id.clone();
    validate(&health, &agent, &health, &id, id.as_str(), /*pid*/ 101)?;
    for change in 0..8 {
        let mut current = agent.clone();
        match change {
            0 => current.process_id = Some(102),
            1 => current.spawn_generation = Some(11),
            2 => current.current_release = None,
            3 => current.control_fence.lifecycle_generation += 1,
            4 => current.healthy = false,
            5 => current.active = false,
            6 => current.release_change_pending = true,
            7 => current.runtime_generation = Some(12),
            _ => unreachable!(),
        }
        assert!(
            validate(
                &health,
                &current,
                &health,
                &id,
                id.as_str(),
                /*pid*/ 101
            )
            .is_err()
        );
    }
    let mut replaced = health.clone();
    replaced.process_id += 1;
    assert!(
        validate(
            &health,
            &agent,
            &replaced,
            &id,
            id.as_str(),
            /*pid*/ 101
        )
        .is_err()
    );
    let mut unready = health.clone();
    unready.ready = false;
    assert!(
        validate(
            &unready,
            &agent,
            &health,
            &id,
            id.as_str(),
            /*pid*/ 101
        )
        .is_err()
    );
    assert!(
        validate(
            &health,
            &agent,
            &health,
            &id,
            "another-original-subject",
            /*pid*/ 101
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn independent_observation_cannot_rebind_same_agent_to_new_process_or_fence() -> Result<()> {
    let (_, original) = fixture()?;
    unchanged(&original, &original)?;
    let mut new_process = original.clone();
    new_process.process_id = Some(102);
    assert!(unchanged(&original, &new_process).is_err());
    let mut new_fence = original.clone();
    new_fence.control_fence.state_digest =
        serde_json::from_value(serde_json::json!("b".repeat(64)))?;
    assert!(unchanged(&original, &new_fence).is_err());
    Ok(())
}

#[test]
fn original_readers_use_runtime_epoch_after_the_spawn_transition() -> Result<()> {
    let (health, agent) = fixture()?;
    validate(
        &health,
        &agent,
        &health,
        &agent.agent_id,
        agent.agent_id.as_str(),
        /*pid*/ 101,
    )?;
    validate_runtime_generation(&agent, /*generation*/ 11)?;
    for generation in [10, 12] {
        assert!(validate_runtime_generation(&agent, generation).is_err());
    }
    let mut missing = agent;
    missing.runtime_generation = None;
    assert!(validate_runtime_generation(&missing, /*generation*/ 11).is_err());
    Ok(())
}

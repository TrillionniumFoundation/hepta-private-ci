use anyhow::Context;
use anyhow::Result;
use serde_json::Value;

use super::*;

fn fixture(id: &str) -> Result<RobrixSupervisordResponse> {
    let artifacts = crate::generated_robrix_control_artifacts()?;
    let corpus: Value = serde_json::from_slice(
        artifacts
            .get(crate::CORPUS_FILE)
            .context("generated corpus")?,
    )?;
    let wire = corpus["cases"]
        .as_array()
        .context("corpus cases")?
        .iter()
        .find(|case| case["id"] == id)
        .and_then(|case| case["wire_utf8"].as_str())
        .context("response fixture")?;
    Ok(serde_json::from_str(wire)?)
}

#[test]
fn health_and_roster_enforce_capacity_and_agent_identity_uniqueness() -> Result<()> {
    let mut health = fixture("supervisord_response_health")?;
    health.validate(health.request_id)?;
    if let RobrixSupervisordPayload::Health(health) = &mut health.payload {
        health.registered_agents = MAX_SUPERVISORD_ROSTER + 1;
    }
    assert!(health.validate(health.request_id).is_err());
    let mut roster = fixture("supervisord_response_roster")?;
    roster.validate(roster.request_id)?;
    if let RobrixSupervisordPayload::Roster { agents } = &mut roster.payload {
        let mut duplicate = agents.first().context("roster Agent")?.clone();
        // Distinct full objects still represent the same Agent, so JSON
        // Schema uniqueItems alone cannot enforce this identity constraint.
        duplicate.healthy = false;
        agents.push(duplicate);
    }
    assert!(roster.validate(roster.request_id).is_err());
    Ok(())
}

#[test]
fn readonly_response_matches_method_selected_agent_and_requested_roster_limit() -> Result<()> {
    let agent = fixture("supervisord_response_agent")?;
    let RobrixSupervisordPayload::Agent(status) = &agent.payload else {
        anyhow::bail!("Agent fixture")
    };
    let selected = RobrixSupervisordRequest::new(
        agent.request_id,
        RobrixSupervisordMethod::Snapshot {
            agent_id: status.agent_id.clone(),
        },
    );
    agent.validate_for(&selected)?;
    let wrong_method =
        RobrixSupervisordRequest::new(agent.request_id, RobrixSupervisordMethod::Health);
    assert!(agent.validate_for(&wrong_method).is_err());
    let wrong_agent = RobrixSupervisordRequest::new(
        agent.request_id,
        RobrixSupervisordMethod::Snapshot {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")
                .map_err(anyhow::Error::msg)?,
        },
    );
    assert!(agent.validate_for(&wrong_agent).is_err());
    let mut roster = fixture("supervisord_response_roster")?;
    if let RobrixSupervisordPayload::Roster { agents } = &mut roster.payload {
        let mut other = agents.first().context("roster Agent")?.clone();
        other.agent_id = match wrong_agent.method {
            RobrixSupervisordMethod::Snapshot { agent_id } => agent_id,
            _ => anyhow::bail!("selected fixture"),
        };
        other.control_fence.agent_id = other.agent_id.clone();
        agents.push(other);
    }
    roster.validate(roster.request_id)?;
    let request = RobrixSupervisordRequest::new(
        roster.request_id,
        RobrixSupervisordMethod::Roster { limit: 1 },
    );
    assert!(roster.validate_for(&request).is_err());
    Ok(())
}

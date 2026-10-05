use super::*;
use pretty_assertions::assert_eq;

#[test]
fn shared_legacy_descriptor_never_crosses_agent_identity() {
    let first = AgentId::parse("0ebc6aa4-a764-4dfa-a529-8bdf9e5f6cba").unwrap();
    let second = AgentId::parse("4f1971d2-7aa1-416a-b6e0-2b2d9f4b61ac").unwrap();
    let path = Path::new("/etc/hepta/self-iteration/first.json");
    let bytes = serde_json::to_vec(&serde_json::json!({
        "version": 1, "agent_id": first, "model": "real-model"
    }))
    .unwrap();
    let first_environment = descriptor_environment(path, &bytes, &first).unwrap();
    assert!(first_environment.is_some());
    assert_eq!(descriptor_environment(path, &bytes, &second).unwrap(), None);
}

#[test]
fn descriptor_revision_changes_future_launch_pin_without_mutating_prepared_launch() {
    let agent = AgentId::parse("0ebc6aa4-a764-4dfa-a529-8bdf9e5f6cba").unwrap();
    let path = Path::new("/etc/hepta/self-iteration/first.json");
    let before = serde_json::to_vec(&serde_json::json!({
        "version": 1, "agent_id": agent, "objective_prompt": "first objective"
    }))
    .unwrap();
    let after = serde_json::to_vec(&serde_json::json!({
        "version": 1, "agent_id": agent, "objective_prompt": "next objective"
    }))
    .unwrap();
    let prepared = descriptor_environment(path, &before, &agent)
        .unwrap()
        .unwrap();
    let next = descriptor_environment(path, &after, &agent)
        .unwrap()
        .unwrap();
    assert_ne!(prepared, next);
    assert_eq!(
        prepared,
        descriptor_environment(path, &before, &agent)
            .unwrap()
            .unwrap()
    );
}

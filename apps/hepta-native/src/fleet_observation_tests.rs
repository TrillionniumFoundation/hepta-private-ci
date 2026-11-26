use super::*;

const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

fn observation() -> serde_json::Value {
    serde_json::json!({
        "schema": "hepta_fleet_observation_v1", "observation_revision": 9,
        "health": {"ready": true, "supervisor_epoch": EPOCH,
            "process_id": 2233, "registered_agents": 1, "observed_faults": 2},
        "agents": [{"agent_id": AGENT, "lifecycle": "failed", "lifecycle_generation": 9,
            "active": false, "healthy": false, "process_id": null,
            "current_release": "agentd-real-owner", "control_fence": {"supervisor_epoch": EPOCH},
            "matrix": {"configured": true, "healthy": false, "degraded": true, "last_error": "process exited"}}],
    })
}

#[test]
fn fleet_identity_and_modules_do_not_require_legacy_snapshot_fields() {
    let value = observation();
    let metadata = view_metadata(&value).unwrap();
    assert_eq!(
        (metadata.generation, metadata.modules),
        (
            9,
            vec![
                format!("agent.{AGENT}"),
                format!("matrix.{AGENT}"),
                "ui.native".into()
            ]
        )
    );
    assert!(value.get("state").is_none());
}

#[test]
fn complete_roster_rejects_foreign_epoch_duplicates_and_false_health() {
    let value = observation();
    let mut foreign = value.clone();
    foreign["agents"][0]["control_fence"]["supervisor_epoch"] =
        "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c13".into();
    let mut duplicate = value.clone();
    duplicate["agents"]
        .as_array_mut()
        .unwrap()
        .push(value["agents"][0].clone());
    duplicate["health"]["registered_agents"] = 2.into();
    let mut false_health = value.clone();
    false_health["agents"][0]["healthy"] = true.into();
    let mut partial = value.clone();
    partial["health"]["registered_agents"] = 2.into();
    let mut empty_identity = value;
    empty_identity["observation_revision"] = 0.into();
    for malformed in [foreign, duplicate, false_health, partial, empty_identity] {
        assert!(FleetObservation::parse(&malformed).is_err());
    }
}

#[test]
fn legacy_consumer_retains_its_generation_with_an_explicit_legacy_source_module() {
    let metadata =
        view_metadata(&serde_json::json!({"state": {"runtime_snapshot_generation": 0}})).unwrap();
    assert_eq!(
        (metadata.generation, metadata.modules),
        (0, vec!["runtime.legacy".into(), "ui.native".into()])
    );
}

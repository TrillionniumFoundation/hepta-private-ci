//! Original deployment wire/identity cases only. No sealed producer, grant,
//! persisted Core seed, model or application acceptance is represented here.
use super::Deployment;
use serde_json::Value;
use serde_json::json;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18";

fn wire() -> Value {
    json!({
        "schema":"hepta.agentd.original_desktop_launch.v1",
        "profile":"notes_calculator_v1", "agent_id":AGENT, "spawn_generation":1,
        "session":{"uid":1000,"pid":42,"boot_id":"11111111-2222-3333-4444-555555555555","process_start_ticks":7},
        "bindings":{
            "principal_scope":"organ.desktop.notes_calculator",
            "principal_scope_digest":"1".repeat(64),"issuer_id":"fixture-root","policy_generation":1,
            "locale":"en-US","runtime_body_digest":"2".repeat(64),
            "preference_state_digest":"3".repeat(64),"model_tuple_digest":"4".repeat(64),
            "prompt_registry_digest":"5".repeat(64),"artifact_set_digest":"6".repeat(64)
        },
        "startup_release":{
            "notes":{"session_instance":"1".repeat(32),"task_id":1,"incarnation":"2".repeat(32)},
            "calculator":{"session_instance":"1".repeat(32),"task_id":2,"incarnation":"3".repeat(32)},
            "nonce":"4".repeat(32)
        },
        "interaction":{
            "kind":"original_desktop_thread_tool_v1",
            "route":{"control_socket":"/fixture/agentd.sock","agent_id":AGENT,"spawn_generation":1,
                "thread_id":"original-desktop","app_server_session_id":"original-session","codex_home":"/fixture/home"},
            "seed":{"schema_version":1,"codex_home":"/fixture/home","thread_id":"original-desktop",
                "app_server_session_id":"original-session","model":"fixture-model","model_provider":"fixture-provider",
                "rollout_path":"/fixture/home/rollout.jsonl","catalog_sha256":"7".repeat(64),
                "session_meta_sha256":"8".repeat(64),"execution_profile":"fixture-only",
                "execution_cwd":"/fixture/workspace","core_config_sha256":"9".repeat(64),
                "environments_sha256":"a".repeat(64)}
        }
    })
}

#[test]
fn joint_header_requires_matching_owner_generation_and_actual_target_pair() -> anyhow::Result<()> {
    let value: Deployment = serde_json::from_value(wire())?;
    value.validate_identity(AGENT, /*spawn_generation*/ 1, /*owner*/ 1000)?;
    assert!(
        value
            .validate_identity(AGENT, /*spawn_generation*/ 2, /*owner*/ 1000)
            .is_err()
    );
    assert!(
        value
            .validate_identity(AGENT, /*spawn_generation*/ 1, /*owner*/ 1001)
            .is_err()
    );
    assert!(
        value
            .validate_identity(AGENT, /*spawn_generation*/ 1, /*owner*/ 0)
            .is_err()
    );
    assert!(
        value
            .validate_identity(
                "other-agent",
                /*spawn_generation*/ 1,
                /*owner*/ 1000
            )
            .is_err()
    );
    for field in ["profile", "schema"] {
        let mut changed = wire();
        changed[field] = "legacy-notes".into();
        let changed: Deployment = serde_json::from_value(changed)?;
        assert!(
            changed
                .validate_identity(AGENT, /*spawn_generation*/ 1, /*owner*/ 1000)
                .is_err()
        );
    }
    let mut changed = wire();
    changed["startup_release"]["calculator"]["session_instance"] = "f".repeat(32).into();
    let changed: Deployment = serde_json::from_value(changed)?;
    assert!(
        changed
            .validate_identity(AGENT, /*spawn_generation*/ 1, /*owner*/ 1000)
            .is_err()
    );
    Ok(())
}

#[test]
fn joint_wire_never_defaults_a_release_interaction_or_old_recovery() {
    for field in ["startup_release", "interaction", "profile"] {
        let mut changed = wire();
        changed.as_object_mut().unwrap().remove(field);
        assert!(serde_json::from_value::<Deployment>(changed).is_err());
    }
    let mut changed = wire();
    changed["previous_recovery"] = Value::Null;
    assert!(serde_json::from_value::<Deployment>(changed).is_err());
    let mut changed = wire();
    changed["interaction"]["kind"] = "original_thread_tool_v1".into();
    assert!(serde_json::from_value::<Deployment>(changed).is_err());
    let mut changed = wire();
    changed["bindings"]["grant"] = true.into();
    assert!(serde_json::from_value::<Deployment>(changed).is_err());
}

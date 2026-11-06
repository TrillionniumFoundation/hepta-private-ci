//! Consumer-only strict stdout/profile controls. These do not execute Chain.
use super::*;
use serde_json::json;

fn config(owner: NativeOwner) -> NativePqConfig {
    NativePqConfig {
        configuration: PathBuf::from("/test-only/configuration.json"),
        configuration_sha256: "10".repeat(32),
        application_profile: APPLICATION_PROFILE.into(),
        network: "11".repeat(32),
        parameters: "12".repeat(32),
        genesis: "13".repeat(32),
        network_policy: "14".repeat(32),
        owner,
    }
}
fn observation(config: &NativePqConfig, wire: &[u8]) -> Value {
    json!({"result":{"block":"15".repeat(32),"stored_exact":true},
        "pq_application_context":{
            "schema":"native-pq-application-local-observation-v1",
            "configuration_sha256":config.configuration_sha256,
            "profile":config.application_profile,"network":config.network,
            "parameters":config.parameters,"genesis":config.genesis,
            "network_policy":config.network_policy,"owner_profile":config.owner_profile(),
            "packet_sha256":Sha256Digest::for_bytes(wire).as_str(),"block":"15".repeat(32)},
        "clock_scope":"local-wall","local_owner_only":true,
        "whole_node_rollback_protection":false,"production_activation":false})
}
#[test]
fn npq6_readback_requires_all_exact_context_and_observation_fields() {
    let wire = b"synthetic consumer bytes, not a Chain packet";
    let config = config(NativeOwner::NetworkV2 {});
    let good = observation(&config, wire);
    assert!(config.readback_matches(&serde_json::to_vec(&good).unwrap(), wire));
    for field in [
        "schema",
        "configuration_sha256",
        "profile",
        "network",
        "parameters",
        "genesis",
        "network_policy",
        "owner_profile",
        "packet_sha256",
        "block",
    ] {
        for fault in 0..3 {
            let mut changed = good.clone();
            let map = changed["pq_application_context"].as_object_mut().unwrap();
            match fault {
                0 => {
                    map.remove(field);
                }
                1 => {
                    map.insert(field.into(), Value::Null);
                }
                2 => {
                    map.insert(field.into(), json!("different"));
                }
                _ => unreachable!(),
            }
            assert!(
                !config.readback_matches(&serde_json::to_vec(&changed).unwrap(), wire),
                "{field}/{fault}"
            );
        }
    }
    for field in [
        "result",
        "pq_application_context",
        "clock_scope",
        "local_owner_only",
        "whole_node_rollback_protection",
        "production_activation",
    ] {
        let mut changed = good.clone();
        changed.as_object_mut().unwrap().remove(field);
        assert!(
            !config.readback_matches(&serde_json::to_vec(&changed).unwrap(), wire),
            "{field}"
        );
    }
    for field in [
        "whole_node_rollback_protection",
        "production_activation",
        "local_owner_only",
    ] {
        let mut changed = good.clone();
        changed[field] = json!(!good[field].as_bool().unwrap());
        assert!(!config.readback_matches(&serde_json::to_vec(&changed).unwrap(), wire));
    }
    assert!(!config.readback_matches(&serde_json::to_vec(&good).unwrap(), b"other exact bytes"));
}
#[test]
fn npq6_readback_rejects_duplicate_unknown_and_mixed_owner_json_before_value_acceptance() {
    let wire = b"consumer fixture";
    let config = config(NativeOwner::NetworkV2 {});
    let good = observation(&config, wire);
    for pointer in ["", "/pq_application_context"] {
        let mut changed = good.clone();
        changed
            .pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("extra".into(), json!(0));
        assert!(!config.readback_matches(&serde_json::to_vec(&changed).unwrap(), wire));
    }
    let raw = serde_json::to_string(&good).unwrap();
    let field = format!("\"network\":\"{}\"", config.network);
    let duplicate = raw.replacen(&field, &format!("{field},{field}"), 1);
    assert_ne!(raw, duplicate);
    assert!(!config.readback_matches(duplicate.as_bytes(), wire));
    assert!(!config.readback_matches(format!("{raw}null").as_bytes(), wire));
    let mut different_block = good.clone();
    different_block["result"]["block"] = json!("16".repeat(32));
    assert!(!config.readback_matches(&serde_json::to_vec(&different_block).unwrap(), wire));
    let witness = self::config(NativeOwner::WitnessV4 {
        writer_key: PathBuf::from("/test-only/writer"),
    });
    assert!(!witness.readback_matches(&serde_json::to_vec(&good).unwrap(), wire));
    assert!(witness.readback_matches(
        &serde_json::to_vec(&observation(&witness, wire)).unwrap(),
        wire
    ));
}
#[test]
fn npq6_provider_owner_is_mandatory_and_closed_without_nullable_fallback() {
    let config = config(NativeOwner::NetworkV2 {});
    let original = serde_json::to_value(&config).unwrap();
    for fault in 0..6 {
        let mut value = original.clone();
        match fault {
            0 => {
                value.as_object_mut().unwrap().remove("owner");
            }
            1 => value["owner"] = Value::Null,
            2 => value["owner"] = json!({"profile":"network_v2","writer_key":"/test-only/writer"}),
            3 => value["owner"] = json!({"profile":"witness_v4"}),
            4 => value["owner"] = json!({"profile":"unknown"}),
            5 => value["unexpected"] = json!(true),
            _ => unreachable!(),
        }
        assert!(
            serde_json::from_value::<NativePqConfig>(value).is_err(),
            "fault {fault}"
        );
    }
}
#[test]
fn npq6_command_profile_never_adds_classical_flags_and_development_remains_explicit() {
    let native = Profile::NativePq(Box::new(config(NativeOwner::NetworkV2 {})));
    let mut command = Command::new("not-executed");
    native.append_arguments(&mut command);
    let args: Vec<_> = command.get_args().map(|v| v.to_str().unwrap()).collect();
    assert_eq!(
        args,
        [
            "--pq-application-config",
            "/test-only/configuration.json",
            "--pq-application-config-sha256",
            &"10".repeat(32)
        ]
    );
    let legacy = Profile::Development {
        state_backend: "legacy-v2".into(),
        genesis_time: 7,
        evaluation_policy: "legacy-first-two-v3".into(),
        task_profile: "legacy-task-v1".into(),
        model_profile: "linear-expert-dev-v1".into(),
    };
    let mut command = Command::new("not-executed");
    legacy.append_arguments(&mut command);
    let args: Vec<_> = command.get_args().map(|v| v.to_str().unwrap()).collect();
    assert_eq!(
        args,
        [
            "--state-backend",
            "legacy-v2",
            "--genesis-time",
            "7",
            "--evaluation-policy",
            "legacy-first-two-v3",
            "--task-profile",
            "legacy-task-v1",
            "--model-profile",
            "linear-expert-dev-v1"
        ]
    );
    assert!(legacy.validate_selected_configuration().is_ok());
    assert!(legacy.readback_matches(b"legacy observation policy unchanged", b""));
}

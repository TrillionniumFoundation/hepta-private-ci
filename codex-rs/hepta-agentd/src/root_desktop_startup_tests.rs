//! Wire and target-correlation cases; these fixtures grant no Root authority.
use super::*;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_memory::NotesTargetIdentity;
use serde_json::Value;
use serde_json::json;

fn wire() -> Value {
    json!({
        "schema":"hepta.root.desktop_launch_profile.v1",
        "profile":"notes_calculator_v1", "grant_lifetime_ms":1000,
        "bindings":{
            "principal_scope":"organ.desktop.notes_calculator",
            "principal_scope_digest":"1".repeat(64),"issuer_id":"fixture-root","policy_generation":1,
            "locale":"en-US","runtime_body_digest":"2".repeat(64),
            "preference_state_digest":"3".repeat(64),"model_tuple_digest":"4".repeat(64),
            "prompt_registry_digest":"5".repeat(64),"artifact_set_digest":"6".repeat(64)
        },
        "interaction":{
            "kind":"original_desktop_thread_tool_v1",
            "route":{"control_socket":"/fixture/agentd.sock","agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18","spawn_generation":2,
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

fn targets() -> (
    NotesTargetIdentity,
    CalculatorTargetIdentity,
    crate::AgentdDesktopStartupRelease,
) {
    (
        NotesTargetIdentity {
            session_instance: "1".repeat(32),
            task_id: 1,
            incarnation: "2".repeat(32),
        },
        CalculatorTargetIdentity {
            session_instance: "1".repeat(32),
            task_id: 2,
            incarnation: "3".repeat(32),
        },
        crate::AgentdDesktopStartupRelease {
            notes: NotesTargetIdentity {
                session_instance: "4".repeat(32),
                task_id: 1,
                incarnation: "5".repeat(32),
            },
            calculator: CalculatorTargetIdentity {
                session_instance: "4".repeat(32),
                task_id: 2,
                incarnation: "6".repeat(32),
            },
            nonce: "7".repeat(32),
        },
    )
}

fn recovered_wire() -> Value {
    let (notes, calculator, _) = targets();
    let mut value = wire();
    value["schema"] = "hepta.root.desktop_launch_profile.v2".into();
    value["previous_recovery"] = json!({
        "notes":{"helper":"/fixture/trill-notes-recovery","helper_sha256":"a".repeat(64),
            "state_directory":"/fixture/notes","previous_target":notes,
            "selector":{"kind":"latest_recorded_original_notes"}},
        "calculator":{"helper":"/fixture/trill-calculator-recovery","helper_sha256":"b".repeat(64),
            "state_directory":"/fixture/calculator","previous_target":calculator,
            "selector":{"kind":"latest_recorded_original_calculator"}}
    });
    value
}

#[test]
fn joint_root_fresh_and_recovery_profiles_cannot_relabel_each_other() {
    let fresh: Profile = serde_json::from_value(wire()).unwrap();
    validate_profile(&fresh, "fixture-root", false).unwrap();
    assert!(validate_profile(&fresh, "fixture-root", true).is_err());
    let recovered: Profile = serde_json::from_value(recovered_wire()).unwrap();
    validate_profile(&recovered, "fixture-root", true).unwrap();
    assert!(validate_profile(&recovered, "fixture-root", false).is_err());
    assert!(validate_profile(&recovered, "different-root", true).is_err());
    for base in [wire(), recovered_wire()] {
        let mut changed = base;
        changed["previous_recovery"] = Value::Null;
        assert!(serde_json::from_value::<Profile>(changed).is_err());
    }
    let mut changed = recovered_wire();
    changed["previous_recovery"]["calculator"] = Value::Null;
    assert!(serde_json::from_value::<Profile>(changed).is_err());
}

#[test]
fn joint_root_requires_both_exact_previous_policies_and_a_distinct_actual_pair() {
    let profile: Profile = serde_json::from_value(recovered_wire()).unwrap();
    let (notes, mut calculator, mut release) = targets();
    let previous = || RootDesktopPolicy {
        notes: &notes,
        calculator: &calculator,
        grant_lifetime_ms: 1000,
    };
    validate_recovery_policy(&profile, &previous(), &release).unwrap();
    release.calculator.session_instance = "8".repeat(32);
    assert!(validate_recovery_policy(&profile, &previous(), &release).is_err());
    release = targets().2;
    release.notes.session_instance = notes.session_instance.clone();
    release.calculator.session_instance = notes.session_instance.clone();
    assert!(validate_recovery_policy(&profile, &previous(), &release).is_err());
    calculator.incarnation = "9".repeat(32);
    assert!(
        validate_recovery_policy(
            &profile,
            &RootDesktopPolicy {
                notes: &notes,
                calculator: &calculator,
                grant_lifetime_ms: 1000
            },
            &targets().2
        )
        .is_err()
    );
}

#[test]
fn joint_root_bounds_every_saved_selector_and_original_helper_path() {
    for change in [
        "relative-helper",
        "relative-state",
        "missing-selector",
        "extra-authority",
    ] {
        let mut value = recovered_wire();
        match change {
            "relative-helper" => value["previous_recovery"]["notes"]["helper"] = "relative".into(),
            "relative-state" => {
                value["previous_recovery"]["calculator"]["state_directory"] = "relative".into()
            }
            "missing-selector" => {
                value["previous_recovery"]["notes"]
                    .as_object_mut()
                    .unwrap()
                    .remove("selector");
            }
            _ => value["previous_recovery"]["grant"] = true.into(),
        }
        match serde_json::from_value::<Profile>(value) {
            Ok(profile) => assert!(
                validate_profile(&profile, "fixture-root", true).is_err(),
                "accepted {change}"
            ),
            Err(_) => {}
        }
    }
    let mut value = recovered_wire();
    value["grant_lifetime_ms"] = 30001.into();
    let profile: Profile = serde_json::from_value(value).unwrap();
    assert!(validate_profile(&profile, "fixture-root", true).is_err());
}

use super::*;
use pretty_assertions::assert_eq;

fn descriptor(version: u8) -> serde_json::Value {
    serde_json::json!({
        "schema": format!("hepta.cpu-neuron.installed-owner-composition.v{version}"),
        "agent_id": "original-agent",
        "current_pointer": "/var/lib/original/current.json",
        "compiled_body": {"path": "/var/lib/original/body.json", "digest": "b".repeat(64)},
        "tick_provider": {"path": "/var/lib/original/tick.json", "digest": "c".repeat(64)},
        "fleet_manifest_digest": "a".repeat(64),
        "control_state_path": "/var/lib/original/control.json",
        "authority_file": "/etc/original/authority.json",
        "authority_signer_id": "original-root",
        "authority_verifying_key_hex": "d".repeat(64),
        "maximum_request_duration_ms": 1000
    })
}

#[test]
fn legacy_fixed_launch_binding_does_not_inherit_a_new_fact() -> HostResult<()> {
    for version in [2, 3] {
        let mut value = descriptor(version);
        if version == 3 {
            value["model_use_pointer"] = "/var/lib/original/model-use.json".into();
        }
        let installed: Installed = serde_json::from_value(value)?;
        assert_eq!(
            installed.launch_digest(Some(&"e".repeat(64)))?,
            digest(&"a".repeat(64))?
        );
        assert_eq!(installed.launch_digest(None)?, digest(&"a".repeat(64))?);
    }
    Ok(())
}

#[test]
fn explicit_current_launch_requires_the_original_nonzero_fact() -> HostResult<()> {
    let mut value = descriptor(4);
    value
        .as_object_mut()
        .ok_or("descriptor object")?
        .remove("fleet_manifest_digest");
    value["model_use_pointer"] = "/var/lib/original/model-use.json".into();
    value["fleet_execution_binding"] = "CurrentRootFleetExecutionV1".into();
    let installed: Installed = serde_json::from_value(value)?;
    for actual in ["e".repeat(64), "f".repeat(64)] {
        assert_eq!(installed.launch_digest(Some(&actual))?, digest(&actual)?);
    }
    assert!(installed.launch_digest(None).is_err());
    for invalid in ["", "wrong", &"0".repeat(64)] {
        assert!(installed.launch_digest(Some(invalid)).is_err());
    }
    Ok(())
}

#[test]
fn binding_modes_cannot_mix_static_claims_or_silently_widen_legacy() -> HostResult<()> {
    for version in [2, 3, 4] {
        let mut value = descriptor(version);
        value["model_use_pointer"] = "/var/lib/original/model-use.json".into();
        value["fleet_execution_binding"] = "CurrentRootFleetExecutionV1".into();
        let installed: Installed = serde_json::from_value(value)?;
        assert!(installed.launch_digest(Some(&"e".repeat(64))).is_err());
    }
    let mut value = descriptor(4);
    value["fleet_execution_binding"] = "AllowAnyCurrentExecution".into();
    assert!(serde_json::from_value::<Installed>(value).is_err());
    Ok(())
}

#[test]
fn registered_model_mode_requires_pinned_reader_and_original_current_fleet_fact() -> HostResult<()>
{
    let mut value = descriptor(5);
    value
        .as_object_mut()
        .ok_or("descriptor object")?
        .remove("fleet_manifest_digest");
    value["model_use_pointer"] = "/var/lib/original/model-use.json".into();
    value["fleet_execution_binding"] = "CurrentRootFleetExecutionV1".into();
    let absent: Installed = serde_json::from_value(value.clone())?;
    assert!(absent.launch_digest(Some(&"e".repeat(64))).is_err());
    value["model_registry"] =
        serde_json::json!({"path":"/etc/original/registry-reader.json", "digest":"f".repeat(64)});
    let installed: Installed = serde_json::from_value(value.clone())?;
    assert!(installed.launch_digest(None).is_err());
    assert_eq!(
        installed.launch_digest(Some(&"e".repeat(64)))?,
        digest(&"e".repeat(64))?
    );
    value["schema"] = "hepta.cpu-neuron.installed-owner-composition.v4".into();
    let legacy: Installed = serde_json::from_value(value)?;
    assert!(legacy.launch_digest(Some(&"e".repeat(64))).is_err());
    Ok(())
}

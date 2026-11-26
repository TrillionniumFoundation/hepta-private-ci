use super::*;

fn selected() -> RuntimeModuleSelectionV1 {
    RuntimeModuleSelectionV1 {
        module_id: "automation.taskflow".to_string(),
        topology_digest: Sha256Digest::for_bytes(b"topology"),
        selected: Some(RuntimeModuleBindingV1 {
            owner_id: "automation-platform".to_string(),
            generation: 7,
            implementation_digest: Sha256Digest::for_bytes(b"image"),
            candidate_artifact_digest: Sha256Digest::for_bytes(b"candidate"),
            state_class: "stateful".to_string(),
            dependencies: vec![],
            authoritative_domains: vec![],
            input_ports: vec![],
            output_ports: vec![],
            effect_scope: vec![],
        }),
    }
}

#[test]
fn active_and_absent_selections_round_trip_without_grant_fields() {
    let active = selected();
    let mut absent = active.clone();
    absent.selected = None;
    for expected in [active, absent] {
        let bytes = serde_json::to_vec(&expected).expect("encode");
        let actual: RuntimeModuleSelectionV1 = serde_json::from_slice(&bytes).expect("decode");
        actual.validate().expect("bounded");
        assert_eq!(actual, expected);
    }
}

#[test]
fn malformed_identity_zero_generation_and_forged_grant_are_rejected() {
    let mut value = selected();
    value.module_id = "../other-owner".to_string();
    assert!(value.validate().is_err());
    let mut value = selected();
    value.selected.as_mut().expect("selected").generation = 0;
    assert!(value.validate().is_err());
    let mut value = serde_json::to_value(selected()).expect("JSON");
    value["activation_granted"] = true.into();
    assert!(serde_json::from_value::<RuntimeModuleSelectionV1>(value).is_err());
}

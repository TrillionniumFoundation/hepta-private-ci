use super::*;
use pretty_assertions::assert_eq;

fn binding() -> RegisteredOperationalModelBindingV3 {
    let pin = Digest32::of_bytes(b"actual whole registered native source").to_string();
    RegisteredOperationalModelBindingV3 {
        purpose: "registered-successor-cpu-abstention-only.v3".into(),
        subject: "actual-enrolled-subject".into(),
        model_generation: 2,
        material_digest: pin.clone(),
        runtime_digest: pin.clone(),
        native_digest: pin.clone(),
        body_digest: pin.clone(),
        execution_profile_digest: pin.clone(),
        input_profile_digest: pin.clone(),
        objective_digest: pin.clone(),
        scope_digest: pin.clone(),
        model_artifact_id: "actual-model-v2".into(),
        predecessor_id: "actual-model-v1".into(),
        predecessor_manifest_digest: pin.clone(),
        manifest_digests: std::array::from_fn(|_| pin.clone()),
        payload_digests: std::array::from_fn(|_| pin.clone()),
        registry_binding: pin.clone(),
        registry_head: pin.clone(),
        current_witness: pin.clone(),
        current_trust: pin.clone(),
        withdrawal_scope: pin.clone(),
        withdrawal_head: pin,
        publication_operation_id: "actual-ack-operation".into(),
        authority_epoch: 2,
    }
}
#[test]
fn whole_registered_tuple_canonical_digest_binds_every_current_material_field() {
    let original = binding();
    let json = serde_json::to_value(&original).unwrap();
    assert_eq!(original, serde_json::from_value(json.clone()).unwrap());
    let original_digest = original.binding_digest().unwrap();
    for field in [
        "material_digest",
        "runtime_digest",
        "native_digest",
        "body_digest",
        "execution_profile_digest",
        "input_profile_digest",
        "objective_digest",
        "scope_digest",
        "predecessor_manifest_digest",
        "registry_binding",
        "registry_head",
        "current_witness",
        "current_trust",
        "withdrawal_scope",
        "withdrawal_head",
    ] {
        let mut changed = json.clone();
        changed[field] = serde_json::json!(Digest32::of_bytes(field.as_bytes()).to_string());
        let changed: RegisteredOperationalModelBindingV3 = serde_json::from_value(changed).unwrap();
        assert_ne!(original_digest, changed.binding_digest().unwrap());
    }
    for field in ["manifest_digests", "payload_digests"] {
        for i in 0..3 {
            let mut changed = json.clone();
            changed[field][i] = serde_json::json!(Digest32::of_bytes(&[i as u8]).to_string());
            let changed: RegisteredOperationalModelBindingV3 =
                serde_json::from_value(changed).unwrap();
            assert_ne!(original_digest, changed.binding_digest().unwrap());
        }
    }
}
#[test]
fn original_initial_purpose_partial_or_foreign_fields_cannot_be_registered_successor() {
    let mut original = binding();
    original.model_generation = 1;
    assert!(original.binding_digest().is_err());
    original.model_generation = 2;
    original.purpose = "ConservativeCpuAbstentionOnlyV1".into();
    assert!(original.binding_digest().is_err());
    let mut json = serde_json::to_value(binding()).unwrap();
    json.as_object_mut().unwrap().remove("current_witness");
    assert!(serde_json::from_value::<RegisteredOperationalModelBindingV3>(json).is_err());
    let mut json = serde_json::to_value(binding()).unwrap();
    json["authority_granted"] = serde_json::json!(true);
    assert!(serde_json::from_value::<RegisteredOperationalModelBindingV3>(json).is_err());
}

use super::*;
use codex_hepta_types::Generation;
use serde_json::json;

fn pin_json() -> serde_json::Value {
    let digest = Digest32::of_bytes(b"controlled-neural-pin").to_string();
    json!({
        "payload_digest": digest, "objective_digest": digest,
        "dataset_digest": digest, "generation": 3,
        "family_digest": digest, "execution_profile_digest": digest,
    })
}

#[test]
fn neural_raw_pin_preserves_every_family_and_parameter_commitment() {
    let raw: NeuralCognitivePinV1Raw = serde_json::from_value(pin_json()).unwrap();
    let pin = NeuralCognitivePinV1::from(raw);
    let digest = Digest32::of_bytes(b"controlled-neural-pin");
    assert_eq!(
        pin,
        NeuralCognitivePinV1 {
            payload_digest: digest,
            objective_digest: digest,
            dataset_digest: digest,
            generation: Generation::new(3).unwrap(),
            family_digest: digest,
            execution_profile_digest: digest,
        }
    );
    let mut changed = pin_json();
    changed["family_digest"] = json!(Digest32::of_bytes(b"different-family").to_string());
    let changed = NeuralCognitivePinV1::from(
        serde_json::from_value::<NeuralCognitivePinV1Raw>(changed).unwrap(),
    );
    assert_ne!(pin.compatibility_digest(), changed.compatibility_digest());
    let mut changed = pin_json();
    changed["execution_profile_digest"] =
        json!(Digest32::of_bytes(b"different-runtime").to_string());
    let changed = NeuralCognitivePinV1::from(
        serde_json::from_value::<NeuralCognitivePinV1Raw>(changed).unwrap(),
    );
    assert_ne!(pin.compatibility_digest(), changed.compatibility_digest());
}

#[test]
fn neural_raw_pin_cannot_inject_runtime_authority_or_a_tabular_pin() {
    for name in [
        "inference",
        "runtime",
        "resource_grant",
        "final_use",
        "selection_receipt",
        "artifact_digest",
        "sensor_core_digest",
    ] {
        let mut injected = pin_json();
        injected[name] = json!({"caller_selected": true});
        assert!(serde_json::from_value::<NeuralCognitivePinV1Raw>(injected).is_err());
    }
    for missing in [
        "family_digest",
        "execution_profile_digest",
        "payload_digest",
    ] {
        let mut incomplete = pin_json();
        incomplete.as_object_mut().unwrap().remove(missing);
        assert!(serde_json::from_value::<NeuralCognitivePinV1Raw>(incomplete).is_err());
    }
    let mut zero_generation = pin_json();
    zero_generation["generation"] = json!(0);
    assert!(serde_json::from_value::<NeuralCognitivePinV1Raw>(zero_generation).is_err());
    assert!(
        serde_json::from_value::<crate::cognitive_process_materials::TabularPayloadPinV1Raw>(
            pin_json()
        )
        .is_err()
    );
}

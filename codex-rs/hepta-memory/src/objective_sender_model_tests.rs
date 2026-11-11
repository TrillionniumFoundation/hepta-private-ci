use super::super::test_support::request;
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn absent_notes_reference_preserves_original_origin_bytes_and_hash_input() {
    let origin = request().origin;
    let legacy = format!(
        "{{\"agent_id\":\"{}\",\"spawn_generation\":1,\"request_id\":19,\"expected_peer_uid\":1000,\"expected_peer_pid\":4321,\"endpoint_identity\":\"/test/original-agentd.sock\"}}",
        origin.agent_id
    );
    assert_eq!(serde_json::to_string(&origin).unwrap(), legacy);
    let decoded: ObjectiveSenderOrigin = serde_json::from_str(&legacy).unwrap();
    assert!(decoded.original_notes_thread.is_none());
    assert_eq!(serde_json::to_string(&decoded).unwrap(), legacy);
}

#[test]
fn exact_original_utf8_and_whitespace_survive_structural_projection() {
    let original = request();
    let padded = format!(" {} ", original.original);
    let projected =
        ObjectiveSenderRequest::from_original(padded.clone(), original.origin.clone()).unwrap();
    assert_eq!(projected.exact_original(), padded.as_bytes());
    assert_eq!(
        projected.identity.signed_body_sha256,
        original.identity.signed_body_sha256
    );
    assert_ne!(
        projected.identity.original_sha256,
        original.identity.original_sha256
    );
    assert!(projected.original.contains("你好"));
}

#[test]
fn duplicate_unknown_truncated_or_out_of_profile_originals_are_rejected() {
    let original = request();
    let mut value: serde_json::Value = serde_json::from_str(&original.original).unwrap();
    value["body"]["unknown_authority"] = serde_json::json!(true);
    for raw in [
        serde_json::to_string(&value).unwrap(),
        original.original.replacen('{', "{\"key_epoch\":3,", 1),
        original.original[..original.original.len() - 1].to_string(),
        format!("{}\n", original.original),
        " ".repeat(MAX_ORIGINAL_BYTES + 1),
    ] {
        assert!(ObjectiveSenderRequest::from_original(raw, original.origin.clone()).is_err());
    }
    let mut wrong_origin = original.origin.clone();
    wrong_origin.spawn_generation += 1;
    assert!(matches!(
        ObjectiveSenderRequest::from_original(original.original, wrong_origin),
        Err(ObjectiveSenderInputError::Identity)
    ));
}

#[test]
fn every_signed_body_field_changes_the_retained_binding() {
    let original = request();
    let initial: serde_json::Value = serde_json::from_str(&original.original).unwrap();
    for key in [
        "run_id",
        "source_envelope_json",
        "runtime_body_digest",
        "preference_state_digest",
        "model_tuple_digest",
        "prompt_registry_digest",
        "artifact_set_digest",
    ] {
        let mut changed = initial.clone();
        changed["body"][key] = serde_json::json!(if key.ends_with("digest") {
            "66".repeat(32)
        } else {
            "changed-original".to_string()
        });
        let changed = ObjectiveSenderRequest::from_original(
            serde_json::to_string(&changed).unwrap(),
            original.origin.clone(),
        )
        .unwrap();
        assert_ne!(
            changed.identity.signed_body_sha256,
            original.identity.signed_body_sha256
        );
        assert_ne!(
            changed.identity.original_sha256,
            original.identity.original_sha256
        );
    }
    for key in ["objective_revision", "authority_epoch"] {
        let mut changed = initial.clone();
        changed["body"][key] = serde_json::json!(999);
        let changed = ObjectiveSenderRequest::from_original(
            serde_json::to_string(&changed).unwrap(),
            original.origin.clone(),
        )
        .unwrap();
        assert_ne!(
            changed.identity.signed_body_sha256,
            original.identity.signed_body_sha256
        );
    }
}

#[test]
fn observations_are_bounded_exact_data_without_an_inferred_anchor() {
    let raw = " {\"status\":\"unknown\",\"original\":\"你好\"} ";
    let observed = ObjectiveSenderObservation::from_original(
        ObjectiveSenderObservationKind::History,
        raw.to_string(),
    )
    .unwrap();
    assert_eq!(observed.exact_original(), raw.as_bytes());
    assert!(
        ObjectiveSenderObservation::from_original(
            ObjectiveSenderObservationKind::History,
            "x".to_string()
        )
        .is_err()
    );
    assert!(
        ObjectiveSenderObservation::from_original(
            ObjectiveSenderObservationKind::History,
            " ".repeat(MAX_OBSERVATION_BYTES + 1)
        )
        .is_err()
    );
}

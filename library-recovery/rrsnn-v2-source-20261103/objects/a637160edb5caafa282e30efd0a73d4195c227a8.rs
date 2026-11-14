use rrsnn_offline_replay_bridge::{Context, Envelope, Fixture};

fn fixture() -> Fixture {
    serde_json::from_str(include_str!("../fixtures/exact_replay_fixture.json"))
        .expect("recorded Python engine fixture is valid JSON")
}

fn context() -> Context {
    Context {
        upstream_source_commit: "f8c9419df6ddeb36ff8b522a50219981fb8d9345".into(),
        engine_source_sha256: "1".repeat(64),
        model_artifact_sha256: None,
        numpy_version: fixture().numpy_version,
        instance_id: "offline.fixture.1".into(),
        logical_sequence: 1,
        previous_payload_sha256: None,
    }
}

#[test]
fn recorded_python_state_and_events_roundtrip_without_float_loss() {
    let fixture = fixture();
    fixture
        .validate()
        .expect("physical and temporal fixture invariants");
    let encoded = serde_json::to_vec(&fixture).expect("encode fixture");
    let decoded: Fixture = serde_json::from_slice(&encoded).expect("decode fixture");
    assert_eq!(fixture, decoded);
    for (left, right) in fixture
        .checkpoint_at_split
        .refractory_until
        .iter()
        .zip(&decoded.checkpoint_at_split.refractory_until)
    {
        assert_eq!(left.to_bits(), right.to_bits());
    }
}

#[test]
fn complete_rng_and_pending_observations_survive_the_envelope() {
    let f = fixture();
    let envelope = Envelope::pack(
        f.checkpoint_at_split.clone(),
        context(),
        f.continuation.clone(),
    )
    .expect("pack complete replay context");
    let payload = envelope
        .unpack()
        .expect("verify payload digest and bounded schema");
    assert_eq!(payload.checkpoint, f.checkpoint_at_split);
    assert_eq!(payload.pending_inputs, f.continuation);
    assert_eq!(payload.context, context());
}

#[test]
fn tampering_and_authority_claims_are_rejected() {
    let f = fixture();
    let envelope = Envelope::pack(f.checkpoint_at_split, context(), f.continuation).unwrap();
    let original = serde_json::to_value(&envelope).unwrap();
    let mut altered = original.clone();
    altered["canonicalPayloadJson"] = serde_json::Value::String("{}".into());
    let altered: Envelope = serde_json::from_value(altered).unwrap();
    assert!(altered.unpack().is_err());
    let mut elevated = original;
    elevated["productionActivationAllowed"] = true.into();
    let elevated: Envelope = serde_json::from_value(elevated).unwrap();
    assert!(elevated.unpack().is_err());
}

#[test]
fn malformed_physical_state_and_incomplete_rng_are_rejected() {
    let original = fixture().checkpoint_at_split;
    let mut bad = original.clone();
    bad.drift.pop();
    assert!(bad.validate().is_err());
    let mut bad = original.clone();
    bad.sigma[0] = -1.;
    assert!(bad.validate().is_err());
    let mut bad = original.clone();
    bad.rng[0].state.state = "340282366920938463463374607431768211456".into();
    assert!(bad.validate().is_err());
    let mut bad = original;
    bad.rng[0].state.inc = "2".into();
    assert!(bad.validate().is_err());
}

#[test]
fn incorrect_event_counts_and_backward_inputs_are_rejected() {
    let mut bad = fixture();
    bad.expected_final.count[0] += 1;
    assert!(bad.validate().is_err());
    let mut bad = fixture();
    bad.continuation[0].time = bad.checkpoint_at_split.time - 0.1;
    assert!(bad.validate().is_err());
}

#[test]
fn duplicate_fields_and_unknown_schema_fields_fail_closed() {
    let text = serde_json::to_string(&fixture()).unwrap();
    let duplicate = text.replacen("{", "{\"schema\":\"ambiguous\",", 1);
    assert!(serde_json::from_str::<Fixture>(&duplicate).is_err());
    let extra = text.replacen("{", "{\"unsafeShortcut\":true,", 1);
    assert!(serde_json::from_str::<Fixture>(&extra).is_err());
}

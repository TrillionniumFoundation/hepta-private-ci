use super::*;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

pub(super) fn registration(temp: &TempDir) -> OrdinaryCpuRegistration {
    OrdinaryCpuRegistration::new(
        OrdinaryCpuBinding {
            subject_id: StableId::new("ordinary-host-subject").expect("subject"),
            scope_digest: Digest32::of_bytes(b"ordinary-child-only-scope"),
            policy_generation: Generation::new(1).expect("generation"),
            source_digest: Digest32::of_bytes(b"registered-test-worker-source"),
            worker_id: StableId::new("fixed-ordinary-worker").expect("worker"),
            profile_id: StableId::new("ordinary-test-profile").expect("profile"),
            observer_deadline: Duration::from_secs(8),
        },
        temp.path().join("fixed-worker"),
        vec!["fixed-argument".to_owned()],
    )
    .expect("registration")
}

pub(super) fn request(
    registration: &OrdinaryCpuRegistration,
    operation_id: &str,
) -> ProductionDispatchRequest {
    let intent = registration
        .operation(StableId::new(operation_id).expect("operation id"))
        .expect("operation");
    ProductionDispatchRequest {
        schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_owned(),
        lease_id: "original-source-lease".to_owned(),
        occurrence_key: operation_id.to_owned(),
        topic: TOPIC.to_owned(),
        payload_json: registration.payload_json().expect("payload"),
        payload_sha256: Sha256Digest::for_bytes(
            registration.payload_json().expect("payload").as_bytes(),
        ),
        idempotency_key: operation_id.to_owned(),
        operation_scope_sha256: Sha256Digest::parse(intent.scope_digest().to_string())
            .expect("scope"),
        operation_subject_id: intent.subject_id().as_str().to_owned(),
        operation_destination_id: DESTINATION.to_owned(),
        operation_semantic_sha256: Sha256Digest::parse(intent.semantic_digest().to_string())
            .expect("semantic"),
        operation_policy_generation: 1,
        expected_predecessor_sha256: None,
        operation_digest: Sha256Digest::for_bytes(b"not-an-authority-in-these-owner-controls"),
    }
}

#[test]
fn registration_rejects_unbounded_or_invalid_host_configuration() {
    let temp = TempDir::new().expect("temp");
    let program = temp.path().join("fixed-worker");
    assert!(
        OrdinaryCpuRegistration::new(
            registration(&temp).binding,
            program.clone(),
            vec!["arg".to_owned(); 9]
        )
        .is_err()
    );
    assert!(
        OrdinaryCpuRegistration::new(
            registration(&temp).binding,
            program.clone(),
            vec!["a".repeat(257)]
        )
        .is_err()
    );
    assert!(
        OrdinaryCpuRegistration::new(
            registration(&temp).binding,
            program.clone(),
            vec!["\0".to_owned()]
        )
        .is_err()
    );
    assert!(
        OrdinaryCpuRegistration::new(
            registration(&temp).binding,
            PathBuf::from("relative-worker"),
            Vec::new()
        )
        .is_err()
    );
    let mut binding = registration(&temp).binding;
    binding.observer_deadline = Duration::from_secs(9);
    assert!(OrdinaryCpuRegistration::new(binding, program.clone(), Vec::new()).is_err());
    let mut binding = registration(&temp).binding;
    binding.observer_deadline = Duration::ZERO;
    assert!(OrdinaryCpuRegistration::new(binding, program.clone(), Vec::new()).is_err());
    let mut binding = registration(&temp).binding;
    binding.scope_digest = Digest32::from_array([0; 32]);
    assert!(OrdinaryCpuRegistration::new(binding, program.clone(), Vec::new()).is_err());
    let mut binding = registration(&temp).binding;
    binding.source_digest = Digest32::from_array([0; 32]);
    assert!(OrdinaryCpuRegistration::new(binding, program, Vec::new()).is_err());
    assert!(
        OrdinaryCpuRegistration::new(
            registration(&temp).binding,
            temp.path().join("a".repeat(4097)),
            Vec::new()
        )
        .is_err()
    );
    assert!(
        OrdinaryCpuRegistration::new(
            registration(&temp).binding,
            temp.path().join("invalid\0worker"),
            Vec::new()
        )
        .is_err()
    );
    #[cfg(unix)]
    {
        use std::ffi::OsString;
        use std::os::unix::ffi::OsStringExt;
        let path = temp.path().join(OsString::from_vec(vec![0xff]));
        assert!(
            OrdinaryCpuRegistration::new(registration(&temp).binding, path, Vec::new()).is_err()
        );
    }
    #[cfg(windows)]
    {
        use std::ffi::OsString;
        use std::os::windows::ffi::OsStringExt;
        let path = temp.path().join(OsString::from_wide(&[0xd800]));
        assert!(
            OrdinaryCpuRegistration::new(registration(&temp).binding, path, Vec::new()).is_err()
        );
    }
}

#[test]
fn every_bound_intent_field_and_fixed_payload_is_recomputed() {
    let temp = TempDir::new().expect("temp");
    let registration = registration(&temp);
    let original = request(&registration, "original-effect");
    let expected = registration
        .operation(StableId::new("original-effect").expect("id"))
        .expect("intent");
    assert_eq!(registration.validate(&original).expect("exact"), expected);
    let mut variants = Vec::new();
    let mut changed = original.clone();
    changed.payload_json.push(' ');
    variants.push(changed);
    let mut changed = original.clone();
    changed.operation_subject_id = "other-subject".to_owned();
    variants.push(changed);
    let mut changed = original.clone();
    changed.operation_destination_id = "other-destination".to_owned();
    variants.push(changed);
    let mut changed = original.clone();
    changed.operation_scope_sha256 = Sha256Digest::for_bytes(b"other-scope");
    variants.push(changed);
    let mut changed = original.clone();
    changed.operation_policy_generation += 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.expected_predecessor_sha256 = Some(Sha256Digest::for_bytes(b"predecessor"));
    variants.push(changed);
    let mut changed = original.clone();
    changed.operation_semantic_sha256 = Sha256Digest::for_bytes(b"forged-semantic");
    variants.push(changed);
    let mut changed = original.clone();
    changed.idempotency_key = "other-effect".to_owned();
    variants.push(changed);
    let mut changed = original.clone();
    changed.occurrence_key = "other-effect".to_owned();
    changed.idempotency_key = changed.occurrence_key.clone();
    variants.push(changed);
    let mut changed = original.clone();
    changed.payload_sha256 = Sha256Digest::for_bytes(b"other-payload");
    variants.push(changed);
    let mut changed = original.clone();
    changed.schema_version += 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.namespace = "other-namespace".to_owned();
    variants.push(changed);
    let mut changed = original.clone();
    changed.topic = "other-topic".to_owned();
    variants.push(changed);
    let mut changed = original.clone();
    changed.lease_id.clear();
    variants.push(changed);
    let mut changed = original.clone();
    changed.lease_id = "l".repeat(129);
    variants.push(changed);
    let mut changed = original.clone();
    changed.occurrence_key.clear();
    changed.idempotency_key.clear();
    variants.push(changed);
    let mut changed = original.clone();
    changed.occurrence_key = "o".repeat(129);
    changed.idempotency_key = changed.occurrence_key.clone();
    variants.push(changed);
    for changed in variants {
        assert!(
            registration.validate(&changed).is_err(),
            "accepted tampered request: {changed:?}"
        );
    }
    for field in ["source_digest", "profile_id", "command_digest"] {
        let mut changed = original.clone();
        let mut payload: serde_json::Value =
            serde_json::from_str(&changed.payload_json).expect("payload");
        payload[field] = serde_json::Value::String("substituted-registration".to_owned());
        changed.payload_json = payload.to_string();
        changed.payload_sha256 = Sha256Digest::for_bytes(changed.payload_json.as_bytes());
        let substituted = OperationIntentV1::new(
            expected.operation_id().clone(),
            expected.subject_id().clone(),
            expected.destination_id().clone(),
            Digest32::of_bytes(changed.payload_json.as_bytes()),
            expected.scope_digest(),
            expected.policy_generation(),
            /*expected_predecessor*/ None,
        )
        .expect("internally consistent substituted intent");
        changed.operation_semantic_sha256 =
            Sha256Digest::parse(substituted.semantic_digest().to_string()).expect("semantic");
        assert!(
            registration.validate(&changed).is_err(),
            "accepted substituted registered {field}"
        );
    }
}

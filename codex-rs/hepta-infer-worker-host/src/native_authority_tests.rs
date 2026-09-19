use super::*;
use codex_hepta_types::Digest32;

fn admission() -> NativeAdmission {
    NativeAdmission {
        operation_id: "operation-r1".to_string(),
        request_id: "request-r1".to_string(),
        maximum_in_flight: 4,
        quota_reservation_digest: Digest32::of_bytes(b"quota"),
        resource_snapshot_digest: Digest32::of_bytes(b"resource-snapshot"),
        worker_assignment_digest: Digest32::of_bytes(b"worker-assignment"),
    }
}

fn binding(admission: &NativeAdmission, provider: &str, prompt: &str) -> FinalUseBinding {
    build_binding(
        admission,
        &AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
        9,
        "model",
        provider,
        Path::new("/private/agentd.sock"),
        Duration::from_secs(30),
        prompt,
        Some("memory"),
        &"a".repeat(64),
    )
    .unwrap()
}

#[test]
fn final_use_binding_changes_for_each_external_admission_dimension() {
    let base = admission();
    let expected = binding(&base, "provider", "prompt");

    let mut changed = base.clone();
    changed.quota_reservation_digest = Digest32::of_bytes(b"quota-2");
    assert_ne!(expected, binding(&changed, "provider", "prompt"));

    let mut changed = base.clone();
    changed.resource_snapshot_digest = Digest32::of_bytes(b"resource-2");
    assert_ne!(expected, binding(&changed, "provider", "prompt"));

    let mut changed = base.clone();
    changed.worker_assignment_digest = Digest32::of_bytes(b"assignment-2");
    assert_ne!(expected, binding(&changed, "provider", "prompt"));

    let mut changed = base.clone();
    changed.maximum_in_flight = 5;
    assert_ne!(expected, binding(&changed, "provider", "prompt"));

    assert_ne!(expected, binding(&base, "provider-2", "prompt"));
    assert_ne!(expected, binding(&base, "provider", "changed prompt"));
}

#[test]
fn empty_or_zero_admission_evidence_fails_closed() {
    let mut invalid = admission();
    invalid.worker_assignment_digest = Digest32::ZERO;
    assert!(
        build_binding(
            &invalid,
            &AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
            9,
            "model",
            "provider",
            Path::new("/private/agentd.sock"),
            Duration::from_secs(30),
            "prompt",
            None,
            &"a".repeat(64),
        )
        .is_err()
    );

    invalid = admission();
    invalid.operation_id.clear();
    assert!(
        build_binding(
            &invalid,
            &AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
            9,
            "model",
            "provider",
            Path::new("/private/agentd.sock"),
            Duration::from_secs(30),
            "prompt",
            None,
            &"a".repeat(64),
        )
        .is_err()
    );
}

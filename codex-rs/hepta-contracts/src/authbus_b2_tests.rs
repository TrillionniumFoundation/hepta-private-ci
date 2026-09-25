use super::*;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn subject() -> SubjectRef {
    SubjectRef::new("tenant-b2", "workspace-b2", "agent-b2", "authbusd", 11).expect("subject")
}

fn principal() -> Principal {
    Principal::new("owner:b2-qualification").expect("principal")
}

fn admission() -> AdmissionDecision {
    AdmissionDecision {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        decision_id: "decision:b2-1".to_string(),
        request_sha256: digest("request:b2"),
        subject: subject(),
        resource_sha256: digest("resource:b2"),
        policy_sha256: digest("policy:b2"),
        decision: AdmissionDecisionKind::Allow,
        reason_code: "policy_allow".to_string(),
        authority_epoch: 5,
        owner_epoch: 4,
        generation: 11,
        expected_revision: 7,
        observed_revision: 7,
        fencing_token_sha256: digest("fence:b2"),
        issued_at_unix_seconds: 2_000,
        expires_at_unix_seconds: 2_060,
        authority: false,
    }
}

fn reservation() -> QuotaReservation {
    QuotaReservation {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        reservation_id: "reservation:b2-1".to_string(),
        operation_sha256: digest("operation:b2"),
        decision_sha256: admission().digest().expect("decision digest"),
        subject: subject(),
        resource_sha256: digest("resource:b2"),
        reserved_requests: 1,
        reserved_tokens: 256,
        reserved_concurrency: 1,
        reserved_day_budget: 512,
        state: QuotaReservationState::Held,
        expected_revision: 1,
        revision: 1,
        authority_epoch: 5,
        owner_epoch: 4,
        generation: 11,
        fencing_token_sha256: digest("fence:b2"),
        not_before_unix_seconds: 2_000,
        expires_at_unix_seconds: 2_060,
        authority: false,
    }
}

fn provider_status() -> ProviderStatus {
    ProviderStatus {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        status_id: "provider-status:b2-1".to_string(),
        provider_id: "synthetic-provider".to_string(),
        resource_sha256: Some(digest("resource:b2")),
        status: ProviderStatusKind::Healthy,
        reason_code: None,
        observed_at_unix_seconds: 2_020,
        retry_after_seconds: None,
        expected_revision: 3,
        revision: 3,
        authority_epoch: 5,
        owner_epoch: 4,
        generation: 11,
        fencing_token_sha256: digest("fence:b2"),
        authority: false,
    }
}

fn operation_ref() -> OperationRef {
    OperationRef {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        operation_id: "operation:b2-1".to_string(),
        operation_kind: "acquire_permit".to_string(),
        request_sha256: digest("request:b2"),
        decision_sha256: Some(admission().digest().expect("decision digest")),
        reservation_sha256: Some(reservation().digest().expect("reservation digest")),
        subject: subject(),
        resource_sha256: digest("resource:b2"),
        authority_epoch: 5,
        owner_epoch: 4,
        generation: 11,
        fencing_token_sha256: digest("fence:b2"),
        created_at_unix_seconds: 2_000,
        expires_at_unix_seconds: 2_060,
        authority: false,
    }
}

fn attenuation() -> CapabilityAttenuation {
    CapabilityAttenuation {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        attenuation_id: "attenuation:b2-1".to_string(),
        parent_capability_sha256: digest("capability:parent"),
        subject: subject(),
        operation: "infer".to_string(),
        resource_sha256: digest("resource:b2"),
        scope_sha256: digest("scope:b2"),
        policy_sha256: digest("policy:b2"),
        audience: "inferd.local".to_string(),
        max_usage: 256,
        transferable: false,
        authority_epoch: 5,
        owner_epoch: 4,
        generation: 11,
        fencing_token_sha256: digest("fence:b2"),
        not_before_unix_seconds: 2_000,
        expires_at_unix_seconds: 2_060,
        authority: false,
    }
}

fn peer_session() -> PeerSession {
    PeerSession {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        session_id: "session:b2-1".to_string(),
        peer: principal(),
        subject: subject(),
        peer_identity_sha256: digest("peer-identity:b2"),
        session_nonce_sha256: digest("session-nonce:b2"),
        capability_sha256: digest("capability:b2"),
        trust_mode: PeerTrustMode::ServiceUid,
        authority_epoch: 5,
        owner_epoch: 4,
        generation: 11,
        fencing_token_sha256: digest("fence:b2"),
        not_before_unix_seconds: 2_000,
        expires_at_unix_seconds: 2_060,
        authority: false,
    }
}

fn clock_snapshot() -> ClockSnapshot {
    ClockSnapshot {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        snapshot_id: "clock:b2-1".to_string(),
        source: ClockSource::MonotonicWall,
        wall_time_unix_seconds: 2_020,
        monotonic_ticks: 99_001,
        uncertainty_millis: 25,
        authority_epoch: 5,
        owner_epoch: 4,
        generation: 11,
        fencing_token_sha256: digest("fence:b2"),
        authority: false,
    }
}

fn advertisement() -> ResourceAdvertisement {
    ResourceAdvertisement {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        advertisement_id: "advertisement:b2-1".to_string(),
        resource_id: "resource:b2-1".to_string(),
        owner: principal(),
        subject: Some(subject()),
        provider_id: "synthetic-provider".to_string(),
        model: Some("synthetic-model".to_string()),
        resource_sha256: digest("resource:b2"),
        quota_sha256: digest("quota:b2"),
        capability_sha256: vec![digest("capability:b2")],
        state: ResourceAdvertisementState::Available,
        revision: 2,
        authority_epoch: 5,
        owner_epoch: 4,
        generation: 11,
        fencing_token_sha256: digest("fence:b2"),
        not_before_unix_seconds: 2_000,
        expires_at_unix_seconds: 2_060,
        authority: false,
    }
}

#[test]
fn b2_contracts_validate_and_have_golden_digests() {
    let admission = admission();
    let reservation = reservation();
    let provider_status = provider_status();
    let operation = operation_ref();
    let attenuation = attenuation();
    let session = peer_session();
    let clock = clock_snapshot();
    let advertisement = advertisement();

    for result in [
        admission.validate(),
        reservation.validate(),
        provider_status.validate(),
        operation.validate(),
        attenuation.validate(),
        session.validate(),
        clock.validate(),
        advertisement.validate(),
    ] {
        result.expect("valid B2 contract");
    }

    assert_eq!(
        String::from_utf8(admission.canonical_bytes().expect("admission bytes")).expect("utf8"),
        "{\"schema_version\":1,\"decision_id\":\"decision:b2-1\",\"request_sha256\":\"5bc7b459f50727795afced881b5745758aab79a31b79648c01e1e1771e3baab7\",\"subject\":{\"tenant\":\"tenant-b2\",\"workspace\":\"workspace-b2\",\"agent\":\"agent-b2\",\"service\":\"authbusd\",\"generation\":11},\"resource_sha256\":\"00d5610a70ec6263754a6e3f5ff53f29603a9e44e9ac425e7364cf0c6c2c6fc1\",\"policy_sha256\":\"730161a3ec40b82cdaa7eb10b127598462518a8d7ef59dd786c456826b1f04ce\",\"decision\":\"allow\",\"reason_code\":\"policy_allow\",\"authority_epoch\":5,\"owner_epoch\":4,\"generation\":11,\"expected_revision\":7,\"observed_revision\":7,\"fencing_token_sha256\":\"b445d9b90d1313cc0a2f186370a0149c5d90126da9b6a54b8d0401777c7b0b04\",\"issued_at_unix_seconds\":2000,\"expires_at_unix_seconds\":2060,\"authority\":false}"
    );
    assert_eq!(
        admission.digest().expect("admission digest").as_str(),
        "420dcce104c21ee5a8c78eb36c211d8572cf8f83764581d3d52617271a82dc37"
    );
    assert_eq!(
        reservation.digest().expect("reservation digest").as_str(),
        "b3f3f707fb91bb96afeb7f4487599728fce73f46e59e221376846550f284be89"
    );
    assert_eq!(
        provider_status
            .digest()
            .expect("provider status digest")
            .as_str(),
        "59d4f1e37edb2de25c7d67db32dfd1adce75cdae194da0848c18345ed0e81f3b"
    );
    assert_eq!(
        operation.digest().expect("operation digest").as_str(),
        "601018bfb77ff20cda689654f5003ccc3114a31d8a07a554a7f4cbe9c4d75465"
    );
    assert_eq!(
        attenuation.digest().expect("attenuation digest").as_str(),
        "b97c10a6ef3b181bb39059c668bd65853780a8a1175db946df4cec0033e8fecb"
    );
    assert_eq!(
        session.digest().expect("session digest").as_str(),
        "e67cf8c85ae8c479a5b49e982c87bd18d30a6624a776cb6ff7bd650015d57927"
    );
    assert_eq!(
        clock.digest().expect("clock digest").as_str(),
        "c519babe03faf3087870bd49647079c65c7d284b6a1aad598820f1c450db2145"
    );
    assert_eq!(
        advertisement
            .digest()
            .expect("advertisement digest")
            .as_str(),
        "a7ecb77f921928ad1285a31aebc97ede2a7e57e8c9914dfd74463afa5674c7bf"
    );
}

#[test]
fn b2_wire_shapes_are_strict_and_authority_defaults_false() {
    let bytes = serde_json::to_vec(&admission()).expect("admission json");
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("json value");
    value["unknown"] = serde_json::Value::Bool(true);
    assert!(serde_json::from_value::<AdmissionDecision>(value).is_err());

    let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("json value");
    value["authority"] = serde_json::Value::Bool(true);
    let forged: AdmissionDecision = serde_json::from_value(value).expect("wire shape");
    assert!(forged.validate().is_err());

    let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("json value");
    value.as_object_mut().expect("object").remove("authority");
    let defaulted: AdmissionDecision = serde_json::from_value(value).expect("default authority");
    assert!(!defaulted.authority);
    defaulted.validate().expect("default remains fail-closed");
}

#[test]
fn b2_subject_epochs_and_fences_reject_stale_values() {
    let mut admission = admission();
    admission.generation += 1;
    assert!(admission.validate().is_err());

    let mut operation = operation_ref();
    operation.subject = SubjectRef::new("tenant-b2", "workspace-b2", "agent-b2", "authbusd", 12)
        .expect("new subject");
    assert!(operation.validate().is_err());

    let mut session = peer_session();
    session.generation += 1;
    assert!(session.validate().is_err());

    let mut forged: serde_json::Value = serde_json::to_value(peer_session()).expect("session json");
    forged["fencing_token_sha256"] = serde_json::Value::String("not-a-digest".to_string());
    let forged: PeerSession = serde_json::from_value(forged).expect("wire shape");
    assert!(forged.validate().is_err());

    let mut advertisement = advertisement();
    advertisement.authority_epoch = 0;
    assert!(advertisement.validate().is_err());
}

#[test]
fn b2_quota_reservation_cas_is_terminal_and_idempotent() {
    let held = reservation();
    assert!(
        held.transition(0, 5, QuotaReservationState::DispatchAttempted)
            .is_err()
    );
    assert!(
        held.transition(1, 4, QuotaReservationState::DispatchAttempted)
            .is_err()
    );
    let attempted = held
        .transition(1, 5, QuotaReservationState::DispatchAttempted)
        .expect("mark dispatch attempt");
    assert_eq!(attempted.revision, 2);
    assert_eq!(attempted.state, QuotaReservationState::DispatchAttempted);
    let accepted = attempted
        .transition(2, 5, QuotaReservationState::DispatchAccepted)
        .expect("accept dispatch");
    assert_eq!(accepted.revision, 3);
    assert_eq!(accepted.state, QuotaReservationState::DispatchAccepted);
    let partial = accepted
        .transition(3, 5, QuotaReservationState::PartiallyConsumed)
        .expect("record partial consumption");
    assert_eq!(partial.revision, 4);
    assert_eq!(partial.state, QuotaReservationState::PartiallyConsumed);
    assert_eq!(
        partial
            .transition(4, 5, QuotaReservationState::PartiallyConsumed)
            .expect("idempotent replay"),
        partial
    );
    assert!(
        partial
            .transition(4, 5, QuotaReservationState::Held)
            .is_err()
    );

    let uncertain = accepted
        .transition(3, 5, QuotaReservationState::Indeterminate)
        .expect("indeterminate");
    let refunded = uncertain
        .transition(4, 5, QuotaReservationState::Refunded)
        .expect("refund after reconciliation");
    assert!(
        refunded
            .transition(5, 5, QuotaReservationState::Held)
            .is_err()
    );
}

#[test]
fn b2_quota_reservation_state_set_matches_registry_v13() {
    // Keep this list in the same order as
    // AUTHBUS_CANONICAL_CONTRACT_REGISTRY_v1.yaml#/registry/status_error_registry.
    // `DispatchAttempted` is intentionally retained even though older plan
    // prose omitted it from the compact projection summary.
    let expected = [
        (QuotaReservationState::Proposed, "Proposed", false),
        (QuotaReservationState::Held, "Held", false),
        (
            QuotaReservationState::DispatchAttempted,
            "DispatchAttempted",
            false,
        ),
        (
            QuotaReservationState::DispatchAccepted,
            "DispatchAccepted",
            false,
        ),
        (
            QuotaReservationState::PartiallyConsumed,
            "PartiallyConsumed",
            false,
        ),
        (QuotaReservationState::Indeterminate, "Indeterminate", false),
        (QuotaReservationState::Released, "Released", true),
        (QuotaReservationState::Refunded, "Refunded", true),
        (QuotaReservationState::Expired, "Expired", true),
    ];

    let states = QuotaReservationState::all();
    assert_eq!(states.len(), expected.len());
    for (state, (expected_state, expected_name, expected_terminal)) in
        states.iter().zip(expected.iter())
    {
        assert_eq!(state, expected_state);
        assert_eq!(state.canonical_name(), *expected_name);
        assert_eq!(state.is_terminal(), *expected_terminal);
        assert_eq!(state.is_non_terminal(), !*expected_terminal);
        let wire = serde_json::to_string(state).expect("state wire encoding");
        assert_eq!(wire, format!("\"{expected_name}\""));
        let decoded: QuotaReservationState =
            serde_json::from_str(&wire).expect("canonical state decoding");
        assert_eq!(decoded, *state);
    }

    // Historical internal spellings are decode-only; serialization remains
    // canonical and never emits an alias.
    let aliases = [
        ("PROPOSED", QuotaReservationState::Proposed),
        ("HELD", QuotaReservationState::Held),
        (
            "DISPATCH_ATTEMPTED",
            QuotaReservationState::DispatchAttempted,
        ),
        ("DISPATCH_ACCEPTED", QuotaReservationState::DispatchAccepted),
        ("DISPATCHED", QuotaReservationState::DispatchAccepted),
        ("PARTIAL", QuotaReservationState::PartiallyConsumed),
        ("INDETERMINATE", QuotaReservationState::Indeterminate),
        ("RELEASED", QuotaReservationState::Released),
        ("REFUNDED", QuotaReservationState::Refunded),
        ("EXPIRED", QuotaReservationState::Expired),
    ];
    for (alias, expected_state) in aliases {
        let decoded: QuotaReservationState =
            serde_json::from_str(&format!("\"{alias}\"")).expect("documented decode-only alias");
        assert_eq!(decoded, expected_state);
        assert_eq!(
            serde_json::to_string(&decoded).expect("canonical alias re-encoding"),
            format!("\"{}\"", expected_state.canonical_name())
        );
    }

    // The old `Consumed` state had no canonical v1.3 meaning.  Accepting it
    // would silently conflate quota accounting with an effect terminal.
    for legacy in ["Consumed", "consumed"] {
        assert!(
            serde_json::from_str::<QuotaReservationState>(&format!("\"{legacy}\"")).is_err(),
            "obsolete state must fail closed: {legacy}"
        );
    }
}

#[test]
fn b2_quota_reservation_transition_matrix_is_closed() {
    let states = QuotaReservationState::all();
    for &from in &states {
        for &to in &states {
            let mut current = reservation();
            current.state = from;
            let result = current.transition(1, 5, to);
            assert_eq!(
                result.is_ok(),
                from.can_transition_to(to),
                "unexpected quota transition {from:?} -> {to:?}"
            );
            if from == to {
                assert_eq!(result.expect("idempotent state transition"), current);
            } else if from.can_transition_to(to) {
                let next = result.expect("allowed state transition");
                assert_eq!(next.state, to);
                assert_eq!(next.expected_revision, 1);
                assert_eq!(next.revision, 2);
            }
        }
    }

    // A post-dispatch reservation cannot skip the uncertainty hold and jump
    // directly to a release/refund/expiry outcome.
    assert!(
        !QuotaReservationState::DispatchAttempted
            .can_transition_to(QuotaReservationState::Released)
    );
    assert!(
        !QuotaReservationState::DispatchAccepted.can_transition_to(QuotaReservationState::Refunded)
    );
    assert!(
        !QuotaReservationState::PartiallyConsumed.can_transition_to(QuotaReservationState::Expired)
    );
}

#[test]
fn b2_provider_status_cas_is_fail_closed() {
    let status = provider_status();
    assert!(
        status
            .transition(2, 5, ProviderStatusKind::Degraded)
            .is_err()
    );
    assert!(
        status
            .transition(3, 4, ProviderStatusKind::Degraded)
            .is_err()
    );
    let degraded = status
        .transition(3, 5, ProviderStatusKind::Degraded)
        .expect("new provider observation");
    assert_eq!(degraded.revision, 4);
    assert_eq!(degraded.status, ProviderStatusKind::Degraded);

    let status_json = serde_json::to_string(&provider_status()).expect("status json");
    assert!(!status_json.contains("access_token"));
    assert!(!status_json.contains("refresh_token"));
    assert!(!status_json.contains("private_key"));

    let mut unknown: serde_json::Value =
        serde_json::to_value(provider_status()).expect("status json");
    unknown["unexpected"] = serde_json::Value::Bool(true);
    assert!(serde_json::from_value::<ProviderStatus>(unknown).is_err());
}

#[test]
fn b2_attenuation_clock_and_advertisement_bounds_fail_closed() {
    let mut attenuation = attenuation();
    attenuation.transferable = true;
    assert!(attenuation.validate().is_err());

    let mut clock = clock_snapshot();
    clock.uncertainty_millis = 86_400_001;
    assert!(clock.validate().is_err());

    clock.uncertainty_millis = 0;
    clock.source = ClockSource::Unknown;
    assert!(clock.validate().is_err());

    let mut advertisement = advertisement();
    advertisement.capability_sha256.clear();
    assert!(advertisement.validate().is_err());
}

#[test]
fn b2_peer_and_resource_wire_round_trip_is_secret_free() {
    let session_bytes = serde_json::to_vec(&peer_session()).expect("session json");
    let session_json = String::from_utf8(session_bytes.clone()).expect("utf8");
    assert!(!session_json.contains("access_token"));
    assert!(!session_json.contains("raw_secret"));
    assert!(!session_json.contains("private_key"));
    let session: PeerSession = serde_json::from_slice(&session_bytes).expect("session round trip");
    session.validate().expect("session valid");

    let advertisement_bytes = serde_json::to_vec(&advertisement()).expect("advertisement json");
    let advertisement: ResourceAdvertisement =
        serde_json::from_slice(&advertisement_bytes).expect("advertisement round trip");
    advertisement.validate().expect("advertisement valid");
}

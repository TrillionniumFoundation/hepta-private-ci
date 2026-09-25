use super::*;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn profile() -> BasilServiceProfile {
    BasilServiceProfile::qualification(digest("descriptor:b1")).expect("profile")
}

fn identity() -> IdentityBinding {
    let mut value = IdentityBinding {
        schema_version: AUTHBUS_B1_CONTRACT_SCHEMA_VERSION,
        binding_id: "identity:b1-1".to_string(),
        tenant_id: "tenant-b1".to_string(),
        workspace_id: "workspace-b1".to_string(),
        agent_id: "agent-b1".to_string(),
        service_id: "authbusd".to_string(),
        node_id: "node-b1".to_string(),
        generation: 7,
        launch_nonce_sha256: digest("launch:b1"),
        session_id: "session:b1".to_string(),
        operation: "Sign".to_string(),
        secret_ref_allowlist_digest: digest("secret-ref-allowlist:b1"),
        epoch: 3,
        nonce_sha256: digest("nonce:b1"),
        key_id: "key:b1".to_string(),
        capability_digest: digest("capability:b1"),
        intent_digest: digest("intent:b1"),
        transcript_digest: digest("transcript:b1"),
        audience: "authbusd.local".to_string(),
        issued_at_unix_seconds: 1_010,
        not_before_unix_seconds: 1_000,
        expires_at_unix_seconds: 1_100,
        policy_digest: digest("policy:b1"),
        hnl_attestation_digest: digest("hnl-attestation:b1"),
        service_identity_digest: digest("service-identity:b1"),
        subject_digest: digest("placeholder"),
        authority_epoch: 5,
        owner_epoch: 4,
        fencing_token_sha256: digest("fence:b1"),
        peer: IdentityPeerEvidence::LinuxPeer {
            peer_uid: 501,
            peer_gid: 20,
            peer_pid: 42,
            agentd_generation: 7,
            launch_nonce_sha256: digest("launch:b1"),
            pid_start_time_ticks: 123,
            pidfd_bound: true,
        },
        authority: false,
    };
    value.subject_digest = value.computed_subject_digest().expect("subject digest");
    value
}

fn registration() -> BasilKeyRegistration {
    BasilKeyRegistration {
        key_id: "key:b1".to_string(),
        key_epoch: 2,
        signature_alg: "ES256".to_string(),
        key_type: "P-256".to_string(),
        signer_usage_domain: "hepta.auth.sign".to_string(),
        public_key_digest: digest("public:b1"),
        backend_binding_digest: digest("backend:b1"),
    }
}

#[test]
fn b1_profile_is_exact_default_deny_and_key_generation_forbidden() {
    let profile = profile();
    profile.validate().expect("profile");
    assert_eq!(
        profile.classify_route("/basil.broker.v1.SigningService/Sign"),
        BasilRouteClass::Allowed
    );
    assert_eq!(
        profile.classify_route("/basil.broker.v1.AeadService/Decrypt"),
        BasilRouteClass::OptionalProcessBound
    );
    assert_eq!(
        profile.classify_route("/basil.broker.v1.FutureService/New"),
        BasilRouteClass::Denied
    );
    profile
        .allows_static_route("/basil.broker.v1.SigningService/Verify")
        .expect("allowed route");
    assert!(
        profile
            .allows_static_route("/basil.broker.v1.AeadService/Decrypt")
            .is_err()
    );
    assert!(
        profile
            .allows_static_route("/basil.broker.v1.FutureService/New")
            .is_err()
    );
    assert!(profile.require_registered_key(None).is_err());
    profile
        .require_registered_key(Some(&registration()))
        .expect("registered key");
}

#[test]
fn b1_profile_rejects_route_or_descriptor_tampering() {
    let mut tampered = profile();
    tampered.allowed_routes[0] = "/basil.broker.v1.SigningService/NewKey".to_string();
    assert!(tampered.validate().is_err());

    let mut tampered = profile();
    tampered.route_set_digest = digest("wrong-route-set");
    assert!(tampered.validate().is_err());

    let mut tampered = profile();
    tampered.authority = true;
    assert!(tampered.validate().is_err());
}

#[test]
fn b1_registration_requires_unambiguous_algorithm_and_backend_binding() {
    let mut tampered = registration();
    tampered.signature_alg.clear();
    assert!(tampered.validate().is_err());

    let mut tampered = registration();
    tampered.key_epoch = 0;
    assert!(tampered.validate().is_err());

    let mut valid = registration();
    valid.backend_binding_digest = digest("not-the-empty-digest");
    valid.validate().expect("digest is syntactically valid");
}

#[test]
fn b1_identity_requires_full_peer_binding_and_derived_subject_digest() {
    let identity = identity();
    identity.validate().expect("identity");
    assert_eq!(
        identity.digest().expect("identity digest").as_str().len(),
        64
    );

    let mut tampered = identity.clone();
    tampered.generation += 1;
    assert!(tampered.validate().is_err());

    let mut tampered = identity.clone();
    tampered.peer = IdentityPeerEvidence::LinuxPeer {
        peer_uid: 501,
        peer_gid: 20,
        peer_pid: 42,
        agentd_generation: 8,
        launch_nonce_sha256: digest("launch:b1"),
        pid_start_time_ticks: 123,
        pidfd_bound: true,
    };
    assert!(tampered.validate().is_err());

    let mut tampered = identity.clone();
    tampered.peer = IdentityPeerEvidence::LinuxPeer {
        peer_uid: 501,
        peer_gid: 20,
        peer_pid: 42,
        agentd_generation: 7,
        launch_nonce_sha256: digest("launch:other"),
        pid_start_time_ticks: 123,
        pidfd_bound: true,
    };
    assert!(tampered.validate().is_err());

    let mut tampered = identity.clone();
    tampered.subject_digest = digest("forged-subject");
    assert!(tampered.validate().is_err());

    let mut tampered = identity;
    tampered.peer = IdentityPeerEvidence::LinuxPeer {
        peer_uid: 501,
        peer_gid: 20,
        peer_pid: 42,
        agentd_generation: 7,
        launch_nonce_sha256: digest("launch:b1"),
        pid_start_time_ticks: 123,
        pidfd_bound: false,
    };
    assert!(tampered.validate().is_err());
}

#[test]
fn b1_identity_rejects_same_uid_and_forwarded_unknown_claims() {
    let mut tampered = identity();
    tampered.peer = IdentityPeerEvidence::SameUidOnly;
    assert!(tampered.validate().is_err());

    let mut wire = serde_json::to_value(identity()).expect("identity json");
    wire["forwarded_uid"] = serde_json::Value::String("501".to_string());
    assert!(serde_json::from_value::<IdentityBinding>(wire).is_err());

    let mut wire = serde_json::to_value(identity()).expect("identity json");
    wire["peer"]["unexpected"] = serde_json::Value::Bool(true);
    assert!(serde_json::from_value::<IdentityBinding>(wire).is_err());
}

#[test]
fn b1_identity_wire_is_strict_and_authority_is_default_false() {
    let value = serde_json::to_value(identity()).expect("identity json");
    let mut without_authority = value.clone();
    without_authority
        .as_object_mut()
        .expect("object")
        .remove("authority");
    let decoded: IdentityBinding = serde_json::from_value(without_authority).expect("default");
    assert!(!decoded.authority);
    decoded.validate().expect("default-deny identity");

    let mut forged = value;
    forged["authority"] = serde_json::Value::Bool(true);
    let forged: IdentityBinding = serde_json::from_value(forged).expect("wire shape");
    assert!(forged.validate().is_err());
}

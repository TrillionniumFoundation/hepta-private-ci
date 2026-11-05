use super::*;
use std::collections::BTreeSet;

#[test]
fn observation_never_truncates_a_complete_revocation_head_to_fit() {
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 2,
        revoked_grant_ids: (0..256)
            .map(|id| format!("{id:0128x}"))
            .collect::<BTreeSet<_>>(),
    };
    let response = ObservationResponse {
        schema_version: 1,
        operation: "runtime.authority.observation.v1",
        authority_epoch: 1,
        revocations: head.clone(),
        clock: HostAuthorityClockProjection {
            schema_version: 1,
            boot_id: "00000000-0000-0000-0000-000000000001".into(),
            anchor_boottime_ns: 1_000_000,
            anchor_unix_ms: 10_000,
            ceiling_unix_ms: 11_000,
        },
        observed_unix_ms: 10_001,
        registered_agent_id: "fixture",
        spawn_generation: 1,
    };
    assert_eq!(
        encode_bounded(&response, 16 * 1024),
        Err(HostIssuerTransportError::Unavailable)
    );
    let full: serde_json::Value =
        serde_json::from_slice(&encode_bounded(&response, 64 * 1024).unwrap()).unwrap();
    assert_eq!(full["revocations"], serde_json::to_value(head).unwrap());
}

#[test]
fn lane_decoders_reject_unknown_duplicate_and_self_selected_authority() {
    for bytes in [
        br#"{"schema_version":1,"schema_version":1,"operation":"runtime.authority.observation.v1"}"#.as_slice(),
        br#"{"schema_version":1,"operation":"runtime.authority.observation.v1","authority_epoch":1}"#.as_slice(),
    ] {
        assert!(matches!(decode::<ObservationRequest>(bytes), Err(HostIssuerTransportError::InvalidRequest)));
    }
    let valid = serde_json::to_string(&serde_json::json!({"schema_version":1,
        "operation":"runtime.agentd.production_operation", "binding":FinalUseBinding {
            subject_id:"original-owner".into(),destination_id:"no-effect".into(),scope_sha256:[2;32],request_sha256:[1;32],payload_sha256:[3;32]
        }})).unwrap();
    assert!(decode::<IssuerRequest>(valid.as_bytes()).is_ok());
    let unknown = format!("{},\"identity\":{{}}}}", valid.strip_suffix('}').unwrap());
    let duplicate = valid.replace("\"operation\":\"runtime.agentd.production_operation\"", "\"operation\":\"runtime.agentd.production_operation\",\"operation\":\"runtime.agentd.production_operation\"");
    for bytes in [unknown, duplicate] {
        assert!(matches!(
            decode::<IssuerRequest>(bytes.as_bytes()),
            Err(HostIssuerTransportError::InvalidRequest)
        ));
    }
}

#[path = "authority_host_service_root_tests.rs"]
mod root;

#[test]
fn observation_discards_a_lease_expiring_during_io_or_a_different_epoch() {
    use codex_hepta_contracts::authority_lease::AuthorityLease;
    use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
    let lease = AuthorityLease {
        schema_version: 1,
        lease_id: "original-pinned".into(),
        authority_epoch: 1,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: "original-owner".into(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: "no-effect".into(),
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        issued_at_unix_ms: 10_000,
        expires_at_unix_ms: 20_000,
    };
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    assert!(validate_observation_lease(&lease, &head, 19_999).is_ok());
    for (post_io, epoch) in [(20_000, 1), (25_000, 1), (9_999, 1), (19_999, 2)] {
        assert_eq!(
            validate_observation_lease(
                &lease,
                &FinalUseRevocations {
                    authority_epoch: epoch,
                    ..head.clone()
                },
                post_io
            )
            .unwrap_err()
            .kind(),
            io::ErrorKind::PermissionDenied
        );
    }
}

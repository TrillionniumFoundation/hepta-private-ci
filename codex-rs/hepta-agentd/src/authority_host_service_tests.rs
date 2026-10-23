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
    for bytes in [
        br#"{"schema_version":1,"operation":"runtime.authbus.objective.sign.v1","body":{},"identity":{}}"#.as_slice(),
        br#"{"schema_version":1,"operation":"runtime.authbus.objective.sign.v1","operation":"runtime.authbus.objective.sign.v1","body":{}}"#.as_slice(),
    ] {
        assert!(matches!(decode::<IssuerRequest>(bytes), Err(HostIssuerTransportError::InvalidRequest)));
    }
}

#[path = "authority_host_service_root_tests.rs"]
mod root;

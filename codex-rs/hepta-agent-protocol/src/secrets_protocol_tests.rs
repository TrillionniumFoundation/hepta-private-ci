#![allow(clippy::expect_used)]
//! Enrolled original-operation wire cannot carry caller-issued authority.
use super::*;

#[test]
fn secrets_original_methods_round_trip_and_reject_caller_authority_fields() {
    for method in [
        AgentdMethod::SecretsConsumeOriginal {
            original_id: "original".into(),
            budget_ms: 1000,
        },
        AgentdMethod::SecretsOriginalStatus {
            original_id: "original".into(),
        },
        AgentdMethod::SecretsRecoverOriginal {
            original_id: "original".into(),
        },
    ] {
        let request = AgentdRequest {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: 1,
            spawn_generation: 7,
            method,
        };
        let encoded = serde_json::to_value(&request).expect("wire request");
        assert_eq!(
            serde_json::from_value::<AgentdRequest>(encoded.clone()).expect("typed request"),
            request
        );
        for field in [
            "issuer_private_key",
            "approval",
            "caller_uid",
            "provider_token",
        ] {
            let mut untrusted = encoded.clone();
            untrusted["method"][field] = serde_json::json!("caller-controlled");
            assert!(serde_json::from_value::<AgentdRequest>(untrusted).is_err());
        }
    }
}
#[test]
fn secrets_original_observation_round_trip_rejects_secret_and_self_reported_success() {
    for observation in [
        SecretsOriginalObservation::Unknown {
            original_operation_id: "same-original".into(),
        },
        SecretsOriginalObservation::Completed {
            original_operation_id: "same-original".into(),
            reservation_id: "same-reservation".into(),
            observed_cost: 1,
            receipt_digest: "receipt-digest".into(),
        },
        SecretsOriginalObservation::Rejected {},
    ] {
        let value = serde_json::to_value(&observation).expect("wire observation");
        assert_eq!(
            serde_json::from_value::<SecretsOriginalObservation>(value.clone())
                .expect("typed observation"),
            observation
        );
        for field in ["secret", "caller_verified", "settlement_private_key"] {
            let mut untrusted = value.clone();
            untrusted[field] = serde_json::json!("caller-controlled");
            assert!(serde_json::from_value::<SecretsOriginalObservation>(untrusted).is_err());
        }
    }
}

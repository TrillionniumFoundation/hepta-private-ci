//! Wire data has no trust/owner authority. Real signatures are tested at Agentd.

use super::*;
use crate::AgentdMethod;
use crate::AgentdRequest;

fn request() -> AgentdRequest {
    AgentdRequest {
        schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 1,
        spawn_generation: 1,
        method: AgentdMethod::Q24OriginalTerminalOutcome {
            request: Box::new(Q24OriginalTerminalOutcomeRequestV1 {
                outcome_preimage_hex: "ab".repeat(MAX_Q24_OUTCOME_PREIMAGE_BYTES),
                evidence: Q24OriginalObserverEvidenceV1 {
                    evidence_id: "e".repeat(128),
                    principal_id: "p".repeat(128),
                    role: "observer".into(),
                    trust_digest: "11".repeat(32),
                    scope_digest: "22".repeat(32),
                    objective_digest: "33".repeat(32),
                    authority_epoch: 1,
                    issued_at: 1,
                    expires_at: 2,
                    payload_digest: "44".repeat(32),
                    signature_hex: "55".repeat(64),
                },
            }),
        },
    }
}

#[test]
fn q24_original_outcome_wire_fits_existing_frame_and_roundtrips() -> Result<(), serde_json::Error> {
    let original = request();
    let bytes = serde_json::to_vec(&original)?;
    assert!(bytes.len() < 64 * 1024);
    assert_eq!(serde_json::from_slice::<AgentdRequest>(&bytes)?, original);
    Ok(())
}

#[test]
fn q24_original_outcome_wire_rejects_injected_owner_trust_or_controller()
-> Result<(), serde_json::Error> {
    for (parent, key) in [
        ("/method", "owner"),
        ("/method/request", "capability"),
        ("/method/request/evidence", "root_key"),
        ("/method/request/evidence", "controller_id"),
        ("/method/request/evidence", "trust"),
    ] {
        let mut value = serde_json::to_value(request())?;
        let target = match value.pointer_mut(parent) {
            Some(target) => target,
            None => panic!("fixture parent missing: {parent}"),
        };
        target[key] = serde_json::json!("caller-supplied authority");
        assert!(
            serde_json::from_value::<AgentdRequest>(value).is_err(),
            "accepted {key}"
        );
    }
    Ok(())
}

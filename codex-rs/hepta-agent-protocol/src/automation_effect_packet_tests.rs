use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;

use super::*;

#[test]
fn packet_header_preserves_complete_intent_without_inline_hex() {
    let intent = AuthorizedEffectIntent {
        run_id: "packet-run".to_string(),
        step_id: "packet-step".to_string(),
        attempt: 1,
        operation_id: "provider.deliver".to_string(),
        subject_id: "019153a4-3088-7e03-a56a-9b1964f75ddd".to_string(),
        destination_id: "pon:fixture".to_string(),
        payload_digest: Sha256Digest::for_bytes(&vec![0x9f; 49_508]),
        final_use_scope_digest: Sha256Digest::for_bytes(b"packet-scope"),
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    };
    // A transport fixture only; cryptographic admission belongs to the owner.
    let signed_grant = SignedFinalUseGrant {
        grant: FinalUseGrant {
            schema_version: 2,
            signer_id: "security-owner".to_string(),
            authority_epoch: 1,
            grant_id: "packet-grant".to_string(),
            nonce: [7; 32],
            binding: intent.final_use_binding().expect("binding"),
            not_before_unix_ms: 1,
            expires_at_unix_ms: 1_001,
        },
        signature: vec![0x9f; 3_309],
    };
    let request = AgentdRequest::automation_execute_effect_packet_v1(
        /*request_id*/ 11,
        /*spawn_generation*/ 3,
        intent.clone(),
        /*wire_len*/ 49_508,
        signed_grant.clone(),
        "packet-command".to_string(),
    );
    let expected = serde_json::json!({
        "schema_version": AGENTD_CONTROL_SCHEMA_VERSION,
        "request_id": 11,
        "spawn_generation": 3,
        "method": {
            "type": "automation_execute_effect_packet_v1",
            "intent": intent,
            "wire_len": 49508,
            "signed_grant": signed_grant,
            "command_id": "packet-command",
        },
    });
    let header = serde_json::to_vec(&request).expect("header");
    assert!((header.len() as u64) < MAX_CONTROL_FRAME_BYTES);
    assert_eq!(
        serde_json::to_value(&request).expect("wire shape"),
        expected
    );
    assert_eq!(
        serde_json::from_slice::<AgentdRequest>(&header).expect("round trip"),
        request
    );

    let mut old_payload = expected.clone();
    old_payload["method"]["wire_payload_hex"] = serde_json::json!("00");
    assert!(serde_json::from_value::<AgentdRequest>(old_payload).is_err());
    for invalid_length in [
        serde_json::json!(-1),
        serde_json::json!(4_294_967_296_u64),
        serde_json::json!("49508"),
        serde_json::Value::Null,
    ] {
        let mut invalid = expected.clone();
        invalid["method"]["wire_len"] = invalid_length;
        assert!(serde_json::from_value::<AgentdRequest>(invalid).is_err());
    }
}

#[test]
fn packet_negotiation_never_substitutes_the_legacy_capability() {
    let local = AgentdCapabilitySet::new(vec![
        AgentdCapability::new(
            AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1,
            /*major*/ 1,
            /*minor*/ 0,
        )
        .expect("local capability"),
    ])
    .expect("local set");
    for (id, major) in [
        (AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT, 1),
        (AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1, 2),
    ] {
        let remote = AgentdCapabilitySet::new(vec![
            AgentdCapability::new(id, major, /*minor*/ 0).expect("remote capability"),
        ])
        .expect("remote set");
        assert!(
            negotiate_capabilities(&local, &remote)
                .expect("negotiation")
                .capabilities
                .is_empty()
        );
    }
    assert_eq!(
        negotiate_capabilities(&local, &local)
            .expect("packet negotiation")
            .capabilities,
        local.capabilities
    );
}

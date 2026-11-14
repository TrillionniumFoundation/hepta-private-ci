use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdRequest;
use crate::MAX_CONTROL_FRAME_BYTES;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Serialize;

// This is the wire representation before the grant was moved behind a Box.
// Comparing complete bytes also pins field ordering and string escaping.
#[derive(Serialize)]
struct PreviousRequest<'a> {
    schema_version: u32,
    request_id: u64,
    spawn_generation: u64,
    method: PreviousMethod<'a>,
}

#[derive(Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum PreviousMethod<'a> {
    AutomationExecuteEffect {
        intent: &'a AuthorizedEffectIntent,
        wire_payload_hex: &'a str,
        signed_grant: &'a SignedFinalUseGrant,
        command_id: &'a str,
    },
}

#[test]
fn boxed_effect_grant_preserves_complete_request_bytes() -> Result<(), Box<dyn std::error::Error>> {
    for (index, payload) in [
        b"{\"effect\":\"test\"}".as_slice(),
        "escaped \"grant\" \\ 中文".as_bytes(),
    ]
    .into_iter()
    .enumerate()
    {
        let intent = AuthorizedEffectIntent {
            run_id: format!("run-{index}"),
            step_id: "effect".to_string(),
            attempt: 1,
            operation_id: "provider.deliver".to_string(),
            subject_id: "019153a4-3088-7e03-a56a-9b1964f75ddd".to_string(),
            destination_id: "provider:fixture".to_string(),
            payload_digest: Sha256Digest::for_bytes(payload),
            final_use_scope_digest: Sha256Digest::for_bytes(b"scope"),
            policy_generation: 1,
            expected_predecessor_digest: None,
            dependencies: Vec::new(),
            compensation_for: None,
        };
        let signed_grant = SignedFinalUseGrant {
            grant: FinalUseGrant {
                schema_version: 1,
                signer_id: "security-owner".to_string(),
                authority_epoch: 1,
                grant_id: format!("effect-grant-{index}"),
                nonce: [7_u8; 32],
                binding: intent.final_use_binding()?,
                not_before_unix_ms: 1,
                expires_at_unix_ms: 1_001,
            },
            signature: vec![9_u8; 64],
        };
        let wire_payload_hex = payload
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let command_id = format!("effect-command-{index}");
        let previous = PreviousRequest {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: 11,
            spawn_generation: 3,
            method: PreviousMethod::AutomationExecuteEffect {
                intent: &intent,
                wire_payload_hex: &wire_payload_hex,
                signed_grant: &signed_grant,
                command_id: &command_id,
            },
        };
        let previous_bytes = serde_json::to_vec(&previous)?;
        let request = AgentdRequest::automation_execute_effect(
            11,
            3,
            intent,
            wire_payload_hex,
            signed_grant,
            command_id,
        );
        let bytes = serde_json::to_vec(&request)?;
        assert_eq!(bytes, previous_bytes);
        assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&previous_bytes)?,
            request
        );

        let mut unknown = serde_json::from_slice::<serde_json::Value>(&bytes)?;
        unknown["method"]["unexpected"] = serde_json::Value::Bool(true);
        assert!(serde_json::from_value::<AgentdRequest>(unknown).is_err());
        let mut invalid_grant = serde_json::from_slice::<serde_json::Value>(&bytes)?;
        invalid_grant["method"]["signed_grant"] = serde_json::Value::Null;
        assert!(serde_json::from_value::<AgentdRequest>(invalid_grant).is_err());
    }
    Ok(())
}

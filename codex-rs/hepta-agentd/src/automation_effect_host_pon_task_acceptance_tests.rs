//! Exercise the actual compiled native-response parser; these are response
//! fixtures, not a model-install or independent evaluation campaign.

use codex_hepta_agent_protocol::AutomationEffectTaskAcceptanceV1;
use codex_hepta_agent_protocol::ExpectedAutomationTaskAcceptanceV1;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use serde_json::Value;
use serde_json::json;

fn observation() -> Value {
    json!({"result": {
        "schema": "pon-native-exact-packet-observation-v3",
        "block": "01".repeat(32), "stored_exact": true, "block_height": 5,
        "block_chainwork_hex": format!("{}01", "00".repeat(63)),
        "active_tip": "02".repeat(32), "active_tip_height": 7,
        "active_tip_chainwork_hex": format!("{}03", "00".repeat(63)),
        "active_chain_member": true, "active_depth": 2,
        "active_work_depth_hex": format!("{}02", "00".repeat(63)),
        "active_membership_sql_lookups": 2, "active_membership_sql_budget": 1024,
        "generation": 3, "local_target_only": true, "global_absence_authority": false,
        "confirmation_authority": false, "finality_authority": false,
        "execution_authority": false, "production_activation": false,
        "accepted_task": {
            "schema_version": 1, "task_id": "03".repeat(32),
            "owner": "04".repeat(32), "provider": "05".repeat(32),
            "output_sha256": "06".repeat(32), "accept_tx_id": "07".repeat(32),
            "accepted_in_exact_packet": true, "current_status": "settled"
        }
    }})
}

fn parse(value: &Value) -> Option<crate::AutomationEffectChainObservation> {
    super::super::parse_pon_chain_observation(value, 1, &format!("{}01", "00".repeat(63)))
}

#[test]
fn native_parser_preserves_exact_settlement_and_requires_independent_effect_binding() {
    let wire = observation();
    let mut observed = parse(&wire).unwrap();
    let task: AutomationEffectTaskAcceptanceV1 =
        serde_json::from_value(wire["result"]["accepted_task"].clone()).unwrap();
    assert_eq!(observed.accepted_task, Some(task));
    let expected = ExpectedAutomationTaskAcceptanceV1 {
        effect: ProviderEffectIntent::new(
            ProviderEffectKey::for_operation("pon-task", "run-1", "submit-1").unwrap(),
            Sha256Digest::for_bytes(b"original owner-retained packet"),
        ),
        min_confirmation_depth: 1,
        min_confirmation_work_depth_hex: format!("{}01", "00".repeat(63)),
        block_id: "01".repeat(32),
        task_id: "03".repeat(32),
        owner: "04".repeat(32),
        provider: "05".repeat(32),
        output_sha256: "06".repeat(32),
        accept_tx_id: "07".repeat(32),
    };
    assert!(!observed.matches_expected_task_acceptance(&expected));
    observed.provider_effect_key = Some(expected.effect.key.as_str().to_owned());
    observed.payload_sha256 = Some(expected.effect.payload_sha256.as_str().to_owned());
    assert!(observed.matches_expected_task_acceptance(&expected));
    let response =
        crate::AgentdPayload::AutomationEffectReconcile(crate::AutomationEffectReconcileSnapshot {
            state: crate::AutomationEffectReconcileState::Terminal,
            effect: None,
            chain: Some(Box::new(observed.clone())),
        });
    let encoded = serde_json::to_vec(&response).unwrap();
    let decoded: crate::AgentdPayload = serde_json::from_slice(&encoded).unwrap();
    assert_eq!(decoded, response);
    let crate::AgentdPayload::AutomationEffectReconcile(snapshot) = decoded else {
        panic!("task observation lost its response owner");
    };
    assert!(
        snapshot
            .chain
            .unwrap()
            .matches_expected_task_acceptance(&expected)
    );
    for field in [
        "task_id",
        "owner",
        "provider",
        "output_sha256",
        "accept_tx_id",
    ] {
        let mut other = wire.clone();
        other["result"]["accepted_task"][field] = json!("11".repeat(32));
        let mut other = parse(&other).unwrap();
        other.provider_effect_key = observed.provider_effect_key.clone();
        other.payload_sha256 = observed.payload_sha256.clone();
        assert!(!other.matches_expected_task_acceptance(&expected));
    }
}

#[test]
fn native_parser_rejects_malformed_or_inactive_task_claims_without_inventing_acceptance() {
    let wire = observation();
    for (field, value) in [
        ("schema_version", json!(2)),
        ("task_id", json!("00".repeat(32))),
        ("owner", json!("AB".repeat(32))),
        ("provider", json!("a".repeat(4096))),
        ("accepted_in_exact_packet", json!(false)),
        ("current_status", json!("receipt")),
        ("unexpected", json!(true)),
    ] {
        let mut other = wire.clone();
        other["result"]["accepted_task"][field] = value;
        assert!(parse(&other).is_none());
    }
    let mut missing = wire.clone();
    missing["result"]["accepted_task"]
        .as_object_mut()
        .unwrap()
        .remove("accept_tx_id");
    assert!(parse(&missing).is_none());
    let mut inactive = wire.clone();
    inactive["result"]["active_chain_member"] = json!(false);
    inactive["result"]["active_depth"] = Value::Null;
    inactive["result"]["active_work_depth_hex"] = Value::Null;
    assert!(parse(&inactive).is_none());
    inactive["result"]["accepted_task"] = Value::Null;
    assert!(parse(&inactive).unwrap().accepted_task.is_none());
    let mut historical = wire;
    historical["result"]
        .as_object_mut()
        .unwrap()
        .remove("accepted_task");
    assert!(parse(&historical).unwrap().accepted_task.is_none());
}

//! Captured native genesis output and forged-shape controls for the consumer.
//! Raw JSON: Chain 04be5f02c84cf5cb626a53f34bc03a5bd6ff5137, ELF SHA256
//! 095458755051afd137478145a42b5edb94ee32587837e4723931317900a955d9.
//! Capture SHA256 460cefbc8d3cf559ba08ff3ada90652d930ef1e06d039b7cb6b1e11f53ffb076.
//! This remains a local observation; it grants no effect or global absence authority.

use super::parse;
use serde_json::Value;
use serde_json::json;

const GENESIS_ABSENT_OBSERVATION: &str = concat!(
    r#"{"clock_scope":"local-wall","production_activation":false,"result":{"accepted_task":null,"active_chain_member":false,"active_depth":null,"active_membership_sql_budget":1024,"active_membership_sql_lookups":null,"active_tip":"2d8dd8fb0b1673e65dbe05cca2a55c7d7d35d14c49e9e597a13f9e0b02a544ac","active_tip_chainwork_hex":"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000","active_tip_height":0,"active_work_depth_hex":null,"block":"9d74d5c97e79cecdaddf9bcd3d5b90471a4466db47dc7db6598d3cf78c6769fb","block_chainwork_hex":null,"block_height":null,"confirmation_authority":false,"execution_authority":false,"finality_authority":false,"generation":0,"global_absence_authority":false,"local_target_only":true,"production_activation":false,"schema":"pon-native-exact-packet-observation-v3","stored_exact":false}}"#,
    "\n"
);

#[test]
fn pon_real_genesis_zero_observation_is_local_absence_only() {
    let value: Value = serde_json::from_str(GENESIS_ABSENT_OBSERVATION).unwrap();
    let observation = parse(&value).expect("native fresh-genesis absence");
    assert_eq!(
        observation,
        crate::AutomationEffectChainObservation {
            schema_version: codex_hepta_agent_protocol::AUTOMATION_EFFECT_CHAIN_OBSERVATION_VERSION,
            block_id: "9d74d5c97e79cecdaddf9bcd3d5b90471a4466db47dc7db6598d3cf78c6769fb".into(),
            stored_exact: false,
            block_height: None,
            block_chainwork_hex: None,
            active_tip: "2d8dd8fb0b1673e65dbe05cca2a55c7d7d35d14c49e9e597a13f9e0b02a544ac".into(),
            active_tip_height: 0,
            active_tip_chainwork_hex: "00".repeat(64),
            active_chain_member: false,
            active_depth: None,
            active_work_depth_hex: None,
            active_membership_sql_lookups: None,
            active_membership_sql_budget: 1024,
            confirmation_policy_min_depth: 1,
            confirmation_policy_min_work_depth_hex: format!("{}01", "00".repeat(63)),
            confirmation_policy_satisfied: false,
            provider_effect_key: None,
            payload_sha256: None,
            accepted_task: None,
            owner_generation: 0,
            local_target_only: true,
            global_absence_authority: false,
            confirmation_authority: false,
            finality_authority: false,
            execution_authority: false,
        }
    );
}

#[test]
fn pon_zero_generation_rejects_forged_head_storage_membership_and_task_fields() {
    let value: Value = serde_json::from_str(GENESIS_ABSENT_OBSERVATION).unwrap();
    for (field, forged) in [
        ("active_tip_height", json!(1)),
        (
            "active_tip_chainwork_hex",
            json!(format!("{}01", "00".repeat(63))),
        ),
        ("stored_exact", json!(true)),
        ("block_height", json!(0)),
        ("block_chainwork_hex", json!("00".repeat(64))),
        ("active_chain_member", json!(true)),
        ("active_depth", json!(0)),
        ("active_work_depth_hex", json!("00".repeat(64))),
        ("active_membership_sql_lookups", json!(2)),
        ("accepted_task", json!({})),
        ("global_absence_authority", json!(true)),
        ("confirmation_authority", json!(true)),
        ("finality_authority", json!(true)),
        ("execution_authority", json!(true)),
        ("production_activation", json!(true)),
    ] {
        let mut changed = value.clone();
        changed["result"][field] = forged;
        assert!(parse(&changed).is_none(), "forged {field} accepted");
    }
    let mut missing_task_field = value;
    missing_task_field["result"]
        .as_object_mut()
        .unwrap()
        .remove("accepted_task");
    assert!(parse(&missing_task_field).is_none());
}

#[test]
fn pon_zero_generation_cannot_claim_a_consistent_stored_genesis_packet() {
    let mut value: Value = serde_json::from_str(GENESIS_ABSENT_OBSERVATION).unwrap();
    // These membership fields agree with each other, but the native genesis
    // sentinel has no packet body. Generation zero cannot acknowledge a send.
    value["result"]["block"] = value["result"]["active_tip"].clone();
    value["result"]["stored_exact"] = json!(true);
    value["result"]["block_height"] = json!(0);
    value["result"]["block_chainwork_hex"] = json!("00".repeat(64));
    value["result"]["active_chain_member"] = json!(true);
    value["result"]["active_depth"] = json!(0);
    value["result"]["active_work_depth_hex"] = json!("00".repeat(64));
    value["result"]["active_membership_sql_lookups"] = json!(2);
    assert!(parse(&value).is_none());
}

use super::parse_pon_chain_observation;
use crate::AutomationAcceptedTaskObservation;
use serde_json::json;

#[test]
fn accepted_task_requires_the_exact_active_settled_observation() {
    let task = AutomationAcceptedTaskObservation {
        schema_version: 1,
        task_id: "11".repeat(32),
        owner: "22".repeat(32),
        provider: "33".repeat(32),
        output_sha256: "44".repeat(32),
        accept_tx_id: "55".repeat(32),
        accepted_in_exact_packet: true,
        current_status: "settled".to_owned(),
    };
    let work = format!("{}01", "00".repeat(63));
    let value = json!({"result": {
        "schema": "pon-native-exact-packet-observation-v3",
        "block": "66".repeat(32), "stored_exact": true, "block_height": 7,
        "block_chainwork_hex": work,
        "active_tip": "77".repeat(32), "active_tip_height": 9,
        "active_tip_chainwork_hex": format!("{}03", "00".repeat(63)),
        "active_chain_member": true, "active_depth": 2,
        "active_work_depth_hex": format!("{}02", "00".repeat(63)),
        "active_membership_sql_lookups": 2, "active_membership_sql_budget": 1024,
        "generation": 9, "local_target_only": true, "global_absence_authority": false,
        "confirmation_authority": false, "finality_authority": false,
        "execution_authority": false, "production_activation": false,
        "accepted_task": task,
    }});
    let observed = parse_pon_chain_observation(&value, 2, &work).expect("valid observation");
    assert_eq!(observed.accepted_task, Some(task));

    let mut reorg = value.clone();
    reorg["result"]["active_chain_member"] = json!(false);
    reorg["result"]["active_depth"] = json!(null);
    reorg["result"]["active_work_depth_hex"] = json!(null);
    assert!(parse_pon_chain_observation(&reorg, 2, &work).is_none());
    reorg["result"]["accepted_task"] = json!(null);
    let reorg = parse_pon_chain_observation(&reorg, 2, &work).expect("valid reorg");
    assert_eq!(reorg.accepted_task, None);
    assert!(!reorg.confirmation_policy_satisfied);

    for (field, invalid) in [
        ("schema_version", json!(2)),
        ("accepted_in_exact_packet", json!(false)),
        ("current_status", json!("receipt")),
        ("output_sha256", json!("00".repeat(32))),
        ("provider", json!("AA".repeat(32))),
        ("accept_tx_id", json!("55")),
        ("authority", json!(true)),
    ] {
        let mut invalid_value = value.clone();
        invalid_value["result"]["accepted_task"][field] = invalid;
        assert!(
            parse_pon_chain_observation(&invalid_value, 2, &work).is_none(),
            "{field}"
        );
    }
}
